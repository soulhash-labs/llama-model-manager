#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

APP_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
INTEGRATION_ROOT = APP_ROOT / "integrations" / "public-glyphos-ai-compute"
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))

from lmm_updates import UpdateChecker  # noqa: E402

from lmm_config import load_lmm_config_from_env  # noqa: E402
from lmm_errors import GatewayError, InvalidRequestError  # noqa: E402
from lmm_health import ComponentHealth, HealthChecker  # noqa: E402
from lmm_notifications import NotificationType, create_notification_manager  # noqa: E402
from lmm_storage import JsonGatewayTelemetryStore, JsonRunRecordStore  # noqa: E402
from lmm_types import ExitResult, RunRecord, RunStatus  # noqa: E402

# Phase 06: Handoff module (optional import for backward compat)
try:
    from lmm_handoff import HandoffSummary, format_handoff_text  # type: ignore
except ImportError:
    HandoffSummary = None  # type: ignore
    format_handoff_text = None  # type: ignore


def _generate_handoff_summary(record: dict[str, Any], duration_ms: int) -> None:
    """Generate handoff summary for long-running sessions and store in record.

    Phase 06: For runs exceeding the handoff threshold, populate the
    handoff_summary field with a human-readable summary.
    """
    if HandoffSummary is None or format_handoff_text is None:
        return
    threshold_ms = int(os.environ.get("LMM_HANDOFF_THRESHOLD_MS", "60000"))
    if duration_ms < threshold_ms:
        return
    try:
        summary = HandoffSummary.from_run_record(record)
        record["handoff_summary"] = format_handoff_text(summary)
    except Exception:
        pass  # Never break recording for handoff generation failure


def now() -> float:
    return time.time()


