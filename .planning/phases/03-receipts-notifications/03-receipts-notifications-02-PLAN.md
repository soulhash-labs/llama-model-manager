---
phase: 03-receipts-notifications
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/lmm_notifications.py
  - scripts/glyphos_openai_gateway.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: [NOTIFY-01]
user_setup: []

must_haves:
  truths:
    - "Desktop notifications fire on long run completions (>30s) using notify-send"
    - "Notification fallback chain: desktop → log (no webhook for first pass)"
    - "Notifications are rate-limited: max 1 per 60 seconds"
    - "Notification config is optional and disabled by default"
  artifacts:
    - path: "scripts/lmm_notifications.py"
      provides: "NotificationType enum, NotificationBackend protocol, DesktopBackend, LogBackend, NotificationManager"
      exports: ["NotificationType", "NotificationBackend", "DesktopBackend", "LogBackend", "NotificationManager"]
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "NotificationManager integration in stream_completion and do_POST"
      contains: "NotificationManager|notify"
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "scripts/lmm_notifications.py:NotificationManager"
      via: "fires notification on completion/failure with duration check"
      pattern: "notification_manager|NotificationManager"
---

<objective>
Add a pluggable notification system for gateway events (run completions, failures, client disconnects).

Purpose: Alert users when long local runs complete or fail, using desktop notifications on Linux/macOS with a log fallback.
Output: lmm_notifications.py + gateway integration
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@scripts/lmm_config.py
@scripts/lmm_errors.py
@docs/ACE-PATTERN-TRANSFER-ANALYSIS.md (Pattern 9: Notification System)
</context>

<interfaces>
<!-- Key contracts from existing code. -->

