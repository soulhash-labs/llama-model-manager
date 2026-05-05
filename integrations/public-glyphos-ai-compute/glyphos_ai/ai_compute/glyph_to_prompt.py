"""
Glyph-to-Prompt Translation
===========================
Converts glyph packets to optimized LLM prompts while preserving privacy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..glyph.types import ContextPacket, ContextPayload, validate_context_packet_shape

GLYPH_PROMPT_TEMPLATES: dict[str, str] = {
    "BOOK": "User wants to {action_destination} at time {time_slot}. Coherence: {psi_level}. Provide actionable response.",
    "QUERY": "User queries {destination}. Coherence: {psi_description}. Provide concise answer.",
    "CREATE": "Create new {destination}. Coherence: {psi_level}. Execute with appropriate parameters.",
    "EXECUTE": "Execute {destination}. Coherence: {psi_level}. Optimize for current mental state.",
    "VERIFY": "Verify {destination} status. Coherence: {psi_description}. Report validation result.",
    "GRANT": "Grant access to {destination}. Coherence: {psi_description}. Process with verification.",
    "DELETE": "Delete {destination}. Coherence: {psi_level}. Confirm with safety checks.",
    "UPDATE": "Update {destination}. Coherence: {psi_description}. Apply changes with validation.",
    "ANALYZE": "Analyze {destination} in depth. Coherence: {psi_level}. Provide detailed analysis.",
    "SYNTHESIZE": "Synthesize {destination}. Coherence: {psi_level}. Create comprehensive output.",
    "PREDICT": "Predict {destination}. Coherence: {psi_description}. Provide forecast with confidence.",
    "DEFAULT": "Process {action_destination}. Coherence: {psi_description}. Respond appropriately.",
}


COHERENCE_DESCRIPTIONS = {
    (0.0, 0.3): "low - keep simple and grounding",
    (0.3, 0.5): "moderate - provide balanced response",
    (0.5, 0.7): "good - standard detailed response",
    (0.7, 0.9): "high - provide nuanced response",
    (0.9, 1.01): "optimal - deliver comprehensive response",
}


TIME_INTERPRETATIONS = {
    "T00": "immediate",
    "T01": "within 1 hour",
    "T02": "within 2 hours",
    "T03": "within 3 hours",
    "T06": "within 6 hours",
    "T12": "within 12 hours",
    "T24": "within 24 hours",
    "T48": "within 2 days",
    "T72": "within 3 days",
    "T99": "unspecified future",
}


def _get_coherence_description(psi: float) -> str:
    """Get description for coherence level."""
    for (low, high), desc in COHERENCE_DESCRIPTIONS.items():
        if low <= psi < high:
            return desc
    return "unknown"


def _get_coherence_level(psi: float) -> str:
    """Get coherence level string."""
    if psi >= 0.8:
        return "high coherence"
    elif psi >= 0.5:
        return "moderate coherence"
    return "low coherence"


def _interpret_time(time_slot: str) -> str:
    """Interpret time slot to human-readable string."""
    return TIME_INTERPRETATIONS.get(time_slot, "specified time")


def _packet_value(packet: Any, snake_name: str, camel_name: str, default: Any) -> Any:
    """Read packet fields while tolerating either snake_case or camelCase names."""
    snake_value = getattr(packet, snake_name, None)
    if snake_value is not None:
        return snake_value
    camel_value = getattr(packet, camel_name, None)
    if camel_value is not None:
        return camel_value
    return default


def _normalize_upstream_context(
    upstream_context: str | ContextPacket | None = None,
    context: dict | None = None,
) -> ContextPacket:
    candidate: Any = upstream_context if upstream_context is not None else context
    if candidate is None:
        return {}
    if isinstance(candidate, str):
        return {"content": candidate}
    if isinstance(candidate, Mapping):
        return validate_context_packet_shape(dict(candidate))
    return {"content": str(candidate)}


def _format_context_metadata(ctx: ContextPacket) -> str:
    lines: list[str] = []

    locality = ctx.get("locality")
    if locality:
        lines.append(f"locality: {locality}")

    freshness = ctx.get("freshness")
    if freshness is not None:
        lines.append(f"freshness: {freshness}")

    provenance = ctx.get("provenance") or []
    if provenance:
        lines.append("provenance: " + ", ".join(str(item) for item in provenance))

    routing_hints = ctx.get("routing_hints") or {}
    if routing_hints:
        lines.append("routing_hints: " + json.dumps(routing_hints, ensure_ascii=False, sort_keys=True))

    metadata = ctx.get("metadata") or {}
    if metadata:
        lines.append("metadata: " + json.dumps(metadata, ensure_ascii=False, sort_keys=True))

    return "\n".join(lines)


def _preferred_backend_from_context(ctx: ContextPacket, psi_coherence: float) -> tuple[str, str]:
    hints = ctx.get("routing_hints") or {}
    preferred = hints.get("preferred_backend") if isinstance(hints, dict) else None
    if preferred:
        return str(preferred), "routing_hints"

    locality = ctx.get("locality")
    if locality in {"orion-local", "lan"}:
        return "local", "locality"
    if locality in {"cloud", "external"}:
        return "external", "locality"

    return ("local" if psi_coherence >= 0.8 else "external"), "coherence_default"


def glyph_to_prompt(
    glyph_packet: Any,
    context: dict | None = None,
    upstream_context: str | ContextPacket | None = None,
) -> str:
    """Convert glyph packet to LLM prompt.

    Args:
        glyph_packet: Object with action, destination, timeSlot, psiCoherence, instanceId
        context: Optional additional context

    Returns:
        Optimized prompt string for LLM
    """
    template = GLYPH_PROMPT_TEMPLATES.get(glyph_packet.action, GLYPH_PROMPT_TEMPLATES["DEFAULT"])

    time_slot = _packet_value(glyph_packet, "time_slot", "timeSlot", "T00")
    psi_coherence = float(_packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5) or 0.5)

    prompt = template.format(
        action_destination=f"{glyph_packet.action.lower()} {glyph_packet.destination}",
        time_slot=_interpret_time(time_slot),
        psi_description=_get_coherence_description(psi_coherence),
        psi_level=_get_coherence_level(psi_coherence),
        destination=glyph_packet.destination,
    )

    # Add coherence-based instructions
    if psi_coherence >= 0.8:
        prompt += "\n\nUser in optimal state - comprehensive insights welcome."
    elif psi_coherence < 0.5:
        prompt += "\n\nUser may need grounding - keep practical."

    ctx = _normalize_upstream_context(upstream_context=upstream_context, context=context)
    if ctx:
        content = str(ctx.get("content", "")).strip()
        prompt += "\n\n[CONTEXT_ANCHOR]\n"
        prompt += content if content else "[metadata-only context packet]"

        metadata_block = _format_context_metadata(ctx)
        if metadata_block:
            prompt += f"\n\n[CONTEXT_METADATA]\n{metadata_block}"

    return prompt.strip()


def glyph_to_structured_json(
    glyph_packet: Any,
    upstream_context: str | ContextPacket | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Convert glyph packet to structured JSON.

    Args:
        glyph_packet: Object with action, destination, timeSlot/time_slot, psiCoherence/psi_coherence, instance_id/instanceId

    Returns:
        Structured dictionary for API calls
    """
    time_slot = _packet_value(glyph_packet, "time_slot", "timeSlot", "T00")
    psi_coherence = float(_packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5) or 0.5)
    instance_id = _packet_value(glyph_packet, "instance_id", "instanceId", "")
    ctx = _normalize_upstream_context(upstream_context=upstream_context, context=context)
    preferred_backend, preferred_backend_source = _preferred_backend_from_context(ctx, psi_coherence)

    return {
        "intent": {
            "action": glyph_packet.action,
            "target": glyph_packet.destination,
            "time": time_slot,
            "priority": "high" if psi_coherence >= 0.8 else "normal",
        },
        "context": {
            "coherence": psi_coherence,
            "coherence_level": _get_coherence_level(psi_coherence),
            "instance_id": instance_id,
            "upstream_context_present": bool(ctx),
            "upstream_content_present": bool(str(ctx.get("content", "")).strip()) if ctx else False,
            "upstream": {
                "content": ctx.get("content") if ctx else None,
                "locality": ctx.get("locality") if ctx else None,
                "freshness": ctx.get("freshness") if ctx else None,
                "provenance": ctx.get("provenance", []) if ctx else [],
                "metadata": ctx.get("metadata", {}) if ctx else {},
            },
        },
        "routing": {
            "suggested_provider": preferred_backend,
            "preferred_backend": preferred_backend,
            "preferred_backend_source": preferred_backend_source,
            "routing_hints": ctx.get("routing_hints", {}) if ctx else {},
            "complexity": "high" if glyph_packet.action in {"ANALYZE", "SYNTHESIZE", "PREDICT"} else "normal",
        },
    }


