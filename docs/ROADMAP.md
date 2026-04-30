# Roadmap

This roadmap tracks product-level follow-up that is not yet part of the shipped baseline.

## Receipts & Notifications

Status: planned

Plans: 2 plans in 1 wave (parallel)

Plans:
- [ ] 03-receipts-notifications-01-PLAN.md — SHA-256-digested receipt emitter for per-request audit trail
- [ ] 03-receipts-notifications-02-PLAN.md — Pluggable notification system with desktop/log fallback

## Provider Protocol & Registry

Status: planned

Plans: 1 plan in 1 wave

Plans:
- [ ] 04-provider-protocol-01-PLAN.md — Provider protocol, LlamaCppProvider, and priority-based ProviderRegistry

## Developer Experience

Status: planned

Plans: 1 plan in 1 wave

Plans:
- [ ] 05-devex-01-PLAN.md — Pre-commit hooks, Ruff linting, and install script improvements

## Run Records & Health Checks

Status: planned

Plans: 3 plans in 2 waves

Plans:
- [ ] 02-run-records-01-PLAN.md — Run record types and bounded JSON storage
- [ ] 02-run-records-02-PLAN.md — Gateway emits RunRecords, standardized health endpoints
- [ ] 02-run-records-03-PLAN.md — Dashboard consumes real run history, demo state externalized

## Long-Run Session Handoff

Status: planned

Local long-running agents need more than a healthy model process. Users also need to know what finished, what changed, and what needs review after a slow local run completes.

Planned capabilities:

- persistent run records for long local sessions
- completion detection for tool-driven runs when available
- final handoff summaries with status, duration, model, endpoint, and exit result
- captured artifacts or links to output logs where supported
- dashboard history for recent long-running sessions
- optional desktop, webhook, or local notification hooks
- CLI status surface for checking the latest completed run without reopening the dashboard

Initial focus:

- observe and summarize runs launched through LMM-managed gateways or sync surfaces
- keep user data local by default
- avoid turning LMM into a full agent runner before the handoff layer is proven

Terran evidence:

- Terran sustained a `8h 59m` GlyphOS AI Compute coding run on `Qwen3.5-9B-Q8_0.gguf` at `context 128000` and `parallel 1` through `opencode` + local LMM
- this increases the value of completion handoff, recent-run history, and end-of-run notification surfaces because full work-session local runs are now practical

Non-goals for the first pass:

- replacing Claude Code, OpenClaw, opencode, or GlyphOS AI Compute as the agent UI
- uploading session contents to hosted services
- guaranteeing semantic task success when the upstream tool only exposes process-level status


## Update Watcher

Status: planned

LMM should optionally check for updates to both `soulhash-labs/llama-model-manager` and upstream `ggml-org/llama.cpp` without silently installing or rebuilding anything. The proposed design is notify-only, opt-in for 12-hour background checks, and air-gap friendly.

Plan: [UPDATE-WATCHER-PLAN.md](UPDATE-WATCHER-PLAN.md)
