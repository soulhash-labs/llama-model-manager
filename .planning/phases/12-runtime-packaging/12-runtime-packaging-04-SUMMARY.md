---
phase: 12-runtime-packaging
plan: 04
subsystem: runtime
tags: [runtime, preflight, validation, doctor, startup, diagnostics]

# Dependency graph
requires:
  - phase: 12-runtime-packaging
    provides: [validate_runtime_profile() from 12-02, 4-tier selection from 12-03]
provides:
  - [Startup preflight guardrails with structured diagnostics]
  - [Runtime validation status exposed in doctor and gateway state]
affects: [dashboard, gateway, startup]

# Tech tracking
tech-stack:
  added: []
  patterns: [preflight_check, structured_failure_categories, runtime_validation_in_state]
key-files:
  created: []
  modified: [bin/llama-model]
key-decisions:
  - "Added preflight_runtime_check() that blocks startup before llama-server fork on runtime validation failures"
  - "Mapped validation statuses to structured failure categories: runtime-missing-libs, runtime-backend-mismatch, runtime-version-incompatible, runtime-missing"
  - "Doctor output includes runtime_validation_ok, runtime_status, runtime_missing_libs, runtime_version_text, runtime_backend_detected fields"
  - "Startup categories (startup_category, startup_diagnosis, startup_suggested_fix) exposed in doctor for dashboard consumption"
patterns-established:
  - "Preflight check pattern: validate before fork, block with structured diagnosis"
  - "Structured failure categories: runtime-missing-libs, runtime-backend-mismatch, runtime-version-incompatible, runtime-missing"

requirements-completed: [RUNTIME-09, RUNTIME-10]

# Metrics
duration: 13 min
completed: 2026-05-03
---

# Phase 12 Plan 04: Startup Preflight Guardrails Summary

**Startup preflight guardrails that fail fast on runtime problems with structured diagnostics, exposing validation status in doctor and gateway state**

## Performance

- **Duration:** 13 min
- **Started:** 2026-05-03T06:33:21Z
- **Completed:** 2026-05-03T06:46:35Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added `preflight_runtime_check()` function in `bin/llama-model` that runs before `llama-server` fork
- Mapped validation failures to four structured categories: `runtime-missing-libs`, `runtime-backend-mismatch`, `runtime-version-incompatible`, `runtime-missing`
- Integrated preflight check into `start_server()` after `probe_server_binary()` and before model path validation
- Blocks startup immediately with structured diagnosis when runtime problems detected
- Updated `show_doctor()` to include runtime validation fields: `runtime_validation_ok`, `runtime_status`, `runtime_missing_libs`, `runtime_version_text`, `runtime_backend_detected`
- Added `startup_category`, `startup_diagnosis`, `startup_suggested_fix` fields to doctor output
- CUDA mismatch detection: blocks when model requests CUDA but selected binary is CPU-only
- External-with-warning source handled with non-fatal warning

## Task Commits

Each task was committed atomically:

1. **Task 1: Add preflight_runtime_check() to start_server()** - `85cb422` (feat)
2. **Task 2: Expose runtime validation status in doctor and gateway state** - `45fb3ea` (feat)

**Plan metadata:** `c8a5f1a` (docs: complete plan)

_Note: TDD tasks may have multiple commits (test → feat → refactor)_

## Files Created/Modified

- `bin/llama-model` - Added `preflight_runtime_check()` function, updated `start_server()` and `show_doctor()`

## Decisions Made

- Used existing `validate_runtime_profile()` outputs (`VALIDATE_RUNTIME_OK`, `VALIDATE_RUNTIME_STATUS`, etc.) to populate preflight check results
- Structured failure categories align with existing `classify_startup_log_file()` pattern for consistency
- Doctor output fields named with `runtime_` prefix to distinguish from general validation fields
- Preflight check runs AFTER `probe_server_binary()` so all global vars are populated

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 12 runtime-packaging is ready for Plan 05 (dashboard integration with runtime validation status)
- Runtime validation fields now available in `/api/state` for dashboard consumption
- Structured failure categories enable rich error display in UI

---

## Self-Check: PASSED

- [x] SUMMARY.md file exists
- [x] Task commits found: 85cb422, 45fb3ea
- [x] Plan metadata commit found
- [x] `bin/llama-model` syntax check passed
- [x] `preflight_runtime_check()` function added
- [x] `show_doctor()` includes runtime validation fields
- [x] Structured failure categories implemented

---
*Phase: 12-runtime-packaging*
*Completed: 2026-05-03*
