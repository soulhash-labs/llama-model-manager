# External Integrations

**Analysis Date:** 2026-04-30

## APIs & External Services

**Hugging Face:**
- Remote GGUF model search and download
- Search endpoint: HF API via `urllib`
- Download: Direct artifact URL fetch
- Auth: Not supported (gated/private repos excluded)

**llama.cpp:**
- Local inference engine
- Communication: OpenAI-compatible HTTP API
- Default endpoint: `http://127.0.0.1:8081/v1`
- Health check: `GET /health`

**GlyphOS AI Compute (bundled):**
- Adaptive routing layer for inference requests
- SDK: Python package at `integrations/public-glyphos-ai-compute/`
- Supports: llamacpp, OpenAI, Anthropic, XAI clients
- Config: `~/.glyphos/config.yaml`

**Context Mode MCP (bundled):**
- MCP server for context retrieval
- SDK: Node.js package at `integrations/context-mode-mcp/`
- Communication: stdin/stdout JSON-RPC 2.0 via `context_mcp_bridge.py`

## Data Storage

**Databases:**
- None - JSON file-based storage

**File Storage:**
- Local filesystem only
- Model files: User-specified paths (typically `~/models/`)
- Download artifacts: Destination root from download job config

**JSON Stores (all under `~/.local/state/llama-server/`):**
- `download-jobs.json` - Download queue and history
- `remote-models.json` - Hugging Face search cache
- `host-capability.json` - Host GPU/backend capability
- `validation-results.json` - Binary validation history
- `operation-activity.json` - Recent API activity log
- `lmm-gateway-requests.json` - Gateway request telemetry

**Config Files (under `~/.config/llama-server/`):**
- `defaults.env` - Runtime configuration (shell-sourced)
- `models.tsv` - Model registry (tab-separated)
- `runtime-profiles.json` - Discovered binary profiles

**State Files:**
- `~/.local/state/llama-server/current.env` - Current server state (shell-sourced)

## Authentication & Identity

**Dashboard Auth:**
- Default: No auth (localhost only)
- Remote: `LLAMA_MODEL_WEB_API_TOKEN` env var
- Headers: `X-LLAMA-MODEL-MANAGER-TOKEN` or `Authorization: Bearer <token>`
- Allowed hosts: `LLAMA_MODEL_WEB_ALLOWED_HOSTS`

**Client API Keys:**
- OpenClaw: `OPENCLAW_API_KEY` (default: `llama-local`)
- Claude: `CLAUDE_AUTH_TOKEN`, `CLAUDE_API_KEY`

## Monitoring & Observability

**Error Tracking:**
- None - local-only tool

**Logs:**
- llama.cpp server: `LLAMA_SERVER_LOG` (default: `~/models/llama-server.log`)
- LMM Gateway: `LLAMA_MODEL_GATEWAY_LOG` (default: `~/models/lmm-gateway.log`)
- Claude Gateway: `CLAUDE_GATEWAY_LOG` (default: `~/models/claude-gateway.log`)
- Gateway telemetry: JSON state file with counters and recent requests

**Diagnostics:**
- `llama-model doctor` - Comprehensive health report
- `llama-model logs [lines]` - Tail server logs
- Dashboard activity feed - Recent API actions

## CI/CD & Deployment

**Hosting:**
- Local-only, user-space deployment

**CI Pipeline:**
- None - GitHub releases as tarballs
- Bootstrap install via `curl -fsSL <url> | sh`

## Environment Configuration

**Required env vars (with defaults):**
- `LLAMA_SERVER_HOST=127.0.0.1`
- `LLAMA_SERVER_PORT=8081`
- `LLAMA_SERVER_CONTEXT=128000`
- `LLAMA_SERVER_NGL=999`
- `LLAMA_SERVER_BATCH=128`
- `LLAMA_SERVER_THREADS=16`
- `LLAMA_MODEL_HARNESS_MODE=routed`
- `LLAMA_MODEL_GATEWAY_HOST=127.0.0.1`
- `LLAMA_MODEL_GATEWAY_PORT=4010`

**Optional env vars:**
- `LLAMA_MODEL_WEB_API_TOKEN` - Remote dashboard auth
- `LLAMA_MODEL_WEB_HOST` / `LLAMA_MODEL_WEB_PORT` - Dashboard bind
- `LLAMA_MODEL_WEB_MAX_REQUEST_BYTES` - Request size limit (default 2MB)
- `LLAMA_MODEL_WEB_CLI_TIMEOUT_SECONDS` - CLI subprocess timeout (default 60s)
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY` - CUDA unified memory toggle
- `LLAMA_MODEL_AUTO_FIT` - Guarded GPU startup (default: 1)
- `LLAMA_MODEL_SYNC_OPENCODE` - Auto-sync opencode (default: 1)
- `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE` - Enable context pipeline

**Secrets location:**
- Environment variables only, no secret management

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None - all local communication

## Synced Client Configs

**opencode (`~/.config/opencode/opencode.json`):**
- Synced via `llama-model sync-opencode`
- Updates: `llamacpp` provider baseURL, model, compaction settings

**OpenClaw (`~/.openclaw/openclaw.json` or `~/.openclaw-<profile>/openclaw.json`):**
- Synced via `llama-model sync-openclaw`
- Updates: `llamacpp` provider, model catalog

**Claude Code (`~/.claude/settings.json`):**
- Synced via `llama-model sync-claude`
- Updates: `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` env vars

**GlyphOS (`~/.glyphos/config.yaml`):**
- Synced via `llama-model sync-glyphos`
- Updates: `ai_compute.llamacpp` url and model

---

*Integration audit: 2026-04-30*
