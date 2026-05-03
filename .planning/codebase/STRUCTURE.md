# Codebase Structure

**Analysis Date:** 2026-04-30

## Directory Layout

```
llama-model-manager/
├── bin/                      # CLI entry points
│   ├── llama-model           # Main CLI wrapper (bash, 5099 lines)
│   ├── llama-model-web       # Dashboard launcher (bash)
│   └── llama-model-gui       # Desktop GUI launcher (bash)
├── web/                      # Browser dashboard
│   ├── app.py                # Python HTTP server + Manager class (3429 lines)
│   ├── app.js                # Frontend JS (2328 lines)
│   ├── index.html            # Dashboard HTML
│   └── styles.css            # Dashboard styles
├── scripts/                  # Python helper scripts
│   ├── glyphos_openai_gateway.py   # LMM OpenAI gateway (975 lines)
│   ├── claude_gateway.py           # Claude Anthropic gateway (326 lines)
│   ├── context_mcp_bridge.py       # Context MCP stdin bridge (148 lines)
│   ├── integration_sync.py         # Client config sync (348 lines)
│   └── build-llama-server.sh       # Runtime build wrapper
├── config/                   # Configuration templates
│   ├── defaults.env.example  # Runtime defaults template
│   ├── models.tsv.example    # Model registry template
│   └── HELP.txt              # End-user help text
├── integrations/             # Bundled integrations
│   ├── public-glyphos-ai-compute/  # GlyphOS AI Compute (vendored)
│   └── context-mode-mcp/          # Context Mode MCP (TypeScript/Node)
├── desktop/                  # Desktop integration
│   ├── llama-model-manager.desktop
│   └── llama-model-manager-icon.svg
├── tests/                    # Test suite
│   ├── test_phase0_contracts.py   # Python unit tests (4304 lines)
│   └── test_portability.sh        # Bash portability tests (1904 lines)
├── docs/                     # Documentation
├── install.sh                # Local installer (364 lines)
└── install-bootstrap.sh      # Bootstrap installer (curl | sh)
```

## Directory Purposes

**`bin/`:**
- Purpose: All CLI entry points
- Contains: Bash scripts for model management, web launch, GUI
- Key files: `llama-model` (main CLI), `llama-model-web` (dashboard), `llama-model-gui` (desktop)

**`web/`:**
- Purpose: Browser dashboard application
- Contains: Python HTTP server, JavaScript frontend, HTML, CSS
- Key files: `app.py` (backend), `app.js` (frontend), `index.html` (markup)

**`scripts/`:**
- Purpose: Supporting Python services invoked by CLI or standalone
- Contains: Gateway servers, sync utilities, build wrappers
- Key files: `glyphos_openai_gateway.py`, `claude_gateway.py`, `integration_sync.py`

**`config/`:**
- Purpose: User-facing configuration templates
- Contains: Example files shipped with installer
- Key files: `defaults.env.example`, `models.tsv.example`

**`integrations/`:**
- Purpose: Vendored third-party/bundled packages
- Contains: Public GlyphOS AI Compute, Context Mode MCP
- Key files: `integrations/public-glyphos-ai-compute/`, `integrations/context-mode-mcp/`

**`tests/`:**
- Purpose: Automated test suite
- Contains: Python unittest + bash integration tests
- Key files: `test_phase0_contracts.py`, `test_portability.sh`

## Key File Locations

**Entry Points:**
- `bin/llama-model`: Main CLI - model list/add/switch/doctor/sync
- `bin/llama-model-web`: Dashboard launcher
- `web/app.py`: HTTP server with all API endpoints

**Configuration:**
- `config/defaults.env.example`: Template for `~/.config/llama-server/defaults.env`
- `config/models.tsv.example`: Template for `~/.config/llama-server/models.tsv`

**Core Logic:**
- `web/app.py` `Manager` class: All dashboard business logic
- `bin/llama-model` `start_server()`: Model launch with auto-fit
- `scripts/glyphos_openai_gateway.py` `GatewayHandler`: Request pipeline

**Testing:**
- `tests/test_phase0_contracts.py`: Python unittest for web contracts
- `tests/test_portability.sh`: Bash tests for binary selection, install flows

## Naming Conventions

**Files:**
- CLI scripts: `llama-model-*` (kebab-case)
- Python modules: `snake_case.py`
- Test files: `test_*.py`, `test_*.sh`
- Config examples: `*.example`

**Environment Variables:**
- Server config: `LLAMA_SERVER_*`
- Model manager config: `LLAMA_MODEL_*`
- Gateway config: `LLAMA_MODEL_GATEWAY_*`
- Claude gateway: `CLAUDE_GATEWAY_*`
- Client-specific: `OPENCODE_*`, `OPENCLAW_*`, `GLYPHOS_*`

**API Routes:**
- Pattern: `/api/<resource>/<action>` (e.g., `/api/models/save`, `/api/downloads/cancel`)
- GET: `/api/state`, `/api/logs`, `/api/glyphos/telemetry`
- POST: All mutation endpoints

## Where to Add New Code

**New CLI Command:**
- Add case branch in `bin/llama-model` main dispatch
- Add usage text in `usage()` function
- Add bash function at appropriate location

**New API Endpoint:**
- Add route in `web/app.py` `AppHandler.do_GET()` or `do_POST()`
- Add schema to `API_POST_PAYLOAD_SCHEMAS` for POST endpoints
- Add handler method in `Manager` class

**New Gateway Feature:**
- Modify `scripts/glyphos_openai_gateway.py` `GatewayHandler` or pipeline functions
- Update `prepare_gateway_pipeline()` for new pipeline stages

**New Client Sync:**
- Add sync function to `scripts/integration_sync.py`
- Add subparser in `main()` function
- Wire up in `bin/llama-model` sync dispatch

**New Tests:**
- Python: Add test methods to `Phase0ContractTests` in `tests/test_phase0_contracts.py`
- Bash: Add test functions to `tests/test_portability.sh`

**Utilities:**
- Shared helpers: `bin/llama-model` for bash, `web/app.py` for Python
- New standalone scripts: `scripts/` directory

## Special Directories

**`integrations/context-mode-mcp/`:**
- Purpose: Optional MCP server for context retrieval
- Generated: `dist/`, `node_modules/` (gitignored)
- Contains: TypeScript source, esbuild config, Claude hook templates
- Build: `npm ci && npm run build`

**`runtime/`:**
- Purpose: Compiled `llama-server` binaries
- Generated: By `llama-model build-runtime`
- Committed: No (gitignored)
- Structure: `runtime/llama-server/<os>-<arch>-<backend>/llama-server` + `.compat.env`

**XDG State (`~/.local/state/llama-server/`):**
- Contains: `download-jobs.json`, `remote-models.json`, `current.env`, `host-capability.json`, etc.
- Created: At runtime by CLI or web server

---

*Structure analysis: 2026-04-30*
