# Phase 07: Update Watcher - Research

**Researched:** 2026-04-30
**Domain:** GitHub API polling, background scheduling, notify-only update checking
**Confidence:** HIGH

## Summary

Phase 07 introduces an optional, opt-in update watcher for llama-model-manager (LMM). The system will periodically check GitHub releases for both `soulhash-labs/llama-model-manager` (LMM itself) and `ggml-org/llama.cpp` (upstream dependency) using only stdlib Python (`urllib.request`). The design is strictly notify-only: no automatic installations or rebuilds. Background checks run every 12 hours (configurable) via a `Threading.Timer` loop in the gateway server. Update state is persisted using the existing `_FileLockedJsonStore` pattern. The dashboard will show update status via a new `/v1/updates` endpoint. A new CLI command `llama-model update-check` will allow manual checks.

**Primary recommendation:** Implement `lmm_updates.py` as a self-contained stdlib-only module using `urllib.request` for GitHub API access, with graceful offline handling (3-5 second timeouts). Store update state in a new JSON file using the existing `_FileLockedJsonStore` pattern. Integrate background scheduling into the gateway startup via `Threading.Timer` recursive loop.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|----------------|
| Python stdlib (`urllib.request`) | 3.x | GitHub API HTTP requests | Project constraint: no external deps |
| Python stdlib (`json`) | 3.x | Parse GitHub API responses | Project constraint: no external deps |
| Python stdlib (`threading`) | 3.x | Background timer loop | Project already uses ThreadingHTTPServer |
| Python stdlib (`fcntl`) | 3.x | File locking for update state | Already used in lmm_storage.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|----------------|
| `ThreadingHTTPServer` | Python stdlib | Gateway server base | Already in use (glyphos_openai_gateway.py) |
| `_FileLockedJsonStore` | Custom | Update state persistence | Reuse pattern from lmm_storage.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `urllib.request` | `requests` library | Better API but violates stdlib-only constraint |
| `Threading.Timer` | `asyncio` | Async is cleaner but gateway uses sync ThreadingHTTPServer |
| Polling | Webhooks | Webhooks require public endpoint, not air-gap friendly |

**Installation:**
```bash
# No additional packages required - stdlib only
```

## Architecture Patterns

### Recommended Project Structure
```
scripts/
├── lmm_config.py          # ADD: UpdateWatcherConfig dataclass
├── lmm_updates.py         # NEW: UpdateChecker class
├── lmm_notifications.py   # EXTEND: Add UPDATE_AVAILABLE notification type
├── glyphos_openai_gateway.py  # MODIFY: Add /v1/updates endpoint, start background timer
└── lmm_storage.py         # REUSE: _FileLockedJsonStore for update state

bin/
└── llama-model              # MODIFY: Add update-check command

web/
├── app.py                  # MODIFY: Add update status to state, API endpoint
└── templates/             # MODIFY: Add update banner/status indicator
```

### Pattern 1: GitHub API Release Checking
**What:** Use `urllib.request` to call GitHub REST API for latest release
**When to use:** Periodic background checks, manual CLI checks
**Example:**
```python
# Source: GitHub API Docs (docs.github.com/en/rest/releases/releases)
# Verified: 2026-04-30
import json
import urllib.request
from urllib.error import HTTPError, URLError

def get_latest_release(owner: str, repo: str, timeout: int = 5) -> dict[str, Any] | None:
    """Fetch latest release info from GitHub API. Returns None on any failure."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {"User-Agent": "llama-model-manager/2.1", "Accept": "application/vnd.github+json"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError):
        return None
```

