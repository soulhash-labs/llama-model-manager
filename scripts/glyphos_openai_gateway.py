#!/usr/bin/env python3
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
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


def read_json(handler: BaseHTTPRequestHandler, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    length_text = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_text)
    except ValueError as exc:
        raise ValueError("invalid Content-Length") from exc
    if length < 0 or length > max_bytes:
        raise ValueError("request body too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("request JSON must be an object")
    return payload


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


def record_gateway_request(record: dict[str, Any]) -> None:
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


def context_status() -> tuple[str, bool]:
    enabled = os.environ.get("LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return "disabled", False
    root = APP_ROOT / "integrations" / "context-mode-mcp"
    if not (root / "package.json").is_file():
        return "missing", False
    return "available_not_invoked", False


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
    result = router.route(packet, prompt=prompt)
    latency_ms = round((time.perf_counter() - start) * 1000)
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
            "mode": "routed",
            "context_status": context_state,
            "context_used": context_used,
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
            max_tokens = int(payload.get("max_tokens") or 1000)
            temperature = float(payload.get("temperature") or 0.7)
            if not prompt.strip():
                raise ValueError("messages must contain text content")
            routed, headers = route_prompt(prompt, model, max_tokens, temperature)
            record.update({
                "route_target": routed["target"],
                "reason_code": routed["reason_code"],
                "success": True,
                "latency_ms": routed["latency_ms"],
            })
            response_payload = {
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
                    "route_mode": "routed",
                    "context_status": context_state,
                    "context_used": context_used,
                    "glyphos_target": routed["target"],
                    "glyphos_reason_code": routed["reason_code"],
                    "glyphos_reason": routed["reason"],
                    "latency_ms": routed["latency_ms"],
                },
            }
            record_gateway_request(record)
            json_response(self, 200, response_payload, headers=headers)
        except Exception as exc:
            record["error"] = str(exc)
            record["latency_ms"] = round((now() - started) * 1000)
            record_gateway_request(record)
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
