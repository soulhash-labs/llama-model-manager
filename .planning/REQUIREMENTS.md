# Requirements: llama-model-manager

**Defined:** 2026-05-03

## Runtime Packaging Requirements (Phase 12)

- [x] **RUNTIME-01**: `build-runtime --backend cuda` produces a self-contained bundle with all required `.so` files
- [x] **RUNTIME-02**: Bundled binary has no unresolved `libggml*`, `libllama*`, or `libmtmd*` references via `ldd`
- [x] **RUNTIME-03**: Runtime bundle uses wrapper script + payload binary pattern for correct `LD_LIBRARY_PATH` at launch
- [x] **RUNTIME-04**: Every discovered runtime profile is validated (exists, executable, ldd, --version, backend match) before use
- [x] **RUNTIME-05**: Broken CUDA bundle is marked `invalid-missing-libs` before any launch attempt occurs
- [x] **RUNTIME-06**: Validated bundled runtime matching preferred backend is selected before external PATH binaries
- [x] **RUNTIME-07**: `LLAMA_SERVER_BIN` is persisted to `defaults.env` after successful runtime validation
- [x] **RUNTIME-08**: CUDA-tagged model on CUDA host never silently falls back to CPU-only binary
- [x] **RUNTIME-09**: Startup fails fast on runtime problems with structured diagnosis before model load
- [x] **RUNTIME-10**: Failure categories distinguish: `runtime-missing-libs`, `runtime-backend-mismatch`, `runtime-version-incompatible`, `runtime-missing`
- [x] **RUNTIME-11**: Dashboard shows selected runtime path, backend, validation status, and missing libraries
- [x] **RUNTIME-12**: Installer post-build checks validate bundle completeness (`ldd` + `--version`) before claiming success
- [x] **RUNTIME-13**: User can distinguish four problem types on dashboard: missing libs, wrong binary, backend mismatch, model incompatibility

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RUNTIME-01 | Phase 12 Plan 01 | Complete |
| RUNTIME-02 | Phase 12 Plan 01 | Complete |
| RUNTIME-03 | Phase 12 Plan 01 | Complete |
| RUNTIME-04 | Phase 12 Plan 02 | Complete |
| RUNTIME-05 | Phase 12 Plan 02 | Complete |
| RUNTIME-06 | Phase 12 Plan 03 | Complete |
| RUNTIME-07 | Phase 12 Plan 03 | Complete |
| RUNTIME-08 | Phase 12 Plan 03 | Complete |
| RUNTIME-09 | Phase 12 Plan 04 | Complete |
| RUNTIME-10 | Phase 12 Plan 04 | Complete |
| RUNTIME-11 | Phase 12 Plan 05 | Complete |
| RUNTIME-12 | Phase 12 Plan 05 | Complete |
| RUNTIME-13 | Phase 12 Plan 05 | Complete |

---
*Last updated: 2026-05-03*
