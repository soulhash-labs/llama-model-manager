---
phase: 02-run-records
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/lmm_types.py
  - scripts/lmm_storage.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [RUNREC-01]
user_setup: []

must_haves:
  truths:
    - "RunRecord dataclass captures UUID, timestamps, status, model, duration, and result"
    - "Run records persist to a bounded JSON file with atomic writes and fcntl locking"
    - "Store returns recent runs in reverse-chronological order with configurable limit"
    - "Store supports filtering by status (completed, failed, running, cancelled)"
  artifacts:
    - path: "scripts/lmm_types.py"
      provides: "RunRecord, RunStatus, ExitResult dataclasses and enums"
      exports: ["RunRecord", "RunStatus", "ExitResult"]
    - path: "scripts/lmm_storage.py"
      provides: "JsonRunRecordStore extending StorageAdapter protocol"
      contains: "class JsonRunRecordStore"
  key_links:
    - from: "scripts/lmm_storage.py"
      to: "scripts/lmm_types.py"
      via: "import RunRecord, RunStatus"
      pattern: "from lmm_types import.*RunRecord"
---

<objective>
Create the run record data model and a bounded JSON storage adapter for gateway run history.

Purpose: Provide the typed foundation that Plan 02 (gateway emission) and Plan 03 (dashboard consumption) depend on.
Output: lmm_types.py (RunRecord, RunStatus, ExitResult) and JsonRunRecordStore in lmm_storage.py
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/codebase/ARCHITECTURE.md
@.planning/codebase/CONCERNS.md
@.planning/codebase/STACK.md
@scripts/lmm_storage.py
@scripts/lmm_errors.py
@scripts/lmm_config.py
</context>

<interfaces>
<!-- Key types and contracts from Phase 1 that Plan 01 builds on. -->

From scripts/lmm_storage.py:
```python
class StorageAdapter(Protocol):
    def read_state(self) -> dict[str, Any]: ...
    def append_event(self, record: dict[str, Any]) -> dict[str, Any]: ...

class JsonGatewayTelemetryStore:
    """Compatibility storage adapter for gateway telemetry JSON state."""
    def __init__(self, path: Path, *, recent_limit: int = 40) -> None: ...
    def read_state(self) -> dict[str, Any]: ...
    def append_event(self, record: dict[str, Any]) -> dict[str, Any]: ...
```

From scripts/lmm_errors.py:
```python
class LMMError(Exception):
    error_type = "lmm_error"
    def __init__(self, message: str, **details: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create run record types (lmm_types.py)</name>
  <files>scripts/lmm_types.py</files>
  <action>
Create scripts/lmm_types.py with:

1. `RunStatus` enum: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED (matching Ace's ace/types.py pattern but without TIMEOUT — folded into FAILED for simplicity)

2. `ExitResult` enum: SUCCESS, ERROR, USER_CANCELLED, TIMEOUT_EXPIRED, PROVIDER_ERROR

3. `RunRecord` dataclass with these fields:
   - `id: str` — auto-generated via `uuid4().hex[:12]` (shorter than full UUID for CLI readability)
   - `created_at: str` — ISO 8601 timestamp, set in `__post_init__` if not provided
   - `started_at: str | None` — ISO 8601 or None
   - `completed_at: str | None` — ISO 8601 or None
   - `prompt: str` — the user message text (truncated to 4000 chars in `__post_init__`)
   - `model: str` — model identifier (e.g. "Qwen3.5-9B-Q8_0.gguf")
   - `provider: str` — provider target (e.g. "llamacpp", "openai", "anthropic")
   - `status: RunStatus` — defaults to PENDING
   - `exit_result: ExitResult | None` — defaults to None
   - `duration_ms: int | None` — computed from started_at/completed_at if both present
   - `error_message: str | None` — error text if failed
   - `route_target: str` — routing target from gateway (e.g. "llamacpp", "fallback")
   - `route_reason_code: str` — routing reason (e.g. "high_coherence_local")
   - `completion_chars: int` — response length
   - `harness: str` — User-Agent of the requesting client
   - `context_status: str` — context pipeline status
   - `context_used: bool` — whether context was retrieved

   Add `to_dict()` method that serializes enums to their `.value` strings.
   Add class method `from_dict(cls, data: dict) -> RunRecord` that parses enums from strings.
   Do NOT include `response` text in the record — the gateway already stores telemetry, and storing full responses in JSON would bloat the file. Only store `completion_chars` as a proxy.
  </action>
  <verify>
    <automated>python3 -c "
import sys; sys.path.insert(0, 'scripts')
from lmm_types import RunRecord, RunStatus, ExitResult
r = RunRecord(prompt='test', model='test.gguf', provider='llamacpp')
assert r.id is not None and len(r.id) == 12
assert r.status == RunStatus.PENDING
assert r.created_at is not None
d = r.to_dict()
assert d['status'] == 'pending'
r2 = RunRecord.from_dict(d)
assert r2.status == RunStatus.PENDING
print('lmm_types OK')
"</automated>
  </verify>
  <done>RunRecord serializes/deserializes correctly, enums round-trip, prompt truncates to 4000 chars, auto-generates ID and created_at</done>
</task>

<task type="auto">
  <name>Task 2: Add JsonRunRecordStore to lmm_storage.py</name>
  <files>scripts/lmm_storage.py</files>
  <action>
Extend scripts/lmm_storage.py with a new `JsonRunRecordStore` class:

```python
class JsonRunRecordStore:
    """Bounded JSON store for gateway run records."""
    
    def __init__(self, path: Path, *, recent_limit: int = 50) -> None:
        # path defaults to ~/.local/state/llama-server/lmm-run-records.json
        # recent_limit caps the number of stored records (default 50)
