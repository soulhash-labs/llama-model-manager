#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from gateway.protocol_normalizers import (  # noqa: E402
    append_tool_contract_to_prompt,
    apply_anthropic_tool_use_response,
    classify_tool_invocation,
    compact_json,
)


class UpstreamClient:
    def __init__(self, upstream_base: str, request_timeout_seconds: int = 1800) -> None:
        self.base = upstream_base.rstrip("/")
        self.request_timeout_seconds = max(1, int(request_timeout_seconds))

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"upstream {path} failed: HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"upstream {path} failed: {exc.reason}") from exc

        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError(f"upstream {path} returned non-object JSON")
        return data

    def list_models(self) -> list[dict[str, Any]]:
        data = self._json("GET", "/models")
        models = data.get("data")
        if not isinstance(models, list):
            return []
        return [item for item in models if isinstance(item, dict)]

    def resolve_model_name(self) -> str:
        for item in self.list_models():
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                return model_id.strip()
        return "local-llama"

    def tokenize(self, text: str) -> int:
        data = self._json("POST", "/tokenize", {"content": text})
        if isinstance(data.get("tokens"), list):
            return len(data["tokens"])
        if isinstance(data.get("count"), int):
            return int(data["count"])
        return max(1, len(text.split())) if text.strip() else 0

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/chat/completions", payload)


class ClaudeGateway:
    def __init__(self, upstream_base: str, upstream_timeout_seconds: int = 1800, advertised_model_id: str = "") -> None:
        self.upstream = UpstreamClient(upstream_base, request_timeout_seconds=upstream_timeout_seconds)
        self.advertised_model_id = advertised_model_id.strip()

    def exposed_model_name(self) -> str:
        if self.advertised_model_id:
            return self.advertised_model_id
        return self.upstream.resolve_model_name()

    def health(self) -> dict[str, str]:
        return {"status": "ok", "model": self.exposed_model_name()}

    def list_models(self) -> dict[str, Any]:
        model_id = self.exposed_model_name()
        return {
            "data": [
                {
                    "id": model_id,
                    "type": "model",
                    "display_name": model_id,
                }
            ]
        }

    def count_tokens(self, payload: dict[str, Any]) -> dict[str, int]:
        text = self._messages_to_text(payload)
        return {"input_tokens": self.upstream.tokenize(text)}

    def _normalize_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif isinstance(item, dict) and item.get("type") == "tool_use":
                    parts.append("tool_use: " + compact_json(item))
                elif isinstance(item, dict) and item.get("type") == "tool_result":
                    tool_id = str(item.get("tool_use_id", "")).strip()
                    tool_content = item.get("content", "")
                    if isinstance(tool_content, list):
                        tool_text = "\n".join(
                            str(part.get("text", ""))
                            for part in tool_content
                            if isinstance(part, dict) and part.get("type") == "text"
                        )
                    else:
                        tool_text = str(tool_content)
                    parts.append(f"tool_result {tool_id}: {tool_text}".strip())
            return "\n".join(part for part in parts if part)
        return ""

    def _messages_to_text(self, payload: dict[str, Any]) -> str:
        parts: list[str] = []
        system = payload.get("system")
        system_text = self._normalize_content(system)
        if system_text:
            parts.append(system_text)
        for item in payload.get("messages", []):
            if not isinstance(item, dict):
                continue
            content = self._normalize_content(item.get("content"))
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def _messages_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        system_text = self._normalize_content(payload.get("system"))
        system_text = append_tool_contract_to_prompt(system_text, payload, protocol="anthropic-messages")
        if system_text:
            messages.append({"role": "system", "content": system_text})
        for item in payload.get("messages", []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "user"))
            content = self._normalize_content(item.get("content"))
            messages.append({"role": role, "content": content})
        request = {
            "model": self.upstream.resolve_model_name(),
            "messages": messages,
            "stream": False,
        }
        if isinstance(payload.get("max_tokens"), int):
            request["max_tokens"] = payload["max_tokens"]
        if isinstance(payload.get("temperature"), int | float):
            request["temperature"] = payload["temperature"]
        return request

    def message(self, payload: dict[str, Any]) -> dict[str, Any]:
        upstream = self.upstream.chat(self._messages_payload(payload))
        choices = upstream.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("upstream chat response did not include choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("upstream chat response choice was invalid")
        message = first.get("message")
        text = ""
        if isinstance(message, dict):
            text = str(message.get("content", ""))
        usage = upstream.get("usage") if isinstance(upstream.get("usage"), dict) else {}
        response = {
            "id": f"msg_{int(time.time() * 1000)}",
            "type": "message",
            "role": "assistant",
            "model": self.exposed_model_name(),
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(usage.get("completion_tokens", 0) or 0),
            },
        }
        response = apply_anthropic_tool_use_response(response, text, payload)
        tool_report = classify_tool_invocation(text, payload)
        response["lmm"] = {
            "tool_invocation_mode": tool_report["tool_invocation_mode"],
            "tool_name": tool_report["tool_name"],
            "repair_attempted": tool_report["repair_attempted"],
            "repair_succeeded": tool_report["repair_succeeded"],
        }
        return response


