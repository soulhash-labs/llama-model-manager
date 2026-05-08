#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import os
import signal  # noqa: F401 - compatibility export for timeout tests/operators
import subprocess
import sys
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
INTEGRATION_ROOT = APP_ROOT / "integrations" / "public-glyphos-ai-compute"
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))

from gateway import context_provider as _context_provider  # noqa: E402
from gateway.context_provider import assemble_prompt as _context_assemble_prompt  # noqa: E402
from gateway.context_provider import assemble_prompt_raw as _context_assemble_prompt_raw  # noqa: E402
from gateway.context_provider import build_upstream_context  # noqa: E402,F401 - compatibility export
from gateway.context_provider import command_context_from_output as _command_context_from_output_impl  # noqa: E402
from gateway.context_provider import context_mcp_bridge_path as _context_mcp_bridge_path_impl  # noqa: E402
from gateway.context_provider import context_mcp_db_path as _context_mcp_db_path_impl  # noqa: E402
from gateway.context_provider import context_mcp_root as _context_mcp_root_impl  # noqa: E402
from gateway.context_provider import context_status as _context_status_impl  # noqa: E402
from gateway.context_provider import context_to_text as _context_to_text_impl  # noqa: E402
from gateway.context_provider import extract_payload_context as _extract_payload_context_impl  # noqa: E402
from gateway.context_provider import glyph_encode_context as _glyph_encode_context_impl  # noqa: E402
from gateway.context_provider import prepare_gateway_context as _prepare_gateway_context_impl  # noqa: E402
from gateway.context_provider import prepare_gateway_pipeline as _prepare_gateway_pipeline_impl  # noqa: E402
from gateway.context_provider import retrieve_context as _retrieve_context_impl  # noqa: E402
from gateway.context_provider import run_context_command as _run_context_command_impl  # noqa: E402
from gateway.handlers_anthropic import handle_messages, handle_messages_count_tokens  # noqa: E402
from gateway.handlers_openai import handle_chat_completions  # noqa: E402
from gateway.health_runtime import GatewayRuntime as _GatewayRuntime  # noqa: E402
from gateway.health_runtime import cloud_routing_config as _cloud_routing_config_impl  # noqa: E402
from gateway.health_runtime import coerce_bool as _coerce_bool_impl  # noqa: E402
from gateway.health_runtime import get_cloud_provider_status as _get_cloud_provider_status_impl  # noqa: E402
from gateway.health_runtime import load_glyphos_config as _load_glyphos_config_impl  # noqa: E402
from gateway.health_runtime import maybe_start_update_watcher as _maybe_start_update_watcher  # noqa: E402
from gateway.health_runtime import normalize_cloud_provider as _normalize_cloud_provider_impl  # noqa: E402
from gateway.health_runtime import parse_cloud_fallback_order as _parse_cloud_fallback_order_impl  # noqa: E402
from gateway.health_runtime import provider_status as _provider_status_impl  # noqa: E402
from gateway.http_utils import http_json as gateway_http_json  # noqa: E402
from gateway.http_utils import json_response as gateway_json_response  # noqa: E402
from gateway.http_utils import read_json as gateway_read_json  # noqa: E402
from gateway.http_utils import request_float as gateway_request_float  # noqa: E402
from gateway.http_utils import request_int as gateway_request_int  # noqa: E402
from gateway.protocol_normalizers import anthropic_messages_summary as gateway_anthropic_messages_summary  # noqa: E402
from gateway.protocol_normalizers import (  # noqa: E402
    anthropic_messages_to_text,  # noqa: E402,F401 - compatibility export for extracted handlers
    append_tool_contract_to_prompt,  # noqa: E402,F401 - compatibility export for extracted handlers
    apply_anthropic_tool_use_response,  # noqa: E402,F401 - compatibility export for extracted handlers
    apply_openai_tool_call_response,  # noqa: E402,F401 - compatibility export for extracted handlers
    build_anthropic_response,  # noqa: E402,F401 - compatibility export for extracted handlers
    compact_json,  # noqa: E402,F401 - compatibility export
    format_tool_contract,  # noqa: E402,F401 - compatibility export
    messages_to_prompt,  # noqa: E402,F401 - compatibility export for extracted handlers
)
from gateway.routing_service import create_router as _routing_create_router  # noqa: E402
from gateway.routing_service import route_prompt as _routing_route_prompt  # noqa: E402
from gateway.routing_service import route_prompt_stream as _routing_route_prompt_stream  # noqa: E402
from gateway.sse import anthropic_sse_event as gateway_anthropic_sse_event  # noqa: E402
from gateway.sse import sse_comment as gateway_sse_comment  # noqa: E402
from gateway.sse import sse_event as gateway_sse_event  # noqa: E402
from gateway.sse import stream_anthropic_completion as gateway_stream_anthropic_completion  # noqa: E402
from gateway.sse import stream_completion as gateway_stream_completion  # noqa: E402
from gateway.telemetry import current_iso_timestamp as _telemetry_current_iso_timestamp  # noqa: E402
from gateway.telemetry import generate_handoff_summary as _telemetry_generate_handoff_summary  # noqa: E402
from gateway.telemetry import load_gateway_state as _load_gateway_state  # noqa: E402
from gateway.telemetry import record_gateway_request as _record_gateway_request  # noqa: E402
from gateway.telemetry import redact_gateway_telemetry_record as _redact_gateway_telemetry_record_impl  # noqa: E402
from gateway.telemetry import run_record_from_dict as _telemetry_run_record_from_dict  # noqa: E402
from gateway.telemetry import run_record_store as _run_record_store  # noqa: E402
from gateway.telemetry import safe_record_run_record as _safe_record_run_record  # noqa: E402
from gateway.telemetry import telemetry_store as _telemetry_store  # noqa: E402

