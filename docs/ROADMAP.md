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

Non-goals for the first pass:

- replacing Claude Code, OpenClaw, opencode, or GlyphOS AI Compute as the agent UI
- uploading session contents to hosted services
- guaranteeing semantic task success when the upstream tool only exposes process-level status
