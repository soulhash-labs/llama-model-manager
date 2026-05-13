import os
import unittest
from pathlib import Path

# test_glyph_codec.py
from glyphos_ai.glyph import (
    GlyphCodecError,
    GlyphRegistryError,
    bytes_to_glyph_stream,
    bytes_to_json,
    decode_bytes_to_entries,
    decode_bytes_to_glyphs,
    decode_bytes_to_names,
    encode_glyphs_to_bytes,
    encode_names_to_bytes,
    glyph_stream_to_bytes,
    glyph_stream_to_json,
    load_registry,
    normalize_glyph_stream,
    tokenize_glyph_stream,
)


class GlyphCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_registry.cache_clear()
        cls.registry = load_registry()

    def test_tokenize_simple_stream(self) -> None:
        tokens = tokenize_glyph_stream("⊕ 🌍 1️⃣ ✨", registry=self.registry)
        self.assertEqual(len(tokens), 4)
        self.assertEqual(tokens[0].kind, "glyph")
        self.assertEqual(tokens[0].entry.name, "merge")
        self.assertEqual(tokens[1].entry.name, "earth")
        self.assertEqual(tokens[2].entry.name, "one")
        self.assertEqual(tokens[3].entry.name, "sparkle")

    def test_tokenize_multicodepoint_glyph(self) -> None:
        tokens = tokenize_glyph_stream("🏴‍☠️", registry=self.registry)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].entry.name, "pirate_net")
        self.assertEqual(tokens[0].entry.code, 0x72)

    def test_tokenize_unknown_raises_by_default(self) -> None:
        with self.assertRaises(GlyphCodecError):
            tokenize_glyph_stream("⊕ X 🌍", registry=self.registry)

    def test_tokenize_unknown_can_be_preserved(self) -> None:
        tokens = tokenize_glyph_stream(
            "⊕ X 🌍",
            registry=self.registry,
            preserve_unknown_literals=True,
        )
        self.assertEqual(len(tokens), 3)
        self.assertEqual(tokens[0].kind, "glyph")
        self.assertEqual(tokens[1].kind, "literal")
        self.assertEqual(tokens[1].value, "X")
        self.assertEqual(tokens[2].kind, "glyph")

    def test_encode_glyphs_to_bytes(self) -> None:
        payload = encode_glyphs_to_bytes(["⊕", "🌍", "1️⃣", "✨"], registry=self.registry)
        self.assertEqual(payload, bytes([0x00, 0x40, 0x81, 0xC0]))

    def test_encode_names_to_bytes(self) -> None:
        payload = encode_names_to_bytes(["merge", "earth", "one", "sparkle"], registry=self.registry)
        self.assertEqual(payload, bytes([0x00, 0x40, 0x81, 0xC0]))

    def test_glyph_stream_to_bytes(self) -> None:
        payload = glyph_stream_to_bytes("⊕ 🌍 1️⃣ ✨", registry=self.registry)
        self.assertEqual(payload.hex(), "004081c0")

    def test_decode_bytes_to_entries(self) -> None:
        entries = decode_bytes_to_entries(bytes([0x00, 0x40, 0x81, 0xC0]), registry=self.registry)
        self.assertEqual([e.name for e in entries], ["merge", "earth", "one", "sparkle"])

    def test_decode_bytes_to_glyphs(self) -> None:
        glyphs = decode_bytes_to_glyphs(bytes([0x00, 0x40, 0x81, 0xC0]), registry=self.registry)
        self.assertEqual(glyphs, ["⊕", "🌍", "1️⃣", "✨"])

    def test_decode_bytes_to_names(self) -> None:
        names = decode_bytes_to_names(bytes([0x00, 0x40, 0x81, 0xC0]), registry=self.registry)
        self.assertEqual(names, ["merge", "earth", "one", "sparkle"])

    def test_bytes_to_glyph_stream(self) -> None:
        stream = bytes_to_glyph_stream(bytes([0x00, 0x40, 0x81, 0xC0]), registry=self.registry)
        self.assertEqual(stream, "⊕ 🌍 1️⃣ ✨")

    def test_normalize_glyph_stream(self) -> None:
        stream = normalize_glyph_stream("  ⊕   🌍   1️⃣   ✨  ", registry=self.registry)
        self.assertEqual(stream, "⊕ 🌍 1️⃣ ✨")

    def test_glyph_stream_to_json(self) -> None:
        data = glyph_stream_to_json("⊕ 🌍 1️⃣ ✨", registry=self.registry)
        self.assertEqual(data["raw"], "⊕ 🌍 1️⃣ ✨")
        self.assertEqual(data["normalized"], "⊕ 🌍 1️⃣ ✨")
        self.assertTrue(data["encodable"])
        self.assertEqual(data["token_count"], 4)
        self.assertEqual(data["glyph_count"], 4)
        self.assertEqual(data["mnemonic"], "merge earth one sparkle")
        self.assertEqual(data["glyph_byte_values"], [0x00, 0x40, 0x81, 0xC0])
        self.assertEqual(data["glyph_hex"], "004081c0")

    def test_glyph_stream_to_json_with_literals(self) -> None:
        data = glyph_stream_to_json(
            "⊕ RAW 🌍",
            registry=self.registry,
            preserve_unknown_literals=True,
        )
        self.assertFalse(data["encodable"])
        self.assertEqual(data["token_count"], 3)
        self.assertEqual(data["glyph_count"], 2)
        self.assertEqual(data["tokens"][1]["kind"], "literal")
        self.assertEqual(data["tokens"][1]["value"], "RAW")

    def test_bytes_to_json(self) -> None:
        data = bytes_to_json(bytes([0x00, 0x40, 0x81, 0xC0]), registry=self.registry)
        self.assertEqual(data["raw_bytes"], [0x00, 0x40, 0x81, 0xC0])
        self.assertEqual(data["hex"], "004081c0")
        self.assertEqual(data["normalized"], "⊕ 🌍 1️⃣ ✨")
        self.assertEqual(data["mnemonic"], "merge earth one sparkle")
        self.assertEqual(data["token_count"], 4)

    def test_encode_unknown_glyph_raises(self) -> None:
        with self.assertRaises(GlyphCodecError):
            encode_glyphs_to_bytes(["⊕", "NOT_REAL"], registry=self.registry)

    def test_encode_unknown_name_raises(self) -> None:
        with self.assertRaises(GlyphCodecError):
            encode_names_to_bytes(["merge", "not_real_name"], registry=self.registry)

    def test_registry_unknown_code_path(self) -> None:
        with self.assertRaises(GlyphRegistryError):
            self.registry.get_by_code(0x100)

    def test_round_trip_stream_bytes_stream(self) -> None:
        original = "⊕ 🌍 1️⃣ ✨"
        payload = glyph_stream_to_bytes(original, registry=self.registry)
        reconstructed = bytes_to_glyph_stream(payload, registry=self.registry)
        self.assertEqual(reconstructed, original)

    # ------------------------------------------------------------------
    # Defensive input validation
    # ------------------------------------------------------------------

    def test_decode_bytes_to_entries_rejects_none(self) -> None:
        with self.assertRaises(GlyphCodecError):
            decode_bytes_to_entries(None, registry=self.registry)

    def test_decode_bytes_to_entries_rejects_string(self) -> None:
        with self.assertRaises(TypeError):
            decode_bytes_to_entries("not bytes", registry=self.registry)

    def test_tokenize_glyph_stream_bare_string(self) -> None:
        """tokenize_glyph_stream calls str() on input so ints are safe."""
        tokens = tokenize_glyph_stream("⊕ 🌍", registry=self.registry)
        self.assertEqual(len(tokens), 2)


