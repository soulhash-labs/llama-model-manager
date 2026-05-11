from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_TOOL_CONTRACT_CHARS = 12_000


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _bounded_json(value: Any, *, max_chars: int = MAX_TOOL_CONTRACT_CHARS) -> str:
    text = compact_json(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 32)] + "...[truncated]"


def _content_to_text(content: Any, *, provider: str) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                parts.append(str(part.get("text", "")))
            elif provider == "anthropic" and isinstance(part, dict) and part.get("type") == "tool_result":
                tool_id = str(part.get("tool_use_id", "")).strip()
                tool_content = part.get("content", "")
                if isinstance(tool_content, list):
                    tool_text = "\n".join(
                        str(item.get("text", ""))
                        for item in tool_content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                else:
                    tool_text = str(tool_content)
                parts.append(f"tool_result {tool_id}: {tool_text}".strip())
            elif provider == "anthropic" and isinstance(part, dict) and part.get("type") == "tool_use":
                parts.append("tool_use: " + _bounded_json(part))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(piece for piece in parts if piece)
    return str(content)


def messages_to_prompt(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content_text = _content_to_text(item.get("content", ""), provider="openai")
        if item.get("tool_calls"):
            content_text = "\n".join(
                piece for piece in [content_text, "tool_calls: " + _bounded_json(item.get("tool_calls"))] if piece
            )
        if item.get("function_call"):
            content_text = "\n".join(
                piece for piece in [content_text, "function_call: " + _bounded_json(item.get("function_call"))] if piece
            )
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def anthropic_messages_to_text(messages: Any, system: Any = None) -> str:
    lines: list[str] = []

    if system is not None:
        if isinstance(system, str):
            system_text = system.strip()
        elif isinstance(system, list):
            parts: list[str] = []
            for item in system:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            system_text = "\n".join(part for part in parts if part).strip()
        else:
            system_text = str(system).strip()
        if system_text:
            lines.append(f"system: {system_text}")

    if not isinstance(messages, list):
        return "\n\n".join(lines)

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content_text = _content_to_text(item.get("content", ""), provider="anthropic")
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


def format_tool_contract(payload: dict[str, Any], *, protocol: str) -> str:
    """
    Format tool/function declarations for model-visible routing prompts.

    This does not execute tools. It preserves harness-supplied contracts so the
    routed model can decide whether a provider-shaped tool call is appropriate.
    """
    selected: dict[str, Any] = {}
    for key in ("tools", "tool_choice", "functions", "function_call", "parallel_tool_calls"):
        value = payload.get(key)
        if value is not None:
            selected[key] = value

    if not selected:
        return ""

    body = {
        "protocol": protocol,
        "contract": selected,
        "instructions": (
            "Use these tools/functions only when the user request requires them. "
            "Do not invent undeclared tools. If a tool call is required, return a valid "
            "tool-call request for the declared provider shape with JSON arguments."
        ),
    }
    return "[TOOL_CONTRACT]\n" + _bounded_json(body)


def append_tool_contract_to_prompt(prompt: str, payload: dict[str, Any], *, protocol: str) -> str:
    contract = format_tool_contract(payload, protocol=protocol)
    if not contract:
        return prompt
    if not prompt.strip():
        return contract
    return f"{prompt.rstrip()}\n\n{contract}"


def _declared_tool_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    tools = payload.get("tools")
    if isinstance(tools, list):
        for item in tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if isinstance(function, dict) and function.get("name"):
                names.add(str(function["name"]))
            elif item.get("name"):
                names.add(str(item["name"]))

    functions = payload.get("functions")
    if isinstance(functions, list):
        for item in functions:
            if isinstance(item, dict) and item.get("name"):
                names.add(str(item["name"]))
    return names


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_tool_call(text: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    declared_names = _declared_tool_names(payload)
    if not declared_names:
        return None

    parsed = _parse_json_object(text)
    if not parsed:
        return None

    candidate: Any = None
    if isinstance(parsed.get("tool_call"), dict):
        candidate = parsed["tool_call"]
    elif isinstance(parsed.get("tool_calls"), list) and parsed["tool_calls"]:
        candidate = parsed["tool_calls"][0]
    elif parsed.get("type") == "tool_use":
        candidate = parsed

    if not isinstance(candidate, dict):
        return None

    function = candidate.get("function")
    if isinstance(function, dict):
        name = str(function.get("name", ""))
        arguments = function.get("arguments", {})
    else:
        name = str(candidate.get("name", ""))
        arguments = candidate.get("arguments", candidate.get("input", {}))

    if name not in declared_names:
        return None

    if isinstance(arguments, str):
        parsed_arguments = _parse_json_object(arguments)
        arguments = parsed_arguments if parsed_arguments is not None else {"value": arguments}
    if not isinstance(arguments, dict):
        arguments = {"value": arguments}

    return {
        "id": str(
            candidate.get("id") or "call_" + hashlib.sha1(f"{name}:{compact_json(arguments)}".encode()).hexdigest()[:12]
        ),
        "name": name,
        "arguments": arguments,
    }


def apply_openai_tool_call_response(response: dict[str, Any], text: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = _normalize_tool_call(text, payload)
    if not tool_call:
        return response

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return response

    choice = choices[0]
    if not isinstance(choice, dict):
        return response

    choice["finish_reason"] = "tool_calls"
    choice["message"] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": compact_json(tool_call["arguments"]),
                },
            }
        ],
    }
    return response


def apply_anthropic_tool_use_response(response: dict[str, Any], text: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = _normalize_tool_call(text, payload)
    if not tool_call:
        return response

    response["stop_reason"] = "tool_use"
    response["content"] = [
        {
            "type": "tool_use",
            "id": tool_call["id"].replace("call_", "toolu_"),
            "name": tool_call["name"],
            "input": tool_call["arguments"],
        }
    ]
    return response


def message_summary(messages: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary

    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        content_chars = len(compact_json(content) if not isinstance(content, str) else content)
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})

    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def anthropic_messages_summary(messages: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": 0,
        "roles": {},
        "chars": 0,
    }
    if not isinstance(messages, list):
        return summary

    roles: dict[str, int] = {}
    chars = 0
    canonical: list[dict[str, Any]] = []

    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = item.get("content", "")
        if isinstance(content, list):
            content_chars = sum(
                len(str(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            content_chars = len(str(content))
        roles[role] = roles.get(role, 0) + 1
        chars += content_chars
        canonical.append({"role": role, "chars": content_chars})

    summary.update(
        {
            "count": len(canonical),
            "roles": roles,
            "chars": chars,
        }
    )
    return summary


def build_anthropic_response(
    text: str,
    model: str,
    started: float,
    routed: dict[str, Any],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"msg_{int(started * 1000)}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 0,
            "output_tokens": max(1, len(text.split())),
        },
        "lmm": {
            "route_target": routed.get("target", "unknown"),
            "route_reason_code": routed.get("reason_code", "unknown"),
            "context_status": pipeline.get("context_status", "unknown"),
            "context_used": bool(pipeline.get("context_used")),
            "glyph_encoding_status": pipeline.get("glyph_encoding_status", "skipped"),
            "latency_ms": routed.get("latency_ms", 0),
        },
    }


__all__ = [
    "compact_json",
    "messages_to_prompt",
    "anthropic_messages_to_text",
    "format_tool_contract",
    "append_tool_contract_to_prompt",
    "apply_openai_tool_call_response",
    "apply_anthropic_tool_use_response",
    "message_summary",
    "anthropic_messages_summary",
    "build_anthropic_response",
]
