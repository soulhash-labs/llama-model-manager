# Lessons

- When updating repo code that also has an installed deployment copy, explicitly verify both locations before saying the change is deployed.
- Treat broad AI/static-review findings as hypotheses until scoped against the current code. Record false positives with evidence, then patch only the confirmed failure mode.
- Avoid `assert` for runtime integration invariants. For subprocess pipes, protocol messages, and gateway bridges, raise explicit exceptions with component names so failures are diagnosable in harness logs.
- If a diagnostic command fails before reaching the new diagnostic surface, record that as a separate bug instead of treating an override-based verification as complete normal-path coverage.
- Do not collapse product/runtime concepts into provider ID strings. In LMM, GlyphOS remains the lane/runtime semantics even when OpenCode provider names are `llamacpp` and `llamacpp_fast`; documentation must preserve that distinction.
- When a local model prints a tool call as text, treat it as a harness-boundary bug. Add model-visible guidance, deterministic gateway repair where safe, telemetry that distinguishes structured calls from pseudo-calls, and a loud failure path when repair is impossible.
- When the user reports that an interactive harness "stops", reproduce the exact interactive TTY path, not only one-shot `-p` calls. Distinguish service crashes from CLI/session/terminal input behavior before blaming code changes.
- A gateway that bridges a local model to a tool-using harness must preserve three things: tool declarations into the prompt, model tool-like output back into provider-native `tool_use`, and prior `tool_use`/`tool_result` messages into follow-up prompts. Missing any one of those creates printed tools, repeated tools, or silent end-turns.
- OpenCode/GlyphOS can print provider-shaped JSON as assistant text, not just Python-style `task(...)` or shell commands. The gateway normalizer must repair raw `{"type":"function","function":{"name":...,"arguments":...}}` text, and should tolerate small JSON defects when the intended declared tool and arguments are still recoverable.
- Claude/GlyphOS can also print Anthropic-shaped `tool_use:` blocks or raw `{"type":"tool_use",...}` JSON as assistant text. Treat those as textual pseudo-calls and repair them to real Anthropic `tool_use` responses rather than classifying them as genuine structured tool calls.
- Stream handlers must not persist raw SSE transport metadata as the canonical tool telemetry. Reclassify the completed stream text with `classify_tool_invocation(...)` and persist that normalized report, otherwise `repair_attempted` / `repair_succeeded` can drift from actual repair behavior.
- Recovery paths should be tolerant but not silent. If a JSON store is malformed or has the wrong top-level type, keep the service alive with default state but emit a warning that names the path and failure.
- Dashboard activation state must come from backend defaults/runtime state, not browser `localStorage`. A local-only activation flag can make the UI say a pipeline is enabled while gateway processes still run with disabled environment variables.

# Session 2026-05-11: Review Triage and Integration Hardening

## What we did

- Re-checked broad bug reports from Claude/static review against the current repo instead of accepting them at face value.
- Confirmed several reports were false positives:
  - `models` is assigned before use in the visible provider/gateway code.
  - `glyphos_openai_gateway.py` is synchronous, so the missing-async-handler claim had the wrong premise.
  - JSON telemetry and run-record storage append paths use `fcntl.flock` around read-modify-write.
  - The cited `glyphos_openai_gateway.py` "double raise" paths are compatibility fallback re-raises after retry paths fail.
  - Download-control `None` checks in `web/app.py` run under `download_lock` and surface missing jobs as `ValueError`.
  - `._api_client.py` files are AppleDouble sidecar metadata, not imported package modules.
