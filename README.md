# Llama Model Manager

**by soulhash.ai**

## 🔱 The Engine Room for Local AI

llama-model-manager is a production-grade operations dashboard for `llama.cpp` and GlyphOS™ AI Compute. It transforms local inference from a brittle CLI experiment into a resilient, browser-first control surface.

If you're running Claude Code, OpenClaw, or opencode, this is where your stability lives.

Key capabilities:

- 📦 **GGUF Discovery & Management:** Find, register, and hot-swap local models.
- ⚙️ **Runtime Posture Tuning:** Real-time control over context limits, GPU offload, batch, threads, health metrics, and guarded startup auto-fit.
- 🛠️ **Dev-Tool Sync:** Native integration for local coding environments, with CLI and desktop launchers included.
- 🧬 **GlyphOS™ Routing:** Route workloads through the active local endpoint with 🔱 𝚿 Glyph Encoding, reducing token payloads by 60-90% for faster transport and stronger long-context stability.

Stay local. Stay sovereign. Stay fast.

![Dashboard overview](docs/screenshots/dashboard-overview.png)

## What You Get

- `bin/llama-model`: CLI wrapper for registry management, switching, restart/stop, discovery, diagnostics, and download job inspection/control
- `bin/llama-model-web`: browser dashboard launcher
- `bin/llama-model-gui`: launcher that prefers the web dashboard and falls back to Zenity
- `config/defaults.env.example`: runtime defaults template
- `config/models.tsv.example`: model registry template
- `config/HELP.txt`: end-user help text
- `desktop/llama-model-manager.desktop`: desktop launcher
- `desktop/llama-model-manager-icon.svg`: desktop icon asset used by the installer
- `scripts/build-llama-server.sh`: wrapper for fetching and compiling a host-specific llama.cpp runtime
- `integrations/public-glyphos-ai-compute/`: bundled public GlyphOS AI Compute lane
- `integrations/context-mode-mcp/`: optional Context Mode MCP package for indexed context, lifecycle checks, and temporary-workdir execution tools
- `web/`: browser dashboard assets and Python server
- `LICENSE`: Apache License 2.0
- `NOTICE`: copyright and attribution notice
- `install.sh`: optional local installer for user-space deployment

## Quick Install

```bash
./install.sh
```

## One-Line Install

Host `install-bootstrap.sh` at a stable URL such as `https://soulhash.ai/install_lmm.sh`, then users can install without cloning the repo first:

```bash
curl -fsSL https://soulhash.ai/install_lmm.sh | sh
```

What the bootstrap script does:

- downloads the repo tarball from GitHub into a temporary directory
- extracts it locally
- hands off to the existing `install.sh`
- cleans up the temporary download on exit

Override knobs for testing or pinned installs:

- `LLAMA_MODEL_MANAGER_REF=v1.2.3`
- `LLAMA_MODEL_MANAGER_ARCHIVE_URL=https://.../custom.tar.gz`
- `LLAMA_MODEL_MANAGER_REPO_OWNER=...`
- `LLAMA_MODEL_MANAGER_REPO_NAME=...`

### What `install.sh` Does

- installs the CLI, web UI, desktop launcher, help text, and example config files
- copies bundled runtime assets if this repo already contains them
- in an interactive terminal, offers to check/install missing build dependencies and compile a local runtime
- does **not** silently compile `llama.cpp`; it only launches the runtime build flow if the user agrees
- does **not** silently install OS packages or GPU SDKs/toolkits for you

### After Install

```bash
llama-model-web
llama-model list
llama-model doctor
llama-model build-runtime --backend auto
```

## Optional Dashboard Background Service

The dashboard normally runs on demand and does not stay resident. Advanced users can opt into a managed `systemd --user` service when they want a stable local dashboard URL without launching it manually.

Default mode:

- run `llama-model-web` when needed
- or use `llama-model-gui`
- nothing starts automatically at login unless you enable it

Advanced mode:

```bash
llama-model dashboard-service install
llama-model dashboard-service enable
llama-model dashboard-service restart
llama-model dashboard-service status
llama-model dashboard-service logs
```

The installed user unit serves the installed dashboard launcher with a fixed local URL:

- unit: `llama-model-web.service`
- URL: `http://127.0.0.1:8765/`

The background service remains fully optional and is never enabled by default.

## Dashboard Safety Defaults

The dashboard is designed for localhost operation by default:

