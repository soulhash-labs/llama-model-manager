# Phase 07: Update Watcher — Plan

**Phase:** 07-update-watcher
**Plan:** 01
**Goal:** Optional, opt-in update checker for LMM and llama.cpp GitHub releases — notify-only, no auto-install, air-gap friendly.
**Created:** 2026-04-30

## Must-Haves

```yaml
must_haves:
  truths:
    - "UpdateChecker queries GitHub API for latest releases and compares versions"
    - "Update watcher is disabled by default, enabled via config/env var"
    - "Background timer runs periodic checks every 12 hours (configurable)"
    - "Gateway exposes /v1/updates endpoint returning cached check results"
    - "CLI command llama-model update-check prints current/latest versions"
    - "Air-gap/offline: no errors, graceful degradation with cached results"
  artifacts:
    - path: "scripts/lmm_config.py"
      provides: "UpdateWatcherConfig dataclass with enabled, interval, repo, timeout fields"
    - path: "scripts/lmm_updates.py"
      provides: "UpdateChecker class, version comparison, GitHub API client, UpdateStateStore"
    - path: "scripts/lmm_notifications.py"
      provides: "UPDATE_AVAILABLE notification type in NotificationType enum"
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "/v1/updates endpoint, background timer startup, notification on update found"
    - path: "web/app.py"
      provides: "Update status in dashboard state response"
    - path: "web/app.js"
      provides: "Update status banner/indicator in dashboard UI"
    - path: "bin/llama-model"
      provides: "update-check subcommand for manual version check"
  key_links:
    - from: "glyphos_openai_gateway.py"
      to: "lmm_updates.py"
      via: "UpdateChecker instance created at server startup, attached to server object"
    - from: "lmm_updates.py"
      to: "lmm_storage.py"
      via: "UpdateStateStore inherits from _FileLockedJsonStore"
    - from: "lmm_updates.py"
      to: "lmm_notifications.py"
      via: "NotificationManager.notify() called when update_available is True"
    - from: "web/app.py"
      to: "gateway /v1/updates"
      via: "urllib.request GET to gateway URL for update status"
    - from: "bin/llama-model update-check"
      to: "lmm_updates.py"
      via: "UpdateChecker().check_lmm_update() / check_llamacpp_update()"

requirements:
  - UPDATE-01
  - UPDATE-02
  - UPDATE-03
  - UPDATE-04
  - UPDATE-05
  - UPDATE-06
```

## Requirements

- **UPDATE-01**: UpdateChecker queries GitHub API (`/repos/{owner}/{repo}/releases/latest`) for both LMM and llama.cpp
- **UPDATE-02**: Version comparison correctly identifies newer releases (handles `v` prefix, semantic versioning)
- **UPDATE-03**: Background timer starts when `LMM_UPDATE_WATCHER_ENABLED=true`, fires every `check_interval_hours` (default 12)
- **UPDATE-04**: `GET /v1/updates` returns JSON with current/latest versions and update_available flags
- **UPDATE-05**: CLI `llama-model update-check [--component lmm|llamacpp|all]` prints version info
- **UPDATE-06**: Air-gap/offline: no errors, cached results returned, network failures silently handled

## Tasks

### Task 1: Add UpdateWatcherConfig to lmm_config.py

**File:** `scripts/lmm_config.py`
**Action:** Add UpdateWatcherConfig dataclass and integrate into LMMConfig.
**Details:**
- `UpdateWatcherConfig` dataclass (frozen):
  - `enabled: bool = False` — opt-in, disabled by default
  - `check_interval_hours: int = 12` — range 1-168 (1 week max)
  - `lmm_repo: str = "soulhash-labs/llama-model-manager"`
  - `llamacpp_repo: str = "ggml-org/llama.cpp"`
  - `timeout_seconds: int = 5` — range 1-30
- `__post_init__` validation: interval >= 1, timeout 1-30
- Add `update_watcher: UpdateWatcherConfig` field to `LMMConfig`
- Extend `load_lmm_config_from_env()`:
  - `LMM_UPDATE_WATCHER_ENABLED` (bool, default False)
  - `LMM_UPDATE_CHECK_INTERVAL_HOURS` (int, default 12)
  - `LMM_UPDATE_LMM_REPO` (str, default as above)
  - `LMM_UPDATE_LLAMACPP_REPO` (str, default as above)
  - `LMM_UPDATE_TIMEOUT_SECONDS` (int, default 5)
- Backward compatible: LMMConfig constructor adds new field with default

### Task 2: Create lmm_updates.py module

**File:** `scripts/lmm_updates.py` (new)
**Action:** Create UpdateChecker class with GitHub API client and state persistence.
**Details:**
- `UpdateCheckResult` dataclass: current_version, latest_version, update_available, release_url, release_notes_preview, checked_at
- `UpdateStateStore(_FileLockedJsonStore)`: stores last check results for lmm and llamacpp
  - `read_state() -> dict` — returns schema with lmm/llamacpp sections
  - `update_result(component, result) -> None` — persists check result
- `UpdateChecker` class:
  - `__init__`: current_lmm_version, lmm_repo, llamacpp_repo, timeout, state_file
  - `check_lmm_update() -> UpdateCheckResult` — checks LMM repo
  - `check_llamacpp_update(current_version="") -> UpdateCheckResult` — checks llama.cpp repo
  - `_check_repo(component, repo_full_name, current) -> UpdateCheckResult` — internal
  - `_fetch_latest_release(owner, repo) -> dict | None` — GitHub API call via urllib.request
  - `_is_newer(current, latest) -> bool` — version tuple comparison
  - `_cached_result(component) -> UpdateCheckResult` — returns last cached result
