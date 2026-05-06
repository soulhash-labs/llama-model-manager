# Phase 14 Plan 06 Summary: OpenCode Fast Lane And Cloud Override Hygiene

## Completed

- Extended OpenCode sync to emit explicit `glyphos` and `glyphos-fast` provider entries.
- Preserved the existing `llamacpp` provider and direct-backend diagnostic mode.
- Added optional model catalog validation for generated OpenCode model IDs.
- Added sync diagnostics for full/fast GlyphOS provider IDs and base URLs.
- Added CLI output for `gateway_fast_api_base`.
- Added operator documentation at `docs/opencode-glyphos-fast-lane.md`.
- Added tests for OpenCode provider generation, model-catalog mismatch detection, and manual cloud routing behavior.

## Behavior

- OpenCode can now target full GlyphOS or fast GlyphOS explicitly.
- Raw llama.cpp remains available for diagnostic direct mode but is not required as the normal GlyphOS harness path.
- Manual cloud override remains reversible by removing `routing_hints.preferred_backend` or choosing `llamacpp`.

## Verification

- `python3 -m py_compile scripts/integration_sync.py web/app.py integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py`
- `pytest tests/test_phase0_contracts.py -k 'opencode or integration'`
- `pytest tests/test_phase0_contracts.py -k 'opencode or model'`
- `pytest tests/test_q2_flow.py -q` from `integrations/public-glyphos-ai-compute`
- Targeted portability functions: `test_sync_opencode_updates_config_and_state`, `test_sync_opencode_removes_stale_local_provider_blocks`, `test_sync_opencode_direct_mode`
- `ruff check web/app.py scripts/integration_sync.py integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py tests/test_phase0_contracts.py integrations/public-glyphos-ai-compute/tests/test_q2_flow.py`
- `ruff format --check web/app.py scripts/integration_sync.py integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py tests/test_phase0_contracts.py integrations/public-glyphos-ai-compute/tests/test_q2_flow.py`

## Remaining Risks

- The full shell portability suite was not run end-to-end because it enters a real temporary runtime build path. Targeted portability functions were run instead.
