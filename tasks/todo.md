# Gateway Cleanup Plan

Scope: `scripts/glyphos_openai_gateway.py` and new `scripts/gateway/*` adapter modules.

Behavior lock:
- Run existing gateway contract tests before/after extraction.
- Add a regression test proving retrieved context is passed as explicit `upstream_context` while preserving `ContextPayload`.

## Sabotage Claim Review Triage

Current checklist:
- [x] Verify reported double-raise pattern in `scripts/glyphos_openai_gateway.py`.
- [x] Verify reported `assert` crash paths in `scripts/context_mcp_bridge.py`.
- [x] Verify reported download-control `None` checks in `web/app.py`.
- [x] Verify generated `._api_client.py` files.
- [x] Patch confirmed context MCP bridge error-reporting defects.
- [x] Add regression coverage for context MCP bridge pipe validation.
- [x] Verify with compile and focused tests.
- [x] Deploy confirmed bridge fix to the installed LMM runtime.

Review:
- The `glyphos_openai_gateway.py` report is misclassified: the cited `raise` statements are fallback shims that re-raise the original callback `TypeError` only after compatibility retries fail.
- The `web/app.py` download-control `None` checks are not inconsistent error handling. They run under `download_lock`; `job is None` is the correct result for a missing or concurrently removed job and is surfaced as `ValueError`.
- The `._api_client.py` files are AppleDouble metadata sidecar files, not Python modules imported by the package. They are cleanup noise, not missing-import evidence.
- Confirmed issue: `context_mcp_bridge.py` uses `assert` for required pipes and has opaque startup/cleanup failure handling.
- Patched `context_mcp_bridge.py` to raise explicit runtime errors for missing pipes, stdin write failures, stdout wait/read failures, malformed JSON, and initialization failures. Initialization cleanup stays strict; routine dispatch cleanup logs warnings so it does not mask a successful tool result.
- Updated the bridge protocol regression to use NDJSON, which matches the current MCP SDK transport.
- Verification passed: compile checks, focused context bridge tests, queued-download removal race guard test, and deployed-copy syntax parse.

## Exception Handling and Telemetry Redaction Follow-Up

Current checklist:
- [x] Locate nested broad `except Exception` clauses in gateway context command handling.
- [x] Inspect telemetry persistence for broad catches and command-substitution leakage.
- [x] Narrow context command timeout cleanup exceptions.
- [x] Redact command-substitution telemetry fields before persistence.
- [x] Add focused regression coverage.
- [x] Verify with compile and targeted tests.
- [x] Deploy confirmed fixes to the installed LMM runtime.

Review:
- The nested broad catches are in `scripts/gateway/context_provider.py` timeout cleanup, not `scripts/gateway/telemetry.py`.
- `safe_record_gateway_request()` and `safe_record_run_record()` intentionally catch broad telemetry persistence failures so gateway requests can still return; they already log warnings.
- `generate_handoff_summary()` currently swallows all handoff failures silently and should log a warning.
- Telemetry request summaries can persist sensitive metadata key names such as `command_substitution`; they should be removed or redacted before state is written.
- Patched `context_provider.py` to replace nested bare `except Exception` process cleanup with explicit process/OSError catches.
- Patched `telemetry.py` so gateway/run-record persistence and handoff summary handling catch expected failure classes and log warnings instead of broad silent masking.
- Patched telemetry redaction to recursively remove sensitive command-substitution fields and matching metadata key names before persistence.
- Verification passed: compile checks, no `except Exception` remains in repo/deployed `context_provider.py` or `telemetry.py`, focused gateway telemetry tests passed with loopback access, and deployed-copy syntax parse passed.

## Bug Analysis Hardening Pass

