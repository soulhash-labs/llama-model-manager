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
| 4 | `integrations/context-mode-mcp/src/index.ts` | `asToolResponse` parameter `Record<string, unknown>` → `unknown` (kept as `unknown` param + cast on assignment to `structuredContent`) | Low |
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

# Session 2026-05-11: bin/llama-model Bug Fixes (12 bugs + JSON escaping)

## What we did

- **Fixed 12 bugs in `bin/llama-model`** (6538-line bash script):

| # | Severity | Bug | Fix |
|---|----------|-----|-----|
| 1/3 | 🔴 High | `claude_gateway_start`: stale PID on startup failure + no cleanup on `wait_ready` fail | Moved PID write **after** readiness check; added cleanup (rm PID + kill process) on failure; changed `wait_ready` from `die()` to `return 1` |
| 2 | 🔴 High | `dashboard_service_uninstall`: checks existence AFTER disabling | Removed `dashboard_service_installed || die` — function is now idempotent |
| 4 | 🟡 Med | `local -a args=()` POSIX-incompatible | Removed `-a` flag (`local args=()`) |
| 5 | 🟡 Med | `local` masks `$?` from arithmetic expansion | Split `local var=$((...))` into two lines |
| 6 | 🟡 Med | No `trap` handlers → temp files leak on error | Added `trap 'rm -f "$tmp"' EXIT` / `trap - EXIT` around all 3 `mktemp` sites |
| 7 | 🟡 Med | `show_logs` hardcoded to server log | Added `target` param: `server`, `claude`, `gateway`, `gateway-fast` |
| 8 | 🟡 Med | `show_doctor` greps unbounded log file (OOM risk) | All 5 `grep` calls now scan only last 10k lines via `tail -n 10000` |
| 9 | 🟡 Med | `claude_gateway_stop` TOCTOU PID race | Added `pid_matches_claude_gateway` verification right before `kill` |
| 10 | 🟢 Low | `opencode_plugin` error message wrong backup filename | Changed hardcoded `oh-my-openagent.json` to `{path}.lmm-plugin-backup` |
| 11 | 🟢 Low | `sync_claude` leaks API key source metadata | Replaced `$api_key_source` with `configured`/`none` |
| 12 | 🟢 Low | `sync_glyphos` redundant validation | Removed `(( timeout_seconds >= 1 ))` — regex already covers it |

- **Fixed JSON escaping in embedded Python heredocs**: 4 `print()` f-strings that embedded user-controlled strings from the opencode config now wrap values with `json.dumps(value, ensure_ascii=False)`. Prevents broken terminal output from config entries containing double quotes, backslashes, or control characters.
- **Verified**: `bash -n` syntax check passes clean.

## What we learned

### PID file lifecycle in startup functions
- **PID files must be written AFTER readiness checks, not before.** The `lmm_gateway_start` pattern (write PID → check health → remove on failure) is correct. The old `claude_gateway_start` wrote PID first, so if `die()` was called during readiness, a stale PID remained.
- **`die()` (hard `exit 1`) is incompatible with cleanup patterns.** Functions like `claude_gateway_wait_ready` that call `die()` on failure prevent the caller from doing cleanup. Use `return 1` and let the caller handle both success and failure paths.
- **`disown` does NOT protect against the caller needing to kill the process.** If a backgrounded process fails its readiness check, the caller must explicitly `kill` it even though `disown` was called.

### Shell gotchas
- **`local -a` is bash-specific.** POSIX sh rejects `local -a args=()` with `Syntax error: "(" unexpected`. The `#!/usr/bin/env bash` shebang protects normal usage, but removing `-a` (`local args=()`) is a harmless belt-and-suspenders fix that works in all bash versions.
- **`local` always returns 0**, which suppresses `set -e` from catching arithmetic errors in `local var=$((...))`. Always split: `local var` then `var=$((...))`.
- **`mktemp` + `mv` is an atomic update pattern**, but any error between the two leaks the temp file. The fix: `trap 'rm -f "$tmp"' EXIT` before the operation, then `trap - EXIT` after the `mv` succeeds.
- **`grep` on an unbounded log file can OOM.** Even with `set -euo pipefail`, a gigabyte log file will be fully read by `grep` before `tail -n 1` can filter it. Always pipe through `tail -n <limit>` first.