### Pattern 2: Background Timer Loop
**What:** Recursive `Threading.Timer` for periodic checks
**When to use:** Gateway server startup, long-running background tasks
**Example:**
```python
# Source: Python stdlib threading documentation
# Verified: 2026-04-30
import threading

def start_periodic_check(interval_hours: float, check_func: Callable[[], None]) -> threading.Timer:
    def wrapper():
        try:
            check_func()
        except Exception:
            pass  # Air-gap friendly: swallow errors
        finally:
            # Reschedule recursively
            timer = start_periodic_check(interval_hours, check_func)
            timer.daemon = True
            timer.start()

    timer = threading.Timer(interval_hours * 3600, wrapper)
    timer.daemon = True
    return timer
```

### Pattern 3: Update State Persistence
**What:** Store last check results using `_FileLockedJsonStore`
**When to use:** Persisting update check results across gateway restarts
**Example:**
```python
# Source: lmm_storage.py pattern (lines 17-48)
# Verified: 2026-04-30 (existing codebase)
class UpdateStateStore(_FileLockedJsonStore):
    def read_state(self) -> dict[str, Any]:
        return self._read_state({
            "schema_version": 1,
            "last_checked_at": "",
            "lmm": {"current_version": "", "latest_version": "", "update_available": False, "release_url": "", "checked_at": ""},
            "llamacpp": {"current_version": "", "latest_version": "", "update_available": False, "release_url": "", "checked_at": ""},
        })
```

### Anti-Patterns to Avoid
- **Auto-update:** Never auto-install or auto-rebuild. Notify-only per requirements.
- **Blocking on network:** Gateway startup must not block waiting for GitHub API.
- **Ignoring rate limits:** GitHub API has 60 req/hour unauthenticated. Cache results.
- **No graceful degradation:** Must work offline/air-gapped without errors.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|---------------|-----|
| GitHub API client | Custom REST client with auth handling | `urllib.request` with proper headers | GitHub API is simple REST; stdlib suffices for GET requests |
| JSON file locking | Custom lock files, race condition-prone writes | `_FileLockedJsonStore` from lmm_storage.py | Already tested, uses fcntl locks + atomic writes |
| Version comparison | String comparison, regex parsing | `packaging.version.Version` or simple tuple parse | Version parsing has edge cases (semver, prefixes like "v") |
| Notification dispatch | Direct desktop/log calls | Reuse `NotificationManager` from lmm_notifications.py | Consistent with existing notification patterns |

**Key insight:** The existing `_FileLockedJsonStore` pattern handles all file persistence needs. The `NotificationManager` handles all notification routing. Don't duplicate these capabilities.

## Common Pitfalls

### Pitfall 1: GitHub API Rate Limiting
**What goes wrong:** After 60 unauthenticated requests/hour, GitHub returns 403/429
**Why it happens:** Multiple gateway restarts, frequent manual checks, or shared IP
**How to avoid:**
- Cache successful responses with timestamps
- Respect `x-ratelimit-remaining` and `x-ratelimit-reset` headers
- Only check when `last_checked_at` is older than `check_interval_hours`
**Warning signs:** HTTP 403 responses, log messages about rate limiting

### Pitfall 2: Blocking Gateway Startup
**What goes wrong:** Gateway waits for GitHub API check before serving requests
**Why it happens:** Synchronous HTTP request in startup path
**How to avoid:** Start background timer AFTER gateway is serving (in a separate thread). First check should run after `check_interval_hours`, not immediately.
**Warning signs:** Slow gateway startup when offline

### Pitfall 3: Version String Comparison
**What goes wrong:** `"v2.1.0" > "v2.10.0"` evaluates incorrectly as True with string comparison
**Why it happens:** Version strings with different digit counts
**How to avoid:** Parse versions into tuples: `tuple(int(x) for x in version.lstrip('v').split('.'))`
**Warning signs:** False positives/negatives on update detection

### Pitfall 4: Air-Gap False Positives
**What goes wrong:** Offline system shows "update failed" errors
**Why it happens:** Not handling `URLError` gracefully
**How to avoid:** Catch `URLError`, `HTTPError`, `TimeoutError` and return `None`. Log at debug level only.
**Warning signs:** Error messages in logs when offline

