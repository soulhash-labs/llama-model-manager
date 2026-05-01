# Codebase Concerns

**Analysis Date:** 2026-04-30

## Tech Debt

**Single Massive Files:**
- Issue: Core logic concentrated in very large files
- Files: `bin/llama-model` (5099 lines), `web/app.py` (3429 lines), `web/app.js` (2328 lines), `tests/test_phase0_contracts.py` (4304 lines)
- Impact: Hard to navigate, high merge conflict risk, difficult to review changes
- Fix approach: Extract logical modules from `bin/llama-model` (e.g., separate binary selection, auto-fit, sync, gateway management into separate scripts). Split `web/app.py` into `manager.py`, `routes.py`, `downloads.py`.

**No JavaScript Module System:**
- Issue: All frontend code in single `web/app.js` file (2328 lines)
- Files: `web/app.js`
- Impact: No bundling, no tree-shaking, hard to test individual components
- Fix approach: Consider a lightweight module system or bundler (esbuild already used for Context Mode MCP)

**Global State in Bash:**
- Issue: `bin/llama-model` uses global variables extensively (e.g., `SELECTED_LLAMA_SERVER_BIN`, `STARTUP_FAILURE_CATEGORY`)
- Files: `bin/llama-model`
- Impact: Implicit coupling between functions, hard to test in isolation, fragile ordering dependencies
- Fix approach: Use return values and local variables, or migrate to Python for complex logic

**Demo State Hardcoded in Production Code:**
- Issue: `web/app.py` contains 100+ lines of hardcoded demo state (`DEMO_STATE`, `DEMO_DISCOVERY`, `DEMO_LOG`)
- Files: `web/app.py:254-411`
- Impact: Demo data lives alongside production logic, easy to drift from reality
- Fix approach: Move demo state to separate JSON file loaded only in demo mode

## Known Bugs

**None explicitly documented in codebase.** The test suite covers many edge cases, suggesting bugs are caught proactively.

## Security Considerations

**Shell Sourcing of User Config:**
- Risk: `defaults.env` is shell-sourced (`source "$DEFAULTS_FILE"`), allowing arbitrary code execution
- Files: `bin/llama-model:114`
- Current mitigation: File is user-owned; installer validates it
- Recommendations: Parse key=value pairs instead of sourcing, or validate content before sourcing

**State File Execution Risk:**
- Risk: `current.env` contains shell-sourced state (`source "$STATE_FILE"`)
- Files: `bin/llama-model:748`
- Current mitigation: Test explicitly verifies this is safe (`test_install_does_not_execute_saved_state_when_checking_post_install_sync`)
- Recommendations: The test proves the install script doesn't execute it, but the CLI does source it. Consider parsing instead.

**No Input Sanitization on API Paths:**
- Risk: URL path components not sanitized beyond `split("?", 1)[0]`
- Files: `web/app.py` route handlers
- Current mitigation: Localhost-only default, optional token auth
- Recommendations: Add path normalization to prevent traversal

**Subprocess Command Construction:**
- Risk: `subprocess.run(command, ...)` with user-influenced args
- Files: `web/app.py:543`
- Current mitigation: `shlex.quote` used in display, args validated through Manager methods
- Recommendations: Audit all subprocess call sites for injection paths

## Performance Bottlenecks

**Recursive GGUF Discovery:**
- Problem: `discovery_root.rglob("*.gguf")` can be slow on large directory trees
- Files: `web/app.py:841`
- Cause: Unbounded recursive glob
- Improvement path: Add depth limit, cache results, or use filesystem watch

**Large JSON State Files:**
- Problem: Download jobs, operation activity, and gateway state grow unbounded
- Files: `web/app.py` `MAX_ACTIVITY_EVENTS = 100`, gateway `del recent[40:]`
- Cause: Arbitrary caps but no automatic cleanup
- Improvement path: Add TTL-based cleanup, rotate old records

**Download Threading:**
- Problem: Download threads tracked in dict without pool management
- Files: `web/app.py` `self.download_threads: dict[str, threading.Thread]`
- Cause: Custom threading with manual lifecycle management
- Improvement path: Consider `concurrent.futures.ThreadPoolExecutor`

## Fragile Areas

