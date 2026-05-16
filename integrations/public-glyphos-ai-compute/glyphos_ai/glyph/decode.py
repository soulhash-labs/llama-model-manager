"""
Legacy compatibility shim.

Preferred modern import:
    from glyphos_ai.glyph.decoder import decode_text

Old code that does:
    from glyphos_ai.glyph.decode import decode_text
still works via this re-export module.
"""

from __future__ import annotations

try:
    from .decoder import (
        GlyphDecoder,
        GlyphDecodingError,
        decode,
        decode_base64_payload,
        decode_string,
        decode_text,
        decode_to_bytes,
        decode_utf8,
    )
except ModuleNotFoundError:
    from decoder import (  # type: ignore
        GlyphDecoder,
        GlyphDecodingError,
        decode,
        decode_base64_payload,
        decode_string,
        decode_text,
        decode_to_bytes,
        decode_utf8,
    )

__all__ = [
    "GlyphDecoder",
    "GlyphDecodingError",
    "decode",
    "decode_base64_payload",
    "decode_string",
    "decode_text",
    "decode_to_bytes",
    "decode_utf8",
]


def main() -> int:
    try:
        from .decoder import _main
    except ModuleNotFoundError:
        from decoder import _main  # type: ignore
    return _main()


if __name__ == "__main__":
    raise SystemExit(main())
