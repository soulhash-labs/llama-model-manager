from __future__ import annotations

import json
import os
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping
from http.server import BaseHTTPRequestHandler
from typing import Any, TypedDict, cast

from lmm_errors import GatewayError, InvalidRequestError
from lmm_types import ExitResult, RunStatus

JsonDict = dict[str, Any]
Headers = dict[str, str]
RoutedResult = dict[str, Any]
ContextPayload = Any
ToolCallInfo = dict[str, Any] | None

RoutePromptFn = Callable[..., tuple[RoutedResult, Headers]]
RoutePromptStreamFn = Callable[..., tuple[RoutedResult, Headers, Iterator[str]]]


def _log_unexpected_handler_error(exc: BaseException) -> None:
    sys.stderr.write(f"error: unexpected Anthropic gateway handler failure: {exc}\n")
    sys.stderr.write(traceback.format_exc())


class AnthropicCountTokensAPI(TypedDict):
    read_json: Callable[[BaseHTTPRequestHandler], JsonDict]
    anthropic_messages_to_text: Callable[[Any, Any], str]
    append_tool_contract_to_prompt: Callable[..., str]
    http_json: Callable[..., tuple[int, JsonDict]]
    json_response: Callable[..., None]


class AnthropicHandlerAPI(AnthropicCountTokensAPI):
    now: Callable[[], float]
    request_int: Callable[[JsonDict, str, int], int]
    request_float: Callable[[JsonDict, str, float], float]
    _current_iso_timestamp: Callable[[], str]
    prepare_gateway_pipeline: Callable[..., tuple[Any, JsonDict]]
    _build_context_payload: Callable[..., ContextPayload]
    _invoke_route_prompt: Callable[..., tuple[RoutedResult, Headers]]
    _invoke_route_prompt_stream: Callable[..., tuple[RoutedResult, Headers, Iterator[str]]]
    route_prompt: RoutePromptFn
    route_prompt_stream: RoutePromptStreamFn
    _fallback_prompt_for_legacy_route: Callable[[str, JsonDict, ContextPayload], str]
    build_anthropic_response: Callable[..., JsonDict]
    classify_tool_invocation: Callable[[str, JsonDict], JsonDict]
    apply_anthropic_tool_use_response: Callable[[JsonDict, str, JsonDict], JsonDict]
    stream_anthropic_completion: Callable[..., tuple[str, bool, str, int, ToolCallInfo]]
    _generate_handoff_summary: Callable[[JsonDict, int], None]
    safe_record_run_record: Callable[[Any], None]
    _run_record_from_dict: Callable[[JsonDict], Any]
    safe_record_gateway_request: Callable[[JsonDict], None]