```

Methods:
- `append_record(record: dict[str, Any]) -> list[dict[str, Any]]` — atomically appends a run record to the store, caps to recent_limit, returns the updated recent list. Uses same `_lock()` and `_write_state()` pattern as JsonGatewayTelemetryStore.
- `list_recent(limit: int = 20, status: str | None = None) -> list[dict[str, Any]]` — returns recent records in reverse-chronological order (newest first), optionally filtered by status string.
- `get_record(record_id: str) -> dict[str, Any] | None` — retrieves a single record by ID.
- `latest_completed() -> dict[str, Any] | None` — returns the most recently completed run.
- `count_by_status() -> dict[str, int]` — returns counts per status value.
- `total_records() -> int` — total count of stored records.

File format:
```json
{
  "schema_version": 1,
  "updated_at": "2026-04-30T12:00:00Z",
  "records": [
    {"id": "...", "status": "completed", ...},
    ...
  ]
}
```

The `_lock()` and `_write_state()` methods should be shared with JsonGatewayTelemetryStore via a small `_FileLockedJsonStore` base class to avoid code duplication. Extract common file locking + atomic write logic into a private base class.
  </action>
  <verify>
    <automated>python3 -c "
import sys, tempfile; sys.path.insert(0, 'scripts')
from pathlib import Path
from lmm_storage import JsonRunRecordStore
with tempfile.TemporaryDirectory() as d:
    store = JsonRunRecordStore(Path(d)/'runs.json', recent_limit=3)
    store.append_record({'id': 'r1', 'status': 'completed', 'model': 'a.gguf', 'created_at': '2026-01-01T00:00:00Z'})
    store.append_record({'id': 'r2', 'status': 'failed', 'model': 'b.gguf', 'created_at': '2026-01-02T00:00:00Z'})
    store.append_record({'id': 'r3', 'status': 'completed', 'model': 'c.gguf', 'created_at': '2026-01-03T00:00:00Z'})
    store.append_record({'id': 'r4', 'status': 'completed', 'model': 'd.gguf', 'created_at': '2026-01-04T00:00:00Z'})
    recent = store.list_recent(limit=10)
    assert len(recent) == 3, f'expected 3, got {len(recent)}'  # capped at recent_limit
    assert recent[0]['id'] == 'r4'  # newest first
    completed = store.list_recent(status='completed')
    assert len(completed) == 2
    latest = store.latest_completed()
    assert latest['id'] == 'r4'
    print('JsonRunRecordStore OK')
"</automated>
  </verify>
  <done>Store appends records, caps to recent_limit, returns newest-first, filters by status, finds latest_completed, shares lock/write logic via base class</done>
</task>

<task type="auto">
  <name>Task 3: Add contract tests for run record types and store</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_run_record_round_trips_to_dict` — Create RunRecord, call to_dict(), call from_dict(), verify all fields match including enum values.

2. `test_run_record_truncates_long_prompt` — Create RunRecord with 8000-char prompt, verify prompt is truncated to 4000 chars.

3. `test_run_record_auto_generates_id_and_timestamp` — Create RunRecord without id or created_at, verify both are set.

4. `test_json_run_record_store_caps_recent_records` — Append N records where N > recent_limit, verify store only keeps recent_limit records.

5. `test_json_run_record_store_filters_by_status` — Append records with mixed statuses, filter by 'completed', verify only completed returned.

6. `test_json_run_record_store_latest_completed` — Verify latest_completed() returns the most recent completed run, not the most recent run overall.

7. `test_json_run_record_store_atomic_writes` — Verify the store uses temp file + replace pattern for atomic writes (check that .tmp files are never left behind).

Use the existing `load_script_module()` pattern to import lmm_types and lmm_storage in tests.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_run_record_round_trips_to_dict tests.test_phase0_contracts.Phase0ContractTests.test_run_record_truncates_long_prompt tests.test_phase0_contracts.Phase0ContractTests.test_run_record_auto_generates_id_and_timestamp tests.test_phase0_contracts.Phase0ContractTests.test_json_run_record_store_caps_recent_records tests.test_phase0_contracts.Phase0ContractTests.test_json_run_record_store_filters_by_status tests.test_phase0_contracts.Phase0ContractTests.test_json_run_record_store_latest_completed tests.test_phase0_contracts.Phase0ContractTests.test_json_run_record_store_atomic_writes -v 2>&1</automated>
  </verify>
  <done>All 7 new tests pass, no existing tests broken</done>
</task>

</tasks>

<verification>
- lmm_types.py exports RunRecord, RunStatus, ExitResult with to_dict/from_dict
- JsonRunRecordStore uses same atomic write + fcntl lock pattern as JsonGatewayTelemetryStore
- Common lock/write logic extracted to shared base class (no duplication)
- All new tests pass
- No existing tests broken
</verification>

<success_criteria>
- RunRecord dataclass serializes/deserializes correctly
- JsonRunRecordStore caps records, filters by status, finds latest completed
- Store uses atomic writes (temp file + replace) and fcntl locking
- Test coverage for types and store methods
</success_criteria>

<output>
After completion, create `.planning/phases/02-run-records/02-run-records-01-SUMMARY.md`
</output>