Current checklist:
- [x] Re-check cited bare exception sites after previous telemetry/context-provider fixes.
- [x] Verify stream wrappers forward `payload` to tool detection.
- [x] Verify `LlamaCppClient` lazy availability initialization is lock-protected.
- [x] Verify Context MCP TypeScript config has `strict: true`.
- [x] Narrow remaining HTTP/provider/SSE exception handling.
- [x] Preserve upstream stream exception class context.
- [x] Add focused regression coverage for confirmed gaps.
- [x] Verify Python and TypeScript checks.
- [x] Deploy runtime-impacting Python fixes.

Review:
- `scripts/gateway/telemetry.py` and `scripts/gateway/context_provider.py` no longer have bare `except Exception` in the repo or deployed runtime copy.
- `scripts/gateway/sse.py` already forwards `payload` into `_detect_tool_call(...)` for OpenAI and Anthropic stream wrappers.
- `integrations/public-glyphos-ai-compute/.../api_client.py` already guards lazy availability initialization with `self._availability_lock`.
- `integrations/context-mode-mcp/tsconfig.json` already sets `"strict": true`.
- Remaining confirmed hardening: `http_utils.py` and `lmm_providers.py` still use broad JSON parse fallbacks, and stream wrapper errors lose the upstream exception class by wrapping as `RuntimeError(str(exc))`.
- Patched `http_utils.py` and `lmm_providers.py` to catch `json.JSONDecodeError` explicitly for malformed HTTP error bodies.
- Patched `lmm_providers.py` to reject empty resolved model names and map malformed non-stream provider JSON to `ProviderError`.
- Patched `context_mcp_bridge.py` to report malformed stdin JSON with a component-named `RuntimeError`.
- Patched `sse.py` to preserve upstream exception class names in stream error messages and to narrow provider/stream error catches.
- Verification passed: Python compile checks, focused provider/bridge/http tests, focused SSE tests, Context MCP TypeScript typecheck, no `except Exception` remains in cited repo/deployed runtime files, and deployed-copy syntax parse.

## Provider/Gateway Review Triage

Current checklist:
- [x] Verify the reported undefined `models` variable.
- [x] Verify the reported missing async error handling in `scripts/glyphos_openai_gateway.py`.
- [x] Verify the reported storage race in `scripts/lmm_storage.py`.
- [x] Harden provider streaming timeout and malformed SSE handling.
- [x] Add focused provider stream regression coverage.
- [x] Verify with compile and focused unit tests.
- [x] Deploy confirmed provider fix to the installed LMM runtime.

Review:
- The `models` report is a false positive in the visible repo code: `scripts/lmm_providers.py`, `scripts/claude_gateway.py`, and `scripts/integration_sync.py` assign `models` before using it.
- The `scripts/glyphos_openai_gateway.py` async-error report has a false premise: the gateway is a synchronous `ThreadingHTTPServer`; extracted OpenAI/Anthropic handlers own request error paths.
- The JSON storage race report is a false positive for the current append paths: telemetry and run-record writes use `_lock()` with `fcntl.flock` around read-modify-write.
- Confirmed hardening gap: `LlamaCppProvider.generate_stream()` maps `URLError` timeouts but can still leak direct socket/timeout exceptions raised while iterating a streaming response.
- Patched `scripts/lmm_providers.py` so malformed SSE JSON is ignored only for JSON decode failures and direct stream timeouts map to `ProviderTimeoutError`.
- Verification passed: provider compile check, focused provider tests, and deployed-copy syntax parse.

## Claude Review Triage

