"""
GlyphOS SI Glyph Decoder

Pairs with:
    glyphos_ai/glyph/encoder.py
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

try:
    from .encoder import MAGIC, GlyphMap, load_glyph_map
except ImportError:
    from encoder import MAGIC, GlyphMap, load_glyph_map  # type: ignore


class GlyphDecodingError(ValueError):
    """Raised when glyph decoding fails."""


def _strip_header(payload: str) -> str:
    if not isinstance(payload, str):
        raise GlyphDecodingError(f"payload must be a string, got {type(payload).__name__}")
    payload = payload.strip()
    if payload.startswith(MAGIC):
        return payload[len(MAGIC) :].strip()
    return payload


def _tokens_from_payload(payload: str, delimiter: str | None = " ") -> list[str]:
    payload = _strip_header(payload)

    if not payload:
        return []

    if delimiter is None:
        return list(payload)

    return [token for token in payload.split(delimiter) if token]


def decode_to_bytes(
    payload: str,
    *,
    glyph_map_path: str | Path | None = None,
    delimiter: str | None = " ",
    strict: bool = True,
) -> bytes:
    glyph_map = load_glyph_map(glyph_map_path)
    tokens = _tokens_from_payload(payload, delimiter=delimiter)

    decoded = bytearray()

    for index, token in enumerate(tokens):
        if token not in glyph_map.glyph_to_byte:
            if strict:
                raise GlyphDecodingError(f"unknown glyph token at position {index}: {token!r}")
            continue

        decoded.append(glyph_map.glyph_to_byte[token])

    return bytes(decoded)


def decode_text(
    payload: str,
    *,
    glyph_map_path: str | Path | None = None,
    delimiter: str | None = " ",
    strict: bool = True,
    errors: str = "strict",
) -> str:
    raw = decode_to_bytes(
        payload,
        glyph_map_path=glyph_map_path,
        delimiter=delimiter,
        strict=strict,
    )
    return raw.decode("utf-8", errors=errors)


def decode_base64_payload(
    payload: str,
    *,
    glyph_map_path: str | Path | None = None,
    delimiter: str | None = " ",
    strict: bool = True,
) -> str:
    b64_text = decode_text(
        payload,
        glyph_map_path=glyph_map_path,
        delimiter=delimiter,
        strict=strict,
    )
    return base64.urlsafe_b64decode(b64_text.encode("ascii")).decode("utf-8")


class GlyphDecoder:
    def __init__(self, glyph_map_path: str | Path | None = None, delimiter: str | None = " "):
        self.glyph_map_path = glyph_map_path
        self.delimiter = delimiter
        self.glyph_map: GlyphMap = load_glyph_map(glyph_map_path)

    def decode_to_bytes(self, payload: str, strict: bool = True) -> bytes:
        tokens = _tokens_from_payload(payload, delimiter=self.delimiter)
        decoded = bytearray()

        for index, token in enumerate(tokens):
            if token not in self.glyph_map.glyph_to_byte:
                if strict:
                    raise GlyphDecodingError(f"unknown glyph token at position {index}: {token!r}")
                continue
            decoded.append(self.glyph_map.glyph_to_byte[token])

        return bytes(decoded)

    def decode_text(self, payload: str, strict: bool = True, errors: str = "strict") -> str:
        return self.decode_to_bytes(payload, strict=strict).decode("utf-8", errors=errors)

    def decode_tokens(self, tokens: list[str], strict: bool = True) -> bytes:
        decoded = bytearray()

        for index, token in enumerate(tokens):
            if token not in self.glyph_map.glyph_to_byte:
                if strict:
                    raise GlyphDecodingError(f"unknown glyph token at position {index}: {token!r}")
                continue
            decoded.append(self.glyph_map.glyph_to_byte[token])

        return bytes(decoded)


decode = decode_text
decode_string = decode_text
decode_utf8 = decode_text


def _main() -> int:
    parser = argparse.ArgumentParser(description="Decode GlyphOS glyph stream into text/file.")
    parser.add_argument("input", help="Glyph payload, or file path when --file is set.")
    parser.add_argument("-m", "--map", dest="glyph_map_path", default=None)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--file", action="store_true", help="Treat input as a file path.")
    parser.add_argument("--bytes", action="store_true", help="Write decoded bytes instead of UTF-8 text.")
    parser.add_argument("--non-strict", action="store_true", help="Skip unknown glyphs.")
    args = parser.parse_args()

    payload = Path(args.input).read_text(encoding="utf-8") if args.file else args.input

    if args.bytes:
        decoded_bytes = decode_to_bytes(
            payload,
            glyph_map_path=args.glyph_map_path,
            strict=not args.non_strict,
        )
        if args.output:
            Path(args.output).write_bytes(decoded_bytes)
        else:
            print(decoded_bytes)
    else:
        decoded_text = decode_text(
            payload,
            glyph_map_path=args.glyph_map_path,
            strict=not args.non_strict,
        )
        if args.output:
            Path(args.output).write_text(decoded_text, encoding="utf-8")
        else:
            print(decoded_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
