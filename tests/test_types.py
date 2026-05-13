import unittest

from glyphos_ai.glyph import (
    ACTION_MAP,
    DEST_MAP,
    GlyphPacket,
    Glyphs,
    Intent,
    action_to_glyph,
    destination_to_glyph,
    level_to_psi,
    normalize_psi,
    normalize_time_slot,
    packet_to_compat_dict,
    psi_to_level,
    slot_to_time,
    time_to_slot,
    validate_context_packet_shape,
)


class IntentTests(unittest.TestCase):
    def test_intent_normalized(self) -> None:
        intent = Intent(
            action=" query ",
            destination=" model ",
            time_slot=7,
            modifiers=["  alpha  ", "", "beta"],
            coherence=1.2,
        ).normalized()

        self.assertEqual(intent.action, "QUERY")
        self.assertEqual(intent.destination, "MODEL")
        self.assertEqual(intent.time_slot, 7)
        self.assertEqual(intent.modifiers, ["alpha", "beta"])
        self.assertEqual(intent.coherence, 1.0)

    def test_intent_normalized_negative_time_slot_clamped(self) -> None:
        intent = Intent(action="book", destination="mars", time_slot=-4).normalized()
        self.assertEqual(intent.time_slot, 0)


class GlyphPacketTests(unittest.TestCase):
    def test_packet_init_normalizes_fields(self) -> None:
        packet = GlyphPacket(
            instance_id=" abc123 ",
            psi_coherence=1.5,
            action=" query ",
            time_slot="t7",
            destination=" model ",
            modifiers=["  x ", "", "y"],
            packet_version=2,
        )

        self.assertEqual(packet.instance_id, "abc123")
        self.assertEqual(packet.psi_coherence, 1.0)
        self.assertEqual(packet.action, "QUERY")
        self.assertEqual(packet.header, Glyphs.HEADER)
        self.assertEqual(packet.time_slot, "T07")
        self.assertEqual(packet.destination, "MODEL")
        self.assertEqual(packet.modifiers, ["x", "y"])
        self.assertEqual(packet.packet_version, 2)

    def test_packet_camelcase_aliases(self) -> None:
        packet = GlyphPacket(
            instance_id="abc123",
            psi_coherence=0.82,
            action="QUERY",
            time_slot="T07",
            destination="MODEL",
        )

        self.assertEqual(packet.instanceId, "abc123")
        self.assertEqual(packet.psiCoherence, 0.82)
        self.assertEqual(packet.timeSlot, "T07")

    def test_packet_to_dict(self) -> None:
        packet = GlyphPacket(
            instance_id="abc123",
            psi_coherence=0.5,
            action="QUERY",
            time_slot="T03",
            destination="MODEL",
        )
        data = packet.to_dict()

        self.assertEqual(data["instance_id"], "abc123")
        self.assertEqual(data["psi_coherence"], 0.5)
        self.assertEqual(data["action"], "QUERY")
        self.assertEqual(data["time_slot"], "T03")
        self.assertEqual(data["destination"], "MODEL")

    def test_packet_from_intent(self) -> None:
        intent = Intent(
            action="query",
            destination="model",
            time_slot=7,
            modifiers=["alpha"],
        )
        packet = GlyphPacket.from_intent("abc123", intent, psi_coherence=0.83)

        self.assertEqual(packet.instance_id, "abc123")
        self.assertEqual(packet.psi_coherence, 0.83)
        self.assertEqual(packet.action, "QUERY")
        self.assertEqual(packet.time_slot, "T07")
        self.assertEqual(packet.destination, "MODEL")
        self.assertEqual(packet.modifiers, ["alpha"])

    def test_packet_from_mapping_snake_case(self) -> None:
        packet = GlyphPacket.from_mapping(
            {
                "instance_id": "abc123",
                "psi_coherence": 0.77,
                "action": "query",
                "time_slot": "T07",
                "destination": "model",
                "modifiers": ["x"],
                "packet_version": 3,
            }
        )

        self.assertEqual(packet.instance_id, "abc123")
        self.assertEqual(packet.psi_coherence, 0.77)
        self.assertEqual(packet.action, "QUERY")
        self.assertEqual(packet.time_slot, "T07")
        self.assertEqual(packet.destination, "MODEL")
        self.assertEqual(packet.modifiers, ["x"])
        self.assertEqual(packet.packet_version, 3)

    def test_packet_from_mapping_camel_case(self) -> None:
        packet = GlyphPacket.from_mapping(
            {
                "instanceId": "abc123",
                "psiCoherence": 0.61,
                "action": "book",
                "timeSlot": "T03",
                "destination": "mars",
                "packetVersion": 2,
            }
        )

        self.assertEqual(packet.instance_id, "abc123")
        self.assertEqual(packet.psi_coherence, 0.61)
        self.assertEqual(packet.action, "BOOK")
        self.assertEqual(packet.time_slot, "T03")
        self.assertEqual(packet.destination, "MARS")
        self.assertEqual(packet.packet_version, 2)