## Code Examples

Verified patterns from official sources:

### GitHub API: Get Latest Release
```python
# Source: GitHub REST API Docs (docs.github.com/en/rest/releases/releases)
# Verified: 2026-04-30 via websearch
import json
import urllib.request
from urllib.error import HTTPError, URLError

def fetch_latest_release(owner: str, repo: str, timeout: int = 5) -> dict[str, Any] | None:
    """Fetch latest release from GitHub API. Returns parsed JSON or None."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "User-Agent": "llama-model-manager/2.1",
        "Accept": "application/vnd.github+json",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "tag_name": data.get("tag_name", ""),
                "name": data.get("name", ""),
                "html_url": data.get("html_url", ""),
                "body": data.get("body", "")[:500],  # Preview only
                "published_at": data.get("published_at", ""),
            }
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
```

### Version Comparison
```python
# Source: Python stdlib pattern
# Verified: 2026-04-30 (existing codebase convention)
def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse version string like 'v2.1.0' into comparable tuple."""
    cleaned = version_str.lstrip("v").strip()
    parts = []
    for part in cleaned.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)

def is_newer_version(current: str, latest: str) -> bool:
    """Return True if latest > current."""
    return parse_version(latest) > parse_version(current)
```

### Update State Store
```python
# Source: lmm_storage.py pattern (reuse _FileLockedJsonStore)
# Verified: 2026-04-30 (existing codebase)
from pathlib import Path
from lmm_storage import _FileLockedJsonStore

class UpdateStateStore(_FileLockedJsonStore):
    """Store update check results with file locking."""

    def read_state(self) -> dict[str, Any]:
        return self._read_state({
            "schema_version": 1,
            "last_checked_at": "",
            "lmm": {
                "current_version": "v2.1.0",
                "latest_version": "",
                "update_available": False,
                "release_url": "",
                "release_notes_preview": "",
                "checked_at": "",
            },
            "llamacpp": {
                "current_version": "",  # Detected at runtime or from config
                "latest_version": "",
                "update_available": False,
                "release_url": "",
                "release_notes_preview": "",
                "checked_at": "",
            },
        })

    def update_result(self, component: str, result: dict[str, Any]) -> None:
        """Persist a check result for lmm or llamacpp."""
        with self._lock():
            state = self.read_state()
            if component in ("lmm", "llamacpp"):
                state[component].update(result)
                state["last_checked_at"] = result.get("checked_at", "")
                self._write_state(state)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Polling with `requests` library | `urllib.request` (stdlib) | 2026-04-30 | Project constraint: no external deps |
| No version checking | GitHub API releases/latest | Phase 07 | New feature |
| No background tasks | `Threading.Timer` loop | Phase 07 | Gateway already uses threading |

**Deprecated/outdated:**
- `urllib2` (Python 2) — Use `urllib.request` (Python 3)
- Polling in CLI only — Background gateway timer is more user-friendly

## Open Questions

1. **How to detect current llama.cpp version?**
   - What we know: llama.cpp is fetched/built from `LLAMA_CPP_REPO_URL` and `LLAMA_CPP_REF` (see `bin/llama-model` lines 22-23)
   - What's unclear: Runtime detection of actual compiled llama.cpp version
   - Recommendation: Parse version from binary output (`llama-server --version`) or store ref in state file during build-runtime

2. **Should update notifications use existing NotificationType enum?**
   - What we know: `NotificationType` has `RUN_COMPLETED`, `RUN_FAILED`, `CLIENT_DISCONNECTED`
   - What's unclear: Add `UPDATE_AVAILABLE` to enum or create separate update notification path?
   - Recommendation: Add `UPDATE_AVAILABLE` to `NotificationType` enum in `lmm_notifications.py`

3. **Dashboard integration approach?**
   - What we know: `web/app.py` Manager class handles state, `API_POST_PAYLOAD_SCHEMAS` defines endpoints
   - What's unclear: New `/api/updates` endpoint or extend existing `/api/state`?
   - Recommendation: New `/v1/updates` in gateway, proxy via web API

## Validation Architecture

> workflow.nyquist_validation is not set in config.json (treated as enabled)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (inferred from test_phase0_contracts.py) |
| Config file | None — see Wave 0 |
| Quick run command | `python -m pytest tests/test_update_checker.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UPDATE-01 | Background check runs every 12 hours | integration | `pytest tests/test_update_watcher.py::test_background_timer -x` | ❌ Wave 0 |
| UPDATE-02 | GitHub API returns latest release info | unit | `pytest tests/test_update_checker.py::test_fetch_release -x` | ❌ Wave 0 |
| UPDATE-03 | Notification sent when update available | unit | `pytest tests/test_update_checker.py::test_notification_sent -x` | ❌ Wave 0 |
| UPDATE-04 | CLI `update-check` returns version info | unit | `pytest tests/test_update_checker.py::test_cli_check -x` | ❌ Wave 0 |
| UPDATE-05 | Dashboard shows update status | integration | `pytest tests/test_update_watcher.py::test_dashboard_status -x` | ❌ Wave 0 |
| UPDATE-06 | Air-gap graceful degradation | unit | `pytest tests/test_update_checker.py::test_offline_handling -x` | ❌ Wave 0 |
| UPDATE-07 | Config controls check interval | unit | `pytest tests/test_update_checker.py::test_config_interval -x` | ❌ Wave 0 |

