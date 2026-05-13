import unittest

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


if __name__ == "__main__":
    unittest.main()
