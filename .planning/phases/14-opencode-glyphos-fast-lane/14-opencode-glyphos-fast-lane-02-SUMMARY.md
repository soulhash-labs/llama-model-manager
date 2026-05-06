---
phase: 14-opencode-glyphos-fast-lane
plan: 02
status: complete
completed: 2026-05-06
---

# Plan 02 Summary: GPU Runtime Compatibility And Effective GPU-Layer Reporting

## Result

Completed the GPU-layer guardrail cut.

CPU-only runtime selection now forces requested GPU layers to effective zero, preserves the originally requested value in runtime state, and reports the requested/effective posture through CLI `current`, CLI `doctor`, and the dashboard runtime status card.

## Changes

- Added requested/effective GPU-layer state fields to `bin/llama-model`.
- Added `gpu_layer_posture` reporting for CPU fallback, adjusted GPU-layer counts, and as-configured runs.
- Hardened runtime preflight against unset validation status in strict shell mode.
- Allowed validated scripted bundle wrappers to use the selected bundle manifest backend after `--version` succeeds.
- Preserved `bundled-cpu-fallback` source/status after runtime validation.
- Rendered effective/requested GPU layer posture in the dashboard status card.
- Added portability coverage for CPU backend plus requested GPU layers.
- Refreshed docs/UI labels required by existing portability contract checks.

## Verification

- `bash -n bin/llama-model`
- `bash -n tests/test_portability.sh`
- Targeted portability functions:
  - `test_host_match_accepts_bundled_backend`
  - `test_cpu_fallback_selected_when_gpu_bundle_is_rejected`
  - `test_cpu_backend_forces_requested_gpu_layers_to_zero`
  - `test_current_and_doctor_report_cuda_unified_memory`
- `python3 -m py_compile web/app.py scripts/glyphos_openai_gateway.py scripts/gateway/sse.py scripts/gateway/handlers_anthropic.py`
- `pytest tests/test_phase0_contracts.py -k 'runtime or compatibility or gpu or ngl'` -> 4 passed, 160 deselected
- `ruff check scripts/glyphos_openai_gateway.py scripts/gateway tests/test_phase0_contracts.py`

## Notes

Full `bash tests/test_portability.sh` was not used as final evidence because it entered a real temporary llama.cpp runtime build path. That behavior is outside this GPU-layer guardrail cut and is tracked in `tasks/todo.md` as a verification caveat.
