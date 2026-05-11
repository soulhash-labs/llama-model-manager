# oh-my-openagent #3883: Proposed `task()` defaulting fix

## Problem

Issue #3883 reports that `task()` throws when callers omit `run_in_background` or `load_skills`, causing retry loops and breaking callers whose tool schema cannot provide `load_skills`.

The failing path is `prepareDelegateTaskArgs`:

```ts
const runInBackground = args.run_in_background
if (runInBackground === undefined) {
  throw new Error("Invalid arguments: 'run_in_background' parameter is REQUIRED...")
}

let loadSkills = args.load_skills
if (loadSkills === undefined) {
  throw new Error("Invalid arguments: 'load_skills' parameter is REQUIRED...")
}
```

## Proposed Fix

Default only omitted fields:

```ts
const runInBackground = args.run_in_background === undefined
  ? false
  : args.run_in_background

let loadSkills = args.load_skills
if (typeof loadSkills === "string") {
  try {
    const parsed = JSON.parse(loadSkills)
    loadSkills = Array.isArray(parsed) ? parsed : []
  } catch {
    loadSkills = []
  }
}

if (loadSkills === undefined) {
  loadSkills = []
}

if (loadSkills === null) {
  throw new Error("Invalid arguments: load_skills=null is not allowed. Pass [] if no skills needed.")
}
```

This preserves explicit invalid-value rejection while avoiding hard failures for omitted optional-by-practice fields.

## Local Deployment Patch

Patched `/home/angelo/.cache/opencode/packages/oh-my-openagent@latest/node_modules/oh-my-openagent/dist/index.js`:

- omitted `run_in_background` now defaults to `false`
- omitted `load_skills` now defaults to `[]`
- explicit `load_skills=null` still throws

OpenCode must be restarted before the patched bundle is loaded.

## LMM Guard

`llama-model doctor` now reports `oh_my_openagent_task_defaults_patch` so plugin reinstalls that lose this patch are visible.
