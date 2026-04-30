# Roadmap

This roadmap tracks product-level follow-up that is not yet part of the shipped baseline.

## Completed Phases

### Phase 01 — Foundation

Status: ✅ shipped

- `lmm_config.py` — dataclass-based env config with validation
- `lmm_errors.py` — structured error types (GatewayError, InvalidRequestError)
- `lmm_storage.py` — fcntl-locked JSON store with atomic writes
- Gateway refactor: `ThreadingHTTPServer` (stdlib), telemetry persistence

### Phase 02 — Run Records & Health Checks

Status: ✅ shipped (3 plans, 2 waves)

- `lmm_types.py` — RunRecord, RunStatus, ExitResult
- `lmm_storage.py` — JsonRunRecordStore (bounded JSON store)
- `lmm_health.py` — HealthChecker with backend/storage/context checks
- Gateway: `/readyz`, `/-/runtime/report`, typed run record emission
- Dashboard: real run history, demo state externalized to `web/demo_state.json`

### Phase 03 — Receipts & Notifications

Status: ✅ shipped (2 plans, parallel)

- `lmm_receipts.py` — SHA-256-digested ReceiptEmitter (JSONL audit trail)
- `lmm_notifications.py` — Desktop/Log NotificationManager with cooldown
- Gateway: notifications on long runs (>30s), receipt capture

### Phase 04 — Provider Protocol & Registry

Status: ✅ shipped (1 plan)

- `lmm_providers.py` — Provider Protocol, LlamaCppProvider (stdlib urllib), ProviderRegistry with priority selection

### Phase 05 — Developer Experience

Status: ✅ shipped (1 plan)

- `pyproject.toml` — Ruff config (E/W/F/I/B/C4/UP rules)
- `.pre-commit-config.yaml` — ruff + standard hooks
- All existing modules lint-cleaned

### Privacy Fix

Status: ✅ shipped

- Gateway telemetry stores `prompt_chars` (length only) instead of raw prompt text

---

## Planned Phases

## Phase 06 — Long-Run Session Handoff

Status: planned

Session-level continuity for long-running local AI sessions. Extends RunRecord with handoff fields, generates summaries, adds CLI status command, and dashboard history panel.

Plans:
- [ ] 06-long-run-handoff-01-PLAN.md — HandoffSummary module, gateway session tracking, CLI + dashboard integration

## Phase 07 — Update Watcher

Status: planned

Optional, opt-in update checker for LMM and llama.cpp GitHub releases — notify-only, no auto-install, air-gap friendly.

Plans:
- [ ] 07-update-watcher-01-PLAN.md — UpdateChecker module, background timer, /v1/updates endpoint, CLI command