### Wave 0 Gaps
- [ ] `tests/test_update_checker.py` — covers UPDATE-01 through UPDATE-07
- [ ] `tests/test_update_watcher.py` — integration tests for background timer
- [ ] `scripts/lmm_updates.py` — main module to test
- [ ] Framework install: `python -m pip install pytest` if not present

## Module Design: lmm_updates.py

### Class: UpdateChecker
```python
# Location: scripts/lmm_updates.py
# Confidence: HIGH (based on GitHub API docs + existing patterns)

from __future__ import annotations
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lmm_storage import _FileLockedJsonStore

@dataclass
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    release_notes_preview: str
    checked_at: str = ""

class UpdateChecker:
    """Check GitHub releases for updates (notify-only, no auto-install)."""

    def __init__(
        self,
        current_lmm_version: str = "v2.1.0",
        lmm_repo: str = "soulhash-labs/llama-model-manager",
        llamacpp_repo: str = "ggml-org/llama.cpp",
        timeout: int = 5,
        state_file: Path | None = None,
    ):
        self.current_lmm_version = current_lmm_version
        self.lmm_repo = lmm_repo
        self.llamacpp_repo = llamacpp_repo
        self.timeout = timeout
        self.state_store = UpdateStateStore(state_file or Path.home() / ".local" / "state" / "llama-server" / "lmm-update-state.json")

    def check_lmm_update(self) -> UpdateCheckResult:
        """Check for LMM updates. Returns result even on failure."""
        return self._check_repo("lmm", self.lmm_repo, self.current_lmm_version)

    def check_llamacpp_update(self, current_version: str = "") -> UpdateCheckResult:
        """Check for llama.cpp updates."""
        return self._check_repo("llamacpp", self.llamacpp_repo, current_version)

    def _check_repo(self, component: str, repo_full_name: str, current: str) -> UpdateCheckResult:
        """Check a single repo's latest release."""
        owner, repo = repo_full_name.split("/")
        data = self._fetch_latest_release(owner, repo)
        if data is None:
            # Return cached or empty result
            return self._cached_result(component)

        latest = data.get("tag_name", "")
        url = data.get("html_url", "")
        notes = (data.get("body") or "")[:300]

        result = UpdateCheckResult(
            current_version=current,
            latest_version=latest,
            update_available=bool(latest) and self._is_newer(current, latest),
            release_url=url,
            release_notes_preview=notes,
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        # Persist result
        self.state_store.update_result(component, result.__dict__)
        return result

    def _fetch_latest_release(self, owner: str, repo: str) -> dict | None:
        """Call GitHub API. Returns None on any failure (air-gap friendly)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        headers = {
            "User-Agent": "llama-model-manager/2.1",
            "Accept": "application/vnd.github+json",
        }
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

    def _is_newer(self, current: str, latest: str) -> bool:
        """Compare version strings. Handle 'v' prefix."""
        def parse(v: str) -> tuple:
            try:
                return tuple(int(x) for x in v.lstrip("v").split("."))
            except ValueError:
                return (0,)
        return parse(latest) > parse(current)

    def _cached_result(self, component: str) -> UpdateCheckResult:
        """Return last cached result from state store."""
        state = self.state_store.read_state()
        cached = state.get(component, {})
        return UpdateCheckResult(**cached)
```

