#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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

from lmm_config import load_lmm_config_from_env  # noqa: E402
from lmm_errors import GatewayError, InvalidRequestError  # noqa: E402
from lmm_health import ComponentHealth, HealthChecker  # noqa: E402
from lmm_notifications import NotificationType, create_notification_manager  # noqa: E402
from lmm_storage import JsonGatewayTelemetryStore, JsonRunRecordStore  # noqa: E402
from lmm_types import ExitResult, RunRecord, RunStatus  # noqa: E402


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
        duration_ms=record.get("duration_ms") if isinstance(record.get("duration_ms"), int) else None,
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


def context_pipeline_enabled() -> bool:
    return load_lmm_config_from_env().context.enabled


def context_mcp_root() -> Path:
    return APP_ROOT / "integrations" / "context-mode-mcp"


def context_mcp_bridge_path() -> Path:
    return APP_ROOT / "scripts" / "context_mcp_bridge.py"


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


def command_context_from_output(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return parsed
    for key in ("retrieved_context", "context", "text", "markdown"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, list) and value:
            return value
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
        return "\n".join(pieces)
    return ""


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
    }
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
        text = context_to_text(command_context_from_output(completed.stdout))
        result.update(
            {
                "status": "retrieved" if text else "empty",
                "used": bool(text),
                "context": text,
                "source": "context-mode-mcp",
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
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    request_lifecycle = {
        "messages": message_summary(payload.get("messages", [])),
        "model": model,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 1000),
        "stream": stream,
        "harness_identity": "",
        "workspace_present": bool(payload.get("workspace") or metadata.get("workspace")),
        "session_present": bool(payload.get("session") or metadata.get("session")),
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
    }
    context_result = retrieve_context(payload, raw_prompt, model=model, stream=stream)
    encoding_result = (
        glyph_encode_context(str(context_result.get("context") or ""))
        if context_result.get("used")
        else glyph_encode_context("")
    )
    assembled_prompt, assembly = assemble_prompt(raw_prompt, context_result, encoding_result)
    pipeline_mode = "routed-full" if context_result.get("used") else "routed-basic"
    pipeline = {
        "mode": pipeline_mode,
        "request": request_lifecycle,
        "context_status": context_result.get("status", "unknown"),
        "context_used": bool(context_result.get("used")),
        "context_source": context_result.get("source", ""),
        "context_error": context_result.get("error", ""),
        "context_latency_ms": context_result.get("latency_ms", 0),
        "glyph_encoding_status": encoding_result.get("status", "skipped"),
        "glyph_encoding_used": bool(encoding_result.get("used")),
        "raw_context_chars": encoding_result.get("raw_context_chars", 0),
        "encoded_context_chars": encoding_result.get("encoded_context_chars", 0),
        "estimated_token_delta": encoding_result.get("estimated_token_delta", 0),
        "encoding_ratio": encoding_result.get("encoding_ratio", 1.0),
        "glyph_encoding_error": encoding_result.get("error", ""),
        "glyph_encoding_latency_ms": encoding_result.get("latency_ms", 0),
        **assembly,
    }
    return assembled_prompt, pipeline


def create_router():
    from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore
    from glyphos_ai.ai_compute.router import AdaptiveRouter  # type: ignore

    clients = create_configured_clients()
    return AdaptiveRouter(
        llamacpp_client=clients.get("llamacpp"),
        openai_client=clients.get("openai"),
        anthropic_client=clients.get("anthropic"),
        xai_client=clients.get("xai"),
    )


def route_prompt(prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[dict[str, Any], dict[str, str]]:
    from glyphos_ai.glyph.types import GlyphPacket  # type: ignore

    packet = GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
    )
    start = time.perf_counter()
    router = create_router()
    result = router.route(packet, prompt=prompt, model=model, max_tokens=max_tokens, temperature=temperature)
    latency_ms = round((time.perf_counter() - start) * 1000)
    if result.target.value == "fallback" or str(result.routing_reason_code).endswith(".error"):
        raise GatewayError(f"{result.target.value} route failed: {result.response}", target=result.target.value)
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": result.target.value,
        "X-LMM-GlyphOS-Reason": result.routing_reason_code,
    }
    return {
        "text": result.response,
        "target": result.target.value,
        "reason_code": result.routing_reason_code,
        "reason": result.routing_reason,
        "latency_ms": latency_ms,
    }, headers


def route_prompt_stream(
    prompt: str, model: str, max_tokens: int, temperature: float
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    from glyphos_ai.glyph.types import GlyphPacket  # type: ignore

    packet = GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
    )
    router = create_router()
    routed, chunks = router.route_stream(
        packet, prompt=prompt, model=model, max_tokens=max_tokens, temperature=temperature
    )
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": str(routed["target"]),
        "X-LMM-GlyphOS-Reason": str(routed["reason_code"]),
    }
    return routed, headers, chunks


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
        return {"ok": True, "service": "lmm-glyphos-openai-gateway"}

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
        json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
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
            max_tokens = request_int(payload, "max_tokens", 1000)
            temperature = request_float(payload, "temperature", 0.7)
            stream = payload.get("stream") is True
            if not prompt.strip():
                raise InvalidRequestError("messages must contain text content")
            assembled_prompt, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream)
            pipeline_request = pipeline.get("request")
            if isinstance(pipeline_request, dict):
                pipeline_request["harness_identity"] = record["harness"]
            record.update(
                {
                    "mode": pipeline.get("mode", "routed-basic"),
                    "context_status": pipeline.get("context_status", context_state),
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
                    "glyph_encoding_error": pipeline.get("glyph_encoding_error", ""),
                    "assembly_status": pipeline.get("assembly_status", "raw_prompt"),
                    "assembled_prompt_chars": pipeline.get("assembled_prompt_chars", 0),
                    "context_block_chars": pipeline.get("context_block_chars", 0),
                    "request": pipeline_request if isinstance(pipeline_request, dict) else {},
                }
            )
            if stream:
                routed, headers, chunks = route_prompt_stream(assembled_prompt, model, max_tokens, temperature)
                headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
                headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
                headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
                record.update(
                    {
                        "route_target": routed["target"],
                        "reason_code": routed["reason_code"],
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
                safe_record_run_record(_run_record_from_dict(record))
                safe_record_gateway_request(record)
                return
            routed, headers = route_prompt(assembled_prompt, model, max_tokens, temperature)
            headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
            headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
            headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
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
            response_payload = completion_payload(
                started=started,
                model=model,
                routed=routed,
                pipeline=pipeline,
            )
            safe_record_run_record(_run_record_from_dict(record))
            safe_record_gateway_request(record)
            json_response(self, 200, response_payload, headers=headers)
        except InvalidRequestError as exc:
            record["error"] = str(exc)
            record["status"] = RunStatus.FAILED.value
            record["exit_result"] = ExitResult.ERROR.value
            record["latency_ms"] = round((now() - started) * 1000)
            record["completed_at"] = _current_iso_timestamp()
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
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer for the LMM OpenAI gateway.

    Returns a server with ``GatewayHandler`` and the following attributes:
    - ``server.backend_base_url`` (str)
    - ``server.model_id`` (str)
    - ``server.gateway`` (LMMOpenAIGateway)
    """
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    server.backend_base_url = backend_base_url  # type: ignore[attr-defined]
    server.model_id = model_id  # type: ignore[attr-defined]
    server.gateway = LMMOpenAIGateway(backend_base_url=backend_base_url, model_id=model_id)  # type: ignore[attr-defined]
    server.health_checker = server.gateway.health_checker  # type: ignore[attr-defined]
    return server


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
