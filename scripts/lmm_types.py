#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExitResult(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    USER_CANCELLED = "user_cancelled"
    TIMEOUT_EXPIRED = "timeout_expired"
    PROVIDER_ERROR = "provider_error"


def _coerce_run_status(value: Any) -> RunStatus:
    try:
        return value if isinstance(value, RunStatus) else RunStatus(str(value))
    except ValueError:
        return RunStatus.FAILED


def _coerce_exit_result(value: Any) -> ExitResult | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, ExitResult) else ExitResult(str(value))
    except ValueError:
        return ExitResult.ERROR


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "y"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "n"}:
        return False
    return default


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso8601_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00", 1) if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


@dataclass
class RunRecord:
    id: str = ""
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    prompt: str = ""
    model: str = ""
    provider: str = ""
    status: RunStatus = RunStatus.PENDING
    exit_result: ExitResult | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    route_target: str = "llamacpp"
    route_reason_code: str = ""
    completion_chars: int = 0
    harness: str = "python"
    context_status: str = "unknown"
    context_used: bool = False
    # Handoff fields (Phase 06) — optional, backward compatible
    session_id: str = ""
    upstream_session_ref: str = ""
    handoff_summary: str = ""
    request_fingerprint: str = ""
    tool_invocation_mode: str = ""
    tool_name: str = ""
    lane: str = ""
    repair_attempted: bool = False
    repair_succeeded: bool = False
    stream_tool_call_detected: bool = False
    stream_tool_call_name: str = ""
    artifacts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid4().hex[:12]
        if not self.created_at:
            self.created_at = _utc_now()
        if self.prompt is None:
            self.prompt = ""
        if len(self.prompt) > 4000:
            self.prompt = self.prompt[:4000]
        if self.duration_ms is None:
            self.duration_ms = self._compute_duration_ms()
        if not self.session_id:
            self.session_id = self.id

    def _compute_duration_ms(self) -> int | None:
        start = _parse_iso8601_timestamp(self.started_at)
        end = _parse_iso8601_timestamp(self.completed_at)
        if not start or not end:
            return self.duration_ms
        if end < start:
            return 0
        return int((end - start).total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "prompt": self.prompt,
            "model": self.model,
            "provider": self.provider,
            "status": self.status.value,
            "exit_result": self.exit_result.value if self.exit_result is not None else None,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "route_target": self.route_target,
            "route_reason_code": self.route_reason_code,
            "completion_chars": self.completion_chars,
            "harness": self.harness,
            "context_status": self.context_status,
            "context_used": self.context_used,
        }
        # Handoff fields — only include when non-empty (backward compatible)
        if self.session_id and self.session_id != self.id:
            result["session_id"] = self.session_id
        if self.upstream_session_ref:
            result["upstream_session_ref"] = self.upstream_session_ref
        if self.handoff_summary:
            result["handoff_summary"] = self.handoff_summary
        if self.request_fingerprint:
            result["request_fingerprint"] = self.request_fingerprint
        if self.tool_invocation_mode:
            result["tool_invocation_mode"] = self.tool_invocation_mode
        if self.tool_name:
            result["tool_name"] = self.tool_name
        if self.lane:
            result["lane"] = self.lane
        if self.repair_attempted:
            result["repair_attempted"] = self.repair_attempted
        if self.repair_succeeded:
            result["repair_succeeded"] = self.repair_succeeded
        if self.stream_tool_call_detected:
            result["stream_tool_call_detected"] = self.stream_tool_call_detected
        if self.stream_tool_call_name:
            result["stream_tool_call_name"] = self.stream_tool_call_name
        if self.artifacts:
            result["artifacts"] = list(self.artifacts)
        if self.tags:
            result["tags"] = list(self.tags)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        status_value = data.get("status", RunStatus.PENDING.value)
        status = _coerce_run_status(status_value)

        exit_value = data.get("exit_result")
        exit_result = _coerce_exit_result(exit_value)

        return cls(
            id=str(data.get("id", "")),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            prompt=str(data.get("prompt", "")),
            model=str(data.get("model", "")),
            provider=str(data.get("provider", "")),
            status=status,
            exit_result=exit_result,
            duration_ms=_coerce_optional_int(data.get("duration_ms")),
            error_message=data.get("error_message"),
            route_target=str(data.get("route_target", "")),
            route_reason_code=str(data.get("route_reason_code", "")),
            completion_chars=_coerce_int(data.get("completion_chars", 0)),
            harness=str(data.get("harness", "")),
            context_status=str(data.get("context_status", "")),
            context_used=_coerce_bool(data.get("context_used", False)),
            session_id=str(data.get("session_id", "")),
            upstream_session_ref=str(data.get("upstream_session_ref", "")),
            handoff_summary=str(data.get("handoff_summary", "")),
            request_fingerprint=str(data.get("request_fingerprint", "")),
            tool_invocation_mode=str(data.get("tool_invocation_mode", "")),
            tool_name=str(data.get("tool_name", "")),
            lane=str(data.get("lane", "")),
            repair_attempted=_coerce_bool(data.get("repair_attempted", False)),
            repair_succeeded=_coerce_bool(data.get("repair_succeeded", False)),
            stream_tool_call_detected=_coerce_bool(data.get("stream_tool_call_detected", False)),
            stream_tool_call_name=str(data.get("stream_tool_call_name", "")),
            artifacts=_coerce_str_list(data.get("artifacts")),
            tags=_coerce_str_list(data.get("tags")),
        )
