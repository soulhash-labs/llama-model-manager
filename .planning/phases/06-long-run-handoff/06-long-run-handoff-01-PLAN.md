# Phase 06: Long-Run Session Handoff — Plan

**Phase:** 06-long-run-handoff
**Plan:** 01
**Goal:** Build session handoff layer so users see what finished, what changed, and what needs review after long local runs complete.
**Created:** 2026-04-30

## Must-Haves

```yaml
must_haves:
  truths:
    - "RunRecord supports handoff-specific fields without breaking existing serialization"
    - "HandoffSummary generates human-readable summary from a completed RunRecord"
    - "Gateway extracts session metadata and populates new RunRecord fields"
    - "Dashboard shows session history panel with recent long-running sessions"
    - "CLI command displays latest completed run status without opening dashboard"
  artifacts:
    - path: "scripts/lmm_types.py"
      provides: "RunRecord with handoff fields (session_id, upstream_session_ref, handoff_summary, artifacts, tags)"
    - path: "scripts/lmm_handoff.py"
      provides: "HandoffSummary dataclass, generation from RunRecord, text formatting"
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Session metadata extraction, handoff trigger for long runs"
    - path: "web/app.py"
      provides: "/api/handoff/summary endpoint, run_history summary mode"
    - path: "web/app.js"
      provides: "renderSessionHandoffs() function, session history UI"
    - path: "web/index.html"
      provides: "session-handoffs-panel DOM element"
    - path: "bin/llama-model"
      provides: "handoff status subcommand"
  key_links:
    - from: "glyphos_openai_gateway.py"
      to: "lmm_handoff.py"
      via: "HandoffSummary.from_run_record() call in do_POST"
    - from: "web/app.py /api/handoff/summary"
      to: "lmm_handoff.py"
      via: "HandoffSummary + JsonRunRecordStore query"
    - from: "web/app.js"
      to: "/api/state run_history"
      via: "renderSessionHandoffs() consuming run_history.records"
    - from: "bin/llama-model handoff"
      to: "lmm_handoff.py / lmm_storage.py"
      via: "JsonRunRecordStore.read_recent() + HandoffSummary"

requirements:
  - HANDOFF-01
  - HANDOFF-02
  - HANDOFF-03
  - HANDOFF-04
  - HANDOFF-05
```

## Requirements

- **HANDOFF-01**: RunRecord extensible with handoff fields (session_id, upstream_session_ref, handoff_summary, artifacts, tags) — all optional with defaults, backward compatible
- **HANDOFF-02**: HandoffSummary generates from completed RunRecord with duration_human, prompt_preview, exit_result, model, provider
- **HANDOFF-03**: CLI `llama-model handoff status` prints latest completed run status in < 1s
- **HANDOFF-04**: Dashboard session handoff panel renders last 10 long-running sessions (>30s threshold)
- **HANDOFF-05**: Gateway extracts session metadata from payload and populates new RunRecord fields

## Tasks

### Task 1: Extend RunRecord with handoff fields

**File:** `scripts/lmm_types.py`
**Action:** Add 5 optional fields to RunRecord dataclass with defaults. Update `to_dict()` and `from_dict()` to handle new fields.
**Details:**
- `session_id: str = ""` — defaults to `self.id` in `__post_init__`
- `upstream_session_ref: str = ""`
- `handoff_summary: str = ""`
- `artifacts: list[str] = field(default_factory=list)`
- `tags: list[str] = field(default_factory=list)`
- `to_dict()` includes new fields only when non-empty (backward compatible)
- `from_dict()` reads new fields with defaults
- Run `python3 -m unittest tests.test_phase0_contracts -v` to verify no regressions

### Task 2: Create lmm_handoff.py module

**File:** `scripts/lmm_handoff.py` (new)
**Action:** Create HandoffSummary dataclass with generation and formatting functions.
**Details:**
- `HandoffSummary` dataclass: session_id, run_id, status, model, provider, duration_human, completed_at, exit_result, prompt_preview, artifacts, upstream_session_ref
- `HandoffSummary.from_run_record(record: dict) -> HandoffSummary` — builds from RunRecord.to_dict() output
- `_format_duration(ms: int) -> str` — converts ms to human-readable (e.g., "2h 15m")
- `_extract_artifacts(record: dict) -> list[str]` — extracts from metadata.artifacts or metadata.output_files
- `format_handoff_text(summary: HandoffSummary) -> str` — plain text output for CLI
- `format_handoff_html(summary: HandoffSummary) -> str` — HTML snippet for dashboard (optional)
- Stdlib only: dataclasses, typing, datetime, json