class PsiHelperTests(unittest.TestCase):
    def test_normalize_psi_clamps(self) -> None:
        self.assertEqual(normalize_psi(-1.0), 0.0)
        self.assertEqual(normalize_psi(0.25), 0.25)
        self.assertEqual(normalize_psi(2.0), 1.0)

    def test_psi_to_level(self) -> None:
        self.assertEqual(psi_to_level(0.0), "Ψ0")
        self.assertEqual(psi_to_level(0.19), "Ψ1")
        self.assertEqual(psi_to_level(0.5), "Ψ5")
        self.assertEqual(psi_to_level(0.99), "Ψ9")
        self.assertEqual(psi_to_level(1.0), "Ψ9")

    def test_level_to_psi(self) -> None:
        self.assertEqual(level_to_psi("Ψ0"), 0.0)
        self.assertEqual(level_to_psi("Ψ5"), 0.5)
        self.assertEqual(level_to_psi("Ψ9"), 0.9)
        self.assertEqual(level_to_psi("NOPE"), 0.0)


class TimeHelperTests(unittest.TestCase):
    def test_time_to_slot(self) -> None:
        self.assertEqual(time_to_slot(0), "T00")
        self.assertEqual(time_to_slot(7), "T07")
        self.assertEqual(time_to_slot(12), "T12")
        self.assertEqual(time_to_slot(-1), "T00")

    def test_slot_to_time(self) -> None:
        self.assertEqual(slot_to_time("T00"), 0)
        self.assertEqual(slot_to_time("T07"), 7)
        self.assertEqual(slot_to_time("12"), 12)
        self.assertEqual(slot_to_time("bad"), 0)

    def test_normalize_time_slot(self) -> None:
        self.assertEqual(normalize_time_slot("t7"), "T07")
        self.assertEqual(normalize_time_slot("T03"), "T03")
        self.assertEqual(normalize_time_slot(9), "T09")
        self.assertEqual(normalize_time_slot("bad"), "T00")


