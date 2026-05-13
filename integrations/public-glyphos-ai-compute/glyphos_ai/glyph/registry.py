"""
glyphos_ai/glyph/registry.py
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

BUCKET_NAMES: tuple[str, ...] = (
    "actions",
    "destinations",
    "time_quantity",
    "sacred_mods",
)

BUCKET_BASES: dict[str, int] = {
    "actions": 0x00,
    "destinations": 0x40,
    "time_quantity": 0x80,
    "sacred_mods": 0xC0,
}

EXPECTED_CODES: set[int] = set(range(0x00, 0x100))


class GlyphRegistryError(ValueError):
    """Raised when glyph_map.yaml is malformed or incomplete."""


@dataclass(frozen=True, slots=True)
class GlyphEntry:
    bucket: str
    code: int
    glyph: str
    name: str
    index: int

    @property
    def code_hex(self) -> str:
        return f"0x{self.code:02X}"

    @property
    def bucket_bits(self) -> str:
        return f"{self.code >> 6:02b}"

    @property
    def index_bits(self) -> str:
        return f"{self.code & 0x3F:06b}"

    @property
    def binary(self) -> str:
        return f"{self.code:08b}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "code": self.code,
            "code_hex": self.code_hex,
            "binary": self.binary,
            "bucket_bits": self.bucket_bits,
            "index_bits": self.index_bits,
            "glyph": self.glyph,
            "name": self.name,
            "index": self.index,
        }


def _coerce_code(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise GlyphRegistryError(f"Invalid code value: {value!r}")


def _coerce_nonempty_str(field_name: str, value: Any) -> str:
    if value is None:
        raise GlyphRegistryError(f"Missing required field: {field_name}")
    text = str(value)
    if not text.strip():
        raise GlyphRegistryError(f"Field {field_name!r} must not be empty")
    return text


class GlyphRegistry:
    """
    Immutable validated registry loaded from glyph_map.yaml.

    Guarantees:
    - exactly 256 unique codes (0x00..0xFF)
    - exactly 64 entries per bucket
    - unique glyph tokens
    - unique mnemonic names
    """

    def __init__(self, entries: Iterable[GlyphEntry]) -> None:
        entry_list = list(entries)

        if len(entry_list) != 256:
            raise GlyphRegistryError(f"Registry must contain 256 entries; got {len(entry_list)}")

        self._entries = tuple(sorted(entry_list, key=lambda e: e.code))
        self._by_code = {entry.code: entry for entry in self._entries}
        self._by_glyph = {entry.glyph: entry for entry in self._entries}
        self._by_name = {entry.name.lower(): entry for entry in self._entries}

        if len(self._by_code) != 256:
            raise GlyphRegistryError("Duplicate glyph codes detected")
        if len(self._by_glyph) != 256:
            raise GlyphRegistryError("Duplicate glyph tokens detected")
        if len(self._by_name) != 256:
            raise GlyphRegistryError("Duplicate mnemonic names detected")

        codes = set(self._by_code.keys())
        if codes != EXPECTED_CODES:
            missing = sorted(EXPECTED_CODES - codes)
            extra = sorted(codes - EXPECTED_CODES)
            raise GlyphRegistryError(f"Registry code coverage invalid; missing={missing}, extra={extra}")

        for bucket in BUCKET_NAMES:
            bucket_entries = [e for e in self._entries if e.bucket == bucket]
            if len(bucket_entries) != 64:
                raise GlyphRegistryError(f"Bucket {bucket!r} must contain 64 entries; got {len(bucket_entries)}")
            base = BUCKET_BASES[bucket]
            expected_bucket_codes = set(range(base, base + 64))
            actual_bucket_codes = {e.code for e in bucket_entries}
            if actual_bucket_codes != expected_bucket_codes:
                raise GlyphRegistryError(f"Bucket {bucket!r} codes invalid; expected 0x{base:02X}-0x{base + 63:02X}")

        self._glyphs_by_length_desc = tuple(sorted(self._by_glyph.keys(), key=len, reverse=True))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GlyphRegistry:
        entries: list[GlyphEntry] = []

        for bucket in BUCKET_NAMES:
            raw_bucket = data.get(bucket)
            if not isinstance(raw_bucket, list):
                raise GlyphRegistryError(f"Bucket {bucket!r} missing or not a list in glyph map")

            for raw in raw_bucket:
                if not isinstance(raw, Mapping):
                    raise GlyphRegistryError(f"Entries in bucket {bucket!r} must be mappings")

                code = _coerce_code(raw.get("code"))
                glyph = _coerce_nonempty_str("glyph", raw.get("glyph"))
                name = _coerce_nonempty_str("name", raw.get("name")).strip()

                expected_base = BUCKET_BASES[bucket]
                if not (expected_base <= code < expected_base + 64):
                    raise GlyphRegistryError(f"Entry {name!r} in bucket {bucket!r} has out-of-range code {code:#04x}")

                index = code - expected_base

                entries.append(
                    GlyphEntry(
                        bucket=bucket,
                        code=code,
                        glyph=glyph,
                        name=name,
                        index=index,
                    )
                )

        return cls(entries)

    @classmethod
    def from_yaml_text(cls, text: str) -> GlyphRegistry:
        data = yaml.safe_load(text)
        if not isinstance(data, Mapping):
            raise GlyphRegistryError("glyph_map.yaml must decode to a mapping")
        return cls.from_mapping(data)

    @classmethod
    def from_file(cls, path: str | Path) -> GlyphRegistry:
        file_path = Path(path)
        return cls.from_yaml_text(file_path.read_text(encoding="utf-8"))

    @classmethod
    def from_package_resource(
        cls,
        package: str = "glyphos_ai.glyph",
        resource: str = "glyph_map.yaml",
    ) -> GlyphRegistry:
        resource_path = files(package).joinpath(resource)
        with resource_path.open("r", encoding="utf-8") as handle:
            return cls.from_yaml_text(handle.read())

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    @property
    def entries(self) -> tuple[GlyphEntry, ...]:
        return self._entries

    @property
    def glyphs_by_length_desc(self) -> tuple[str, ...]:
        return self._glyphs_by_length_desc

    def get_by_code(self, code: int) -> GlyphEntry:
        try:
            return self._by_code[int(code)]
        except KeyError as exc:
            raise GlyphRegistryError(f"Unknown glyph code: {code:#04x}") from exc

    def get_by_glyph(self, glyph: str) -> GlyphEntry:
        try:
            return self._by_glyph[glyph]
        except KeyError as exc:
            raise GlyphRegistryError(f"Unknown glyph token: {glyph!r}") from exc

    def get_by_name(self, name: str) -> GlyphEntry:
        key = str(name).strip().lower()
        try:
            return self._by_name[key]
        except KeyError as exc:
            raise GlyphRegistryError(f"Unknown glyph mnemonic: {name!r}") from exc

    def has_glyph(self, glyph: str) -> bool:
        return glyph in self._by_glyph

    def has_code(self, code: int) -> bool:
        return int(code) in self._by_code

    def has_name(self, name: str) -> bool:
        return str(name).strip().lower() in self._by_name

    def match_glyph_at(self, text: str, offset: int) -> tuple[GlyphEntry, int] | None:
        """
        Longest-match glyph token lookup at a given offset.
        Supports multicodepoint glyph tokens.
        """
        for glyph in self._glyphs_by_length_desc:
            if text.startswith(glyph, offset):
                entry = self._by_glyph[glyph]
                return entry, offset + len(glyph)
        return None

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKET_NAMES}
        for entry in self._entries:
            out[entry.bucket].append(
                {
                    "code": entry.code_hex,
                    "glyph": entry.glyph,
                    "name": entry.name,
                }
            )
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "entry_count": len(self._entries),
            "bucket_counts": {bucket: len([e for e in self._entries if e.bucket == bucket]) for bucket in BUCKET_NAMES},
            "codes_min": min(self._by_code),
            "codes_max": max(self._by_code),
        }


@lru_cache(maxsize=8)
def load_registry(
    package: str = "glyphos_ai.glyph",
    resource: str = "glyph_map.yaml",
) -> GlyphRegistry:
    return GlyphRegistry.from_package_resource(package=package, resource=resource)
