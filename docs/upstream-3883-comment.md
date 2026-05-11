# Upstream #3883 Comment

## Summary

`task()` throws when `run_in_background` or `load_skills` is omitted,
causing repeated model retries and can destabilize the OpenCode client.

## Proposed Fix

Default omitted fields only, preserve explicit-invalid validation:

- Missing `run_in_background` → `false`
- Missing `load_skills` → `[]`
- `load_skills: null` should still throw (explicit invalid value)

## Local Patch (Applied to Deployed Bundle)

```js
// prepareDelegateTaskArgs
const runInBackground = args.run_in_background === undefined ? false : args.run_in_background;
let loadSkills = args.load_skills;
if (loadSkills === undefined) { loadSkills = []; }
args.run_in_background = runInBackground;
args.load_skills = loadSkills;
```

## Additional Finding: Provider/Model Failures Can Crash Host

When `task()` receives an invalid provider model ID (e.g.
`glyphos-fast/ModelName.gguf` when only `llamacpp_fast/ModelName.gguf` is
registered), the plugin raises `ProviderModelNotFoundError`. On Windows this
can crash the whole OpenCode desktop app. On Linux it makes OpenCode unusable
until the plugin is manually removed from `opencode.json`.

**Recommendation**: Provider/model lookup failures from delegated task setup
should fail the individual tool call with a diagnostic message rather than
destabilizing the host application. Background child session errors should
propagate as structured task failure results to the parent session.

## Related: Parent Wake-Up After Background Task

`notifyParentSession` in `src/features/background-agent/manager.ts` uses
`promptAsync(...)` which is fire-and-forget — it injects a message but does
NOT trigger the parent agent loop. The parent session remains idle until
manually nudged.

Switching to `this.client.session.prompt({...})` (which routes through
`POST /session/{id}/message`) wakes the parent. This is a separate issue
but directly affects the usability of background task delegation.