class ContextPacketValidationTests(unittest.TestCase):
    def test_validate_context_packet_shape_minimal(self) -> None:
        ctx = validate_context_packet_shape({"content": "LANE_STATE(AURORA): healthy"})
        self.assertEqual(ctx["content"], "LANE_STATE(AURORA): healthy")
        self.assertNotIn("locality", ctx)

    def test_validate_context_packet_shape_full(self) -> None:
        ctx = validate_context_packet_shape(
            {
                "content": "LANE_STATE(AURORA): healthy",
                "locality": "orion-local",
                "freshness": 1717000000.0,
                "provenance": ["aurora-health", "ops-heartbeat"],
                "routing_hints": {"preferred_backend": "llamacpp", "token_budget": 2048},
                "metadata": {"operator": "angelo"},
                "source": "ops",
            }
        )

        self.assertEqual(ctx["content"], "LANE_STATE(AURORA): healthy")
        self.assertEqual(ctx["locality"], "orion-local")
        self.assertEqual(ctx["freshness"], 1717000000.0)
        self.assertEqual(ctx["provenance"], ["aurora-health", "ops-heartbeat"])
        self.assertEqual(ctx["routing_hints"]["preferred_backend"], "llamacpp")
        self.assertEqual(ctx["routing_hints"]["token_budget"], 2048)
        self.assertEqual(ctx["metadata"]["operator"], "angelo")
        self.assertEqual(ctx["source"], "ops")

    def test_validate_context_packet_shape_accepts_none(self) -> None:
        ctx = validate_context_packet_shape(None)
        self.assertEqual(ctx, {})

    def test_validate_context_packet_shape_rejects_non_mapping(self) -> None:
        with self.assertRaises(TypeError):
            validate_context_packet_shape("not-a-mapping")

    def test_validate_context_packet_shape_rejects_bad_locality(self) -> None:
        with self.assertRaises(ValueError):
            validate_context_packet_shape({"locality": "somewhere-else"})

    def test_validate_context_packet_shape_rejects_bad_provenance(self) -> None:
        with self.assertRaises(ValueError):
            validate_context_packet_shape({"provenance": "not-a-list"})

    def test_validate_context_packet_shape_rejects_bad_routing_hints(self) -> None:
        with self.assertRaises(ValueError):
            validate_context_packet_shape({"routing_hints": "not-a-mapping"})

    def test_validate_context_packet_shape_rejects_bad_metadata(self) -> None:
        with self.assertRaises(ValueError):
            validate_context_packet_shape({"metadata": "not-a-mapping"})

    def test_validate_context_packet_shape_rejects_bad_freshness(self) -> None:
        with self.assertRaises(ValueError):
            validate_context_packet_shape({"freshness": "not-a-float"})


class MappingHelperTests(unittest.TestCase):
    def test_action_to_glyph(self) -> None:
        self.assertEqual(action_to_glyph("BOOK"), ACTION_MAP["BOOK"])
        self.assertEqual(action_to_glyph("query"), ACTION_MAP["QUERY"])

    def test_action_to_glyph_unknown_falls_back(self) -> None:
        self.assertEqual(action_to_glyph("NOT_REAL"), Glyphs.ACTION_QUERY)

    def test_destination_to_glyph(self) -> None:
        self.assertEqual(destination_to_glyph("MARS"), DEST_MAP["MARS"])
        self.assertEqual(destination_to_glyph("model"), DEST_MAP["MODEL"])

    def test_destination_to_glyph_unknown_falls_back_to_uppercase_text(self) -> None:
        self.assertEqual(destination_to_glyph("mystery"), "MYSTERY")

    def test_packet_to_compat_dict(self) -> None:
        packet = GlyphPacket(
            instance_id="abc123",
            psi_coherence=0.73,
            action="QUERY",
            time_slot="T07",
            destination="MODEL",
            modifiers=["alpha"],
            packet_version=2,
        )
        data = packet_to_compat_dict(packet)

        self.assertEqual(data["instance_id"], "abc123")
        self.assertEqual(data["instanceId"], "abc123")
        self.assertEqual(data["psi_coherence"], 0.73)
        self.assertEqual(data["psiCoherence"], 0.73)
        self.assertEqual(data["time_slot"], "T07")
        self.assertEqual(data["timeSlot"], "T07")
        self.assertEqual(data["action"], "QUERY")
        self.assertEqual(data["destination"], "MODEL")
        self.assertEqual(data["modifiers"], ["alpha"])
        self.assertEqual(data["packet_version"], 2)
        self.assertEqual(data["packetVersion"], 2)


if __name__ == "__main__":
    unittest.main()
