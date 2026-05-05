# Llama Model Manager Architecture

Llama Model Manager turns a local `llama.cpp` runtime into an operator-facing local AI platform. The repository is organized around three boundaries:

- Product surfaces: CLI, browser dashboard, gateways, and integration helpers.
- Runtime semantics: GlyphOS AI Compute, context encoding, prompt shaping, and routing.
- Operations layer: health, telemetry, update checks, run records, and compatibility adapters.

The core rule is simple: package code owns AI semantics; scripts own transport, process wiring, and operator tooling.

## Top-Level Components

```text
Browser Dashboard / CLI / External Clients
                 |
                 v
        scripts/glyphos_openai_gateway.py
                 |
        scripts/gateway/* adapter modules
                 |
                 v
integrations/public-glyphos-ai-compute/glyphos_ai
                 |
        llama.cpp local lanes
                 |
        optional cloud fallback
        xAI / OpenAI / Anthropic
```

## Repository Map

| Path | Responsibility |
| --- | --- |
| `web/` | Browser dashboard UI and local operational API surface. |
| `bin/` | Installed command entrypoints and wrappers. |
| `scripts/` | Runtime scripts, gateways, health checks, storage, installer helpers, and integration adapters. |
| `scripts/gateway/` | OpenAI/Anthropic gateway adapter package. |
| `integrations/public-glyphos-ai-compute/` | Public GlyphOS AI Compute package: glyph types, context encoding, prompt shaping, clients, and adaptive routing. |
| `integrations/context-mode-mcp/` | Optional project-context MCP backend. |
| `tests/` | Contract and regression tests for web, scripts, gateway behavior, and integration package behavior. |
| `tasks/` | Local cleanup/refactor notes and execution checklists. |

## Runtime Request Flow

```text
OpenAI-compatible or Anthropic-compatible request
        |
        v
scripts/glyphos_openai_gateway.py
  - HTTP server
  - route dispatch
  - compatibility wrappers
        |
        v
scripts/gateway/handlers_openai.py
scripts/gateway/handlers_anthropic.py
  - protocol request parsing
  - response shaping
        |
        v
scripts/gateway/context_provider.py
  - optional payload context
  - optional Context Mode MCP retrieval
  - ContextPayload construction
  - upstream_context packet construction
        |
        v
scripts/gateway/routing_service.py
  - router creation
  - route / stream invocation
        |
        v
glyphos_ai.ai_compute.router.AdaptiveRouter
  - local-first routing
  - context-aware routing hints
  - cloud fallback when configured
        |
        v
llama.cpp lane or configured cloud provider
```

## Package Boundary

`integrations/public-glyphos-ai-compute/glyphos_ai` owns reusable AI behavior.

Key modules:

- `glyph/types.py`
  - `GlyphPacket`
  - `ContextPayload`
  - `ContextPacket`
  - routing hint types
  - glyph helper functions

- `glyph/context_encoding.py`
  - context compression and encoding metadata.
  - produces `ContextPayload`.

- `ai_compute/glyph_to_prompt.py`
  - converts glyph packets to prompts.
  - appends explicit upstream context using deterministic `[CONTEXT_ANCHOR]`.
  - preserves the `ContextPayload` compression path.

- `ai_compute/router.py`
  - local-first adaptive routing.
  - explicit `upstream_context` support.
  - local `ContextPayload` handling.
  - cloud fallback behavior.

- `ai_compute/api_client.py`
  - configured local and cloud client creation.

Package code should not perform hidden retrieval, indexing, request parsing, HTTP response shaping, or dashboard/UI work.

## Gateway Boundary

`scripts/glyphos_openai_gateway.py` is intentionally becoming a thin compatibility shell.

It should contain:

- HTTP server class.
- GET route dispatch.
- POST route dispatch.
- server factory and CLI entrypoint.
- compatibility wrappers for legacy tests and operator code.

It should not contain:

- protocol normalization bodies.
- SSE streaming implementation.
- telemetry persistence implementation.
- health/update implementation.
- retrieval/MCP orchestration bodies.
- routing implementation bodies.

Those responsibilities now live in `scripts/gateway/`.

## Gateway Adapter Modules

| Module | Responsibility |
| --- | --- |
| `http_utils.py` | JSON request/response helpers, typed request coercion, simple HTTP JSON client. |
| `protocol_normalizers.py` | OpenAI and Anthropic message normalization and response shaping helpers. |
| `sse.py` | OpenAI and Anthropic server-sent event streaming, keepalive, disconnect handling, stream notifications. |
| `telemetry.py` | Gateway telemetry store, run record store, run-record conversion, handoff summaries. |
| `health_runtime.py` | Gateway runtime health, cloud provider status, update watcher setup. |
| `handlers_openai.py` | `/v1/chat/completions` handler body. |
| `handlers_anthropic.py` | `/v1/messages` and `/v1/messages/count_tokens` handler bodies. |
| `context_provider.py` | Context status, payload context extraction, MCP retrieval, context encoding metadata, upstream context packets. |
| `routing_service.py` | Configured router creation and route/stream calls into the GlyphOS package. |

## Context Contract

There are two separate context shapes by design.

### `ContextPacket`

Public upstream context supplied by a harness, gateway, or orchestrator.

Used for:

- explicit retrieved context
- provenance
- locality
- routing hints
- metadata

This flows into routing and prompt shaping as `upstream_context`.

### `ContextPayload`

Internal local encoding/compression metadata.

Used for:

- raw context
- encoded context
- encoding status
- encoding format
- encoding ratio
- token delta estimate

This flows into local prompt assembly and router decisions as `context_payload`.

The gateway should pass both explicitly when both are available.