## Config Additions

### UpdateWatcherConfig dataclass (add to lmm_config.py)
```python
# Location: scripts/lmm_config.py
# Add to existing dataclases

@dataclass(frozen=True)
class UpdateWatcherConfig:
    enabled: bool = False  # Opt-in: disabled by default
    check_interval_hours: int = 12
    lmm_repo: str = "soulhash-labs/llama-model-manager"
    llamacpp_repo: str = "ggml-org/llama.cpp"
    timeout_seconds: int = 5

    def __post_init__(self) -> None:
        if self.check_interval_hours < 1:
            raise ConfigurationError("check_interval_hours must be >= 1", field="check_interval_hours")
        if self.timeout_seconds < 1 or self.timeout_seconds > 30:
            raise ConfigurationError("timeout_seconds must be 1-30", field="timeout_seconds")

# Extend LMMConfig:
@dataclass(frozen=True)
class LMMConfig:
    gateway: GatewayConfig
    context: ContextConfig
    glyph_encoding: GlyphEncodingConfig
    update_watcher: UpdateWatcherConfig  # NEW

# Extend load_lmm_config_from_env():
def load_lmm_config_from_env() -> LMMConfig:
    # ... existing code ...
    update_watcher = UpdateWatcherConfig(
        enabled=_bool_env("LMM_UPDATE_WATCHER_ENABLED", False),
        check_interval_hours=_int_env("LMM_UPDATE_CHECK_INTERVAL_HOURS", 12, minimum=1, maximum=168),
        lmm_repo=_env("LMM_UPDATE_LMM_REPO", "soulhash-labs/llama-model-manager"),
        llamacpp_repo=_env("LMM_UPDATE_LLAMACPP_REPO", "ggml-org/llama.cpp"),
        timeout_seconds=_int_env("LMM_UPDATE_TIMEOUT_SECONDS", 5, minimum=1, maximum=30),
    )
    return LMMConfig(gateway=gateway, context=context, glyph_encoding=glyph_encoding, update_watcher=update_watcher)
```

### Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `LMM_UPDATE_WATCHER_ENABLED` | `false` | Enable/disable update watcher |
| `LMM_UPDATE_CHECK_INTERVAL_HOURS` | `12` | Hours between checks (1-168) |
| `LMM_UPDATE_LMM_REPO` | `soulhash-labs/llama-model-manager` | LMM repo to watch |
| `LMM_UPDATE_LLAMACPP_REPO` | `ggml-org/llama.cpp` | llama.cpp repo to watch |
| `LMM_UPDATE_TIMEOUT_SECONDS` | `5` | HTTP timeout for GitHub API |

## Background Scheduler Design

