"""
GlyphOS Semantic Decoder
========================

Author: Angelo Kapantais / Soul Hash Labs

Purpose:
    Decode GlyphOS semantic glyph strings back into Intent / packet semantics.

Design:
    - Glyph string -> decoder.decode_text() -> GIS1 semantic wire -> SemanticIntentPayload.
    - Reversible pair for semantic_encoder.py.
    - Supports compact field aliases.
    - Can return project Intent when available.
    - No retrieval, network I/O, hidden context loading, or filesystem mutation.

Semantic wire format:
    GIS1|a=<ACTION>|d=<DESTINATION>|t=<TIME_SLOT>|p=<PSI>|i=<INSTANCE_ID>
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

try:
    from ..glyph.decoder import decode_text
except Exception as exc:  # pragma: no cover - fail closed if package import is broken
    decode_text = None  # type: ignore[assignment]
    _DECODER_IMPORT_ERROR = exc
else:
    _DECODER_IMPORT_ERROR = None


try:
    from ..glyph.types import Intent as ProjectIntent
except Exception:  # pragma: no cover - project type may not exist in some test harnesses
    ProjectIntent = None  # type: ignore[assignment]


SEMANTIC_INTENT_VERSION = "GIS1"
DEFAULT_TIME_SLOT = "T00"
DEFAULT_PSI_COHERENCE = 0.5
DEFAULT_GLYPH_DELIMITER = " "


class SemanticDecodingError(RuntimeError):
    """Raised when semantic glyph stream cannot be decoded safely."""


@dataclass(frozen=True)
class SemanticIntentPayload:
    action: str
    destination: str
    time_slot: str = DEFAULT_TIME_SLOT
    psi_coherence: float = DEFAULT_PSI_COHERENCE
    instance_id: str = ""

    def to_wire(self) -> str:
        psi_text = f"{self.psi_coherence:.6f}".rstrip("0").rstrip(".")
        if not psi_text:
            psi_text = "0"
        return "|".join(
            [
                SEMANTIC_INTENT_VERSION,
                f"a={_escape_field(self.action)}",
                f"d={_escape_field(self.destination)}",
                f"t={_escape_field(self.time_slot)}",
                f"p={_escape_field(psi_text)}",
                f"i={_escape_field(self.instance_id)}",
            ]
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.to_wire().encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "destination": self.destination,
            "time_slot": self.time_slot,
            "psi_coherence": self.psi_coherence,
            "instance_id": self.instance_id,
        }


def _escape_field(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\p").replace("=", "\\e").replace("\n", "\\n").replace("\r", "\\r")


def _unescape_field(value: str) -> str:
    output: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\":
            output.append(ch)
            i += 1
            continue

        if i + 1 >= len(value):
            output.append("\\")
            i += 1
            continue

        nxt = value[i + 1]
        if nxt == "p":
            output.append("|")
        elif nxt == "e":
            output.append("=")
        elif nxt == "n":
            output.append("\n")
        elif nxt == "r":
            output.append("\r")
        elif nxt == "\\":
            output.append("\\")
        else:
            output.append("\\")
            output.append(nxt)
        i += 2

    return "".join(output)


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


def decode_glyphs_to_semantic_wire(
    glyph_string: str,
    *,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> str:
    if decode_text is None:
        raise SemanticDecodingError(
            "GlyphOS decoder is unavailable; cannot decode semantic glyph stream. "
            f"Import error: {_DECODER_IMPORT_ERROR!r}"
        )

    try:
        return str(decode_text(glyph_string, delimiter=delimiter, strict=True))
    except TypeError:
        try:
            return str(decode_text(glyph_string, delimiter=delimiter))
        except TypeError:
            return str(decode_text(glyph_string))
    except Exception as exc:
        raise SemanticDecodingError(f"GlyphOS semantic decode failed: {exc}") from exc


def parse_semantic_wire(wire: str) -> SemanticIntentPayload:
    if not isinstance(wire, str) or not wire:
        raise SemanticDecodingError("semantic wire must be a non-empty string")

    parts = wire.split("|")
    version = parts[0].strip() if parts else ""

    if version != SEMANTIC_INTENT_VERSION:
        raise SemanticDecodingError(
            f"unsupported semantic intent version: {version!r}; expected {SEMANTIC_INTENT_VERSION!r}"
        )

    fields: dict[str, str] = {}
    for part in parts[1:]:
        if not part:
            continue
        if "=" not in part:
            raise SemanticDecodingError(f"malformed semantic field: {part!r}")
        key, value = part.split("=", 1)
        key = key.strip()
        if not key:
            raise SemanticDecodingError(f"empty semantic field key in {part!r}")
        fields[key] = _unescape_field(value)

    return SemanticIntentPayload(
        action=_normalize_action(fields.get("a")),
        destination=_normalize_destination(fields.get("d")),
        time_slot=_normalize_time_slot(fields.get("t")),
        psi_coherence=_normalize_psi(fields.get("p")),
        instance_id=str(fields.get("i") or "").strip(),
    )


def decode_intent_from_glyphs(
    glyph_string: str,
    *,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> SemanticIntentPayload:
    wire = decode_glyphs_to_semantic_wire(glyph_string, delimiter=delimiter)
    return parse_semantic_wire(wire)


def decode_intent_dict_from_glyphs(
    glyph_string: str,
    *,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> dict[str, Any]:
    return decode_intent_from_glyphs(glyph_string, delimiter=delimiter).as_dict()


def decode_project_intent_from_glyphs(
    glyph_string: str,
    *,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> tuple[str, Any, float]:
    payload = decode_intent_from_glyphs(glyph_string, delimiter=delimiter)

    if ProjectIntent is None:
        raise SemanticDecodingError("project Intent type is unavailable")

    try:
        intent = ProjectIntent(
            action=payload.action,
            destination=payload.destination,
            time_slot=payload.time_slot,
        )
    except TypeError:
        try:
            intent = ProjectIntent(
                action=payload.action,
                destination=payload.destination,
                time_slot=int(str(payload.time_slot).replace("T", "") or 0),
            )
        except Exception as exc:
            raise SemanticDecodingError(f"cannot construct project Intent: {exc}") from exc
    except Exception as exc:
        raise SemanticDecodingError(f"cannot construct project Intent: {exc}") from exc

    return payload.instance_id, intent, payload.psi_coherence


def semantic_decoding_manifest(
    glyph_string: str,
    *,
    delimiter: str = DEFAULT_GLYPH_DELIMITER,
) -> dict[str, Any]:
    wire = decode_glyphs_to_semantic_wire(glyph_string, delimiter=delimiter)
    payload = parse_semantic_wire(wire)

    return {
        "semantic_version": SEMANTIC_INTENT_VERSION,
        "wire_sha256": hashlib.sha256(wire.encode("utf-8")).hexdigest(),
        "glyph_sha256": hashlib.sha256(glyph_string.encode("utf-8")).hexdigest(),
        "wire_chars": len(wire),
        "glyph_chars": len(glyph_string),
        "wire_utf8_bytes": len(wire.encode("utf-8")),
        "glyph_utf8_bytes": len(glyph_string.encode("utf-8")),
        "fields": payload.as_dict(),
    }


__all__ = [
    "SEMANTIC_INTENT_VERSION",
    "DEFAULT_GLYPH_DELIMITER",
    "SemanticDecodingError",
    "SemanticIntentPayload",
    "decode_glyphs_to_semantic_wire",
    "parse_semantic_wire",
    "decode_intent_from_glyphs",
    "decode_intent_dict_from_glyphs",
    "decode_project_intent_from_glyphs",
    "semantic_decoding_manifest",
]
