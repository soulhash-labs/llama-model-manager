---
phase: 14-opencode-glyphos-fast-lane
plan: 03
type: execute
wave: 2
depends_on: ["14-01"]
files_modified:
  - scripts/lmm_config.py
  - scripts/gateway/context_provider.py
  - scripts/gateway/routing_service.py
  - scripts/gateway/sse.py
  - scripts/gateway/telemetry.py
  - scripts/gateway/handlers_openai.py
  - scripts/gateway/handlers_anthropic.py
  - tests/test_gateway_context_provider.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: []
user_setup: []
---

<objective>
Add gateway first-byte timing, bounded stream-safe context preflight, and early SSE liveness without changing the public harness contracts.
</objective>

<context>
@.planning/phases/14-opencode-glyphos-fast-lane/RESEARCH.md
@scripts/lmm_config.py
@scripts/gateway/context_provider.py
@scripts/gateway/routing_service.py
@scripts/gateway/sse.py
@scripts/gateway/telemetry.py
@scripts/gateway/handlers_openai.py
@scripts/gateway/handlers_anthropic.py
@tests/test_gateway_context_provider.py
@tests/test_phase0_contracts.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add gateway stage timing fields</name>
  <files>scripts/gateway/handlers_openai.py, scripts/gateway/handlers_anthropic.py, scripts/gateway/context_provider.py, scripts/gateway/routing_service.py, scripts/gateway/telemetry.py, tests/test_phase0_contracts.py</files>
  <action>
Add structured timing fields to gateway records and headers where appropriate.

Track at minimum:
- request received
- prompt normalized
- context preflight start/end/duration
- context payload build duration
- route start/end/duration
- stream open
- first SSE write
- effective TTFB
- context degraded status
- gateway mode

Keep field names stable and machine-readable.
  </action>
  <verify>
    <automated>pytest tests/test_phase0_contracts.py -k 'gateway or telemetry or stream'</automated>
  </verify>
  <done>Gateway telemetry can identify whether delay is context, routing, upstream open, or first-write related.</done>
</task>

<task type="auto">
  <name>Task 2: Add stream-safe context preflight budgets</name>
  <files>scripts/lmm_config.py, scripts/gateway/context_provider.py, tests/test_gateway_context_provider.py, tests/test_phase0_contracts.py</files>
  <action>
Add context preflight budget configuration.

Required behavior:
- explicit payload context remains first-class and is not skipped
- MCP retrieval is optional and budgeted
- stream requests cannot block indefinitely on MCP retrieval or indexing
- timeout/degraded state is recorded in context metadata
- `ContextPayload` and explicit `upstream_context` remain distinct
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/lmm_config.py scripts/gateway/context_provider.py</automated>
    <automated>pytest tests/test_gateway_context_provider.py</automated>
  </verify>
  <done>Slow optional context work degrades rather than blocking stream liveness.</done>
</task>

<task type="auto">
  <name>Task 3: Add protocol-safe early SSE liveness</name>
  <files>scripts/gateway/sse.py, scripts/gateway/handlers_openai.py, scripts/gateway/handlers_anthropic.py, tests/test_phase0_contracts.py</files>
  <action>
Emit a comment-only SSE liveness preamble when safe.

Constraints:
- do not emit semantic OpenAI or Anthropic content before route/upstream state is safe
- keep existing OpenAI and Anthropic stream event shapes valid
- preserve disconnect/error behavior
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/gateway/sse.py scripts/gateway/handlers_openai.py scripts/gateway/handlers_anthropic.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'streaming or anthropic or completion'</automated>
  </verify>
  <done>Clients receive early liveness bytes without invalid protocol frames.</done>
</task>

</tasks>

<success_criteria>
- Gateway TTFB is measurable by stage.
- Stream paths cannot silently block on optional retrieval beyond configured budget.
- Existing OpenAI and Anthropic streaming contracts remain valid.
- Explicit upstream context and ContextPayload contracts remain preserved.
</success_criteria>

<output>
Create `.planning/phases/14-opencode-glyphos-fast-lane/14-opencode-glyphos-fast-lane-03-SUMMARY.md`.
</output>