### Integration with Gateway Server
```python
# Location: scripts/glyphos_openai_gateway.py
# Modify create_gateway_server() and add background timer

def create_gateway_server(...) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    server.backend_base_url = backend_base_url
    server.model_id = model_id
    server.gateway = LMMOpenAIGateway(backend_base_url=backend_base_url, model_id=model_id)
    server.health_checker = server.gateway.health_checker

    # NEW: Start update watcher if enabled
    config = load_lmm_config_from_env()
    if config.update_watcher.enabled:
        start_update_watcher(server, config.update_watcher)

    return server

def start_update_watcher(server, watcher_config: UpdateWatcherConfig) -> None:
    """Start background update checker (non-blocking)."""
    from lmm_updates import UpdateChecker

    checker = UpdateChecker(
        current_lmm_version="v2.1.0",  # TODO: detect from package
        lmm_repo=watcher_config.lmm_repo,
        llamacpp_repo=watcher_config.llamacpp_repo,
        timeout=watcher_config.timeout_seconds,
    )
    server.update_checker = checker  # Attach to server for /v1/updates endpoint

    def periodic_check():
        try:
            lmm_result = checker.check_lmm_update()
            cpp_result = checker.check_llamacpp_update()

            # Notify if updates available
            if lmm_result.update_available:
                mgr = notification_manager()
                if mgr:
                    mgr.notify(
                        "LMM Update Available",
                        f"Version {lmm_result.latest_version} is available (current: {lmm_result.current_version})",
                        NotificationType.UPDATE_AVAILABLE,  # NEW enum value
                    )
            # TODO: similar for llama.cpp
        except Exception:
            pass  # Air-gap friendly
        finally:
            # Reschedule
            timer = threading.Timer(watcher_config.check_interval_hours * 3600, periodic_check)
            timer.daemon = True
            timer.start()

    # Start timer (first check after interval, not immediately)
    timer = threading.Timer(watcher_config.check_interval_hours * 3600, periodic_check)
    timer.daemon = True
    timer.start()
    server.update_timer = timer  # Keep reference to prevent GC
```

## Gateway Endpoint: /v1/updates

### Add to GatewayHandler in glyphos_openai_gateway.py
```python
# Add to do_GET method:
def do_GET(self) -> None:
    path = self.path.split("?", 1)[0]
    # ... existing routes ...
    if path == "/v1/updates":
        self._handle_updates()
        return

def _handle_updates(self):
    """Return update check status."""
    checker = getattr(self.server, 'update_checker', None)
    if checker is None:
        json_response(self, 200, {
            "enabled": False,
            "message": "Update watcher is disabled",
        })
        return

    lmm_result = checker._cached_result("lmm")
    cpp_result = checker._cached_result("llamacpp")

    json_response(self, 200, {
        "enabled": True,
        "last_checked": lmm_result.checked_at or cpp_result.checked_at,
        "lmm": {
            "current_version": lmm_result.current_version,
            "latest_version": lmm_result.latest_version,
            "update_available": lmm_result.update_available,
            "release_url": lmm_result.release_url,
        },
        "llamacpp": {
            "current_version": cpp_result.current_version,
            "latest_version": cpp_result.latest_version,
            "update_available": cpp_result.update_available,
            "release_url": cpp_result.release_url,
        },
    })
```

## CLI Integration: `llama-model update-check`

### Add to bin/llama-model
```bash
# Add to usage() output:
#   llama-model update-check [--component lmm|llamacpp|all]

# Add handler function:
update_check() {
    local component="${1:-all}"
    command_available python3 || die "python3 is required for update-check"

    python3 - "$component" <<'PY'
import json
import sys
from lmm_updates import UpdateChecker

component = sys.argv[1]
checker = UpdateChecker()

def print_result(name, result):
    print(f"{name}:")
    print(f"  Current:  {result.current_version}")
    print(f"  Latest:   {result.latest_version}")
    print(f"  Update:   {'Available' if result.update_available else 'Up to date'}")
    if result.release_url:
        print(f"  URL:      {result.release_url}")
    if result.checked_at:
        print(f"  Checked:  {result.checked_at}")

if component in ("lmm", "all"):
    result = checker.check_lmm_update()
    print_result("LMM", result)
if component in ("llamacpp", "all"):
    result = checker.check_llamacpp_update()
    if component == "all":
        print()
    print_result("llama.cpp", result)
PY
}

# Add to main case statement:
# update-check) shift; update_check "$@" ;;
```

