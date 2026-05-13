import builtins
import unittest
from unittest.mock import patch

from glyphos_ai.ai_compute.glyph_to_prompt import (
    glyph_to_prompt,
    glyph_to_structured_json,
)
from glyphos_ai.ai_compute.router import (
    AdaptiveRouter,
    ComputeTarget,
    route_with_configured_clients,
)
from glyphos_ai.glyph.types import GlyphPacket, validate_context_packet_shape


class CapturingClient:
    """
    Minimal backend stub.

    Stores prompts so tests can assert prompt-shaping and routing behavior.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return f"{self.label}:{prompt}"

    @property
    def last_prompt(self) -> str | None:
        return self.calls[-1] if self.calls else None


class ErrorClient:
    """Backend stub that always raises."""

    def __init__(self, label: str) -> None:
        self.label = label

    def generate(self, prompt: str) -> str:
        raise RuntimeError(f"{self.label} exploded")


class Phase6Q2FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = GlyphPacket(
            instance_id="abc123",
            psi_coherence=0.82,
            action="QUERY",
            time_slot="T07",
            destination="MODEL",
        )

        self.low_psi_packet = GlyphPacket(
            instance_id="abc999",
            psi_coherence=0.25,
            action="QUERY",
            time_slot="T07",
            destination="MODEL",
        )

        self.complex_packet = GlyphPacket(
            instance_id="abc777",
            psi_coherence=0.55,
            action="ANALYZE",
            time_slot="T07",
            destination="MODEL",
        )

        self.ctx_string = "LANE_STATE(AURORA): healthy"

        self.ctx_packet = validate_context_packet_shape(
            {
                "content": "LANE_STATE(AURORA): healthy",
                "locality": "orion-local",
                "freshness": 1717000000.0,
                "provenance": ["aurora-health", "ops-heartbeat"],
                "routing_hints": {
                    "preferred_backend": "llamacpp",
                    "token_budget": 2048,
                },
                "metadata": {"operator": "angelo"},
                "source": "ops",
            }
        )

    # ------------------------------------------------------------------
    # Public import / contract integrity
    # ------------------------------------------------------------------

    def test_public_import_surface(self) -> None:
        # This should fail loudly if __init__.py does not export the public API.
        from glyphos_ai import AdaptiveRouter as PublicAdaptiveRouter
        from glyphos_ai import ContextPacket as PublicContextPacket

        self.assertIs(PublicAdaptiveRouter, AdaptiveRouter)

        packet: PublicContextPacket = {  # type: ignore[valid-type]
            "content": "LANE_STATE(AURORA): healthy",
            "locality": "orion-local",
        }
        self.assertIn("content", packet)

    # ------------------------------------------------------------------
    # glyph_to_prompt behavior
    # ------------------------------------------------------------------

    def test_glyph_to_prompt_no_context_has_no_anchor(self) -> None:
        prompt = glyph_to_prompt(self.packet)
        self.assertIn("User queries MODEL", prompt)
        self.assertNotIn("[CONTEXT_ANCHOR]", prompt)
        self.assertNotIn("[CONTEXT_METADATA]", prompt)

    def test_glyph_to_prompt_string_context_adds_anchor(self) -> None:
        prompt = glyph_to_prompt(self.packet, upstream_context=self.ctx_string)
        self.assertIn("[CONTEXT_ANCHOR]", prompt)
        self.assertIn(self.ctx_string, prompt)
        self.assertNotIn("[CONTEXT_METADATA]", prompt)

    def test_glyph_to_prompt_context_packet_adds_anchor_and_metadata(self) -> None:
        prompt = glyph_to_prompt(self.packet, upstream_context=self.ctx_packet)
        self.assertIn("[CONTEXT_ANCHOR]", prompt)
        self.assertIn("LANE_STATE(AURORA): healthy", prompt)
        self.assertIn("[CONTEXT_METADATA]", prompt)
        self.assertIn("locality: orion-local", prompt)
        self.assertIn("freshness: 1717000000.0", prompt)
        self.assertIn("provenance: aurora-health, ops-heartbeat", prompt)
        self.assertIn('"preferred_backend": "llamacpp"', prompt)
        self.assertIn('"token_budget": 2048', prompt)

    # ------------------------------------------------------------------
    # glyph_to_structured_json behavior
    # ------------------------------------------------------------------

    def test_glyph_to_structured_json_without_context(self) -> None:
        data = glyph_to_structured_json(self.packet)

        self.assertEqual(data["intent"]["action"], "QUERY")
        self.assertEqual(data["intent"]["target"], "MODEL")
        self.assertFalse(data["context"]["upstream_context_present"])
        self.assertFalse(data["context"]["upstream_content_present"])
        self.assertEqual(data["routing"]["preferred_backend_source"], "coherence_default")

    def test_glyph_to_structured_json_with_context(self) -> None:
        data = glyph_to_structured_json(self.packet, upstream_context=self.ctx_packet)

        self.assertTrue(data["context"]["upstream_context_present"])
        self.assertTrue(data["context"]["upstream_content_present"])
        self.assertEqual(data["context"]["upstream"]["locality"], "orion-local")
        self.assertEqual(
            data["context"]["upstream"]["provenance"],
            ["aurora-health", "ops-heartbeat"],
        )
        self.assertEqual(
            data["routing"]["preferred_backend"],
            "llamacpp",
        )
        self.assertEqual(
            data["routing"]["preferred_backend_source"],
            "routing_hints",
        )
        self.assertEqual(data["routing"]["token_budget"], 2048)

    # ------------------------------------------------------------------
    # AdaptiveRouter backward compatibility
    # ------------------------------------------------------------------

    def test_route_without_context_is_backward_compatible(self) -> None:
        llamacpp = CapturingClient("llamacpp")
        router = AdaptiveRouter(llamacpp_client=llamacpp)

        result = router.route(self.packet)

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIn("local", result.routing_reason.lower())
        self.assertIsNotNone(llamacpp.last_prompt)
        self.assertNotIn("[CONTEXT_ANCHOR]", llamacpp.last_prompt or "")

    def test_route_with_explicit_prompt_preserves_existing_call_shape(self) -> None:
        llamacpp = CapturingClient("llamacpp")
        router = AdaptiveRouter(llamacpp_client=llamacpp)

        result = router.route(self.packet, prompt="manual prompt")

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertEqual(llamacpp.last_prompt, "manual prompt")
        self.assertEqual(result.response, "llamacpp:manual prompt")

    # ------------------------------------------------------------------
    # AdaptiveRouter + upstream context
    # ------------------------------------------------------------------

    def test_route_with_string_context_passes_anchor_to_backend(self) -> None:
        llamacpp = CapturingClient("llamacpp")
        router = AdaptiveRouter(llamacpp_client=llamacpp)

        result = router.route(self.packet, upstream_context=self.ctx_string)

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIsNotNone(llamacpp.last_prompt)
        self.assertIn("[CONTEXT_ANCHOR]", llamacpp.last_prompt or "")
        self.assertIn(self.ctx_string, llamacpp.last_prompt or "")

    def test_route_with_context_packet_uses_routing_hint_preferred_backend(self) -> None:
        llamacpp = CapturingClient("llamacpp")
        openai = CapturingClient("openai")
        router = AdaptiveRouter(
            llamacpp_client=llamacpp,
            openai_client=openai,
        )

        ctx = validate_context_packet_shape(
            {
                "content": "MODEL_STATE: warm",
                "routing_hints": {"preferred_backend": "openai"},
                "locality": "orion-local",
            }
        )

        result = router.route(self.low_psi_packet, upstream_context=ctx)

        self.assertEqual(result.target, ComputeTarget.EXTERNAL_OPENAI)
        self.assertIn("routing_hints", result.routing_reason)
        self.assertIsNotNone(openai.last_prompt)
        self.assertIn("[CONTEXT_ANCHOR]", openai.last_prompt or "")
        self.assertIn("MODEL_STATE: warm", openai.last_prompt or "")

    def test_route_complex_action_prefers_anthropic_when_available(self) -> None:
        llamacpp = CapturingClient("llamacpp")
        anthropic = CapturingClient("anthropic")
        router = AdaptiveRouter(
            llamacpp_client=llamacpp,
            anthropic_client=anthropic,
        )

        result = router.route(self.complex_packet)

        self.assertEqual(result.target, ComputeTarget.EXTERNAL_ANTHROPIC)
        self.assertIn("complex action", result.routing_reason)

    def test_route_falls_through_when_backend_errors(self) -> None:
        broken_llama = ErrorClient("llama")
        ollama = CapturingClient("ollama")

        router = AdaptiveRouter(
            llamacpp_client=broken_llama,
            ollama_client=ollama,
            preferred_local_backend="llamacpp",
        )

        result = router.route(self.packet)

        self.assertEqual(result.target, ComputeTarget.LOCAL_OLLAMA)
        self.assertIn("local", result.routing_reason.lower())
        self.assertIsNotNone(ollama.last_prompt)

    # ------------------------------------------------------------------
    # route_with_configured_clients additive API surface
    # ------------------------------------------------------------------

    def test_route_with_configured_clients_accepts_upstream_context(self) -> None:
        llamacpp = CapturingClient("llamacpp")

        fake_clients = {
            "llamacpp": llamacpp,
            "ollama": None,
            "openai": None,
            "anthropic": None,
            "xai": None,
            "_preferred_local_backend": "llamacpp",
        }

        with patch(
            "glyphos_ai.ai_compute.router.create_configured_clients",
            return_value=fake_clients,
        ):
            result = route_with_configured_clients(
                self.packet,
                upstream_context=self.ctx_packet,
            )

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIsNotNone(llamacpp.last_prompt)
        self.assertIn("[CONTEXT_ANCHOR]", llamacpp.last_prompt or "")
        self.assertIn("LANE_STATE(AURORA): healthy", llamacpp.last_prompt or "")

    def test_route_with_configured_clients_existing_call_still_works(self) -> None:
        llamacpp = CapturingClient("llamacpp")

        fake_clients = {
            "llamacpp": llamacpp,
            "ollama": None,
            "openai": None,
            "anthropic": None,
            "xai": None,
            "_preferred_local_backend": "llamacpp",
        }

        with patch(
            "glyphos_ai.ai_compute.router.create_configured_clients",
            return_value=fake_clients,
        ):
            result = route_with_configured_clients(self.packet)

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertNotIn("[CONTEXT_ANCHOR]", llamacpp.last_prompt or "")

    # ------------------------------------------------------------------
    # Enforcement-oriented no hidden I/O test
    # ------------------------------------------------------------------

    def test_route_with_context_is_side_effect_free_for_file_io(self) -> None:
        """
        Phase 6 requires explicit context acceptance without hidden retrieval or file lookups.
        If route/glyph_to_prompt starts reading local files here, this test fails.
        """
        llamacpp = CapturingClient("llamacpp")
        router = AdaptiveRouter(llamacpp_client=llamacpp)

        original_open = builtins.open

        def guarded_open(*args, **kwargs):
            raise AssertionError("route path attempted file I/O")

        with patch("builtins.open", side_effect=guarded_open):
            result = router.route(self.packet, upstream_context=self.ctx_packet)

        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIn("[CONTEXT_ANCHOR]", llamacpp.last_prompt or "")

        # sanity: builtins.open restored by patch context
        self.assertIsNot(builtins.open, guarded_open)
        self.assertIsNotNone(original_open)

    # ------------------------------------------------------------------
    # JSON payload consistency
    # ------------------------------------------------------------------

    def test_prompt_and_structured_json_remain_consistent(self) -> None:
        prompt = glyph_to_prompt(self.packet, upstream_context=self.ctx_packet)
        data = glyph_to_structured_json(self.packet, upstream_context=self.ctx_packet)

        self.assertIn("MODEL", prompt)
        self.assertEqual(data["intent"]["target"], "MODEL")
        self.assertEqual(data["context"]["coherence"], 0.82)
        self.assertEqual(
            data["routing"]["preferred_backend"],
            "llamacpp",
        )


if __name__ == "__main__":
    unittest.main()