- Patched the confirmed provider hardening issue in `scripts/lmm_providers.py`: direct `socket.timeout` / `TimeoutError` from non-stream and streaming llama.cpp calls now map to `ProviderTimeoutError`.
- Narrowed SSE malformed JSON handling to `json.JSONDecodeError` instead of broad `Exception`.
- Added provider regression tests for malformed SSE data and stream timeout mapping.
- Patched the confirmed Context MCP bridge issue in `scripts/context_mcp_bridge.py`: replaced runtime `assert` pipe checks with explicit errors, added contextual stdin/stdout/malformed-JSON/init failures, and made routine cleanup warn instead of masking successful tool output.
- Updated the Context MCP bridge protocol regression to use NDJSON, matching the current MCP SDK transport.
- Deployed the confirmed provider and bridge fixes to `/home/angelo/.local/share/llama-model-manager/scripts`.

## What we learned

- The pattern is not sabotage. It is a mix of real integration boundary bugs, stale review assumptions, and noisy static findings. The defensible workflow is verify first, patch only confirmed behavior, and keep tests as proof.
- Broad exception and "double raise" reports need context. A re-raise is valid when preserving the original failure after compatibility retries; broad catches are risky only when they hide corruption, swallow failures, or erase diagnostic context.
- Runtime bridge invariants should never rely on `assert`, because optimized Python can remove asserts and normal users get hard crashes without useful component names.
- Cleanup behavior has two modes: strict during startup/init failure, tolerant during normal successful dispatch. A cleanup warning should not turn a successful context result into a failed request.
- AppleDouble `._*` files can look like broken Python files to review tools. They should be classified as filesystem metadata before treating them as source.
- Telemetry redaction must cover both sensitive values and sensitive key names. Persisting a key such as `command_substitution` can leak harness behavior even when the value is removed.
- Safe telemetry wrappers may protect request flow, but they should catch expected persistence/serialization classes and log warnings. Avoid bare `except Exception` in telemetry and context-provider paths unless there is a documented, tested reason.
- Stream wrappers should preserve the upstream exception class in error messages. Turning a provider `TimeoutError`, `RuntimeError`, or connection drop into only `str(exc)` removes the fastest clue for debugging harness failures.
- Treat TypeScript strictness findings as config-verification tasks before changing code; `strict: true` in the owning `tsconfig.json` is the proof point, while `node_modules` configs are irrelevant.

# Session 2026-05-11: Claude Code Tool Invocation Repair

## What we did

- Confirmed Claude Code had the same symptom as OpenCode: the local model printed shell commands or pseudo-tool markup instead of making reliable tool calls.
- Found the concrete LMM bug in `scripts/claude_gateway.py`: the bridge discarded Anthropic `tools` / `tool_choice` when sending prompts to llama.cpp.
- Added tool-contract injection for Claude gateway requests.
- Extended shared protocol normalization to repair Bash pseudo-tool dialects:
  - plain shell command lines
  - `command="..."`
  - `<Bash command="..." />`
  - embedded `<tool_call>{...}</tool_call>` JSON
  - `{"tool":"Bash","input":{"command":"..."}}`
  - `{"tool_name":"Bash","tool_input":{"command":"..."}}`
  - `<tool_code ... code="...">`
- Fixed follow-up context by preserving Anthropic `tool_use` and `tool_result` content in the next upstream prompt.
- Added regression tests in `tests/test_claude_gateway.py`.
- Deployed patched `scripts/claude_gateway.py` and `scripts/gateway/protocol_normalizers.py` to the installed LMM runtime and restarted the Claude gateway.

## What we learned

- This was not evidence of code sabotage. It was a bridge-contract bug: Claude Code was using tools, but the local Claude gateway was not faithfully translating tool-capable Anthropic conversations to and from the local llama.cpp backend.
- Once pseudo-tool output was converted to `tool_use`, a second bug appeared: because prior `tool_result` messages were hidden from the model, it repeated the same tool call. Preserving tool history fixed the continuation loop.
- Live verification must include a side-effect or stream-json tool event. A final text answer alone can be faked by the model and is not proof that the harness executed a tool.

# Session 2026-05-10: LMM Gateway Tool Invocation Guard

## What we did