- Air-gap friendly: `_fetch_latest_release` returns None on any exception (HTTPError, URLError, TimeoutError, JSONDecodeError)
- Version parsing: `tuple(int(x) for x in v.lstrip("v").split("."))` with ValueError fallback to (0,)
- Stdlib only: urllib.request, urllib.error, json, dataclasses, time, pathlib

### Task 3: Add UPDATE_AVAILABLE to NotificationType

**File:** `scripts/lmm_notifications.py`
**Action:** Add new enum value to NotificationType.
**Details:**
- Add `UPDATE_AVAILABLE = "update_available"` to NotificationType enum
- No other changes needed — existing NotificationManager handles new types

### Task 4: Gateway integration — endpoint + background timer

**File:** `scripts/glyphos_openai_gateway.py`
**Action:** Add `/v1/updates` GET endpoint and start background update timer on server creation.
**Details:**
- In `create_gateway_server()`:
  - After server creation, check `config.update_watcher.enabled`
  - If enabled, call `start_update_watcher(server, config.update_watcher)`
- `start_update_watcher(server, watcher_config) -> None`:
  - Create `UpdateChecker` with current LMM version (read from LMM_VERSION env var or "v2.1.0")
  - Attach to `server.update_checker`
  - Define `periodic_check()` inner function:
    - Run `checker.check_lmm_update()` and `checker.check_llamacpp_update()`
    - If `lmm_result.update_available`, call `notification_manager().notify(...)` with NotificationType.UPDATE_AVAILABLE
    - Similar notification for llama.cpp if update available
    - Reschedule with `threading.Timer(watcher_config.check_interval_hours * 3600, periodic_check)`
  - Start timer as daemon thread
  - Store timer reference as `server.update_timer`
- In `GatewayHandler.do_GET()`:
  - Add route for `/v1/updates`:
    - If `server.update_checker` exists, return cached results from state store
    - If not enabled, return `{"enabled": false, "message": "Update watcher is disabled"}`
- LMM version detection: `os.environ.get("LMM_VERSION", "v2.1.0")`

### Task 5: Dashboard update status

**File:** `web/app.py`
**Action:** Add update status to dashboard state response.
**Details:**
- Add `_get_update_status()` method to Manager class:
  - If demo mode, return `{"enabled": False}`
  - GET gateway `/v1/updates` via urllib.request (2s timeout)
  - Return parsed JSON or `{"enabled": False, "error": "..."}` on failure
- Include `update_status` in `/api/state` response

### Task 6: Dashboard UI — update banner

**File:** `web/app.js`
**Action:** Add update status indicator to dashboard.
**Details:**
- Add `renderUpdateStatus(updateStatus)` function:
  - If not enabled or no data, show nothing
  - If `lmm.update_available` or `llamacpp.update_available`, show banner:
    - "Update available: LMM v2.2.0 (current: v2.1.0)" with link to release
  - If up to date, show subtle indicator: "✓ Up to date"
- Call from state update handler after `renderStatus()`
- Add CSS for banner (green for up-to-date, orange for available)

### Task 7: CLI update-check command

**File:** `bin/llama-model`
**Action:** Add `update-check` subcommand.
**Details:**
- `llama-model update-check [--component lmm|llamacpp|all]`
- Default: `all`
- Uses embedded Python script to call `UpdateChecker`:
  - `checker.check_lmm_update()` for LMM
  - `checker.check_llamacpp_update(current_version)` for llama.cpp
  - Current llama.cpp version: read from `LLAMA_CPP_REF` env var or "unknown"
- Output format:
  ```
  LMM:
    Current:  v2.1.0
    Latest:   v2.2.0
    Update:   Available
    URL:      https://github.com/soulhash-labs/llama-model-manager/releases/tag/v2.2.0
  ```
- `--json` flag: output as JSON
- Add to usage() output

## Tests

### Unit tests (tests/test_phase0_contracts.py)

- `test_update_watcher_config_defaults` — disabled by default, correct interval/repo values
- `test_update_watcher_config_validation` — rejects interval < 1, timeout out of range
- `test_update_checker_fetch_release_format` — GitHub API response parsed correctly
- `test_update_checker_version_comparison` — "v2.10.0" > "v2.1.0", handles v prefix
- `test_update_checker_offline_handling` — returns cached result on network failure
- `test_update_checker_notification_on_update` — NotificationManager.notify called when update available
- `test_update_state_store_persistence` — results persist across reads
- `test_update_endpoint_disabled` — /v1/updates returns disabled message when not enabled

## Success Criteria

1. `UpdateChecker.check_lmm_update()` returns valid UpdateCheckResult with current/latest/available flag
2. Version comparison correctly handles semantic versioning with `v` prefix
3. Background timer starts when enabled, runs every N hours without blocking gateway
4. `GET /v1/updates` returns JSON with lmm and llamacpp status (or disabled message)
5. `llama-model update-check` prints version info for both components
6. Offline: no errors logged, cached results returned gracefully
7. Zero regressions in existing gateway, notification, or config logic

---

_Verified: 2026-04-30_
_Planner: Claude (gsd-planner)_
