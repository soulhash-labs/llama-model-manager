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
- [x] Complete harness contract: preserve OpenAI/Anthropic tool declarations into routed prompts.
- [x] Verify harness contract with compile, ruff, focused gateway tests, and integration package tests.

Deferred:
- Moving `integration_sync.py` and `context_mcp_bridge.py` under `scripts/integrations/` needs install-script and portability-test updates, so this pass will label boundaries but avoid path churn.

## Phase 14 Planning

Current checklist:
- [x] Add Phase 14 from consolidated OpenCode/GlyphOS update plan.
- [x] Research Phase 14 using the four update source documents.
- [x] Split Phase 14 into executable wave-based plans.
- [x] Update ROADMAP.md and STATE.md for Phase 14 planning status.

## Phase 14 Execution

Current checklist:
- [x] Wave 1 / Plan 01: Reconcile Phase 13 Anthropic streaming and dashboard endpoint planning state.
- [x] Wave 1 / Plan 02: Force CPU-only runtime GPU-layer requests to effective zero and expose requested/effective posture.
- [x] Verify Wave 1 with focused py_compile, runtime/compatibility pytest selection, ruff, and targeted shell portability regressions.
- [x] Wave 2 / Plan 03: Gateway timing, bounded context preflight, and early SSE liveness.
- [x] Wave 2 / Plan 04: Fast GlyphOS lane on 4011.
- [x] Wave 3 / Plan 05: Operator policy and web diagnostics.
- [x] Wave 3 / Plan 06: OpenCode/oh-my-openagent integration and manual cloud override hygiene.

Review notes:
- Full `bash tests/test_portability.sh` was intentionally stopped because it entered a real temporary llama.cpp CPU runtime build path. Use targeted portability functions for this cut unless installer/build-runtime behavior is the explicit verification target.

## Phase 14 Review Follow-Up

Current checklist:
- [x] Wire `sync-opencode` to read the live OpenCode model catalog when available and validate the selected local model before writing config.
- [x] Add oh-my-openagent sync for existing agent entries so they prefer `glyphos-fast/<model>` with `glyphos/<model>` fallback.
- [x] Decide `~/.glyphos/config.yaml` / `GLYPHOS_CONFIG_FILE` is the canonical runtime policy source and expose that source in dashboard policy state.
- [ ] Run machine-local TTFB comparison for `4010`, `4011`, and `8081` after reinstall/update.
- [ ] Run machine-local dashboard screenshot / visual verification after reinstall/update.

## Installer CUDA Toolkit Follow-Up

Current checklist:
- [x] Make the interactive installer explicit that CUDA hosts without `nvcc` will install CUDA toolkit packages before building the CUDA runtime.
- [x] Allow forced non-interactive runtime builds to attempt CUDA toolkit dependency install instead of silently falling back to CPU.
- [x] Add portability coverage for installer CUDA toolkit behavior.
