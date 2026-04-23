# Roadmap

This roadmap tracks product-level follow-up that is not yet part of the shipped baseline.

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

- Terran sustained a `4h 8m` GlyphOS AI Compute coding run on `Qwen3.5-9B-Q8_0.gguf` at `context 128000` and `parallel 1` through `opencode` + local LMM
- this increases the value of completion handoff, recent-run history, and end-of-run notification surfaces because multi-hour local sessions are now practical

Non-goals for the first pass:

- replacing Claude Code, OpenClaw, opencode, or GlyphOS AI Compute as the agent UI
- uploading session contents to hosted services
- guaranteeing semantic task success when the upstream tool only exposes process-level status


## Update Watcher

Status: planned

LMM should optionally check for updates to both `soulhash-labs/llama-model-manager` and upstream `ggml-org/llama.cpp` without silently installing or rebuilding anything. The proposed design is notify-only, opt-in for 12-hour background checks, and air-gap friendly.

Plan: [UPDATE-WATCHER-PLAN.md](UPDATE-WATCHER-PLAN.md)
