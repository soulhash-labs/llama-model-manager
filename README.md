# Llama Model Manager

**by soulhash.ai**

## The engine room for local AI

llama-model-manager is a production-grade operations dashboard for `llama.cpp` and GlyphOS™ AI Compute. It turns local LLM inference from a fragile CLI experiment into a resilient, browser-first control surface.

If you're running Claude Code, OpenClaw, or opencode, this is where your stability lives.

![Dashboard overview](docs/screenshots/dashboard-overview.png)

---

## One-line install

```bash
curl -fsSL https://soulhash.ai/install_lmm.sh | sh
```

Then get started:

```bash
llama-model-web
llama-model list
llama-model doctor
```

Or install from a local checkout:

```bash
./install.sh
```

No root access. No silent compilation. Installs to `~/.local/` and asks before building anything.

---

## What it does

| Capability | What you get |
|------------|--------------|
| Model management | Discover, register, and hot-swap GGUF models from a local registry |
| Runtime control | Real-time tuning of context limits, GPU offload, batch sizes, threads, health metrics, and guarded startup auto-fit |
| AI routing | Route workloads across local `llama.cpp` and cloud providers (OpenAI, Anthropic, xAI) with intelligent fallback |
| Context intelligence | Indexed project search (FTS5), MCP bridge for context injection, Ψ Glyph Encoding for context compression |
| Observability | Telemetry, doctor diagnostics, run records, and dashboard health cards |
| Dev tool integration | CLI wrappers, desktop launchers, systemd background service, and coding environment sync |

## What ships

| Component | Purpose |
|-----------|---------|
| `bin/llama-model` | CLI for registry management, switching, restart, discovery, and diagnostics |
| `bin/llama-model-web` | Browser dashboard launcher |
| `bin/llama-model-gui` | Desktop launcher (prefers web, falls back to Zenity) |
| `scripts/build-llama-server.sh` | Fetches and compiles a host-specific `llama.cpp` runtime |
| `integrations/public-glyphos-ai-compute/` | Bundled public GlyphOS AI Compute lane |
| `integrations/context-mode-mcp/` | Optional Context Mode MCP package for indexed context and lifecycle checks |
| `web/` | Browser dashboard assets and Python server |
| `config/HELP.txt` | End-user help text |
| `install.sh` | Local installer for user-space deployment |

---

## Key features

### 🔱 GlyphOS AI Compute pipeline

GlyphOS AI Compute is bundled as a public local integration lane. It turns glyph state into model-ready prompts and routes requests through the same local `llama.cpp` endpoint managed by Llama Model Manager.

![Animated demo showing a verbose local AI request being converted into compact GlyphOS tokens, reducing the displayed payload by 60–90%, then routing through a local llama.cpp endpoint at 127.0.0.1:8081/v1. The final frame reads: Stay local. Stay private. Stay fast.](docs/branding/glyphos-encoding-demo.gif)

- **Ψ Encoding** — compresses structured context payloads (GE1-JSON, GE1-LINES) to reduce token usage in long-context workflows
- **Adaptive routing** — automatically routes requests based on psi coherence, action complexity, and context quality
- **Local-first guarantee** — all local traffic goes through the unified GlyphOS pipeline; cloud is only used when local is unavailable
- **Cloud provider control** — master toggle (`GLYPHOS_CLOUD_ENABLED`), per-provider toggles, xAI-first default ordering, and config.yaml API key support

Terran sustained a continuous 8h 59m coding session using GlyphOS AI Compute routed through local LMM-managed `llama.cpp`: `Qwen3.5-9B-Q8_0.gguf`, context 128000, parallel 1. No fatal session drops. Reference: [Terran GlyphOS Long-Run Validation](docs/TERRAN-GLYPHOS-LONG-RUN-VALIDATION.md)

### 🧠 Context-MCP integration

