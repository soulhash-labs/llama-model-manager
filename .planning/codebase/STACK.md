# Technology Stack

**Analysis Date:** 2026-04-30

## Languages

**Primary:**
- **Bash** - CLI wrapper (`bin/llama-model`, `bin/llama-model-web`, `install.sh`)
- **Python 3** - Web server (`web/app.py`), gateways (`scripts/*.py`), tests

**Secondary:**
- **JavaScript (ES6+)** - Browser frontend (`web/app.js`)
- **TypeScript** - Context Mode MCP integration (`integrations/context-mode-mcp/src/`)
- **HTML/CSS** - Dashboard markup and styling

## Runtime

**Environment:**
- Python 3.10+ (uses `from __future__ import annotations`, `dict[str, str]` syntax)
- Bash 4+ (uses associative arrays, `${var,,}` lowercase)
- Node.js 18+ (for Context Mode MCP build only)

**Package Manager:**
- System Python (no `requirements.txt` - stdlib only for core)
- npm for Context Mode MCP (`integrations/context-mode-mcp/package.json`)
- Lockfile: `package-lock.json` present in context-mode-mcp

## Frameworks

**Core:**
- **Python `http.server`** - `BaseHTTPRequestHandler` + `ThreadingHTTPServer` (stdlib)
- No third-party web framework; raw HTTP handling

**Testing:**
- **Python `unittest`** - Standard library test runner
- **Bash** - Custom test framework in `test_portability.sh`

**Build/Dev:**
- **esbuild** - Context Mode MCP bundler
- **GNU Make** - Not used; direct shell scripts for builds

## Key Dependencies

**Critical:**
- **llama.cpp** - External inference runtime, cloned and built by `llama-model build-runtime`
  - Source: `https://github.com/ggml-org/llama.cpp.git`
  - Ref: `b8851` (configurable via `LLAMA_CPP_REF`)

**Infrastructure:**
- **GlyphOS AI Compute** - Bundled Python package at `integrations/public-glyphos-ai-compute/`
  - Provides adaptive routing, glyph encoding, AI compute clients
- **PyYAML** - Optional dependency for GlyphOS YAML config sync (`scripts/integration_sync.py`)

## External Services

**Hugging Face:**
- Remote model search via HF API
- Direct artifact downloads for GGUF files

**Local Endpoints:**
- `llama.cpp` server: `http://127.0.0.1:8081/v1` (default)
- LMM Gateway: `http://127.0.0.1:4010/v1`
- Claude Gateway: `http://127.0.0.1:4000`
- Dashboard: `http://127.0.0.1:8765/`

## Configuration

**Environment:**
- `~/.config/llama-server/defaults.env` - Shell-sourced config file
- Override via `export LLAMA_*` before CLI/dashboard launch
- XDG directories: `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_DATA_HOME`

**Build:**
- `scripts/build-llama-server.sh` - Wraps llama.cpp cmake build
- Backends: `auto`, `cpu`, `cuda`, `vulkan`, `metal`

## Platform Requirements

**Development:**
- Python 3.10+, Bash 4+, GNU coreutils
- For building: `git`, `cmake`, C++ compiler
- GPU builds: CUDA toolkit, Vulkan SDK, or Xcode (macOS)

**Production:**
- User-space deployment via `install.sh`
- Optional: `systemd --user` for dashboard background service
- Target: Linux (primary), macOS (supported)
- No root access required

---

*Stack analysis: 2026-04-30*