Current checklist:
- [x] Validate reported worker status race in `web/app.py`.
- [x] Validate reported SSE stream exception/resource leak in `scripts/gateway/sse.py`.
- [x] Validate reported lazy initialization race in public GlyphOS API client.
- [x] Classify lower-priority type-hint/provider-name/test/idempotency notes.
- [x] Decide which confirmed issues need immediate patches.
- [x] Patch download worker liveness recovery so registered not-yet-started workers are not marked stale.
- [x] Add regression coverage for the worker handoff race.
- [x] Patch SSE stream cleanup so upstream exceptions/client disconnects close iterators and join worker threads briefly.
- [x] Add SSE regression coverage for upstream drops and client disconnects.
- [x] Patch `LlamaCppClient` lazy availability initialization with a per-instance lock.
- [x] Add concurrent availability regression coverage.
- [x] Add complete type hints for OpenAI and Anthropic gateway handler dependency maps.
- [x] Add gateway request/run idempotency fingerprinting.
- [x] Add storage-level duplicate suppression for consecutive identical fingerprints.
- [x] Add idempotency regression coverage for storage and gateway double-post behavior.
- [x] Log malformed JSON store recovery instead of silently resetting state.
- [x] Normalize `None` message content to empty text in gateway protocol normalizers.
- [x] Separate known `GatewayError` handling from unexpected OpenAI/Anthropic handler exceptions and log unexpected failures.

Review:
- Worker status race is mostly a false positive: download scheduling, recovery, and stale-thread cleanup all run under `download_lock`, and the code deliberately handles not-yet-started threads.
- Follow-up patch made that intent explicit: `_download_worker_is_active()` treats registered not-yet-started workers as active, while `_prune_stopped_download_controls_locked()` removes only started-and-stopped workers.
- SSE stream handling was patched: stream pump threads are no longer daemon-only fire-and-forget; disconnect/error paths now set cancellation, close closeable iterators, and join briefly.
- Lazy availability initialization was patched with a per-instance lock. It cannot coordinate separate OS processes, but it now prevents duplicate concurrent `/models` probes on the same `LlamaCppClient` instance.
- Gateway handlers now use `TypedDict` dependency maps plus callable aliases instead of unstructured `dict[str, Any]` handler APIs.
- Gateway request and run stores now dedupe consecutive identical request fingerprints and track `duplicate_count`; this is persistence-level idempotency, not response caching.
- Malformed JSON store recovery now emits a warning with the store path and parse/type failure before falling back to default state.
- Protocol normalizers now treat `None` message content and `None` content-list entries as empty/ignored instead of rendering `"None"` into prompts.
- OpenAI and Anthropic handlers now classify `GatewayError` separately and log unexpected handler exceptions before returning structured gateway errors.
- Duplicate download jobs are already guarded for active downloads by `active_download_for` inside the same lock as creation, but there is no HTTP idempotency key for repeated completed/failed historical starts.

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
- [x] Run machine-local TTFB comparison for `4010`, `4011`, and `8081` after reinstall/update.
- [x] Run machine-local dashboard screenshot / visual verification after reinstall/update.

Review note:
- `glyphos-fast` alias never existed in the current opencode.json format (uses singular `provider` key, not `providers[]`). No cleanup needed.
- oh-my-openagent.json agents/categories all use `llamacpp/` or `llamacpp_fast/` — no stale `glyphos` references.
- Dist patches confirmed on both running PIDs (150515 from May 10 22:12, 190240 from May 11 07:01). Both started after dist was patched at May 10 21:04.
- Gateways restarted with deployed fixes, all tests pass (185/186).

Review note:
- ⚠️ SUPERSEDED: The original oh-my-openagent sync target used `glyphos-fast/<model>` and `glyphos/<model>` as model IDs. Later OpenCode validation showed those are stale provider IDs for this integration — they cause `ProviderModelNotFoundError` and can crash OpenCode.
- Current canonical behavior keeps the GlyphOS full/fast lane semantics but registers agent model IDs as `llamacpp/<model>` (port 4010, full lane) and `llamacpp_fast/<model>` (port 4011, fast lane).
- `glyphos-fast` may exist in `opencode.json` as a temporary compatibility provider alias for stale in-memory plugin config, but do not use `glyphos-fast/<model>` as the canonical oh-my-openagent agent model ID.
- Doctor now detects stale `glyphos/` model IDs in `oh-my-openagent.json` and recommends `llama-model sync-opencode`.
- Doctor now scans plugin logs for `ProviderModelNotFoundError` and other fatal signatures.
- Safe mode: `llama-model opencode-plugin disable` removes oh-my-openagent from `opencode.json` without deleting config.

