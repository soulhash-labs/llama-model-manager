# Roadmap: llama-model-manager

## Phases

- ✅ **Phase 01: foundation** — [shipped]
- ✅ **Phase 02: run-records** — [shipped]
- ✅ **Phase 03: receipts-notifications** — [shipped]
- ✅ **Phase 04: provider-protocol** — [shipped]
- ✅ **Phase 05: devex** — [shipped]
- ✅ **Phase 06: long-run-handoff** — [shipped]
- ✅ **Phase 07: update-watcher** — [shipped]
- ✅ **Phase 12: runtime-packaging** — [shipped]
- 📋 **Phase 13: anthropic-proxy** — [planned]

## Phase 12: runtime-packaging

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 12-runtime-packaging | 5/5 | Complete | 2026-05-03 |

Plans:
- [x] 12-runtime-packaging-01-PLAN.md — Self-contained runtime bundles (wrapper + payload + all .so files)
- [x] 12-runtime-packaging-02-PLAN.md — Runtime profile validation (ldd, --version, backend match)
- [x] 12-runtime-packaging-03-PLAN.md — Strengthened selection policy + LLAMA_SERVER_BIN persistence
- [x] 12-runtime-packaging-04-PLAN.md — Startup preflight guardrails + structured diagnostics
- [x] 12-runtime-packaging-05-PLAN.md — Dashboard UI diagnostics + installer post-build validation

## Phase 13: anthropic-proxy

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 13-anthropic-proxy | 1/3 | In Progress | 2026-05-03 |

Plans:
- [x] 13-anthropic-proxy-01-PLAN.md — Non-streaming `/v1/messages` endpoint with Anthropic format translation
- [ ] 13-anthropic-proxy-02-PLAN.md — Anthropic SSE streaming for `/v1/messages`
- [ ] 13-anthropic-proxy-03-PLAN.md — Dashboard UI updates for dual-format gateway
