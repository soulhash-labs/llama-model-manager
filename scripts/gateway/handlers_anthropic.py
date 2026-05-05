from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler
from typing import Any

from lmm_errors import GatewayError, InvalidRequestError
from lmm_types import ExitResult, RunStatus


def handle_messages_count_tokens(handler: BaseHTTPRequestHandler, api: dict[str, Any]) -> None:
    read_json = api["read_json"]
    anthropic_messages_to_text = api["anthropic_messages_to_text"]
    append_tool_contract_to_prompt = api["append_tool_contract_to_prompt"]
    http_json = api["http_json"]
    json_response = api["json_response"]

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


def handle_messages(handler: BaseHTTPRequestHandler, api: dict[str, Any]) -> None:
    now = api["now"]
    read_json = api["read_json"]
    anthropic_messages_to_text = api["anthropic_messages_to_text"]
    append_tool_contract_to_prompt = api["append_tool_contract_to_prompt"]
    json_response = api["json_response"]
    request_int = api["request_int"]
    request_float = api["request_float"]
    current_iso_timestamp = api["_current_iso_timestamp"]
    prepare_gateway_pipeline = api["prepare_gateway_pipeline"]
    build_context_payload = api["_build_context_payload"]
    invoke_route_prompt = api["_invoke_route_prompt"]
    invoke_route_prompt_stream = api["_invoke_route_prompt_stream"]
    route_prompt = api["route_prompt"]
    route_prompt_stream = api["route_prompt_stream"]
    fallback_prompt_for_legacy_route = api["_fallback_prompt_for_legacy_route"]
    build_anthropic_response = api["build_anthropic_response"]
    apply_anthropic_tool_use_response = api["apply_anthropic_tool_use_response"]
    stream_anthropic_completion = api["stream_anthropic_completion"]
    generate_handoff_summary = api["_generate_handoff_summary"]
    safe_record_run_record = api["safe_record_run_record"]
    run_record_from_dict = api["_run_record_from_dict"]
    safe_record_gateway_request = api["safe_record_gateway_request"]

    started = now()
    try:
        payload = read_json(handler)
        prompt = anthropic_messages_to_text(payload.get("messages", []), payload.get("system"))
        prompt = append_tool_contract_to_prompt(prompt, payload, protocol="anthropic-messages")
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
        }

        _, pipeline = prepare_gateway_pipeline(payload, prompt, model=model, stream=stream)
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
                    "encoding_status": context_payload.encoding_status,
                    "encoding_format": context_payload.encoding_format,
                    "encoding_ratio": context_payload.encoding_ratio,
                    "encoding_aware_routing": True,
                }
            )
            text, success, error_message, latency_ms = stream_anthropic_completion(
                handler,
                started=started,
                model=model,
                chunks=chunks,
                headers=headers,
            )
            record.update(
                {
                    "success": success,
                    "latency_ms": latency_ms,
                    "completion_chars": len(text),
                    "completed_at": current_iso_timestamp(),
                    "provider": record["route_target"],
                    "status": RunStatus.COMPLETED.value if success else RunStatus.CANCELLED.value,
                    "exit_result": ExitResult.SUCCESS.value if success else ExitResult.USER_CANCELLED.value,
                }
            )
            if error_message:
                record["error"] = error_message
            generate_handoff_summary(record, record.get("latency_ms", 0))
            safe_record_run_record(run_record_from_dict(record))
            safe_record_gateway_request(record)
            return

        routed, _ = invoke_route_prompt(
            route_fn=route_prompt,
            prompt=prompt,
            fallback_prompt=fallback_prompt_for_legacy_route(prompt, pipeline, context_payload),
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            context_payload=context_payload,
            upstream_context=pipeline.get("upstream_context"),
        )

        record.update(
            {
                "route_target": routed["target"],
                "reason_code": routed["reason_code"],
                "success": True,
                "latency_ms": routed["latency_ms"],
                "provider": routed["target"],
                "status": RunStatus.COMPLETED.value,
                "exit_result": ExitResult.SUCCESS.value,
                "completed_at": current_iso_timestamp(),
            }
        )

        response = build_anthropic_response(
            text=routed["text"],
            model=model,
            started=started,
            routed=routed,
            pipeline=pipeline,
        )
        response = apply_anthropic_tool_use_response(response, routed["text"], payload)

        safe_record_gateway_request(record)
        json_response(handler, 200, response)
    except InvalidRequestError as exc:
        json_response(handler, 400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
    except GatewayError as exc:
        json_response(handler, 502, {"error": {"message": str(exc), "type": "gateway_error"}})
    except Exception as exc:
        json_response(handler, 500, {"error": {"message": str(exc), "type": "internal_error"}})


__all__ = ["handle_messages", "handle_messages_count_tokens"]