![Animated demo showing the sovereignty bridge: Context Mode MCP indexes project files, retrieves relevant snippets, and injects them into prompts before GlyphOS routing.](docs/branding/sovereignty-bridge.gif)

- **Project indexing** — auto-indexes project files into an FTS5 SQLite database for fast full-text search
- **Context injection** — searches project context and injects relevant snippets into prompts before routing
- **Context quality scoring** — 0.0–1.0 score based on result count, search strategy quality, degradation status, and index recency
- **Graceful fallback** — handles empty, degraded, stale, and error context states without breaking the request

### 📦 Installation and portability

- **One-line install** — `curl -fsSL https://soulhash.ai/install_lmm.sh | sh`
- **`safe_install`** — works on Alpine, minimal Docker, and stripped containers (no GNU coreutils dependency)
- **`npm_hardened_ci`** — supply-chain safe npm installs with `--omit=optional` toggle for frontend and backend builds
- **Zero root** — installs to `~/.local/`, never requires sudo

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Browser dashboard               │
│              (http://127.0.0.1:8765)            │
└─────────────────────┬───────────────────────────┘
                      │ HTTP API
┌─────────────────────▼───────────────────────────┐
│           llama-model (CLI wrapper)              │
│  registry · doctor · switch · restart · build   │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│         GlyphOS OpenAI gateway                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Context  │  │ Ψ Encode │  │ Adaptive     │  │
│  │ Pipeline │→ │ Pipeline │→ │ Router       │  │
│  │ (FTS5)   │  │ (GE1)    │  │ (Local/Cloud)│  │
│  └──────────┘  └──────────┘  └──────┬───────┘  │
└─────────────────────────────────────┼──────────┘
                                      │
                    ┌─────────────────┼─────────────┐
                    ▼                 ▼             ▼
              llama.cpp          OpenAI/        Anthropic/
              (local)            Claude         xAI (cloud)
```

---

## Why it matters

| Benefit | How |
|---------|-----|
| Stay local | Local-first routing with cloud fallback only when needed |
| Stay sovereign | No data leaves your machine unless you explicitly route to cloud |
| Stay fast | Ψ encoding reduces token counts; auto-fit optimizes GPU offload |
| Stay stable | Guarded startup, context quality scoring, graceful degradation |
| Stay observable | Telemetry, doctor diagnostics, dashboard health cards |
| Stay portable | Works on bare metal, Docker, Alpine, and stripped containers |

---

## What `install.sh` does

- installs the CLI, web UI, desktop launcher, help text, and example config files
- copies bundled runtime assets if this repo already contains them
- in an interactive terminal, offers to check and install missing build dependencies and compile a local runtime
- does **not** silently compile `llama.cpp` — it only launches the runtime build flow if you agree
- does **not** silently install OS packages or GPU SDKs

### After install

```bash
llama-model-web
llama-model list
llama-model doctor
llama-model build-runtime --backend auto
```

### Recommended first-run flow

```bash
./install.sh
llama-model doctor
llama-model build-runtime --backend auto
llama-model doctor
llama-model-web
```

If `doctor` reports `binary_status: unavailable`, install the missing build dependencies for that machine and run `build-runtime` again.

---

## Optional dashboard background service

The dashboard runs on demand by default. You can opt into a managed `systemd --user` service if you want a stable local dashboard URL without launching it manually.

```bash
llama-model dashboard-service install
llama-model dashboard-service enable
llama-model dashboard-service status
```

- unit: `llama-model-web.service`
- URL: `http://127.0.0.1:8765/`

The background service is optional and is never enabled by default.

---

## Dashboard safety defaults

The dashboard binds to `127.0.0.1` by default. API responses use structured JSON errors with stable `code` fields. State-changing API payloads are schema-checked and reject unknown fields. Request bodies are capped by `LLAMA_MODEL_WEB_MAX_REQUEST_BYTES`.

If you intentionally bind the dashboard beyond localhost, set the hardening knobs explicitly:

```bash
export LLAMA_MODEL_WEB_HOST=0.0.0.0
export LLAMA_MODEL_WEB_API_TOKEN='replace-with-a-long-random-token'
export LLAMA_MODEL_WEB_ALLOWED_HOSTS='127.0.0.1,192.168.1.25'
llama-model-web --no-browser
```

Remote clients must send either:

- `X-LLAMA-MODEL-MANAGER-TOKEN: <token>`
- `Authorization: Bearer <token>`

Localhost clients remain convenient for normal single-user workflows. External binds should be treated as operator-controlled surfaces, not public internet endpoints.

---

## Runtime portability

llama.cpp source is portable, but built `llama-server` binaries are backend, platform, and architecture specific. This repo does not assume one bundled GPU binary works everywhere. `llama-model doctor` reports host backends, selected binary source, and compatibility status.

### What `llama-model build-runtime` does

- clones or updates `https://github.com/ggml-org/llama.cpp.git`
- checks out the configured `llama.cpp` ref
- builds a host-specific `llama-server` runtime for the selected backend
- also builds a CPU fallback runtime
- writes compatibility metadata so the manager can reject mismatched bundled binaries later

### What it does not do

- does **not** silently run `apt`, `dnf`, `pacman`, `brew`, or any other package manager without asking first
- does **not** install unsupported toolchains or SDK paths by guesswork
- does **not** try to guess a safe third-party GPU binary from another machine

### Interactive dependency assistance

When `build-runtime` sees missing build tools in an interactive terminal, it tells you what's missing, shows the install commands it plans to run, and asks for confirmation first. If the host package manager is unsupported, the script stops and tells you what to install manually.

### Remote model downloads

The dashboard can search Hugging Face for cached GGUF artifacts, annotate basic fit signals, and queue downloads through a serialized lifecycle. Download jobs are stored under `~/.local/state/llama-server/download-jobs.json`, so the UI can recover stale workers and the CLI can inspect or cancel jobs even when the browser is closed.

```bash
llama-model download-jobs
llama-model download-cancel <job_id>
llama-model download-retry <job_id>
```

---

## Supported integrations

| Integration | What it does | CLI |
|-------------|-------------|-----|
| **opencode** | Syncs to the live local OpenAI-compatible `llama.cpp` endpoint | `llama-model sync-opencode --preset balanced\|long-run` |
| **OpenClaw** | Syncs to the live local OpenAI-compatible `llama.cpp` endpoint | `llama-model sync-openclaw` |
| **Claude Code** | Syncs local Claude settings to a local Anthropic-compatible gateway | `llama-model sync-claude` |
| **Claude gateway** | Local bridge in front of the active `llama.cpp` endpoint for Claude Code compatibility | `llama-model claude-gateway start\|stop\|restart\|status\|logs` |
| **GlyphOS AI Compute** | Syncs `~/.glyphos/config.yaml` to the active local `llama.cpp` runtime | `llama-model sync-glyphos` |

These integrations are optional. The default product behavior remains the local `llama.cpp` runtime plus the on-demand dashboard.

### Client sync details

- `opencode` keeps its own local client config in `~/.config/opencode/opencode.json`, so it can keep pointing at a stale GGUF even after `llama-model switch`.
- Successful model switches auto-run the OpenCode sync by default with `LLAMA_MODEL_SYNC_OPENCODE=1`; set it to `0` for manual-only sync.
- `llama-model sync-opencode` updates the `llamacpp` provider endpoint, default model, and local model-state wiring to match `llama-model current`. The default route mode is `routed`, which points OpenAI-compatible harnesses at the LMM gateway on `http://127.0.0.1:4010/v1`.
- In routed mode, `sync-opencode` and `sync-openclaw` start or verify the LMM gateway so clients do not land on a refused `127.0.0.1:4010` connection. Set `LLAMA_MODEL_AUTOSTART_GATEWAY_ON_SYNC=0` only if you manage the gateway lifecycle yourself.
- Routed mode means `harness → LMM gateway → Context MCP when available → Glyph Encoding when useful → GlyphOS AI Compute → local llama.cpp backend`. Sync output reports `routed-full-capable` when the combined feature is configured. Use `--mode direct` when you want to bypass the gateway and call the backend `8081/v1` endpoint directly.
- `llama-model sync-opencode --preset long-run` writes model-aware `compaction.reserved` headroom. For 128k-token local contexts it reserves 64000 tokens, which avoids the observed long-session stall pattern where opencode aborts a pending tool after a parent message timeout.
- `llama-model sync-openclaw` updates `~/.openclaw/openclaw.json` so OpenClaw points at the routed LMM gateway by default.
- `llama-model sync-claude` writes `~/.claude/settings.json` for Claude Code.
- Post-switch sync for Claude Code, OpenClaw, and GlyphOS is opt-in with `LLAMA_MODEL_SYNC_CLAUDE=1`, `LLAMA_MODEL_SYNC_OPENCLAW=1`, and `LLAMA_MODEL_SYNC_GLYPHOS=1`.
- Post-switch sync is non-fatal; a client-config error warns but does not roll back a successfully started local model.

---

## Context Mode MCP

The optional Context Mode MCP package lives under `integrations/context-mode-mcp/`. It is intended for local development workflows that need indexed context, compact retrieval, lifecycle diagnostics, and MCP tool execution helpers.

Gateway requests use the bundled `scripts/context_mcp_bridge.py` by default when the Context Mode MCP package and built `dist/index.js` are present. If Context MCP is unavailable, times out, or returns no context, the gateway continues in `routed-basic` mode and records the degraded stage in telemetry.

Glyph Encoding runs after context retrieval and before GlyphOS routing. It only compresses structured or repeated retrieved context, never the latest user instruction. If encoding is not smaller or fails, the gateway falls back to raw retrieved context and records the reason.

### Common commands

```bash
cd integrations/context-mode-mcp
npm ci --omit=optional --ignore-scripts --no-audit --fund=false
npm run typecheck
npm run build
npm run lifecycle-matrix
```

Supply-chain policy:

- All `npm ci` invocations use `--ignore-scripts` (blocks arbitrary postinstall hooks) and `--no-audit --fund=false` (skips network telemetry).
- `--omit=optional` is correct for the Context MCP bundle (no optional platform deps needed).
- **Do not use `--omit=optional` for Next.js, Vite, or other frontend builds** — those require optional platform-native packages like `@next/swc-*` binaries. Use `npm ci --ignore-scripts --no-audit --fund=false` instead.

Safety notes:

- `ctx_execute` and `ctx_execute_file` run in temporary working directories with allowlist and denylist policy checks.
- These helpers are not described as OS-level sandboxes; use container or VM isolation if you need a security boundary.
- Large outputs are indexed automatically when configured, so MCP responses stay compact.

### Context + GlyphOS readiness

The dashboard has a `Context + GlyphOS` preference in global defaults. The toggle activates a combined readiness and workflow view for:

- active local model selected by Llama Model Manager
- GlyphOS config present at `~/.glyphos/config.yaml`
- Context Mode MCP package present in `integrations/context-mode-mcp/`
- lifecycle and typecheck commands available for local validation

This toggle is operator-facing. It does not create a new network service or claim extra sandboxing; it makes the bundled combined workflow clear when Context Mode MCP retrieval and GlyphOS routing are used together.

The Integrations panel also includes an **Activate feature** button for this card. That one click persists `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE=1`, enables GlyphOS auto-sync, runs `llama-model sync-glyphos`, and refreshes the readiness card.

---

## Common commands

```bash
llama-model list
llama-model show gemma4-e4b-q8
llama-model add gemma4-e4b-q8 /absolute/path/to/model.gguf --mmproj /absolute/path/to/mmproj.gguf
llama-model discover ~/models
llama-model build-runtime --backend auto
llama-model switch qwen35-9b-q8
llama-model sync-opencode --preset balanced
llama-model sync-opencode --preset long-run
llama-model sync-openclaw --profile lmm-eval qwen35-9b-q8
llama-model sync-claude qwen35-9b-q8
llama-model claude-gateway start
llama-model sync-glyphos
llama-model doctor
```

`llama-model doctor` also checks install health. After a curl or bootstrap install it should report `install_ok: yes`. If it reports `install_ok: no`, rerun `./install.sh` from the current checkout or rerun the latest bootstrap installer, then restart `llama-model-web`.

---

## Dependencies

- `python3` is required for the web dashboard
- `zenity` is optional and only needed for the legacy fallback UI
- `git`, `cmake`, and a C++ compiler are required if you want the repo to fetch and build `llama.cpp` locally
- CUDA builds need the CUDA toolkit, Vulkan builds need the Vulkan SDK, and Metal builds need Xcode command line tools
- the runtime build script fetches `llama.cpp` source automatically, but system dependencies must already be present
- the scripts use XDG-style config and state locations under `~/.config/llama-server` and `~/.local/state/llama-server`
- `LLAMA_SERVER_PARALLEL=1` is recommended for a single coding harness because it avoids parallel slot pressure without reducing context length
- `LLAMA_MODEL_AUTO_FIT=1` is the default guarded GPU and RAM-aware startup mitigation; use `--no-auto-fit` for a strict launch
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` is an experimental CUDA-only escape hatch for oversized context, KV-cache, or compute allocations; it can preserve larger context attempts, but it may be much slower on discrete GPUs
- set `LLAMA_MODEL_UI=zenity` if you want to force the old Zenity UI instead of the browser dashboard

## Bundled local packages

The public GlyphOS AI Compute package is vendored locally under `integrations/public-glyphos-ai-compute/`. This bundled copy contains only the public glyph and AI routing layers. The private Q45 and quantum stack is intentionally not included here.

## Gateway foundation modules

The gateway Python surfaces share small stdlib-only foundation modules under `scripts/`:

- `lmm_config.py` loads and validates gateway and context environment settings with dataclasses instead of ad-hoc parsing.
- `lmm_errors.py` provides machine-readable error payloads for configuration, gateway, provider, routing, and storage failures.
- `lmm_storage.py` owns gateway telemetry persistence behind a storage adapter so handlers do not mutate state files directly.

These modules are intentionally dependency-free and can coexist with the existing `defaults.env` shell configuration.

---

## Maintainer verification

Before pushing a release branch, run the focused checks that cover the web dashboard, GlyphOS routing, and Context Mode MCP surfaces:

```bash
python -m unittest tests.test_phase0_contracts
python -m unittest integrations.public-glyphos-ai-compute.tests.test_q2_flow
cd integrations/context-mode-mcp && npm run typecheck && npm run build
```

Expected notes:

- The web contract suite includes cancellation-path coverage and may exercise connection-reset behavior while still passing.
- `npm run build` may warn about dashboard chunk size; that is a bundle-size hygiene item, not a functional failure.
- `npm run lifecycle-matrix` is the manual MCP lifecycle smoke test for `ctx_doctor`, `ctx_execute`, `ctx_upgrade`, `ctx_purge`, `ctx_index`, and `ctx_search`.

## Roadmap

Planned follow-up is tracked in [docs/ROADMAP.md](docs/ROADMAP.md), including long-run session handoff: persistent run state, completion summaries, artifacts, and optional local notifications for extended agent sessions.

---

## License

- Copyright 2026 soulhash.ai
- Licensed under Apache-2.0
- The code is free to use under the license terms while soulhash.ai remains the copyright owner

## Trademark notice

- **Soul Hash®** is a registered trademark of soulhash.ai
- **GlyphOS™** is a trademark of soulhash.ai
- The Apache-2.0 license does not grant trademark rights
