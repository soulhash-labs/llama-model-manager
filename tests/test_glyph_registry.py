import unittest

from glyphos_ai.glyph import (
    GlyphRegistryError,
    load_registry,
)


class GlyphRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # In case you rerun in the same process after edits
        load_registry.cache_clear()
        cls.registry = load_registry()

    def test_registry_loads(self) -> None:
        self.assertEqual(len(self.registry), 256)

    def test_registry_summary(self) -> None:
        summary = self.registry.summary()
        self.assertEqual(summary["entry_count"], 256)
        self.assertEqual(summary["bucket_counts"]["actions"], 64)
        self.assertEqual(summary["bucket_counts"]["destinations"], 64)
        self.assertEqual(summary["bucket_counts"]["time_quantity"], 64)
        self.assertEqual(summary["bucket_counts"]["sacred_mods"], 64)
        self.assertEqual(summary["codes_min"], 0x00)
        self.assertEqual(summary["codes_max"], 0xFF)

    def test_lookup_by_code(self) -> None:
        entry = self.registry.get_by_code(0x00)
        self.assertEqual(entry.bucket, "actions")
        self.assertEqual(entry.glyph, "⊕")
        self.assertEqual(entry.name, "merge")

    def test_lookup_by_glyph(self) -> None:
        entry = self.registry.get_by_glyph("🌍")
        self.assertEqual(entry.code, 0x40)
        self.assertEqual(entry.bucket, "destinations")
        self.assertEqual(entry.name, "earth")

    def test_lookup_by_name_is_case_insensitive(self) -> None:
        entry = self.registry.get_by_name("EaRtH")
        self.assertEqual(entry.code, 0x40)
        self.assertEqual(entry.glyph, "🌍")

    def test_match_glyph_at_supports_multicodepoint_glyphs(self) -> None:
        stream = "🏴‍☠️ ☣"
        match = self.registry.match_glyph_at(stream, 0)
        self.assertIsNotNone(match)
        entry, next_i = match
        self.assertEqual(entry.name, "pirate_net")
        self.assertEqual(entry.code, 0x72)
        self.assertGreater(next_i, 1)

    def test_has_helpers(self) -> None:
        self.assertTrue(self.registry.has_code(0x00))
        self.assertTrue(self.registry.has_glyph("⊕"))
        self.assertTrue(self.registry.has_name("merge"))

        self.assertFalse(self.registry.has_code(0x100))
        self.assertFalse(self.registry.has_glyph("X_NOT_A_GLYPH"))
        self.assertFalse(self.registry.has_name("not_real"))

    def test_unknown_code_raises(self) -> None:
        with self.assertRaises(GlyphRegistryError):
            self.registry.get_by_code(0x100)

    def test_unknown_glyph_raises(self) -> None:
        with self.assertRaises(GlyphRegistryError):
            self.registry.get_by_glyph("NOPE")

    def test_unknown_name_raises(self) -> None:
        with self.assertRaises(GlyphRegistryError):
            self.registry.get_by_name("not_real_name")

    def test_to_dict_contains_all_buckets(self) -> None:
        data = self.registry.to_dict()
        self.assertIn("actions", data)
        self.assertIn("destinations", data)
        self.assertIn("time_quantity", data)
        self.assertIn("sacred_mods", data)
        self.assertEqual(len(data["actions"]), 64)
        self.assertEqual(len(data["destinations"]), 64)
        self.assertEqual(len(data["time_quantity"]), 64)
        self.assertEqual(len(data["sacred_mods"]), 64)

    def test_entries_are_sorted_by_code(self) -> None:
        codes = [entry.code for entry in self.registry.entries]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(codes[0], 0x00)
        self.assertEqual(codes[-1], 0xFF)


if __name__ == "__main__":
    unittest.main()
