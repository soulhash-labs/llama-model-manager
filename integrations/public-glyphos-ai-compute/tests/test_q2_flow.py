import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glyphos_ai import (
    AdaptiveRouter,
    ComputeTarget,
    PulseService,
    build_router_from_env,
    create_configured_clients,
    create_packet,
    decode_packet,
    glyph_to_prompt,
    route_with_configured_clients,
)
from glyphos_ai.ai_compute.router import reset_routing_telemetry, routing_telemetry_snapshot
from glyphos_ai.glyph.encoder import encode_intent
from glyphos_ai.glyph.types import GlyphPacket, Intent


class DummyClient:
    def __init__(self, value: str):
        self.value = value

    def generate(self, prompt: str):
        return f"{self.value}:{prompt[:16]}"


class GlyphosPublicFlowTests(unittest.TestCase):
    def test_encode_intent_accepts_intent_object(self):
        self.assertEqual(encode_intent(Intent("QUERY", "MODEL", 7)), "?H • T07|MDL>")

    def test_encode_intent_accepts_simple_arguments(self):
        self.assertEqual(encode_intent("QUERY", "MODEL", time_slot=7), "?H • T07|MDL>")

    def test_create_decode_packet_round_trip(self):
        packet = create_packet("QUERY", "MODEL", psi=0.75, time_slot=7)
        decoded = decode_packet(packet)
        self.assertIsInstance(packet, str)
        self.assertEqual(decoded.action, "QUERY")
        self.assertEqual(decoded.destination, "MODEL")
        self.assertEqual(decoded.time_slot, "T07")
        self.assertAlmostEqual(decoded.psi_coherence, 0.7, places=1)

    def test_polaris_is_first_class_destination(self):
        packet = create_packet("QUERY", "POLARIS", psi=0.75, time_slot=7)
        decoded = decode_packet(packet)
        self.assertEqual(decoded.destination, "POLARIS")

    def test_glyph_to_prompt_works_with_snake_case_packet(self):
        packet = GlyphPacket(instance_id="abc", psi_coherence=0.8, action="QUERY", time_slot="T07", destination="MODEL")
        prompt = glyph_to_prompt(packet)
        self.assertIn("User queries MODEL", prompt)
        self.assertIn("high - provide nuanced response", prompt)

    def test_router_fallback_without_backends(self):
        packet = GlyphPacket(instance_id="abc", psi_coherence=0.8, action="QUERY", time_slot="T07", destination="MODEL")
        result = AdaptiveRouter().route(packet)
        self.assertEqual(result.target, ComputeTarget.FALLBACK)
        self.assertEqual(result.routing_reason, "no cloud backends available")

    def test_router_can_use_xai_backend(self):
        packet = GlyphPacket(instance_id="abc", psi_coherence=0.2, action="QUERY", time_slot="T07", destination="MODEL")
        result = AdaptiveRouter(xai_client=DummyClient("xai-ok")).route(packet, prompt="test prompt")
        self.assertEqual(result.target, ComputeTarget.EXTERNAL_XAI)
        self.assertIn("xai-ok", result.response)

    def test_public_package_excludes_ollama_from_supported_exports(self):
        import glyphos_ai

        self.assertFalse(hasattr(glyphos_ai, "Q45_AVAILABLE"))
        self.assertFalse(hasattr(glyphos_ai, "create_q45_ai_compute_engine"))
        self.assertNotIn("OllamaClient", glyphos_ai.__all__)

    def test_top_level_ollama_import_is_guided_failure(self):
        import glyphos_ai

        removed_client = glyphos_ai.OllamaClient
        with self.assertRaisesRegex(RuntimeError, "llama.cpp runtime"):
            removed_client()

    def test_ollama_module_import_is_guided_failure(self):
        from glyphos_ai.ai_compute.ollama_client import create_ollama_client

        with self.assertRaisesRegex(RuntimeError, "llama.cpp runtime"):
            create_ollama_client()

    def test_route_with_configured_clients_prefers_llamacpp_lane(self):
        packet = GlyphPacket(
            instance_id="abc", psi_coherence=0.8, action="QUERY", time_slot="T07", destination="TERRAN"
        )
        terran = DummyClient("llamacpp-terran-ok")
        with patch("glyphos_ai.ai_compute.router.create_configured_clients", return_value={"llamacpp-terran": terran}):
            result = route_with_configured_clients(packet)
        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIn("llamacpp-terran-ok", result.response)

    def test_create_configured_clients_warns_on_retired_config_keys(self):
        disabled_client = Mock()
        disabled_client.is_available.return_value = False
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with (
                patch(
                    "glyphos_ai.ai_compute.api_client._load_glyphos_config",
                    return_value={
                        "ai_compute": {
                            "local": {"preferred_local_backend": "ollama"},
                            "routing": {"preferred_local_backend": "ollama"},
                            "ollama": {
                                "enabled": "true",
                                "url": "http://localhost:11434",
                            },
                        }
                    },
                ),
                patch("glyphos_ai.ai_compute.api_client.LlamaCppClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.OpenAIClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.AnthropicClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.XAIClient", return_value=disabled_client),
            ):
                clients = create_configured_clients()
        self.assertNotIn("_preferred_local_backend", clients)
        messages = "\n".join(str(item.message) for item in caught)
        self.assertIn("preferred_local_backend", messages)
        self.assertIn("ai_compute.ollama.url", messages)
        self.assertIn("llama.cpp-only", messages)

    def test_create_configured_clients_warns_on_retired_env_vars(self):
        disabled_client = Mock()
        disabled_client.is_available.return_value = False
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with (
                patch.dict(
                    "os.environ",
                    {
                        "GLYPHOS_OLLAMA_URL": "http://localhost:11434",
                        "GLYPHOS_PREFERRED_LOCAL_BACKEND": "ollama",
                    },
                    clear=True,
                ),
                patch("glyphos_ai.ai_compute.api_client._load_glyphos_config", return_value={}),
                patch("glyphos_ai.ai_compute.api_client.LlamaCppClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.OpenAIClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.AnthropicClient", return_value=disabled_client),
                patch("glyphos_ai.ai_compute.api_client.XAIClient", return_value=disabled_client),
            ):
                create_configured_clients()
        messages = "\n".join(str(item.message) for item in caught)
        self.assertIn("GLYPHOS_OLLAMA_URL", messages)
        self.assertIn("GLYPHOS_PREFERRED_LOCAL_BACKEND", messages)

    def test_build_router_from_env_is_llamacpp_only(self):
        local = DummyClient("llamacpp-local-ok")
        with patch("glyphos_ai.ai_compute.router.create_configured_clients", return_value={"llamacpp": local}):
            router = build_router_from_env()
        self.assertIsInstance(router, AdaptiveRouter)
        self.assertTrue(router.get_status()["llamacpp"])
        self.assertNotIn("ollama", router.get_status())

    def test_route_with_configured_clients_fallbacks_cleanly(self):
        packet = GlyphPacket(instance_id="abc", psi_coherence=0.8, action="QUERY", time_slot="T07", destination="MODEL")
        with patch("glyphos_ai.ai_compute.router.create_configured_clients", return_value={}):
            result = route_with_configured_clients(packet)
        self.assertEqual(result.target, ComputeTarget.FALLBACK)
        self.assertEqual(result.routing_reason, "no cloud backends available")

    def test_pulse_service_is_unsigned_without_private_key(self):
        with patch.dict("os.environ", {}, clear=True):
            service = PulseService(instance_id="test-instance", private_key=None)
        pulse = service.generate_pulse(psi_coherence=0.8)
        headers = service.get_pulse_header()
        self.assertEqual(service.private_key, "")
        self.assertTrue(pulse.timestamp.endswith("Z"))
        self.assertIsNone(pulse.metadata["pulse_signature"])
        self.assertEqual(pulse.metadata["pulse_signing"], "disabled")
        self.assertNotIn("X-Pulse-Sig", headers)
        self.assertFalse(service.verify_pulse_signature(1, pulse.frequency_hz, pulse.psi_coherence, "anything"))

    def test_pulse_service_reads_private_key_from_env(self):
        with patch.dict("os.environ", {"GLYPHOS_PULSE_PRIVATE_KEY": "secret-key"}, clear=True):
            service = PulseService(instance_id="test-instance", private_key=None)
        headers = service.get_pulse_header()
        self.assertEqual(service.private_key, "secret-key")
        self.assertIn("X-Pulse-Sig", headers)

    def test_routing_telemetry_snapshot_tracks_success_routes(self):
        reset_routing_telemetry()
        packet = GlyphPacket(instance_id="abc", psi_coherence=0.9, action="QUERY", time_slot="T07", destination="MODEL")
        router = AdaptiveRouter(llamacpp_client=DummyClient("llamacpp-ok"))
        router.route(packet, prompt="test prompt")
        router.route(packet, prompt="test prompt")

        snap = routing_telemetry_snapshot(limit=10)
        self.assertGreaterEqual(snap.get("total_attempts", 0), 2)
        self.assertIn("llamacpp", snap.get("attempts_by_target", {}))

    def test_routing_telemetry_error_reason_is_suffixed_once(self):
        class ExplodingClient(DummyClient):
            def generate(self, prompt: str):
                raise RuntimeError("boom")

        reset_routing_telemetry()
        packet = GlyphPacket(
            instance_id="abc", psi_coherence=0.95, action="QUERY", time_slot="T07", destination="MODEL"
        )
        router = AdaptiveRouter(llamacpp_client=ExplodingClient("llamacpp"))
        router.route(packet, prompt="test prompt")

        snap = routing_telemetry_snapshot(limit=10)
        reasons = snap.get("fallback_reason_counts", {})
        self.assertTrue(any(str(key).endswith(".error") for key in reasons.keys()))
        self.assertFalse(any(str(key).endswith(".error.error") for key in reasons.keys()))


if __name__ == "__main__":
    unittest.main()
