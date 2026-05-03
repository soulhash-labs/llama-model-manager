---
phase: 03-receipts-notifications
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/lmm_receipts.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [RECEIPT-01]
user_setup: []

must_haves:
  truths:
    - "Each gateway request produces a receipt record with SHA-256 digests of request and response"
    - "Receipts are written as newline-delimited JSON to a bounded file"
    - "Receipt file caps at a configurable line limit, oldest entries dropped"
    - "Receipts are machine-readable audit trail — no full payloads stored"
  artifacts:
    - path: "scripts/lmm_receipts.py"
      provides: "Receipt dataclass, ReceiptEmitter with JSONL output"
      exports: ["Receipt", "ReceiptEmitter"]
  key_links:
    - from: "scripts/lmm_receipts.py"
      to: "scripts/lmm_storage.py"
      via: "shares atomic write + fcntl lock pattern"
      pattern: "from lmm_storage import|_FileLockedJsonStore"
---

<objective>
Create a receipt emitter that produces SHA-256-digested audit records per gateway request.

Purpose: Provide a lightweight, verifiable per-request audit trail without storing full payloads. Useful for debugging timeouts, upstream failures, client disconnects.
Output: lmm_receipts.py with Receipt dataclass and ReceiptEmitter
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@scripts/lmm_storage.py
@scripts/lmm_errors.py
@docs/ACE-PATTERN-TRANSFER-ANALYSIS.md (Pattern 8: Receipt Emitter)
</context>

<interfaces>
<!-- Key contracts from Phase 1 that this plan builds on. -->

From scripts/lmm_storage.py:
```python
class StorageAdapter(Protocol):
    def read_state(self) -> dict[str, Any]: ...
    def append_event(self, record: dict[str, Any]) -> dict[str, Any]: ...
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create Receipt dataclass and ReceiptEmitter</name>
  <files>scripts/lmm_receipts.py</files>
  <action>
Create scripts/lmm_receipts.py with:

1. `Receipt` dataclass:
   - `version: int = 1`
   - `run_id: str` — the gateway request ID (same as chatcmpl-lmm-* from stream_completion)
   - `route_target: str` — "llamacpp", "openai", "fallback", etc.
   - `route_reason_code: str` — routing reason
   - `model: str` — model identifier
   - `harness: str` — User-Agent
   - `status: str` — "success", "error", "client_disconnect"
   - `status_code: int` — HTTP status code (200, 400, 503)
   - `request_digest: str` — SHA-256 hex of the request prompt (first 2000 chars)
   - `response_chars: int` — response length (not the full text)
   - `response_digest: str` — SHA-256 hex of response text (first 2000 chars)
   - `duration_ms: int` — request latency
   - `created_at: str` — ISO 8601 timestamp
   - `error_message: str | None` — error text if failed

   Add `to_dict()` and `from_dict()` class methods.

2. `ReceiptEmitter` class:
   - `__init__(self, path: Path, *, line_limit: int = 200)` — writes to JSONL file, caps at line_limit
   - `emit(self, receipt: Receipt) -> None` — appends receipt as one JSON line. If file exceeds line_limit, drops oldest entries. Uses same atomic write + fcntl lock pattern as JsonGatewayTelemetryStore.
   - `read_recent(self, limit: int = 20) -> list[Receipt]` — reads last N receipts from file

3. `sha256_prefix(text: str, max_chars: int = 2000) -> str` — helper that computes SHA-256 of text[:max_chars]

4. Keep it stdlib-only. Use `hashlib`, `json`, `fcntl`, `os`, `pathlib`, `time`.

5. The JSONL file format:
   ```
   {"version":1,"run_id":"chatcmpl-lmm-1714492800000","route_target":"llamacpp",...}
   {"version":1,"run_id":"chatcmpl-lmm-1714492801000","route_target":"fallback",...}
   ```

6. Do NOT add GatewayHandler integration — that's Phase 03 Plan 02. This task is just the receipt module.
  </action>
  <verify>
    <automated>python3 -c "
import sys, tempfile; sys.path.insert(0, 'scripts')
from pathlib import Path
from lmm_receipts import Receipt, ReceiptEmitter, sha256_prefix
r = Receipt(run_id='test-1', route_target='llamacpp', model='test.gguf',
            request_digest=sha256_prefix('hello world'),
            response_chars=42, response_digest=sha256_prefix('response text'),
            duration_ms=100, status='success', status_code=200, harness='test')
d = r.to_dict()
assert d['run_id'] == 'test-1'
assert d['request_digest'].startswith('sha256:')
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / 'receipts.ndjson'
    emitter = ReceiptEmitter(path, line_limit=3)
    for i in range(5):
        r2 = Receipt(run_id=f'test-{i}', route_target='llamacpp', model='test.gguf',
                     request_digest=sha256_prefix(f'prompt {i}'), response_chars=10,
                     response_digest=sha256_prefix(f'resp {i}'), duration_ms=i*10,
                     status='success', status_code=200, harness='test')
        emitter.emit(r2)
    recent = emitter.read_recent(limit=10)
    assert len(recent) == 3, f'expected 3, got {len(recent)}'
    assert recent[0].run_id == 'test-4'  # newest first
print('lmm_receipts OK')
"</automated>
  </verify>
  <done>Receipt serializes correctly, SHA-256 digests computed, emitter caps at line_limit, newest-first ordering, atomic writes with fcntl lock</done>
</task>

<task type="auto">
  <name>Task 2: Add contract tests for receipt types and emitter</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_receipt_round_trips_to_dict` — Create Receipt, to_dict(), from_dict(), verify all fields match.

2. `test_sha256_prefix_truncates_long_text` — Compute digest of 4000-char text, verify it matches digest of first 2000 chars.

3. `test_receipt_emitter_caps_at_line_limit` — Emit N receipts where N > line_limit, verify file contains exactly line_limit lines.

4. `test_receipt_emitter_newest_first_ordering` — Emit 5 receipts, read_recent() returns newest first.

5. `test_receipt_emitter_atomic_writes` — Verify .tmp files are never left behind after emit.

Use load_script_module pattern. All tests should be self-contained with temp directories.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_receipt_round_trips_to_dict tests.test_phase0_contracts.Phase0ContractTests.test_sha256_prefix_truncates_long_text tests.test_phase0_contracts.Phase0ContractTests.test_receipt_emitter_caps_at_line_limit tests.test_phase0_contracts.Phase0ContractTests.test_receipt_emitter_newest_first_ordering tests.test_phase0_contracts.Phase0ContractTests.test_receipt_emitter_atomic_writes -v 2>&1</automated>
  </verify>
  <done>All 5 new tests pass, no existing tests broken</done>
</task>

</tasks>

<verification>
- Receipt dataclass with SHA-256 digests, round-trip serialization
- ReceiptEmitter writes JSONL, caps at line_limit, newest-first reads
- Atomic writes with fcntl locking (same pattern as lmm_storage.py)
- All new tests pass
</verification>

<success_criteria>
- Receipt records contain only digests (not full payloads)
- Emitter file never exceeds line_limit entries
- Receipts are valid JSONL, parseable by any JSONL reader
- Test coverage for types, serialization, capping, ordering
</success_criteria>

<output>
After completion, create `.planning/phases/03-receipts-notifications/03-receipts-notifications-01-SUMMARY.md`
</output>