## Installer CUDA Toolkit Follow-Up

Current checklist:
- [x] Make the interactive installer explicit that CUDA hosts without `nvcc` will install CUDA toolkit packages before building the CUDA runtime.
- [x] Allow forced non-interactive runtime builds to attempt CUDA toolkit dependency install instead of silently falling back to CPU.
- [x] Add portability coverage for installer CUDA toolkit behavior.

## Installer Python Diagnostics Follow-Up

Current checklist:
- [x] Add interactive basedpyright install through `pipx` for externally-managed Python environments.
- [x] Add apt-based `pipx` install guidance and portability coverage for the basedpyright installer prompt and retry guidance.

## Installer Runtime Validation Follow-Up

Current checklist:
- [x] Fix post-build validation to inspect built runtime bundle subdirectories instead of the runtime root.
- [x] Prefer the detected GPU backend bundle when persisting `LLAMA_SERVER_BIN`.
- [x] Add portability coverage preventing regression to root-level runtime validation.

## Installer Harness Integration Follow-Up

Current checklist:
- [x] Add an interactive post-sync check for installed LMM assets, live llama-server config files, OpenCode config, oh-my-openagent config, and GlyphOS policy.
- [x] Recommend an OpenCode install command based on available host package managers and offer the supported install alternatives.
- [x] Offer to fetch the upstream oh-my-openagent installation guide when the local agent config is missing.
- [x] Install oh-my-openagent from the wizard when missing, using `bunx` when available and `npx` as fallback.
- [x] Add portability coverage for the new installer wizard surface.

## oh-my-openagent Upstream Deferred Busy Parent Wake Fix

Applied upstream commit 5a4127c — replaces the old `prompt`→`promptAsync` hack.

Current checklist:
- [x] Inspect deployed oh-my-openagent and confirm upstream 5a4127c patch presence.
- [x] Apply the 5-edit deferred wake mechanism to BackgroundManager.
- [x] Revert old `prompt`→`promptAsync` patch in favor of upstream's deferral approach.
- [x] Verify dist loads correctly with bun.
- [x] Save unified patch file at `docs/patches/oh-my-openagent-local.patch`.
- [x] Update docs to reference upstream fix instead of old hack.
- [ ] E2E runtime test: restart opencode, dispatch background sub-agent, confirm parent wakes correctly.
- [ ] If wake works, open upstream PR or comment on #3883 with local evidence.

Review:
- Patched `dist/index.js` with 5 edits: `pendingParentWakes` field, `notifyParentSession` deferral, `flushPendingParentWake` method, `session.idle` flush, shutdown cleanup.
- Backups: `index.js.bak-issue3883-20260509144721` (original), `index.js.bak-upstream-5a4127c-20260510` (patched).
- Reapply with: `cd ~/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent && patch -p0 < /path/to/repo/docs/patches/oh-my-openagent-local.patch`
- Team mode not configured — upstream b36389e tool-visibility fix is NOT needed.

## oh-my-openagent Issue 3883 Task Defaults Fix

Current checklist:
- [x] Patch deployed `prepareDelegateTaskArgs` so omitted `run_in_background` defaults to `false`.
- [x] Patch deployed `prepareDelegateTaskArgs` so omitted `load_skills` defaults to `[]`.
- [x] Preserve explicit invalid argument behavior such as `load_skills=null`.
- [x] Add LMM-side doctor detection for the task default patch.
- [x] Document upstream fix proposal and local verification.

Review:
- Patched deployed oh-my-openagent `dist/index.js` to default omitted `task()` fields without accepting explicit `load_skills=null`.
- Added repo/deployed `llama-model doctor` field `oh_my_openagent_task_defaults_patch`.
- Installed doctor now reports `oh_my_openagent_task_defaults_patch: yes`.
- OpenCode still needs restart to load the patched plugin bundle.

## OpenCode Stop After oh-my-openagent Patches Investigation

