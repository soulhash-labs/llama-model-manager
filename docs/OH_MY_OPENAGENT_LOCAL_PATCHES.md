# oh-my-openagent Local Patches and Findings

Date: 2026-05-09

## Context

This machine runs LMM plus OpenCode with `oh-my-openagent` installed from the OpenCode package cache:

```text
/home/angelo/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent
```

The installed package inspected during this pass was `oh-my-openagent` `3.17.13`.

Two separate oh-my-openagent issues were investigated:

- background sub-agent completion does not wake the parent session
- GitHub issue #3883: `task()` throws when `run_in_background` or `load_skills` is omitted

These are related in the broader delegation flow, but they are different bugs.

## Patch 1: Deferred Busy Parent Wake (Upstream Commit 5a4127c)

### Problem

When a background sub-agent completed and `notifyParentSession` called `session.promptAsync(...)`, the MCP SDK would throw a "busy parent" error if the parent session was still generating a response. This caused the background completion notification to be silently lost, leaving the parent session idle.

### Initial Local Fix (Replaced)

The first attempt patched `notifyParentSession` to use `session.prompt({...})` instead of `session.promptAsync({...})`. This bypassed the busy-parent check but used the wrong API — `prompt` does not follow the same lifecycle as `promptAsync`.

### Upstream Fix Applied

Upstream commit `5a4127c` (found in oh-my-openagent `dev` branch) implements a proper **deferred busy parent wake** mechanism. Applied to the installed dist at:

```text
~/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent/dist/index.js
```

Five insertion points in `BackgroundManager`:

1. **`pendingParentWakes` class field** (line ~105032) — `Map` keyed by `parentSessionId`
2. **`notifyParentSession` deferral logic** (line ~106505) — checks `this.client.session.status()` before calling `promptAsync`. If parent session status is `busy`/`retry`/`running`, stores the prompt body in `pendingParentWakes` and returns early instead of calling `promptAsync`. On successful `promptAsync`, cascades to `flushPendingParentWake`.
3. **`flushPendingParentWake()` method** — retrieves stored wake for a parent session, calls `promptAsync`, recursively flushes additional deferred wakes on success.
4. **`handleEvent` `session.idle` handler** — calls `this.flushPendingParentWake(idleSessionID)` after existing idle handling, so deferred wakes flush when the parent goes idle.
5. **`shutdown()` cleanup** — clears `pendingParentWakes`.

Key design:
- Only defers completions when `allComplete && !isTaskFailure` (errors sent immediately)
- Uses `isActiveSessionStatus()` (checks `["busy", "retry", "running"]`) to detect busy parent
- On `session.idle`, flushes deferred wakes automatically
- After a successful wake notification, checks for more pending wakes (cascade)

### Patch File

A patch file for reapplication is at:
```text
docs/patches/oh-my-openagent-5a4127c-deferred-wake.patch
```

Apply with:
```bash
cd ~/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent
patch -p0 < /path/to/repo/docs/patches/oh-my-openagent-5a4127c-deferred-wake.patch
```

### Verification

```bash
bun -e "import('...oh-my-openagent/dist/index.js').then(() => console.log('OK'))"
grep -c 'flushPendingParentWake' dist/index.js    # → 5
grep -c 'shouldDeferReply' dist/index.js          # → 2
grep -c 'pendingParentWakes' dist/index.js        # → 5
```

Backup saved as `dist/index.js.bak-upstream-5a4127c-20260510`.

### LMM Crash Containment

Added in the same pass:

- `llama-model doctor` now reports:
  - `oh_my_openagent_recent_error` — detected error signature from plugin logs
  - `oh_my_openagent_recent_error_detail` — matching log line excerpt
  - `oh_my_openagent_recent_error_log` — which log file was scanned
  - `oh_my_openagent_recent_error_guidance` — actionable fix
  - `oh_my_openagent_plugin_enabled` — whether the plugin is active in `opencode.json`
- `llama-model opencode-plugin status|disable|enable` — safe mode to disable oh-my-openagent without deleting config
- `probe_server_binary` no longer calls `die()` on priority-1 failures, so `llama-model doctor` always reaches integration diagnostics even when the runtime binary is broken.

## Patch 2: GitHub Issue #3883 `task()` Defaults

Issue:

```text
https://github.com/code-yeongyu/oh-my-openagent/issues/3883
```

### Problem

`task()` throws when callers omit:

- `run_in_background`
- `load_skills`

This can cause repeated model retries and blocks callers whose schema cannot provide `load_skills`.

### Local Fix

The deployed bundle's `prepareDelegateTaskArgs` was patched so omitted fields default safely:

```js
const runInBackground = args.run_in_background === undefined ? false : args.run_in_background;
```

and:

```js
if (loadSkills === undefined) {
  loadSkills = [];
}
```

Explicit invalid values are still rejected. In particular, `load_skills=null` still throws.

### Proposed Upstream Shape

The upstream fix should default only omitted fields:

- missing `run_in_background` -> `false`
- missing `load_skills` -> `[]`

It should preserve explicit invalid-value validation such as `load_skills: null`.

## LMM Guards Added

LMM now includes doctor checks for both local oh-my-openagent patches:

```text
oh_my_openagent_wake_patch
oh_my_openagent_task_defaults_patch
```

When checked after deployment, the installed LMM CLI reported:

```text
oh_my_openagent_version: 3.17.13
oh_my_openagent_wake_patch: yes
oh_my_openagent_task_defaults_patch: yes
```