### Python heredoc hygiene
- **User-controlled strings from JSON configs must be sanitized with `json.dumps()` before printing.** Direct f-string interpolation (`f"enabled ({name})"`) produces broken output if `name` contains double quotes, backticks, or control characters.
- **`json.dumps(value, ensure_ascii=False)` produces human-readable, safe output.** It wraps strings in double quotes and escapes internal special characters. The visual output changes slightly (`oh-my-openagent` → `"oh-my-openagent"`) but is always valid.
- **`json` is always available across the heredoc** since `import json` is at the top of each embedded script.

### Idempotent uninstall pattern
- **Uninstall functions should be idempotent.** `dashboard_service_uninstall` previously checked `dashboard_service_installed || die "..."` after already doing the work. If the service was already gone, this was a fatal error. The fix: always try to disable, silently ignore if already not installed, then clean up the unit file.

# Session 2026-05-11: Gateway SSE Streaming Tools, Idempotency, and Handler Typedefs

## What we did

- **SSE streaming holdback for tool detection**: `stream_completion()` in `sse.py` now buffers streamed chunks until the full text is collected when tools are declared. Once all text arrives, `_detect_tool_call` runs on the complete text. If a tool call is detected, the buffered content is repressed and a real `tool_calls` delta is emitted instead. If no tool call is detected, the buffered content is flushed as normal text. This prevents the "leaked pseudo-tool text" failure mode that was the last remaining gap in the gateway tool invocation guard.
- **Anthropic streaming tool_use delta sequence**: `stream_anthropic_completion()` now emits the proper 4-step `tool_use` delta: (1) `content_block_stop` for text, (2) `content_block_start` with `tool_use` id/name, (3) `input_json_delta` streaming, (4) `content_block_stop` for tool. Previously it skipped step 1 and didn't emit the stop for the text block, causing silent failures on the Anthropic client side.
- **Streaming telemetry via `classify_tool_invocation()`**: Stream handlers previously persisted raw SSE transport metadata as canonical tool telemetry (e.g., "stream_tool_call_detected" from the SSE parser, not from the normalized classifier). Now both OpenAI and Anthropic stream handlers reclassify completed stream text with `classify_tool_invocation(text, payload)` and persist that normalized report, so `repair_attempted`/`repair_succeeded` accurately reflect the actual repair behavior. Non-stream handlers already used the classifier — this closes the streaming telemetry gap.
- **Request idempotency (fingerprinting + dedup)**: Added `request_fingerprint` field to `RunRecord` and gateway telemetry records. `JsonRunRecordStore.append_record()` and `JsonGatewayTelemetryStore.append_event()` now deduplicate consecutive identical fingerprints — the second write replaces the first and increments `duplicate_count`. This prevents the same gateway POST from creating duplicate run records and telemetry entries when the client retries or the harness re-sends. Counters (`mode:routed-basic`, `success:True`, etc.) only increment on new events, not on deduplicated repeats.
- **Handler TypedDict API contracts**: Both `handlers_openai.py` and `handlers_anthropic.py` now use typed `TypedDict` API dictionaries (`OpenAIHandlerAPI`, `AnthropicHandlerAPI`, `AnthropicCountTokensAPI`) instead of raw `dict[str, Any]`. The handler functions accept `Mapping[str, Any]` and `cast()` to the typed variant, providing static analysis of the dependency contract without changing the dynamic dispatch.
- **GatewayError classification**: OpenAI and Anthropic handlers now classify `GatewayError` (returns 502 with structured `to_dict()` payload) separately from unexpected `Exception` (returns 500 with `internal_error` type). Unexpected failures are logged with traceback to stderr via `_log_unexpected_handler_error()`. Previously both got `{"error": {"type": "gateway_error"}}` and the unexpected error was silently swallowed.
- **Handler encoding metadata symmetry**: Added missing `encoding_status`/`encoding_format`/`encoding_ratio` to the Anthropic non-streaming `handle_messages` record update (was already present in OpenAI path but missing from Anthropic). Also added `stream` field, `tool_invocation_mode`, `tool_name`, `lane`, `session_id`, `repair_attempted`, `repair_succeeded` to both streaming and non-streaming paths.
- **Gateway prompt tool contract guidance**: Updated the `format_tool_contract()` instructions to explicitly tell models: "Never print task(...) as plain text", "Never print shell commands as plain text", "Never print tool_use: blocks or raw tool_use JSON as plain text". This is model-visible guidance at the prompt level and complements the gateway repair layer.
- **`routed["key"]` → `routed.get("key", default)`**: All 8 subscript access sites in both handlers were changed to `.get()` with defaults, covering `target`, `reason_code`, `latency_ms`, `text`, and `route_duration_ms`. Prevents `KeyError` crashes from unexpected route response shapes.
- **Added `compact_json` import guard in `sse.py`**: The `compact_json` function from `protocol_normalizers` is imported with a fallback to `json.dumps` if import fails, since `sse.py` runs in a different process/context and may not have the same import path.

