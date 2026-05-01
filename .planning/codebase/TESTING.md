# Testing Patterns

**Analysis Date:** 2026-04-30

## Test Framework

**Runner:**
- **Python `unittest`** - Standard library
- **Bash** - Custom framework with `assert_contains`, `assert_not_contains`, `fail`

**Assertion Library:**
- Python: `unittest.TestCase` assertions (`assertEqual`, `assertTrue`, `assertIn`, `assertIsInstance`)
- Bash: String matching with `[[ "$haystack" == *"$needle"* ]]`

**Run Commands:**
```bash
python -m unittest tests.test_phase0_contracts     # Run all Python tests
bash tests/test_portability.sh                     # Run all Bash tests
python -m unittest tests.test_phase0_contracts     # Coverage via unittest (no coverage tool)
```

## Test File Organization

**Location:**
- Co-located at repo root under `tests/`
- `tests/test_phase0_contracts.py` - Python unittest for web API contracts
- `tests/test_portability.sh` - Bash integration tests for CLI

**Naming:**
- `test_<subject>.py` for Python
- `test_<subject>.sh` for Bash

**Structure:**
```
tests/
├── test_phase0_contracts.py    # Phase0ContractTests class
└── test_portability.sh         # test_* functions sourced and executed
```

## Test Structure

**Python Suite Organization (`test_phase0_contracts.py`):**
```python
class Phase0ContractTests(unittest.TestCase):
    def make_manager(self, tmpdir: str) -> object:
        # Creates isolated Manager with temp XDG dirs
        env = {
            "HOME": str(Path(tmpdir) / "home"),
            "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
            "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
        }
        # Mock environment, return Manager instance
        return WEB_APP.Manager(ROOT_DIR / "web")

    def start_app_server(self, manager: object) -> ThreadingHTTPServer:
        # Starts real HTTP server on random port
        # Registers cleanup via self.addCleanup()
        return server

    def test_unknown_post_field_is_rejected_with_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.post_json_raw(f"{api_base}/api/downloads/policy", {...})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertEqual(response["code"], "unknown_field")
```

**Bash Suite Organization (`test_portability.sh`):**
```bash
test_host_match_accepts_bundled_backend() {
    local tmp output
    tmp="$(mktemp -d)"
    make_env "$tmp"
    make_bundle "$tmp/runtime" "linux-x86_64-cuda" "cuda" "LLAMA_BUNDLE_CUDA_CC=8.6"
    output="$(run_doctor "$tmp" LLAMA_HOST_OS=linux ...)"
    assert_contains "$output" "binary_ok: yes"
}

# All test_* functions defined, then sourced by bin/llama-model or called directly
```

**Patterns:**
- Setup: `tempfile.TemporaryDirectory()` for Python, `mktemp -d` for Bash
- Isolation: Override `HOME`, `XDG_*` env vars per test
- Teardown: `self.addCleanup()` for Python, temp dirs auto-cleaned
- Real HTTP servers started on random ports for API tests

## Mocking

**Framework:** Python `unittest.mock`

**Patterns:**
```python
from unittest import mock

# Environment variable mocking
with mock.patch.dict(os.environ, {"LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1"}, clear=True):
    self.assertEqual(gateway.context_status(), ("missing", False))

# Module attribute mocking
with mock.patch.object(gateway, "APP_ROOT", app_root):
    ...

# CLI method mocking (replace subprocess calls)
manager.run_cli = lambda command, *args: outputs[command]

# sys.modules manipulation for package import testing
sys.modules["glyphos_ai"] = stale_package
self.addCleanup(lambda: sys.modules.pop("glyphos_ai", None))
```

**What to Mock:**
- `subprocess.run` via `manager.run_cli` lambda
- Environment variables via `mock.patch.dict`
- Module attributes via `mock.patch.object`
- External package imports via `sys.modules` manipulation

**What NOT to Mock:**
- File I/O - uses real temp directories
- HTTP handling - starts real servers on random ports
- JSON parsing - uses real `json` module

## Fixtures and Factories

**Test Data:**
- Inline construction in each test
- No centralized fixtures file
- Temp directory trees built per test:

```python
def make_manager(self, tmpdir: str) -> object:
    env = {
        "HOME": str(Path(tmpdir) / "home"),
        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
        "LLAMA_SERVER_RUNTIME_DIR": str(Path(tmpdir) / "runtime"),
    }
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    config_dir = Path(env["XDG_CONFIG_HOME"]) / "llama-server"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "defaults.env").write_text(...)
```

**Location:** No shared fixtures; each test is self-contained

## Coverage

**Requirements:** None enforced (no coverage tool configured)

**View Coverage:** No coverage command available

## Test Types

**Unit Tests:**
- Python: `test_phase0_contracts.py` - Tests Manager class methods, API route wiring, state transitions, download lifecycle, glyphos telemetry
- Bash: `test_portability.sh` - Tests binary selection, CUDA CC matching, auto-fit logic, mmproj validation, install flows, sync commands

**Integration Tests:**
- Python: Real HTTP server tests with `ThreadingHTTPServer`
- Bash: Real CLI invocation with isolated environments

**E2E Tests:**
- Not used - Bash tests cover CLI end-to-end with mocked subsystems

## Common Patterns

**Async Testing (Python threading):**
```python
def test_scheduler_starts_next_queued_download_when_slot_opens(self):
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    worker.start()
    self.addCleanup(release.set)
    self.addCleanup(worker.join, 1)

    # Start download with blocked worker
    manager.upsert_download_job({...})
    manager._register_download_controls("active-a", thread=worker)

    # Queue another download
    queued = manager.start_remote_download({...})
    self.assertEqual(queued["status"], "queued")

    # Release worker, verify scheduler picks up queued job
    release.set()
```

**Error Testing:**
```python
def test_download_api_state_transitions_return_structured_invalid_request(self):
    # Test invalid state transitions
    status, response = self.post_json_raw(f"{api_base}/api/downloads/cancel", {"id": "missing"})
    self.assertEqual(status, HTTPStatus.BAD_REQUEST)
    self.assertEqual(response["code"], "invalid_request")

    # Test valid transitions with pre-seeded data
    manager.write_json_store(manager.download_jobs_file, {
        "items": [
            {"id": "queued-one", "status": "queued", ...},
            {"id": "done-with-partial", "status": "failed", ...},
        ],
    })
    status, response = self.post_json_raw(f"{api_base}/api/downloads/resume", {"id": "done-with-partial"})
    self.assertEqual(status, HTTPStatus.OK)
```

**Route Table Testing (mock manager):**
```python
class RouteTableManager:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
    def search_remote_models(self, payload):
        self.calls.append(("search_remote_models", dict(payload)))
        return {"query": payload.get("query"), "items": []}

# Verify all routes wired correctly
manager = RouteTableManager()
app_server = self.start_app_server(manager)
for path, payload, method_name, response_key in cases:
    response = self.post_json(f"{api_base}{path}", payload)
    self.assertTrue(response["ok"], path)
self.assertEqual([m for m, _ in manager.calls], expected_methods)
```

---

*Testing analysis: 2026-04-30*
