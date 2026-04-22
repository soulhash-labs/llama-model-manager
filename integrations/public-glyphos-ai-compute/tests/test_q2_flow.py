import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glyphos_ai import (
    AdaptiveRouter,
    ComputeTarget,
    build_router_from_env,
    create_packet,
    decode_packet,
    glyph_to_prompt,
    route_with_configured_clients,
)
from glyphos_ai.glyph.encoder import encode_intent
from glyphos_ai.glyph.types import Intent, GlyphPacket


class DummyClient:
    def __init__(self, value: str):
        self.value = value

    def generate(self, prompt: str):
        return f"{self.value}:{prompt[:16]}"


class GlyphosPublicFlowTests(unittest.TestCase):
    def test_encode_intent_accepts_intent_object(self):
        self.assertEqual(encode_intent(Intent('QUERY', 'MODEL', 7)), '?H • T07|MDL>')

    def test_encode_intent_accepts_simple_arguments(self):
        self.assertEqual(encode_intent('QUERY', 'MODEL', time_slot=7), '?H • T07|MDL>')

    def test_create_decode_packet_round_trip(self):
        packet = create_packet('QUERY', 'MODEL', psi=0.75, time_slot=7)
        decoded = decode_packet(packet)
        self.assertIsInstance(packet, str)
        self.assertEqual(decoded.action, 'QUERY')
        self.assertEqual(decoded.destination, 'MODEL')
        self.assertEqual(decoded.time_slot, 'T07')
        self.assertAlmostEqual(decoded.psi_coherence, 0.7, places=1)

    def test_polaris_is_first_class_destination(self):
        packet = create_packet('QUERY', 'POLARIS', psi=0.75, time_slot=7)
        decoded = decode_packet(packet)
        self.assertEqual(decoded.destination, 'POLARIS')

    def test_glyph_to_prompt_works_with_snake_case_packet(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.8, action='QUERY', time_slot='T07', destination='MODEL')
        prompt = glyph_to_prompt(packet)
        self.assertIn('User queries MODEL', prompt)
        self.assertIn('high - provide nuanced response', prompt)

    def test_router_fallback_without_backends(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.8, action='QUERY', time_slot='T07', destination='MODEL')
        result = AdaptiveRouter().route(packet)
        self.assertEqual(result.target, ComputeTarget.FALLBACK)
        self.assertEqual(result.routing_reason, 'no backends configured')

    def test_router_can_use_xai_backend(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.2, action='QUERY', time_slot='T07', destination='MODEL')
        result = AdaptiveRouter(xai_client=DummyClient('xai-ok')).route(packet, prompt='test prompt')
        self.assertEqual(result.target, ComputeTarget.EXTERNAL_XAI)
        self.assertIn('xai-ok', result.response)

    def test_public_package_excludes_q45_exports(self):
        import glyphos_ai
        self.assertFalse(hasattr(glyphos_ai, 'Q45_AVAILABLE'))
        self.assertFalse(hasattr(glyphos_ai, 'create_q45_ai_compute_engine'))

    def test_route_with_configured_clients_prefers_llamacpp_lane(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.8, action='QUERY', time_slot='T07', destination='TERRAN')
        terran = DummyClient('llamacpp-terran-ok')
        with patch('glyphos_ai.ai_compute.router.create_configured_clients', return_value={'llamacpp-terran': terran, '_preferred_local_backend': 'llamacpp'}):
            result = route_with_configured_clients(packet)
        self.assertEqual(result.target, ComputeTarget.LOCAL_LLAMACPP)
        self.assertIn('llamacpp-terran-ok', result.response)

    def test_route_with_configured_clients_fallbacks_to_ollama_lane(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.8, action='QUERY', time_slot='T07', destination='POLARIS')
        polaris = DummyClient('ollama-polaris-ok')
        with patch('glyphos_ai.ai_compute.router.create_configured_clients', return_value={'ollama-polaris': polaris, '_preferred_local_backend': 'ollama'}):
            result = route_with_configured_clients(packet)
        self.assertEqual(result.target, ComputeTarget.LOCAL_OLLAMA)
        self.assertIn('ollama-polaris-ok', result.response)

    def test_build_router_from_env(self):
        with patch('glyphos_ai.ai_compute.router.create_configured_clients', return_value={'_preferred_local_backend': 'llamacpp'}):
            router = build_router_from_env()
        self.assertIsInstance(router, AdaptiveRouter)

    def test_route_with_configured_clients_fallbacks_cleanly(self):
        packet = GlyphPacket(instance_id='abc', psi_coherence=0.8, action='QUERY', time_slot='T07', destination='MODEL')
        with patch('glyphos_ai.ai_compute.router.create_configured_clients', return_value={'_preferred_local_backend': 'llamacpp'}):
            result = route_with_configured_clients(packet)
        self.assertEqual(result.target, ComputeTarget.FALLBACK)
        self.assertEqual(result.routing_reason, 'no backends configured')


if __name__ == '__main__':
    unittest.main()