class GatewayHandler(BaseHTTPRequestHandler):
    gateway: ClaudeGateway

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("", "/", "/healthz", "/v1", "/v1/models"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("", "/", "/v1"):
            self.send_json(self.gateway.health())
            return
        if parsed.path == "/healthz":
            self.send_json(self.gateway.health())
            return
        if parsed.path == "/v1/models":
            self.send_json(self.gateway.list_models())
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def write_sse_event(self, event: str, payload: dict[str, Any]) -> None:
        self.wfile.write(f"event: {event}\n".encode())
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def write_sse_comment(self, text: str = "keepalive") -> None:
        self.wfile.write(f": {text}\n\n".encode())
        self.wfile.flush()

    def _stream_messages(self, payload: dict[str, Any]) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        message_id = f"msg_{int(time.time() * 1000)}"
        self.write_sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self.gateway.exposed_model_name(),
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.gateway.message, payload)
            while True:
                try:
                    message = future.result(timeout=5)
                    break
                except concurrent.futures.TimeoutError:
                    self.write_sse_comment()

        content = message.get("content") if isinstance(message.get("content"), list) else []
        first_block = content[0] if content and isinstance(content[0], dict) else {"type": "text", "text": ""}
        if first_block.get("type") == "tool_use":
            self.write_sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": first_block.get("id", f"toolu_{int(time.time() * 1000)}"),
                        "name": first_block.get("name", ""),
                        "input": {},
                    },
                },
            )
            self.write_sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(first_block.get("input", {}), ensure_ascii=True),
                    },
                },
            )
        else:
            self.write_sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
            text = str(first_block.get("text", ""))
            if text:
                self.write_sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
        self.write_sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
        self.write_sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": message.get("stop_reason", "end_turn")},
                "usage": message.get("usage", {"input_tokens": 0, "output_tokens": 0}),
            },
        )
        self.write_sse_event("message_stop", {"type": "message_stop"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/v1/messages/count_tokens":
                self.send_json(self.gateway.count_tokens(payload))
                return
            if parsed.path == "/v1/messages":
                if payload.get("stream") is True:
                    self._stream_messages(payload)
                else:
                    self.send_json(self.gateway.message(payload))
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        except Exception as exc:  # pragma: no cover
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Anthropic-style gateway for a local llama.cpp server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--upstream-base", required=True)
    parser.add_argument("--upstream-timeout-seconds", type=int, default=1800)
    parser.add_argument("--advertised-model-id", default="")
    args = parser.parse_args(argv)

    handler = type("GatewayHandlerImpl", (GatewayHandler,), {})
    handler.gateway = ClaudeGateway(
        args.upstream_base,
        upstream_timeout_seconds=args.upstream_timeout_seconds,
        advertised_model_id=args.advertised_model_id,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        f"Claude gateway listening on http://{args.host}:{args.port} -> {args.upstream_base} (timeout={args.upstream_timeout_seconds}s)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