Current checklist:
- [x] Read docs for OpenCode/LMM architecture and known timeout/patch behavior.
- [x] Inspect live OpenCode, gateway, backend, and oh-my-openagent process/log state.
- [x] Verify whether the current failure is wake-up, task argument defaulting, timeout, provider mismatch, or process crash.
- [x] Propose a fix plan with concrete repo/deployment changes.

Review:
- Live process inspection found OpenCode, both LMM gateway lanes, and the llama backend stopped.
- `llama-model doctor` still reports both deployed oh-my-openagent hot patches present, but runtime health is unavailable because the backend and gateways are down.
- `/tmp/oh-my-opencode.log` shows the concrete background-task failure: the child session tried `glyphos-fast/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf` and failed with `ProviderModelNotFoundError`.
- Current deployed OpenCode config now uses `llamacpp_fast/...` and `llamacpp/...`, but stale repo docs/tests still mention `glyphos-fast`/`glyphos` for oh-my-openagent.
- The oh-my-openagent auto-updater is still a deployment risk: logs show an attempted/latest update path from 3.17.13 to 4.0.0, which can overwrite local hot patches unless disabled or replaced by a repo-owned installer path.

## oh-my-openagent Crash Containment Follow-Up

Current checklist:
- [x] Add a doctor log scan for fatal oh-my-openagent/OpenCode plugin errors, including `ProviderModelNotFoundError`, task argument validation failures, and session/plugin crash signatures.
- [x] Add an LMM safe-mode command or doctor-guided repair that can temporarily remove `oh-my-openagent@latest` from `opencode.json` without deleting the user's plugin config.
- [x] Add a recovery note to docs explaining that removing the plugin should restore OpenCode while leaving LMM, llama-server, gateways, and dashboard intact.
- [x] Add regression coverage proving `sync-opencode` keeps `auto_update: false`, rejects stale `glyphos`/`glyphos-fast` provider IDs as OpenCode provider names, and preserves GlyphOS full/fast lane semantics in display names/docs.
- [x] Prepare an upstream #3883 comment recommending graceful tool-call failure and host-app crash isolation when `task(...)` arguments or provider model IDs are invalid.

Review:
- Windows feedback on #3883 suggests plugin failures can break the whole OpenCode desktop app. In the LMM stack, that risk applies to the OpenCode process/plugin layer, not to the separate LMM backend, gateway, or dashboard services.
- The local failure evidence is consistent with this class: oh-my-openagent tried `glyphos-fast/...`, OpenCode only registered `llamacpp_fast/...`, and the plugin raised `ProviderModelNotFoundError`.
- LMM should therefore treat oh-my-openagent as an optional integration that can be disabled for recovery without disrupting the local model runtime.

## oh-my-openagent Background Task Model Resolution Fix

Corrected diagnosis and fixes for the `glyphos-fast` model resolution failure in background tasks.

Current checklist:
- [x] Root cause: opencode PID 5751 started at May 9 10:10 AM, before oh-my-openagent.json was updated at 6:28 PM. In-memory `pluginConfig.agents` has stale `glyphos-fast` references.
- [x] Fix A: Add `glyphos-fast`/`glyphos` → `llamacpp_fast`/`llamacpp` provider alias remapping in `resolveModelForDelegateTask` (dist/index.js line 100000).
- [x] Fix B: Add `glyphos-fast` as backward-compatible provider entry in `opencode.json` pointing to port 4011/v1.
- [x] Fix C: `resolveParentContext` uses `getMainSessionID()` instead of stale `ctx.sessionID` (line 98478).
- [x] Patch file updated: `docs/patches/oh-my-openagent-local.patch` (180 lines, all 3 fixes).
- [x] E2E verification: stale PID 5751 is dead; both running PIDs (150515, 190240) started after dist was patched; gateways restarted with deployed fixes; all services healthy.