```python
router.route(
    packet,
    prompt=raw_prompt,
    context_payload=context_payload,
    upstream_context=upstream_context,
)
```

The gateway must not silently mutate the user prompt before routing. Retrieved context is handed off as explicit context and encoding metadata.

## Web UI Operations Contract

The dashboard and operational UI depend on stable scripts-layer surfaces, not package internals.

Important operational endpoints and surfaces:

- `/healthz`, `/v1`, `/v1/health`
- `/readyz`
- `/-/runtime/report`
- `/v1/models`
- `/v1/telemetry`
- `/v1/updates`
- gateway log APIs exposed by the web manager

The web UI should treat gateway responses as operational state:

- backend health
- storage health
- context readiness
- routing telemetry
- update watcher state
- model list / fallback model shape
- run records and recent request telemetry

Changes to those response shapes should be covered by contract tests before shipping.

## Harness Endpoints

The gateway listens on the configured gateway host/port, usually `http://127.0.0.1:4010`.

OpenAI-compatible harnesses use:

- `POST /v1/chat/completions`
- `GET /v1/models`

Anthropic-compatible harnesses use:

- `GET /v1/messages`
- `GET /v1/message`
- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

`POST /v1/messages` supports both non-streaming JSON responses and Anthropic-style SSE when the request includes `"stream": true`. The stream emits Anthropic event names such as `message_start`, `content_block_delta`, `message_delta`, and `message_stop`.

Tool/function declarations are preserved into the routed prompt for both protocol surfaces:

- OpenAI-style `tools`, `tool_choice`, legacy `functions`, and `function_call`
- Anthropic-style `tools` and `tool_choice`

The gateway does not execute tools. It exposes the declared contract to the model and keeps routing/local context semantics unchanged.
If the routed model returns a declared tool call as structured JSON, the gateway shapes it back into the matching provider response:

- OpenAI: `message.tool_calls` with `finish_reason: "tool_calls"`
- Anthropic: `content[].type == "tool_use"` with `stop_reason: "tool_use"`

## Compatibility Surface

Several names remain exported from `scripts/glyphos_openai_gateway.py` for legacy tests and operator code:

- `route_prompt`
- `route_prompt_stream`
- `context_status`
- `retrieve_context`
- `run_context_command`
- `glyph_encode_context`
- `prepare_gateway_pipeline`
- `stream_completion`
- `stream_anthropic_completion`
- telemetry helpers

These wrappers are compatibility boundaries. Do not remove or bypass them unless the tests and installed operator flows have been migrated.

## Local-First Routing

The public local stance is llama.cpp-only.

Local routing goes through GlyphOS AI Compute:

- `GlyphPacket` describes action, destination, time slot, and coherence.
- `ContextPacket` provides explicit upstream context.
- `ContextPayload` provides local encoding metadata.
- `AdaptiveRouter` selects local llama.cpp or configured cloud fallback.

Cloud providers are optional and configured through environment/config:

- xAI
- OpenAI
- Anthropic

Ollama support remains a lazy compatibility tombstone, not an active runtime path.

## Context Mode MCP

`scripts/context_mcp_bridge.py` is an adapter to `integrations/context-mode-mcp`.

Current role:

- spawn bridge process
- dispatch `ctx_search` / `ctx_index`
- return context text and search metadata

This is integration glue, not core runtime semantics. Long term, this may become a persistent bridge or daemon, but that is a separate adapter-level change.

## Telemetry And Run Records

Gateway telemetry is append-only JSON state managed by `scripts/gateway/telemetry.py` and `scripts/lmm_storage.py`.

Telemetry records intentionally redact raw prompts and preserve:

- route target
- route reason code
- success/failure
- context status
- context usage
- encoding status
- latency
- run status
- handoff metadata for long-running sessions

Run records use `scripts/lmm_types.py` and are separate from request telemetry.

## Health And Updates

Health and update behavior lives in scripts:

- `scripts/lmm_health.py`
- `scripts/lmm_updates.py`
- `scripts/gateway/health_runtime.py`

Readiness requires core components to be healthy enough for operation. Context can be reported as degraded when optional context infrastructure is unavailable.

## Testing Strategy

Key test groups:

- `tests/test_phase0_contracts.py`
  - gateway contract behavior
  - web/API operational expectations
  - health/readiness
  - telemetry/run records
  - context and routing compatibility

- `tests/test_gateway_context_provider.py`
  - payload context to `upstream_context`
  - MCP retrieval to `upstream_context`
  - degraded metadata preservation
  - empty retrieval behavior
  - prompt immutability

- `integrations/public-glyphos-ai-compute`
  - package-level GlyphOS AI Compute behavior.

Recommended verification for gateway changes:

```bash
python3 -m py_compile scripts/gateway/*.py scripts/glyphos_openai_gateway.py
ruff check scripts/gateway scripts/glyphos_openai_gateway.py tests
ruff format --check scripts/gateway scripts/glyphos_openai_gateway.py tests
python3 -m unittest tests.test_gateway_context_provider
python3 -m unittest <focused gateway tests>
cd integrations/public-glyphos-ai-compute && pytest -q
```

## Change Rules

- Keep package semantics in `glyphos_ai/*`.
- Keep HTTP/protocol/ops adapters in `scripts/gateway/*`.
- Preserve `glyphos_openai_gateway.py` wrapper names until installed flows no longer patch them.
- Do not introduce hidden retrieval in package code.
- Do not pre-inject retrieved context into prompts when `upstream_context` is available.
- Keep local llama.cpp as the public local runtime path.
- Treat `scripts/integration_sync.py` and `scripts/context_mcp_bridge.py` as adapter/tooling scripts, not core runtime.
