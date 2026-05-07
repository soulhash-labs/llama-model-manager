# LMM Fresh Install — Agent Runbook

## Architecture

```
HARNESS (OpenCode)
  ├── llamacpp      → 127.0.0.1:4010  → LMM Gateway + GlyphOS (full)
  ├── llamacpp_fast → 127.0.0.1:4011  → LMM Gateway + GlyphOS (fast, planned)
  └── llama.cpp     → 127.0.0.1:8081  → raw backend (internal only)
```

- **4010** = full GlyphOS pipeline (routed context, enrichment, routing)
- **4011** = fast GlyphOS lane (planned — GlyphOS-backed, lower latency)
- **8081** = raw llama.cpp, not user-facing long-term

Policy: local-first by default. Cloud use is explicit human choice, not hidden fallback.

---

## Phase A — LMM Install

```bash
curl -fsSL https://soulhash.ai/install_lmm.sh | sh
```

Verify:

| Check | Command |
|-------|---------|
| binary exists | `command -v llama-model` |
| defaults file | `~/.config/llama-server/defaults.env` |
| models registry | `~/.config/llama-server/models.tsv` |
| runtime exists | `ls ~/.local/share/llama-model-manager/runtime/llama-server/` |
| models directory | `~/models/` |
| doctor | `llama-model doctor` |

On errors, inspect: `~/models/llama-server.log`, `~/.local/state/llama-server/`.

---

## Phase B — OpenCode Install

```bash
curl -fsSL https://opencode.ai/install | bash
opencode --version
opencode models --refresh
```

Verify: `~/.config/opencode/` exists, model refresh completes.

---

## Phase C — oh-my-openagent Install

```bash
curl -s https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/installation.md
```

- Collect subscription answers from user.
- Install Bun if needed: `curl -fsSL https://bun.sh/install | bash`
- Run installer with user's flags + `--skip-auth`.
- Verify:

```bash
bun x oh-my-opencode doctor
opencode models --refresh
```

Expected files: `~/.config/opencode/opencode.json`, `~/.config/opencode/oh-my-openagent.json`.

---

## Phase D — Local-First Provider Setup

Ensure `opencode.json` has:

```json
{
  "provider": {
    "llamacpp": { "baseUrl": "http://127.0.0.1:4010/v1", "model": "llamacpp/<model>" },
    "llamacpp_direct": { "baseUrl": "http://127.0.0.1:8081/v1", "model": "llamacpp_direct/<model>" }
  },
  "model": "llamacpp/<model>"
}
```

Verify endpoints respond:

```bash
curl -s http://127.0.0.1:4010/v1/models
curl -s http://127.0.0.1:8081/v1/models
```

Refresh OpenCode catalog after changes.

---

## Phase E — Timeout Mitigation

Set explicit values in `~/.config/llama-server/defaults.env`:

```env
LLAMA_CPP_STREAM_TIMEOUT=7200
LMM_GATEWAY_SSE_HEARTBEAT_SECONDS=2
LMM_GATEWAY_TIMEOUT_SECONDS=7200
LLAMA_MODEL_HARNESS_MODE=routed
```

Restart: `llama-model gateway restart`

Measure TTFB:

```bash
# Routed 4010
time curl -s -N http://127.0.0.1:4010/v1/chat/completions \
  -d '{"model":"<model>","messages":[{"role":"user","content":"hi"}],"stream":true}' >/dev/null

# Direct 8081
time curl -s -N http://127.0.0.1:8081/v1/chat/completions \
  -d '{"model":"<model>","messages":[{"role":"user","content":"hi"}],"stream":true}' >/dev/null
```

---

## Phase F — Model Catalog Validation

```bash
opencode models --refresh
```

Compare visible model IDs against agent config in `oh-my-openagent.json`. Replace any missing `openai/*` or unavailable IDs with local `llamacpp/...` or catalog-safe `opencode/*` models.

---

## Common Failure Patterns

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `invalid argument: --chat-templateFile` | Deprecated flag in models.tsv | Replace with `--chat-template-file` |
| `SSE read timed out` | Pre-stream enrichment too slow | Set explicit timeouts, use direct path for diagnosis |
| `Model not found: openai/*` | oh-my-openagent references unavailable models | Normalize to live catalog IDs |
| `EBADENGINE` | Node version mismatch | Install Node 22+ via nvm/fnm |

---

## Key Files

| Path | Purpose |
|------|---------|
| `~/.config/llama-server/defaults.env` | LMM runtime defaults |
| `~/.config/llama-server/models.tsv` | Model registry |
| `~/.config/opencode/opencode.json` | OpenCode providers |
| `~/.config/opencode/oh-my-openagent.json` | Agent catalog |
| `~/.glyphos/config.yaml` | GlyphOS config |
| `~/models/llama-server.log` | llama.cpp logs |
| `~/models/lmm-gateway.log` | Gateway logs |

---

## Agent Musts

- Do NOT assume installer-intended model IDs are present — validate against live catalog.
- Do NOT keep silent cloud fallbacks when policy is local-first.
- Do NOT confuse shipped defaults with active runtime config.
- Do NOT treat `8081` as the future user-facing path if GlyphOS is required.
- Do NOT combine timeout stabilization and provider-neutral streaming into one change.