Review:
- The two coupled bugs: (1) stale `glyphos-fast` provider in agent config → "Model not found" on background launch; (2) stale `ctx.sessionID` → wrong parent wake target.
- Dispatch routing is NOT broken — confirmed via live test with `bg_3daadfd2` producing `[background-agent]` log entries.
- Config is read once at process startup via `loadPluginConfig` (line 134129). File updates after process start have no effect until restart.
- Provider alias in `resolveModelForDelegateTask` is a safety net for any future provider renames.
- `opencode.json` provider alias provides defense-in-depth if code alias doesn't apply. Both needed for full coverage.
- Child sessions in DB show `Agent: None, Model: None` — model is embedded in first message data, not session record.

## LMM Gateway Tool Invocation Guard

Current checklist:
- [x] Add lane-visible tool-use guidance telling local models to emit structured task tool calls and never print `task(...)` as plain text.
- [x] Add gateway detection for textual `task(...)` pseudo-calls when the `task` tool is declared.
- [x] Convert parseable textual pseudo-calls into provider-shaped OpenAI/Anthropic tool-use responses before they reach OpenCode.
- [x] Fail loudly when a textual `task(...)` pseudo-call is detected but cannot be repaired.
- [x] Add per-turn telemetry fields: `tool_invocation_mode`, `tool_name`, `provider`, `lane`, `session_id`, `repair_attempted`, and `repair_succeeded`.
- [x] Add focused regression coverage for OpenAI non-stream pseudo-call repair and SSE tool-call mode reporting.
- [x] Patch both repo files and the deployed LMM gateway copy.
- [x] Fix OpenAI SSE holdback so tool-capable streamed requests emit real `tool_calls` deltas instead of leaking pseudo-tool text.
- [x] Add regression coverage proving streamed Bash/task pseudo-calls are converted before client-visible content.
- [ ] Restart LMM backend and gateways from a persistent user terminal before the next live OpenCode proof run.
- [ ] Run a minimal background-task E2E proof with healthy `llama-model current`, `gateway status`, and `gateway fast status`.
- [x] Repair raw OpenAI-style function JSON printed as text, e.g. `{"type":"function","function":{"name":"background_output","arguments":...}}`.
- [x] Add containment for repeated identical pseudo-tool-call text by converting only the first detected call into one streamed tool-call delta.
- [x] Repair Anthropic-style `tool_use:` / `{"type":"tool_use",...}` text leaks as textual pseudo-calls in repo and deployed LMM normalizer.

Review:
- This addresses the latest failure mode where GlyphOS/llama.cpp printed `task(subagent_type=..., run_in_background=true, ...)` as text instead of producing a structured tool invocation.
- The gateway now repairs parseable pseudo-calls deterministically into real tool-call responses; if repair fails, it returns `task tool invocation formation failed` with diagnostic context rather than silently showing fake tool text.
- Streaming mode now records whether detected tool output was `structured` or `textual_pseudo_call`, but already-streamed text cannot be fully hidden without a future streaming buffer/holdback design.
- 2026-05-11 OpenCode proof showed that caveat is now the active bug: OpenCode printed a fenced bash command, so SSE holdback/repair is required before OpenCode tool execution can be called fixed.
- 2026-05-11 user proof showed background delegation, sub-agent completion, system reminder, and parent wake now partially work. Remaining failure: after wake, the model prints repeated raw OpenAI-style function-call JSON for `background_output` / `ast_grep_search` instead of emitting a structured client-visible tool call.
- Added parser support for printed OpenAI-style `{"type":"function","function":{"name":...,"arguments":...}}` objects, including a malformed spilled-argument variant seen with `ast_grep_search`.
- Added parser support for printed Anthropic-style `tool_use:` blocks and raw `{"type":"tool_use",...}` objects, preserving tool IDs and arguments while reporting `tool_invocation_mode=textual_pseudo_call`. Deployed copy at `/home/angelo/.local/share/llama-model-manager/scripts/gateway/protocol_normalizers.py` was updated and import-verified.
- E2E background task proof is partially passing but not clean: child completion reaches the parent, then tool-call formatting fails in the resumed parent turn.

