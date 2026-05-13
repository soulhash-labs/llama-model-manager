"""
Context Encoding (Ψ Compression)
=================================
Extracts glyph encoding logic from the gateway into the glyphos_ai package.
The router inspects ContextPayload to decide whether to apply encoding.
"""

from __future__ import annotations

import json
from typing import Any

from glyphos_ai.glyph.types import ContextPayload

# ---------------------------------------------------------------------------
# Key-alias tables (moved from gateway)
# ---------------------------------------------------------------------------

GLYPH_KEY_ALIASES = {
    "path": "p",
    "file": "f",
    "title": "t",
    "uri": "u",
    "content": "c",
    "text": "x",
    "snippet": "s",
    "summary": "m",
    "score": "r",
    "line": "l",
    "lines": "ls",
    "language": "g",
}


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _alias_context_keys(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            alias = GLYPH_KEY_ALIASES.get(str(key), str(key))
            if alias in result:
                raise ValueError(f"glyph key collision: '{key}' -> '{alias}' overwrites existing key")
            result[alias] = _alias_context_keys(item)
        return result
    if isinstance(value, list):
        return [_alias_context_keys(item) for item in value]
    return value


_MAX_UNIQUE_LINES = 10_000


def _repeated_line_payload(text: str) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in (item.strip() for item in text.splitlines()):
        if not line:
            continue
        if line not in counts:
            if len(order) >= _MAX_UNIQUE_LINES:
                return ""  # too many unique lines, skip line-based encoding
            order.append(line)
        counts[line] = counts.get(line, 0) + 1
    repeated = [{"n": counts[line], "x": line} for line in order if counts[line] > 1]
    if not repeated:
        return ""
    singles = [line for line in order if counts[line] == 1]
    return "GE1-LINES " + _compact_json({"repeat": repeated, "single": singles})


# ---------------------------------------------------------------------------
# Main encoding entry point
# ---------------------------------------------------------------------------


def encode_context(raw: str, *, disabled: bool = False) -> ContextPayload:
    """Attempt Ψ (GE1) compression on raw context text.

    Returns a ContextPayload with:
    - raw_context always preserved (original text including whitespace)
    - encoded_context only if compression is effective
    - encoding_status indicating result
    """
    if raw is None:
        raise TypeError("encode_context requires a string, got None")
    raw_context = raw  # preserve original per docstring contract
    working = raw.strip()
    raw_chars = len(working)

    if not working:
        return ContextPayload(
            raw_context=raw_context,
            raw_context_chars=raw_chars,
            encoding_status="none",
        )

    if disabled:
        return ContextPayload(
            raw_context=raw_context,
            raw_context_chars=raw_chars,
            encoding_status="disabled",
        )

    try:
        encoded = ""
        encoding_format = ""

        # Try GE1-JSON first
        try:
            parsed = json.loads(working)
            encoded = "GE1-JSON " + _compact_json(_alias_context_keys(parsed))
            encoding_format = "GE1-JSON"
        except json.JSONDecodeError:
            # Fall back to GE1-LINES
            encoded = _repeated_line_payload(working)
            if encoded:
                encoding_format = "GE1-LINES"

        if not encoded:
            return ContextPayload(
                raw_context=raw_context,
                raw_context_chars=raw_chars,
                encoding_status="raw_unstructured",
            )

        encoded_chars = len(encoded)

        if encoded_chars >= raw_chars:
            return ContextPayload(
                raw_context=raw_context,
                raw_context_chars=raw_chars,
                encoding_status="raw_not_smaller",
                encoding_format=encoding_format,
                encoding_ratio=round(encoded_chars / raw_chars, 4) if raw_chars else 1.0,
            )

        return ContextPayload(
            raw_context=raw_context,
            raw_context_chars=raw_chars,
            encoding_status="encoded",
            encoded_context=encoded,
            encoding_format=encoding_format,
            encoding_ratio=round(encoded_chars / raw_chars, 4),
            estimated_token_delta=_estimate_token_delta(working, encoded),
        )

    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError, RecursionError) as exc:
        return ContextPayload(
            raw_context=raw_context,
            raw_context_chars=raw_chars,
            encoding_status="error_raw_fallback",
            error=f"{type(exc).__name__}: {exc}"[:400],
        )


def _estimate_token_delta(raw: str, encoded: str) -> int:
    return round((len(raw.encode("utf-8")) - len(encoded.encode("utf-8"))) / 4)
