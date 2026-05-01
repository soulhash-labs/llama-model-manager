# Coding Conventions

**Analysis Date:** 2026-04-30

## Naming Patterns

**Files:**
- CLI scripts: `llama-model` (no extension), `llama-model-web`
- Python modules: `snake_case.py` (e.g., `app.py`, `glyphos_openai_gateway.py`)
- Test files: `test_<subject>.py` or `test_<subject>.sh`
- Config templates: `<name>.example`
- State files: `kebab-case.json` (e.g., `download-jobs.json`, `host-capability.json`)

**Functions (Bash):**
- `snake_case` with descriptive names (e.g., `detect_host_os`, `probe_server_binary`, `write_state`)
- Predicate functions: `command_available`, `host_has_cuda_runtime`, `toggle_enabled`
- Die functions: `die()` for fatal errors

**Functions (Python):**
- `snake_case` (e.g., `parse_api_token`, `sanitize_alias`, `run_context_command`)
- Class methods follow same convention (e.g., `Manager.read_models()`, `Manager.write_models()`)
- Private hints: No underscore prefix convention consistently applied

**Variables:**
- Bash: `UPPER_SNAKE_CASE` for env/config vars (e.g., `LLAMA_SERVER_BIN`, `STATE_FILE`)
- Python: `snake_case` for locals, `UPPER_SNAKE_CASE` for constants (e.g., `PHASE0_SCHEMA_VERSION`)
- JavaScript: `camelCase` for functions/vars (e.g., `healthLabel()`, `state.data`)

**Types:**
- Python: Full type hints on functions and class methods
  - `def parse_env_file(self, path: Path) -> dict[str, str]:`
  - Uses `from __future__ import annotations` for forward refs
- TypeScript: Full typing in Context Mode MCP

## Code Style

**Formatting:**
- No linter/formatter config files (`.prettierrc`, `.eslintrc`) found in repo root
- Context Mode MCP uses `esbuild.config.ts` for build
- Python: PEP 8 style with 4-space indentation

**Bash conventions:**
- `set -euo pipefail` at top of scripts
- `local` for all function-scoped variables
- `printf` over `echo` for portability
- Quoted expansions: `"$variable"` consistently

**Python conventions:**
- `from __future__ import annotations` in all modules
- Type hints on all function signatures
- `raise SystemExit(code)` for script exits
- `raise ValueError` / `RuntimeError` for errors

## Import Organization

**Python:**
1. `from __future__ import annotations`
2. Standard library imports (grouped: builtins, stdlib modules)
3. No third-party imports in core (stdlib only)
4. Optional imports with try/except (e.g., `yaml` in `integration_sync.py`)

**Example from `web/app.py`:**
```python
from __future__ import annotations
import argparse
import importlib
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
```

**JavaScript:**
- No module system; single `app.js` file
- Global `state` object, helper functions, event handlers
- No imports; all code in one file

**Bash:**
- `source` for defaults file loading
- No module system; functions defined inline

## Error Handling

**Bash:**
- `die()` function: `printf 'error: %s\n' "$*" >&2; exit 1`
- `set -euo pipefail` for automatic failure on errors
- Command failures caught with `|| true` when non-fatal
- Subprocess errors captured to stderr and checked

**Python:**
- Custom exception classes: `ValidationError`, `CommandTimeoutError`
- Structured errors: `{"ok": false, "code": "error_code", "error": "message"}`
- JSON file I/O: Graceful fallback to defaults on parse errors
- Thread safety: `threading.RLock()` for shared state

**API:**
- POST payload validation: `API_POST_PAYLOAD_SCHEMAS` with `allowed`, `required`, `int_fields`, `str_fields`
- Unknown fields rejected with `code: "unknown_field"`
- Oversized bodies rejected with `code: "payload_too_large"`
- Unknown routes return `code: "unknown_route"`

## Logging

**Framework:**
- Bash: `printf` to stderr for errors, `printf` to stdout for output
- Python: Minimal `logging` usage, mostly `print()` for server messages
- Gateway: `sys.stderr.write()` for gateway logs

**Patterns:**
- CLI output: `key: value` format for machine parsing
- Server logs: Timestamped stderr output
- Gateway telemetry: JSON state file with counters

## Comments

**When to Comment:**
- Bash: Inline comments explaining shell workarounds
- Python: Docstrings on custom exception classes, inline comments for complex logic
- Self-documenting variable/function names preferred

**Style:**
- Bash: `# User-tunable runtime defaults live here, not in the wrapper itself.`
- Python: `"""Structured validation failure for request/route payload validation."""`

## Function Design

**Bash:**
- Single-purpose functions, typically < 50 lines
- Heavy use of helper functions for composition
- Global state for shared variables (e.g., `SELECTED_LLAMA_SERVER_BIN`)
- Return 0 for success, non-zero for failure

**Python:**
- `Manager` class as central orchestrator (~2000+ lines)
- Methods typically 10-50 lines
- Helper functions at module level for pure operations
- Return dicts/strings, raise exceptions for errors

**JavaScript:**
- Small utility functions (2-10 lines)
- Rendering functions return DOM manipulations
- State managed in global `state` object

## Module Design

**Exports:**
- Bash: Functions exposed via `source` in tests
- Python: `Manager` class and module-level functions
- JavaScript: No module system; global scope

**No barrel files** - each file is standalone

**Atomic file writes:**
- Pattern: Write to temp file, then `temp_path.replace(path)`
- Used in: `Manager.write_json_store()`, `write_json()` in `integration_sync.py`

---

*Convention analysis: 2026-04-30*
