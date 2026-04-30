#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lmm_storage import _FileLockedJsonStore, _utc_timestamp


def sha256_prefix(text: str, max_chars: int = 2000) -> str:
    """Return a stable sha256 digest for a truncated string segment."""

    if not text:
        text = ""
    limit = max(0, int(max_chars))
    payload = str(text)[:limit].encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass
class Receipt:
    version: int = 1
    run_id: str = ""
    route_target: str = ""
    route_reason_code: str = ""
    model: str = ""
    harness: str = "python"
    status: str = "success"
    status_code: int = 200
    request_digest: str = ""
    response_chars: int = 0
    response_digest: str = ""
    duration_ms: int = 0
    created_at: str = field(default_factory=_utc_timestamp)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "route_target": self.route_target,
            "route_reason_code": self.route_reason_code,
            "model": self.model,
            "harness": self.harness,
            "status": self.status,
            "status_code": self.status_code,
            "request_digest": self.request_digest,
            "response_chars": self.response_chars,
            "response_digest": self.response_digest,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Receipt:
        return cls(
            version=int(data.get("version", 1)),
            run_id=str(data.get("run_id", "")),
            route_target=str(data.get("route_target", "")),
            route_reason_code=str(data.get("route_reason_code", "")),
            model=str(data.get("model", "")),
            harness=str(data.get("harness", "python")),
            status=str(data.get("status", "success")),
            status_code=int(data.get("status_code", 200)),
            request_digest=str(data.get("request_digest", "")),
            response_chars=int(data.get("response_chars", 0)),
            response_digest=str(data.get("response_digest", "")),
            duration_ms=int(data.get("duration_ms", 0)),
            created_at=str(data.get("created_at", _utc_timestamp())),
            error_message=data.get("error_message"),
        )


class ReceiptEmitter(_FileLockedJsonStore):
    """Bounded JSONL emitter for request receipts."""

    def __init__(self, path: Path, *, line_limit: int = 200) -> None:
        super().__init__(path)
        self.line_limit = max(1, int(line_limit))

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [line.strip() for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write_lines(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(self.path)

    def emit(self, receipt: Receipt) -> None:
        with self._lock():
            lines = self._read_lines()
            lines.append(json.dumps(receipt.to_dict(), separators=(",", ":")))
            if len(lines) > self.line_limit:
                lines = lines[-self.line_limit :]
            self._write_lines(lines)

    def read_recent(self, limit: int = 20) -> list[Receipt]:
        count = max(0, int(limit))
        if not self.path.exists() or count == 0:
            return []
        receipts: list[Receipt] = []
        for raw in reversed(self._read_lines()):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            receipts.append(Receipt.from_dict(payload))
            if len(receipts) >= count:
                break
        return receipts