**Binary Compatibility Validation:**
- Files: `bin/llama-model` `validate_bundled_binary`, `validate_cuda_bundle`
- Why fragile: Complex multi-step validation (OS, arch, backend, CC matching, dynamic links)
- Safe modification: Add new validation steps carefully; test with `test_portability.sh`
- Test coverage: Good - multiple tests cover CC matching, fallback selection, rejection

**mmproj Family Matching:**
- Files: `bin/llama-model` `model_family_token`, `mmproj_matches_model_filename`
- Why fragile: Regex-based filename parsing that must evolve with model naming conventions
- Safe modification: Add new regex patterns for new model families; add tests
- Test coverage: Partial - covers qwen3.5, gemma4; missing coverage for new families

**Auto-Fit Logic:**
- Files: `bin/llama-model` `autofit_memory_posture`, `hybrid_ngl_for_system_memory`
- Why fragile: Heuristic-based GPU/RAM calculations that may be wrong for edge cases
- Safe modification: Add new posture types; adjust thresholds conservatively
- Test coverage: Good - covers hybrid-fit, cpu-fit, ram-risk, no-fit scenarios

**Client Config Sync:**
- Files: `scripts/integration_sync.py`
- Why fragile: Writes to external client config files with evolving schemas
- Safe modification: Add defensive type checks for existing config shapes
- Test coverage: Good - covers opencode stale provider cleanup, long-run preset, direct mode

## Scaling Limits

**Single-threaded HTTP Server:**
- Current capacity: `ThreadingHTTPServer` handles concurrent requests
- Limit: One Python process per dashboard instance; no horizontal scaling
- Scaling path: Not applicable - designed for single-user local use

**Download Queue:**
- Current capacity: Configurable `max_active_downloads` (default 2)
- Limit: No resume chunk management, no bandwidth throttling
- Scaling path: Add chunk-based downloads, parallel chunk fetching

## Dependencies at Risk

**llama.cpp Source Dependency:**
- Risk: Upstream repo URL or ref may change; build may break
- Impact: `llama-model build-runtime` fails
- Migration plan: Pin to specific commit hash, add checksum validation

**PyYAML (Optional):**
- Risk: GlyphOS sync requires PyYAML but it's not installed by default
- Impact: `llama-model sync-glyphos` fails if PyYAML missing
- Migration plan: Ship fallback YAML parser or install PyYAML during setup

## Missing Critical Features

**No Health Check Timeout for Server Start:**
- Problem: `LLAMA_SERVER_WAIT_SECONDS=300` is a very long wait
- Files: `bin/llama-model`
- Blocks: Faster feedback for startup failures
- Recommendation: Progressive health checks with early failure on known error patterns

**No Config Validation on Startup:**
- Problem: Invalid values in `defaults.env` silently fall back to defaults
- Files: `bin/llama-model:114`
- Recommendation: Validate config values and warn on invalid entries

**No Rollback for Failed Syncs:**
- Problem: Client config syncs are not atomic; partial failures leave corrupted configs
- Files: `scripts/integration_sync.py` `write_json`
- Recommendation: Already uses temp-file atomic writes, but should validate JSON before replacing

## Test Coverage Gaps

**Gateway Streaming:**
- What's not tested: SSE streaming error paths, client disconnect handling, heartbeat behavior
- Files: `scripts/glyphos_openai_gateway.py` `stream_completion()`
- Risk: Streaming failures not caught in CI
- Priority: Medium

**Claude Gateway Streaming:**
- What's not tested: `_stream_messages` error paths, upstream timeout during SSE
- Files: `scripts/claude_gateway.py` `_stream_messages()`
- Risk: Streaming failures silently drop responses
- Priority: Medium

**Install Script Edge Cases:**
- What's not tested: Non-bash shells, missing coreutils, unusual XDG paths
- Files: `install.sh`
- Risk: Install failures on edge-case systems
- Priority: Low

**Context MCP Bridge:**
- What's not tested: Bridge subprocess lifecycle, MCP protocol errors, timeout handling
- Files: `scripts/context_mcp_bridge.py`
- Risk: Bridge hangs or leaks processes on MCP failure
- Priority: Medium

**Download Resume:**
- What's not tested: Partial file corruption, resume with changed artifact, network interruption mid-resume
- Files: `web/app.py` download methods
- Risk: Corrupted model files from failed resume
- Priority: High

---

*Concerns audit: 2026-04-30*