These guards are important because reinstalling or updating the plugin can replace the generated `dist/index.js` bundle and silently drop local hot patches.

## Deployment State

Patched:

- repo `bin/llama-model`
- deployed `/home/angelo/.local/bin/llama-model`
- deployed oh-my-openagent bundle under the OpenCode package cache

Backups were made before modifying deployed oh-my-openagent bundles:

```text
index.js.bak-issue3883-*
```

Earlier wake-up patch backup naming may differ depending on the session that applied it.

## Verification Done

Local verification included:

- shell syntax checks for `bin/llama-model`
- shell syntax checks for `tests/test_portability.sh`
- focused portability tests for the new doctor guards
- `llama-model doctor` with neutral runtime overrides to avoid an unrelated CUDA validation failure
- static inspection of the deployed oh-my-openagent bundle

The relevant doctor output after both patches:

```text
oh_my_openagent_wake_patch: yes
oh_my_openagent_task_defaults_patch: yes
```

## Known Remaining Gaps

OpenCode must be restarted before it loads the patched oh-my-openagent bundle.

The end-to-end runtime test still needs to be performed after restart:

1. start/restart OpenCode
2. launch a background sub-agent
3. let it complete
4. confirm the parent session wakes without manual input
5. confirm omitted `task()` fields no longer cause the #3883 retry loop

There is also a separate LMM bug: normal `llama-model doctor` can fail before diagnostics if CUDA runtime validation cannot detect host compute capability. That is documented in:

```text
tasks/doctor-cuda-validation-bug.md
```

## Lessons

- Do not assume a repo-side guard is deployed; verify both the repo copy and `/home/angelo/.local/bin/llama-model`.
- Treat local patches to generated dependency bundles as fragile. Add a diagnostic guard so reinstall drift is visible.
- Separate delegation startup failures from completion wake-up failures. #3883 prevents tasks from launching cleanly; the wake-up patch only matters after a background task completes.
- `doctor` should be resilient enough to report unrelated diagnostics even when one runtime validation path fails.

## Patch 3: Parent Session Binding Fix (getMainSessionID)

### Problem

`resolveParentContext` used `ctx.sessionID` to identify the parent session for background task context. However, `ctx.sessionID` from opencode's tool context always returns the FIRST session ID (`ses_1f5e70bbeffezDa9yoK0ctLKBe`) regardless of which session called the tool. Background tasks were associated with this stale first session ID, so `notifyParentSession` sent wake notifications to the wrong session.

### Fix

Replaced `ctx.sessionID` with `getMainSessionID() ?? ctx.sessionID` in `resolveParentContext` (line 98478 of `dist/index.js`). `getMainSessionID()` tracks the latest root session, ensuring background task wake notifications go to the correct parent.

### Impact

- Background tasks now use the CORRECT parent session for context resolution
- Parent wake notifications target the right session

## Patch 4: Stale Model Provider Alias (glyphos-fast → llamacpp_fast)

### Problem

The `oh-my-openagent.json` config was updated to rename `glyphos-fast` → `llamacpp_fast` as the provider for sub-agents (`explore`, `librarian`, etc.). However, opencode PID 5751 started at `May 9 10:10 AM` — BEFORE the config was updated at `6:28 PM`. The in-memory `pluginConfig.agents` retained the stale `glyphos-fast` references. When background tasks resolved their model through `resolveSubagentExecution`/`resolveCategoryExecution`, they produced `glyphos-fast/Qwen3.5-4B-...` which opencode's runtime couldn't match to any known provider, causing "Model not found" errors.

### Root Cause

`loadPluginConfig` (line 134129 of `dist/index.js`) reads `oh-my-openagent.json` ONCE at process startup via `readFileSync`. File updates after process start have NO effect on the running process. Combined with the stale session ID bug (Patch 3), background tasks both failed to launch AND sent wake notifications to the wrong session.

### Fixes Applied

1. **Runtime provider alias** (line 100000 of `dist/index.js`): Added `PROVIDER_ALIASES` map in `resolveModelForDelegateTask` that remaps `glyphos-fast/` → `llamacpp_fast/` and `glyphos/` → `llamacpp/` before model resolution. This provides resilience against future provider renames even with stale in-memory config.

2. **Backward-compatible provider entry** in `opencode.json`: Added `glyphos-fast` as a provider pointing to the same port 4011/v1 endpoint as `llamacpp_fast`. This provides defense-in-depth if the code alias doesn't apply.

### Combined Patch File

All four patches (5a4127c deferred wake, #3883 task defaults, getMainSessionID, provider alias) are consolidated in a single unified diff:

```text
docs/patches/oh-my-openagent-local.patch
```

Apply with:
```bash
cd ~/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent
patch -p0 < /path/to/repo/docs/patches/oh-my-openagent-local.patch
```

### Verification (Requires Restart)

```bash
grep -c 'getMainSessionID' dist/index.js   # → 16
grep -c 'PROVIDER_ALIASES' dist/index.js   # → 2
grep -c 'flushPendingParentWake' dist/index.js    # → 5
grep -c 'pendingParentWakes' dist/index.js        # → 5
```

OpenCode PID 5751 must be restarted for the new in-memory config to take effect. After restart:
1. Launch a background sub-agent (`task(subagent_type="explore", ...)`)
2. Verify child session created with correct `llamacpp_fast` provider
3. Let child complete
4. Verify parent session receives wake notification