def handle_messages_count_tokens(handler: BaseHTTPRequestHandler, api: Mapping[str, Any]) -> None:
    typed_api = cast(AnthropicCountTokensAPI, api)
    read_json = typed_api["read_json"]
    anthropic_messages_to_text = typed_api["anthropic_messages_to_text"]
    append_tool_contract_to_prompt = typed_api["append_tool_contract_to_prompt"]
    http_json = typed_api["http_json"]
    json_response = typed_api["json_response"]

    try:
        payload = read_json(handler)
        text = anthropic_messages_to_text(payload.get("messages", []), payload.get("system"))
        text = append_tool_contract_to_prompt(text, payload, protocol="anthropic-messages")
        backend_base_url = getattr(handler.server, "backend_base_url", "http://127.0.0.1:8081/v1")
        try:
            _, token_data = http_json("POST", f"{backend_base_url}/tokenize", {"content": text}, timeout=5)
            if isinstance(token_data.get("tokens"), list):
                token_count = len(token_data["tokens"])
            elif isinstance(token_data.get("count"), int):
                token_count = token_data["count"]
            else:
                token_count = max(1, len(text.split())) if text.strip() else 0
        except Exception:
            token_count = max(1, len(text.split())) if text.strip() else 0
        json_response(handler, 200, {"input_tokens": token_count})
    except InvalidRequestError as exc:
        json_response(handler, 400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
    except Exception as exc:
        json_response(handler, 500, {"error": {"message": str(exc), "type": "internal_error"}})


def handle_messages(handler: BaseHTTPRequestHandler, api: Mapping[str, Any]) -> None:
    typed_api = cast(AnthropicHandlerAPI, api)
    now = typed_api["now"]
    read_json = typed_api["read_json"]
    anthropic_messages_to_text = typed_api["anthropic_messages_to_text"]
    append_tool_contract_to_prompt = typed_api["append_tool_contract_to_prompt"]
    json_response = typed_api["json_response"]
    request_int = typed_api["request_int"]
    request_float = typed_api["request_float"]
    current_iso_timestamp = typed_api["_current_iso_timestamp"]
    prepare_gateway_pipeline = typed_api["prepare_gateway_pipeline"]
    build_context_payload = typed_api["_build_context_payload"]
    invoke_route_prompt = typed_api["_invoke_route_prompt"]
    invoke_route_prompt_stream = typed_api["_invoke_route_prompt_stream"]
    route_prompt = typed_api["route_prompt"]
    route_prompt_stream = typed_api["route_prompt_stream"]
    fallback_prompt_for_legacy_route = typed_api["_fallback_prompt_for_legacy_route"]
    build_anthropic_response = typed_api["build_anthropic_response"]
    classify_tool_invocation = typed_api["classify_tool_invocation"]
    apply_anthropic_tool_use_response = typed_api["apply_anthropic_tool_use_response"]
    stream_anthropic_completion = typed_api["stream_anthropic_completion"]
    generate_handoff_summary = typed_api["_generate_handoff_summary"]
    safe_record_run_record = typed_api["safe_record_run_record"]
    run_record_from_dict = typed_api["_run_record_from_dict"]
    safe_record_gateway_request = typed_api["safe_record_gateway_request"]

    started = now()
    try:
        payload = read_json(handler)
        prompt = anthropic_messages_to_text(payload.get("messages", []), payload.get("system"))
        prompt = append_tool_contract_to_prompt(prompt, payload, protocol="anthropic-messages")
        prompt_normalized_ms = round((now() - started) * 1000)
        if not prompt.strip():
            raise InvalidRequestError("messages must contain text content")
        model = str(payload.get("model") or getattr(handler.server, "model_id", "") or "claude-3")
        max_tokens = request_int(payload, "max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768")))
        temperature = request_float(payload, "temperature", 0.7)
        stream = payload.get("stream") is True

        record: dict[str, Any] = {
            "time": started,
            "started_at": current_iso_timestamp(),
            "harness": handler.headers.get("User-Agent", "unknown"),
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
            "stream": stream,
            "timing": {"request_received_ms": 0, "prompt_normalized_ms": prompt_normalized_ms},
        }

        gateway_mode = str(getattr(handler.server, "gateway_mode", "full"))
        _, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream, gateway_mode=gateway_mode)
        record["timing"].update(pipeline.get("timing", {}))
        context_payload = build_context_payload(
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
                "gateway_mode": pipeline.get("gateway_mode", gateway_mode),
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

        if stream:
            routed, headers, chunks = invoke_route_prompt_stream(
                route_fn=route_prompt_stream,
                prompt=prompt,
                fallback_prompt=fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                context_payload=context_payload,
                upstream_context=pipeline.get("upstream_context"),
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
                    "route_latency_ms": routed.get("route_duration_ms", 0),
                    "encoding_status": context_payload.encoding_status,
                    "encoding_format": context_payload.encoding_format,
                    "encoding_ratio": context_payload.encoding_ratio,
                    "encoding_aware_routing": True,
                }
            )
            text, success, error_message, latency_ms, tool_call_info = stream_anthropic_completion(
                handler,
                started=started,
                model=model,
                chunks=chunks,
                headers=headers,
                payload=payload,
            )
            tool_report = classify_tool_invocation(text, payload)
            record.update(
                {
                    "success": success,
                    "latency_ms": latency_ms,
                    "effective_ttfb_ms": latency_ms if text else record["timing"].get("pipeline_total_ms", 0),
                    "completion_chars": len(text),
                    "completed_at": current_iso_timestamp(),
                    "provider": record["route_target"],
                    "status": RunStatus.COMPLETED.value if success else RunStatus.CANCELLED.value,
                    "exit_result": ExitResult.SUCCESS.value if success else ExitResult.USER_CANCELLED.value,
                    "stream_tool_call_detected": bool(tool_call_info),
                    "stream_tool_call_name": str(tool_call_info.get("name", ""))
                    if isinstance(tool_call_info, dict)
                    else "",
                    "tool_invocation_mode": tool_report["tool_invocation_mode"],
                    "tool_name": tool_report["tool_name"],
                    "lane": "4011" if record.get("gateway_mode") == "fast" else "4010",
                    "session_id": record.get("session_id", ""),
                    "repair_attempted": tool_report["repair_attempted"],
                    "repair_succeeded": tool_report["repair_succeeded"],
                }
            )
            if error_message:
                record["error"] = error_message
            generate_handoff_summary(record, record.get("latency_ms", 0))
            safe_record_run_record(run_record_from_dict(record))
            safe_record_gateway_request(record)
            return

        tools = payload.get("tools")
        tool_choice = payload.get("tool_choice")

        # Convert Anthropic tools to OpenAI format for the router
        if tools:
            openai_tools = []
            for t in tools:
                if isinstance(t, dict):
                    openai_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": t.get("name", ""),
                                "description": t.get("description", ""),
                                "parameters": t.get("input_schema", {}),
                            },
                        }
                    )
            tools = openai_tools

        # Convert Anthropic tool_choice to OpenAI format
        if tool_choice and isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                func_name = tool_choice.get("function", {}).get("name", "")
                if func_name:
                    tool_choice = {"type": "function", "function": {"name": func_name}}

        routed, _ = invoke_route_prompt(
            route_fn=route_prompt,
            prompt=prompt,
            fallback_prompt=fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            context_payload=context_payload,
            upstream_context=pipeline.get("upstream_context"),
            tools=tools,
            tool_choice=tool_choice,
        )

        record.update(
            {
                "route_target": routed.get("target", "unknown"),
                "reason_code": routed.get("reason_code", "unknown"),
                "success": True,
                "latency_ms": routed.get("latency_ms", 0),
                "route_latency_ms": routed.get("route_duration_ms", routed.get("latency_ms", 0)),
                "provider": routed.get("target", "unknown"),
                "status": RunStatus.COMPLETED.value,
                "exit_result": ExitResult.SUCCESS.value,
                "completed_at": current_iso_timestamp(),
                "encoding_status": context_payload.encoding_status,
                "encoding_format": context_payload.encoding_format,
                "encoding_ratio": context_payload.encoding_ratio,
                "encoding_aware_routing": True,
            }
        )
        tool_report = classify_tool_invocation(routed.get("text", ""), payload)
        record.update(
            {
                "tool_invocation_mode": tool_report["tool_invocation_mode"],
                "tool_name": tool_report["tool_name"],
                "lane": "4011" if record.get("gateway_mode") == "fast" else "4010",
                "session_id": record.get("session_id", ""),
                "repair_attempted": tool_report["repair_attempted"],
                "repair_succeeded": tool_report["repair_succeeded"],
            }
        )
        if tool_report["tool_invocation_mode"] == "textual_pseudo_call" and not tool_report["repair_succeeded"]:
            raise GatewayError(
                "task tool invocation formation failed",
                provider=record.get("provider", ""),
                lane=record.get("lane", ""),
                session_id=record.get("session_id", ""),
                repair_attempted=tool_report["repair_attempted"],
                repair_succeeded=tool_report["repair_succeeded"],
            )

        response = build_anthropic_response(
            text=routed.get("text", ""),
            model=model,
            started=started,
            routed=routed,
            pipeline=pipeline,
        )

        tool_calls = routed.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            response["stop_reason"] = "tool_use"
            response["content"] = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                if isinstance(func, dict):
                    name = str(func.get("name", ""))
                    args = func.get("arguments", {})
                else:
                    name = str(tc.get("name", ""))
                    args = tc.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        args = {"value": args}
                response["content"].append(
                    {
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"toolu_{int(started * 1000)}"),
                        "name": name,
                        "input": args if isinstance(args, dict) else {},
                    }
                )
        else:
            response = apply_anthropic_tool_use_response(response, routed.get("text", ""), payload)

        safe_record_gateway_request(record)
        json_response(handler, 200, response)
    except InvalidRequestError as exc:
        json_response(handler, 400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
    except GatewayError as exc:
        json_response(handler, 502, {"error": exc.to_dict()})
    except Exception as exc:
        _log_unexpected_handler_error(exc)
        json_response(handler, 500, {"error": {"message": str(exc), "type": "internal_error"}})


__all__ = ["handle_messages", "handle_messages_count_tokens"]