### Task 3: Gateway session metadata extraction

**File:** `scripts/glyphos_openai_gateway.py`
**Action:** Extract session metadata from request payload, populate new RunRecord fields, trigger handoff for long runs.
**Details:**
- Add `_extract_session_metadata(payload: dict) -> dict` — extracts `metadata.session_id`, `metadata.conversation_id`, `metadata.tags`, `metadata.artifact_paths`
- In `do_POST`, after building record dict, merge session metadata into RunRecord before `safe_record_run_record()`
- For runs with `duration_ms > 60000` (1 min), generate HandoffSummary and store in `record.handoff_summary`
- Import `HandoffSummary` from `lmm_handoff` (guarded with try/except for backward compat)

### Task 4: CLI handoff status command

**File:** `bin/llama-model`
**Action:** Add `handoff` subparser with `status` subcommand.
**Details:**
- `llama-model handoff status` — prints latest completed run
- Output: run_id, status, model, provider, duration, completed_at, exit_result, prompt_preview
- If handoff_summary exists, print it
- If artifacts exist, list them
- `llama-model handoff status --json` — outputs JSON instead of text
- Uses `JsonRunRecordStore.read_recent(limit=1)` + `HandoffSummary.from_run_record()`

### Task 5: Dashboard handoff API endpoint

**File:** `web/app.py`
**Action:** Add `/api/handoff/summary` POST endpoint and extend run_history with summary mode.
**Details:**
- Add to `API_POST_PAYLOAD_SCHEMAS`: `"/api/handoff/summary": {"allowed": {"run_id", "limit"}, "int_fields": {"limit"}}`
- POST `/api/handoff/summary` with optional `run_id` or `limit` (default: latest completed)
- Returns: `{"ok": true, "summary": {...}}` or `{"ok": false, "error": "..."}`
- Extend `_load_run_history()` to include `long_runs` list (runs > 30s, newest first, max 10)
- Add `handoff` section to state response

### Task 6: Dashboard session history UI

**Files:** `web/index.html`, `web/app.js`
**Action:** Add session handoff panel to dashboard.
**Details:**
- HTML: Add `<section id="session-handoffs-panel" class="collapsible">` in main dashboard area
- JS: Add `renderSessionHandoffs(records)` function
  - Filter records with `duration_ms > 30000`
  - Show last 10, newest first
  - Each card: model, status badge, duration, completed_at, provider, prompt preview
  - Color-coded status: completed=green, failed=red, cancelled=gray
- Call `renderSessionHandoffs()` from state update handler

## Tests

### Unit tests (tests/test_phase0_contracts.py)

- `test_run_record_handoff_fields_default` — new fields have correct defaults
- `test_run_record_handoff_fields_round_trip` — to_dict/from_dict preserves new fields
- `test_run_record_backward_compat` — old records without new fields still parse
- `test_handoff_summary_from_completed_run` — HandoffSummary generates from RunRecord
- `test_handoff_summary_duration_formatting` — _format_duration handles ms, s, m, h
- `test_handoff_summary_prompt_preview` — truncates to 200 chars with ellipsis
- `test_gateway_session_metadata_extraction` — _extract_session_metadata pulls from payload
- `test_cli_handoff_status_output` — CLI command produces expected output format

## Success Criteria

1. RunRecord with handoff fields passes all existing tests + new handoff field tests
2. `HandoffSummary.from_run_record()` produces valid summary for any completed RunRecord
3. Gateway populates session metadata when available, handoff_summary for runs > 60s
4. `llama-model handoff status` prints latest run status within 1 second
5. Dashboard session panel shows long-running sessions with correct status colors
6. Zero regressions in existing run record storage, telemetry, or notification logic

---

_Verified: 2026-04-30_
_Planner: Claude (gsd-planner)_
