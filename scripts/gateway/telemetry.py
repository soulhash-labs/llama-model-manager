from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from lmm_config import load_lmm_config_from_env
from lmm_storage import JsonGatewayTelemetryStore, JsonRunRecordStore
from lmm_types import ExitResult, RunRecord, RunStatus

try:
    from lmm_handoff import HandoffSummary, format_handoff_text  # type: ignore
except ImportError:
    HandoffSummary = None  # type: ignore
    format_handoff_text = None  # type: ignore


SENSITIVE_TELEMETRY_KEYS = {
    "command_substitution",
    "command_substitutions",
    "raw_command",
    "shell_command",
}


def telemetry_store() -> JsonGatewayTelemetryStore:
    config = load_lmm_config_from_env().gateway
    return JsonGatewayTelemetryStore(config.state_file, recent_limit=config.telemetry_recent_limit)


def run_record_store() -> JsonRunRecordStore:
    config = load_lmm_config_from_env().gateway
    run_path = Path(
        os.environ.get(
            "LMM_RUN_RECORDS_FILE",
            str(Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json"),
        )
    ).expanduser()
    return JsonRunRecordStore(run_path, recent_limit=config.telemetry_recent_limit)


def load_gateway_state() -> dict[str, Any]:
    return telemetry_store().read_state()


def redact_gateway_telemetry_record(record: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_sensitive_telemetry_value(record)
    prompt = redacted.pop("prompt", "")
    if isinstance(prompt, str):
        redacted.setdefault("prompt_chars", len(prompt))
    elif prompt:
        redacted.setdefault("prompt_chars", len(json.dumps(prompt)))
    return redacted


def _redact_sensitive_telemetry_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in SENSITIVE_TELEMETRY_KEYS:
                continue
            redacted[key_text] = _redact_sensitive_telemetry_value(item)
        return redacted
    if isinstance(value, list):
        return [
            _redact_sensitive_telemetry_value(item)
            for item in value
            if not (isinstance(item, str) and item in SENSITIVE_TELEMETRY_KEYS)
        ]
    return value


def request_fingerprint(record: dict[str, Any]) -> str:
    selected = {
        "format": record.get("format", "openai"),
        "model": record.get("model", ""),
        "prompt": record.get("prompt", ""),
        "gateway_mode": record.get("gateway_mode", ""),
        "mode": record.get("mode", ""),
        "harness": record.get("harness", ""),
        "stream": bool(record.get("stream", False)),
    }
    payload = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def with_request_fingerprint(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    if not str(enriched.get("request_fingerprint", "")).strip():
        enriched["request_fingerprint"] = request_fingerprint(enriched)
    return enriched


def record_gateway_request(record: dict[str, Any]) -> None:
    """Record gateway request with full error propagation."""
    try:
        telemetry_store().append_event(redact_gateway_telemetry_record(with_request_fingerprint(record)))
    except Exception:
        sys.stderr.write(f"warning: failed to record gateway telemetry: {traceback.format_exc()}\n")


def safe_record_gateway_request(record: dict[str, Any]) -> None:
    try:
        record_gateway_request(record)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        sys.stderr.write(f"warning: failed to persist LMM gateway telemetry: {exc}\n")


def safe_record_run_record(record: RunRecord) -> None:
    try:
        run_record_store().append_record(record.to_dict())
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        sys.stderr.write(f"warning: failed to persist LMM run record: {exc}\n")


def current_iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_record_from_dict(record: dict[str, Any]) -> RunRecord:
    raw_prompt = record.get("prompt", "")
    if not isinstance(raw_prompt, str):
        raw_prompt = json.dumps(raw_prompt)

    provider = str(record.get("provider") or record.get("route_target") or "")
    status = RunStatus(record.get("status", RunStatus.PENDING))
    exit_result = record.get("exit_result")
    if isinstance(exit_result, str):
        exit_result = ExitResult(exit_result)
    elif not isinstance(exit_result, ExitResult):
        exit_result = None

    duration_ms = (
        record.get("duration_ms")
        if isinstance(record.get("duration_ms"), int)
        else (record.get("latency_ms") if isinstance(record.get("latency_ms"), int) else None)
    )

    return RunRecord(
        prompt=raw_prompt,
        model=str(record.get("model", "")),
        provider=provider,
        status=status,
        exit_result=exit_result,
        started_at=str(record.get("started_at")) if record.get("started_at") else None,
        completed_at=str(record.get("completed_at")) if record.get("completed_at") else None,
        error_message=str(record.get("error")) if isinstance(record.get("error"), str) else None,
        route_target=str(record.get("route_target", "")),
        route_reason_code=str(record.get("reason_code", "")),
        completion_chars=int(record.get("completion_chars", 0) or 0),
        harness=str(record.get("harness", "")),
        context_status=str(record.get("context_status", "")),
        context_used=bool(record.get("context_used", False)),
        duration_ms=duration_ms,
        session_id=str(record.get("session_id", "")),
        upstream_session_ref=str(record.get("upstream_session_ref", "")),
        handoff_summary=str(record.get("handoff_summary", "")),
        artifacts=list(record.get("artifacts", [])),
        tags=list(record.get("tags", [])),
        request_fingerprint=str(record.get("request_fingerprint", "") or request_fingerprint(record)),
        tool_invocation_mode=str(record.get("tool_invocation_mode", "")),
        tool_name=str(record.get("tool_name", "")),
        lane=str(record.get("lane", "")),
        repair_attempted=bool(record.get("repair_attempted", False)),
        repair_succeeded=bool(record.get("repair_succeeded", False)),
        stream_tool_call_detected=bool(record.get("stream_tool_call_detected", False)),
        stream_tool_call_name=str(record.get("stream_tool_call_name", "")),
    )


def generate_handoff_summary(record: dict[str, Any], duration_ms: int) -> None:
    """Populate record['handoff_summary'] for long-running sessions."""

    if HandoffSummary is None or format_handoff_text is None:
        return
    threshold_ms = int(os.environ.get("LMM_HANDOFF_THRESHOLD_MS", "60000"))
    if duration_ms < threshold_ms:
        return
    try:
        summary = HandoffSummary.from_run_record(record)
        record["handoff_summary"] = format_handoff_text(summary)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        sys.stderr.write(f"warning: failed to generate LMM handoff summary: {exc}\n")


__all__ = [
    "telemetry_store",
    "run_record_store",
    "load_gateway_state",
    "redact_gateway_telemetry_record",
    "request_fingerprint",
    "with_request_fingerprint",
    "record_gateway_request",
    "safe_record_gateway_request",
    "safe_record_run_record",
    "current_iso_timestamp",
    "run_record_from_dict",
    "generate_handoff_summary",
]
