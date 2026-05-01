# Roadmap: llama-model-manager-v2.1.0

## Phases

- ✅ **Phase 01: foundation** — [shipped]
- ✅ **Phase 02: run-records** — [shipped]
- ✅ **Phase 03: receipts-notifications** — [shipped]
- ✅ **Phase 04: provider-protocol** — [shipped]
- ✅ **Phase 05: devex** — [shipped]
- ✅ **Phase 06: long-run-handoff** — [shipped]
- ✅ **Phase 07: update-watcher** — [shipped]
- **Phase 08: context-mcp-enhancements** — [in-progress]

## Phase 02: run-records

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 02-run-records | 3/3 | Complete | 2026-04-30 |

Plans:
- [x] 02-run-records-01-PLAN.md — Run record types and bounded JSON storage
- [x] 02-run-records-02-PLAN.md — Gateway emits RunRecords, standardized health endpoints
- [x] 02-run-records-03-PLAN.md — Dashboard consumes real run history, demo state externalized

## Phase 03: receipts-notifications

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 03-receipts-notifications | 2/2 | Complete | 2026-04-30 |

Plans:
- [x] 03-receipts-notifications-01-PLAN.md — Receipt dataclass, SHA-256 digest, JSONL emitter
- [x] 03-receipts-notifications-02-PLAN.md — Notification manager, delivery thresholds

## Phase 04: provider-protocol

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 04-provider-protocol | 1/1 | Complete | 2026-04-30 |

Plans:
- [x] 04-provider-protocol-01-PLAN.md — Provider protocol, LlamaCppProvider, ProviderRegistry

## Phase 05: devex

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 05-devex | 1/1 | Complete | 2026-04-30 |

Plans:
- [x] 05-devex-01-PLAN.md — Ruff linting, pre-commit hooks, dev-ex baseline

## Phase 06: long-run-handoff

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 06-long-run-handoff | 1/1 | Complete | 2026-05-01 |

Plans:
- [x] 06-long-run-handoff-01-PLAN.md — Session handoff layer, HandoffSummary, CLI + UI

## Phase 07: update-watcher

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 07-update-watcher | 1/1 | Complete | 2026-05-01 |

Plans:
- [x] 07-update-watcher-01-PLAN.md — Notify-only update watcher for LMM and llama.cpp

## Phase 08: context-mcp-enhancements

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 08-context-mcp-enhancements | 1/6 | In Progress | — |

Plans:
- [ ] 08-context-mcp-enhancements-01-PLAN.md — Incremental indexing + file-watcher auto-index
- [ ] 08-context-mcp-enhancements-02-PLAN.md — Execute tool audit (ctx_execute, ctx_batch, ctx_fetch_index)
- [ ] 08-context-mcp-enhancements-03-PLAN.md — Dashboard integration (Vite app + ctx_dashboard_open)
- [ ] 08-context-mcp-enhancements-04-PLAN.md — DB migration system (versioned migrations)
- [ ] 08-context-mcp-enhancements-05-PLAN.md — Search ranking improvements (BM25, recency, cross-project)
- [ ] 08-context-mcp-enhancements-06-PLAN.md — Future scope (TBD)
