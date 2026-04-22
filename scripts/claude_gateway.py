#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class UpstreamClient:
    def __init__(self, upstream_base: str) -> None:
        self.base = upstream_base.rstrip("/")

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=600) as response:
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
    def __init__(self, upstream_base: str, advertised_model_id: str = "") -> None:
        self.upstream = UpstreamClient(upstream_base)
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
        if isinstance(payload.get("temperature"), (int, float)):
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
        return {
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
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def write_sse_comment(self, text: str = "keepalive") -> None:
        self.wfile.write(f": {text}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream_messages(self, payload: dict[str, Any]) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        message_id = f"msg_{int(time.time() * 1000)}"
        self.write_sse_event("message_start", {
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
        })

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.gateway.message, payload)
            while True:
                try:
                    message = future.result(timeout=5)
                    break
                except concurrent.futures.TimeoutError:
                    self.write_sse_comment()

        self.write_sse_event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        text = message["content"][0]["text"] if message.get("content") else ""
        if text:
            self.write_sse_event("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            })
        self.write_sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
        self.write_sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": message.get("usage", {"input_tokens": 0, "output_tokens": 0}),
        })
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
    parser.add_argument("--advertised-model-id", default="")
    args = parser.parse_args(argv)

    handler = type("GatewayHandlerImpl", (GatewayHandler,), {})
    handler.gateway = ClaudeGateway(args.upstream_base, args.advertised_model_id)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
