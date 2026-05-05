from __future__ import annotations

import json
from typing import Any


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


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
        content = item.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text", ""))
                    if text:
                        parts.append(text)
                elif isinstance(part, str):
                    parts.append(part)
            content_text = "\n".join(parts)
        else:
            content_text = str(content)
        if content_text.strip():
            lines.append(f"{role}: {content_text.strip()}")
    return "\n\n".join(lines)


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
    "message_summary",
    "anthropic_messages_summary",
    "build_anthropic_response",
]
