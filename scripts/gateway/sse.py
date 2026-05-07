from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from typing import Any

from lmm_config import load_lmm_config_from_env
from lmm_notifications import NotificationType, create_notification_manager

try:
    from gateway.protocol_normalizers import _normalize_tool_call as _detect_tool_call
except Exception:
    _detect_tool_call = None


def _notification_manager():
    enabled = os.environ.get("LMM_NOTIFICATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
    return create_notification_manager(enabled=enabled)


def sse_event(payload: dict[str, Any] | str) -> bytes:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"data: {data}\n\n".encode()


def sse_comment(comment: str) -> bytes:
    safe = comment.replace("\n", " ").replace("\r", " ").strip() or "keepalive"
    return f": {safe}\n\n".encode()


def anthropic_sse_event(event_type: str, payload: dict[str, Any]) -> bytes:
    safe_type = str(event_type).replace("\n", " ").replace("\r", " ").strip()
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"event: {safe_type}\ndata: {data}\n\n".encode()


def stream_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
    heartbeat_seconds: float | None = None,
    notification_manager_factory=None,
    time_fn=None,
    payload: dict[str, Any] | None = None,
) -> tuple[str, bool, str, int]:
    _detect_tool = _detect_tool_call if payload is not None else None
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
        handler.wfile.write(sse_comment("lmm-stream-open"))
        handler.wfile.flush()
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

        full_text = "".join(collected)
        finish_reason = "stop"
        if _detect_tool and _detect_tool(full_text, payload):
            finish_reason = "tool_calls"

        handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}))
        handler.wfile.write(sse_event("[DONE]"))
        handler.wfile.flush()

        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        if latency_ms > 30000:
            mgr = (notification_manager_factory or _notification_manager)()
            if mgr:
                mgr.notify(
                    f"LMM: {model_short} completed",
                    f"Run finished in {latency_ms // 1000}s",
                    NotificationType.RUN_COMPLETED,
                )
        return "".join(collected), True, "", latency_ms

    except (BrokenPipeError, ConnectionResetError) as exc:
        stop_event.set()
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
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
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
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


def stream_anthropic_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
    heartbeat_seconds: float | None = None,
    notification_manager_factory=None,
    time_fn=None,
    payload: dict[str, Any] | None = None,
) -> tuple[str, bool, str, int]:
    _detect_tool = _detect_tool_call if payload is not None else None
    collected: list[str] = []
    iterator = iter(chunks)
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop_event = threading.Event()
    model_short = model.split("/")[-1] if "/" in model else model
    message_id = f"msg_{int(started * 1000)}"

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
        handler.wfile.write(sse_comment("lmm-stream-open"))
        handler.wfile.flush()

        handler.wfile.write(
            anthropic_sse_event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        )
        handler.wfile.write(
            anthropic_sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        )
        handler.wfile.flush()

        worker = threading.Thread(target=pump_chunks, name="lmm-anthropic-stream-pump", daemon=True)
        worker.start()

        output_tokens = 0
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
            output_tokens += max(1, len(str(chunk).split()))

            handler.wfile.write(
                anthropic_sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": str(chunk)},
                    },
                )
            )
            handler.wfile.flush()

        full_text = "".join(collected)
        stop_reason = "end_turn"
        if _detect_tool and _detect_tool(full_text, payload):
            stop_reason = "tool_use"

        handler.wfile.write(anthropic_sse_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
        handler.wfile.write(
            anthropic_sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason},
                    "usage": {"input_tokens": 0, "output_tokens": output_tokens},
                },
            )
        )
        handler.wfile.write(anthropic_sse_event("message_stop", {"type": "message_stop"}))
        handler.wfile.flush()

        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        if latency_ms > 30000:
            mgr = (notification_manager_factory or _notification_manager)()
            if mgr:
                mgr.notify(
                    f"LMM: {model_short} completed",
                    f"Run finished in {latency_ms // 1000}s",
                    NotificationType.RUN_COMPLETED,
                )
        return "".join(collected), True, "", latency_ms

    except (BrokenPipeError, ConnectionResetError) as exc:
        stop_event.set()
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
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
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
        if mgr:
            mgr.notify(
                f"LMM: {model_short} failed",
                f"Error: {error_message[:100]}",
                NotificationType.RUN_FAILED,
            )
        try:
            handler.wfile.write(anthropic_sse_event("message_stop", {"type": "message_stop"}))
            handler.wfile.flush()
        except Exception:
            pass
        return "".join(collected), False, error_message, latency_ms


__all__ = [
    "sse_event",
    "sse_comment",
    "anthropic_sse_event",
    "stream_completion",
    "stream_anthropic_completion",
]