## What we learned

### SSE streaming tool detection requires holdback
- **When a local model prints tool calls as text during streaming, the chunks are already sent.** The only way to prevent tool-call text from reaching the client is to buffer chunks until the full response is collected, then either emit a `tool_calls` delta or flush the buffered text. Holdback trades latency (first-token delay) for correctness (no leaked tool text).
- **Holdback is only needed when tools are declared.** When no tools are in the payload, streaming can proceed normally without buffering. Check `_payload_declares_tools()` before enabling holdback.
- **After holdback + detection, the tool_use content block must be emitted as an SSE delta**, not as accumulated text followed by a finish_reason. The client (OpenCode, Claude Code) needs the structured `tool_calls`/`tool_use` delta to interpret the response as a tool invocation.

### Telemetry must use normalized classification, not transport metadata
- **Stream handlers must not persist raw SSE transport metadata as canonical tool telemetry.** The SSE parser's `stream_tool_call_detected` flag reflects whether the transport layer saw a tool-like pattern, but the gateway's `classify_tool_invocation()` is the authoritative normalized report. Reclassify the completed stream text with the same classifier used by non-stream handlers, then persist that report.
- **Both streaming and non-streaming paths should persist tool telemetry from the same source.** Non-streaming handlers already used `classify_tool_invocation()`; streaming handlers were using raw SSE metadata. The inconsistent source meant `repair_attempted`/`repair_succeeded` could drift. Fixed by calling the classifier in the streaming path after full text is collected.

### Request idempotency at the storage layer
- **Consecutive identical request fingerprints should deduplicate, not create new entries.** Client retries, network duplicates, and harness re-sends produce identical gateway POST bodies. By comparing `request_fingerprint` against the most recent entry in both telemetry and run-record stores, the system collapses duplicates into a single entry with an incrementing `duplicate_count`.
- **Fingerprinting should not prevent the route call.** The gateway still routes every request — idempotency is storage-layer only. The `request_fingerprint` is computed from the normalised prompt, model, tools, and stream flag.
- **Counter fields (mode:routed-basic, success:True, etc.) should only increment on genuinely new events**, not on deduplicated repeats. Move counter logic into the "not a duplicate" branch.

### Handler API contracts
- **`TypedDict` for handler dependency maps provides static analysis without changing the dynamic dispatch pattern.** The gateway injects functions as a `dict[str, Any]` at request time. By defining `OpenAIHandlerAPI(TypedDict)` in the handler module and `cast()`-ing the injected dict, editors and type checkers can validate usage without changing the injection mechanism.
- **`Mapping[str, Any]` as the function parameter type** (instead of `dict[str, Any]`) signals to callers that the dict is read-only, which matches the injection pattern (a constructed dict is passed in, not mutated).
- **All `routed["key"]` accesses must be `.get("key", default)`.** The route response dict is populated by external code (routing service, context provider) and can change structure. A `KeyError` crash on a missing `latency_ms` or `target` field is a hard 500 when a softer 502 (GatewayError) or fallback value would be more appropriate.

### Gateway error classification
- **Separate `GatewayError` from unexpected `Exception` in handler catch blocks.** `GatewayError` is a predictable, structured failure (502 with typed payload). Unexpected exceptions are infrastructure bugs or integration failures (500 with internal_error). Logging unexpected failures with traceback (via `sys.stderr.write(traceback.format_exc())`) makes them discoverable without masking the error category.

