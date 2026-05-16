"""Live cloud roundtrip test — GIS1 injection → OpenAI → verify response."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PKG = REPO_ROOT / "integrations" / "public-glyphos-ai-compute"
if str(PUBLIC_PKG) not in sys.path:
    sys.path.insert(0, str(PUBLIC_PKG))

from glyphos_ai.ai_compute.router import AdaptiveRouter, ComputeTarget  # noqa: E402


class LiveCloudRoundtripTests(unittest.TestCase):
    """Test full GIS1 injection → cloud model → response roundtrip."""

    @classmethod
    def setUpClass(cls):
        key_file = REPO_ROOT / "config" / "openai_api_key.txt"
        if not key_file.exists():
            raise unittest.SkipTest("No OpenAI API key found — skipping live test")
        cls.api_key = key_file.read_text().strip()
        if not cls.api_key:
            raise unittest.SkipTest("Empty API key — skipping live test")

    def setUp(self):
        from glyphos_ai.ai_compute.api_client import OpenAIClient

        self.client = OpenAIClient(api_key=self.api_key, model="gpt-4o-mini", timeout=30)
        self.router = AdaptiveRouter(
            llamacpp_client=MagicMock(),
            openai_client=self.client,
            anthropic_client=None,
            xai_client=None,
        )

    def test_gis1_injection_produces_valid_openai_response(self):
        """Send GIS1-injected prompt to OpenAI, verify valid response."""
        injected = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            "What is 2+2? Answer with just the number.",
            psi_coherence=0.85,
            glyph_action="QUERY",
            glyph_destination="MODEL",
            instance_id="live-test-001",
        )
        self.assertIn("GIS1|a=QUERY", injected)
        self.assertIn("p=0.85", injected)
        self.assertIn("What is 2+2?", injected)

        response = self.client.generate(injected, max_tokens=20, temperature=0.0)
        self.assertIsNotNone(response)
        text = response if isinstance(response, str) else response.get("response", "")
        self.assertIn("4", text)

    def test_gis1_with_learning_context_produces_valid_response(self):
        """Send GIS1 + learning context injection, verify valid response."""
        state_file = Path.home() / ".config" / "llama-model-manager" / "agent_state.json"
        if not state_file.exists():
            self.skipTest("No agent_state.json — skipping learning context test")

        state = json.loads(state_file.read_text())
        if not state.get("per_domain_strategies"):
            self.skipTest("No strategies in state — skipping learning context test")

        injected = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            "What is the capital of France? Answer with just the city name.",
            psi_coherence=0.75,
            glyph_action="ANALYZE",
            glyph_destination="KNOWLEDGE",
            instance_id="live-test-002",
        )
        self.assertIn("GIS1|", injected)
        self.assertIn("[LEARNING_CONTEXT]", injected)
        self.assertIn("[/LEARNING_CONTEXT]", injected)
        self.assertIn("session_count:", injected)
        self.assertIn("What is the capital of France?", injected)

        response = self.client.generate(injected, max_tokens=20, temperature=0.0)
        self.assertIsNotNone(response)
        text = response if isinstance(response, str) else response.get("response", "")
        self.assertIn("Paris", text)

    def test_gis1_action_field_survives_roundtrip(self):
        """Verify the model receives and can act on GIS1 action metadata."""
        injected = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            "Read the action code below and confirm you see it. Respond YES if you see a=SYNTHESIZE.",
            psi_coherence=0.9,
            glyph_action="SYNTHESIZE",
            glyph_destination="CODEBASE",
            instance_id="live-test-003",
        )
        self.assertIn("a=SYNTHESIZE", injected)
        self.assertIn("Read the action code below", injected)

        response = self.client.generate(injected, max_tokens=30, temperature=0.0)
        self.assertIsNotNone(response)
        text = response if isinstance(response, str) else response.get("response", "")
        self.assertTrue(
            "YES" in text.upper() or "SYNTHESIZE" in text.upper(),
            f"Model did not acknowledge action. Response: {text[:100]}",
        )

    def test_gis1_no_hardware_leakage_in_live_call(self):
        """Verify live cloud call does not leak hardware info."""
        injected = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            "Test prompt",
            psi_coherence=0.5,
            glyph_action="QUERY",
            glyph_destination="MODEL",
        )
        forbidden = ["vram", "ram", "gpu", "GB", "gb", "/home/", ".gguf", "tier"]
        for term in forbidden:
            self.assertNotIn(term, injected, f"Hardware leakage: '{term}'")

    def test_cloud_routing_result_via_router(self):
        """Test full router.route() with cloud target and verify RoutingResult."""
        from glyphos_ai.glyph.types import GlyphPacket

        packet = GlyphPacket(
            instance_id="live-router-test",
            psi_coherence=0.8,
            action="QUERY",
            header="H",
            time_slot="T00",
            destination="MODEL",
            encoding_status="none",
        )

        # Force cloud routing by setting high psi and complex action
        result = self.router.route(
            packet,
            prompt="What is 1+1? Answer with just the number.",
            max_tokens=10,
            temperature=0.0,
        )
        self.assertIsNotNone(result)
        text = result.response if isinstance(result.response, str) else str(result.response)
        self.assertIn("2", text)


if __name__ == "__main__":
    unittest.main()