def build_prompt_from_packet(
    glyph_packet: Any,
    context_payload: ContextPayload | None = None,
    user_message: str = "",
    upstream_context: str | ContextPacket | None = None,
) -> str:
    """Build complete prompt from packet + encoding-aware context.

    If context_payload.encoding_status == "encoded":
        → Include Ψ encoding header + compact context (local llama.cpp)
    If context_payload.encoding_status is anything else or None:
        → Include raw context block (cloud backends, no encoding)

    Args:
        glyph_packet: GlyphPacket with action, destination, etc.
        context_payload: ContextPayload carrying raw + encoded context.
        user_message: The original user instruction text.

    Returns:
        Full prompt string ready for the target backend.
    """
    base = glyph_to_prompt(glyph_packet, upstream_context=upstream_context)

    if context_payload is not None:
        status = getattr(context_payload, "encoding_status", "none")
        raw = getattr(context_payload, "raw_context", "")
        encoded = getattr(context_payload, "encoded_context", "")
        fmt = getattr(context_payload, "encoding_format", "")

        if status == "encoded" and encoded:
            context_block = "\n".join(
                [
                    "[Glyph Encoding v1]",
                    "Decode this compact context before reasoning. Key aliases: p=path, f=file, t=title, u=uri, c=content, x=text, s=snippet, m=summary, r=score.",
                    f"Format: {fmt}",
                    encoded,
                ]
            )
        elif raw:
            context_block = "\n".join(
                [
                    "[Retrieved Context]",
                    raw,
                ]
            )
        else:
            context_block = ""
    else:
        context_block = ""

    parts: list[str] = []
    if context_block:
        parts.extend(
            [
                "System: Use retrieved context only as supporting evidence. "
                "The latest user instruction below overrides retrieved or encoded context.",
                context_block,
            ]
        )
    parts.append("[Conversation and latest user request]")
    parts.append(base)
    if user_message.strip():
        parts.append(f"User: {user_message.strip()}")

    return "\n\n".join(parts)


# Quick test
if __name__ == "__main__":

    class MockPacket:
        action = "BOOK"
        destination = "MARS"
        timeSlot = "T07"
        psiCoherence = 0.85
        instance_id = "abc123"

    packet = MockPacket()
    print("=== Glyph → Prompt Demo ===")
    print("Input: ⊕H • T07 |MRS>")
    print(f"ψ-Coherence: {packet.psiCoherence}")
    print(f"\nOutput Prompt:\n{glyph_to_prompt(packet)}")
    print(f"\nStructured JSON:\n{glyph_to_structured_json(packet)}")
