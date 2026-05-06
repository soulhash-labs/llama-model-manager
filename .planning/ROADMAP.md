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
- ✅ **Phase 13: anthropic-proxy** — [shipped]
- ✅ **Phase 14: opencode-glyphos-fast-lane** — [shipped]

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
| 13-anthropic-proxy | 3/3 | Complete | 2026-05-06 |

Plans:
- [x] 13-anthropic-proxy-01-PLAN.md — Non-streaming `/v1/messages` endpoint with Anthropic format translation
- [x] 13-anthropic-proxy-02-PLAN.md — Anthropic SSE streaming for `/v1/messages`
- [x] 13-anthropic-proxy-03-PLAN.md — Dashboard UI updates for dual-format gateway

## Phase 14: opencode-glyphos-fast-lane

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 14-opencode-glyphos-fast-lane | 6/6 | Complete | 2026-05-06 |

Goal:
- Build a fast GlyphOS-backed gateway lane for OpenCode and oh-my-openagent while preserving the full GlyphOS lane, keeping raw llama.cpp internal, bounding context preflight, exposing operational diagnostics, and keeping cloud overrides manual/operator-controlled.

Source:
- `.planning/updates/5. consolidated-opencode-glyphos-update-plan-2026-05-06.md`

Depends on:
- Phase 13 planning-state reconciliation for already-implemented Anthropic streaming and web UI endpoint surface.
- Phase 12 runtime packaging guardrails for GPU/runtime compatibility diagnostics.

Plans:
- [x] 14-opencode-glyphos-fast-lane-01-PLAN.md — Reconcile Phase 13 Anthropic/web UI planning state
- [x] 14-opencode-glyphos-fast-lane-02-PLAN.md — GPU runtime compatibility and effective GPU-layer reporting
- [x] 14-opencode-glyphos-fast-lane-03-PLAN.md — Gateway timing, bounded context preflight, and early SSE liveness
- [x] 14-opencode-glyphos-fast-lane-04-PLAN.md — Fast GlyphOS lane on `4011`
- [x] 14-opencode-glyphos-fast-lane-05-PLAN.md — Operator policy and web UI diagnostics
- [x] 14-opencode-glyphos-fast-lane-06-PLAN.md — OpenCode/oh-my-openagent integration and manual cloud override hygiene
