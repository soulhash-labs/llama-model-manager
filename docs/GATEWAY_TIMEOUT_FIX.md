# Fix: LMM Gateway 300s Timeout Causing OpenCode Session Termination

## Problem

OpenCode sessions were terminating after ~5 minutes with a `-300` negative remaining time error. The root cause was a **300s hard timeout** in the GlyphOS-routed gateway path that killed long-running sessions before opencode's configured timeout (30 min / 2 hours) could take effect.

## Root Cause Chain

```
OpenCode (1800000ms balanced preset) → LMM Gateway (300s hard timeout) → llama.cpp
```

When the model generated for more than 300 seconds, the gateway cut the connection. By the time opencode detected this and tried to continue, its internal deadline had already passed, resulting in the `-300` negative remaining time.

## Timeout Architecture

There are **two distinct timeout paths** in the system. Understanding which one applies is critical:

### Path A: GlyphOS-Routed Gateway (OpenCode's default path)

```
UI → defaults.env → bin/llama-model → GLYPHOS env → GlyphOS create_configured_clients() → LlamaCppClient
```

This is the path used when `LLAMA_MODEL_HARNESS_MODE=routed` (the default). The gateway imports `create_configured_clients()` from `integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py`, which creates `LlamaCppClient` instances.

### Path B: Direct Provider Registry (non-routed)

```
LMM_GATEWAY_TIMEOUT_SECONDS → lmm_providers.py create_default_registry() → LlamaCppProvider
```

This is used by the standalone provider registry, not by the GlyphOS-routed gateway.

### Timeout Variable Mapping

| Variable | Used By | Default | Notes |
|----------|---------|---------|-------|
| `LMM_GATEWAY_TIMEOUT_SECONDS` | UI field, `lmm_providers.py`, `bin/llama-model` fallback | 3600 | **Source of truth** — user-configurable via UI |
| `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS` | `bin/llama-model` shell env | 3600 (or `LMM_GATEWAY_TIMEOUT_SECONDS`) | Cascades from UI value |
| `GLYPHOS_LLAMACPP_TIMEOUT` | `create_configured_clients()` (GlyphOS path) | 3600 | Set by `bin/llama-model` at gateway launch |
| `LLAMA_CPP_STREAM_TIMEOUT` | `LlamaCppClient` direct instantiation | 3600 | Only used when client is created without explicit timeout |

### Full Chain (GlyphOS-Routed Path)

1. **UI field** `LMM_GATEWAY_TIMEOUT_SECONDS` → saved to `defaults.env` via `/api/defaults/save`
2. **`bin/llama-model:111-114`** → sources `defaults.env`, making `LMM_GATEWAY_TIMEOUT_SECONDS` available in env
3. **`bin/llama-model:62`** → `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS="${GLYPHOS_LLAMACPP_TIMEOUT_SECONDS:-${LMM_GATEWAY_TIMEOUT_SECONDS:-3600}}"`
   - Priority: explicit `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS` → `LMM_GATEWAY_TIMEOUT_SECONDS` (from defaults.env) → `3600` fallback
4. **`bin/llama-model:4413`** → `GLYPHOS_LLAMACPP_TIMEOUT="$GLYPHOS_LLAMACPP_TIMEOUT_SECONDS"` → passed to gateway process
5. **`scripts/glyphos_openai_gateway.py:680-684`** → `create_router()` calls `create_configured_clients()`
6. **`api_client.py:381-386`** → reads `GLYPHOS_LLAMACPP_TIMEOUT` env, default `"3600"` (was `"300"`)
7. **`api_client.py:393`** → `LlamaCppClient(base_url=..., model=..., timeout=llama_timeout)` — explicit timeout overrides class default

## Fix Summary

Bumped the default gateway timeout from **300s (5 min) → 3600s (1 hour)** across all layers and exposed it in the UI for user configuration.

### Files Changed

| File | Change |
|------|--------|
| `bin/llama-model:62` | Chained fallback: `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS="${GLYPHOS_LLAMACPP_TIMEOUT_SECONDS:-${LMM_GATEWAY_TIMEOUT_SECONDS:-3600}}"` |
| `bin/llama-model:3972` | `sync-glyphos` inline default: `300` → `3600` |
| `scripts/lmm_providers.py:100` | `LlamaCppProvider.__init__` default: `timeout: float = 300.0` → `3600.0` |
| `scripts/lmm_providers.py:286` | `create_default_registry` env default: `"300"` → `"3600"` |
| `integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py:383` | `create_configured_clients` default: `"300"` → `"3600"` |
| `integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py:412` | Lane timeout defaults: `"300"` → `"3600"` |
| `integrations/public-glyphos-ai-compute/glyphos_ai/config/default.yaml:9` | YAML config timeout: `300` → `3600` |
| `integrations/public-glyphos-ai-compute/config/default.yaml:9` | YAML config timeout: `300` → `3600` |
| `config/defaults.env.example:42` | `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS`: `300` → `3600` |
| `web/index.html:550-553` | **New UI field**: "Gateway Timeout (s)" input |
| `web/app.js:1568` | **Render** new field in `renderDefaults()` |
| `web/app.js:1725` | **Collect** new field in `collectDefaultsPayload()` |
| `web/app.py:42` | Added `LMM_GATEWAY_TIMEOUT_SECONDS` to `KNOWN_DEFAULT_KEYS` |

### New UI Field

**Location**: Global Defaults panel (after SSE Heartbeat field)
- **Label**: Gateway Timeout (s)
- **Env var**: `LMM_GATEWAY_TIMEOUT_SECONDS`
- **Placeholder**: `3600`
- **Description**: "Max time gateway waits for llama.cpp before aborting. Default 3600 (1 hour); raise for long sessions."

## Verification

- ✅ 153/153 Python contract tests pass
- ✅ All shell scripts syntax valid
- ✅ All timeout defaults consistent at 3600 across both paths
- ✅ UI field cascades correctly: `LMM_GATEWAY_TIMEOUT_SECONDS` → `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS` → `GLYPHOS_LLAMACPP_TIMEOUT` → `LlamaCppClient`
- ✅ YAML default configs updated to 3600

## Impact

- Sessions can now run up to **1 hour** by default (previously 5 minutes)
- Users can configure the timeout via the UI for even longer sessions
- Aligns with opencode `balanced` preset (30 min) and `long-run` preset (2 hours)
- No breaking changes — existing `GLYPHOS_LLAMACPP_TIMEOUT_SECONDS` env var takes priority over UI value
