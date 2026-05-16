"""
GlyphOS SI Transport Builder
============================

Author: Angelo Kapantais / Soul Hash Labs

Purpose:
    Build privacy-preserving, token-reduced GlyphOS SI transport payloads.

Core rule:
    Raw prompt text is not transported.

Pipeline:
    raw user/context text
        -> GE1/context_encoding compression where useful
        -> GlyphOS SI reversible byte-level glyph encoding
        -> decoder roundtrip verification
        -> SHA-256 integrity hashes + transport metrics
        -> glyph-only transport payload

Design:
    - No plain fallback.
    - No raw prompt fallback.
    - No raw user_message transport.
    - No raw context transport.
    - Fail closed if encoder/decoder cannot verify transport.
    - Use context_encoding.encode_context() for token reduction.
    - Use encoder.encode_text() / decoder.decode_text() for privacy glyph transport.
    - Preserve legacy API:
        glyph_to_prompt(packet, context=...)
        glyph_to_structured_json(packet, context=...)
    - Preserve router compatibility:
        build_prompt_from_packet(
            packet,
            context_payload=...,
            user_message=...,
            upstream_context=...,
        )
    - No retrieval, network I/O, or hidden context loading.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

try:
    from ..glyph.context_encoding import encode_context
except Exception as exc:  # pragma: no cover - fail closed if package is broken
    encode_context = None  # type: ignore[assignment]
    _CONTEXT_ENCODING_IMPORT_ERROR = exc
else:
    _CONTEXT_ENCODING_IMPORT_ERROR = None


try:
    from .semantic_decoder import decode_intent_from_glyphs as _decode_intent_from_glyphs
    from .semantic_encoder import encode_intent_to_glyphs as _encode_intent_to_glyphs
except Exception:  # pragma: no cover - semantic layer is optional
    _encode_intent_to_glyphs = None  # type: ignore[assignment]
    _decode_intent_from_glyphs = None  # type: ignore[assignment]


try:
    from ..glyph.encoder import encode_text
except Exception as exc:  # pragma: no cover - fail closed if package is broken
    encode_text = None  # type: ignore[assignment]
    _ENCODER_IMPORT_ERROR = exc
else:
    _ENCODER_IMPORT_ERROR = None


try:
    from ..glyph.decoder import decode_text
except Exception as exc:  # pragma: no cover - fail closed if package is broken
    decode_text = None  # type: ignore[assignment]
    _DECODER_IMPORT_ERROR = exc
else:
    _DECODER_IMPORT_ERROR = None


try:
    from ..glyph.types import ContextPacket, ContextPayload
except Exception:

    class ContextPacket(TypedDict, total=False):
        content: str
        locality: Literal["orion-local", "lan", "cloud", "external"]
        freshness: float | None
        provenance: list[str]
        routing_hints: dict[str, Any]
        routingHints: dict[str, Any]
        metadata: dict[str, Any]

    class ContextPayload(TypedDict, total=False):
        raw_context: str
        raw_context_chars: int
        encoding_status: str
        encoding_format: str
        encoding_ratio: float
        # Legacy / alternate field names for backward compatibility
        content: str
        rawContext: str
        context: str
        encoded_context: str
        encodedContext: str
        encodingStatus: str
        encodingFormat: str
        encodingRatio: float
        rawContextChars: int
        estimated_token_delta: int
        estimatedTokenDelta: int
        error: str
        locality: str
        freshness: float | None
        provenance: list[str]
        routing_hints: dict[str, Any]
        routingHints: dict[str, Any]
        metadata: dict[str, Any]


GLYPHOS_SI_VERSION = "GlyphOS-SI-v1"
TRANSPORT_KIND = "glyph_only"
DEFAULT_GLYPH_DELIMITER = " "


TIME_INTERPRETATIONS: dict[str, str] = {
    "T00": "immediate",
    "T01": "within 1 hour",
    "T02": "within 2 hours",
    "T03": "within 3 hours",
    "T06": "within 6 hours",
    "T07": "within 7 hours",
    "T12": "within 12 hours",
    "T24": "within 24 hours",
    "T48": "within 2 days",
    "T72": "within 3 days",
    "T99": "unspecified future",
}


class GlyphTransportError(RuntimeError):
    """Raised when GlyphOS SI cannot safely produce glyph-only transport."""


class NormalizedContext(TypedDict):
    provided: bool
    raw_content: str | None
    encoded_context: str | None
    encoding_status: str | None
    encoding_format: str | None
    encoding_ratio: float | None
    raw_context_chars: int | None
    estimated_token_delta: int | None
    error: str | None
    locality: str | None
    freshness: float | None
    provenance: list[str]
    routing_hints: dict[str, Any]
    metadata: dict[str, Any]


class EncodedPart(TypedDict):
    label: str
    source_kind: str
    semantic_text: str
    glyph_stream: str
    encoding_format: str
    raw_sha256: str
    glyph_sha256: str
    raw_chars: int
    glyph_chars: int
    raw_utf8_bytes: int
    glyph_utf8_bytes: int
    estimated_token_delta: int | None
    roundtrip_verified: bool


def _read_field(source: Any, *names: str, default: Any = None) -> Any:
    if source is None:
        return default

    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return default

    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value

    return default


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_action(value: Any) -> str:
    text = _coerce_str(value, "DEFAULT").strip()
    return (text or "DEFAULT").upper()


def _normalize_destination(value: Any) -> str:
    text = _coerce_str(value, "unspecified target").strip()
    return text or "unspecified target"


def _normalize_time_slot(value: Any) -> str:
    text = _coerce_str(value, "T00").strip()
    return text or "T00"


def _normalize_psi(value: Any) -> float:
    if value is None:
        return 0.5
    try:
        psi = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(1.0, max(0.0, psi))


def _interpret_time(time_slot: str) -> str:
    return TIME_INTERPRETATIONS.get(str(time_slot), "specified time")


def _coherence_level(psi: float) -> str:
    if psi >= 0.8:
        return "high"
    if psi >= 0.5:
        return "moderate"
    return "low"


def _packet_fields(glyph_packet: Any) -> tuple[str, str, str, float, str]:
    action = _normalize_action(_read_field(glyph_packet, "action", default="DEFAULT"))
    destination = _normalize_destination(
        _read_field(
            glyph_packet,
            "destination",
            "target",
            default="unspecified target",
        )
    )
    time_slot = _normalize_time_slot(_read_field(glyph_packet, "time_slot", "timeSlot", default="T00"))
    psi_coherence = _normalize_psi(_read_field(glyph_packet, "psi_coherence", "psiCoherence", default=0.5))
    instance_id = _coerce_str(
        _read_field(glyph_packet, "instance_id", "instanceId", default=""),
        default="",
    )
    return action, destination, time_slot, psi_coherence, instance_id


def _existing_packet_glyph_stream(glyph_packet: Any) -> tuple[str | None, str | None]:
    glyph_stream = _read_field(
        glyph_packet,
        "glyph_stream",
        "glyphStream",
        "encoded_prompt",
        "encodedPrompt",
        "encoded_text",
        "encodedText",
        "glyphs",
        default=None,
    )
    encoding_format = _read_field(
        glyph_packet,
        "encoding_format",
        "encodingFormat",
        "glyph_format",
        "glyphFormat",
        default=None,
    )
    return _coerce_optional_str(glyph_stream), _coerce_optional_str(encoding_format)


def _resolve_explicit_context(
    *,
    context: Mapping[str, Any] | None = None,
    context_payload: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    upstream_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
) -> str | ContextPacket | ContextPayload | Mapping[str, Any] | None:
    """
    Resolve explicit caller-supplied context without hidden retrieval.

    Precedence:
    1. upstream_context — newest router/gateway API
    2. context_payload — GE1/encoded payload from context_encoding.py
    3. context — legacy glyph_to_prompt(packet, context={...}) API
    """
    if upstream_context is not None:
        return upstream_context
    if context_payload is not None:
        return context_payload
    return context


def _normalize_context(
    explicit_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None,
) -> NormalizedContext:
    empty: NormalizedContext = {
        "provided": False,
        "raw_content": None,
        "encoded_context": None,
        "encoding_status": None,
        "encoding_format": None,
        "encoding_ratio": None,
        "raw_context_chars": None,
        "estimated_token_delta": None,
        "error": None,
        "locality": None,
        "freshness": None,
        "provenance": [],
        "routing_hints": {},
        "metadata": {},
    }

    if explicit_context is None:
        return empty

    if isinstance(explicit_context, str):
        return {
            **empty,
            "provided": True,
            "raw_content": explicit_context.strip() or None,
        }

    raw_content = _read_field(
        explicit_context,
        "content",
        "raw_context",
        "rawContext",
        "context",
        default=None,
    )
    encoded_context = _read_field(
        explicit_context,
        "encoded_context",
        "encodedContext",
        "glyph_stream",
        "glyphStream",
        "glyphs",
        default=None,
    )

    return {
        "provided": True,
        "raw_content": _coerce_optional_str(raw_content),
        "encoded_context": _coerce_optional_str(encoded_context),
        "encoding_status": _coerce_optional_str(
            _read_field(
                explicit_context,
                "encoding_status",
                "encodingStatus",
                default=None,
            )
        ),
        "encoding_format": _coerce_optional_str(
            _read_field(
                explicit_context,
                "encoding_format",
                "encodingFormat",
                default=None,
            )
        ),
        "encoding_ratio": _coerce_optional_float(
            _read_field(
                explicit_context,
                "encoding_ratio",
                "encodingRatio",
                default=None,
            )
        ),
        "raw_context_chars": _coerce_optional_int(
            _read_field(
                explicit_context,
                "raw_context_chars",
                "rawContextChars",
                default=None,
            )
        ),
        "estimated_token_delta": _coerce_optional_int(
            _read_field(
                explicit_context,
                "estimated_token_delta",
                "estimatedTokenDelta",
                default=None,
            )
        ),
        "error": _coerce_optional_str(_read_field(explicit_context, "error", default=None)),
        "locality": _coerce_optional_str(_read_field(explicit_context, "locality", default=None)),
        "freshness": _coerce_optional_float(_read_field(explicit_context, "freshness", default=None)),
        "provenance": _coerce_string_list(_read_field(explicit_context, "provenance", default=[])),
        "routing_hints": _coerce_dict(
            _read_field(
                explicit_context,
                "routing_hints",
                "routingHints",
                default={},
            )
        ),
        "metadata": _coerce_dict(_read_field(explicit_context, "metadata", default={})),
    }


def _preferred_backend_from_context(
    psi_coherence: float,
    ctx: NormalizedContext,
) -> tuple[str, str]:
    hints = ctx["routing_hints"]
    preferred_backend = _read_field(
        hints,
        "preferred_backend",
        "preferredBackend",
        default=None,
    )
    if preferred_backend:
        return str(preferred_backend), "routing_hints"

    locality = ctx["locality"]
    if locality in {"orion-local", "lan"}:
        return "local", "locality"
    if locality in {"cloud", "external"}:
        return "external", "locality"

    return ("local" if psi_coherence >= 0.8 else "external"), "coherence_default"


def _canonical_intent_text(glyph_packet: Any) -> str:
    """
    Canonical intent text used only as encoder input.

    This text is never transported directly.
    """
    action, destination, time_slot, psi_coherence, instance_id = _packet_fields(glyph_packet)
    return json.dumps(
        {
            "action": action,
            "destination": destination,
            "time_slot": time_slot,
            "time_description": _interpret_time(time_slot),
            "psi_coherence": psi_coherence,
            "coherence_level": _coherence_level(psi_coherence),
            "instance_id": instance_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _call_encode_context(raw: str) -> Any:
    if encode_context is None:
        raise GlyphTransportError(
            "context_encoding.encode_context is unavailable; refusing SI transport. "
            f"Import error: {_CONTEXT_ENCODING_IMPORT_ERROR!r}"
        )

    try:
        return encode_context(raw)
    except TypeError:
        # Compatibility if a future/older encoder requires keyword naming.
        return encode_context(raw_context=raw)


def _ge1_compress_text(raw: str, *, label: str) -> tuple[str, dict[str, Any]]:
    """
    Apply GE1/context_encoding compression where useful.

    If GE1 cannot improve size, preserve raw as encoder input.
    Raw is still never transported directly; it is glyph-encoded later.
    """
    if raw is None:
        raise GlyphTransportError(f"{label} cannot be None")

    payload = _call_encode_context(raw)

    status = _coerce_optional_str(_read_field(payload, "encoding_status", "encodingStatus", default=None))
    encoded = _coerce_optional_str(_read_field(payload, "encoded_context", "encodedContext", default=None))
    fmt = _coerce_optional_str(_read_field(payload, "encoding_format", "encodingFormat", default=None))
    ratio = _coerce_optional_float(_read_field(payload, "encoding_ratio", "encodingRatio", default=None))
    raw_chars = _coerce_optional_int(_read_field(payload, "raw_context_chars", "rawContextChars", default=None))
    estimated_delta = _coerce_optional_int(
        _read_field(
            payload,
            "estimated_token_delta",
            "estimatedTokenDelta",
            default=None,
        )
    )
    error = _coerce_optional_str(_read_field(payload, "error", default=None))

    if status == "encoded" and encoded:
        return encoded, {
            "semantic_compression": "GE1",
            "semantic_status": status,
            "semantic_format": fmt,
            "semantic_ratio": ratio,
            "semantic_raw_chars": raw_chars,
            "estimated_token_delta": estimated_delta,
            "semantic_error": error,
            "semantic_used": True,
        }

    return raw, {
        "semantic_compression": "GE1",
        "semantic_status": status,
        "semantic_format": fmt,
        "semantic_ratio": ratio,
        "semantic_raw_chars": raw_chars,
        "estimated_token_delta": estimated_delta,
        "semantic_error": error,
        "semantic_used": False,
    }


def _call_encode_text(
    semantic_text: str,
    *,
    include_header: bool,
    delimiter: str,
) -> str:
    if encode_text is None:
        raise GlyphTransportError(
            "GlyphOS SI encoder is unavailable; refusing to transport raw text. "
            f"Import error: {_ENCODER_IMPORT_ERROR!r}"
        )

    try:
        encoded = encode_text(
            semantic_text,
            include_header=include_header,
            delimiter=delimiter,
        )
    except TypeError:
        try:
            encoded = encode_text(semantic_text, include_header=include_header)
        except TypeError:
            encoded = encode_text(semantic_text)

    return str(encoded)


def _call_decode_text(glyph_stream: str, *, delimiter: str) -> str:
    if decode_text is None:
        raise GlyphTransportError(
            "GlyphOS SI decoder is unavailable; refusing unverified glyph transport. "
            f"Import error: {_DECODER_IMPORT_ERROR!r}"
        )

    try:
        decoded = decode_text(glyph_stream, delimiter=delimiter, strict=True)
    except TypeError:
        try:
            decoded = decode_text(glyph_stream, delimiter=delimiter)
        except TypeError:
            decoded = decode_text(glyph_stream)

    return str(decoded)


def _glyph_encode_verified(
    semantic_text: str,
    *,
    label: str,
    include_header: bool = True,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> EncodedPart:
    """
    Encode semantic text into GlyphOS glyph stream and verify roundtrip.

    Fails closed if encoder/decoder is unavailable or roundtrip fails.
    """
    glyph_stream = _call_encode_text(
        semantic_text,
        include_header=include_header,
        delimiter=delimiter,
    )

    if not glyph_stream.strip():
        raise GlyphTransportError(f"{label} GlyphOS SI produced an empty glyph stream")

    decoded = _call_decode_text(glyph_stream, delimiter=delimiter)

    if decoded != semantic_text:
        raise GlyphTransportError(
            f"{label} GlyphOS SI roundtrip mismatch: "
            f"decoded_sha256={_sha256_text(decoded)} "
            f"raw_sha256={_sha256_text(semantic_text)}"
        )

    return {
        "label": label,
        "source_kind": "semantic_text",
        "semantic_text": semantic_text,
        "glyph_stream": glyph_stream,
        "encoding_format": "glyphos_ai.glyph.encoder.encode_text",
        "raw_sha256": _sha256_text(semantic_text),
        "glyph_sha256": _sha256_text(glyph_stream),
        "raw_chars": len(semantic_text),
        "glyph_chars": len(glyph_stream),
        "raw_utf8_bytes": len(semantic_text.encode("utf-8")),
        "glyph_utf8_bytes": len(glyph_stream.encode("utf-8")),
        "estimated_token_delta": None,
        "roundtrip_verified": True,
    }


def _packet_glyph_part(glyph_packet: Any) -> EncodedPart | None:
    """
    Use packet-provided glyph stream if present.

    It may not be roundtrip-verifiable here without the original raw text, so
    roundtrip_verified=False but glyph integrity is still hashed.
    """
    glyph_stream, fmt = _existing_packet_glyph_stream(glyph_packet)
    if not glyph_stream:
        return None

    return {
        "label": "primary",
        "source_kind": "packet_glyph_stream",
        "semantic_text": "",
        "glyph_stream": glyph_stream,
        "encoding_format": fmt or "packet-provided",
        "raw_sha256": "",
        "glyph_sha256": _sha256_text(glyph_stream),
        "raw_chars": 0,
        "glyph_chars": len(glyph_stream),
        "raw_utf8_bytes": 0,
        "glyph_utf8_bytes": len(glyph_stream.encode("utf-8")),
        "estimated_token_delta": None,
        "roundtrip_verified": False,
    }


def _primary_part(
    glyph_packet: Any,
    user_message: str | None,
) -> tuple[EncodedPart, dict[str, Any]]:
    packet_part = _packet_glyph_part(glyph_packet)
    if packet_part is not None:
        return packet_part, {
            "semantic_compression": "none",
            "semantic_status": "packet_glyph_stream",
            "semantic_used": False,
        }

    psi_raw = _read_field(glyph_packet, "psi_coherence", "psiCoherence", default=0.5)
    try:
        psi = float(psi_raw)
    except (TypeError, ValueError):
        psi = 0.5

    if psi >= 0.7 and _encode_intent_to_glyphs is not None:
        try:
            glyph_string = _encode_intent_to_glyphs(glyph_packet)
            if glyph_string:
                return {
                    "label": "primary",
                    "source_kind": "semantic_intent",
                    "semantic_text": glyph_string,
                    "glyph_stream": glyph_string,
                    "encoding_format": "semantic-intent",
                    "raw_sha256": _sha256_text(glyph_string),
                    "glyph_sha256": _sha256_text(glyph_string),
                    "raw_chars": len(glyph_string),
                    "glyph_chars": len(glyph_string),
                    "raw_utf8_bytes": len(glyph_string.encode("utf-8")),
                    "glyph_utf8_bytes": len(glyph_string.encode("utf-8")),
                    "estimated_token_delta": None,
                    "roundtrip_verified": True,
                }, {
                    "semantic_compression": "semantic-intent",
                    "semantic_status": "encoded",
                    "semantic_used": True,
                    "semantic_raw_chars": len(_canonical_intent_text(glyph_packet)),
                    "estimated_token_delta": None,
                }
        except Exception:
            pass

    raw = user_message.strip() if user_message and user_message.strip() else _canonical_intent_text(glyph_packet)
    semantic_text, compression_meta = _ge1_compress_text(raw, label="primary")
    part = _glyph_encode_verified(semantic_text, label="primary")
    part["estimated_token_delta"] = compression_meta.get("estimated_token_delta")
    return part, compression_meta


def _context_part(ctx: NormalizedContext) -> tuple[EncodedPart | None, dict[str, Any]]:
    if not ctx["provided"]:
        return None, {"context_source": "none"}

    if ctx["encoded_context"]:
        semantic_text = ctx["encoded_context"]
        compression_meta = {
            "context_source": "context_payload.encoded_context",
            "semantic_compression": "GE1",
            "semantic_status": ctx["encoding_status"],
            "semantic_format": ctx["encoding_format"],
            "semantic_ratio": ctx["encoding_ratio"],
            "semantic_raw_chars": ctx["raw_context_chars"],
            "estimated_token_delta": ctx["estimated_token_delta"],
            "semantic_error": ctx["error"],
            "semantic_used": True,
        }
    elif ctx["raw_content"]:
        semantic_text, compression_meta = _ge1_compress_text(
            ctx["raw_content"],
            label="context",
        )
        compression_meta = {
            **compression_meta,
            "context_source": "raw_context",
        }
    else:
        return None, {"context_source": "metadata_only"}

    part = _glyph_encode_verified(semantic_text, label="context")
    part["estimated_token_delta"] = compression_meta.get("estimated_token_delta")
    return part, compression_meta


def _safe_metadata_for_transport(
    ctx: NormalizedContext,
    *,
    external: bool = True,
) -> dict[str, Any]:
    """
    Keep metadata bounded and non-sensitive.

    External mode intentionally does not include raw provenance strings because
    they can leak paths, filenames, people, project names, or repo secrets.
    """
    metadata: dict[str, Any] = {
        "locality": ctx["locality"],
        "freshness": ctx["freshness"],
        "routing_hints": ctx["routing_hints"],
        "context_provided": ctx["provided"],
        "context_encoding_status": ctx["encoding_status"],
        "context_encoding_format": ctx["encoding_format"],
        "context_encoding_ratio": ctx["encoding_ratio"],
        "context_estimated_token_delta": ctx["estimated_token_delta"],
    }

    if external:
        metadata["provenance_count"] = len(ctx["provenance"])
        metadata["metadata_keys"] = sorted(str(key) for key in ctx["metadata"])
    else:
        metadata["provenance"] = ctx["provenance"]
        metadata["metadata"] = ctx["metadata"]

    return metadata


def _transport_metadata(
    glyph_packet: Any,
    ctx: NormalizedContext,
    primary: EncodedPart,
    primary_compression: dict[str, Any],
    context_part: EncodedPart | None,
    context_compression: dict[str, Any],
    *,
    target_privacy_level: Literal["external", "local"],
) -> dict[str, Any]:
    action, destination, time_slot, psi_coherence, instance_id = _packet_fields(glyph_packet)
    preferred_backend, preferred_backend_source = _preferred_backend_from_context(
        psi_coherence,
        ctx,
    )

    total_raw_bytes = primary["raw_utf8_bytes"] + (context_part["raw_utf8_bytes"] if context_part else 0)
    total_glyph_bytes = primary["glyph_utf8_bytes"] + (context_part["glyph_utf8_bytes"] if context_part else 0)
    total_estimated_token_delta = sum(
        value
        for value in [
            primary["estimated_token_delta"],
            context_part["estimated_token_delta"] if context_part else None,
        ]
        if isinstance(value, int)
    )

    return {
        "si_version": GLYPHOS_SI_VERSION,
        "transport": TRANSPORT_KIND,
        "raw_prompt_transported": False,
        "raw_context_transported": False,
        "target_privacy_level": target_privacy_level,
        "intent": {
            "action": action,
            "destination": destination,
            "time_slot": time_slot,
            "time_description": _interpret_time(time_slot),
            "psi_coherence": psi_coherence,
            "coherence_level": _coherence_level(psi_coherence),
            "instance_id": instance_id,
        },
        "routing": {
            "preferred_backend": preferred_backend,
            "preferred_backend_source": preferred_backend_source,
        },
        "codec": {
            "primary_encoding_format": primary["encoding_format"],
            "decoder": "glyphos_ai.glyph.decoder.decode_text",
            "byte_level": True,
            "unicode_roundtrip": True,
            "primary_roundtrip_verified": primary["roundtrip_verified"],
            "context_roundtrip_verified": (context_part["roundtrip_verified"] if context_part else None),
        },
        "integrity": {
            "primary_raw_sha256": primary["raw_sha256"],
            "primary_glyph_sha256": primary["glyph_sha256"],
            "context_raw_sha256": context_part["raw_sha256"] if context_part else None,
            "context_glyph_sha256": (context_part["glyph_sha256"] if context_part else None),
        },
        "semantic_compression": {
            "primary": primary_compression,
            "context": context_compression,
        },
        "transport_metrics": {
            "primary_raw_chars": primary["raw_chars"],
            "primary_glyph_chars": primary["glyph_chars"],
            "primary_raw_utf8_bytes": primary["raw_utf8_bytes"],
            "primary_glyph_utf8_bytes": primary["glyph_utf8_bytes"],
            "context_raw_chars": context_part["raw_chars"] if context_part else 0,
            "context_glyph_chars": context_part["glyph_chars"] if context_part else 0,
            "context_raw_utf8_bytes": (context_part["raw_utf8_bytes"] if context_part else 0),
            "context_glyph_utf8_bytes": (context_part["glyph_utf8_bytes"] if context_part else 0),
            "total_raw_utf8_bytes": total_raw_bytes,
            "total_glyph_utf8_bytes": total_glyph_bytes,
            "glyph_to_raw_byte_ratio": (round(total_glyph_bytes / total_raw_bytes, 6) if total_raw_bytes else None),
            "estimated_token_delta": total_estimated_token_delta,
        },
        "context": _safe_metadata_for_transport(
            ctx,
            external=target_privacy_level == "external",
        ),
    }


def _json_block(label: str, payload: Any) -> str:
    return f"[{label}]\n" + json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _text_block(label: str, payload: str) -> str:
    return f"[{label}]\n{payload}"


def build_si_transport(
    glyph_packet: Any,
    *,
    context: Mapping[str, Any] | None = None,
    context_payload: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    user_message: str | None = None,
    upstream_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    target_privacy_level: Literal["external", "local"] = "external",
) -> str:
    """
    Build a production-grade GlyphOS SI transport payload.

    Args:
        glyph_packet:
            Object with action, destination, timeSlot/time_slot,
            psiCoherence/psi_coherence, instanceId/instance_id.
        context:
            Optional additional explicit context. Legacy argument retained.
        context_payload:
            GE1/encoded context payload from context_encoding.py.
        user_message:
            Latest user instruction. GE1-compressed where useful, glyph-encoded,
            roundtrip-verified, and never transported raw.
        upstream_context:
            Explicit harness-supplied context. Takes precedence.
        target_privacy_level:
            "external" redacts provenance/metadata values.
            "local" preserves provenance/metadata values.

    Returns:
        GlyphOS SI glyph-only transport payload.
    """
    if target_privacy_level not in {"external", "local"}:
        raise ValueError("target_privacy_level must be 'external' or 'local'")

    explicit_context = _resolve_explicit_context(
        context=context,
        context_payload=context_payload,
        upstream_context=upstream_context,
    )
    ctx = _normalize_context(explicit_context)

    primary, primary_compression = _primary_part(
        glyph_packet,
        user_message=user_message,
    )
    context_encoded_part, context_compression = _context_part(ctx)

    metadata = _transport_metadata(
        glyph_packet,
        ctx,
        primary,
        primary_compression,
        context_encoded_part,
        context_compression,
        target_privacy_level=target_privacy_level,
    )

    blocks = [
        _json_block("GLYPHOS_SI", metadata),
        _text_block("GLYPH_STREAM", primary["glyph_stream"]),
    ]

    if context_encoded_part is not None:
        blocks.append(
            _text_block(
                "CONTEXT_GLYPH_STREAM",
                context_encoded_part["glyph_stream"],
            )
        )

    return "\n\n".join(blocks).strip()


def glyph_to_prompt(
    glyph_packet: Any,
    context: dict | None = None,
    upstream_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
) -> str:
    """
    Convert GlyphOS packet to GlyphOS SI transport payload.

    Args:
        glyph_packet:
            Object with action, destination, timeSlot/time_slot,
            psiCoherence/psi_coherence, instanceId/instance_id.
        context:
            Optional additional explicit context. Legacy argument retained for
            backward compatibility. It is never retrieved implicitly and is
            glyph-encoded before transport.
        upstream_context:
            Explicit harness-supplied context. Takes precedence over context.

    Returns:
        GlyphOS SI glyph-only transport payload for LLM/gateway routing.
        This is not raw natural-language prompt text.
    """
    return build_si_transport(
        glyph_packet,
        context=context,
        upstream_context=upstream_context,
    )


def build_prompt_from_packet(
    glyph_packet: Any,
    context_payload: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    *,
    user_message: str | None = None,
    upstream_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    context: dict | None = None,
    target_privacy_level: Literal["external", "local"] = "external",
) -> str:
    """
    Router/gateway compatibility wrapper.

    Args:
        glyph_packet:
            Object with action, destination, timeSlot/time_slot,
            psiCoherence/psi_coherence, instanceId/instance_id.
        context_payload:
            GE1/encoded context payload from context_encoding.py.
        user_message:
            Latest user instruction. Encoded into GlyphOS SI; never transported raw.
        upstream_context:
            Explicit harness-supplied context.
        context:
            Legacy optional context argument.
        target_privacy_level:
            "external" redacts provenance/metadata values.
            "local" preserves provenance/metadata values.

    Returns:
        GlyphOS SI glyph-only transport payload.
    """
    return build_si_transport(
        glyph_packet,
        context=context,
        context_payload=context_payload,
        user_message=user_message,
        upstream_context=upstream_context,
        target_privacy_level=target_privacy_level,
    )


def glyph_to_structured_json(
    glyph_packet: Any,
    upstream_context: str | ContextPacket | ContextPayload | Mapping[str, Any] | None = None,
    context: dict | None = None,
    *,
    target_privacy_level: Literal["external", "local"] = "external",
) -> dict[str, Any]:
    """
    Convert GlyphOS packet to structured routing/observability JSON.

    Args:
        glyph_packet:
            Object with action, destination, timeSlot/time_slot,
            psiCoherence/psi_coherence, instanceId/instance_id.
        upstream_context:
            Explicit harness-supplied context.
        context:
            Optional additional explicit context. Legacy argument retained.
        target_privacy_level:
            "external" redacts provenance/metadata values.
            "local" preserves provenance/metadata values.

    Returns:
        Structured dictionary for API calls / routing / observability.
        Does not include raw prompt text or raw context.
    """
    if target_privacy_level not in {"external", "local"}:
        raise ValueError("target_privacy_level must be 'external' or 'local'")

    explicit_context = _resolve_explicit_context(
        context=context,
        upstream_context=upstream_context,
    )
    ctx = _normalize_context(explicit_context)

    action, destination, time_slot, psi_coherence, instance_id = _packet_fields(glyph_packet)
    preferred_backend, preferred_backend_source = _preferred_backend_from_context(
        psi_coherence,
        ctx,
    )
    existing_stream, existing_format = _existing_packet_glyph_stream(glyph_packet)

    token_budget = _read_field(
        ctx["routing_hints"],
        "token_budget",
        "tokenBudget",
        default=None,
    )

    return {
        "intent": {
            "action": action,
            "target": destination,
            "time": time_slot,
            "time_description": _interpret_time(time_slot),
            "priority": "high" if psi_coherence >= 0.8 else "normal",
        },
        "context": {
            "coherence": psi_coherence,
            "instance_id": instance_id,
            "upstream_context_present": ctx["provided"],
            "upstream_raw_present": bool(ctx["raw_content"]),
            "upstream_encoded_present": bool(ctx["encoded_context"]),
            "upstream": _safe_metadata_for_transport(
                ctx,
                external=target_privacy_level == "external",
            ),
        },
        "transport": {
            "si_version": GLYPHOS_SI_VERSION,
            "transport": TRANSPORT_KIND,
            "raw_prompt_transported": False,
            "raw_context_transported": False,
            "packet_glyph_stream_present": bool(existing_stream),
            "packet_encoding_format": existing_format,
            "target_privacy_level": target_privacy_level,
        },
        "routing": {
            "suggested_provider": preferred_backend,
            "preferred_backend": preferred_backend,
            "preferred_backend_source": preferred_backend_source,
            "locality": ctx["locality"],
            "routing_hints": ctx["routing_hints"],
            "token_budget": token_budget,
            "complexity": ("high" if action in {"ANALYZE", "SYNTHESIZE", "PREDICT", "LEARN"} else "normal"),
        },
    }


__all__ = [
    "ContextPacket",
    "ContextPayload",
    "GlyphTransportError",
    "build_si_transport",
    "glyph_to_prompt",
    "glyph_to_structured_json",
    "build_prompt_from_packet",
]


if __name__ == "__main__":

    class MockPacket:
        action = "ANALYZE"
        destination = "AURORA"
        timeSlot = "T07"
        psiCoherence = 0.85
        instance_id = "abc123"

    packet = MockPacket()
    message = "Check Aurora route health without transporting raw text."

    print("=== GlyphOS SI Transport Demo ===")
    print(build_prompt_from_packet(packet, user_message=message))

    print("\n=== Structured JSON ===")
    print(json.dumps(glyph_to_structured_json(packet), indent=2, ensure_ascii=False))