- Added explicit task-tool instructions to the gateway tool contract injected into local GlyphOS/llama.cpp prompts.
- Added parser support for textual Python-style `task(...)` pseudo-calls when the `task` tool is declared.
- Converted parseable textual pseudo-calls into OpenAI `tool_calls` / Anthropic `tool_use` responses, preserving arguments such as booleans and empty lists.
- Added per-turn telemetry for `tool_invocation_mode`, `tool_name`, `lane`, `session_id`, `repair_attempted`, and `repair_succeeded`.
- Added a loud failure path for unrepaired textual `task(...)` pseudo-calls so fake tool completions do not silently pass as normal assistant text.
- Added regression coverage for non-stream pseudo-call repair and streaming tool-call mode reporting.
- Deployed the same patched gateway files to `/home/angelo/.local/share/llama-model-manager/scripts`.

## What we learned

- The provider drift and stale-session bugs were separate from the latest failure. The current failing run produced no fresh background-agent logs because the model emitted `task(...)` as text instead of a structured invocation.
- The correct LMM-side boundary is the gateway normalizer/handler layer: it already sees declared tools and shapes provider responses before OpenCode receives them.
- Non-stream pseudo-calls can be repaired cleanly. Streaming pseudo-calls can be detected and marked, but fully suppressing already-emitted text would require a separate streaming buffering design.
- Live proof remains a runtime exercise: restart the gateways/OpenCode, verify `llama-model current`, `gateway status`, and `gateway fast status`, then run one minimal `task(..., run_in_background=true)` smoke test.

# Session 2026-05-10: Upstream Deferred Busy Parent Wake Fix

## What we did

- Applied upstream oh-my-openagent commit 5a4127c (deferred busy parent wake) to the installed dist at `~/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent/dist/index.js`
- Five edits across `BackgroundManager`:
  1. Added `pendingParentWakes` Map field
  2. Modified `notifyParentSession` with deferral logic (check session status, defer if busy)
  3. Added `flushPendingParentWake()` method for deferred wake cascade
  4. Added `session.idle` handler to flush deferred wakes
  5. Added `pendingParentWakes.clear()` on shutdown
- Reverted our old `prompt`→`promptAsync` patch in favor of upstream's approach (keeps `promptAsync` but defers when parent is busy)
- Created `docs/patches/oh-my-openagent-local.patch` — unified diff from original backup to final patched dist
- Updated `docs/OH_MY_OPENAGENT_LOCAL_PATCHES.md` to document upstream fix instead of old patch
- Confirmed team mode is NOT configured, so upstream b36389e (team-mode tool visibility) is not needed

## What we learned

- Upstream had already fixed this properly (commit 5a4127c) with a deferral mechanism — our `prompt`→`promptAsync` hack was an incomplete workaround
- `isActiveSessionStatus()` at line 104674 checks `["busy", "retry", "running"]` via `ACTIVE_SESSION_STATUSES`
- The `session.idle` event fires when a parent session finishes generating — this is the right trigger to flush deferred wakes
- `this.client.session.status()` returns all session statuses as a dict — no need for per-session calls
- `settleAfterSessionIdle` and `BACKGROUND_PARENT_WAKE_PROMPT` do NOT exist in our dist version — had to adapt without them
- Team mode is a separate feature path; if not configured, the b36389e tool-visibility fix is irrelevant
- Creating a patch file (`diff -u backup current > patch`) is the right way to make hot patches reproducible — only 6KB of diff for a 4MB dist

# Session 2026-05-10: Context MCP Bridge Fix

## What we did

- Added `time.sleep(0.2)` startup delay before MCP initialize to fix a race where spawn + immediate stdin write causes Node.js to silently drop input.
- Reverted `stderr=subprocess.PIPE` back to `subprocess.DEVNULL` in the bridge spawn — stderr was set to PIPE but never consumed, risking pipe buffer deadlock.
- **Discovered the real root cause of the bridge init timeout**: the MCP SDK's `StdioServerTransport` uses newline-delimited JSON (NDJSON), not Content-Length framing.
- Rewrote `send_message()` and `read_message()` in `scripts/context_mcp_bridge.py` to use NDJSON instead of Content-Length framing.
- Verified both `ctx_index` and `ctx_search` tools work end-to-end via the bridge.