def json_response(
    handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: BaseHTTPRequestHandler, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    length_text = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_text)
    except ValueError as exc:
        raise InvalidRequestError("invalid Content-Length") from exc
    if length < 0 or length > max_bytes:
        raise InvalidRequestError("request body too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError as exc:
        raise InvalidRequestError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise InvalidRequestError("request JSON must be an object")
    return payload


def request_int(payload: dict[str, Any], key: str, default: int, *, minimum: int = 1) -> int:
    raw = payload.get(key, default)
    if isinstance(raw, bool):
        raise InvalidRequestError(f"{key} must be an integer")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    else:
        raise InvalidRequestError(f"{key} must be an integer")
    if value < minimum:
        raise InvalidRequestError(f"{key} must be at least {minimum}")
    return value


def request_float(payload: dict[str, Any], key: str, default: float) -> float:
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{key} must be a number") from exc
    if not math.isfinite(value):
        raise InvalidRequestError(f"{key} must be finite")
    return value


def http_json(
    method: str, url: str, *, payload: dict[str, Any] | None = None, timeout: int = 5
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return int(exc.code), parsed if isinstance(parsed, dict) else {"error": raw}
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def run_context_command(
    command: list[str], *, input_text: str, timeout_seconds: float, cwd: str
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(command, timeout_seconds, output=stdout, stderr=stderr) from exc
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def state_file() -> Path:
    return load_lmm_config_from_env().gateway.state_file


def telemetry_store() -> JsonGatewayTelemetryStore:
    config = load_lmm_config_from_env().gateway
    return JsonGatewayTelemetryStore(config.state_file, recent_limit=config.telemetry_recent_limit)


def run_record_store() -> JsonRunRecordStore:
    config = load_lmm_config_from_env().gateway
    run_path = Path(
        os.environ.get(
            "LMM_RUN_RECORDS_FILE", str(Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json")
        )
    ).expanduser()
    return JsonRunRecordStore(run_path, recent_limit=config.telemetry_recent_limit)


def load_gateway_state() -> dict[str, Any]:
    return telemetry_store().read_state()


def _redact_gateway_telemetry_record(record: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(record)
    prompt = redacted.pop("prompt", "")
    if isinstance(prompt, str):
        redacted.setdefault("prompt_chars", len(prompt))
    elif prompt:
        redacted.setdefault("prompt_chars", len(json.dumps(prompt)))
    return redacted


def _build_context_payload(
    *,
    raw_context: str,
    raw_context_chars: int,
    encoding_status: str,
    encoded_context: str,
    encoding_format: str,
    encoding_ratio: float,
) -> Any:
    try:
        from glyphos_ai.glyph.types import ContextPayload as _ContextPayload  # type: ignore

        return _ContextPayload(
            raw_context=str(raw_context),
            raw_context_chars=int(raw_context_chars),
            encoding_status=str(encoding_status),
            encoded_context=str(encoded_context),
            encoding_format=str(encoding_format),
            encoding_ratio=float(encoding_ratio),
        )
    except Exception:
        return SimpleNamespace(
            raw_context=str(raw_context),
            raw_context_chars=int(raw_context_chars),
            encoding_status=str(encoding_status),
            encoded_context=str(encoded_context),
            encoding_format=str(encoding_format),
            encoding_ratio=float(encoding_ratio),
        )


def record_gateway_request(record: dict[str, Any]) -> None:
    telemetry_store().append_event(_redact_gateway_telemetry_record(record))


def safe_record_gateway_request(record: dict[str, Any]) -> None:
    try:
        record_gateway_request(record)
    except Exception as exc:
        sys.stderr.write(f"warning: failed to persist LMM gateway telemetry: {exc}\n")


def safe_record_run_record(record: RunRecord) -> None:
    try:
        run_record_store().append_record(record.to_dict())
    except Exception as exc:
        sys.stderr.write(f"warning: failed to persist LMM run record: {exc}\n")


def _current_iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run_record_from_dict(record: dict[str, Any]) -> RunRecord:
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
        duration_ms=record.get("duration_ms")
        if isinstance(record.get("duration_ms"), int)
        else (record.get("latency_ms") if isinstance(record.get("latency_ms"), int) else None),
        session_id=str(record.get("session_id", "")),
        upstream_session_ref=str(record.get("upstream_session_ref", "")),
        handoff_summary=str(record.get("handoff_summary", "")),
        artifacts=list(record.get("artifacts", [])),
        tags=list(record.get("tags", [])),
    )


def messages_to_prompt(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    parts.append(str(part.get("text", "")))
                elif isinstance(part, str):
                    parts.append(part)
            content_text = "\n".join(piece for piece in parts if piece)
        else:
            content_text = str(content)
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def anthropic_messages_to_text(messages: Any, system: Any = None) -> str:
    """Convert Anthropic-format messages to prompt text for the LMM pipeline.

    Handles system prompt from top-level ``system`` parameter (string or
    ``[{"type": "text", "text": "..."}]`` array) and per-message content
    that may be a string or an array of content blocks.
    """
    lines: list[str] = []

    # Extract system prompt
    if system is not None:
        if isinstance(system, str):
            system_text = system.strip()
        elif isinstance(system, list):
            parts: list[str] = []
            for item in system:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            system_text = "\n".join(part for part in parts if part).strip()
        else:
            system_text = str(system).strip()
        if system_text:
            lines.append(f"system: {system_text}")

    if not isinstance(messages, list):
        return "\n\n".join(lines)

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text", ""))
                    if text:
                        parts.append(text)
                elif isinstance(part, str):
                    parts.append(part)
            content_text = "\n".join(parts)
        else:
            content_text = str(content)
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def anthropic_messages_summary(messages: Any) -> dict[str, Any]:
    """Return a summary of Anthropic-format messages (analog of :func:`message_summary`).

    Counts messages by role, total characters, and handles content as both
    string and array formats.
    """
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary
    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            content_chars = sum(
                len(str(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            content_chars = len(str(content))
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})
    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary
    roles: dict[str, int] = {}
    chars = 0
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            content_chars = sum(
                len(str(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            content_chars = len(str(content))
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
    summary.update(
        {
            "count": len(messages),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def build_anthropic_response(
    text: str,
    model: str,
    started: float,
    routed: dict[str, Any],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    """Build an Anthropic-format response dict for non-streaming ``/v1/messages``.

    Includes LMM routing metadata under the ``lmm`` key.
    """
    return {
        "id": f"msg_{int(started * 1000)}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 0,  # Approximate from text length if no upstream count
            "output_tokens": max(1, len(text.split())),
        },
        "lmm": {
            "route_target": routed.get("target", "unknown"),
            "route_reason_code": routed.get("reason_code", "unknown"),
            "context_status": pipeline.get("context_status", "unknown"),
            "context_used": bool(pipeline.get("context_used")),
            "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
            "latency_ms": routed.get("latency_ms", 0),
        },
    }


def context_pipeline_enabled() -> bool:
    return load_lmm_config_from_env().context.enabled


def context_mcp_root() -> Path:
    return APP_ROOT / "integrations" / "context-mode-mcp"


def context_mcp_bridge_path() -> Path:
    return APP_ROOT / "scripts" / "context_mcp_bridge.py"


def context_mcp_db_path() -> Path:
    """Compute the SQLite DB path used by the MCP server for the current project."""
    import hashlib

    project_root = os.getcwd()
    project_hash = hashlib.sha256(project_root.encode()).hexdigest()[:16]
    return Path.home() / ".claude" / "context-mode" / "sessions" / f"{project_hash}.db"


def _maybe_run_indexer(timeout_seconds: float) -> dict[str, Any]:
    """Run the project indexer (incremental — skips unchanged files).

    Returns a dict with indexing stats: indexed, skipped, errors, duration_ms.
    The indexer is now fast enough to call on every search request.
    """
    empty = {"indexed": 0, "skipped": 0, "errors": 0, "duration_ms": 0}
    mcp_entry = context_mcp_root() / "dist" / "index.js"
    if not mcp_entry.is_file():
        return empty

    node_bin = shutil.which("node")
    if not node_bin:
        return empty

    try:
        completed = subprocess.run(
            [node_bin, str(mcp_entry), "--index-project"],
            cwd=str(context_mcp_root()),
            env={**os.environ, "CTX_PROJECT_ROOT": os.getcwd()},
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
        # The MCP indexer prints a JSON summary to stdout on success.
        try:
            result = json.loads(completed.stdout.strip())
            if isinstance(result, dict):
                return {
                    "indexed": int(result.get("indexed", 0)),
                    "skipped": int(result.get("skipped", 0)),
                    "errors": int(result.get("errors", 0)),
                    "duration_ms": int(result.get("duration_ms", 0)),
                }
        except (json.JSONDecodeError, ValueError):
            pass  # No JSON summary — indexer ran silently
        return empty
    except Exception:
        return empty  # Best-effort; search will still work


def _extract_session_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract session metadata from request payload for handoff tracking.

    Reads metadata.session_id, metadata.conversation_id, metadata.tags,
    and metadata.artifact_paths from the incoming chat completion payload.
    """
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict):
        return {}

    result: dict[str, Any] = {}
    session_id = metadata.get("session_id") or metadata.get("conversation_id")
    if isinstance(session_id, str) and session_id:
        result["session_id"] = session_id

    upstream_ref = metadata.get("upstream_session_ref")
    if isinstance(upstream_ref, str) and upstream_ref:
        result["upstream_session_ref"] = upstream_ref

    tags = metadata.get("tags")
    if isinstance(tags, list):
        result["tags"] = [str(t) for t in tags if isinstance(t, str)]

    artifacts = metadata.get("artifact_paths") or metadata.get("artifacts")
    if isinstance(artifacts, list):
        result["artifacts"] = [str(a) for a in artifacts if isinstance(a, str)]

    return result


def context_status() -> tuple[str, bool]:
    context_config = load_lmm_config_from_env().context
    if not context_config.enabled:
        return "disabled", False
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        return "missing", False
    if context_config.command:
        return "command_configured", False
    if not context_mcp_bridge_path().is_file():
        return "missing_bridge", False
    if not (root / "dist" / "index.js").is_file():
        return "missing_dist", False
    return "bridge_ready", False


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def extract_payload_context(payload: dict[str, Any]) -> Any:
    metadata = payload.get("metadata")
    candidates = [
        payload.get("lmm_context"),
        payload.get("retrieved_context"),
        payload.get("context"),
    ]
    if isinstance(metadata, dict):
        candidates.extend(
            [
                metadata.get("lmm_context"),
                metadata.get("retrieved_context"),
                metadata.get("context"),
            ]
        )
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return candidate
    return ""


def context_to_text(context: Any) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context.strip()
    return compact_json(context)


def notification_manager():
    enabled = os.environ.get("LMM_NOTIFICATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
    return create_notification_manager(enabled=enabled)


def message_summary(messages: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary
    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        content_chars = len(compact_json(content) if not isinstance(content, str) else content)
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})
    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def command_context_from_output(raw: str) -> dict[str, Any]:
    """Extract context text and search metadata from bridge output.

    Returns dict with:
    - context: text content (always str)
    - meta: search metadata from MCP (strategy, degraded, suggestions)
    """
    default = {"context": "", "meta": {}}
    raw = raw.strip()
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"context": raw, "meta": {}}
    if not isinstance(parsed, dict):
        return {"context": str(parsed), "meta": {}}

    # Extract search metadata (FTS5 degradation signal)
    meta = parsed.get("meta")
    if isinstance(meta, dict):
        meta = {
            "strategy": str(meta.get("strategy", "unknown")),
            "degraded": bool(meta.get("degraded", False)),
            "suggestions": meta.get("suggestions") if isinstance(meta.get("suggestions"), list) else [],
        }
    else:
        meta = {}

    # Extract context text
    for key in ("retrieved_context", "context", "text", "markdown"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return {"context": value, "meta": meta}
        if isinstance(value, dict) and value:
            return {"context": json.dumps(value), "meta": meta}
        if isinstance(value, list) and value:
            return {"context": str(value), "meta": meta}

    items = parsed.get("items") or parsed.get("results") or parsed.get("snippets")
    if isinstance(items, list):
        pieces: list[str] = []
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("snippet")
                title = item.get("title") or item.get("path") or item.get("uri")
                if text:
                    pieces.append(f"{title}: {text}" if title else str(text))
            elif item:
                pieces.append(str(item))
        return {"context": "\n".join(pieces), "meta": meta}

    return default


def retrieve_context(payload: dict[str, Any], prompt: str, *, model: str, stream: bool) -> dict[str, Any]:
    context_config = load_lmm_config_from_env().context
    started = time.perf_counter()
    result: dict[str, Any] = {
        "status": "disabled",
        "used": False,
        "context": "",
        "source": "",
        "error": "",
        "latency_ms": 0,
    }
    if not context_config.enabled:
        return result
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        result.update({"status": "missing"})
        return result

    payload_context = extract_payload_context(payload)
    if payload_context:
        text = context_to_text(payload_context)
        result.update(
            {
                "status": "retrieved_from_payload",
                "used": bool(text),
                "context": text,
                "source": "payload",
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    command = context_config.command
    if not command:
        bridge = context_mcp_bridge_path()
        if not bridge.is_file():
            result.update(
                {
                    "status": "missing_bridge",
                    "source": "context-mode-mcp",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            return result
        if not (root / "dist" / "index.js").is_file():
            result.update(
                {
                    "status": "missing_dist",
                    "source": "context-mode-mcp",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            return result
        command = f"{sys.executable} {bridge}"
    if not command:
        result.update(
            {
                "status": "available_no_context",
                "source": "context-mode-mcp",
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    timeout_ms = context_config.timeout_ms
    request_payload = {
        "tool": "ctx_search",
        "query": prompt[-4000:],
        "limit": 8,
        "model": model,
        "stream": stream,
        "message_summary": message_summary(payload.get("messages", [])),
        "project_root": os.getcwd(),
    }

    # Incremental index refresh before every search (fast — skips unchanged files).
    _maybe_run_indexer(timeout_seconds=max(5, timeout_ms / 2000))

    try:
        completed = run_context_command(
            shlex.split(command),
            input_text=compact_json(request_payload),
            timeout_seconds=timeout_ms / 1000,
            cwd=str(root),
        )
        if completed.returncode != 0:
            result.update({"status": "error", "source": "context-mode-mcp", "error": "context_command_failed"})
            return result
        extracted = command_context_from_output(completed.stdout)
        text = context_to_text(extracted.get("context", ""))
        search_meta = extracted.get("meta", {})
        result.update(
            {
                "status": "retrieved" if text else "empty",
                "used": bool(text),
                "context": text,
                "source": "context-mode-mcp",
                # FTS5 search metadata (loud failures)
                "search_strategy": search_meta.get("strategy", ""),
                "search_degraded": bool(search_meta.get("degraded", False)),
                "search_suggestions": search_meta.get("suggestions", []),
            }
        )
        return result
    except subprocess.TimeoutExpired:
        result.update({"status": "timeout", "source": "context-mode-mcp", "error": f"timeout after {timeout_ms}ms"})
        return result
    except Exception as exc:
        result.update({"status": "error", "source": "context-mode-mcp", "error": exc.__class__.__name__})
        return result
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)


GLYPH_KEY_ALIASES = {
    "path": "p",
    "file": "f",
    "title": "t",
    "uri": "u",
    "content": "c",
    "text": "x",
    "snippet": "s",
    "summary": "m",
    "score": "r",
    "line": "l",
    "lines": "ls",
    "language": "g",
}


def alias_context_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {GLYPH_KEY_ALIASES.get(str(key), str(key)): alias_context_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [alias_context_keys(item) for item in value]
    return value


def repeated_line_payload(text: str) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in (item.strip() for item in text.splitlines()):
        if not line:
            continue
        if line not in counts:
            order.append(line)
        counts[line] = counts.get(line, 0) + 1
    repeated = [{"n": counts[line], "x": line} for line in order if counts[line] > 1]
    if not repeated:
        return ""
    singles = [line for line in order if counts[line] == 1]
    return "GE1-LINES " + compact_json({"repeat": repeated, "single": singles})


def glyph_encode_context(context: str) -> dict[str, Any]:
    raw = context.strip()
    raw_chars = len(raw)
    result: dict[str, Any] = {
        "status": "skipped",
        "used": False,
        "raw_context_chars": raw_chars,
        "encoded_context_chars": 0,
        "estimated_token_delta": 0,
        "encoding_ratio": 1.0,
        "encoded_context": "",
        "error": "",
        "latency_ms": 0,
    }
    started = time.perf_counter()
    try:
        if not raw:
            return result
        encoding_config = load_lmm_config_from_env().glyph_encoding
        if encoding_config.disabled:
            result["status"] = "disabled"
            return result
        if encoding_config.force_error:
            raise RuntimeError("forced glyph encoding failure")
        encoded = ""
        try:
            parsed = json.loads(raw)
            encoded = "GE1-JSON " + compact_json(alias_context_keys(parsed))
        except json.JSONDecodeError:
            encoded = repeated_line_payload(raw)
        if not encoded:
            result["status"] = "raw_unstructured"
            return result
        encoded_chars = len(encoded)
        if encoded_chars >= raw_chars:
            result.update(
                {
                    "status": "raw_not_smaller",
                    "encoded_context_chars": encoded_chars,
                    "encoding_ratio": round(encoded_chars / raw_chars, 4) if raw_chars else 1.0,
                }
            )
            return result
        result.update(
            {
                "status": "encoded",
                "used": True,
                "encoded_context_chars": encoded_chars,
                "estimated_token_delta": round((raw_chars - encoded_chars) / 4),
                "encoding_ratio": round(encoded_chars / raw_chars, 4),
                "encoded_context": encoded,
            }
        )
        return result
    except Exception as exc:
        result.update({"status": "error_raw_fallback", "error": str(exc)[:400]})
        return result
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)


def assemble_prompt_raw(raw_prompt: str, context_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Assemble prompt with raw context only (no Ψ encoding).

    The router decides whether to apply encoding based on target backend.
    """
    context = str(context_result.get("context") or "").strip()
    if not context:
        return raw_prompt, {
            "assembly_status": "raw_prompt",
            "assembled_prompt_chars": len(raw_prompt),
            "context_block_chars": 0,
        }
    context_block = "\n".join(
        [
            "[Retrieved Context]",
            context,
        ]
    )
    assembled = "\n\n".join(
        [
            "System: Use retrieved context only as supporting evidence. The latest user instruction below overrides retrieved or encoded context.",
            context_block,
            "[Conversation and latest user request]",
            raw_prompt,
        ]
    )
    return assembled, {
        "assembly_status": "raw_context",
        "assembled_prompt_chars": len(assembled),
        "context_block_chars": len(context_block),
    }


def assemble_prompt(
    raw_prompt: str, context_result: dict[str, Any], encoding_result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    context = str(context_result.get("context") or "").strip()
    if not context:
        return raw_prompt, {
            "assembly_status": "raw_prompt",
            "assembled_prompt_chars": len(raw_prompt),
            "context_block_chars": 0,
        }
    if encoding_result.get("used"):
        context_block = "\n".join(
            [
                "[Glyph Encoding v1]",
                "Decode this compact context before reasoning. Key aliases: p=path, f=file, t=title, u=uri, c=content, x=text, s=snippet, m=summary, r=score.",
                str(encoding_result.get("encoded_context", "")),
            ]
        )
        assembly_status = "glyph_encoded_context"
    else:
        context_block = "\n".join(
            [
                "[Retrieved Context]",
                context,
            ]
        )
        assembly_status = "raw_context"
    assembled = "\n\n".join(
        [
            "System: Use retrieved context only as supporting evidence. The latest user instruction below overrides retrieved or encoded context.",
            context_block,
            "[Conversation and latest user request]",
            raw_prompt,
        ]
    )
    return assembled, {
        "assembly_status": assembly_status,
        "assembled_prompt_chars": len(assembled),
        "context_block_chars": len(context_block),
    }


def prepare_gateway_pipeline(
    payload: dict[str, Any], raw_prompt: str, *, model: str, stream: bool
) -> tuple[str, dict[str, Any]]:
    """Prepare gateway pipeline without pre-encoding.

    The router will decide whether to apply Ψ encoding based on target.
    ContextPayload is carried through the pipeline to the router.
    """
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    request_lifecycle = {
        "messages": message_summary(payload.get("messages", [])),
        "model": model,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768"))),
        "stream": stream,
        "harness_identity": "",
        "workspace_present": bool(payload.get("workspace") or metadata.get("workspace")),
        "session_present": bool(payload.get("session") or metadata.get("session")),
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
    }
    context_result = retrieve_context(payload, raw_prompt, model=model, stream=stream)

    # Pre-compute encoding info for telemetry, but DON'T apply it to the prompt yet
    raw_ctx = str(context_result.get("context") or "") if context_result.get("used") else ""
    encoding_result = glyph_encode_context(raw_ctx)

    # Build raw assembled prompt (no Ψ encoding — router decides later)
    assembled_prompt, assembly = assemble_prompt_raw(raw_prompt, context_result)

    pipeline_mode = "routed-full" if context_result.get("used") else "routed-basic"
    pipeline = {
        "mode": pipeline_mode,
        "request": request_lifecycle,
        "context_status": context_result.get("status", "unknown"),
        "context_used": bool(context_result.get("used")),
        "context_source": context_result.get("source", ""),
        "context_error": context_result.get("error", ""),
        "context_latency_ms": context_result.get("latency_ms", 0),
        # FTS5 search metadata (loud failures)
        "search_strategy": context_result.get("search_strategy", ""),
        "search_degraded": bool(context_result.get("search_degraded", False)),
        "search_suggestions": context_result.get("search_suggestions", []),
        # Encoding metadata (for telemetry — NOT applied to prompt yet)
        "glyph_encoding_status": encoding_result.get("status", "skipped"),
        "glyph_encoding_used": bool(encoding_result.get("used")),
        "raw_context_chars": encoding_result.get("raw_context_chars", 0),
        "encoded_context_chars": encoding_result.get("encoded_context_chars", 0),
        "estimated_token_delta": encoding_result.get("estimated_token_delta", 0),
        "encoding_ratio": encoding_result.get("encoding_ratio", 1.0),
        "glyph_encoding_error": encoding_result.get("error", ""),
        "glyph_encoding_latency_ms": encoding_result.get("latency_ms", 0),
        # ContextPayload carried to router for encoding-aware decisions
        "context_payload_raw": raw_ctx,
        "context_payload_encoded": encoding_result.get("encoded_context", ""),
        "context_payload_encoding_status": encoding_result.get("status", "none"),
        "context_payload_encoding_format": "",
        "context_payload_encoding_ratio": encoding_result.get("encoding_ratio", 1.0),
        **assembly,
    }
    return assembled_prompt, pipeline


def _normalize_cloud_provider(raw: str) -> str:
    provider = str(raw or "").strip().lower()
    if provider in {"openai", "anthropic", "xai"}:
        return provider
    return ""


def _parse_cloud_fallback_order(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list | tuple):
        values = list(raw)
    else:
        values = str(raw).split(",")
    providers: list[str] = []
    for value in values:
        provider = _normalize_cloud_provider(str(value))
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "y"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "n"}:
        return False
    return default


def _load_glyphos_config() -> dict[str, Any]:
    from glyphos_ai.ai_compute.api_client import _load_glyphos_config as integration_load_config  # type: ignore

    return integration_load_config()


def _cloud_routing_config() -> tuple[list[str], str]:
    config = _load_glyphos_config()
    cloud_root = config.get("ai_compute", {}).get("cloud", {}) if isinstance(config, dict) else {}
    preferred_raw = os.environ.get("GLYPHOS_CLOUD_PREFERRED", "").strip()
    if not preferred_raw and isinstance(config, dict):
        preferred_raw = (
            str(config.get("ai_compute", {}).get("cloud", {}).get("preferred_cloud", "")).strip()
            if isinstance(cloud_root, dict)
            else ""
        )
    if not preferred_raw and isinstance(config, dict):
        preferred_raw = (
            str(config.get("ai_compute", {}).get("cloud", {}).get("preferred_provider", "")).strip()
            if isinstance(cloud_root, dict)
            else ""
        )
    preferred_cloud = (
        _normalize_cloud_provider(preferred_raw)
        or _normalize_cloud_provider(os.environ.get("GLYPHOS_CLOUD_PREFERRED_PROVIDER", ""))
        or "xai"
    )

    fallback_order = os.environ.get("GLYPHOS_CLOUD_FALLBACK_ORDER", "").strip()
    if not fallback_order and isinstance(config, dict):
        cloud_root = config.get("ai_compute", {}).get("cloud", {})
        fallback_order = cloud_root.get("fallback_order", "") if isinstance(cloud_root, dict) else ""
    return (
        _parse_cloud_fallback_order(fallback_order),
        preferred_cloud,
    )


def _provider_status(enabled: bool, configured: bool, client: Any, reason: str) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "configured": bool(configured),
        "available": bool(client is not None),
        "model": getattr(client, "model", ""),
        "max_tokens": getattr(client, "max_tokens", 0),
        "reason": reason,
    }


def _get_cloud_provider_status() -> dict[str, Any]:
    status = {"xai": {}, "openai": {}, "anthropic": {}}
    try:
        from glyphos_ai.ai_compute.api_client import (
            _load_glyphos_config as integration_load_config,  # type: ignore
        )
        from glyphos_ai.ai_compute.api_client import (
            create_configured_clients,  # type: ignore
        )
    except Exception:
        return status

    try:
        clients = create_configured_clients()
    except Exception:
        clients = {}
    config = integration_load_config()
    cloud_root = config.get("ai_compute", {}).get("cloud", {}) if isinstance(config, dict) else {}
    cloud_root_enabled = _coerce_bool(cloud_root.get("enabled"), default=True)

    for provider in ("xai", "openai", "anthropic"):
        provider_key = provider.upper()
        cfg_provider = (
            config.get("ai_compute", {}).get(provider, {}) if isinstance(config.get("ai_compute", {}), dict) else {}
        )
        cfg_enabled = cfg_provider.get("enabled", "true") if isinstance(cfg_provider, dict) else "true"
        enabled = _coerce_bool(
            os.environ.get(f"GLYPHOS_CLOUD_{provider_key}_ENABLED"),
            default=_coerce_bool(cfg_enabled, default=True),
        )
        if not cloud_root_enabled:
            enabled = False
        api_key = os.environ.get(f"GLYPHOS_CLOUD_{provider_key}_API_KEY") or os.environ.get(
            f"{provider_key}_API_KEY", ""
        )
        if not api_key and isinstance(cfg_provider, dict):
            api_key = cfg_provider.get("api_key", "")
        configured = bool(enabled and str(api_key).strip())
        client = clients.get(provider) if isinstance(clients, dict) else None
        if client is not None:
            reason = "ready"
        elif not enabled:
            reason = "disabled"
        elif not configured:
            reason = "api_key_missing"
        else:
            reason = "not_available"
        status[provider] = _provider_status(enabled=enabled, configured=configured, client=client, reason=reason)

    return status


def create_router():
    from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore
    from glyphos_ai.ai_compute.router import AdaptiveRouter, RoutingConfig  # type: ignore

    clients = create_configured_clients()
    cloud_fallback_order, preferred_cloud = _cloud_routing_config()
    return AdaptiveRouter(
        llamacpp_client=clients.get("llamacpp"),
        openai_client=clients.get("openai"),
        anthropic_client=clients.get("anthropic"),
        xai_client=clients.get("xai"),
        config=RoutingConfig(cloud_fallback_order=cloud_fallback_order, preferred_cloud=preferred_cloud),
    )


def route_prompt(
    prompt: str, model: str, max_tokens: int, temperature: float, context_payload=None
) -> tuple[dict[str, Any], dict[str, str]]:
    from glyphos_ai.glyph.types import GlyphPacket  # type: ignore

    packet = GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
        encoding_status=context_payload.encoding_status if context_payload else "none",
        encoding_format=context_payload.encoding_format if context_payload else "",
        encoding_ratio=context_payload.encoding_ratio if context_payload else 1.0,
    )
    start = time.perf_counter()
    router = create_router()
    result = router.route(
        packet,
        prompt=prompt,
        context_payload=context_payload,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency_ms = round((time.perf_counter() - start) * 1000)
    if result.target.value == "fallback" or str(result.routing_reason_code).endswith(".error"):
        raise GatewayError(f"{result.target.value} route failed: {result.response}", target=result.target.value)
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": result.target.value,
        "X-LMM-GlyphOS-Reason": result.routing_reason_code,
        "X-LMM-Encoding-Status": packet.encoding_status,
        "X-LMM-Encoding-Format": packet.encoding_format,
        "X-LMM-Route-Target": result.target.value,
    }
    return {
        "text": result.response,
        "target": result.target.value,
        "reason_code": result.routing_reason_code,
        "reason": result.routing_reason,
        "latency_ms": latency_ms,
    }, headers


def route_prompt_stream(
    prompt: str, model: str, max_tokens: int, temperature: float, context_payload=None
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    from glyphos_ai.glyph.types import GlyphPacket  # type: ignore

    packet = GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
        encoding_status=context_payload.encoding_status if context_payload else "none",
        encoding_format=context_payload.encoding_format if context_payload else "",
        encoding_ratio=context_payload.encoding_ratio if context_payload else 1.0,
    )
    router = create_router()
    routed, chunks = router.route_stream(
        packet,
        prompt=prompt,
        context_payload=context_payload,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": str(routed["target"]),
        "X-LMM-GlyphOS-Reason": str(routed["reason_code"]),
        "X-LMM-Encoding-Status": packet.encoding_status,
        "X-LMM-Encoding-Format": packet.encoding_format,
        "X-LMM-Route-Target": str(routed["target"]),
    }
    return routed, headers, chunks


def _invoke_route_prompt(
    *,
    route_fn,
    prompt: str,
    fallback_prompt: str | None = None,
    model: str,
    max_tokens: int,
    temperature: float,
    context_payload: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Invoke a route prompt callable with backward-compatible args.

    Older tests patch this function with 4-arg callables.
    Keep new context-aware behavior when supported and gracefully fallback.
    """

    try:
        return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)
    except TypeError as exc:
        message = str(exc)
        if "context_payload" in message:
            return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
        raise


def _invoke_route_prompt_stream(
    *,
    route_fn,
    prompt: str,
    fallback_prompt: str | None = None,
    model: str,
    max_tokens: int,
    temperature: float,
    context_payload: Any,
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    """Invoke a streaming route callable with backward-compatible args."""

    try:
        return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)
    except TypeError as exc:
        message = str(exc)
        if "context_payload" in message:
            return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
        raise


def _fallback_prompt_for_legacy_route(prompt: str, pipeline: dict[str, Any], context_payload: Any) -> str:
    """Reconstruct the context-enriched prompt for legacy 4-arg route callbacks."""

    if not bool(pipeline.get("context_used", False)):
        return prompt

    context_text = str(getattr(context_payload, "raw_context", ""))
    if not context_text.strip():
        return prompt

    encoding_status = str(getattr(context_payload, "encoding_status", pipeline.get("glyph_encoding_status", "")))
    encoded_context = str(getattr(context_payload, "encoded_context", ""))
    encoding = {
        "used": encoding_status.lower() == "encoded" and bool(encoded_context),
        "encoded_context": encoded_context,
    }
    rebuilt_prompt, _ = assemble_prompt(prompt, {"context": context_text}, encoding)
    return rebuilt_prompt


def completion_payload(
    *,
    started: float,
    model: str,
    routed: dict[str, Any],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-lmm-{int(started * 1000)}",
        "object": "chat.completion",
        "created": int(started),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": routed["text"]},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "lmm": {
            "route_mode": pipeline.get("mode", "routed-basic"),
            "context_status": pipeline.get("context_status", "unknown"),
            "context_used": bool(pipeline.get("context_used")),
            "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
            "glyph_encoding_used": bool(pipeline.get("glyph_encoding_used")),
            "raw_context_chars": pipeline.get("raw_context_chars", 0),
            "encoded_context_chars": pipeline.get("encoded_context_chars", 0),
            "estimated_token_delta": pipeline.get("estimated_token_delta", 0),
            "encoding_ratio": pipeline.get("encoding_ratio", 1.0),
            "assembly_status": pipeline.get("assembly_status", "raw_prompt"),
            "glyphos_target": routed["target"],
            "glyphos_reason_code": routed["reason_code"],
            "glyphos_reason": routed["reason"],
            "latency_ms": routed["latency_ms"],
            "encoding_aware_routing": True,
        },
    }


def sse_event(payload: dict[str, Any] | str) -> bytes:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"data: {data}\n\n".encode()


def sse_comment(comment: str) -> bytes:
    safe = comment.replace("\n", " ").replace("\r", " ").strip() or "keepalive"
    return f": {safe}\n\n".encode()


def stream_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
    heartbeat_seconds: float | None = None,
) -> tuple[str, bool, str, int]:
    collected: list[str] = []
    iterator = iter(chunks)
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop_event = threading.Event()
    model_short = model.split("/")[-1] if "/" in model else model
    base = {
        "id": f"chatcmpl-lmm-{int(started * 1000)}",
        "object": "chat.completion.chunk",
        "created": int(started),
        "model": model,
    }

    if heartbeat_seconds is None:
        heartbeat_seconds = load_lmm_config_from_env().gateway.sse_heartbeat_seconds
    heartbeat_seconds = max(0.01, heartbeat_seconds)

    def pump_chunks() -> None:
        try:
            for item in iterator:
                if stop_event.is_set():
                    break
                events.put(("chunk", item))
            events.put(("done", None))
        except Exception as exc:
            events.put(("error", exc))

    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "close")
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(
            sse_event({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
        )
        handler.wfile.flush()

        worker = threading.Thread(target=pump_chunks, name="lmm-gateway-stream-pump", daemon=True)
        worker.start()

        while True:
            try:
                event_type, value = events.get(timeout=heartbeat_seconds)
            except queue.Empty:
                handler.wfile.write(sse_comment("lmm-keepalive"))
                handler.wfile.flush()
                continue

            if event_type == "done":
                break
            if event_type == "error":
                raise RuntimeError(str(value))

            chunk = value
            if not chunk:
                continue
            collected.append(str(chunk))
            handler.wfile.write(
                sse_event({**base, "choices": [{"index": 0, "delta": {"content": str(chunk)}, "finish_reason": None}]})
            )
            handler.wfile.flush()

        handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}))
        handler.wfile.write(sse_event("[DONE]"))
        handler.wfile.flush()
        latency_ms = round((now() - started) * 1000)
        if latency_ms > 30000:
            mgr = notification_manager()
            if mgr:
                mgr.notify(
                    f"LMM: {model_short} completed",
                    f"Run finished in {latency_ms // 1000}s",
                    NotificationType.RUN_COMPLETED,
                )
        return "".join(collected), True, "", latency_ms
    except (BrokenPipeError, ConnectionResetError) as exc:
        stop_event.set()
        latency_ms = round((now() - started) * 1000)
        mgr = notification_manager()
        if mgr:
            mgr.notify(
                "LMM: Client disconnected",
                "Run cancelled by client",
                NotificationType.CLIENT_DISCONNECTED,
            )
        return "".join(collected), False, f"client disconnected: {exc}", latency_ms
    except Exception as exc:
        stop_event.set()
        error_message = str(exc)
        latency_ms = round((now() - started) * 1000)
        mgr = notification_manager()
        if mgr:
            mgr.notify(
                f"LMM: {model_short} failed",
                f"Error: {error_message[:100]}",
                NotificationType.RUN_FAILED,
            )
        try:
            handler.wfile.write(sse_event({"error": {"message": error_message, "type": "lmm_gateway_error"}}))
            handler.wfile.write(sse_event("[DONE]"))
            handler.wfile.flush()
        except Exception:
            pass
        return "".join(collected), False, error_message, latency_ms


class LMMOpenAIGateway:
    def __init__(self, *, backend_base_url: str, model_id: str = "") -> None:
        self.backend_base_url = backend_base_url.rstrip("/")
        self.model_id = model_id
        self._health = HealthChecker(backend_url=backend_base_url, config=load_lmm_config_from_env())

    def health(self) -> dict[str, Any]:
        fallback_order, preferred_cloud = _cloud_routing_config()
        return {
            "ok": True,
            "service": "lmm-glyphos-openai-gateway",
            "cloud_routing": {
                "preferred_cloud": preferred_cloud,
                "fallback_order": fallback_order,
            },
            "cloud_providers": _get_cloud_provider_status(),
        }

    def list_models(self) -> tuple[int, dict[str, Any]]:
        try:
            return http_json("GET", f"{self.backend_base_url}/models", timeout=5)
        except Exception as exc:
            model = self.model_id or "local-llama"
            return 200, {
                "object": "list",
                "data": [{"id": model, "object": "model", "owned_by": "lmm"}],
                "warning": str(exc),
            }

    def telemetry(self) -> dict[str, Any]:
        return load_gateway_state()

    @property
    def health_checker(self) -> HealthChecker:
        return self._health

    def health_check(self) -> dict[str, ComponentHealth]:
        return self.health_checker.check_all()


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "LMMGlyphOSGateway/1.0"

    def gateway(self) -> LMMOpenAIGateway:
        existing = getattr(self.server, "gateway", None)
        if isinstance(existing, LMMOpenAIGateway):
            return existing
        backend_base_url = getattr(self.server, "backend_base_url", "http://127.0.0.1:8081/v1")
        model_id = getattr(self.server, "model_id", "")
        return LMMOpenAIGateway(backend_base_url=str(backend_base_url), model_id=str(model_id))

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/healthz", "/v1", "/v1/health"}:
            json_response(self, 200, self.gateway().health())
            return
        if path in {"/v1/messages", "/v1/message"}:
            json_response(
                self,
                200,
                {
                    "service": "lmm-glyphos-anthropic-gateway",
                    "status": "ok",
                    "format": "anthropic",
                    "endpoints": {
                        "messages": "/v1/messages",
                        "count_tokens": "/v1/messages/count_tokens",
                    },
                },
            )
            return
        if path == "/readyz":
            checker = self.gateway().health_checker
            if checker.is_ready():
                json_response(self, 200, {"status": "ready"})
            else:
                components = {name: item.to_dict() for name, item in checker.check_all().items()}
                json_response(self, 503, {"status": "not_ready", "components": components})
            return
        if path == "/-/runtime/report":
            json_response(self, 200, self.gateway().health_checker.get_runtime_report().to_dict())
            return
        if path == "/v1/models":
            status, payload = self.gateway().list_models()
            json_response(self, status, payload)
            return
        if path == "/v1/telemetry":
            json_response(self, 200, self.gateway().telemetry())
            return
        if path == "/v1/updates":
            checker = getattr(self.server, "update_checker", None)
            if checker is None:
                json_response(
                    self,
                    200,
                    {
                        "enabled": False,
                        "message": "Update watcher is disabled",
                    },
                )
                return
            try:
                raw_state = checker.state_store.read_state()
            except Exception as exc:
                raw_state = {"error": str(exc)}
            if not isinstance(raw_state, dict):
                raw_state = {}
            payload = dict(raw_state)
            payload["enabled"] = True
            json_response(self, 200, payload)
            return
        json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        # Anthropic /v1/messages/count_tokens — token counting endpoint
        if path == "/v1/messages/count_tokens":
            started = now()
            try:
                payload = read_json(self)
                text = anthropic_messages_to_text(payload.get("messages", []), payload.get("system"))
                # Try backend tokenization; fall back to word-count approximation
                backend_base_url = getattr(self.server, "backend_base_url", "http://127.0.0.1:8081/v1")
                try:
                    status_code, token_data = http_json(
                        "POST", f"{backend_base_url}/tokenize", {"content": text}, timeout=5
                    )
                    if isinstance(token_data.get("tokens"), list):
                        token_count = len(token_data["tokens"])
                    elif isinstance(token_data.get("count"), int):
                        token_count = token_data["count"]
                    else:
                        token_count = max(1, len(text.split())) if text.strip() else 0
                except Exception:
                    token_count = max(1, len(text.split())) if text.strip() else 0
                json_response(self, 200, {"input_tokens": token_count})
            except InvalidRequestError as exc:
                json_response(self, 400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            except Exception as exc:
                json_response(self, 500, {"error": {"message": str(exc), "type": "internal_error"}})
            return

        # Anthropic /v1/messages — non-streaming only (streaming in Plan 02)
        if path == "/v1/messages":
            started = now()
            try:
                payload = read_json(self)
                if payload.get("stream") is True:
                    json_response(
                        self,
                        400,
                        {"error": {"message": "streaming not yet supported", "type": "invalid_request_error"}},
                    )
                    return
                prompt = anthropic_messages_to_text(payload.get("messages", []), payload.get("system"))
                if not prompt.strip():
                    raise InvalidRequestError("messages must contain text content")
                model = str(payload.get("model") or self.server.model_id or "claude-3")
                max_tokens = request_int(payload, "max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768")))
                temperature = request_float(payload, "temperature", 0.7)
                stream = False

                # Build telemetry record with Anthropic format marker
                record: dict[str, Any] = {
                    "time": started,
                    "started_at": _current_iso_timestamp(),
                    "harness": self.headers.get("User-Agent", "unknown"),
                    "mode": "routed-basic",
                    "format": "anthropic",
                    "context_status": "unknown",
                    "context_used": False,
                    "glyph_encoding_status": "skipped",
                    "glyph_encoding_used": False,
                    "route_target": "unknown",
                    "reason_code": "unresolved",
                    "success": False,
                    "fallback_mode": "",
                    "latency_ms": 0,
                    "status": RunStatus.RUNNING.value,
                    "exit_result": None,
                    "provider": "unknown",
                    "prompt": prompt,
                    "model": model,
                }

                assembled_prompt, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream)

                # Build ContextPayload for encoding-aware routing
                context_payload = _build_context_payload(
                    raw_context=pipeline.get("context_payload_raw", ""),
                    raw_context_chars=pipeline.get("raw_context_chars", 0),
                    encoding_status=pipeline.get("context_payload_encoding_status", "none"),
                    encoded_context=pipeline.get("context_payload_encoded", ""),
                    encoding_format=pipeline.get("context_payload_encoding_format", ""),
                    encoding_ratio=pipeline.get("context_payload_encoding_ratio", 1.0),
                )

                record.update(
                    {
                        "mode": pipeline.get("mode", "routed-basic"),
                        "context_status": pipeline.get("context_status", "unknown"),
                        "context_used": bool(pipeline.get("context_used")),
                        "context_source": pipeline.get("context_source", ""),
                        "context_error": pipeline.get("context_error", ""),
                        "context_latency_ms": pipeline.get("context_latency_ms", 0),
                        "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
                        "glyph_encoding_used": bool(pipeline.get("glyph_encoding_used")),
                        "raw_context_chars": pipeline.get("raw_context_chars", 0),
                        "encoded_context_chars": pipeline.get("encoded_context_chars", 0),
                        "estimated_token_delta": pipeline.get("estimated_token_delta", 0),
                        "encoding_ratio": pipeline.get("encoding_ratio", 1.0),
                        "assembly_status": pipeline.get("assembly_status", "raw_prompt"),
                        "assembled_prompt_chars": pipeline.get("assembled_prompt_chars", 0),
                        "context_block_chars": pipeline.get("context_block_chars", 0),
                        "request": pipeline.get("request", {}),
                    }
                )

                routed, headers = _invoke_route_prompt(
                    route_fn=route_prompt,
                    prompt=assembled_prompt,
                    fallback_prompt=_fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    context_payload=context_payload,
                )

                record.update(
                    {
                        "route_target": routed["target"],
                        "reason_code": routed["reason_code"],
                        "success": True,
                        "latency_ms": routed["latency_ms"],
                        "provider": routed["target"],
                        "status": RunStatus.COMPLETED.value,
                        "exit_result": ExitResult.SUCCESS.value,
                        "completed_at": _current_iso_timestamp(),
                    }
                )

                response = build_anthropic_response(
                    text=routed["text"],
                    model=model,
                    started=started,
                    routed=routed,
                    pipeline=pipeline,
                )

                safe_record_gateway_request(record)
                json_response(self, 200, response)
            except InvalidRequestError as exc:
                json_response(self, 400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            except GatewayError as exc:
                json_response(self, 502, {"error": {"message": str(exc), "type": "gateway_error"}})
            except Exception as exc:
                json_response(self, 500, {"error": {"message": str(exc), "type": "internal_error"}})
            return

        # OpenAI /v1/chat/completions — existing handler (unchanged)
        if path != "/v1/chat/completions":
            json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})
            return
        started = now()
        context_state, context_used = context_status()
        record: dict[str, Any] = {
            "time": started,
            "started_at": _current_iso_timestamp(),
            "harness": self.headers.get("User-Agent", "unknown"),
            "mode": "routed-basic",
            "context_status": context_state,
            "context_used": context_used,
            "glyph_encoding_status": "skipped",
            "glyph_encoding_used": False,
            "route_target": "unknown",
            "reason_code": "unresolved",
            "success": False,
            "fallback_mode": "",
            "latency_ms": 0,
            "status": RunStatus.RUNNING.value,
            "exit_result": None,
            "provider": "unknown",
            "prompt": "",
            "model": "",
        }
        try:
            payload = read_json(self)
            prompt = messages_to_prompt(payload.get("messages"))
            model = str(payload.get("model") or self.server.model_id or "local-llama")  # type: ignore[attr-defined]
            record["prompt"] = prompt
            record["model"] = model
            # Phase 06: Extract session metadata for handoff tracking
            session_meta = _extract_session_metadata(payload)
            if session_meta:
                record.update(session_meta)
            max_tokens = request_int(payload, "max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768")))
            temperature = request_float(payload, "temperature", 0.7)
            stream = payload.get("stream") is True
            if not prompt.strip():
                raise InvalidRequestError("messages must contain text content")
            assembled_prompt, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream)
            pipeline_request = pipeline.get("request")
            if isinstance(pipeline_request, dict):
                pipeline_request["harness_identity"] = record["harness"]

            # Build ContextPayload for encoding-aware routing
            context_payload = _build_context_payload(
                raw_context=pipeline.get("context_payload_raw", ""),
                raw_context_chars=pipeline.get("raw_context_chars", 0),
                encoding_status=pipeline.get("context_payload_encoding_status", "none"),
                encoded_context=pipeline.get("context_payload_encoded", ""),
                encoding_format=pipeline.get("context_payload_encoding_format", ""),
                encoding_ratio=pipeline.get("context_payload_encoding_ratio", 1.0),
            )

            record.update(
                {
                    "mode": pipeline.get("mode", "routed-basic"),
                    "context_status": pipeline.get("context_status", context_state),
                    "context_used": bool(pipeline.get("context_used")),
                    "context_source": pipeline.get("context_source", ""),
                    "context_error": pipeline.get("context_error", ""),
                    "context_latency_ms": pipeline.get("context_latency_ms", 0),
                    # FTS5 search metadata (loud failures)
                    "search_strategy": pipeline.get("search_strategy", ""),
                    "search_degraded": bool(pipeline.get("search_degraded", False)),
                    # Encoding metadata (for telemetry — NOT applied to prompt yet)
                    "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
                    "glyph_encoding_used": bool(pipeline.get("glyph_encoding_used")),
                    "raw_context_chars": pipeline.get("raw_context_chars", 0),
                    "encoded_context_chars": pipeline.get("encoded_context_chars", 0),
                    "estimated_token_delta": pipeline.get("estimated_token_delta", 0),
                    "encoding_ratio": pipeline.get("encoding_ratio", 1.0),
                    "glyph_encoding_error": pipeline.get("glyph_encoding_error", ""),
                    "assembly_status": pipeline.get("assembly_status", "raw_prompt"),
                    "assembled_prompt_chars": pipeline.get("assembled_prompt_chars", 0),
                    "context_block_chars": pipeline.get("context_block_chars", 0),
                    "request": pipeline_request if isinstance(pipeline_request, dict) else {},
                }
            )
            if stream:
                routed, headers, chunks = _invoke_route_prompt_stream(
                    route_fn=route_prompt_stream,
                    prompt=assembled_prompt,
                    fallback_prompt=_fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    context_payload=context_payload,
                )
                headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
                headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
                headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
                headers["X-LMM-Search-Strategy"] = str(pipeline.get("search_strategy", ""))
                headers["X-LMM-Search-Degraded"] = str(bool(pipeline.get("search_degraded", False)))
                record.update(
                    {
                        "route_target": routed["target"],
                        "reason_code": routed["reason_code"],
                        "encoding_status": context_payload.encoding_status,
                        "encoding_format": context_payload.encoding_format,
                        "encoding_ratio": context_payload.encoding_ratio,
                        "encoding_aware_routing": True,
                    }
                )
                text, success, error_message, latency_ms = stream_completion(
                    self,
                    started=started,
                    model=model,
                    chunks=chunks,
                    headers=headers,
                )
                record.update(
                    {
                        "success": success,
                        "latency_ms": latency_ms,
                        "completion_chars": len(text),
                        "completed_at": _current_iso_timestamp(),
                    }
                )
                if error_message:
                    record["error"] = error_message
                if not success:
                    record["status"] = RunStatus.CANCELLED.value
                    record["exit_result"] = ExitResult.USER_CANCELLED.value
                    record["provider"] = record["route_target"]
                else:
                    record["status"] = RunStatus.COMPLETED.value
                    record["exit_result"] = ExitResult.SUCCESS.value
                    record["provider"] = record["route_target"]
                # Phase 06: Generate handoff summary for long runs
                _generate_handoff_summary(record, record.get("latency_ms", 0))
                safe_record_run_record(_run_record_from_dict(record))
                safe_record_gateway_request(record)
                return
            routed, headers = _invoke_route_prompt(
                route_fn=route_prompt,
                prompt=assembled_prompt,
                fallback_prompt=_fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                context_payload=context_payload,
            )
            headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
            headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
            headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
            headers["X-LMM-Search-Strategy"] = str(pipeline.get("search_strategy", ""))
            headers["X-LMM-Search-Degraded"] = str(bool(pipeline.get("search_degraded", False)))
            record.update(
                {
                    "route_target": routed["target"],
                    "reason_code": routed["reason_code"],
                    "success": True,
                    "latency_ms": routed["latency_ms"],
                    "provider": routed["target"],
                    "status": RunStatus.COMPLETED.value,
                    "exit_result": ExitResult.SUCCESS.value,
                    "completed_at": _current_iso_timestamp(),
                    "encoding_status": context_payload.encoding_status,
                    "encoding_format": context_payload.encoding_format,
                    "encoding_ratio": context_payload.encoding_ratio,
                    "encoding_aware_routing": True,
                }
            )
            response_payload = completion_payload(
                started=started,
                model=model,
                routed=routed,
                pipeline=pipeline,
            )
            # Phase 06: Generate handoff summary for long runs
            _generate_handoff_summary(record, routed.get("latency_ms", 0))
            safe_record_run_record(_run_record_from_dict(record))
            safe_record_gateway_request(record)
            json_response(self, 200, response_payload, headers=headers)
        except InvalidRequestError as exc:
            record["error"] = str(exc)
            record["status"] = RunStatus.FAILED.value
            record["exit_result"] = ExitResult.ERROR.value
            record["latency_ms"] = round((now() - started) * 1000)
            record["completed_at"] = _current_iso_timestamp()
            _generate_handoff_summary(record, record["latency_ms"])
            safe_record_gateway_request(record)
            safe_record_run_record(_run_record_from_dict(record))
            json_response(
                self,
                400,
                {"error": {"message": str(exc), "type": "invalid_request_error"}, "lmm": record},
            )
        except Exception as exc:
            record["error"] = str(exc)
            record["status"] = RunStatus.FAILED.value
            record["exit_result"] = ExitResult.PROVIDER_ERROR.value
            record["latency_ms"] = round((now() - started) * 1000)
            record["completed_at"] = _current_iso_timestamp()
            _generate_handoff_summary(record, record["latency_ms"])
            safe_record_gateway_request(record)
            safe_record_run_record(_run_record_from_dict(record))
            error_payload = (
                exc.to_dict() if isinstance(exc, GatewayError) else {"message": str(exc), "type": "lmm_gateway_error"}
            )
            json_response(self, 503, {"error": error_payload, "lmm": record})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write(f"{self.log_date_time_string()} - {format % args}\n")


def create_gateway_server(
    host: str = "127.0.0.1",
    port: int = 4010,
    backend_base_url: str = "http://127.0.0.1:8081/v1",
    model_id: str = "",
    watcher_config: object | None = None,
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer for the LMM OpenAI gateway.

    Returns a server with ``GatewayHandler`` and the following attributes:
    - ``server.backend_base_url`` (str)
    - ``server.model_id`` (str)
    - ``server.gateway`` (LMMOpenAIGateway)
    """
    config = load_lmm_config_from_env()
    if watcher_config is None:
        watcher_config = config.update_watcher
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    server.backend_base_url = backend_base_url  # type: ignore[attr-defined]
    server.model_id = model_id  # type: ignore[attr-defined]
    server.gateway = LMMOpenAIGateway(backend_base_url=backend_base_url, model_id=model_id)  # type: ignore[attr-defined]
    server.health_checker = server.gateway.health_checker  # type: ignore[attr-defined]

    if getattr(watcher_config, "enabled", False):
        start_update_watcher(
            server,
            watcher_config=watcher_config,
        )
    return server


def start_update_watcher(
    server: ThreadingHTTPServer,
    *,
    watcher_config: Any,
) -> None:
    current_version = os.environ.get("LMM_VERSION", "v2.1.0")
    checker = UpdateChecker(
        current_lmm_version=current_version,
        lmm_repo=watcher_config.lmm_repo,
        llamacpp_repo=watcher_config.llamacpp_repo,
        timeout=watcher_config.timeout_seconds,
        state_file=watcher_config.state_file,
    )
    server.update_checker = checker  # type: ignore[attr-defined]
    interval_seconds = int(watcher_config.check_interval_hours) * 3600
    if interval_seconds < 60:
        interval_seconds = 60

    def periodic_check() -> None:
        try:
            lmm_result = checker.check_lmm_update()
            llamacpp_result = checker.check_llamacpp_update()
        except Exception:
            lmm_result = None
            llamacpp_result = None

        manager = create_notification_manager(True)
        if manager is not None:
            if lmm_result and lmm_result.update_available:
                manager.notify(
                    "LMM update available",
                    f"Current: {lmm_result.current_version}. Latest: {lmm_result.latest_version}.",
                    NotificationType.UPDATE_AVAILABLE,
                )
            if llamacpp_result and llamacpp_result.update_available:
                manager.notify(
                    "llama.cpp update available",
                    f"Current: {llamacpp_result.current_version}. Latest: {llamacpp_result.latest_version}.",
                    NotificationType.UPDATE_AVAILABLE,
                )

        timer = threading.Timer(interval_seconds, periodic_check)
        timer.daemon = True
        server.update_timer = timer  # type: ignore[attr-defined]
        timer.start()

    initial_timer = threading.Timer(0, periodic_check)
    initial_timer.daemon = True
    server.update_timer = initial_timer  # type: ignore[attr-defined]
    initial_timer.start()


def main(argv: list[str]) -> int:
    config = load_lmm_config_from_env().gateway
    parser = argparse.ArgumentParser(description="LMM OpenAI-compatible gateway through GlyphOS AI Compute")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    parser.add_argument("--backend-base-url", default=config.backend_base_url)
    parser.add_argument("--model-id", default=config.model_id)
    args = parser.parse_args(argv)

    server = create_gateway_server(
        host=args.host,
        port=args.port,
        backend_base_url=args.backend_base_url,
        model_id=args.model_id,
    )
    print(f"LMM GlyphOS gateway listening on http://{args.host}:{args.port}/v1 -> {args.backend_base_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
