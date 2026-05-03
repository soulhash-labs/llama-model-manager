---
phase: 02-run-records
plan: 02
type: execute
wave: 2
depends_on: ["02-run-records-01"]
files_modified:
  - scripts/glyphos_openai_gateway.py
  - scripts/lmm_health.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [RUNREC-03, HEALTH-01]
user_setup: []

must_haves:
  truths:
    - "Gateway creates a RunRecord at request start and finalizes it on response completion"
    - "Failed requests are recorded with error_message and FAILED status"
    - "Client disconnects are recorded with CANCELLED status"
    - "/readyz endpoint returns readiness based on backend availability"
    - "Health checker reports component-level status (backend, storage, context)"
  artifacts:
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "RunRecord emission in do_POST handler, /readyz endpoint"
      contains: "RunRecord("
    - path: "scripts/lmm_health.py"
      provides: "HealthChecker with ComponentHealth dataclass"
      exports: ["HealthChecker", "ComponentHealth", "RuntimeReport"]
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "scripts/lmm_storage.py:JsonRunRecordStore"
      via: "record_run_store.append_record(record_dict)"
      pattern: "run_record_store|JsonRunRecordStore"
    - from: "scripts/glyphos_openai_gateway.py"
      to: "scripts/lmm_health.py:HealthChecker"
      via: "/readyz handler calls checker.is_ready()"
      pattern: "HealthChecker|/readyz"
---

<objective>
Wire the gateway to emit structured RunRecords per request and add standardized health check endpoints.

Purpose: Replace ad-hoc telemetry recording with typed run records, and add liveness/readiness distinction for orchestrator integration.
Output: Gateway writes RunRecords to storage, /readyz endpoint added, lmm_health.py created
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@scripts/glyphos_openai_gateway.py
@scripts/lmm_storage.py
@scripts/lmm_config.py
@scripts/lmm_errors.py
@scripts/lmm_types.py
</context>

<interfaces>
<!-- Key types from Plan 01 that Plan 02 consumes. -->

From scripts/lmm_types.py:
```python
class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ExitResult(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    USER_CANCELLED = "user_cancelled"
    TIMEOUT_EXPIRED = "timeout"
    PROVIDER_ERROR = "provider_error"

@dataclass
class RunRecord:
    id: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    prompt: str
    model: str
    provider: str
    status: RunStatus = RunStatus.PENDING
    exit_result: ExitResult | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    route_target: str = ""
    route_reason_code: str = ""
    completion_chars: int = 0
    harness: str = ""
    context_status: str = ""
    context_used: bool = False
    def to_dict(self) -> dict[str, Any]: ...
```

From scripts/lmm_storage.py:
```python
class JsonRunRecordStore:
    def __init__(self, path: Path, *, recent_limit: int = 50) -> None: ...
    def append_record(self, record: dict[str, Any]) -> list[dict[str, Any]]: ...
```