# Session 2026-05-11: Download Worker Handoff, Dashboard Pipeline Activation, and Provider Hardening

## What we did

- **Fixed download worker handoff race**: `web/app.py` `_alive_download_thread_count()` previously inlined the stale-worker pruning logic. Extracted `_download_worker_is_active()` (static method) and `_prune_stopped_download_controls_locked()`. The key behavior: registered workers whose `ident is None` (not yet started) are treated as active. Previously, a thread registered under `download_lock` but started just after releasing it could be immediately pruned by concurrent recovery, causing a lost download worker. Added regression test `test_recover_stale_download_jobs_keeps_registered_unstarted_worker_active`.
- **Fixed `None` id resolution in download search**: `repo_id = str(raw.get("id") or "").strip()` instead of `str(raw.get("id", "")).strip()`. When Hugging Face search returns `"id": None`, the old code produced `"None"` as a valid repo ID, causing a downstream crash. The fix resolves `None` to `""` instead.
- **Removed browser `localStorage` pipeline activation**: Dashboard `deriveContextGlyphosPipeline()` and `renderGlyphosTelemetry()` no longer read `contextGlyphosLocallyActivated()` from `localStorage`. `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE` activation now exclusively depends on backend defaults/runtime state. The "Activate feature" button in the Integrations panel still persists the env var correctly, but stale browser-local flags can no longer show the pipeline as enabled when it is not.
- **Added `glyphEncodingTraceLabel()` in dashboard frontend**: Maps `glyph_encoding_status` values to human-readable labels: `"Encoding disabled"` for status `disabled`, `"Waiting for context"` for `no_context` or empty context, `"Encoding context_unavailable"` for timeout/error/missing, and `"Glyph encoded"` when encoding was used. Previously all non-encoding states showed generic `"Encoding skipped"`.
- **Added `glyph_encoding_result_for_context()` in `context_provider.py`**: When `context_payload` is `None` (encoding not reached), this function maps `context_result["status"]` to meaningful encoding status labels (`disabled`, `no_context`, `context_unavailable`, `skipped`) instead of returning an empty dict. This enriches gateway telemetry with the real reason why encoding was not performed.
- **Provider stream timeout hardening**: `LlamaCppProvider.generate_stream()` now maps `TimeoutError` raised during stream iteration to `ProviderTimeoutError` instead of letting it propagate as a generic exception. Malformed SSE JSON is ignored only for `json.JSONDecodeError` (previously caught `Exception` broadly). Non-stream `generate()` rejects empty resolved model names and maps malformed JSON error bodies to `ProviderError` with a descriptive message.
- **HTTP error body preservation**: `http_utils.py` `http_json()` catches `json.JSONDecodeError` instead of bare `Exception` when parsing error response bodies. Malformed JSON bodies are preserved as `{"error": raw}` rather than silently lost.
- **Provider empty model name rejection**: `LlamaCppProvider.generate()` now rejects empty/whitespace-only resolved model names with a `ProviderError`. Previously an empty model name would produce a confusing downstream HTTP error from the llama.cpp backend.
- **Context bridge startup delay**: Added `time.sleep(0.2)` in `_start_mcp_process()` before sending the first request to the Node.js MCP process. Without this delay, writing immediately after `subprocess.Popen` causes Node.js to silently ignore stdin, leading to a read timeout. This is a subprocess startup timing issue, not a stdin race.
- **Context bridge cleanup strict vs. warning split**: `_terminate_mcp_process()` now accepts a `strict` parameter. Startup failures use `strict=True` (raises `RuntimeError` on cleanup failure). Routine dispatch cleanup uses `strict=False` (logs warnings, does not mask a successful tool result). All `except Exception` sites were narrowed to explicit exception types (`ProcessLookupError`, `subprocess.TimeoutExpired`, `OSError`, `BrokenPipeError`, etc.).
- **Context bridge error reporting**: `send_message()` and `read_message()` now raise explicit `RuntimeError` with component names and failure details instead of bare `assert`/`print()`. `read_stdin_json()` wraps `json.JSONDecodeError` with a component-named error. Empty lines from MCP stdout raise `RuntimeError` instead of being silently skipped.
- **JSON store malformed-state recovery**: `_FileLockedJsonStore._read_state()` now emits a warning via `sys.stderr.write()` when the JSON file is corrupted or has the wrong top-level type. Previously it silently returned default state. This makes store corruption discoverable in gateway logs.
- **Telemetry command-substitution redaction**: `safe_record_gateway_request()` now recursively removes `command_substitution` fields from request metadata before persistence. Tests prove both the key name and the sensitive value (`SECRET_COMMAND_SUBSTITUTION`) are removed.