## Claude/OpenCode Tool Invocation Formation Regression

Current checklist:
- [x] Inspect Claude gateway handling of Anthropic `tools` / `tool_choice` payloads.
- [x] Verify whether Claude Code Bash tool declarations are preserved into the local model prompt.
- [x] Add detection/repair for shell-command pseudo-tool output where a declared Bash tool exists.
- [x] Add detection/repair for Claude-style `tool_use:` / raw `tool_use` JSON text leaks.
- [x] Add regression coverage for Claude-style Bash tool invocation formation.
- [x] Deploy gateway changes and retest Claude Code interactive tool use.
- [x] Fix stream-handler telemetry to use normalized tool reports instead of raw SSE transport metadata.
- [x] Add regression coverage for streamed pseudo-tool repair telemetry in OpenAI and Anthropic handlers.

Review:
- Claude Code transcript showed the same class of failure as OpenCode: the local model printed shell commands (`find ...`, `ls -la`, `grep ...`) as assistant text instead of invoking the declared Bash tool.
- This points at the LMM/GlyphOS local lane's tool-use formation path, not at provider drift or parent wake-up.
- Root cause 1: `scripts/claude_gateway.py` dropped Anthropic `tools` / `tool_choice` when building upstream llama.cpp requests, so the local model did not see a strong tool contract.
- Root cause 2: the gateway always returned text/end-turn responses, so pseudo-tool outputs were never shaped back into Anthropic `tool_use`.
- Root cause 3: follow-up turns dropped prior `tool_use` / `tool_result` content, so the model could not see that tools had already executed and could repeat calls.
- Fixed repo and deployed LMM gateway copy. Claude gateway restarted with patched code.
- Live verification: `claude --bare --verbose --dangerously-skip-permissions --tools Bash --output-format stream-json -p "Use Bash to run pwd, then stop."` emitted real `tool_use`, executed Bash, received `tool_result`, and returned the path as final text.
- Follow-up patch classifies printed `tool_use:` / raw `{"type":"tool_use",...}` as repaired textual pseudo-calls, not genuine structured calls, because genuine tool calls do not arrive as assistant text from llama.cpp.
- Follow-up patch fixed OpenAI and Anthropic stream handlers to persist `repair_attempted` / `repair_succeeded` from a normalized `classify_tool_invocation(text, payload)` report. `RunRecord` now preserves tool telemetry fields so persisted run records match gateway telemetry.

## Glyph Encoding Skipped Investigation

Current checklist:
- [x] Inspect live gateway telemetry for latest context and glyph encoding status.
- [x] Trace `glyph_encoding_status` from dashboard summary back to gateway context provider.
- [x] Patch gateway trace status so context-disabled/no-context turns do not show generic `skipped`.
- [x] Remove stale browser-local activation from backend readiness decisions.
- [x] Add regression coverage for disabled/no-context glyph encoding trace labels.
- [x] Deploy patched gateway/UI files to installed LMM copy.

Review:
- Live telemetry at `/home/angelo/.local/state/llama-server/lmm-gateway-requests.json` shows `context_status: disabled`, `context_used: false`, and `glyph_encoding_status: skipped`.
- That means the encoder is not failing; it is never reached because the context/GlyphOS pipeline is disabled in the gateway process.
- The dashboard currently collapses that into `Glyph Encoding skipped`, which hides the real cause.
- The frontend also treats browser `localStorage` activation as equivalent to backend defaults, so it can show the pipeline as enabled even when the gateway environment still has `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE` unset.
- Gateway traces now report `glyph_encoding_status: disabled` when the pipeline is disabled, `glyph_encoding_status: no_context` when retrieval is empty, and `glyph_encoding_status: context_unavailable` when retrieval fails, instead of generic `skipped`.
- Dashboard readiness now follows backend defaults/API state instead of stale browser-local activation flags.
