---
phase: 12-runtime-packaging
plan: 03
subsystem: runtime-selection
tags: [runtime, cuda, selection-policy, persistence, guardrail]

# Dependency graph
requires:
  - phase: 12-runtime-packaging
    provides: [bundled runtime bundles, validate_runtime_profile(), runtime profiles, doctor integration]
provides:
  - [4-tier runtime selection policy with strict priority ordering]
  - [CUDA guardrail preventing silent CPU fallback for CUDA models]
  - [LLAMA_SERVER_BIN persistence to defaults.env after validated selection]
affects: [runtime-selection, server-startup, install-flow]

# Tech tracking
tech-stack:
  added: []
  patterns: [4-tier selection priority, CUDA guardrail pattern, runtime persistence after validation]
key-files:
  created: []
  modified: [bin/llama-model, install.sh]
key-decisions:
  - "4-tier priority: explicit configured → bundled GPU → bundled CPU → external-with-warning"
  - "CUDA guardrail blocks startup (die) when CUDA model on CUDA host has no validated CUDA runtime"
  - "Only persist bundled runtimes (not external PATH binaries) to defaults.env"
  - "Persist after validation passes, not just binary selection"

patterns-established:
  - "Runtime selection validates before returning: validate_runtime_profile() must pass for bundled binaries"
  - "CUDA guardrail check in start_server() uses SELECTED_LLAMA_SERVER_CUDA_OK flag from probe_server_binary()"

requirements-completed: [RUNTIME-06, RUNTIME-07, RUNTIME-08]

# Metrics
duration: 5 min
completed: 2026-05-03
---

# Phase 12 Plan 03: Runtime Selection Policy and Persistence Summary

**Strengthen runtime selection with 4-tier priority, CUDA guardrail, and LLAMA_SERVER_BIN persistence to defaults.env**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-03T06:20:00Z
- **Completed:** 2026-05-03T06:25:02Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- **Task 1:** Rewrote `probe_server_binary()` with strict 4-tier selection priority:
  1. Explicit LLAMA_SERVER_BIN (if set and validates) → reject with clear error if invalid
  2. Validated bundled runtime matching preferred backend (cuda > vulkan > metal > cpu)
  3. Validated bundled CPU runtime as explicit fallback
  4. Validated external binary from PATH with warning message

- **Task 2:** Added `persist_selected_runtime()` function:
  - Persists LLAMA_SERVER_BIN to defaults.env using `set_default_value()`
  - Only persists bundled runtimes (not external PATH binaries)
  - Called after validation passes in `probe_server_binary()`
  - Integrated into `build_runtime_during_install()` in install.sh

- **CUDA Guardrail:** Added in `start_server()`:
  - Blocks silent CPU fallback when model requests CUDA on CUDA-capable host
  - Checks `SELECTED_LLAMA_SERVER_CUDA_OK` flag set by `probe_server_binary()`
  - Dies with clear error: "Model requests CUDA but no validated CUDA runtime is available"

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite probe_server_binary()** - `b2b0270` (feat)
2. **Task 2: Persist LLAMA_SERVER_BIN after validated runtime** - `68eef41` (feat)

**Plan metadata:** `6c63d2f` (docs: complete plan)

## Files Created/Modified

- `bin/llama-model` - Rewrote probe_server_binary(), added persist_selected_runtime(), added CUDA guardrail in start_server(), added persist-runtime CLI command
- `install.sh` - Updated build_runtime_during_install() to persist runtime after build

## Decisions Made

1. **4-tier priority ordering** - Explicit configured binary first (with strict validation), then bundled GPU, bundled CPU, external-with-warning. This ensures user's explicit choice is honored while providing sensible fallbacks.
2. **CUDA guardrail blocks (not warns)** - When a CUDA-tagged model runs on CUDA host with no validated CUDA runtime, startup is blocked with clear error. Silent fallback to CPU would cause confusing performance issues.
3. **Persistence only for bundled runtimes** - External PATH binaries are not persisted to defaults.env since they may not be stable across environments.
4. **Validation before persistence** - `persist_selected_runtime()` only writes to defaults.env if the runtime passed `validate_runtime_profile()` (status="compatible" or "fallback").

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Runtime selection policy is now strict with proper validation
- CUDA guardrail prevents silent fallback issues
- LLAMA_SERVER_BIN persistence ensures install-time builds are used on next startup
- Ready for plan 04 (next in phase 12-runtime-packaging)

---
*Phase: 12-runtime-packaging*
*Completed: 2026-05-03*