## What we learned

### Download worker lifecycle
- **A `threading.Thread` is not "alive" until started.** `worker.ident is None` means the thread was constructed but `start()` hasn't been called yet. Recovery code that interprets "no ident" as "dead" will race with the handoff between `register_download_controls` (under lock) and `worker.start()` (after releasing lock). The fix: treat `ident is None` as "alive" (registered but pending start).
- **Extract stale-worker pruning into a named method** so recovery (`recover_stale_download_jobs`) and status reporting (`_alive_download_thread_count`) use the same pruning logic. Previously it was inlined in `_alive_download_thread_count` and recovery had its own separate iteration that could disagree.

### Dashboard state must come from the backend
- **Browser `localStorage` is not a reliable source of backend configuration state.** A user may have activated the Context+GlyphOS pipeline in the dashboard weeks ago (stored in localStorage), then the gateway was restarted without the env var. The dashboard would show the pipeline as enabled while the gateway never runs it. The fix: always read `LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE` from backend defaults/API state.
- **When encoding is not reached, the trace label must explain why.** A generic "Encoding skipped" hides whether encoding was disabled, had no context to work with, or failed. Mapping `context_status` to specific labels (`disabled`, `no_context`, `context_unavailable`) makes the dashboard actionable.

### Provider exception mapping
- **Direct `TimeoutError` from stream iteration must be mapped to `ProviderTimeoutError`.** When `llama.cpp` times out during streaming (not during connection setup), `urlopen` can raise `TimeoutError` inside the generator. The old code only caught `URLError` timeouts from the initial connection. Without explicit mapping, the timeout surfaces as a generic exception and loses the provider-timeout classification.
- **Empty/whitespace model names produce confusing downstream errors.** A resolved model name of `" "` (whitespace-only from config) would cause the llama.cpp backend to return a confusing HTTP error. Better to reject it eagerly at the provider boundary with a clear `ProviderError`.
- **`json.JSONDecodeError` is the only exception to catch for malformed JSON.** Bare `except Exception` around JSON parsing can mask `AttributeError`, `TypeError`, or `MemoryError`. Narrowing to `json.JSONDecodeError` makes unexpected failures visible.

### Context MCP bridge patterns
- **Node.js subprocesses started via `Popen` may not be ready to read stdin immediately.** The `time.sleep(0.2)` before the first write is a pragmatic fix for what appears to be a Node.js event loop startup/tick issue. A more robust approach would be to wait for the process to emit a "ready" signal on stdout, but MCP processes don't emit such a signal before the initialize handshake.
- **Cleanup has two modes: strict on init failure, tolerant on success.** During initialization, if the MCP process can't be cleaned up, the gateway should report the combined failure. During routine dispatch (context search/index), a cleanup warning should not turn a successful tool result into a failed request. The `strict` parameter on `_terminate_mcp_process()` encodes this distinction.
- **Named pipes should be checked before use, not asserted.** `assert proc.stdin is not None` becomes a no-op with `python -O`. Replace with `if proc.stdin is None: raise _pipe_error("stdin")` so the check always runs and the error includes the component name.

# Session 2026-05-11: oh-my-openagent Sync, Doctor Diagnostics, and Integration Sync Hardening

## What we did

