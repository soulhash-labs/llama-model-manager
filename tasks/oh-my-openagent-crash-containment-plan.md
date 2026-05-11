# oh-my-openagent Crash Containment Plan

## Context

Windows feedback on upstream issue #3883 says the local server crashes and the
desktop app stops working until the oh-my-openagent plugin is removed. That
matches the risk pattern we saw locally: a plugin-layer failure can make OpenCode
unusable even though LMM, llama-server, the LMM gateways, and the dashboard are
separate processes.

Local evidence so far:

- `/tmp/oh-my-opencode.log` showed `ProviderModelNotFoundError` after a child
  task tried `glyphos-fast/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf`.
- OpenCode was configured with `llamacpp_fast/...`, not `glyphos-fast/...`.
- Deployed oh-my-openagent now has the wake-up hot patch and #3883 task-default
  hot patch.
- Deployed `oh-my-openagent.json` is now pinned with `auto_update: false`.
- Deployed oh-my-openagent model IDs now use the canonical OpenCode-registered
  providers: `llamacpp/...` for the GlyphOS full lane on `4010`, and
  `llamacpp_fast/...` for the GlyphOS fast lane on `4011`.
- Deployed `opencode.json` also contains a temporary backward-compatible
  `glyphos-fast` provider alias pointing at `4011`. This is a stabilization
  bridge for stale in-memory plugin config, not the canonical naming target.

Important distinction:

- `glyphos` is still core to LMM as the full/fast lane runtime behavior.
- `llamacpp` / `llamacpp_fast` are the canonical provider IDs in the LMM sync
  path.
- `glyphos-fast` may exist in `opencode.json` as a temporary compatibility
  provider alias while local oh-my-openagent patches are required.
- `glyphos/...` and `glyphos-fast/...` should not be written as canonical
  oh-my-openagent agent model IDs.
- Docs, diagnostics, and tests must preserve the GlyphOS lane concept while
  preventing stale provider ID strings from re-entering OpenCode config.

## Goals

1. Make plugin failure visible in `llama-model doctor` without requiring users
   to inspect `/tmp/oh-my-opencode.log`.
2. Provide a safe local recovery path that disables oh-my-openagent from
   OpenCode without deleting the user's oh-my-openagent configuration.
3. Keep LMM runtime services recoverable even when the OpenCode plugin layer is
   broken.
4. Prevent config drift back to `glyphos/...` or `glyphos-fast/...` as canonical
   oh-my-openagent agent model IDs while still documenting those endpoints as
   GlyphOS lanes and allowing the temporary `glyphos-fast` provider alias.
5. Produce a precise upstream #3883 recommendation: invalid `task(...)`
   arguments and provider/model failures should fail the tool call gracefully,
   not destabilize the host app.

## Non-Goals

- Do not remove GlyphOS concepts from LMM docs or UI.
- Do not delete `~/.config/opencode/oh-my-openagent.json` as a recovery step.
- Do not auto-disable the plugin without an explicit command or clear operator
  confirmation path.
- Do not depend on upstream oh-my-openagent releases for the local recovery
  path; local doctor and safe mode should work with the currently deployed
  plugin.

## Current Gaps Found During Double-Check

- Normal `llama-model doctor` can still exit early on the existing CUDA runtime
  validation failure before it reaches OpenCode/plugin diagnostics. The
  crash-containment work must either fix that first or move non-runtime
  diagnostics before fatal runtime validation.
- Gateway `start` from this automation shell can pass health briefly and then
  show stale PIDs afterward. This may be a tool-session descendant cleanup issue,
  but the plan should verify gateway persistence from a normal user shell before
  treating gateway lifecycle as solved.
- `tasks/todo.md` had an older completed note saying oh-my-openagent sync should
  prefer `glyphos-fast/<model>` with `glyphos/<model>` fallback. It is now
  annotated as superseded so future readers do not copy it as current canonical
  agent-model guidance.

## Proposed Implementation

### 1. Doctor Must Always Reach Integration Diagnostics

