#!/usr/bin/env python3
"""
scripts/gateway_server.py
"""

from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gateway.handlers_anthropic import handle_messages, handle_messages_count_tokens
from gateway.handlers_openai import handle_chat_completions
from gateway.health_runtime import GatewayRuntime, maybe_start_update_watcher
from gateway.http_utils import json_response


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "LMMGlyphOSGateway/2.0"

    def gateway_runtime(self) -> GatewayRuntime:
        existing = getattr(self.server, "gateway_runtime", None)
        if isinstance(existing, GatewayRuntime):
            return existing
        backend_base_url = getattr(self.server, "backend_base_url", "http://127.0.0.1:8081/v1")
        model_id = getattr(self.server, "model_id", "")
        return GatewayRuntime(backend_base_url=str(backend_base_url), model_id=str(model_id))

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        runtime = self.gateway_runtime()

        if path in {"/healthz", "/v1", "/v1/health"}:
            json_response(self, 200, runtime.health_payload())
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
            checker = runtime.health_checker
            if checker.is_ready():
                json_response(self, 200, {"status": "ready"})
            else:
                components = {name: item.to_dict() for name, item in checker.check_all().items()}
                json_response(self, 503, {"status": "not_ready", "components": components})
            return

        if path == "/-/runtime/report":
            json_response(self, 200, runtime.health_checker.get_runtime_report().to_dict())
            return

        json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/v1/messages/count_tokens":
            handle_messages_count_tokens(self, getattr(self.server, "backend_base_url", "http://127.0.0.1:8081/v1"))
            return

        if path == "/v1/messages":
            handle_messages(self)
            return

        if path == "/v1/chat/completions":
            handle_chat_completions(self)
            return

        json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})

    def log_message(self, format: str, *args):  # noqa: A003
        sys.stderr.write(f"{self.log_date_time_string()} - {format % args}\n")


def create_gateway_server(
    host: str = "127.0.0.1",
    port: int = 4010,
    backend_base_url: str = "http://127.0.0.1:8081/v1",
    model_id: str = "",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    server.backend_base_url = backend_base_url  # type: ignore[attr-defined]
    server.model_id = model_id  # type: ignore[attr-defined]
    server.gateway_runtime = GatewayRuntime(backend_base_url=backend_base_url, model_id=model_id)  # type: ignore[attr-defined]
    maybe_start_update_watcher(server)
    return server


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="LMM OpenAI/Anthropic-compatible gateway through GlyphOS AI Compute")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4010)
    parser.add_argument(
        "--backend-base-url", default=os.environ.get("LLAMA_MODEL_BACKEND_BASE_URL", "http://127.0.0.1:8081/v1")
    )
    parser.add_argument("--model-id", default="")
    args = parser.parse_args(argv)

    server = create_gateway_server(
        host=args.host,
        port=args.port,
        backend_base_url=args.backend_base_url,
        model_id=args.model_id,
    )
    print(f"LMM GlyphOS gateway listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
