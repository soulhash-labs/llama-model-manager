#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class NotificationType(Enum):
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    CLIENT_DISCONNECTED = "client_disconnected"
    UPDATE_AVAILABLE = "update_available"


@runtime_checkable
class NotificationBackend(Protocol):
    def send(self, title: str, body: str, ntype: NotificationType) -> bool: ...

    @property
    def name(self) -> str: ...

    def is_available(self) -> bool: ...


@dataclass
class DesktopBackend:
    @property
    def name(self) -> str:
        return "desktop"

    @property
    def _command(self) -> str:
        current_platform = platform.system()
        if current_platform == "Linux":
            return "notify-send"
        if current_platform == "Darwin":
            return "osascript"
        return ""

    def is_available(self) -> bool:
        return bool(self._command) and shutil.which(self._command) is not None

    def send(self, title: str, body: str, ntype: NotificationType) -> bool:
        if not self.is_available():
            return False
        try:
            if self._command == "notify-send":
                command = ["notify-send", title, body]
            else:
                escaped_body = body.replace('"', '\\"')
                command = ["osascript", "-e", f'display notification "{escaped_body}" with title "{title}"']
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False


@dataclass
class LogBackend:
    @property
    def name(self) -> str:
        return "log"

    def is_available(self) -> bool:
        return True

    def send(self, title: str, body: str, ntype: NotificationType) -> bool:
        sys.stderr.write(f"[LMM Notification] {title}: {body}\n")
        sys.stderr.flush()
        return True


class NotificationManager:
    def __init__(self, backends: list[NotificationBackend] | None = None, *, cooldown_seconds: int = 60) -> None:
        self.backends = backends or [DesktopBackend(), LogBackend()]
        self.cooldown_seconds = cooldown_seconds
        self._last_notification_at: float | None = None

    @property
    def last_notification_at(self) -> float | None:
        return self._last_notification_at

    def reset_cooldown(self) -> None:
        self._last_notification_at = None

    def notify(self, title: str, body: str, ntype: NotificationType) -> None:
        now = time.time()
        if self._last_notification_at is not None and now - self._last_notification_at < self.cooldown_seconds:
            return

        for backend in self.backends:
            if backend.send(title, body, ntype):
                self._last_notification_at = now
                return

        sys.stderr.write(f"[LMM Notification] failed: {title}: {body}\n")


def create_notification_manager(enabled: bool = False) -> NotificationManager | None:
    env_enabled = os.environ.get("LMM_NOTIFICATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
    if not enabled and not env_enabled:
        return None
    return NotificationManager()