Change `bin/llama-model show_doctor()` so runtime binary validation problems are
reported as fields instead of aborting before unrelated checks run.

Expected output when CUDA validation fails:

```text
runtime_validation_ok: no
runtime_status: invalid
binary_guidance: ...
oh_my_openagent_wake_patch: yes|no|unknown
oh_my_openagent_task_defaults_patch: yes|no|unknown
oh_my_openagent_auto_update: pinned|enabled|default-enabled|unknown
oh_my_openagent_config_stale_models: ...
oh_my_openagent_recent_error: ...
oh_my_openagent_safe_mode_available: yes|no
```

Tests:

- Add/extend portability coverage where CUDA validation fails but doctor still
  prints OpenCode and oh-my-openagent fields.
- Keep the existing neutral-runtime override tests as supplemental coverage, not
  the only proof.

### 2. Add oh-my-openagent Log Scanner

Add a small parser, preferably in a repo script or inline doctor Python block,
that inspects likely plugin logs:

- `/tmp/oh-my-opencode.log`
- `/tmp/oh-my-openagent.log` if present
- any future configurable path through `OH_MY_OPENAGENT_LOG_FILE`

Detect these signatures:

- `ProviderModelNotFoundError`
- `Model not found: ...`
- `Invalid arguments: 'run_in_background' parameter is REQUIRED`
- `Invalid arguments: 'load_skills' parameter is REQUIRED`
- `session.error received`
- uncaught plugin exceptions around background task/session handling
- auto-update lines showing local hot patches may have been overwritten

Doctor fields:

```text
oh_my_openagent_recent_error: ProviderModelNotFoundError
oh_my_openagent_recent_error_detail: Model not found: glyphos-fast/...
oh_my_openagent_recent_error_log: /tmp/oh-my-opencode.log
oh_my_openagent_recent_error_guidance: Run llama-model sync-opencode; if OpenCode still fails, run llama-model opencode-safe-mode enable.
```

Tests:

- Synthetic log with `ProviderModelNotFoundError` yields stale provider guidance.
- Synthetic log with #3883 required-parameter error yields task-default patch
  guidance.
- Synthetic log with auto-update to a new version yields patch drift guidance.

### 3. Add OpenCode Plugin Safe Mode

Add a command group that can disable or restore oh-my-openagent in
`opencode.json` without touching `oh-my-openagent.json`.

Proposed commands:

```bash
llama-model opencode-plugin status
llama-model opencode-plugin disable-oh-my-openagent
llama-model opencode-plugin enable-oh-my-openagent
```

Behavior:

- Read `OPENCODE_CONFIG_FILE`.
- Preserve all non-plugin config.
- Remove only plugin entries equal to `oh-my-openagent@latest` or matching the
  installed oh-my-openagent package name.
- Store a reversible backup under the OpenCode config directory, for example:
  `~/.config/opencode/opencode.json.lmm-plugin-backup`.
- Do not delete `~/.config/opencode/oh-my-openagent.json`.
- Print the exact restart instruction: restart OpenCode after changing plugin
  status.

Doctor fields:

```text
oh_my_openagent_plugin_enabled: yes|no|unknown
oh_my_openagent_safe_mode_available: yes
oh_my_openagent_safe_mode_guidance: llama-model opencode-plugin disable-oh-my-openagent
```

Tests:

- Disable removes only the plugin entry and preserves other plugin entries.
- Enable restores the plugin once and does not duplicate it.
- Missing config returns clear guidance.
- Invalid JSON fails without writing partial output.

### 4. Harden Sync Against Drift

Existing repo changes already:

- `sync_oh_my_openagent()` pins `auto_update: false`.
- rejects `glyphos` / `glyphos-fast` when passed as OpenCode provider names.
- writes `fallback_models` and drops stale singular `fallback`.
- the deployed OpenCode config has a temporary `glyphos-fast` provider alias as
  defense-in-depth for stale in-memory plugin config until OpenCode is restarted.

Remaining hardening:

