---
phase: 02-run-records
plan: 03
type: execute
wave: 2
depends_on: ["02-run-records-01"]
files_modified:
  - web/app.py
  - web/demo_state.json
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [RUNREC-02]
user_setup: []

must_haves:
  truths:
    - "Dashboard API /state returns real run history when gateway has recorded runs"
    - "Demo mode loads demo state from a separate JSON file, not hardcoded in Python"
    - "When no runs exist, dashboard returns empty run history (not fake data) in production mode"
    - "Run history appears in the state payload under a new 'run_history' key"
  artifacts:
    - path: "web/demo_state.json"
      provides: "Demo state data extracted from hardcoded DEMO_STATE/DEMO_DISCOVERY/DEMO_LOG"
      contains: '"title"'
    - path: "web/app.py"
      provides: "Real run history in state() method, demo state loaded from JSON file"
      contains: "run_record_store|demo_state.json"
  key_links:
    - from: "web/app.py"
      to: "scripts/lmm_storage.py:JsonRunRecordStore"
      via: "reads run records from same file gateway writes"
      pattern: "JsonRunRecordStore|lmm_run_records"
    - from: "web/app.py"
      to: "web/demo_state.json"
      via: "loads demo state only when self.demo is True"
      pattern: "demo_state.json"
---

<objective>
Wire the dashboard to read real run history from the gateway's run record store and move hardcoded demo state to a separate JSON file.

Purpose: Kill the 100+ lines of DEMO_STATE/DEMO_DISCOVERY/DEMO_LOG hardcoded in web/app.py, replace with file-loaded demo state and real run history in production mode.
Output: web/demo_state.json created, web/app.py demo state extracted, run history surfaced in dashboard API
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@web/app.py (lines 254-411 for DEMO_STATE, DEMO_DISCOVERY, DEMO_LOG)
@web/app.py (lines 2836-2890 for state() demo mode)
@scripts/lmm_storage.py
@scripts/lmm_types.py
</context>

<interfaces>
<!-- Key contracts the executor needs. -->

From scripts/lmm_storage.py:
```python
class JsonRunRecordStore:
    def __init__(self, path: Path, *, recent_limit: int = 50) -> None: ...
    def list_recent(self, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]: ...
    def latest_completed(self) -> dict[str, Any] | None: ...
    def count_by_status(self) -> dict[str, int]: ...
```

