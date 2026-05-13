"""
GlyphOS SI Glyph Encoder
Author: Angelo Kapantais / Soul Hash Labs
Purpose:
    Reversible text/bytes -> glyph stream encoder.

Design:
    - UTF-8 byte-level encoding, so every Unicode string round-trips.
    - Uses glyph_map.yaml if present.
    - Falls back to a deterministic Private Use Area glyph map.
    - Safe for missing/incomplete glyph maps.
    - No hard dependency on PyYAML unless glyph_map.yaml is YAML.

Preferred glyph_map.yaml shape:

    version: "glyphos-byte-map-v1"
    encoding: "utf-8"

    glyphs:
      - code: "0x00"          # byte in hex form
        byte: 0               # byte as integer
        glyph: "\ue000"       # UTF-8 glyph/token, here U+E000
        name: "NULL_SEED"     # mnemonic / audit label

      - code: "0x01"
        byte: 1
        glyph: "\ue001"
        name: "START_OBSERVER"

Minimal legacy shapes also supported:

    byte_to_glyph:
      0: "\ue000"
      1: "\ue001"

    glyphs:
      0: "\ue000"
      1: "\ue001"

    glyphs:
      - "\ue000"
      - "\ue001"

Note:
    Symbols like "\ue000" are Unicode Private Use Area codepoints.
    They are valid UTF-8 glyphs, not display errors.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from .glyph_core import MAGIC, load_glyph_map

# ---------------------------------------------------------------------------
# Public encoding functions
# ---------------------------------------------------------------------------


def encode_bytes(
    data: bytes,
    *,
    glyph_map_path: str | Path | None = None,
    include_header: bool = True,
    delimiter: str = " ",
) -> str:
    glyph_map = load_glyph_map(glyph_map_path)
    body = delimiter.join(glyph_map.byte_to_glyph[b] for b in data)

    if include_header:
        return f"{MAGIC}\n{body}"

    return body


def encode_text(
    text: str,
    *,
    glyph_map_path: str | Path | None = None,
    include_header: bool = True,
    delimiter: str = " ",
) -> str:
    return encode_bytes(
        text.encode("utf-8"),
        glyph_map_path=glyph_map_path,
        include_header=include_header,
        delimiter=delimiter,
    )


def encode_base64_payload(
    text: str,
    *,
    glyph_map_path: str | Path | None = None,
    include_header: bool = True,
    delimiter: str = " ",
) -> str:
    """
    Optional wrapper for systems that want ASCII-safe payloads before glyphing.
    Decoder must call decode_base64_payload().
    """
    b64 = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
    return encode_text(
        b64,
        glyph_map_path=glyph_map_path,
        include_header=include_header,
        delimiter=delimiter,
    )


class GlyphEncoder:
    def __init__(self, glyph_map_path: str | Path | None = None, delimiter: str = " "):
        self.glyph_map_path = glyph_map_path
        self.delimiter = delimiter
        self.glyph_map = load_glyph_map(glyph_map_path)

    def encode_bytes(self, data: bytes, include_header: bool = True) -> str:
        body = self.delimiter.join(self.glyph_map.byte_to_glyph[b] for b in data)
        return f"{MAGIC}\n{body}" if include_header else body

    def encode_text(self, text: str, include_header: bool = True) -> str:
        return self.encode_bytes(text.encode("utf-8"), include_header=include_header)

    def encode_tokens(self, data: bytes) -> list[str]:
        return [self.glyph_map.byte_to_glyph[b] for b in data]


# Compatibility aliases for older GlyphOS code.
encode = encode_text
encode_string = encode_text
encode_utf8 = encode_text


def _main() -> int:
    parser = argparse.ArgumentParser(description="Encode text/file into GlyphOS glyph stream.")
    parser.add_argument("input", help="Text input, or file path when --file is set.")
    parser.add_argument("-m", "--map", dest="glyph_map_path", default=None)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--file", action="store_true", help="Treat input as a file path.")
    parser.add_argument("--no-header", action="store_true")
    args = parser.parse_args()

    if args.file:
        raw = Path(args.input).read_bytes()
        encoded = encode_bytes(
            raw,
            glyph_map_path=args.glyph_map_path,
            include_header=not args.no_header,
        )
    else:
        encoded = encode_text(
            args.input,
            glyph_map_path=args.glyph_map_path,
            include_header=not args.no_header,
        )

    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded)

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