- default bind host: `127.0.0.1`
- default URL: `http://127.0.0.1:8765/`
- API responses use structured JSON errors with stable `code` fields
- state-changing API payloads are schema-checked and reject unknown fields
- request bodies are capped by `LLAMA_MODEL_WEB_MAX_REQUEST_BYTES`
- CLI-backed API calls are capped by `LLAMA_MODEL_WEB_CLI_TIMEOUT_SECONDS`
- download and routing actions are written to a recent-activity trail for troubleshooting queue, retry, and remote-cache behavior
- the optional `Context + GlyphOS` dashboard toggle lets operators activate the bundled combined retrieved-context plus glyph-routed-inference workflow view

If you intentionally bind the dashboard beyond localhost, set the hardening knobs explicitly:

```bash
export LLAMA_MODEL_WEB_HOST=0.0.0.0
export LLAMA_MODEL_WEB_API_TOKEN='replace-with-a-long-random-token'
export LLAMA_MODEL_WEB_ALLOWED_HOSTS='127.0.0.1,192.168.1.25'
export LLAMA_MODEL_WEB_MAX_REQUEST_BYTES=1048576
export LLAMA_MODEL_WEB_CLI_TIMEOUT_SECONDS=30
llama-model-web --no-browser
```

Remote clients must send either:

- `X-LLAMA-MODEL-MANAGER-TOKEN: <token>`
- `Authorization: Bearer <token>`

Localhost clients remain convenient for normal single-user workflows. External binds should be treated as operator-controlled surfaces, not public internet endpoints.

## Runtime Portability

- llama.cpp source is portable, but built `llama-server` binaries are backend-, platform-, and architecture-specific
- this repo does not assume one bundled GPU binary works everywhere
- `llama-model doctor` reports host backends, selected binary source, and compatibility status
- if no safe runtime is available, run `llama-model build-runtime --backend auto` or `./scripts/build-llama-server.sh --backend auto`

### What `llama-model build-runtime` Does

- clones or updates `https://github.com/ggml-org/llama.cpp.git`
- checks out the configured `llama.cpp` ref
- builds a host-specific `llama-server` runtime for the selected backend
- also builds a CPU fallback runtime
- writes compatibility metadata so the manager can reject mismatched bundled binaries later

### What `llama-model build-runtime` Does Not Do

- it does **not** silently run `apt`, `dnf`, `pacman`, `brew`, or any other package manager without asking first
- it does **not** install unsupported toolchains or SDK paths by guesswork
- it does **not** try to guess a safe third-party GPU binary from another machine

### Interactive Dependency Assistance

- when `llama-model build-runtime` sees missing build tools in an interactive terminal, it:
  - tells the user exactly what is missing
  - shows the install commands it plans to run
  - asks for confirmation first
  - runs the detected system package manager when it knows a sane command for that host
- this currently covers common package-manager flows such as `apt-get`, `dnf`, `pacman`, `zypper`, and `brew`, plus `xcode-select --install` for macOS command line tools
- if the host package manager or SDK path is unsupported, the script stops and tells the user what still needs to be installed manually

### Remote Model Downloads

The dashboard can search Hugging Face for cached GGUF artifacts, annotate basic fit signals, and queue downloads through a serialized lifecycle. Download jobs are stored under `~/.local/state/llama-server/download-jobs.json`, so the UI can recover stale workers and the CLI can inspect or act on jobs even if the browser is not open.

Useful CLI fallbacks:

```bash
llama-model download-jobs
llama-model download-cancel <job_id>
llama-model download-retry <job_id>
```

### Recommended First-Run Flow

```bash
./install.sh
llama-model doctor
llama-model build-runtime --backend auto
llama-model doctor
llama-model-web
```

If `doctor` reports `binary_status: unavailable`, install the missing build dependencies for that machine and run `llama-model build-runtime --backend auto` again.

## Key Features

- browser dashboard for switching models, importing discovered GGUFs, editing presets, and checking runtime health
- managed Hugging Face remote search and serialized download lifecycle with cancel, retry, resume, queue controls, and persisted job state
- structured registry entries with per-model overrides for context, `ngl`, batch, threads, parallel, device, and notes
- automatic discovery of `.gguf` models plus same-directory `mmproj` sidecars
- CLI diagnostics via `llama-model doctor`, including startup failure categories and GPU pressure visibility
- hardened dashboard API behavior with optional remote-token auth, request-size limits, schema validation, timeout-specific errors, and recent operation activity
- manifest-driven runtime selection that only accepts validated bundled binaries
- local `llama.cpp` bootstrap via `llama-model build-runtime`
- guarded GPU/RAM-aware auto-fit for known CUDA/KV-cache/projector startup failures without silently persisting downgraded settings
- OpenAI-compatible endpoint summary plus sync wiring for local harnesses such as `opencode`, `OpenClaw`, and `Claude Code`
- bundled GlyphOS AI Compute support for routing glyph-driven workloads to the active local model
- optional Context Mode MCP package with lifecycle matrix checks, indexed context search, Claude hook templates, and temporary-workdir execution helpers with allowlist/denylist policy checks
- Modern Operator dashboard treatment with toasts, busy states, and first-run empty states

