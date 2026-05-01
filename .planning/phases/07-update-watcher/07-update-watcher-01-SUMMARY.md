# Phase 07: Update Watcher — Summary

**Plan:** 07-update-watcher-01
**Status:** Complete
**Completed:** 2026-05-01

## What Shipped

- Added opt-in update watcher config with validated interval, timeout, repo, and state-file settings.
- Added `scripts/lmm_updates.py` with GitHub latest-release checks, semantic-ish version comparison, cached offline fallback, and locked JSON state persistence.
- Added `/v1/updates` to the LMM gateway and a disabled-by-default background watcher that can notify when LMM or llama.cpp releases are newer.
- Added `llama-model update-check [--component lmm|llamacpp|all] [--json]` for manual notify-only checks.
- Added dashboard update status in `/api/state` and a top update banner when the watcher is enabled.
- Added global defaults UI controls for enabling the watcher and setting interval/timeout.
- Added regression tests for config validation, version comparison, offline cache fallback, state persistence, and disabled endpoint shape.

## Key Files Changed

- `scripts/lmm_config.py`
- `scripts/lmm_updates.py`
- `scripts/lmm_notifications.py`
- `scripts/glyphos_openai_gateway.py`
- `bin/llama-model`
- `web/app.py`
- `web/app.js`
- `web/index.html`
- `web/styles.css`
- `config/defaults.env.example`
- `tests/test_phase0_contracts.py`

## Verification

- `python3 -m py_compile scripts/lmm_config.py scripts/lmm_updates.py scripts/lmm_notifications.py scripts/glyphos_openai_gateway.py web/app.py`
- `bash -n bin/llama-model tests/test_portability.sh install.sh`
- `git diff --check`
- `python3 -m unittest tests.test_phase0_contracts` — 157 tests OK
- `bash tests/test_portability.sh` — passed

## Notes

- Watcher remains disabled by default and notify-only. No auto-install or mutation happens from update checks.
- Offline/air-gapped checks return cached state without raising user-visible gateway errors.
