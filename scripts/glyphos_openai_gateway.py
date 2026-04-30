#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shlex
import sys
import subprocess
import time
from typing import Any, Iterator
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


APP_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = APP_ROOT / "integrations" / "public-glyphos-ai-compute"
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))


def now() -> float:
    return time.time()


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(raw)


class InvalidRequestError(ValueError):
    pass


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


def http_json(method: str, url: str, *, payload: dict[str, Any] | None = None, timeout: int = 5) -> tuple[int, dict[str, Any]]:
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


def state_file() -> Path:
    configured = os.environ.get("LMM_GATEWAY_STATE_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
    return state_home / "llama-server" / "lmm-gateway-requests.json"


def load_gateway_state() -> dict[str, Any]:
    path = state_file()
    if not path.exists():
        return {"recent_requests": [], "counters": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"recent_requests": [], "counters": {}}
    return payload if isinstance(payload, dict) else {"recent_requests": [], "counters": {}}


def save_gateway_state(payload: dict[str, Any]) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


@contextmanager
def gateway_state_lock():
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_gateway_request(record: dict[str, Any]) -> None:
    with gateway_state_lock():
        state = load_gateway_state()
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
        del recent[40:]
        state["counters"] = counters
        state["recent_requests"] = recent
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_gateway_state(state)


def safe_record_gateway_request(record: dict[str, Any]) -> None:
    try:
        record_gateway_request(record)
    except Exception as exc:
        sys.stderr.write(f"warning: failed to persist LMM gateway telemetry: {exc}\n")


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
    return os.environ.get("LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE", "").strip().lower() in {"1", "true", "yes", "on"}


def context_mcp_root() -> Path:
    return APP_ROOT / "integrations" / "context-mode-mcp"


def context_status() -> tuple[str, bool]:
    enabled = context_pipeline_enabled()
    if not enabled:
        return "disabled", False
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        return "missing", False
    return "available_no_context", False


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
        candidates.extend([
            metadata.get("lmm_context"),
            metadata.get("retrieved_context"),
            metadata.get("context"),
        ])
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
        if parsed.get(key):
            return parsed[key]
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
    return parsed


def retrieve_context(payload: dict[str, Any], prompt: str, *, model: str, stream: bool) -> dict[str, Any]:
    enabled = os.environ.get("LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE", "").strip().lower() in {"1", "true", "yes", "on"}
    started = time.perf_counter()
    result: dict[str, Any] = {
        "status": "disabled",
        "used": False,
        "context": "",
        "source": "",
        "error": "",
        "latency_ms": 0,
    }
    if not enabled:
        return result
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        result.update({"status": "missing"})
        return result

    payload_context = extract_payload_context(payload)
    if payload_context:
        text = context_to_text(payload_context)
        result.update({
            "status": "retrieved_from_payload",
            "used": bool(text),
            "context": text,
            "source": "payload",
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        return result

    command = os.environ.get("LMM_CONTEXT_MCP_COMMAND", "").strip()
    if not command:
        result.update({
            "status": "available_no_context",
            "source": "context-mode-mcp",
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
        return result

    timeout_ms = request_int({"timeout": os.environ.get("LMM_CONTEXT_MCP_TIMEOUT_MS", "1500")}, "timeout", 1500)
    request_payload = {
        "tool": "ctx_search",
        "query": prompt[-4000:],
        "limit": 8,
        "model": model,
        "stream": stream,
        "messages": payload.get("messages", []),
        "metadata": payload.get("metadata", {}),
    }
    try:
        completed = subprocess.run(
            shlex.split(command),
            input=compact_json(request_payload),
            text=True,
            capture_output=True,
            timeout=timeout_ms / 1000,
            cwd=str(root),
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or f"exit {completed.returncode}"
            result.update({"status": "error", "source": "context-mode-mcp", "error": stderr[:400]})
            return result
        text = context_to_text(command_context_from_output(completed.stdout))
        result.update({
            "status": "retrieved" if text else "empty",
            "used": bool(text),
            "context": text,
            "source": "context-mode-mcp",
        })
        return result
    except subprocess.TimeoutExpired:
        result.update({"status": "timeout", "source": "context-mode-mcp", "error": f"timeout after {timeout_ms}ms"})
        return result
    except Exception as exc:
        result.update({"status": "error", "source": "context-mode-mcp", "error": str(exc)[:400]})
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
        if os.environ.get("LMM_GLYPH_ENCODING_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
            result["status"] = "disabled"
            return result
        if os.environ.get("LMM_GLYPH_ENCODING_FORCE_ERROR", "").strip():
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
            result.update({
                "status": "raw_not_smaller",
                "encoded_context_chars": encoded_chars,
                "encoding_ratio": round(encoded_chars / raw_chars, 4) if raw_chars else 1.0,
            })
            return result
        result.update({
            "status": "encoded",
            "used": True,
            "encoded_context_chars": encoded_chars,
            "estimated_token_delta": round((raw_chars - encoded_chars) / 4),
            "encoding_ratio": round(encoded_chars / raw_chars, 4),
            "encoded_context": encoded,
        })
        return result
    except Exception as exc:
        result.update({"status": "error_raw_fallback", "error": str(exc)[:400]})
        return result
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)


def assemble_prompt(raw_prompt: str, context_result: dict[str, Any], encoding_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    context = str(context_result.get("context") or "").strip()
    if not context:
        return raw_prompt, {
            "assembly_status": "raw_prompt",
            "assembled_prompt_chars": len(raw_prompt),
            "context_block_chars": 0,
        }
    if encoding_result.get("used"):
        context_block = "\n".join([
            "[Glyph Encoding v1]",
            "Decode this compact context before reasoning. Key aliases: p=path, f=file, t=title, u=uri, c=content, x=text, s=snippet, m=summary, r=score.",
            str(encoding_result.get("encoded_context", "")),
        ])
        assembly_status = "glyph_encoded_context"
    else:
        context_block = "\n".join([
            "[Retrieved Context]",
            context,
        ])
        assembly_status = "raw_context"
    assembled = "\n\n".join([
        "System: Use retrieved context only as supporting evidence. The latest user instruction below overrides retrieved or encoded context.",
        context_block,
        "[Conversation and latest user request]",
        raw_prompt,
    ])
    return assembled, {
        "assembly_status": assembly_status,
        "assembled_prompt_chars": len(assembled),
        "context_block_chars": len(context_block),
    }


def prepare_gateway_pipeline(payload: dict[str, Any], raw_prompt: str, *, model: str, stream: bool) -> tuple[str, dict[str, Any]]:
    request_lifecycle = {
        "raw_messages": payload.get("messages", []),
        "model": model,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 1000),
        "stream": stream,
        "harness_identity": "",
        "workspace": payload.get("workspace") or (payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}).get("workspace", ""),
        "session": payload.get("session") or (payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}).get("session", ""),
    }
    context_result = retrieve_context(payload, raw_prompt, model=model, stream=stream)
    encoding_result = glyph_encode_context(str(context_result.get("context") or "")) if context_result.get("used") else glyph_encode_context("")
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
        raise RuntimeError(f"{result.target.value} route failed: {result.response}")
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


def route_prompt_stream(prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
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
    routed, chunks = router.route_stream(packet, prompt=prompt, model=model, max_tokens=max_tokens, temperature=temperature)
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
    return f"data: {data}\n\n".encode("utf-8")


def stream_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
) -> tuple[str, bool, str, int]:
    collected: list[str] = []
    iterator = iter(chunks)
    try:
        first_chunk = next(iterator)
    except StopIteration:
        first_chunk = ""
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    base = {
        "id": f"chatcmpl-lmm-{int(started * 1000)}",
        "object": "chat.completion.chunk",
        "created": int(started),
        "model": model,
    }
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "close")
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}))
        handler.wfile.flush()
        for chunk in ([first_chunk] if first_chunk else []):
            collected.append(str(chunk))
            handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {"content": str(chunk)}, "finish_reason": None}]}))
            handler.wfile.flush()
        for chunk in iterator:
            if not chunk:
                continue
            collected.append(str(chunk))
            handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {"content": str(chunk)}, "finish_reason": None}]}))
            handler.wfile.flush()
        handler.wfile.write(sse_event({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}))
        handler.wfile.write(sse_event("[DONE]"))
        handler.wfile.flush()
        return "".join(collected), True, "", round((now() - started) * 1000)
    except (BrokenPipeError, ConnectionResetError) as exc:
        return "".join(collected), False, f"client disconnected: {exc}", round((now() - started) * 1000)
    except Exception as exc:
        error_message = str(exc)
        try:
            handler.wfile.write(sse_event({"error": {"message": error_message, "type": "lmm_gateway_error"}}))
            handler.wfile.write(sse_event("[DONE]"))
            handler.wfile.flush()
        except Exception:
            pass
        return "".join(collected), False, error_message, round((now() - started) * 1000)


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "LMMGlyphOSGateway/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/healthz", "/v1", "/v1/health"}:
            json_response(self, 200, {"ok": True, "service": "lmm-glyphos-openai-gateway"})
            return
        if path == "/v1/models":
            try:
                status, payload = http_json("GET", f"{self.server.backend_base_url.rstrip('/')}/models", timeout=5)  # type: ignore[attr-defined]
                json_response(self, status, payload)
            except Exception as exc:
                model = self.server.model_id or "local-llama"  # type: ignore[attr-defined]
                json_response(self, 200, {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "lmm"}], "warning": str(exc)})
            return
        if path == "/v1/telemetry":
            json_response(self, 200, load_gateway_state())
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
        }
        try:
            payload = read_json(self)
            prompt = messages_to_prompt(payload.get("messages"))
            model = str(payload.get("model") or self.server.model_id or "local-llama")  # type: ignore[attr-defined]
            max_tokens = request_int(payload, "max_tokens", 1000)
            temperature = request_float(payload, "temperature", 0.7)
            stream = payload.get("stream") is True
            if not prompt.strip():
                raise InvalidRequestError("messages must contain text content")
            assembled_prompt, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream)
            pipeline_request = pipeline.get("request")
            if isinstance(pipeline_request, dict):
                pipeline_request["harness_identity"] = record["harness"]
            record.update({
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
            })
            if stream:
                routed, headers, chunks = route_prompt_stream(assembled_prompt, model, max_tokens, temperature)
                headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
                headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
                headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
                record.update({
                    "route_target": routed["target"],
                    "reason_code": routed["reason_code"],
                })
                text, success, error_message, latency_ms = stream_completion(
                    self,
                    started=started,
                    model=model,
                    chunks=chunks,
                    headers=headers,
                )
                record.update({
                    "success": success,
                    "latency_ms": latency_ms,
                    "completion_chars": len(text),
                })
                if error_message:
                    record["error"] = error_message
                safe_record_gateway_request(record)
                return
            routed, headers = route_prompt(assembled_prompt, model, max_tokens, temperature)
            headers["X-LMM-Route-Mode"] = str(pipeline.get("mode", "routed-basic"))
            headers["X-LMM-Context-Status"] = str(pipeline.get("context_status", "unknown"))
            headers["X-LMM-Glyph-Encoding"] = str(pipeline.get("glyph_encoding_status", "skipped"))
            record.update({
                "route_target": routed["target"],
                "reason_code": routed["reason_code"],
                "success": True,
                "latency_ms": routed["latency_ms"],
            })
            response_payload = completion_payload(
                started=started,
                model=model,
                routed=routed,
                pipeline=pipeline,
            )
            safe_record_gateway_request(record)
            json_response(self, 200, response_payload, headers=headers)
        except InvalidRequestError as exc:
            record["error"] = str(exc)
            record["latency_ms"] = round((now() - started) * 1000)
            safe_record_gateway_request(record)
            json_response(
                self,
                400,
                {"error": {"message": str(exc), "type": "invalid_request_error"}, "lmm": record},
            )
        except Exception as exc:
            record["error"] = str(exc)
            record["latency_ms"] = round((now() - started) * 1000)
            safe_record_gateway_request(record)
            json_response(self, 503, {"error": {"message": str(exc), "type": "lmm_gateway_error"}, "lmm": record})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="LMM OpenAI-compatible gateway through GlyphOS AI Compute")
    parser.add_argument("--host", default=os.environ.get("LLAMA_MODEL_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LLAMA_MODEL_GATEWAY_PORT", "4010")))
    parser.add_argument("--backend-base-url", default=os.environ.get("LLAMA_MODEL_BACKEND_BASE_URL", "http://127.0.0.1:8081/v1"))
    parser.add_argument("--model-id", default=os.environ.get("LLAMA_MODEL_GATEWAY_MODEL_ID", ""))
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    server.backend_base_url = args.backend_base_url  # type: ignore[attr-defined]
    server.model_id = args.model_id  # type: ignore[attr-defined]
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