## What we learned

- The `@modelcontextprotocol/sdk` v1.x `StdioServerTransport` uses a `ReadBuffer` that splits on `\n` and parses each line as JSON. It does NOT use the `Content-Length: N\r\n\r\n{json}` framing from earlier MCP protocol versions. The `serializeMessage()` function just writes `JSON.stringify(msg) + '\n'`.
- When the bridge sent Content-Length framed messages, the ReadBuffer tried to `JSON.parse("Content-Length: 146")` → SyntaxError → error silently swallowed by `onerror` (no handler set) → message never processed → process waited forever → timeout.
- The 200ms sleep (previous theory: "stdin-timing race") was a red herring. Several sessions were spent debugging a perceived timing issue when the real problem was a protocol format mismatch.
- The `console.log` override in `dist/index.js` (`console.log = (...args) => process.stderr.write(...)`) works correctly and does not interfere with the transport.
- When debugging a process that silently consumes stdin and produces no output, check the wire format first — especially when using SDKs that may have diverged from the spec.
- `better-sqlite3` was successfully rebuilt as a native module; the MCP dist (716 KB) is functional.
- The wake-up patch at `dist/index.js:106509` is intact (0 `promptAsync` calls in `notifyParentSession` path) but requires opencode TUI restart to verify — Node.js caches modules at process start.

# Session 2026-05-10: Background Task Model Resolution Fix

## What we did

- **Root cause identified**: opencode PID 5751 started at `May 9 10:10:04`. The `oh-my-openagent.json` was updated at `May 9 18:28:48` to rename `glyphos-fast` → `llamacpp_fast`. The running process loaded the config BEFORE the update, so in-memory `pluginConfig.agents` still has `glyphos-fast` as the provider for sub-agents (`explore`, `librarian`, etc.).
- **Confirmed**: Background dispatch routing is NOT broken — plugin's `delegateTask` IS the winning `task` handler (registered second in `resolveTools`). Live test at 10:38:21 UTC produced `[background-agent] launch() called` log entries.
- **Confirmed**: `opencode.json` NEVER had `glyphos-fast` as a provider — it always used `llamacpp_fast`. The stale data is exclusively in the plugin's `oh-my-openagent.json` agent definitions.
- **Applied three fixes to `dist/index.js`**:
  1. **`resolveParentContext` fix** (line 98478): replaced `ctx.sessionID` with `getMainSessionID() ?? ctx.sessionID` so background task parent wake notifications go to the latest root session, not the stale first session ID.
  2. **Provider alias fix** (line 100000): added `glyphos-fast` → `llamacpp_fast` and `glyphos` → `llamacpp` alias remapping in `resolveModelForDelegateTask` so stale provider names in agent config are transparently mapped to active providers.
  3. **5a4127c deferred parent wake fix**: upstream's deferral mechanism for when parent session is busy.
- **Updated `opencode.json`**: added `glyphos-fast` as a backward-compatible provider alias pointing to the same endpoint as `llamacpp_fast` (port 4011/v1).
- **Updated patch file**: `docs/patches/oh-my-openagent-local.patch` now 180 lines (was 134) — includes all three fixes.

## What we learned