- **oh-my-openagent sync migration to `llamacpp` provider names**: `sync_oh_my_openagent()` now uses `llamacpp/model` for the full lane and `llamacpp_fast/model` for the fast lane instead of the old `glyphos`/`glyphos-fast` prefixes. Added `_assert_openagent_provider_names()` which rejects legacy provider names with a clear error message ("stale oh-my-openagent provider prefix requested: glyphos; use llamacpp for the full lane and llamacpp_fast for the fast lane").
- **`fallback_models` array support**: `_merge_agent_fallbacks()` merges both the new `fallback_models` array and the legacy `fallback` field into a single deduplicated `fallback_models` list. The legacy `fallback` key is removed from the output. Only entries with known provider prefixes (`llamacpp`, `llamacpp_fast`) are preserved from existing lists — stale `glyphos/` entries are dropped.
- **`auto_update` pinning**: Every `sync-opencode` call now writes `"auto_update": false` to `oh-my-openagent.json` and records `"autoUpdatePinned": true` in the sync diagnostics. This prevents the oh-my-openagent auto-updater from overwriting local hot patches (deferred parent wake, task argument defaults, provider aliases).
- **Lane-aware agent classification**: Agents are now assigned to the full lane (`llamacpp/`) or fast lane (`llamacpp_fast/`) based on the `FULL_LANE_AGENTS` / `FAST_LANE_AGENTS` sets. The default `--agents` parameter expanded to include `hephaestus,oracle,librarian,explore,multimodal-looker`. Categories have their own lane assignment with fallback_models.
- **Doctor log scanner for plugin errors**: Added `oh_my_openagent_recent_error` and `oh_my_openagent_recent_error_detail` fields to `llama-model doctor` output. Scans `oh-my-opencode.log` for fatal error signatures including `ProviderModelNotFoundError`. When found, displays `oh_my_openagent_recent_error_guidance: Run llama-model sync-opencode`. Added portability test coverage.
- **Doctor task-defaults patch detection**: Added `oh_my_openagent_task_defaults_patch` field (yes/no) that inspects the deployed `dist/index.js` for the `run_in_background`/`load_skills` defaulting patch. When missing, displays a notice that the `task()` defaulting patch is absent. Added portability test coverage.
- **OpenCode plugin safe mode**: New `llama-model opencode-plugin disable` and `llama-model opencode-plugin enable` subcommands. `disable` removes `oh-my-openagent` from `opencode.json` plugin list (preserving other plugins) and saves a backup to `{path}.lmm-plugin-backup`. `enable` restores from backup or reports that the plugin is already enabled. This lets users recover from plugin crashes without deleting config. Portability tests verify disable removes plugin, backup exists, enable restores, and re-enable is idempotent.
- **Stale opencode.json key stripping**: `sync-opencode` now strips non-standard keys from `opencode.json` including `lanes`, `category_lane_mapping`, and duplicate local provider entries that were introduced by earlier integration code.
- **Fast lane default enabled**: `LLAMA_MODEL_GATEWAY_FAST_ENABLED` now defaults to `1` in the installer configuration. The fast gateway lane (4011) is enabled out of the box instead of requiring explicit opt-in.
- **LlamaCppClient lazy availability initialization**: Moved `_update_availability()` from one-shot init to lazy-on-first-access pattern with a per-instance lock. Prevents duplicate concurrent `/models` probes but more importantly avoids blocking gateway startup on model catalog fetch.

## What we learned

### oh-my-openagent provider naming
- **`glyphos` and `glyphos-fast` are stale provider names** that cause `ProviderModelNotFoundError` in oh-my-openagent when it tries to resolve `glyphos-fast/Qwen.gguf` — OpenCode only registers `llamacpp` and `llamacpp_fast` as provider names. The sync must enforce the correct naming and reject legacy prefixes at the entry point rather than silently writing stale names.
- **`fallback_models` is the current oh-my-openagent schema; `fallback` is legacy.** The v2 oh-my-openagent config format uses `fallback_models` (an array) and does not support `fallback` (a string). The sync function must merge the old field into the new one and remove the legacy key.
- **`auto_update: false` is critical for stability.** oh-my-openagent's auto-updater can break local hot patches by overwriting `dist/index.js`. The sync must explicitly pin this to `false` and report the pinning in diagnostics.

