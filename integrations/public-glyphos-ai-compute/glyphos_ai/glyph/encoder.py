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
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAGIC = "\u27f6GLYPHOS-BYTE-V1\u27f7"
DEFAULT_MAP_NAME = "glyph_map.yaml"


class GlyphEncodingError(ValueError):
    """Raised when glyph encoding fails."""


@dataclass(frozen=True)
class GlyphMap:
    byte_to_glyph: dict[int, str]
    glyph_to_byte: dict[str, int]

    def validate(self) -> None:
        missing = [i for i in range(256) if i not in self.byte_to_glyph]
        if missing:
            raise GlyphEncodingError(f"glyph map missing byte entries: {missing[:10]}")

        duplicate_reverse = len(self.glyph_to_byte) != len(set(self.byte_to_glyph.values()))
        if duplicate_reverse:
            raise GlyphEncodingError("glyph map contains duplicate glyph values")


def _builtin_private_use_map() -> GlyphMap:
    """
    Deterministic fallback map:
    byte 0 -> U+E000, byte 255 -> U+E0FF.
    """
    byte_to_glyph = {i: chr(0xE000 + i) for i in range(256)}
    glyph_to_byte = {glyph: byte for byte, glyph in byte_to_glyph.items()}
    return GlyphMap(byte_to_glyph=byte_to_glyph, glyph_to_byte=glyph_to_byte)


def _coerce_byte_key(key: Any) -> int | None:
    if isinstance(key, int):
        return key if 0 <= key <= 255 else None

    if isinstance(key, str):
        s = key.strip().lower()
        try:
            if s.startswith("0x"):
                value = int(s, 16)
            else:
                value = int(s, 10)
            return value if 0 <= value <= 255 else None
        except ValueError:
            return None

    return None


def _load_structured_file(path: Path) -> Any:
    suffix = path.suffix.lower()

    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise GlyphEncodingError(
            f"{path} appears to be YAML but PyYAML is not installed. Install with: pip install pyyaml"
        ) from exc

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _extract_glyphs_from_mapping(data: Any) -> dict[int, str]:
    """
    Accepts preferred and legacy map formats and returns partial {byte: glyph}.

    Preferred:

    glyphs:
      - code: "0x00"
        byte: 0
        glyph: "\ue000"
        name: "NULL_SEED"

    Legacy:

    byte_to_glyph:
      0: "\ue000"

    glyphs:
      0: "\ue000"

    glyphs:
      - "\ue000"
      - "\ue001"
    """
    if not data:
        return {}

    if isinstance(data, list):
        out: dict[int, str] = {}
        for i, item in enumerate(data[:256]):
            if isinstance(item, Mapping):
                raw_byte = item.get("byte", item.get("code", i))
                byte = _coerce_byte_key(raw_byte)
                glyph = item.get("glyph") or item.get("symbol") or item.get("token")
                if byte is not None and glyph:
                    out[byte] = str(glyph)
            elif str(item):
                out[i] = str(item)
        return out

    if not isinstance(data, Mapping):
        return {}

    candidate = (
        data.get("byte_to_glyph")
        or data.get("byte_map")
        or data.get("glyphs")
        or data.get("map")
        or data.get("alphabet")
    )

    if isinstance(candidate, list):
        out: dict[int, str] = {}
        for i, item in enumerate(candidate[:256]):
            if isinstance(item, Mapping):
                raw_byte = item.get("byte", item.get("code", i))
                byte = _coerce_byte_key(raw_byte)
                glyph = item.get("glyph") or item.get("symbol") or item.get("token")
                if byte is not None and glyph:
                    out[byte] = str(glyph)
            elif str(item):
                out[i] = str(item)
        return out

    if isinstance(candidate, Mapping):
        out: dict[int, str] = {}
        for raw_key, raw_glyph in candidate.items():
            byte = _coerce_byte_key(raw_key)
            if byte is None:
                continue

            if isinstance(raw_glyph, Mapping):
                glyph = (
                    raw_glyph.get("glyph")
                    or raw_glyph.get("symbol")
                    or raw_glyph.get("token")
                    or raw_glyph.get("value")
                )
            else:
                glyph = raw_glyph

            if glyph is not None and str(glyph):
                out[byte] = str(glyph)

        return out

    return {}


def load_glyph_map(path: str | Path | None = None) -> GlyphMap:
    """
    Load a glyph map from path, or glyph_map.yaml beside this file.
    Falls back to built-in private-use map if no file exists.
    """
    fallback = _builtin_private_use_map()

    if path is None:
        path = Path(__file__).with_name(DEFAULT_MAP_NAME)
    else:
        path = Path(path)

    if not path.exists():
        return fallback

    data = _load_structured_file(path)
    partial = _extract_glyphs_from_mapping(data)

    byte_to_glyph = dict(fallback.byte_to_glyph)
    byte_to_glyph.update(partial)

    glyph_to_byte = {glyph: byte for byte, glyph in byte_to_glyph.items()}
    glyph_map = GlyphMap(byte_to_glyph=byte_to_glyph, glyph_to_byte=glyph_to_byte)
    glyph_map.validate()
    return glyph_map


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