- Add a doctor field that reports whether `opencode.json` has plugin enabled,
  whether `oh-my-openagent.json` is pinned, and whether the temporary
  `glyphos-fast` compatibility provider alias is present.
- Add a regression where an existing oh-my-openagent config contains
  `glyphos-fast/...`; after sync, agent model IDs must contain only
  `llamacpp/...` and `llamacpp_fast/...`.
- Add or adjust regression coverage so the temporary `glyphos-fast` provider
  alias in `opencode.json` is allowed only as a compatibility bridge, not as the
  canonical `small_model` or oh-my-openagent agent model.
- Keep old `tasks/todo.md` historical notes annotated so they cannot be mistaken
  for current instructions.

### 5. Documentation Updates

Update or add docs covering:

- OpenCode can be recovered by disabling oh-my-openagent while keeping LMM
  running.
- GlyphOS remains the lane/runtime concept:
  - `4010` is GlyphOS full, registered in OpenCode as `llamacpp`.
  - `4011` is GlyphOS fast, registered in OpenCode as `llamacpp_fast`.
- `glyphos/...` and `glyphos-fast/...` are stale canonical agent model IDs for
  this integration and should be replaced by `llama-model sync-opencode`.
- `glyphos-fast` may be present as a temporary OpenCode provider alias for stale
  in-memory plugin config until OpenCode is restarted and the alias is no longer
  needed.
- `auto_update: false` is intentional while local hot patches are required.

Candidate docs:

- `docs/lmm-agent-runbook.md`
- `docs/OH_MY_OPENAGENT_LOCAL_PATCHES.md`
- `docs/OH_MY_OPENAGENT_PROVIDER_NAME_FIX.md`
- a new recovery doc if the runbook becomes too long

### 6. Upstream #3883 Comment

Prepare a concise upstream comment with the Windows feedback and our local
evidence:

- `task()` should default omitted `run_in_background` to `false`.
- `task()` should default omitted `load_skills` to `[]`.
- Explicit invalid values such as `load_skills: null` should still fail with a
  normal tool error.
- Provider/model lookup failures from delegated task setup should fail the tool
  call and surface a diagnostic message, not crash/freeze the OpenCode host app.
- Background child session errors should propagate as structured task failure
  results to the parent session.

## Execution Order

1. Fix doctor early-exit behavior or move integration diagnostics before runtime
   fatal validation.
2. Add doctor plugin config fields and log scanner.
3. Add OpenCode plugin safe-mode command.
4. Add tests for doctor log scanning and safe-mode config edits.
5. Update docs and historical notes.
6. Run focused tests:
   - `bash -n bin/llama-model`
   - `python3 -m py_compile scripts/integration_sync.py`
   - focused `tests.test_phase0_contracts` tests for sync behavior
   - focused portability functions for doctor/plugin recovery
7. Deploy updated `bin/llama-model` and `scripts/integration_sync.py` to the
   installed LMM paths.
8. Verify on the machine:
   - `llama-model doctor` reaches oh-my-openagent fields without overrides.
   - `llama-model opencode-plugin status` reports plugin state.
   - disable/enable safe mode round-trip preserves config.
   - OpenCode starts with plugin disabled if plugin failure recurs.

## Acceptance Criteria

- A broken CUDA runtime profile no longer prevents doctor from showing
  OpenCode/oh-my-openagent diagnostics.
- Doctor reports recent oh-my-openagent fatal errors from logs with actionable
  guidance.
- A user can disable oh-my-openagent from OpenCode through LMM without deleting
  the plugin config.
- `sync-opencode` cannot reintroduce `glyphos/...` or `glyphos-fast/...` as
  canonical oh-my-openagent agent model IDs.
- If `glyphos-fast` is present in `opencode.json`, doctor identifies it as a
  temporary compatibility alias, not the canonical provider.
- Docs clearly distinguish GlyphOS lane semantics from OpenCode provider ID
  strings.
- Upstream #3883 comment is ready to paste and backed by local evidence.
