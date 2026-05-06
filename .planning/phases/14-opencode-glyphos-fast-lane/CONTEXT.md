# Phase 14: opencode-glyphos-fast-lane

## Source

This phase was created from:

- `.planning/updates/5. consolidated-opencode-glyphos-update-plan-2026-05-06.md`

## Goal

Make OpenCode and oh-my-openagent use LMM/GlyphOS as the stable harness boundary without routing timeout-sensitive traffic directly to raw llama.cpp.

Target runtime shape:

- `4010`: full GlyphOS gateway
- `4011`: fast GlyphOS gateway
- `8081`: internal raw llama.cpp backend only

## Scope

- Reconcile stale Phase 13 planning state against implemented Anthropic Messages streaming and web UI endpoint surface.
- Add GPU runtime compatibility guardrails for CPU-only runtimes receiving GPU-layer settings.
- Add gateway first-byte and pre-stream timing instrumentation.
- Bound stream-safe context preflight while preserving explicit `upstream_context` and internal `ContextPayload`.
- Add early SSE liveness without invalid protocol frames.
- Create a fast GlyphOS lane for timeout-sensitive harness traffic.
- Expose operational policy and diagnostics in the web UI.
- Align OpenCode and oh-my-openagent after the fast lane exists.
- Preserve manual/operator-selected cloud override behavior.

## Non-Goals

- Do not make raw `8081` the final harness-facing path.
- Do not silently reintroduce cloud as automatic fallback.
- Do not add gateway-side tool execution.
- Do not combine timeout stabilization, fast lane, policy UI, provider-neutral streaming, and integration sync in one implementation cut.

## Planning Status

No implementation `PLAN.md` files have been generated for this phase yet.
