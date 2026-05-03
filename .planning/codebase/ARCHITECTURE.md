# Architecture

**Analysis Date:** 2026-04-30

## Pattern Overview

**Overall:** Local-first operations dashboard with CLI wrapper + Python HTTP server + browser frontend.

**Key Characteristics:**
- **CLI-first**: `bin/llama-model` bash script is the primary interface; web dashboard delegates to it
- **Demo mode**: `app.py` ships with hardcoded demo state for first-run previews
- **Subprocess delegation**: Web server calls CLI binary via `subprocess.run()` for real operations
- **JSON state files**: All persistent data stored as JSON under XDG directories
- **No external dependencies**: Python stdlib only for web server (`http.server`, `urllib`, `json`, `threading`)
- **Gateway proxy architecture**: LMM Gateway (port 4010) sits between coding harnesses and local `llama.cpp` backend (port 8081)

## Layers

**CLI Layer (`bin/llama-model`):**
- Purpose: Primary user interface, model management, runtime control, client sync
- Location: `bin/llama-model` (5099-line bash script)
- Contains: Model registry CRUD, server start/stop, discovery, doctor diagnostics, client sync (opencode/openclaw/claude/glyphos), gateway management, download lifecycle
- Depends on: System tools (`nvidia-smi`, `ss`, `pgrep`), Python3 for complex JSON operations
- Used by: Web dashboard (`app.py`), end users, installer scripts

**Web Backend (`web/app.py`):**
- Purpose: Browser dashboard API server, state aggregation, download manager
- Location: `web/app.py` (3429 lines)
- Contains: `Manager` class (business logic), `AppHandler` class (HTTP routing), download threading, Phase 0 contract aggregation
- Depends on: `bin/llama-model` CLI via `run_cli()`, Python stdlib only
- Used by: Browser frontend (`web/app.js`)

**Web Frontend (`web/app.js`, `web/index.html`, `web/styles.css`):**
- Purpose: Browser-based dashboard UI
- Location: `web/app.js` (2328 lines), `web/index.html`, `web/styles.css`
- Contains: State management, rendering functions, API client, toast notifications
- Depends on: Web backend API (`/api/*` endpoints)
- Used by: End users via browser at `http://127.0.0.1:8765/`

**Gateway Layer (`scripts/glyphos_openai_gateway.py`):**
- Purpose: OpenAI-compatible proxy with context retrieval and GlyphOS routing
- Location: `scripts/glyphos_openai_gateway.py` (975 lines)
- Contains: `GatewayHandler`, context pipeline, glyph encoding, SSE streaming
- Depends on: `integrations/public-glyphos-ai-compute/`, `integrations/context-mode-mcp/`
- Used by: Coding harnesses (opencode, OpenClaw) in routed mode

**Claude Gateway (`scripts/claude_gateway.py`):**
- Purpose: Anthropic-compatible proxy for Claude Code
- Location: `scripts/claude_gateway.py` (326 lines)
- Contains: `ClaudeGateway`, `GatewayHandler`, upstream client
- Depends on: Local `llama.cpp` OpenAI endpoint
- Used by: Claude Code

**Integration Sync (`scripts/integration_sync.py`):**
- Purpose: Write external client config files
- Location: `scripts/integration_sync.py` (348 lines)
- Contains: `sync_opencode`, `sync_openclaw`, `sync_claude`, `sync_glyphos`
- Used by: CLI sync commands

## Data Flow

**Model Switch:**
1. User calls `llama-model switch <alias>` or clicks Switch in dashboard
2. CLI resolves alias from `~/.config/llama-server/models.tsv`
3. Validates binary compatibility (bundled vs external)
4. Auto-fit adjusts context/ngl/parallel based on GPU/RAM posture
5. Launches `llama-server` with `setsid` for process isolation
6. Waits for health endpoint, writes state to `~/.local/state/llama-server/current.env`
7. Auto-syncs client configs (opencode by default, others opt-in)