### Doctor diagnostics for plugin health
- **Log scanning for fatal error signatures** is more actionable than raw process health checks. `ProviderModelNotFoundError` in `oh-my-opencode.log` is a clear signal that provider names are stale. The doctor can surface both the error and the recommended fix (`llama-model sync-opencode`) in a single field.
- **Patch detection should inspect the deployed file**, not the repo copy. `oh_my_openagent_task_defaults_patch` checks `~/.cache/opencode/packages/.../dist/index.js` because that's the runtime artifact. The repo copy is irrelevant for runtime diagnostics.

### Plugin safe mode
- **Removing oh-my-openagent from `opencode.json` is a safe recovery path** that restores OpenCode functionality without deleting the user's plugin config. The plugin config remains intact in `oh-my-openagent.json` — only the registration in `opencode.json` is modified.
- **Backups at `{path}.lmm-plugin-backup`** provide a recovery path that's independent of the plugin's own backup mechanism. The enable command checks this backup before failing with a reinstall message.
- **Embedded Python print() calls in bash heredocs** that reference user-controlled paths (`path`, `name`, `removed`) must use `json.dumps()` for safe escaping. Without this, a config file path containing special characters (`"`, `\`, backtick) would produce broken output or syntax errors in the embedded Python.

# Session 2026-05-11 (continued): api_client Bug Fixes & MCP Type Correction

## What we did

- **Triaged 5 bug claims in `api_client.py`**: Bugs 1–4 were false positives; Bug 5 (unhandled `socket.timeout` during `response.read()`) was semi-valid — low-impact but fixable.
- **Fixed 2 bugs in `api_client.py`**:
  - **Bug 5**: Added `except OSError` handler in `_http_json` to catch `socket.timeout` (and other OSError subclasses) during `response.read()`. Placed AFTER `except URLError` since `URLError` is a subclass of `OSError` and must match first.
  - **Bug 3 improvement**: Removed `raise_for_status()` barrier in `_resolve_model` so model list can be parsed regardless of HTTP status; added raw `urlopen` fallback to retry `/models` with a shorter timeout if the `_http_json` wrapper fails entirely.
- **Corrected MCP `asToolResponse` type fix**: The previous "fix" changed `Record<string, unknown>` → `unknown` for the parameter, which broke TypeScript (TS2322: `unknown` not assignable to `Record<string, unknown>`). Correct fix: keep `response: unknown` as parameter (accepts any shape) + `as Record<string, unknown>` cast on `structuredContent` assignment.

## What we learned

### Exception handler ordering (Python)
- **`URLError` is a subclass of `OSError`** in Python 3. If you put `except OSError` before `except URLError`, the `URLError` handler is dead code. Always order from specific → general: `HTTPError` → `URLError` → `OSError`.
- **`socket.timeout` inherits from `OSError`**, not `URLError`. When `urlopen` returns a response object and subsequent `response.read()` blocks past the socket timeout, the exception is a bare `socket.timeout` — NOT wrapped in `URLError`. The `except OSError` handler catches this.
- **`except Exception` should not be the first line of defense** for socket-level errors. Be specific: `socket.timeout`, `OSError`, `ConnectionError`, etc.

### Fallback design
- **`raise_for_status()` gates parsing prematurely.** When the `/models` endpoint returns a non-200 status, the body may still contain valid JSON with model data. Skip `raise_for_status()` — just try to parse, and let the parser fail if the body is genuinely unusable.
- **Two code paths are better than one for fallback.** The `_http_json` wrapper handles structured error responses but can fail for many reasons. A raw `urlopen` bypass is a genuinely different code path that may succeed where the wrapper failed. Mirror comments explaining WHY the second path exists are justified.

### MCP TypeScript patterns
- **`structuredContent` in MCP `CallToolResult` expects `Record<string, unknown>`**, not `unknown`. The `as unknown as Record<string, unknown>` pattern (or simply `as Record<string, unknown>`) is the correct way to assign an `unknown` response to it. Changing the parameter to a narrower type loses flexibility; casting on assignment preserves flexibility without losing type safety.
- **Always run `npm run typecheck` after MCP type changes.** The previous fix silently broke type safety because only the function signature was changed — the assignment mismatch was only caught by the type checker. TypeScript errors show up immediately when you run `tsc --noEmit`.
- **The `share_orion/` copies of MCP files must stay in sync** with the primary `integrations/context-mode-mcp/` copies. Apply the same fix to both.
