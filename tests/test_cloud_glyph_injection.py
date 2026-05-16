"""Cloud glyph injection tests — verifies GIS1 + learning context injection without real API keys."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the bundled public package is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PKG = REPO_ROOT / "integrations" / "public-glyphos-ai-compute"
if str(PUBLIC_PKG) not in sys.path:
    sys.path.insert(0, str(PUBLIC_PKG))

from glyphos_ai.ai_compute.router import AdaptiveRouter, ComputeTarget  # noqa: E402


class CloudGlyphInjectionTests(unittest.TestCase):
    """Test _inject_cloud_glyph_context and _build_anonymized_learning_context."""

    def setUp(self):
        self.router = AdaptiveRouter(
            llamacpp_client=MagicMock(),
            openai_client=None,
            anthropic_client=None,
            xai_client=None,
        )

    def test_inject_cloud_glyph_context_local_target_returns_prompt_unchanged(self):
        """Local targets should not receive any injection."""
        prompt = "Hello world"
        result = self.router._inject_cloud_glyph_context(ComputeTarget.LOCAL_LLAMACPP, prompt)
        self.assertEqual(result, prompt)

    def test_inject_cloud_glyph_context_openai_produces_gis1(self):
        """EXTERNAL_OPENAI target should receive GIS1 prefix with instruction header."""
        prompt = "Translate this"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            prompt,
            psi_coherence=0.75,
            glyph_action="ANALYZE",
            glyph_destination="CODEBASE",
            instance_id="test123",
        )
        self.assertIn("GIS1|", result)
        self.assertIn("a=ANALYZE", result)
        self.assertIn("d=CODEBASE", result)
        self.assertIn("p=0.75", result)
        self.assertIn("i=test123", result)
        self.assertIn("cloud co-processor", result)
        self.assertIn("Translate this", result)

    def test_inject_cloud_glyph_context_anthropic_produces_gis1(self):
        """EXTERNAL_ANTHROPIC target should receive GIS1 with instruction header."""
        prompt = "Summarize"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_ANTHROPIC,
            prompt,
            psi_coherence=0.5,
            glyph_action="QUERY",
            glyph_destination="MODEL",
        )
        self.assertIn("GIS1|", result)
        self.assertIn("a=QUERY", result)
        self.assertIn("d=MODEL", result)
        self.assertIn("Summarize", result)

    def test_inject_cloud_glyph_context_xai_produces_gis1(self):
        """EXTERNAL_XAI target should receive GIS1 with instruction header."""
        prompt = "Generate code"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_XAI,
            prompt,
            psi_coherence=0.9,
            glyph_action="SYNTHESIZE",
            glyph_destination="EXTERNAL",
        )
        self.assertIn("GIS1|", result)
        self.assertIn("a=SYNTHESIZE", result)
        self.assertIn("d=EXTERNAL", result)
        self.assertIn("p=0.90", result)
        self.assertIn("Generate code", result)

    def test_inject_cloud_glyph_context_defaults_when_kwargs_missing(self):
        """Missing kwargs should fall back to defaults."""
        prompt = "Test"
        result = self.router._inject_cloud_glyph_context(ComputeTarget.EXTERNAL_OPENAI, prompt)
        self.assertIn("GIS1|", result)
        self.assertIn("a=QUERY", result)
        self.assertIn("d=UNKNOWN", result)
        self.assertIn("p=0.50", result)

    def test_gis1_wire_format(self):
        """GIS1 wire format must be present in injected output."""
        prompt = "Test"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            prompt,
            psi_coherence=0.82,
            glyph_action="LEARN",
            glyph_destination="KNOWLEDGE",
            instance_id="abc456",
        )
        gis1_line = [line for line in result.split("\n") if "GIS1|" in line][0]
        parts = gis1_line.split("|")
        self.assertEqual(parts[0], "Intent glyph: GIS1")
        self.assertEqual(parts[1], "a=LEARN")
        self.assertEqual(parts[2], "d=KNOWLEDGE")
        self.assertRegex(parts[3], r"^t=T\d{2}$")
        self.assertEqual(parts[4], "p=0.82")
        self.assertEqual(parts[5], "i=abc456")

    def test_no_hardware_leakage_in_injection(self):
        """GIS1 injection must NOT contain VRAM, RAM, file paths, or hardware specs."""
        prompt = "Test"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            prompt,
            psi_coherence=0.5,
            glyph_action="QUERY",
            glyph_destination="MODEL",
        )
        forbidden = ["vram", "ram", "gpu", "GB", "gb", "/home/", "/tmp/", ".gguf", "tier"]
        for term in forbidden:
            self.assertNotIn(term, result, f"Hardware leakage detected: '{term}' found in injection output")


class AnonymizedLearningContextTests(unittest.TestCase):
    """Test _build_anonymized_learning_context with real persistence data."""

    def setUp(self):
        self.router = AdaptiveRouter(
            llamacpp_client=MagicMock(),
            openai_client=None,
            anthropic_client=None,
            xai_client=None,
        )
        self.state_dir = Path.home() / ".config" / "llama-model-manager"
        self.state_file = self.state_dir / "agent_state.json"
        self._backup = None
        if self.state_file.exists():
            self._backup = self.state_file.read_text(encoding="utf-8")

    def tearDown(self):
        if self._backup is not None:
            self.state_file.write_text(self._backup, encoding="utf-8")
        elif self.state_file.exists():
            self.state_file.unlink()

    def test_learning_context_empty_when_no_state_file(self):
        """No agent_state.json → empty learning context."""
        if self.state_file.exists():
            self.state_file.unlink()
        result = self.router._build_anonymized_learning_context("QUERY", "MODEL")
        self.assertEqual(result, "")

    def test_learning_context_empty_when_no_strategies(self):
        """State file exists but no strategies → empty learning context."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "per_domain_strategies": {},
                    "novelty_scores": {},
                    "session_count": 0,
                    "total_tasks": 0,
                }
            ),
            encoding="utf-8",
        )
        result = self.router._build_anonymized_learning_context("QUERY", "MODEL")
        self.assertEqual(result, "")

    def test_learning_context_with_strategies(self):
        """State file with strategies → proper [LEARNING_CONTEXT] block."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "per_domain_strategies": {
                        "routing:llamacpp": {
                            "success_rate": 0.95,
                            "avg_latency_ms": 150,
                            "samples": 5,
                        },
                        "tool_call:llamacpp": {
                            "success_rate": 0.80,
                            "avg_latency_ms": 200,
                            "samples": 3,
                        },
                    },
                    "novelty_scores": {},
                    "session_count": 12,
                    "total_tasks": 42,
                }
            ),
            encoding="utf-8",
        )
        result = self.router._build_anonymized_learning_context("QUERY", "MODEL")
        self.assertTrue(result.startswith("[LEARNING_CONTEXT]"))
        self.assertTrue(result.endswith("[/LEARNING_CONTEXT]"))
        self.assertIn("session_count:12", result)
        self.assertIn("total_tasks:42", result)
        self.assertIn("proven:", result)
        self.assertIn("success:", result)

    def test_learning_context_no_hardware_leakage(self):
        """Learning context must NOT contain VRAM, RAM, file paths, or hardware specs."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "per_domain_strategies": {
                        "routing:llamacpp": {
                            "success_rate": 0.95,
                            "avg_latency_ms": 150,
                            "samples": 5,
                        },
                    },
                    "novelty_scores": {},
                    "session_count": 5,
                    "total_tasks": 10,
                }
            ),
            encoding="utf-8",
        )
        result = self.router._build_anonymized_learning_context("QUERY", "MODEL")
        forbidden = ["vram", "ram", "gpu", "GB", "gb", "/home/", "/tmp/", ".gguf", "tier"]
        for term in forbidden:
            self.assertNotIn(term, result, f"Hardware leakage detected: '{term}' found in learning context")

    def test_learning_context_action_filtering(self):
        """Action-specific entries should be included when action matches domain key."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "per_domain_strategies": {
                        "tool_call:llamacpp": {
                            "success_rate": 0.85,
                            "avg_latency_ms": 180,
                            "samples": 2,
                        },
                    },
                    "novelty_scores": {},
                    "session_count": 3,
                    "total_tasks": 8,
                }
            ),
            encoding="utf-8",
        )
        result = self.router._build_anonymized_learning_context("tool_call", "MODEL")
        self.assertIn("action:tool_call→", result)


class CloudInjectionIntegrationTests(unittest.TestCase):
    """Full injection integration with real persistence data."""

    def setUp(self):
        self.router = AdaptiveRouter(
            llamacpp_client=MagicMock(),
            openai_client=None,
            anthropic_client=None,
            xai_client=None,
        )

    def test_full_injection_with_real_state(self):
        """Full GIS1 + LEARNING_CONTEXT injection using actual agent_state.json."""
        state_file = Path.home() / ".config" / "llama-model-manager" / "agent_state.json"
        if not state_file.exists():
            self.skipTest("No agent_state.json found — run `llama-model learn init` first")

        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            "Test prompt",
            psi_coherence=0.7,
            glyph_action="ANALYZE",
            glyph_destination="CODEBASE",
            instance_id="integration-test",
        )

        self.assertIn("GIS1|", result)
        self.assertIn("a=ANALYZE", result)
        self.assertIn("d=CODEBASE", result)
        self.assertIn("p=0.70", result)
        self.assertIn("i=integration-test", result)
        self.assertIn("Test prompt", result)

        state = json.loads(state_file.read_text())
        if state.get("per_domain_strategies"):
            self.assertIn("[LEARNING_CONTEXT]", result)
            self.assertIn("[/LEARNING_CONTEXT]", result)

    def test_injection_preserves_original_prompt(self):
        """Original prompt must be included in injected output."""
        original = "What is the meaning of life?"
        result = self.router._inject_cloud_glyph_context(
            ComputeTarget.EXTERNAL_OPENAI,
            original,
            psi_coherence=0.5,
        )
        self.assertIn("GIS1|", result)
        self.assertIn(original, result)


if __name__ == "__main__":
    unittest.main()
