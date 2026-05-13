"""
glyphos_ai/glyph/codec.py
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .registry import GlyphEntry, GlyphRegistry, GlyphRegistryError, load_registry


class GlyphCodecError(ValueError):
    """Raised when glyph streams or byte payloads cannot be encoded / decoded."""


@dataclass(frozen=True, slots=True)
class ParsedToken:
    kind: Literal["glyph", "literal"]
    value: str
    entry: GlyphEntry | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "glyph" and self.entry is not None:
            return {
                "kind": "glyph",
                "value": self.value,
                "bucket": self.entry.bucket,
                "code": self.entry.code,
                "code_hex": self.entry.code_hex,
                "name": self.entry.name,
                "index": self.entry.index,
            }
        return {
            "kind": "literal",
            "value": self.value,
        }


def _ensure_registry(registry: GlyphRegistry | None) -> GlyphRegistry:
    return registry if registry is not None else load_registry()


def tokenize_glyph_stream(
    stream: str,
    registry: GlyphRegistry | None = None,
    *,
    preserve_unknown_literals: bool = False,
) -> list[ParsedToken]:
    """
    Tokenize a glyph stream using longest-match glyph lookup.

    Rules:
    - whitespace is ignored
    - known glyphs become kind='glyph'
    - unknown fragments raise unless preserve_unknown_literals=True
    """
    reg = _ensure_registry(registry)
    text = str(stream)

    tokens: list[ParsedToken] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch.isspace():
            i += 1
            continue

        match = reg.match_glyph_at(text, i)
        if match is not None:
            entry, next_i = match
            tokens.append(ParsedToken(kind="glyph", value=entry.glyph, entry=entry))
            i = next_i
            continue

        if not preserve_unknown_literals:
            snippet = text[i : min(i + 16, n)]
            raise GlyphCodecError(f"Unrecognized glyph token starting at offset {i}: {snippet!r}")

        start = i
        while i < n:
            if text[i].isspace():
                break
            if reg.match_glyph_at(text, i) is not None:
                break
            i += 1

        literal = text[start:i]
        if literal:
            tokens.append(ParsedToken(kind="literal", value=literal))
        else:
            i += 1

    return tokens


def encode_glyphs_to_bytes(
    glyphs: Sequence[str],
    registry: GlyphRegistry | None = None,
) -> bytes:
    reg = _ensure_registry(registry)
    try:
        return bytes(reg.get_by_glyph(g).code for g in glyphs)
    except GlyphRegistryError as exc:
        raise GlyphCodecError(str(exc)) from exc


def encode_names_to_bytes(
    names: Sequence[str],
    registry: GlyphRegistry | None = None,
) -> bytes:
    reg = _ensure_registry(registry)
    try:
        return bytes(reg.get_by_name(name).code for name in names)
    except GlyphRegistryError as exc:
        raise GlyphCodecError(str(exc)) from exc


def encode_entries_to_bytes(entries: Sequence[GlyphEntry]) -> bytes:
    return bytes(entry.code for entry in entries)


def glyph_stream_to_bytes(
    stream: str,
    registry: GlyphRegistry | None = None,
) -> bytes:
    tokens = tokenize_glyph_stream(
        stream,
        registry=registry,
        preserve_unknown_literals=False,
    )
    glyph_entries = [token.entry for token in tokens if token.entry is not None]
    return encode_entries_to_bytes(glyph_entries)


def decode_bytes_to_entries(
    payload: bytes | bytearray | memoryview,
    registry: GlyphRegistry | None = None,
) -> list[GlyphEntry]:
    reg = _ensure_registry(registry)
    return [reg.get_by_code(int(code)) for code in bytes(payload)]


def decode_bytes_to_glyphs(
    payload: bytes | bytearray | memoryview,
    registry: GlyphRegistry | None = None,
) -> list[str]:
    return [entry.glyph for entry in decode_bytes_to_entries(payload, registry=registry)]


def decode_bytes_to_names(
    payload: bytes | bytearray | memoryview,
    registry: GlyphRegistry | None = None,
) -> list[str]:
    return [entry.name for entry in decode_bytes_to_entries(payload, registry=registry)]


def bytes_to_glyph_stream(
    payload: bytes | bytearray | memoryview,
    registry: GlyphRegistry | None = None,
    *,
    separator: str = " ",
) -> str:
    return separator.join(decode_bytes_to_glyphs(payload, registry=registry))


def normalize_glyph_stream(
    stream: str,
    registry: GlyphRegistry | None = None,
    *,
    preserve_unknown_literals: bool = False,
    separator: str = " ",
) -> str:
    tokens = tokenize_glyph_stream(
        stream,
        registry=registry,
        preserve_unknown_literals=preserve_unknown_literals,
    )
    values = [token.value for token in tokens]
    return separator.join(values)


def glyph_stream_to_json(
    stream: str,
    registry: GlyphRegistry | None = None,
    *,
    preserve_unknown_literals: bool = False,
) -> dict[str, Any]:
    reg = _ensure_registry(registry)
    tokens = tokenize_glyph_stream(
        stream,
        registry=reg,
        preserve_unknown_literals=preserve_unknown_literals,
    )

    glyph_entries = [token.entry for token in tokens if token.entry is not None]
    byte_values = [entry.code for entry in glyph_entries]
    encodable = len(glyph_entries) == len(tokens)

    payload: dict[str, Any] = {
        "raw": stream,
        "normalized": " ".join(token.value for token in tokens),
        "encodable": encodable,
        "token_count": len(tokens),
        "glyph_count": len(glyph_entries),
        "tokens": [token.to_dict() for token in tokens],
        "mnemonic": " ".join(entry.name for entry in glyph_entries),
        "glyph_byte_values": byte_values,
        "glyph_hex": bytes(byte_values).hex(),
        "glyph_binary": [f"{value:08b}" for value in byte_values],
    }

    if encodable:
        payload["byte_values"] = byte_values
        payload["hex"] = bytes(byte_values).hex()

    return payload


def bytes_to_json(
    payload: bytes | bytearray | memoryview,
    registry: GlyphRegistry | None = None,
) -> dict[str, Any]:
    entries = decode_bytes_to_entries(payload, registry=registry)
    byte_values = [entry.code for entry in entries]
    return {
        "raw_bytes": list(byte_values),
        "hex": bytes(byte_values).hex(),
        "normalized": " ".join(entry.glyph for entry in entries),
        "mnemonic": " ".join(entry.name for entry in entries),
        "token_count": len(entries),
        "tokens": [entry.to_dict() for entry in entries],
    }


def dump_json(data: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False)
