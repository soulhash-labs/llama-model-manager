# Phase 14 Research: OpenCode GlyphOS Fast Lane

## Provenance

This research is based on Phase 14 context and the four update documents that were consolidated into:

- `.planning/updates/5. consolidated-opencode-glyphos-update-plan-2026-05-06.md`

Original source updates:

- `.planning/updates/1. opencode-sse-timeout-plan-2026-05-06.md`
- `.planning/updates/2. opencode-llama-summary-2026-05-06.md`
- `.planning/updates/3. lmm-ohmyopenagent-opencode-full-review-and-fast-glyphos-plan-2026-05-06.md`
- `.planning/updates/4. manual-cloud-override-patterns-2026-05-06.md`

## Findings

### Anthropic and Web UI Status

Anthropic Messages support is already present in code and should not be replanned as missing implementation.

Relevant code:

- `scripts/glyphos_openai_gateway.py`
  - dispatches `POST /v1/messages`
  - dispatches `POST /v1/messages/count_tokens`
  - returns a status payload for `GET /v1/messages` and `GET /v1/message`
- `scripts/gateway/handlers_anthropic.py`
  - normalizes Anthropic messages into text
  - preserves tool contracts through `append_tool_contract_to_prompt(..., protocol="anthropic-messages")`
  - routes streaming requests through `stream_anthropic_completion(...)`
- `scripts/gateway/sse.py`
  - emits Anthropic named SSE events
  - supports `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, and `message_stop`
- `web/app.py`, `web/app.js`, `web/index.html`
  - expose and render OpenAI and Anthropic gateway endpoint formats

Planning impact:

- Phase 13 docs are stale relative to code and need reconciliation.
- Phase 14 should validate and build on this surface, not reimplement it.
- `/v1/chat/completions` remains OpenAI-compatible; `/v1/messages` is the Anthropic-compatible harness surface.

### Runtime GPU Warning

The warning:

```text
warning: no usable GPU found, --gpu-layers option will be ignored
warning: one possible reason is that llama.cpp was compiled without GPU support
```

is separate from the earlier `--chat-templateFile` issue.

Current relevant runtime code:

- `bin/llama-model`
  - has `probe_server_binary()`
  - has `preflight_runtime_check()`
  - tracks `SELECTED_LLAMA_SERVER_BACKEND`
  - forces `ngl=0` when selected backend is `cpu`
  - blocks CUDA device requests when no validated CUDA runtime is available
- `tests/test_portability.sh`
  - already covers auto-fit GPU layer reduction and CUDA guardrail behavior
- `web/app.py`, `web/app.js`, `web/index.html`
  - expose default `LLAMA_SERVER_NGL`
  - expose runtime/backend diagnostics in the dashboard

Planning impact:

- The next fix should make effective GPU-layer behavior explicit and testable.
- CPU fallback should not pass misleading GPU offload settings to llama.cpp.
- The UI should show selected runtime backend and effective GPU layer posture.

### Gateway Context and Timing

Current context path:

- `scripts/gateway/context_provider.py`
  - owns context MCP bridge location and status
  - extracts explicit payload context
  - calls MCP retrieval when enabled
  - builds `ContextPayload`
  - builds explicit `upstream_context`
  - still has legacy assembly helpers for compatibility
- `scripts/gateway/routing_service.py`
  - is the gateway-to-package router boundary
  - passes both `context_payload` and `upstream_context` into the package router
- `scripts/gateway/handlers_openai.py` and `scripts/gateway/handlers_anthropic.py`
  - call `prepare_gateway_pipeline(...)`
  - record context status and glyph encoding status in telemetry

Planning impact:

- Add timing at stage boundaries before optimizing behavior.
- Context retrieval must be budgeted for stream paths.
- Explicit payload context should remain first-class and should not be skipped by fast mode.
- MCP retrieval is optional and should degrade instead of blocking first byte.

### Fast GlyphOS Lane

Current gateway config:

- `scripts/lmm_config.py`
  - has one `GatewayConfig`
  - reads `LLAMA_MODEL_GATEWAY_HOST`
  - reads `LLAMA_MODEL_GATEWAY_PORT`
  - reads `LLAMA_MODEL_BACKEND_BASE_URL`
- `scripts/glyphos_openai_gateway.py`
  - `create_gateway_server(...)` accepts host, port, backend base URL, and model ID
  - CLI has a single `--port`
- `web/app.py`
  - builds one `gateway_api_base`
  - reports `gateway_formats`
- `integration_sync.py`
  - syncs one `llamacpp` OpenCode provider to a selected API base

Planning impact:

- Fast lane should be explicit, not a hidden mode.
- Target shape is:
  - `4010`: full GlyphOS
  - `4011`: fast GlyphOS
  - `8081`: raw backend internal only
- Fast lane should still use protocol normalization, routing metadata, explicit context contract, and GlyphOS prompt shaping.

### Operator Policy and Cloud Override

The update docs set a clear policy:

- local is the default
- cloud is manual/operator-selected
- do not reintroduce hidden cloud fallback

Planning impact:

- UI and config should display effective values and provider status.
- Integration sync must validate generated model IDs against the live OpenCode catalog.
- Cloud override helpers should be explicit and reversible.

## Recommended Plan Split

1. Reconcile Phase 13 planning state and lock the known Anthropic/web UI surface.
2. Fix GPU runtime compatibility and effective GPU-layer reporting.
3. Add gateway stage timing, context budgets, and early stream liveness.
4. Add the fast GlyphOS lane on `4011`.
5. Add operator policy and web UI diagnostics for fast/full lanes.
6. Align OpenCode/oh-my-openagent integration and manual cloud override hygiene.

## Deferred

Provider-neutral cloud streaming should stay out of the first Phase 14 implementation wave. It can be planned later after local full/fast lane behavior is measurable and stable.