**Routed Inference (harness → model):**
1. Harness (opencode/OpenClaw) sends request to LMM Gateway at `127.0.0.1:4010/v1`
2. Gateway extracts context from payload or calls Context MCP bridge
3. Glyph encoding compresses structured context if beneficial
4. Assembled prompt sent through GlyphOS AI Compute router
5. Router selects target (llamacpp/openai/anthropic/xai)
6. Response returned as OpenAI-compatible completion

**Download Lifecycle:**
1. User searches Hugging Face via `/api/remote/search`
2. Results cached in `~/.local/state/llama-server/remote-models.json`
3. Download queued in `~/.local/state/llama-server/download-jobs.json`
4. Threaded download with cancel/resume/retry support
5. Serialized queue with configurable `max_active_downloads`

**State Management:**
- Config: `~/.config/llama-server/defaults.env` (shell-sourced env vars)
- Registry: `~/.config/llama-server/models.tsv` (tab-separated)
- State files: `~/.local/state/llama-server/*.json` (JSON stores)
- All stores use schema versioning (`PHASE0_SCHEMA_VERSION = 1`)
- Atomic writes via temp file + `rename`

## Key Abstractions

**Manager (`web/app.py`):**
- Purpose: Central business logic for all dashboard operations
- Location: `web/app.py` class `Manager`
- Pattern: Stateful object with file I/O, CLI delegation, threading

**Phase 0 Contracts (`web/app.py`):**
- Purpose: Unified state snapshot combining all subsystem data
- Location: `Manager.phase0_contracts()` method
- Pattern: Aggregates remote models, download jobs, runtime profiles, validation results, host capability

**Binary Selection (`bin/llama-model`):**
- Purpose: Choose compatible `llama-server` binary for host
- Location: `bin/llama-model` functions `select_binary_record`, `validate_bundled_binary`
- Pattern: Preference order (requested backend → metal → cuda → vulkan → cpu), validation via manifest files

## Entry Points

**`bin/llama-model`:**
- Location: `bin/llama-model`
- Triggers: Direct CLI invocation, web dashboard subprocess calls
- Responsibilities: All model/server lifecycle, diagnostics, client sync

**`bin/llama-model-web`:**
- Location: `bin/llama-model-web`
- Triggers: User dashboard launch, systemd service
- Responsibilities: Starts Python HTTP server on configurable host/port

**`scripts/glyphos_openai_gateway.py`:**
- Location: `scripts/glyphos_openai_gateway.py`
- Triggers: `llama-model gateway start`, client connections
- Responsibilities: OpenAI-compatible proxy with context pipeline

**`scripts/claude_gateway.py`:**
- Location: `scripts/claude_gateway.py`
- Triggers: `llama-model claude-gateway start`
- Responsibilities: Anthropic-compatible proxy for Claude Code

## Error Handling

**Strategy:** Structured JSON errors with stable `code` fields, categorized startup failures

**Patterns:**
- `ValidationError` class with `code` + `message` (`web/app.py:72`)
- `CommandTimeoutError` for CLI subprocess timeouts (`web/app.py:80`)
- API returns `{ok: false, code: "error_code", error: "message"}`
- Startup log classifier categorizes failures: `kv-cache-oom`, `cuda-oom`, `mmproj-mismatch`, `port-in-use`, `cuda-detect-failed` (`bin/llama-model:1043-1073`)
- Gateway records telemetry for every request including error state

## Cross-Cutting Concerns

**Logging:** Server logs to configurable file, gateway logs to stderr, web server uses Python `logging` module minimally
**Validation:** Schema-based POST validation with allowed/required/typed fields (`API_POST_PAYLOAD_SCHEMAS`)
**Authentication:** Optional `LLAMA_MODEL_WEB_API_TOKEN` for remote access, localhost default

---

*Architecture analysis: 2026-04-30*
