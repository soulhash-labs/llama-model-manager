"""
GlyphOS Semantic Encoder
========================

Author: Angelo Kapantais / Soul Hash Labs

Purpose:
    Encode structured Intent / packet semantics into a reversible GlyphOS glyph string.

Design:
    - Intent -> compact canonical semantic payload -> GlyphOS glyph stream.
    - No raw natural-language prompt transport.
    - Stable canonical format for hashing, transport, and roundtrip verification.
    - Compatible with object-style packets and mapping/dict packets.
    - Uses GlyphOS encoder.encode_text().
    - Fails closed if encoder is unavailable.
    - No retrieval, network I/O, hidden context loading, or filesystem mutation.

Semantic wire format:
    GIS1|a=<ACTION>|d=<DESTINATION>|t=<TIME_SLOT>|p=<PSI>|i=<INSTANCE_ID>

Field aliases:
    a = action
    d = destination
    t = time_slot
    p = psi_coherence
    i = instance_id

The semantic payload is intentionally compact before glyph encoding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

try:
    from ..glyph.encoder import encode_text
except Exception as exc:  # pragma: no cover - fail closed if package import is broken
    encode_text = None  # type: ignore[assignment]
    _ENCODER_IMPORT_ERROR = exc
else:
    _ENCODER_IMPORT_ERROR = None


SEMANTIC_INTENT_VERSION = "GIS1"
DEFAULT_TIME_SLOT = "T00"
DEFAULT_PSI_COHERENCE = 0.5
DEFAULT_GLYPH_DELIMITER = " "


class SemanticEncodingError(RuntimeError):
    """Raised when semantic intent cannot be encoded safely."""


@dataclass(frozen=True)
class SemanticIntentPayload:
    """
    Canonical semantic payload before glyph encoding.

    This is not natural-language prompt text. It is compact structured intent.
    """

    action: str
    destination: str
    time_slot: str = DEFAULT_TIME_SLOT
    psi_coherence: float = DEFAULT_PSI_COHERENCE
    instance_id: str = ""

    def to_wire(self) -> str:
        return _pack_semantic_wire(
            action=self.action,
            destination=self.destination,
            time_slot=self.time_slot,
            psi_coherence=self.psi_coherence,
            instance_id=self.instance_id,
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.to_wire().encode("utf-8")).hexdigest()


def _read_field(source: Any, *names: str, default: Any = None) -> Any:
    if source is None:
        return default

    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return default

    if is_dataclass(source):
        data = asdict(source)
        for name in names:
            if name in data and data[name] is not None:
                return data[name]
        return default

    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value

    return default


def _escape_field(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\p").replace("=", "\\e").replace("\n", "\\n").replace("\r", "\\r")


def _normalize_action(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return (text or "DEFAULT").upper()


def _normalize_destination(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or "unspecified target"


def _normalize_time_slot(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or DEFAULT_TIME_SLOT


def _normalize_psi(value: Any) -> float:
    if value is None:
        return DEFAULT_PSI_COHERENCE
    try:
        psi = float(value)
    except (TypeError, ValueError):
        return DEFAULT_PSI_COHERENCE
    return min(1.0, max(0.0, psi))


def _normalize_instance_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def semantic_payload_from_intent(
    intent: Any,
    *,
    instance_id: str | None = None,
    psi_coherence: float | None = None,
) -> SemanticIntentPayload:
    action = _normalize_action(_read_field(intent, "action", default="DEFAULT"))
    destination = _normalize_destination(_read_field(intent, "destination", "target", default="unspecified target"))
    time_slot = _normalize_time_slot(_read_field(intent, "time_slot", "timeSlot", default=DEFAULT_TIME_SLOT))

    resolved_psi = (
        psi_coherence
        if psi_coherence is not None
        else _read_field(intent, "psi_coherence", "psiCoherence", default=DEFAULT_PSI_COHERENCE)
    )
    resolved_instance_id = (
        instance_id if instance_id is not None else _read_field(intent, "instance_id", "instanceId", default="")
    )

    return SemanticIntentPayload(
        action=action,
        destination=destination,
        time_slot=time_slot,
        psi_coherence=_normalize_psi(resolved_psi),
        instance_id=_normalize_instance_id(resolved_instance_id),
    )


def semantic_payload_from_packet(packet: Any) -> SemanticIntentPayload:
    return semantic_payload_from_intent(packet)


def _pack_semantic_wire(
    *,
    action: str,
    destination: str,
    time_slot: str,
    psi_coherence: float,
    instance_id: str,
) -> str:
    psi_text = f"{_normalize_psi(psi_coherence):.6f}".rstrip("0").rstrip(".")
    if not psi_text:
        psi_text = "0"

    fields = [
        SEMANTIC_INTENT_VERSION,
        f"a={_escape_field(_normalize_action(action))}",
        f"d={_escape_field(_normalize_destination(destination))}",
        f"t={_escape_field(_normalize_time_slot(time_slot))}",
        f"p={_escape_field(psi_text)}",
        f"i={_escape_field(_normalize_instance_id(instance_id))}",
    ]
    return "|".join(fields)


def encode_semantic_wire_to_glyphs(
    semantic_wire: str,
    *,
    include_header: bool = True,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> str:
    if encode_text is None:
        raise SemanticEncodingError(
            f"GlyphOS encoder is unavailable; cannot encode semantic intent. Import error: {_ENCODER_IMPORT_ERROR!r}"
        )

    try:
        return str(
            encode_text(
                semantic_wire,
                include_header=include_header,
                delimiter=delimiter,
            )
        )
    except TypeError:
        try:
            return str(encode_text(semantic_wire, include_header=include_header))
        except TypeError:
            return str(encode_text(semantic_wire))
    except Exception as exc:
        raise SemanticEncodingError(f"GlyphOS semantic encoding failed: {exc}") from exc


def encode_intent_to_glyphs(
    intent: Any,
    *,
    instance_id: str | None = None,
    psi_coherence: float | None = None,
    include_header: bool = True,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> str:
    payload = semantic_payload_from_intent(
        intent,
        instance_id=instance_id,
        psi_coherence=psi_coherence,
    )
    return encode_semantic_wire_to_glyphs(
        payload.to_wire(),
        include_header=include_header,
        delimiter=delimiter,
    )


def encode_packet_to_glyphs(
    packet: Any,
    *,
    include_header: bool = True,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> str:
    payload = semantic_payload_from_packet(packet)
    return encode_semantic_wire_to_glyphs(
        payload.to_wire(),
        include_header=include_header,
        delimiter=delimiter,
    )


def semantic_encoding_manifest(
    intent: Any,
    *,
    instance_id: str | None = None,
    psi_coherence: float | None = None,
) -> dict[str, Any]:
    payload = semantic_payload_from_intent(
        intent,
        instance_id=instance_id,
        psi_coherence=psi_coherence,
    )
    wire = payload.to_wire()
    return {
        "semantic_version": SEMANTIC_INTENT_VERSION,
        "wire_sha256": payload.sha256(),
        "wire_chars": len(wire),
        "wire_utf8_bytes": len(wire.encode("utf-8")),
        "fields": {
            "action": payload.action,
            "destination": payload.destination,
            "time_slot": payload.time_slot,
            "psi_coherence": payload.psi_coherence,
            "instance_id": payload.instance_id,
        },
    }


__all__ = [
    "SEMANTIC_INTENT_VERSION",
    "DEFAULT_GLYPH_DELIMITER",
    "SemanticEncodingError",
    "SemanticIntentPayload",
    "semantic_payload_from_intent",
    "semantic_payload_from_packet",
    "encode_semantic_wire_to_glyphs",
    "encode_intent_to_glyphs",
    "encode_packet_to_glyphs",
    "semantic_encoding_manifest",
]