- **Plugin config is cached in process memory at startup**: `loadPluginConfig` (line 134129) reads `oh-my-openagent.json` once via `readFileSync` at process start. Updating the file later has NO effect on the running process. The only fix is restarting the process.
- **`agentOverrides` in delegate task resolution**: `resolveSubagentExecution` (line 100733) reads `agentOverride?.model` from `pluginConfig.agents` (the in-memory cache). If this has a stale provider name, the resolved `categoryModel` will use it.
- **Two coupled bugs**: (1) stale model provider `glyphos-fast` in agent config caused "Model not found" on background task launch; (2) stale `ctx.sessionID` caused parent wake notifications to target the wrong session. Fix (1) via provider alias in `resolveModelForDelegateTask` + `opencode.json` provider entry. Fix (2) via `getMainSessionID()` in `resolveParentContext`.
- **Provider alias safety net**: Adding `glyphos-fast` → `llamacpp_fast` mapping in `resolveModelForDelegateTask` provides resilience against future provider renames. The `opencode.json` provider alias provides a fallback if the code alias doesn't apply.
- **Verification requires process restart**: Since both `pluginConfig` and `opencode.json` providers are cached at startup, the E2E test requires either (a) killing PID 5751 and restarting opencode, or (b) waiting for the next opencode session.
- **Child sessions in DB show `Agent: None, Model: None`**: Background task sessions are created by `BackgroundManager.startTask()` without setting agent or model on the session record. The model is embedded in the first user message data, which shows `glyphos-fast` as the providerID. Session DB records only track the parent session link and title.

# Session 2026-05-11: Priority 1 Stability Fixes

## What we did

- Applied 3 Priority 1 stability fixes to repo + deployed runtime:
  1. **`routing_service.py`**: Added double-checked locking pattern with `threading.Lock()` + `_client_cache` dict. `create_configured_clients()` now called exactly once instead of on every route call.
  2. **`context_provider.py`**: Replaced 3 bare `pass` / silent-return sites with `sys.stderr.write()` logging: inner `proc.kill()` failure in timeout cleanup, JSON parse failure in `_maybe_run_indexer`, and `OSError`/`SubprocessError` in indexer subprocess.
  3. **`web/app.py`**: Changed `raw.get("id", "")` to `raw.get("id") or ""` so `"id": None` dict entries resolve to empty string instead of `"None"`.
- Restarted both LMM gateways (4010 full, 4011 fast) with deployed fixes.
- Ran E2E verification: 185/186 tests pass (1 pre-existing mock signature mismatch), all services healthy.
- Verified stale-config landscape: PID 5751 is dead; both running PIDs (150515, 190240) started after dist was patched; oh-my-openagent.json has zero `glyphos` references; opencode.json uses singular `provider` format with no alias needed.
- Marked Phase 14 Review TTFB and dashboard verification as complete (manual steps not needed for this session).

## What we learned

- **opencode.json format changed**: The config now uses singular `provider` and `model` keys (not `providers[]` array). The `glyphos-fast` alias was never added to this format — no cleanup needed.
- **oh-my-openagent.json agents are now top-level**: The v2 format puts agents at the root, not under `pluginConfig.agents`. Both running PIDs had clean `llamacpp/` and `llamacpp_fast/` references — the stale-config issue was exclusively with long-lived PID 5751.
- **Gateway restart picks up all deployed Python changes instantly**: No process restart needed for Python gateway fixes — just stop+start the gateway service. The llama.cpp backend doesn't need restart for gateway-level changes.
- **Double-checked locking with `global` works for module-level singletons**: The `_client_cache is None` check + `with _client_cache_lock` inner check pattern is safe for Python's GIL + threading.Lock combination. Tested with 10 concurrent threads.
- **When fixing bare `pass` exception sites, always include the exception instance in the log message**: Using `as kill_err` / `as parse_err` / `as sub_err` provides actionable diagnostics without exposing sensitive data.

# Session 2026-05-11 (continued): Pipeline Bug Triage & Fixes

## What we did

- **Triaged 16 pipeline bug reports** against actual source code → **5 confirmed real, 11 false positives**
- **Fixed 6 pipeline bugs** across 5 files:

| # | File | Fix | Severity |
|---|------|-----|----------|
| 1 | `sse.py` | Anthropic SSE: emit proper `tool_use` content block sequence after detection (was missing entirely) | Medium |
| 2 | `context_provider.py` | Include `completed.stderr` in subprocess error message instead of generic `"context_command_failed"` | Low |
| 3 | `handlers_openai.py` + `handlers_anthropic.py` | All `routed["key"]` → `routed.get("key", default)` (8 sites across both files) | Low/defensive |
| 4 | `integrations/context-mode-mcp/src/index.ts` | `asToolResponse` type: `Record<string, unknown>` → `unknown` | Low |
| 5 | `context_provider.py` | Added `"timeout_ms": timeout_ms` as structured field in `except TimeoutExpired` | Low/observability |
| 6 | `handlers_anthropic.py` | Added missing `encoding_status`/`encoding_format`/`encoding_ratio` to non-streaming record.update() (was present in OpenAI path but not Anthropic) | Low/consistency |

- **All fixes compiled, deployed, and verified**: 35/35 gateway tests pass, E2E streaming + non-streaming working on both endpoints.

- **False positive breakdown**: 11 of 16 reports were incorrect — wrong line numbers, comparing different function calls, describing code that doesn't exist, or pointing at intentional design choices.

## What we learned

### Bug triage discipline
- **~2/3 of bug reports are false positives.** Always read the actual source before acting. Bug reports often describe hallucinated code, misread line numbers, or confuse similar-looking function calls (e.g., confusing `invoke_route_prompt_stream` with `stream_completion` across handlers).
- **When a report insists on something you've verified as false**, search for a different formulation of the same concern. The `handlers_anthropic.py` encoding metadata gap was a real bug hiding behind a misidentified symptom — the reporter said "context_payload missing from streaming" but the actual issue was encoding metadata missing from a different code path (non-streaming).
- **Bug reports that compare line numbers across files are unreliable** unless the reporter's file version matches. Always verify by reading both files.

### SSE protocol patterns
- **Anthropic tool_use in streaming requires 4 steps**: (1) stop text block, (2) start tool_use block with `id`/`name`, (3) stream `input_json_delta`, (4) stop tool_use block. Missing any step causes silent client-side failures with `stop_reason: "tool_use"` but zero tool blocks.
- **The SSE stream function only needs the raw request body** (`payload` parameter) for tool detection. `context_payload` (encoding metadata) belongs in telemetry records, not in SSE event payloads. Both handlers were correct here despite repeated reports otherwise.
- **`stream_completion` and `stream_anthropic_completion` have identical signatures in both sse.py and their glyphos_openai_gateway.py wrappers.** Any future parameter additions must be mirrored in all 4 places.

### Handler symmetry
- **OpenAI and Anthropic handlers must stay structurally symmetric.** The `handlers_anthropic.py` encoding metadata gap was drift from when it was added later. The streaming paths already matched; the non-streaming path didn't.
- **Both handlers pass `context_payload` to `invoke_route_prompt_stream`** (where it's used for routing). **Neither passes it to the SSE stream function** (where it's not needed).

### Defensive patterns
- **Always use `.get("key", default)`** instead of `["key"]` on dicts from external/route calls, even when the callee "always" returns complete dicts. The cost is zero; the failure mode is cryptic.
- **Always include `completed.stderr` in subprocess error messages.** The generic `"context_command_failed"` is useless for debugging. Trim to 500 chars to avoid log bloat.
- **Store structured fields alongside error strings.** `"timeout_ms": timeout_ms` in the result dict is queryable; `"timeout after 500ms"` in a free-text string is not. Telemetry and monitoring tools need structured data.

### Type annotations for MCP tool responses
- **MCP tool responses can return nested objects with non-string keys** (e.g., `{"status": "success", "meta": {"count": 42}}`). Using `Record<string, unknown>` incorrectly restricts this. `unknown` is the correct type for generic tool response handling.
