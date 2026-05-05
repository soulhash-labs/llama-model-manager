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

Deferred:
- Moving `integration_sync.py` and `context_mcp_bridge.py` under `scripts/integrations/` needs install-script and portability-test updates, so this pass will label boundaries but avoid path churn.
