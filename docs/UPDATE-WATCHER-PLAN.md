# Update Watcher Plan

Date: 2026-04-23
Status: planned
Scope: llama-model-manager update awareness for LMM itself and upstream llama.cpp runtimes

## Purpose

Users see frequent upstream llama.cpp changes and need a clean way to know when either:

- Llama Model Manager has a newer release or commit available
- the configured llama.cpp runtime source has advanced beyond the built/ref-pinned runtime they are using

The first version should be a local, privacy-preserving notification layer. It must not silently update code, rebuild runtimes, interrupt active servers, or make network calls when the operator has disabled update checks.

## Requirements Summary

Build an optional Update Watcher that can:

- check `soulhash-labs/llama-model-manager` for newer LMM versions or commits
- check `ggml-org/llama.cpp` for newer upstream runtime refs
- persist update-check results under the existing LMM state directory
- expose status through CLI and dashboard
- optionally install a 12-hour `systemd --user` timer for automatic checks
- stay disabled by default for air-gapped and privacy-sensitive environments
- remain notify-only in the first implementation slice

## Non-Goals For First Pass

- no silent `git pull`
- no silent installer re-run
- no silent `llama.cpp` rebuild
- no auto-stop or auto-restart of `llama-server`
- no telemetry or hosted reporting
- no sending local model paths, machine info, config contents, or registry contents to any service

## Policy Defaults

Recommended defaults:

```env
LLAMA_MODEL_UPDATE_CHECKS=0
LLAMA_MODEL_UPDATE_INTERVAL_HOURS=12
LLAMA_MODEL_UPDATE_NOTIFY_ONLY=1
LLAMA_MODEL_UPDATE_LMM_REPO=soulhash-labs/llama-model-manager
LLAMA_MODEL_UPDATE_LLAMA_CPP_REPO=ggml-org/llama.cpp
```

Default behavior:

- fresh installs do not enable background checks automatically
- installer may ask whether to enable 12-hour update checks when interactive
- explicit `llama-model updates check` works unless `LLAMA_MODEL_UPDATE_CHECKS=0` is treated as a hard network-disable policy
- background timer performs checks only when explicitly installed/enabled
- checks cache results locally and tolerate offline/network errors

Air-gapped behavior:

- `LLAMA_MODEL_UPDATE_CHECKS=0` disables network update checks
- CLI status should report `disabled`, not `failed`
- dashboard should show update checks disabled with no error styling

## Data Model

Persist update state at:

```text
~/.local/state/llama-server/update-check.json
```

Suggested schema:

```json
{
  "schema_version": 1,
  "checked_at": "2026-04-23T00:00:00+00:00",
  "status": "ok",
  "network_enabled": true,
  "sources": {
    "lmm": {
      "repo": "soulhash-labs/llama-model-manager",
      "installed_ref": "7e6f84a",
      "installed_version": "",
      "latest_ref": "abcdef1",
      "latest_version": "",
      "update_available": true,
      "compare_url": "https://github.com/soulhash-labs/llama-model-manager/compare/7e6f84a...abcdef1",
      "recommended_action": "Review release notes and rerun the installer when ready."
    },
    "llama_cpp": {
      "repo": "ggml-org/llama.cpp",
      "configured_ref": "b8851",
      "built_ref": "b8851",
      "latest_ref": "b9000",
      "update_available": true,
      "recommended_action": "Run llama-model build-runtime --backend auto after reviewing upstream changes."
    }
  },
  "error": "",
  "next_check_hint": "2026-04-23T12:00:00+00:00"
}
```

Status values:

- `ok`
- `disabled`
- `offline`
- `partial`
- `error`

Per-source status values:

- `current`
- `update-available`
- `unknown`
- `disabled`
- `error`

## CLI UX

Add top-level command group:

```bash
llama-model updates check
llama-model updates status
llama-model updates service install|enable|disable|status|logs|uninstall
```

First-pass behavior:

- `updates check` performs a foreground check and writes `update-check.json`
- `updates status` prints the persisted state without network access
- `updates service install` writes user service/timer units
- `updates service enable` enables the timer, not the check service directly
- `updates service disable` disables the timer

Example `updates status` output:

```text
update_checks: enabled
last_checked: 2026-04-23T00:00:00+00:00
lmm_status: update-available
lmm_installed_ref: 7e6f84a
lmm_latest_ref: abcdef1
llama_cpp_status: current
llama_cpp_configured_ref: b8851
llama_cpp_latest_ref: b8851
mode: notify-only
```

Later explicit actions, not first pass:

```bash
llama-model updates install-lmm
llama-model updates build-runtime
```

These should remain explicit and operator-triggered.

## Background Timer

Install optional units under:

```text
~/.config/systemd/user/llama-model-updates.service
~/.config/systemd/user/llama-model-updates.timer
```

Suggested service:

```ini
[Unit]
Description=Llama Model Manager update check

[Service]
Type=oneshot
ExecStart=%h/.local/bin/llama-model updates check --background
```

Suggested timer:

```ini
[Unit]
Description=Run Llama Model Manager update checks every 12 hours

[Timer]
OnBootSec=10min
OnUnitActiveSec=12h
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

The interval should be configurable from `LLAMA_MODEL_UPDATE_INTERVAL_HOURS`, but the unit can be generated with the currently saved value.

## Dashboard UX

Add an `Updates` card near the dashboard service/runtime posture cards.

Fields:

- LMM app: `current`, `update available`, `disabled`, `unknown`
- llama.cpp runtime: `current`, `newer upstream available`, `disabled`, `unknown`
- last checked
- check mode: `manual`, `12h timer`, `disabled`
- notify-only badge

Buttons:

- `Check Now`
- `Install Update Timer`
- `Enable Timer`
- `Disable Timer`
- `View Logs`

First pass should not include a one-click update button. If an update is available, display the recommended command instead.

Example copy:

```text
LMM update available. Review changes, then rerun the installer when ready.
llama.cpp has newer upstream commits. Build a new runtime only when you are ready to test it.
```

## Backend/API UX

Add web API routes:

```text
GET  /api/updates/status
POST /api/updates/check
POST /api/updates/service
GET  /api/updates/logs
```

`/api/state` should also include a compact update summary so the dashboard can render without extra calls.

Suggested state keys:

```json
{
  "updates": {
    "enabled": false,
    "notify_only": true,
    "last_checked": "",
    "lmm_status": "disabled",
    "llama_cpp_status": "disabled",
    "timer_status": {},
    "summary": "Update checks disabled."
  }
}
```

## Source Detection

LMM installed ref:

- if checkout install: use `git -C "$APP_ROOT" rev-parse --short HEAD`
- if installed from archive: write install metadata during install, then read it later
- if unavailable: report `installed_ref: unknown`

Recommended install metadata file:

```text
~/.local/share/llama-model-manager/install-metadata.json
```

Suggested contents:

```json
{
  "schema_version": 1,
  "installed_at": "2026-04-23T00:00:00+00:00",
  "source": "github-archive",
  "repo": "soulhash-labs/llama-model-manager",
  "ref": "main",
  "commit": "7e6f84a"
}
```

llama.cpp installed/built ref:

- read `LLAMA_CPP_REF` from defaults/current env
- read runtime manifest fields under `runtime/llama-server/*/llama-server.compat.env`
- prefer manifest source ref when available

Relevant existing files/functions:

- `bin/llama-model`: `LLAMA_CPP_REPO_URL`, `LLAMA_CPP_REF`, `build-runtime`, `dashboard-service`
- `web/app.py`: dashboard service status and `/api/state` shape
- `web/index.html`: service/status card structure
- `web/app.js`: card rendering, button busy states, toast handling
- `config/defaults.env.example`: defaults surface
- `config/HELP.txt`: user-facing command list
- `install.sh`: optional installer prompt and metadata write

## Network Implementation

Use GitHub public APIs or low-cost refs endpoint.

Preferred low-complexity checks:

```text
https://api.github.com/repos/soulhash-labs/llama-model-manager/commits/main
https://api.github.com/repos/ggml-org/llama.cpp/commits/master
```

Considerations:

- use short timeout, around 10-15 seconds
- set `User-Agent: llama-model-manager/<version>`
- tolerate rate limits with clear `offline` or `error` state
- optionally store ETag headers later to avoid unnecessary payloads
- do not send local state to GitHub beyond normal HTTP request metadata

## Acceptance Criteria

CLI:

- `llama-model updates status` works before any check and reports `unknown` or `disabled` cleanly
- `llama-model updates check` writes `update-check.json` when enabled and network succeeds
- `LLAMA_MODEL_UPDATE_CHECKS=0 llama-model updates check` does not perform a network call and reports disabled
- `llama-model updates service install` writes service and timer unit files
- `llama-model updates service enable` enables the timer without starting any update/install job
- `llama-model updates service status` shows installed/enabled/active state

Dashboard:

- `/api/state` includes compact update status
- update card renders disabled/current/update-available/offline states
- `Check Now` triggers a foreground check and refreshes state
- timer controls match existing dashboard service UX patterns

Safety:

- no active `llama-server` process is stopped or restarted by update checks
- no files outside LMM state/config/service paths are modified by `updates check`
- no update or rebuild occurs without a future explicit operator command

Air-gap:

- checks can be fully disabled from defaults/env
- disabled mode is not shown as an error
- timer install is opt-in

## Implementation Steps

1. Add update defaults.

Files:

- `config/defaults.env.example`
- `web/app.py`
- `web/index.html`
- `web/app.js`
- `config/HELP.txt`
- `README.md`

Add `LLAMA_MODEL_UPDATE_CHECKS`, `LLAMA_MODEL_UPDATE_INTERVAL_HOURS`, and notify-only defaults to the same defaults flow used by client sync and Claude gateway settings.

2. Add CLI update state helpers.

File:

- `bin/llama-model`

Implement helpers for:

- update state path
- JSON write/read
- installed LMM ref detection
- llama.cpp built/configured ref detection
- GitHub latest ref lookup
- disabled/offline/error classification

3. Add CLI update commands.

File:

- `bin/llama-model`

Add command parser entries for:

- `updates check`
- `updates status`
- `updates service install|enable|disable|status|logs|uninstall`

Reuse existing dashboard-service patterns where practical.

4. Add optional systemd timer generation.

File:

- `bin/llama-model`

Generate `llama-model-updates.service` and `llama-model-updates.timer` in the user's systemd unit directory.

5. Add installer nicety.

File:

- `install.sh`

Interactive install should ask whether to install/enable the 12-hour update watcher. Non-interactive install should not enable it.

Also write install metadata when possible.

6. Add web manager status/API.

File:

- `web/app.py`

Add update status parsing from the CLI/state file and API routes for check/service actions. Keep failures non-fatal to `/api/state`.

7. Add dashboard card.

Files:

- `web/index.html`
- `web/app.js`
- `web/styles.css`

Follow existing dashboard service card patterns: status, lifecycle, support, controls, logs.

8. Add tests.

Files:

- `tests/test_portability.sh`
- optional Python test module if route behavior is added

Cover:

- disabled update checks do not network
- status works with missing state file
- check writes valid JSON with mocked/latest ref input
- timer unit text contains `OnUnitActiveSec=12h` or configured interval equivalent
- dashboard HTML includes the update card and controls
- help text includes update commands

## Risks And Mitigations

Risk: Users interpret update availability as safe-to-upgrade.

Mitigation: Use copy like `review available`, not `install now`; keep update actions separate from notification.

Risk: Air-gapped users see noisy errors.

Mitigation: disabled state is first-class; network errors become `offline` or `unknown`, not fatal dashboard failures.

Risk: GitHub API rate limiting.

Mitigation: cache locally, use 12-hour timer, add randomized delay, optionally add ETag later.

Risk: llama.cpp latest commit may be unstable for a user's hardware.

Mitigation: report availability only; runtime rebuild remains explicit and already goes through compatibility checks.

Risk: installed archive has no Git metadata.

Mitigation: write install metadata during install and fall back to `unknown` when not available.

## Verification Plan

Minimum verification:

```bash
bash -n bin/llama-model install.sh
python3 -m py_compile web/app.py
node --check web/app.js
tests/test_portability.sh
```

Manual smoke:

```bash
llama-model updates status
LLAMA_MODEL_UPDATE_CHECKS=0 llama-model updates check
llama-model updates service install
llama-model updates service status
llama-model-web
curl -fsS http://127.0.0.1:8765/api/state
```

Network smoke, when allowed:

```bash
LLAMA_MODEL_UPDATE_CHECKS=1 llama-model updates check
llama-model updates status
```

## ADR

Decision: Implement an opt-in, notify-only Update Watcher that tracks both LMM and llama.cpp updates.

Drivers:

- llama.cpp moves frequently enough that users benefit from update awareness
- LMM itself now ships fast, so users also need first-party update awareness
- local AI operators may be privacy-sensitive or air-gapped
- runtime rebuilds can be disruptive and hardware-specific

Alternatives considered:

- Silent auto-update: rejected because it can break active local runtimes and violates operator control.
- LMM-only update check: rejected because the most frequent upstream churn is llama.cpp.
- llama.cpp-only update check: rejected because users install LMM from GitHub and need app update awareness too.
- Always-on timer by default: rejected because air-gapped/private installs should not make surprise network calls.

Why chosen:

A notify-only watcher gives users useful awareness while preserving the local-first, operator-controlled product posture.

Consequences:

- first pass adds status and service plumbing without risky update execution
- future update/install actions can build on trusted state once the watcher proves stable
- docs must explain the difference between LMM app updates and llama.cpp runtime rebuilds

Follow-ups:

- add release-note links when LMM tagged releases are available
- add ETag support if GitHub rate limits become visible
- add explicit `install-lmm` and `build-runtime` actions only after notify-only behavior is validated
