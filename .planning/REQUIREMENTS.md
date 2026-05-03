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

## Anthropic Proxy Requirements (Phase 13)

- [x] **ANTH-01**: POST `/v1/messages` accepts Anthropic-format request and returns Anthropic-format response
- [x] **ANTH-02**: Non-streaming response includes all required fields: `id`, `type`, `role`, `model`, `content`, `stop_reason`, `usage`
- [ ] **ANTH-03**: Streaming response uses Anthropic SSE event types: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`
- [x] **ANTH-04**: Context pipeline runs for Anthropic requests (same retrieval, encoding, routing as OpenAI)
- [x] **ANTH-05**: System prompt extracted from top-level `system` field and included in prompt assembly
- [x] **ANTH-06**: Content array format in messages properly parsed (string and `[{type: "text", text: "..."}]` formats)
- [x] **ANTH-07**: Telemetry records Anthropic requests with correct metadata
- [x] **ANTH-08**: `/v1/messages/count_tokens` returns token count for input messages
- [x] **ANTH-09**: Existing `/v1/chat/completions` endpoint is unchanged
- [x] **ANTH-10**: No new external dependencies added

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

## Anthropic Proxy Requirements (Phase 13)

| Requirement | Phase | Status |
|-------------|-------|--------|
| ANTH-01 | Phase 13 Plan 01 | Complete |
| ANTH-02 | Phase 13 Plan 01 | Complete |
| ANTH-03 | Phase 13 Plan 02 | Pending |
| ANTH-04 | Phase 13 Plan 01 | Complete |
| ANTH-05 | Phase 13 Plan 01 | Complete |
| ANTH-06 | Phase 13 Plan 01 | Complete |
| ANTH-07 | Phase 13 Plan 01 | Complete |
| ANTH-08 | Phase 13 Plan 01 | Complete |
| ANTH-09 | Phase 13 Plan 01 | Complete |
| ANTH-10 | Phase 13 Plan 01 | Complete |

---
*Last updated: 2026-05-03*
