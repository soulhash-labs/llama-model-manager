from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping
from http.server import BaseHTTPRequestHandler
from typing import Any, TypedDict, cast

from lmm_config import load_lmm_config_from_env
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
    sys.stderr.write(f"error: unexpected OpenAI gateway handler failure: {exc}\n")
    sys.stderr.write(traceback.format_exc())


def _estimate_tokens(text: str) -> int:
    # TODO: replace chars/4 heuristic with model tokenizer or
    # llama.cpp tokenize endpoint for accurate per-model counts.
    # Code-heavy, Unicode, or structured payloads deviate from
    # the ~4-char-per-token average.
    return max(1, len(text) // 4) if text.strip() else 0


def _check_context_budget(prompt: str) -> None:
    """Raise InvalidRequestError if estimated tokens exceed configured budget."""
    budget = load_lmm_config_from_env().context_budget
    estimated = _estimate_tokens(prompt)
    allowed = budget.max_tokens - budget.safety_margin
    if estimated <= allowed:
        return

    # If compact/truncate mode is selected but not yet implemented,
    # fall back to reject with an explicit warning.
    if budget.overflow_mode in ("compact", "truncate"):
        sys.stderr.write(
            f"warning: LMM_CONTEXT_OVERFLOW_MODE={budget.overflow_mode} is not yet "
            f"implemented; falling back to reject.\n"
        )

    sys.stderr.write(
        f"context budget exceeded: ~{estimated} estimated tokens, "
        f"{budget.max_tokens} max, {allowed} allowed "
        f"(mode={budget.overflow_mode})\n"
    )
    raise InvalidRequestError(
        f"Context too large: ~{estimated} estimated tokens vs {budget.max_tokens} max context. "
        f"Allowed budget with {budget.safety_margin}-token safety margin: {allowed}. "
        "Use rg/search first, read smaller file ranges (120 lines around match), "
        "or compact current findings into a summary before continuing."
    )


class OpenAIHandlerAPI(TypedDict):
    now: Callable[[], float]
    context_status: Callable[[], tuple[str, bool]]
    _current_iso_timestamp: Callable[[], str]
    read_json: Callable[[BaseHTTPRequestHandler], JsonDict]
    messages_to_prompt: Callable[[Any], str]
    append_tool_contract_to_prompt: Callable[..., str]
    classify_tool_invocation: Callable[[str, JsonDict], JsonDict]
    apply_openai_tool_call_response: Callable[[JsonDict, str, JsonDict], JsonDict]
    _extract_session_metadata: Callable[[JsonDict], JsonDict]
    request_int: Callable[[JsonDict, str, int], int]
    request_float: Callable[[JsonDict, str, float], float]
    prepare_gateway_pipeline: Callable[..., tuple[Any, JsonDict]]
    _build_context_payload: Callable[..., ContextPayload]
    _invoke_route_prompt: Callable[..., tuple[RoutedResult, Headers]]
    _invoke_route_prompt_stream: Callable[..., tuple[RoutedResult, Headers, Iterator[str]]]
    route_prompt: RoutePromptFn
    route_prompt_stream: RoutePromptStreamFn
    _fallback_prompt_for_legacy_route: Callable[[str, JsonDict, ContextPayload], str]
    stream_completion: Callable[..., tuple[str, bool, str, int, ToolCallInfo]]
    _generate_handoff_summary: Callable[[JsonDict, int], None]
    safe_record_run_record: Callable[[Any], None]
    _run_record_from_dict: Callable[[JsonDict], Any]
    safe_record_gateway_request: Callable[[JsonDict], None]
    completion_payload: Callable[..., JsonDict]
    json_response: Callable[..., None]


def _build_openai_record(
    *,
    started: float,
    handler: BaseHTTPRequestHandler,
    context_state: str,
    context_used: bool,
) -> JsonDict:
    return {
        "time": started,
        "started_at": "",
        "harness": handler.headers.get("User-Agent", "unknown"),
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


def handle_chat_completions(handler: BaseHTTPRequestHandler, api: Mapping[str, Any]) -> None:
    typed_api = cast(OpenAIHandlerAPI, api)
    now = typed_api["now"]
    context_status = typed_api["context_status"]
    current_iso_timestamp = typed_api["_current_iso_timestamp"]
    read_json = typed_api["read_json"]
    messages_to_prompt = typed_api["messages_to_prompt"]
    append_tool_contract_to_prompt = typed_api["append_tool_contract_to_prompt"]
    classify_tool_invocation = typed_api["classify_tool_invocation"]
    apply_openai_tool_call_response = typed_api["apply_openai_tool_call_response"]
    extract_session_metadata = typed_api["_extract_session_metadata"]
    request_int = typed_api["request_int"]
    request_float = typed_api["request_float"]
    prepare_gateway_pipeline = typed_api["prepare_gateway_pipeline"]
    build_context_payload = typed_api["_build_context_payload"]
    invoke_route_prompt = typed_api["_invoke_route_prompt"]
    invoke_route_prompt_stream = typed_api["_invoke_route_prompt_stream"]
    route_prompt = typed_api["route_prompt"]
    route_prompt_stream = typed_api["route_prompt_stream"]
    fallback_prompt_for_legacy_route = typed_api["_fallback_prompt_for_legacy_route"]
    stream_completion = typed_api["stream_completion"]
    generate_handoff_summary = typed_api["_generate_handoff_summary"]
    safe_record_run_record = typed_api["safe_record_run_record"]
    run_record_from_dict = typed_api["_run_record_from_dict"]
    safe_record_gateway_request = typed_api["safe_record_gateway_request"]
    completion_payload = typed_api["completion_payload"]
    json_response = typed_api["json_response"]

    started = now()
    context_state, context_used = context_status()
    record = _build_openai_record(
        started=started,
        handler=handler,
        context_state=context_state,
        context_used=context_used,
    )
    record["started_at"] = current_iso_timestamp()
    record["timing"] = {"request_received_ms": 0}

    try:
        payload = read_json(handler)
        prompt = messages_to_prompt(payload.get("messages"))
        prompt = append_tool_contract_to_prompt(prompt, payload, protocol="openai-chat-completions")
        record["timing"]["prompt_normalized_ms"] = round((now() - started) * 1000)
        model = str(payload.get("model") or getattr(handler.server, "model_id", "") or "local-llama")
        record["prompt"] = prompt
        record["model"] = model
        session_meta = extract_session_metadata(payload)
        if session_meta:
            record.update(session_meta)
        max_tokens = request_int(payload, "max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768")))
        temperature = request_float(payload, "temperature", 0.7)
        stream = payload.get("stream") is True
        record["stream"] = stream
        if not prompt.strip():
            raise InvalidRequestError("messages must contain text content")

        _check_context_budget(prompt)

        gateway_mode = str(getattr(handler.server, "gateway_mode", "full"))
        _, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream, gateway_mode=gateway_mode)
        record["timing"].update(pipeline.get("timing", {}))
        pipeline_request = pipeline.get("request")
        if isinstance(pipeline_request, dict):
            pipeline_request["harness_identity"] = record["harness"]

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
                "context_status": pipeline.get("context_status", context_state),
                "context_used": bool(pipeline.get("context_used")),
                "context_source": pipeline.get("context_source", ""),
                "context_error": pipeline.get("context_error", ""),
                "context_latency_ms": pipeline.get("context_latency_ms", 0),
                "search_strategy": pipeline.get("search_strategy", ""),
                "search_degraded": bool(pipeline.get("search_degraded", False)),
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
            text, success, error_message, latency_ms, tool_call_info = stream_completion(
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
            if not success:
                record["status"] = RunStatus.CANCELLED.value
                record["exit_result"] = ExitResult.USER_CANCELLED.value
                record["provider"] = record["route_target"]
            else:
                record["status"] = RunStatus.COMPLETED.value
                record["exit_result"] = ExitResult.SUCCESS.value
                record["provider"] = record["route_target"]
            generate_handoff_summary(record, record.get("latency_ms", 0))
            safe_record_run_record(run_record_from_dict(record))
            safe_record_gateway_request(record)
            return

        routed, headers = invoke_route_prompt(
            route_fn=route_prompt,
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
        response_payload = completion_payload(
            started=started,
            model=model,
            routed=routed,
            pipeline=pipeline,
        )
        response_payload = apply_openai_tool_call_response(response_payload, routed.get("text", ""), payload)
        generate_handoff_summary(record, routed.get("latency_ms", 0))
        safe_record_run_record(run_record_from_dict(record))
        safe_record_gateway_request(record)
        json_response(handler, 200, response_payload, headers=headers)
    except InvalidRequestError as exc:
        record["error"] = str(exc)
        record["status"] = RunStatus.FAILED.value
        record["exit_result"] = ExitResult.ERROR.value
        record["latency_ms"] = round((now() - started) * 1000)
        record["completed_at"] = current_iso_timestamp()
        generate_handoff_summary(record, record["latency_ms"])
        safe_record_gateway_request(record)
        safe_record_run_record(run_record_from_dict(record))
        json_response(
            handler,
            400,
            {"error": {"message": str(exc), "type": "invalid_request_error"}, "lmm": record},
        )
    except GatewayError as exc:
        record["error"] = str(exc)
        record["status"] = RunStatus.FAILED.value
        record["exit_result"] = ExitResult.PROVIDER_ERROR.value
        record["latency_ms"] = round((now() - started) * 1000)
        record["completed_at"] = current_iso_timestamp()
        generate_handoff_summary(record, record["latency_ms"])
        safe_record_gateway_request(record)
        safe_record_run_record(run_record_from_dict(record))
        json_response(handler, 503, {"error": exc.to_dict(), "lmm": record})
    except Exception as exc:
        _log_unexpected_handler_error(exc)
        record["error"] = str(exc)
        record["status"] = RunStatus.FAILED.value
        record["exit_result"] = ExitResult.PROVIDER_ERROR.value
        record["latency_ms"] = round((now() - started) * 1000)
        record["completed_at"] = current_iso_timestamp()
        generate_handoff_summary(record, record["latency_ms"])
        safe_record_gateway_request(record)
        safe_record_run_record(run_record_from_dict(record))
        error_payload = {"message": str(exc), "type": "lmm_gateway_error"}
        json_response(handler, 503, {"error": error_payload, "lmm": record})


__all__ = ["handle_chat_completions"]