From scripts/lmm_config.py:
```python
@dataclass(frozen=True)
class LMMConfig:
    gateway: GatewayConfig
    context: ContextConfig
    glyph_encoding: GlyphEncodingConfig
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create lmm_notifications.py notification system</name>
  <files>scripts/lmm_notifications.py</files>
  <action>
Create scripts/lmm_notifications.py with:

1. `NotificationType` enum: RUN_COMPLETED, RUN_FAILED, CLIENT_DISCONNECTED

2. `NotificationBackend` protocol:
   ```python
   class NotificationBackend(Protocol):
       def send(self, title: str, body: str, ntype: NotificationType) -> bool: ...
       @property
       def name(self) -> str: ...
       def is_available(self) -> bool: ...
   ```

3. `DesktopBackend`:
   - Linux: uses `subprocess.run(["notify-send", title, body], check=False, capture_output=True)`
   - macOS: uses `subprocess.run(["osascript", "-e", f'display notification "{body}" with title "{title}"'], check=False, capture_output=True)`
   - `is_available()`: checks if the command exists on PATH
   - Returns False (not True) on failure — failure should not raise

4. `LogBackend`:
   - Writes to stderr: `sys.stderr.write(f"[LMM Notification] {title}: {body}\n")`
   - Always available
   - Always succeeds

5. `NotificationManager`:
   - `__init__(self, backends: list[NotificationBackend] | None = None, *, cooldown_seconds: int = 60)`
   - Default backends: `[DesktopBackend(), LogBackend()]` — desktop first, log as fallback
   - `notify(title: str, body: str, ntype: NotificationType) -> None`:
     - Checks cooldown: if last notification was < cooldown_seconds ago, skip (don't spam)
     - Iterates backends: calls send() on each, stops at first success
     - If all backends fail, logs to stderr
   - `reset_cooldown() -> None`: resets the cooldown timer
   - `last_notification_at: float | None` property

6. `create_notification_manager(enabled: bool = False) -> NotificationManager | None`:
   - Factory function: returns None if notifications are disabled
   - Controlled by `LMM_NOTIFICATIONS_ENABLED` env var (default False)
   - Returns NotificationManager with configurable backends

7. Keep it stdlib-only. Use `subprocess`, `shutil`, `sys`, `time`, `typing`, `platform`.

8. Do NOT add desktop notification for every request — only for runs exceeding a duration threshold (checked in Plan 02's gateway integration).
  </action>
  <verify>
    <automated>python3 -c "
import sys, io; sys.path.insert(0, 'scripts')
from lmm_notifications import (
    NotificationType, NotificationManager, LogBackend,
    DesktopBackend, create_notification_manager
)
# LogBackend is always available
log = LogBackend()
assert log.is_available()
assert log.name == 'log'
# Capture stderr
old_stderr = sys.stderr
sys.stderr = io.StringIO()
log.send('Test', 'Body', NotificationType.RUN_COMPLETED)
output = sys.stderr.getvalue()
sys.stderr = old_stderr
assert 'Test' in output
assert 'Body' in output
# NotificationManager with cooldown
mgr = NotificationManager([log], cooldown_seconds=0)
mgr.notify('Title', 'Body', NotificationType.RUN_COMPLETED)
# Disabled by default
assert create_notification_manager(enabled=False) is None
mgr2 = create_notification_manager(enabled=True)
assert mgr2 is not None
print('lmm_notifications OK')
"</automated>
  </verify>
  <done>LogBackend writes to stderr, DesktopBackend checks command availability, NotificationManager respects cooldown, factory returns None when disabled</done>
</task>

<task type="auto">
  <name>Task 2: Wire gateway to fire notifications on long runs</name>
  <files>scripts/glyphos_openai_gateway.py</files>
  <action>
Modify scripts/glyphos_openai_gateway.py:

1. **Import notification modules** at top:
   ```python
   from lmm_notifications import create_notification_manager, NotificationType
   ```

2. **Add notification manager factory**:
   ```python
   def notification_manager():
       enabled = os.environ.get("LMM_NOTIFICATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
       return create_notification_manager(enabled=enabled)
   ```

3. **Fire notifications in stream_completion**: After the loop completes (on "done" event), check if duration_ms > 30000 (30 seconds). If so, fire a notification:
   ```python
   mgr = notification_manager()
   if mgr and latency_ms > 30000:
       model_short = model.split("/")[-1] if "/" in model else model
       mgr.notify(
           f"LMM: {model_short} completed",
           f"Run finished in {latency_ms // 1000}s",
           NotificationType.RUN_COMPLETED
       )
   ```

4. **Fire notifications on error**: In the `except Exception` block of stream_completion, fire a failure notification:
   ```python
   mgr = notification_manager()
   if mgr:
       mgr.notify(
           f"LMM: {model_short} failed",
           f"Error: {error_message[:100]}",
           NotificationType.RUN_FAILED
       )
   ```

5. **Fire notifications on client disconnect**: In the `except (BrokenPipeError, ConnectionResetError)` block:
   ```python
   mgr = notification_manager()
   if mgr:
       mgr.notify(
           "LMM: Client disconnected",
           f"Run cancelled by client",
           NotificationType.CLIENT_DISCONNECTED
       )
   ```

6. **Do NOT notify for short requests** — the 30-second threshold prevents notification spam for quick queries.

7. **Do NOT make notifications mandatory** — if the manager is None (disabled), the gateway works normally. No try/except needed around notification calls since the manager handles its own errors.
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/glyphos_openai_gateway.py scripts/lmm_notifications.py && echo "compiles OK"</automated>
  </verify>
  <done>Gateway compiles, notification_manager() factory creates None when disabled, notifications fire on completion (>30s), failure, and disconnect</done>
</task>

<task type="auto">
  <name>Task 3: Add contract tests for notifications</name>
  <files>tests/test_phase0_contracts.py</files>
  <action>
Add tests to tests/test_phase0_contracts.py:

1. `test_notification_manager_respects_cooldown` — Create manager with 1s cooldown, send two notifications within 0.5s, verify only one was sent (check stderr output).

2. `test_notification_manager_falls_back_to_log` — Create manager with unavailable desktop backend + log backend, verify log receives the notification.

3. `test_notifications_disabled_by_default` — create_notification_manager(enabled=False) returns None.

4. `test_gateway_emits_notification_on_long_stream` — Mock notification_manager to return a spy manager, simulate a streaming request that takes >30s, verify notification was sent.

5. `test_gateway_does_not_emit_notification_on_short_stream` — Same setup but request takes <30s, verify no notification was sent.

Use the existing test patterns: mock notification_manager with mock.patch, capture stderr for log backend verification.
  </action>
  <verify>
    <automated>python3 -m unittest tests.test_phase0_contracts.Phase0ContractTests.test_notification_manager_respects_cooldown tests.test_phase0_contracts.Phase0ContractTests.test_notification_manager_falls_back_to_log tests.test_phase0_contracts.Phase0ContractTests.test_notifications_disabled_by_default tests.test_phase0_contracts.Phase0ContractTests.test_gateway_emits_notification_on_long_stream tests.test_phase0_contracts.Phase0ContractTests.test_gateway_does_not_emit_notification_on_short_stream -v 2>&1</automated>
  </verify>
  <done>All 5 new tests pass, no existing tests broken</done>
</task>

</tasks>

<verification>
- NotificationBackend protocol with DesktopBackend + LogBackend implementations
- NotificationManager enforces cooldown, falls back through backend chain
- Gateway fires notifications only for runs > 30 seconds
- Notifications are opt-in via LMM_NOTIFICATIONS_ENABLED (default off)
- All new tests pass
</verification>

<success_criteria>
- LogBackend always works, DesktopBackend gracefully unavailable when command missing
- Cooldown prevents notification spam (max 1 per 60s default)
- Gateway integration fires on long completions, failures, disconnects
- Disabled by default, no impact on gateway behavior when off
</success_criteria>

<output>
After completion, create `.planning/phases/03-receipts-notifications/03-receipts-notifications-02-SUMMARY.md`
</output>