From web/app.py Manager.state() (current demo mode, lines 2836-2889):
```python
def state(self) -> dict[str, Any]:
    if self.demo:
        return {
            **DEMO_STATE,
            "demo": True,
            "gateway_requests": {"recent_requests": [], "counters": {}},
            ...
        }
    # Production mode: calls CLI, builds real state dict
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Extract DEMO_STATE/DEMO_DISCOVERY/DEMO_LOG to web/demo_state.json</name>
  <files>web/demo_state.json</files>
  <action>
Create web/demo_state.json containing the current hardcoded demo data as a JSON object:

```json
{
  "state": { ... },   // current DEMO_STATE dict (lines 254-385)
  "discovery": [...], // current DEMO_DISCOVERY list (lines 387-406)
  "log": "..."        // current DEMO_LOG string (lines 408-411)
}
```

Use `json.dumps(DEMO_STATE, indent=2)` style formatting. Ensure all dict values that are currently Python-only (like `Path` objects or non-JSON-serializable types) are converted to strings. The DEMO_STATE dict at lines 254-385 is already JSON-compatible — it uses string values throughout.

After creating the file, verify it's valid JSON: `python3 -c "import json; json.load(open('web/demo_state.json'))"`
  </action>
  <verify>
    <automated>python3 -c "
import json
with open('web/demo_state.json') as f:
    data = json.load(f)
assert 'state' in data
assert 'discovery' in data
assert 'log' in data
assert data['state']['title'] == 'Llama Model Manager'
assert len(data['discovery']) == 2
assert 'model loaded' in data['log']
print('demo_state.json OK')
"</automated>
  </verify>
  <done>web/demo_state.json contains all three demo sections, is valid JSON, and matches the current hardcoded values</done>
</task>

<task type="auto">
  <name>Task 2: Wire web/app.py to load demo state from JSON and surface run history</name>
  <files>web/app.py</files>
  <action>
Modify web/app.py:

1. **Load demo state from file**: Replace the hardcoded DEMO_STATE, DEMO_DISCOVERY, DEMO_LOG with a `_load_demo_state()` function:
   ```python
   def _load_demo_state() -> dict[str, Any]:
       demo_path = Path(__file__).parent / "demo_state.json"
       if demo_path.exists():
           with open(demo_path) as f:
               return json.load(f)
       # Fallback to empty demo structure if file is missing
       return {"state": {}, "discovery": [], "log": ""}

   _DEMO = _load_demo_state()
   DEMO_STATE = _DEMO["state"]
   DEMO_DISCOVERY = _DEMO["discovery"]
   DEMO_LOG = _DEMO["log"]
   ```
   This preserves all existing code that references DEMO_STATE, DEMO_DISCOVERY, DEMO_LOG — zero breaking changes.

2. **Add run history to state() method**: In the production mode branch of `state()` (after line 2890), add:
   ```python
   # Run history from gateway run record store
   run_history = self._load_run_history()
   ```
   And in the demo mode branch, add:
   ```python
   "run_history": {"records": [], "total": 0, "by_status": {}},
   ```

3. **Add _load_run_history() method to Manager class**:
   ```python
   def _load_run_history(self) -> dict[str, Any]:
       try:
           store_path = Path(os.environ.get(
               "LMM_RUN_RECORDS_FILE",
               str(Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json")
           )).expanduser()
           if not store_path.exists():
               return {"records": [], "total": 0, "by_status": {}}
           from lmm_storage import JsonRunRecordStore
           store = JsonRunRecordStore(store_path)
           records = store.list_recent(limit=20)
           return {
               "records": records,
               "total": store.total_records(),
               "by_status": store.count_by_status(),
               "latest_completed": store.latest_completed(),
           }
       except Exception:
           return {"records": [], "total": 0, "by_status": {}, "error": "run_history_unavailable"}
   ```

   Make the import robust: use `sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))` before importing lmm_storage, matching the pattern used elsewhere in app.py.

4. **Add run history to the state return dict** in both demo and production modes. The production state() method returns a large dict (lines 2899+). Add `"run_history": self._load_run_history()` to the return value.

5. **Do NOT remove DEMO_STATE** — it's still used by demo mode. The goal is to externalize it to a file (Task 1) and make production mode use real data (this task).

Keep changes focused: this task touches web/app.py only for the load function, demo state extraction, and run history surface. No other files.
  </action>
  <verify>
    <automated>python3 -c "
import sys; sys.path.insert(0, 'web')
from app import DEMO_STATE, DEMO_DISCOVERY, DEMO_LOG
assert isinstance(DEMO_STATE, dict)
assert DEMO_STATE['title'] == 'Llama Model Manager'
assert isinstance(DEMO_DISCOVERY, list)
assert isinstance(DEMO_LOG, str)
print('Demo state loads from file OK')
"</automated>
  </verify>
  <done>DEMO_STATE/DEMO_DISCOVERY/DEMO_LOG load from web/demo_state.json, _load_run_history() method exists and returns correct structure, production state includes run_history key</done>
</task>

<task type="auto">
  <name>Task 3: Add contract tests for demo state loading and run history</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_demo_state_loads_from_json_file` — Verify web/demo_state.json exists, is valid JSON, and contains 'state', 'discovery', 'log' keys.

2. `test_demo_state_matches_hardcoded_values` — Verify the JSON file's state dict has the same title, brand, and model count as the original hardcoded DEMO_STATE.

3. `test_manager_load_run_history_returns_empty_when_no_file` — When LMM_RUN_RECORDS_FILE doesn't exist, _load_run_history() returns {"records": [], "total": 0, "by_status": {}}.

4. `test_manager_load_run_history_returns_records_when_file_exists` — Create a temp run record store with test records, set LMM_RUN_RECORDS_FILE env var, verify _load_run_history() returns the records.

5. `test_demo_mode_state_includes_run_history_key` — In demo mode, the state() response includes a "run_history" key with empty records.

Use the existing test patterns: import web/app via load_script_module or direct import, use tempfile for run record files, mock env vars with mock.patch.dict.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_demo_state_loads_from_json_file tests.test_phase0_contracts.Phase0ContractTests.test_demo_state_matches_hardcoded_values tests.test_phase0_contracts.Phase0ContractTests.test_manager_load_run_history_returns_empty_when_no_file tests.test_phase0_contracts.Phase0ContractTests.test_manager_load_run_history_returns_records_when_file_exists tests.test_phase0_contracts.Phase0ContractTests.test_demo_mode_state_includes_run_history_key -v 2>&1</automated>
  </verify>
  <done>All 5 new tests pass, no existing tests broken</done>
</task>

</tasks>

<verification>
- web/demo_state.json contains all demo data (DEMO_STATE, DEMO_DISCOVERY, DEMO_LOG)
- web/app.py loads demo state from file, DEMO_STATE/DEMO_DISCOVERY/DEMO_LOG still accessible
- Production mode state() includes real run history from gateway run record store
- Demo mode state() includes empty run_history placeholder
- _load_run_history() is robust: returns empty dict when store file doesn't exist or import fails
</verification>

<success_criteria>
- Demo state externalized to JSON file with no functional changes to demo mode
- Production dashboard API includes run_history with records, total, by_status, latest_completed
- Run history reads from same file gateway writes to (no duplication)
- All new tests pass, no existing tests broken
</success_criteria>

<output>
After completion, create `.planning/phases/02-run-records/02-run-records-03-SUMMARY.md`
</output>