## GlyphOS AI Compute

GlyphOS AI Compute is bundled as a public local integration lane. It turns glyph state into model-ready prompts and routes those requests through the same local `llama.cpp` endpoint managed by Llama Model Manager.

![Animated demo showing a verbose local AI request being converted into compact GlyphOS tokens, reducing the displayed payload by 60-90%, then routing through a local llama.cpp endpoint at 127.0.0.1:8081/v1. The final frame reads: Stay local. Stay private. Stay fast.](docs/branding/glyphos-encoding-demo.gif)

Benefits:

- local-first routing through `http://127.0.0.1:8081/v1`
- one-command sync with `llama-model sync-glyphos`
- generated config at `~/.glyphos/config.yaml`
- shared active model selection with the dashboard and CLI
- public glyph, prompt, and AI routing layers included in-repo
- private Q45 / quantum components intentionally excluded from this public package

Terran validation:

- Terran sustained a continuous `8h 59m` coding session using GlyphOS AI Compute routed through local LMM-managed `llama.cpp`
- runtime posture: `Qwen3.5-9B-Q8_0.gguf`, `context 128000`, `parallel 1`
- client path: `opencode` + local `llama-model-manager` + GlyphOS AI Compute
- observed result: stable long-run code generation without a fatal session drop during the reported run, with the operator reporting the task completed correctly

Reference: [Terran GlyphOS Long-Run Validation](docs/TERRAN-GLYPHOS-LONG-RUN-VALIDATION.md)

## Supported Integrations

Current public integration support:

- `opencode`
  - direct sync to the live local OpenAI-compatible `llama.cpp` endpoint
  - CLI: `llama-model sync-opencode --preset balanced|long-run`
  - dashboard action: `Sync opencode`
- `OpenClaw`
  - direct sync to the live local OpenAI-compatible `llama.cpp` endpoint
  - CLI: `llama-model sync-openclaw`
  - dashboard action: `Sync OpenClaw`
- `Claude Code`
  - syncs local Claude settings to a local Anthropic-compatible gateway target
  - CLI: `llama-model sync-claude`
  - dashboard action: `Sync Claude`
- `Claude gateway`
  - local bridge in front of the active `llama.cpp` endpoint for Claude Code compatibility
  - CLI: `llama-model claude-gateway start|stop|restart|status|logs`
  - dashboard controls: `Start`, `Restart`, `Stop`, `Logs`
- `GlyphOS AI Compute`
  - syncs `~/.glyphos/config.yaml` to the active local `llama.cpp` runtime
  - CLI: `llama-model sync-glyphos`
  - dashboard action: `Sync GlyphOS`

These integrations are optional. The default product behavior remains the local `llama.cpp` runtime plus the on-demand dashboard.

## Dependencies