from lmm_config import load_lmm_config_from_env  # noqa: E402
from lmm_notifications import create_notification_manager  # noqa: E402
from lmm_types import RunRecord  # noqa: E402

anthropic_messages_summary = gateway_anthropic_messages_summary
sse_event = gateway_sse_event
sse_comment = gateway_sse_comment
anthropic_sse_event = gateway_anthropic_sse_event


def now() -> float:
    return time.time()


def json_response(
    handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> None:
    gateway_json_response(handler, status, payload, headers)


def read_json(handler: BaseHTTPRequestHandler, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    return gateway_read_json(handler, max_bytes=max_bytes)


def request_int(payload: dict[str, Any], key: str, default: int, *, minimum: int = 1) -> int:
    return gateway_request_int(payload, key, default, minimum=minimum)


def request_float(payload: dict[str, Any], key: str, default: float) -> float:
    return gateway_request_float(payload, key, default)


def http_json(
    method: str, url: str, *, payload: dict[str, Any] | None = None, timeout: int = 5
) -> tuple[int, dict[str, Any]]:
    return gateway_http_json(method, url, payload=payload, timeout=timeout)


def run_context_command(
    command: list[str], *, input_text: str, timeout_seconds: float, cwd: str
) -> subprocess.CompletedProcess[str]:
    return _run_context_command_impl(command, input_text=input_text, timeout_seconds=timeout_seconds, cwd=cwd)


def state_file() -> Path:
    return load_lmm_config_from_env().gateway.state_file


def telemetry_store():
    return _telemetry_store()


def run_record_store():
    return _run_record_store()


def load_gateway_state() -> dict[str, Any]:
    return _load_gateway_state()


def _redact_gateway_telemetry_record(record: dict[str, Any]) -> dict[str, Any]:
    return _redact_gateway_telemetry_record_impl(record)


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
    return _record_gateway_request(record)


def safe_record_gateway_request(record: dict[str, Any]) -> None:
    try:
        record_gateway_request(record)
    except Exception as exc:
        sys.stderr.write(f"warning: failed to persist LMM gateway telemetry: {exc}\n")


def safe_record_run_record(record: RunRecord) -> None:
    return _safe_record_run_record(record)


def _current_iso_timestamp() -> str:
    return _telemetry_current_iso_timestamp()


def _run_record_from_dict(record: dict[str, Any]) -> RunRecord:
    return _telemetry_run_record_from_dict(record)


def _generate_handoff_summary(record: dict[str, Any], duration_ms: int) -> None:
    return _telemetry_generate_handoff_summary(record, duration_ms)


def context_pipeline_enabled() -> bool:
    return load_lmm_config_from_env().context.enabled


def _sync_context_provider_roots() -> None:
    _context_provider.APP_ROOT = APP_ROOT
    _context_provider.INTEGRATION_ROOT = APP_ROOT / "integrations" / "public-glyphos-ai-compute"


def context_mcp_root() -> Path:
    _sync_context_provider_roots()
    return _context_mcp_root_impl()


def context_mcp_bridge_path() -> Path:
    _sync_context_provider_roots()
    return _context_mcp_bridge_path_impl()


def context_mcp_db_path() -> Path:
    _sync_context_provider_roots()
    return _context_mcp_db_path_impl()


def _maybe_run_indexer(timeout_seconds: float) -> dict[str, Any]:
    _sync_context_provider_roots()
    from gateway.context_provider import _maybe_run_indexer as context_maybe_run_indexer  # type: ignore

    return context_maybe_run_indexer(timeout_seconds)


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
    _sync_context_provider_roots()
    return _context_status_impl()


def extract_payload_context(payload: dict[str, Any]) -> Any:
    return _extract_payload_context_impl(payload)


def context_to_text(context: Any) -> str:
    return _context_to_text_impl(context)


def notification_manager():
    enabled = os.environ.get("LMM_NOTIFICATIONS_ENABLED", "").lower() in {"1", "true", "yes"}
    return create_notification_manager(enabled=enabled)


def stream_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
    heartbeat_seconds: float | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[str, bool, str, int, dict[str, Any] | None]:
    return gateway_stream_completion(
        handler,
        started=started,
        model=model,
        chunks=chunks,
        headers=headers,
        heartbeat_seconds=heartbeat_seconds,
        notification_manager_factory=notification_manager,
        time_fn=now,
        payload=payload,
    )


def stream_anthropic_completion(
    handler: BaseHTTPRequestHandler,
    *,
    started: float,
    model: str,
    chunks: Iterator[str],
    headers: dict[str, str],
    heartbeat_seconds: float | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[str, bool, str, int, dict[str, Any] | None]:
    return gateway_stream_anthropic_completion(
        handler,
        started=started,
        model=model,
        chunks=chunks,
        headers=headers,
        heartbeat_seconds=heartbeat_seconds,
        notification_manager_factory=notification_manager,
        time_fn=now,
        payload=payload,
    )


def command_context_from_output(raw: str) -> dict[str, Any]:
    return _command_context_from_output_impl(raw)


def retrieve_context(
    payload: dict[str, Any], prompt: str, *, model: str, stream: bool, gateway_mode: str = "full"
) -> dict[str, Any]:
    _sync_context_provider_roots()
    return _retrieve_context_impl(
        payload,
        prompt,
        model=model,
        stream=stream,
        gateway_mode=gateway_mode,
        command_runner=run_context_command,
    )


def glyph_encode_context(context: str) -> dict[str, Any]:
    _sync_context_provider_roots()
    return _glyph_encode_context_impl(context)


def assemble_prompt_raw(raw_prompt: str, context_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return _context_assemble_prompt_raw(raw_prompt, context_result)


def assemble_prompt(
    raw_prompt: str, context_result: dict[str, Any], encoding_result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    return _context_assemble_prompt(raw_prompt, context_result, encoding_result)


def prepare_gateway_pipeline(
    payload: dict[str, Any], raw_prompt: str, *, model: str, stream: bool, gateway_mode: str = "full"
) -> tuple[str, dict[str, Any]]:
    _sync_context_provider_roots()
    return _prepare_gateway_pipeline_impl(
        payload,
        raw_prompt,
        model=model,
        stream=stream,
        gateway_mode=gateway_mode,
        command_runner=run_context_command,
    )


def prepare_gateway_context(
    payload: dict[str, Any],
    prompt: str,
    *,
    model: str,
    stream: bool,
    gateway_mode: str = "full",
) -> tuple[dict[str, Any], Any | None, dict[str, Any] | None]:
    _sync_context_provider_roots()
    return _prepare_gateway_context_impl(
        payload,
        prompt,
        model=model,
        stream=stream,
        gateway_mode=gateway_mode,
        command_runner=run_context_command,
    )


def _normalize_cloud_provider(raw: str) -> str:
    return _normalize_cloud_provider_impl(raw)


def _parse_cloud_fallback_order(raw: Any) -> list[str]:
    return _parse_cloud_fallback_order_impl(raw)


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    return _coerce_bool_impl(raw, default=default)


def _load_glyphos_config() -> dict[str, Any]:
    return _load_glyphos_config_impl()


def _cloud_routing_config() -> tuple[list[str], str]:
    return _cloud_routing_config_impl()


def _provider_status(enabled: bool, configured: bool, client: Any, reason: str) -> dict[str, Any]:
    return _provider_status_impl(enabled=enabled, configured=configured, client=client, reason=reason)


def _get_cloud_provider_status() -> dict[str, Any]:
    return _get_cloud_provider_status_impl()


def create_router():
    return _routing_create_router(cloud_routing_config_fn=_cloud_routing_config)


def route_prompt(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    context_payload=None,
    upstream_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    return _routing_route_prompt(
        prompt,
        model,
        max_tokens,
        temperature,
        context_payload=context_payload,
        upstream_context=upstream_context,
        create_router_fn=create_router,
    )


def route_prompt_stream(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    context_payload=None,
    upstream_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    return _routing_route_prompt_stream(
        prompt,
        model,
        max_tokens,
        temperature,
        context_payload=context_payload,
        upstream_context=upstream_context,
        create_router_fn=create_router,
    )


def _invoke_route_prompt(
    *,
    route_fn,
    prompt: str,
    fallback_prompt: str | None = None,
    model: str,
    max_tokens: int,
    temperature: float,
    context_payload: Any,
    upstream_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Invoke a route prompt callable with backward-compatible args.

    Older tests patch this function with 4-arg callables.
    Keep new context-aware behavior when supported and gracefully fallback.
    """

    effective_route_fn = getattr(route_fn, "side_effect", None) or route_fn
    try:
        parameters = inspect.signature(effective_route_fn).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
    accepts_context_payload = accepts_kwargs or "context_payload" in parameters
    accepts_upstream_context = accepts_kwargs or "upstream_context" in parameters

    if not accepts_context_payload:
        return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
    if not accepts_upstream_context:
        return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)

    try:
        return route_fn(
            prompt,
            model,
            max_tokens,
            temperature,
            context_payload=context_payload,
            upstream_context=upstream_context,
        )
    except TypeError as exc:
        message = str(exc)
        if "context_payload" in message or "upstream_context" in message:
            try:
                return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)
            except TypeError as retry_exc:
                retry_message = str(retry_exc)
                if "context_payload" in retry_message:
                    return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
                raise
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
    upstream_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    """Invoke a streaming route callable with backward-compatible args."""

    effective_route_fn = getattr(route_fn, "side_effect", None) or route_fn
    try:
        parameters = inspect.signature(effective_route_fn).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
    accepts_context_payload = accepts_kwargs or "context_payload" in parameters
    accepts_upstream_context = accepts_kwargs or "upstream_context" in parameters

    if not accepts_context_payload:
        return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
    if not accepts_upstream_context:
        return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)

    try:
        return route_fn(
            prompt,
            model,
            max_tokens,
            temperature,
            context_payload=context_payload,
            upstream_context=upstream_context,
        )
    except TypeError as exc:
        message = str(exc)
        if "context_payload" in message or "upstream_context" in message:
            try:
                return route_fn(prompt, model, max_tokens, temperature, context_payload=context_payload)
            except TypeError as retry_exc:
                retry_message = str(retry_exc)
                if "context_payload" in retry_message:
                    return route_fn(fallback_prompt or prompt, model, max_tokens, temperature)
                raise
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
    if encoding_status.lower() != "encoded" or not encoded_context:
        encoding_result = glyph_encode_context(context_text)
        encoding_status = str(encoding_result.get("status", encoding_status))
        encoded_context = str(encoding_result.get("encoded_context", encoded_context))
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


class LMMOpenAIGateway(_GatewayRuntime):
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

    def telemetry(self) -> dict[str, Any]:
        return load_gateway_state()


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

        if path == "/v1/messages/count_tokens":
            handle_messages_count_tokens(self, globals())
            return

        if path == "/v1/messages":
            handle_messages(self, globals())
            return

        if path != "/v1/chat/completions":
            json_response(self, 404, {"error": {"message": "unknown route", "type": "not_found"}})
            return
        handle_chat_completions(self, globals())

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write(f"{self.log_date_time_string()} - {format % args}\n")


def create_gateway_server(
    host: str = "127.0.0.1",
    port: int = 4010,
    backend_base_url: str = "http://127.0.0.1:8081/v1",
    model_id: str = "",
    gateway_mode: str = "full",
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
    server.gateway_mode = gateway_mode  # type: ignore[attr-defined]
    server.gateway = LMMOpenAIGateway(backend_base_url=backend_base_url, model_id=model_id)  # type: ignore[attr-defined]
    server.gateway.gateway_mode = gateway_mode  # type: ignore[attr-defined]
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
    watcher_config: Any | None = None,
) -> None:
    if watcher_config is None:
        watcher_config = load_lmm_config_from_env().update_watcher
    return _maybe_start_update_watcher(server, watcher_config=watcher_config)


def main(argv: list[str]) -> int:
    config = load_lmm_config_from_env().gateway
    parser = argparse.ArgumentParser(description="LMM OpenAI-compatible gateway through GlyphOS AI Compute")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--backend-base-url", default=config.backend_base_url)
    parser.add_argument("--model-id", default=config.model_id)
    parser.add_argument("--mode", choices=["full", "fast"], default=config.mode)
    args = parser.parse_args(argv)
    port = args.port if args.port is not None else (config.fast_port if args.mode == "fast" else config.port)

    server = create_gateway_server(
        host=args.host,
        port=port,
        backend_base_url=args.backend_base_url,
        model_id=args.model_id,
        gateway_mode=args.mode,
    )
    print(
        f"LMM GlyphOS {args.mode} gateway listening on http://{args.host}:{port}/v1 -> {args.backend_base_url}",
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
