"""
Context Encoding (Ψ Compression)
=================================
Extracts glyph encoding logic from the gateway into the glyphos_ai package.
The router inspects ContextPayload to decide whether to apply encoding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _alias_context_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            GLYPH_KEY_ALIASES.get(str(key), str(key)): _alias_context_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_alias_context_keys(item) for item in value]
    return value


def _repeated_line_payload(text: str) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in (item.strip() for item in text.splitlines()):
        if not line:
            continue
        if line not in counts:
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


def encode_context(raw: str, *, disabled: bool = False, force_error: bool = False) -> ContextPayload:
    """Attempt Ψ (GE1) compression on raw context text.

    Returns a ContextPayload with:
    - raw_context always preserved
    - encoded_context only if compression is effective
    - encoding_status indicating result

    The router calls this ONLY when targeting local llama.cpp.
    Cloud backends receive ContextPayload(encoding_status="skipped").
    """
    raw = raw.strip()
    raw_chars = len(raw)

    if not raw:
        return ContextPayload(
            raw_context=raw,
            raw_context_chars=raw_chars,
            encoding_status="none",
        )

    if disabled:
        return ContextPayload(
            raw_context=raw,
            raw_context_chars=raw_chars,
            encoding_status="disabled",
        )

    if force_error:
        return ContextPayload(
            raw_context=raw,
            raw_context_chars=raw_chars,
            encoding_status="error_raw_fallback",
            error="forced glyph encoding failure",
        )

    try:
        encoded = ""
        encoding_format = ""

        # Try GE1-JSON first
        try:
            parsed = json.loads(raw)
            encoded = "GE1-JSON " + _compact_json(_alias_context_keys(parsed))
            encoding_format = "GE1-JSON"
        except json.JSONDecodeError:
            # Fall back to GE1-LINES
            encoded = _repeated_line_payload(raw)
            if encoded:
                encoding_format = "GE1-LINES"

        if not encoded:
            return ContextPayload(
                raw_context=raw,
                raw_context_chars=raw_chars,
                encoding_status="raw_unstructured",
            )

        encoded_chars = len(encoded)

        if encoded_chars >= raw_chars:
            return ContextPayload(
                raw_context=raw,
                raw_context_chars=raw_chars,
                encoding_status="raw_not_smaller",
                encoding_format=encoding_format,
                encoding_ratio=round(encoded_chars / raw_chars, 4) if raw_chars else 1.0,
            )

        return ContextPayload(
            raw_context=raw,
            raw_context_chars=raw_chars,
            encoding_status="encoded",
            encoded_context=encoded,
            encoding_format=encoding_format,
            encoding_ratio=round(encoded_chars / raw_chars, 4),
            estimated_token_delta=round((raw_chars - encoded_chars) / 4),
        )

    except Exception as exc:
        return ContextPayload(
            raw_context=raw,
            raw_context_chars=raw_chars,
            encoding_status="error_raw_fallback",
            error=str(exc)[:400],
        )
