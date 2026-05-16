"""
glyphos_ai/glyph/glyph_core.py

Shared constants, data classes, and helpers for the GlyphOS byte-level
codec.  Extracted from encoder.py so decoder.py does NOT need to import
encoder.py — breaking the decoder -> encoder dependency.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAGIC = "\u27f6GLYPHOS-BYTE-V1\u27f7"
DEFAULT_MAP_NAME = "glyph_map.yaml"


class GlyphEncodingError(ValueError):
    """Raised when glyph encoding or map loading fails."""


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


@dataclass(frozen=True)
class SemanticGlyphMap:
    """Bucket-aware semantic glyph mapping parsed from glyph_map.yaml.

    Four buckets (2-bit prefix × 64 entries):
      00xxxxxx → actions        (0x00–0x3F)
      01xxxxxx → destinations   (0x40–0x7F)
      10xxxxxx → time/quantity  (0x80–0xBF)
      11xxxxxx → sacred mods    (0xC0–0xFF)
    """

    actions: dict[str, tuple[int, str]]  # name → (byte_code, glyph)
    destinations: dict[str, tuple[int, str]]  # name → (byte_code, glyph)
    time_quantity: dict[str, tuple[int, str]]  # name → (byte_code, glyph)
    sacred_mods: dict[str, tuple[int, str]]  # name → (byte_code, glyph)
    glyph_to_semantic: dict[str, tuple[str, str]]  # glyph → (bucket, name)

    def encode_field(self, bucket: str, name: str) -> tuple[int, str] | None:
        bucket_map = {
            "actions": self.actions,
            "destinations": self.destinations,
            "time_quantity": self.time_quantity,
            "sacred_mods": self.sacred_mods,
        }.get(bucket)
        if bucket_map is None:
            return None
        return bucket_map.get(str(name).strip().lower())

    def decode_glyph(self, glyph: str) -> tuple[str, str] | None:
        return self.glyph_to_semantic.get(glyph)


def _load_semantic_map(data: Any) -> SemanticGlyphMap:
    """Parse glyph_map.yaml structure into SemanticGlyphMap."""
    if not isinstance(data, Mapping):
        raise GlyphEncodingError("glyph_map.yaml must be a mapping")

    actions: dict[str, tuple[int, str]] = {}
    destinations: dict[str, tuple[int, str]] = {}
    time_quantity: dict[str, tuple[int, str]] = {}
    sacred_mods: dict[str, tuple[int, str]] = {}

    bucket_names = {
        "actions": actions,
        "destinations": destinations,
        "time_quantity": time_quantity,
        "sacred_mods": sacred_mods,
    }

    for section_key, target_dict in bucket_names.items():
        entries = data.get(section_key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            code = entry.get("code")
            glyph = entry.get("glyph")
            name = entry.get("name")
            if code is not None and glyph and name:
                byte_code = _coerce_byte_key(code)
                if byte_code is not None:
                    target_dict[str(name).strip().lower()] = (byte_code, str(glyph))

    glyph_to_semantic: dict[str, tuple[str, str]] = {}
    for bucket_name, bucket_dict in [
        ("actions", actions),
        ("destinations", destinations),
        ("time_quantity", time_quantity),
        ("sacred_mods", sacred_mods),
    ]:
        for name, (_code, glyph) in bucket_dict.items():
            glyph_to_semantic[glyph] = (bucket_name, name)

    return SemanticGlyphMap(
        actions=actions,
        destinations=destinations,
        time_quantity=time_quantity,
        sacred_mods=sacred_mods,
        glyph_to_semantic=glyph_to_semantic,
    )


_semantic_map_cache: dict[str, SemanticGlyphMap] = {}


def load_semantic_glyph_map(path: str | Path | None = None) -> SemanticGlyphMap:
    """Load semantic glyph map from glyph_map.yaml (cached)."""
    if path is None:
        path = Path(__file__).with_name(DEFAULT_MAP_NAME)
    else:
        path = Path(path)

    cache_key = str(path.resolve())
    if cache_key in _semantic_map_cache:
        return _semantic_map_cache[cache_key]

    if not path.exists():
        raise GlyphEncodingError(f"semantic glyph map not found: {path}")

    data = _load_structured_file(path)
    semantic_map = _load_semantic_map(data)
    _semantic_map_cache[cache_key] = semantic_map
    return semantic_map


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
