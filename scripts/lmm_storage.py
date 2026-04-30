#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _FileLockedJsonStore:
    """Shared locking + atomic-write helper for JSON file stores."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()

    def _read_state(self, default_state: dict[str, Any]) -> dict[str, Any]:
        if not self.path.exists():
            return dict(default_state)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return dict(default_state)
        return payload if isinstance(payload, dict) else dict(default_state)

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


class StorageAdapter(Protocol):
    def read_state(self) -> dict[str, Any]:
        ...

    def append_event(self, record: dict[str, Any]) -> dict[str, Any]:
        ...


class JsonGatewayTelemetryStore(_FileLockedJsonStore):
    """Compatibility storage adapter for gateway telemetry JSON state."""

    def __init__(self, path: Path, *, recent_limit: int = 40) -> None:
        super().__init__(path)
        self.recent_limit = max(1, int(recent_limit))

    def read_state(self) -> dict[str, Any]:
        return self._read_state({"recent_requests": [], "counters": {}})

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
            state["updated_at"] = _utc_timestamp()
            self._write_state(state)
            return state


class JsonRunRecordStore(_FileLockedJsonStore):
    """Bounded JSON store for gateway run records."""

    def __init__(self, path: Path | None = None, *, recent_limit: int = 50) -> None:
        default_path = Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json"
        super().__init__(path or default_path)
        self.recent_limit = max(1, int(recent_limit))

    def read_state(self) -> dict[str, Any]:
        return self._read_state({"schema_version": 1, "records": [], "updated_at": _utc_timestamp()})

    def append_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock():
            state = self.read_state()
            records = state.get("records")
            if not isinstance(records, list):
                records = []
            records = [entry for entry in records if isinstance(entry, dict)]
            records.insert(0, record)
            del records[self.recent_limit:]

            state["schema_version"] = 1
            state["records"] = records
            state["updated_at"] = _utc_timestamp()
            self._write_state(state)
            return list(records)

    def list_recent(self, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        state = self.read_state()
        records = state.get("records")
        if not isinstance(records, list):
            records = []
        filtered = [
            record
            for record in records
            if isinstance(record, dict) and (status is None or str(record.get("status")) == status)
        ]
        return filtered[: max(0, int(limit))]

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        for record in self.list_recent(limit=self.recent_limit):
            if isinstance(record, dict) and record.get("id") == record_id:
                return record
        return None

    def latest_completed(self) -> dict[str, Any] | None:
        for record in self.list_recent(limit=self.recent_limit, status="completed"):
            if isinstance(record, dict):
                return record
        return None

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.list_recent(limit=self.total_records()):
            status = str(record.get("status")) if isinstance(record, dict) else ""
            if not status:
                continue
            counts[status] = counts.get(status, 0) + 1
        return counts

    def total_records(self) -> int:
        state = self.read_state()
        records = state.get("records")
        if not isinstance(records, list):
            return 0
        return len(records)