## Dashboard Integration

### Add to web/app.py Manager class
```python
# Add method to Manager class:
def get_update_status(self) -> dict[str, Any]:
    """Fetch update status from gateway API."""
    if self.demo:
        return {"enabled": False, "lmm": {}, "llamacpp": {}}

    try:
        url = f"http://{self.llama_model_web_host}:{self.llama_model_web_port}/v1/updates"
        request = urllib.request.Request(url, headers={"User-Agent": "llama-model-manager/2.1"})
        with urllib.request.urlopen(request, timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"enabled": False, "error": "Unable to reach gateway"}
```

### Add to dashboard state endpoint
```python
# In the /api/state handler or phase0_contracts():
update_status = self.get_update_status()
# Merge into state response
```

## Success Criteria

Observable, testable outcomes:

1. **UPDATE-01:** Background timer starts when `LMM_UPDATE_WATCHER_ENABLED=true`, fires every `check_interval_hours`
2. **UPDATE-02:** `GET /v1/updates` returns JSON with lmm and llamacpp status
3. **UPDATE-03:** `llama-model update-check` prints current/latest versions
4. **UPDATE-04:** Notification sent (desktop/log) when update available
5. **UPDATE-05:** Offline/air-gap: no errors, graceful degradation
6. **UPDATE-06:** GitHub API rate limit respected (60 req/hour unauthenticated)
7. **UPDATE-07:** Config values loaded from environment variables
8. **UPDATE-08:** Update state persisted across gateway restarts

## Dependencies & Ordering

### Prerequisites
- Phase 02 (run-records): ✅ Shipped — provides `_FileLockedJsonStore` pattern
- `lmm_config.py`: Exists — will add `UpdateWatcherConfig`
- `lmm_notifications.py`: Exists — will add `UPDATE_AVAILABLE` to enum
- `glyphos_openai_gateway.py`: Exists — will add `/v1/updates` endpoint

### Phase Dependencies
- None — Phase 07 can run independently
- Optimal after Phase 02 (storage patterns established)

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| GitHub API rate limit (60/hour) | Medium | Low | Cache results, only check after interval elapsed |
| Network timeout blocking gateway | Low | High | Run timer in daemon thread, catch all exceptions |
| Version parsing errors | Low | Medium | Use tuple parsing, handle edge cases |
| Incorrect llama.cpp version detection | Medium | Low | Store version during build-runtime, or parse binary output |
| Notification spam | Low | Medium | Reuse existing cooldown mechanism from NotificationManager |

## Sources

### Primary (HIGH confidence)
- GitHub REST API Docs: https://docs.github.com/en/rest/releases/releases (verified 2026-04-30)
- GitHub Rate Limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api (verified 2026-04-30)
- Existing codebase: `lmm_storage.py` (fcntl locking pattern), `lmm_config.py` (dataclass config), `lmm_notifications.py` (NotificationManager)
- Python stdlib `urllib.request` documentation (built-in)

### Secondary (MEDIUM confidence)
- Stack Overflow: "How to get latest release version in Github only use python-requests" (https://stackoverflow.com/questions/60716016) — confirms API endpoint pattern
- GitHub Changelog: "Updated rate limits for unauthenticated requests" (2025-05-08) — confirms 60 req/hour

### Tertiary (LOW confidence)
- Community examples of `Threading.Timer` for periodic tasks — pattern is common but not authoritative

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib-only confirmed as project constraint
- Architecture: HIGH - Based on existing patterns (dataclasses, _FileLockedJsonStore, ThreadingHTTPServer)
- Pitfalls: HIGH - GitHub API docs verified, rate limits confirmed

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (30 days for stable APIs, GitHub rate limits change infrequently)