From scripts/lmm_config.py:
```python
@dataclass(frozen=True)
class GatewayConfig:
    host: str
    port: int
    backend_base_url: str
    model_id: str
    state_file: Path
    sse_heartbeat_seconds: float
    telemetry_recent_limit: int
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create lmm_health.py health checker module</name>
  <files>scripts/lmm_health.py</files>
  <action>
Create scripts/lmm_health.py with:

1. `ComponentHealth` dataclass: `name: str`, `status: str` ("healthy"/"unhealthy"/"degraded"), `message: str = ""`

2. `RuntimeReport` dataclass with `version`, `uptime_seconds`, `components: dict`, `timestamp`. Has `to_dict()` method.

3. `HealthChecker` class:
   - `__init__(self, backend_url: str, config)` — stores backend URL and LMMConfig, records start_time
   - `check_all() -> dict[str, ComponentHealth]` — checks all components
   - `_check_backend() -> ComponentHealth` — HTTP GET to {backend_url}/models with 5s timeout. "healthy" if 200, "unhealthy" on error.
   - `_check_storage() -> ComponentHealth` — verifies run record store path is writable (create parent dirs, write temp file, delete). "healthy" if writable.
   - `_check_context() -> ComponentHealth` — checks context pipeline status (reuse existing context_status() function from gateway). "healthy" if ready, "degraded" if missing components, "unhealthy" if error.
   - `is_healthy() -> bool` — true if no component is "unhealthy"
   - `is_ready() -> bool` — true if all components are "healthy" (not degraded)
   - `get_runtime_report() -> RuntimeReport` — uptime + component status

Do NOT add Flask routes — LMM uses stdlib http.server. The checker is pure logic; routes are added to the gateway in Task 2.

Keep it stdlib-only. Use `urllib.request` for backend check.
  </action>
  <verify>
    <automated>python3 -c "
import sys; sys.path.insert(0, 'scripts')
from lmm_health import HealthChecker, ComponentHealth, RuntimeReport
checker = HealthChecker(backend_url='http://127.0.0.1:9999')
checks = checker.check_all()
assert 'backend' in checks
assert 'storage' in checks
assert 'context' in checks
for name, health in checks.items():
    assert health.status in ('healthy', 'unhealthy', 'degraded'), f'{name}: {health.status}'
healthy = checker.is_healthy()
assert isinstance(healthy, bool)
ready = checker.is_ready()
assert isinstance(ready, bool)
report = checker.get_runtime_report()
assert report.uptime_seconds >= 0
assert 'backend' in report.to_dict()['components']
print('lmm_health OK')
"</automated>
  </verify>
  <done>HealthChecker checks backend, storage, context; is_healthy/is_ready return correct booleans; RuntimeReport serializes correctly</done>
</task>

<task type="auto">
  <name>Task 2: Wire gateway to emit RunRecords and add /readyz endpoint</name>
  <files>scripts/glyphos_openai_gateway.py</files>
  <action>
Modify scripts/glyphos_openai_gateway.py to:

1. **Import new modules**: `from lmm_types import RunRecord, RunStatus, ExitResult` and `from lmm_health import HealthChecker`

2. **Add run record store factory**: Add `run_record_store()` function mirroring `telemetry_store()`:
   ```python
   def run_record_store() -> JsonRunRecordStore:
       config = load_lmm_config_from_env().gateway
       run_path = Path(os.environ.get("LMM_RUN_RECORDS_FILE", str(
           Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json"
       ))).expanduser()
       return JsonRunRecordStore(run_path, recent_limit=config.telemetry_recent_limit)
   ```

3. **Add HealthChecker to LMMOpenAIGateway**:
   - Add `self._health = HealthChecker(backend_url=backend_base_url, config=load_lmm_config_from_env())` to `__init__`
   - Add `self._health` to the server instance in `create_gateway_server()`
   - Add `health_check()` method that returns `checker.check_all()`

4. **Add /readyz endpoint to GatewayHandler.do_GET**:
   ```python
   if path == "/readyz":
       checker = self.gateway().health_checker
       if checker.is_ready():
           json_response(self, 200, {"status": "ready"})
       else:
           json_response(self, 503, {"status": "not_ready", "components": checker.check_all()})
       return
   ```

5. **Add /-/runtime/report endpoint** to GatewayHandler.do_GET:
   ```python
   if path == "/-/runtime/report":
       report = self.gateway().health_checker.get_runtime_report()
       json_response(self, 200, report.to_dict())
       return
   ```

6. **Emit RunRecord in do_POST handler**: Replace the current `record: dict` approach with a typed RunRecord:
   - At the start of do_POST, create a RunRecord with status=RUNNING, started_at set, prompt and model populated
   - On success (stream or non-stream): set status=COMPLETED, exit_result=SUCCESS, completed_at, duration_ms, completion_chars
   - On InvalidRequestError: set status=FAILED, exit_result=ERROR
   - On gateway error (503): set status=FAILED, exit_result=PROVIDER_ERROR
   - On client disconnect: set status=CANCELLED, exit_result=USER_CANCELLED
   - Call `run_record_store().append_record(record.to_dict())` alongside the existing `safe_record_gateway_request(record)` — don't remove telemetry recording, keep both for backward compatibility

   The RunRecord should be created from the existing `record` dict that's already being assembled. Convert the dict to a RunRecord at the end of each branch and emit it.
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/glyphos_openai_gateway.py scripts/lmm_health.py && echo "compiles OK"</automated>
  </verify>
  <done>Gateway compiles, /readyz endpoint added, /-/runtime/report added, RunRecord emitted alongside existing telemetry</done>
</task>

<task type="auto">
  <name>Task 3: Add contract tests for health checks and run record emission</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_health_checker_checks_backend_availability` — HealthChecker with a reachable mock backend reports "healthy" for backend component.

2. `test_health_checker_checks_backend_unreachable` — HealthChecker with an unreachable backend URL reports "unhealthy" for backend.

3. `test_health_checker_readyz_requires_all_healthy` — is_ready() returns False when any component is degraded or unhealthy.

4. `test_gateway_readiness_endpoint_returns_ready` — GET /readyz on a gateway with a healthy backend returns 200 {"status": "ready"}.

5. `test_gateway_readiness_endpoint_returns_not_ready` — GET /readyz on a gateway with an unreachable backend returns 503.

6. `test_gateway_emits_run_record_on_success` — POST /v1/chat/completions creates a RunRecord with status=completed and exit_result=success in the run record store.

7. `test_gateway_emits_run_record_on_failure` — POST /v1/chat/completions when backend fails creates a RunRecord with status=failed.

8. `test_gateway_runtime_report_endpoint` — GET /-/runtime/report returns uptime and component status.

Use the existing test patterns: mock HTTP server for backend, temp directories for storage, load_script_module for imports.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_health_checker_checks_backend_availability tests.test_phase0_contracts.Phase0ContractTests.test_health_checker_checks_backend_unreachable tests.test_phase0_contracts.Phase0ContractTests.test_gateway_readiness_endpoint_returns_ready tests.test_phase0_contracts.Phase0ContractTests.test_gateway_emits_run_record_on_success tests.test_phase0_contracts.Phase0ContractTests.test_gateway_emits_run_record_on_failure tests.test_phase0_contracts.Phase0ContractTests.test_gateway_runtime_report_endpoint -v 2>&1</automated>
  </verify>
  <done>All 6 new tests pass, existing gateway tests still pass</done>
</task>

</tasks>

<verification>
- HealthChecker checks backend via HTTP, storage writability, context pipeline status
- Gateway has /healthz (existing), /readyz (new), /-/runtime/report (new) endpoints
- Every POST /v1/chat/completions creates a typed RunRecord in the run record store
- RunRecord is emitted alongside existing telemetry (backward compatible)
- Health checker and run record store work together — store path verified by health check
</verification>

<success_criteria>
- HealthChecker component checks return correct status for all conditions
- /readyz distinguishes ready (all healthy) from not_ready (any unhealthy/degraded)
- Gateway emits RunRecord on every request path (success, failure, disconnect)
- Run record store file is created and populated with correct schema
- All new tests pass, no existing tests broken
</success_criteria>

<output>
After completion, create `.planning/phases/02-run-records/02-run-records-02-SUMMARY.md`
</output>