- `python3` is required for the web dashboard
- `zenity` is optional and only needed for the legacy fallback UI
- `git`, `cmake`, and a C++ compiler are required if you want the repo to fetch and build `llama.cpp` locally
- CUDA builds need the CUDA toolkit, Vulkan builds need Vulkan SDK/shader tools, and Metal builds need Xcode command line tools
- the runtime build script fetches `llama.cpp` source automatically, but system dependencies must already be present
- the scripts use XDG-style config/state locations under `~/.config/llama-server` and `~/.local/state/llama-server`
- `LLAMA_SERVER_PARALLEL=1` is recommended for a single coding harness because it avoids parallel slot pressure without reducing context length
- `LLAMA_MODEL_AUTO_FIT=1` is the default guarded GPU/RAM-aware startup mitigation; use `--no-auto-fit` for a strict launch
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` is an experimental CUDA-only escape hatch for oversized context/KV/compute allocations; it can preserve larger context attempts, but it may be much slower on discrete GPUs
- high system RAM helps hybrid CPU/GPU offload start successfully, but it is slower than full GPU offload and should not be treated as extra VRAM
- set `LLAMA_MODEL_UI=zenity` if you want to force the old Zenity UI instead of the browser dashboard

## Bundled Local Packages

- public GlyphOS AI Compute package is vendored locally under `integrations/public-glyphos-ai-compute/`
- this bundled copy contains only the public glyph + AI routing layers
- the private Q45 / quantum stack is intentionally not included here

## Client Sync

- `opencode` keeps its own local client config in `~/.config/opencode/opencode.json`, so it can keep pointing at a stale GGUF even after `llama-model switch`.
- successful model switches auto-run the OpenCode sync by default with `LLAMA_MODEL_SYNC_OPENCODE=1`; set it to `0` for manual-only sync.
- `llama-model sync-opencode` updates the `llamacpp` provider endpoint, default model, and local model-state wiring to match `llama-model current`.
- `llama-model sync-openclaw` updates `~/.openclaw/openclaw.json` or `~/.openclaw-<profile>/openclaw.json` so OpenClaw points directly at the live local endpoint.
- `llama-model sync-claude` writes `~/.claude/settings.json` for Claude Code, and `llama-model claude-gateway` runs a local Anthropic-compatible bridge in front of the current llama.cpp server.
- `llama-model sync-glyphos` writes `~/.glyphos/config.yaml` so the bundled public GlyphOS AI Compute package can target the active local `llama.cpp` endpoint directly.
- post-switch sync for Claude Code, OpenClaw, and GlyphOS is opt-in with `LLAMA_MODEL_SYNC_CLAUDE=1`, `LLAMA_MODEL_SYNC_OPENCLAW=1`, and `LLAMA_MODEL_SYNC_GLYPHOS=1`.
- post-switch sync is non-fatal; a client-config error warns but does not roll back a successfully started local model.
- the dashboard exposes direct sync actions for all three tools and gateway controls for Claude Code.

## Context Mode MCP

The optional Context Mode MCP package lives under `integrations/context-mode-mcp/`. It is intended for local development workflows that need indexed context, compact retrieval, lifecycle diagnostics, and MCP tool execution helpers.

Common commands:

```bash
cd integrations/context-mode-mcp
npm ci
npm run typecheck
npm run build
npm run lifecycle-matrix
```

Safety notes:

- `ctx_execute` and `ctx_execute_file` run in temporary working directories with allowlist/denylist policy checks.
- These helpers are not described as OS-level sandboxes; use container or VM isolation if you need a security boundary.
- Large outputs are indexed automatically when configured, so MCP responses stay compact.
- Generated `dist/`, dashboard `dist/`, and `node_modules/` artifacts are intentionally ignored by git.

### Context + GlyphOS readiness

The dashboard has a simple `Context + GlyphOS` preference in global defaults. The pieces are bundled in the repo; the toggle activates a combined readiness/workflow view for:

- active local model selected by Llama Model Manager
- GlyphOS config present at `~/.glyphos/config.yaml`
- Context Mode MCP package present in `integrations/context-mode-mcp/`
- lifecycle/typecheck commands available for local validation

This toggle is intentionally operator-facing. It does not create a new network service or claim extra sandboxing; it makes the bundled combined workflow clear when Context Mode MCP retrieval and GlyphOS routing are used together.

The Integrations panel also includes an `Activate Feature` button for this card. That one click persists `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE=1`, enables GlyphOS auto-sync, runs `llama-model sync-glyphos`, and refreshes the readiness card.

## Maintainer Verification

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

## Common Commands

```bash
llama-model list
llama-model show gemma4-e4b-q8
llama-model add gemma4-e4b-q8 /absolute/path/to/Gemma-4-E4B-Q8_K_P.gguf --mmproj /absolute/path/to/mmproj-Gemma-4-E4B-f16.gguf
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

`llama-model doctor` also checks install health. After a curl/bootstrap install it should report:

- `installed_web_launcher: yes`
- `installed_web_app: yes`
- `bundled_glyphos_integration: yes`
- `context_mode_mcp_installed: yes`
- `install_ok: yes`

If `install_ok: no`, rerun `./install.sh` from the current checkout or rerun the latest bootstrap installer, then restart `llama-model-web`.
When the dashboard is running, `doctor` also reports `dashboard_api_glyphos_telemetry` and `dashboard_api_context_glyphos_status`; if `dashboard_api_guidance` is populated, restart `llama-model-web` and hard refresh the browser.

## License

- Copyright `2026 soulhash.ai`
- Licensed under `Apache-2.0`
- The code is free to use under the license terms while `soulhash.ai` remains the copyright owner

## Trademark Notice

- `Soul Hash®` is a registered trademark of soulhash.ai
- `GlyphOS™` is a trademark of soulhash.ai
- The Apache-2.0 license does not grant trademark rights
