#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, Protocol


class StorageAdapter(Protocol):
    def read_state(self) -> dict[str, Any]:
        ...

    def append_event(self, record: dict[str, Any]) -> dict[str, Any]:
        ...


class JsonGatewayTelemetryStore:
    """Compatibility storage adapter for gateway telemetry JSON state."""

    def __init__(self, path: Path, *, recent_limit: int = 40) -> None:
        self.path = path.expanduser()
        self.recent_limit = max(1, int(recent_limit))

    def read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"recent_requests": [], "counters": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"recent_requests": [], "counters": {}}
        return payload if isinstance(payload, dict) else {"recent_requests": [], "counters": {}}

    def append_event(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock():
            state = self.read_state()
            counters = state.get("counters")
            if not isinstance(counters, dict):
                counters = {}
            for key in ("mode", "route_target", "context_status", "success"):
                value = str(record.get(key, "unknown"))
                counter_key = f"{key}:{value}"
                counters[counter_key] = int(counters.get(counter_key, 0)) + 1

            recent = state.get("recent_requests")
            if not isinstance(recent, list):
                recent = []
            recent.insert(0, record)
            del recent[self.recent_limit:]

            state["counters"] = counters
            state["recent_requests"] = recent
            state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._write_state(state)
            return state

    def _write_state(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
