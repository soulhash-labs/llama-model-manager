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

## Using an Existing llama.cpp Installation

If you already have a llama.cpp build on the target machine and want LMM to use it instead of building its own:

1. **Pin the binary**: Edit `~/.config/llama-server/defaults.env`:
   ```env
   LLAMA_SERVER_BIN=/path/to/your/existing/llama-server
   ```
   LMM's `probe_server_binary()` picks up explicit paths as Priority 1, and the user-pin guard prevents the installer/runtime from overwriting it.

2. **If your existing build uses shared libraries** (`libllama*.so*` not in standard system paths), add:
   ```env
   LD_LIBRARY_PATH=/path/to/llama.cpp/build-dir:${LD_LIBRARY_PATH:-}
   ```
   `defaults.env` is sourced at startup, so the `setsid` launch inherits it.

3. **Alternative — wrapper script** (cleaner, no env vars): Create a one-line wrapper:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   export LD_LIBRARY_PATH="$SCRIPT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
   exec "$SCRIPT_DIR/llama-server.bin" "$@"
   ```
   Place it alongside your real binary (renamed to `llama-server.bin`), then point `LLAMA_SERVER_BIN` at the wrapper. This is the same pattern LMM uses for its own bundled runtime.

4. **Verify**:
   ```bash
   llama-model doctor
   ```
   The doctor output should show `source: configured` or `source: external` for the binary path you set.

---

## How Reinstall Corrects Previous Issues

Re-running the installer (`curl -fsSL https://soulhash.ai/install_lmm.sh | sh`) on a machine with a prior buggy installation:

| Previous Bug | How Reinstall Fixes It |
|-------------|----------------------|
| **Missing shared libs** (`libllama-common.so.0 not found`) | `copy_runtime_bundle_files()` now searches the CMake build root (`build_dir/`) and `lib/` subdirectory — not just `build_dir/bin/` — so `.so` files are copied alongside `llama-server.bin` and the wrapper's `LD_LIBRARY_PATH` resolves them. |
| **Runtime clobber** (validated build replaced by prebuilt `$ROOT_DIR/runtime`) | Installer now uses no-clobber merge instead of `rm -rf`+`cp -a`. Just-built host binaries are preserved. |
| **User pins overwritten** (`LLAMA_SERVER_BIN` silently replaced) | `persist_selected_runtime()` now checks if the existing value points outside the managed runtime root. If so, it warns and preserves the pin. |
| **Doctor mutates config** (diagnostic command writes to `defaults.env`) | `persist_selected_runtime` removed from `probe_server_binary()`; persistence only happens on explicit `start`/`build-runtime`/`persist-runtime` actions. |
| **Stale `--chat-templateFile` flags** crash startup | `normalize_deprecated_llama_flags()` rewrites them at registry-write and preflight; `classify_startup_log_text()` detects unsupported CLI args. |

After reinstall:
- **Existing `models.tsv`** is migrated with a timestamped backup (deprecated flags are rewritten).
- **Existing `defaults.env`** is preserved; the user-pin guard ensures your `LLAMA_SERVER_BIN` is not overwritten.
- **Existing runtime directory** is overlaid (not replaced) so previously built host binaries survive.

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
| `invalid argument: --chat-templateFile` | Deprecated flag in models.tsv | Run install.sh migration or replace with `--chat-template-file` |
| `error while loading shared libraries: libllama-common.so.0` | `.so` files not copied to bundle dir by old installer | Reinstall LMM (fixed in current `copy_runtime_bundle_files()`) or set `LD_LIBRARY_PATH` in `defaults.env` |
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
