# Gateway Cleanup Plan

Scope: `scripts/glyphos_openai_gateway.py` and new `scripts/gateway/*` adapter modules.

Behavior lock:
- Run existing gateway contract tests before/after extraction.
- Add a regression test proving retrieved context is passed as explicit `upstream_context` while preserving `ContextPayload`.

Pass order:
- Pass 1: Extract low-risk protocol and HTTP helpers into `scripts/gateway/*` modules while preserving public names on the legacy script.
- Pass 2: Replace gateway-owned context encoding with package `encode_context(...)`.
- Pass 3: Thread explicit `upstream_context` into `route_prompt`, `route_prompt_stream`, and backward-compatible invocation helpers.
- Pass 4: Run targeted gateway tests, package tests, compile checks, and pre-commit formatting hooks.
- Pass 5: Extract OpenAI and Anthropic request handlers into `scripts/gateway/*` modules while preserving gateway-level patch points.

Current checklist:
- [x] Cut 3: Extract protocol normalizers and SSE helpers.
- [x] Cut 4: Extract telemetry and runtime health/update services.
- [x] Cut 5: Move OpenAI and Anthropic POST handlers out of `scripts/glyphos_openai_gateway.py`.
- [x] Verify Cut 5 with compile, ruff, focused gateway tests, and integration package tests.
- [x] Cut 6: Move retrieval/context provider and routing service bodies out of `scripts/glyphos_openai_gateway.py`.
- [x] Verify Cut 6 with context-provider tests, gateway regressions, and integration package tests.

Deferred:
- Moving `integration_sync.py` and `context_mcp_bridge.py` under `scripts/integrations/` needs install-script and portability-test updates, so this pass will label boundaries but avoid path churn.