# ------------------------------------------------------------------
# Byte-level encoder/decoder integration tests
# ------------------------------------------------------------------


class EncoderDecoderTests(unittest.TestCase):
    """Tests for the byte-level glyph encoder/decoder (encoder.py / decoder.py)."""

    def test_decoder_does_not_import_encoder(self) -> None:
        """decoder.py must NOT import encoder.py — decoder owns its imports."""
        import subprocess
        import sys

        # Point the subprocess at the glyph source with an absolute path so the
        # import test works regardless of how the parent process set PYTHONPATH.
        _glyph_root = str(Path(__file__).resolve().parents[1] / "integrations/public-glyphos-ai-compute")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from glyphos_ai.glyph.decoder import decode_text, decode_to_bytes, GlyphDecoder",
            ],
            capture_output=True,
            text=True,
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
                "PYTHONPATH": _glyph_root,
            },
            cwd=str(Path(__file__).resolve().parents[0]),
        )
        if result.returncode != 0:
            self.fail(f"import decoder failed:\n{result.stderr}")

        import ast

        decoder_path = (
            Path(__file__).resolve().parents[1] / "integrations/public-glyphos-ai-compute/glyphos_ai/glyph/decoder.py"
        )
        tree = ast.parse(decoder_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "encoder" in node.module:
                    self.fail(f"decoder.py still imports from encoder: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "encoder" in alias.name:
                        self.fail(f"decoder.py still imports encoder: import {alias.name}")

    def test_encode_decode_round_trip(self) -> None:
        """Basic byte-level encode → decode round-trip passes."""
        from glyphos_ai.glyph.decoder import decode_text
        from glyphos_ai.glyph.encoder import encode_text

        original = "Hello, GlyphOS!"
        encoded = encode_text(original, include_header=True)
        decoded = decode_text(encoded)
        self.assertEqual(decoded, original)

    def test_encode_decode_round_trip_no_header(self) -> None:
        from glyphos_ai.glyph.decoder import decode_text
        from glyphos_ai.glyph.encoder import encode_text

        original = "no-header test"
        encoded = encode_text(original, include_header=False)
        decoded = decode_text(encoded)
        self.assertEqual(decoded, original)

    def test_decode_text_errors_replace(self) -> None:
        """decode_text with errors='replace' should not raise on invalid UTF-8
        if such bytes are somehow produced."""
        from glyphos_ai.glyph.decoder import decode_text
        from glyphos_ai.glyph.encoder import encode_bytes

        mangled = encode_bytes(b"abc", include_header=False)
        result = decode_text(mangled, errors="replace")
        self.assertIsInstance(result, str)

    def test_decode_tokens_rejects_non_list(self) -> None:
        from glyphos_ai.glyph.decoder import GlyphDecoder

        decoder = GlyphDecoder()
        with self.assertRaises(TypeError):
            decoder.decode_tokens("not-a-list")  # type: ignore[arg-type]

    def test_decode_tokens_rejects_non_string_items(self) -> None:
        from glyphos_ai.glyph.decoder import GlyphDecoder, GlyphDecodingError

        decoder = GlyphDecoder()
        with self.assertRaises(GlyphDecodingError):
            decoder.decode_tokens([42, 73])  # type: ignore[list-item]

    def test_decode_tokens_strict_unknown_raises(self) -> None:
        from glyphos_ai.glyph.decoder import GlyphDecoder, GlyphDecodingError

        decoder = GlyphDecoder()
        with self.assertRaises(GlyphDecodingError):
            decoder.decode_tokens(["\ue000", "NOT_A_GLYPH"], strict=True)

    def test_decode_tokens_non_strict_unknown_skips(self) -> None:
        from glyphos_ai.glyph.decoder import GlyphDecoder

        decoder = GlyphDecoder()
        result = decoder.decode_tokens(["\ue000", "NOT_A_GLYPH"], strict=False)
        self.assertEqual(result, b"\x00")

    def test_context_encoding_rejects_none(self) -> None:
        from glyphos_ai.glyph.context_encoding import encode_context

        with self.assertRaises(TypeError):
            encode_context(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
