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
    from gateway.protocol_normalizers import compact_json
    from gateway.protocol_normalizers import _normalize_tool_call as _detect_tool_call
except ImportError:
    compact_json = None
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


def _payload_declares_tools(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("tools", "functions"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    return bool(payload.get("tool_choice") or payload.get("function_call"))


def _openai_tool_call_delta(tool_call: dict[str, Any]) -> dict[str, Any]:
    arguments = tool_call.get("arguments")
    if compact_json:
        argument_text = compact_json(arguments if isinstance(arguments, dict) else {"value": arguments})
    else:
        argument_text = json.dumps(arguments if isinstance(arguments, dict) else {"value": arguments}, separators=(",", ":"))
    return {
        "tool_calls": [
            {
                "index": 0,
                "id": str(tool_call.get("id") or "call_lmm_stream"),
                "type": "function",
                "function": {
                    "name": str(tool_call.get("name", "")),
                    "arguments": argument_text,
                },
            }
        ]
    }


def _close_iterator(iterator: Iterator[str]) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        try:
            close()
        except (OSError, RuntimeError):
            pass


def _stop_stream_worker(stop_event: threading.Event, worker: threading.Thread | None, iterator: Iterator[str]) -> None:
    stop_event.set()
    _close_iterator(iterator)
    if worker is not None and worker.is_alive():
        worker.join(timeout=1)


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
) -> tuple[str, bool, str, int, dict[str, Any] | None]:
    _detect_tool = _detect_tool_call if payload is not None else None
    hold_for_tool_detection = bool(_detect_tool and _payload_declares_tools(payload))
    collected: list[str] = []
    iterator = iter(chunks)
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop_event = threading.Event()
    worker: threading.Thread | None = None
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
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
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

        worker = threading.Thread(target=pump_chunks, name="lmm-gateway-stream-pump")
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
                if isinstance(value, BaseException):
                    raise RuntimeError(f"{value.__class__.__name__}: {value}") from value
                raise RuntimeError(str(value))

            chunk = value
            if not chunk:
                continue
            collected.append(str(chunk))
            if not hold_for_tool_detection:
                handler.wfile.write(
                    sse_event(
                        {**base, "choices": [{"index": 0, "delta": {"content": str(chunk)}, "finish_reason": None}]}
                    )
                )
                handler.wfile.flush()

        full_text = "".join(collected)
        detected_call = _detect_tool(full_text, payload) if _detect_tool else None
        finish_reason = "stop"
        tool_call_info: dict[str, Any] | None = None
        if detected_call:
            finish_reason = "tool_calls"
            tool_call_info = {
                "detected": True,
                "name": str(detected_call.get("name", "")),
                "mode": str(detected_call.get("mode", "structured")),
            }
            handler.wfile.write(
                sse_event({**base, "choices": [{"index": 0, "delta": _openai_tool_call_delta(detected_call), "finish_reason": None}]})
            )
            handler.wfile.flush()
        elif hold_for_tool_detection and full_text:
            handler.wfile.write(
                sse_event({**base, "choices": [{"index": 0, "delta": {"content": full_text}, "finish_reason": None}]})
            )
            handler.wfile.flush()

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
        return "".join(collected), True, "", latency_ms, tool_call_info

    except (BrokenPipeError, ConnectionResetError) as exc:
        _stop_stream_worker(stop_event, worker, iterator)
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
        if mgr:
            mgr.notify(
                "LMM: Client disconnected",
                "Run cancelled by client",
                NotificationType.CLIENT_DISCONNECTED,
            )
        return "".join(collected), False, f"client disconnected: {exc}", latency_ms, None

    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
        _stop_stream_worker(stop_event, worker, iterator)
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
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        return "".join(collected), False, error_message, latency_ms, None


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
) -> tuple[str, bool, str, int, dict[str, Any] | None]:
    _detect_tool = _detect_tool_call if payload is not None else None
    collected: list[str] = []
    iterator = iter(chunks)
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop_event = threading.Event()
    worker: threading.Thread | None = None
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
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
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

        worker = threading.Thread(target=pump_chunks, name="lmm-anthropic-stream-pump")
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
                if isinstance(value, BaseException):
                    raise RuntimeError(f"{value.__class__.__name__}: {value}") from value
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
        detected_call = _detect_tool(full_text, payload) if _detect_tool else None
        stop_reason = "end_turn"
        tool_call_info: dict[str, Any] | None = None
        if detected_call:
            stop_reason = "tool_use"
            tool_call_info = {
                "detected": True,
                "name": str(detected_call.get("name", "")),
                "mode": str(detected_call.get("mode", "structured")),
            }
            # End the text content block
            handler.wfile.write(anthropic_sse_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
            # Start the tool_use content block with id and name
            handler.wfile.write(anthropic_sse_event("content_block_start", {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": str(detected_call.get("id", f"toolu_{int(started * 1000)}")),
                    "name": str(detected_call.get("name", "")),
                },
            }))
            # Stream the input as JSON delta
            handler.wfile.write(anthropic_sse_event("content_block_delta", {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(detected_call.get("arguments", {})),
                },
            }))
            # End the tool_use content block
            handler.wfile.write(anthropic_sse_event("content_block_stop", {"type": "content_block_stop", "index": 1}))
        else:
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
        return "".join(collected), True, "", latency_ms, tool_call_info

    except (BrokenPipeError, ConnectionResetError) as exc:
        _stop_stream_worker(stop_event, worker, iterator)
        latency_ms = round(((time_fn or time.time)() - started) * 1000)
        mgr = (notification_manager_factory or _notification_manager)()
        if mgr:
            mgr.notify(
                "LMM: Client disconnected",
                "Run cancelled by client",
                NotificationType.CLIENT_DISCONNECTED,
            )
        return "".join(collected), False, f"client disconnected: {exc}", latency_ms, None

    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
        _stop_stream_worker(stop_event, worker, iterator)
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
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        return "".join(collected), False, error_message, latency_ms, None


__all__ = [
    "sse_event",
    "sse_comment",
    "anthropic_sse_event",
    "stream_completion",
    "stream_anthropic_completion",
]
