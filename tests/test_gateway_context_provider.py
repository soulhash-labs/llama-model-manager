#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gateway import context_provider  # noqa: E402


class GatewayContextProviderTests(unittest.TestCase):
    def test_payload_context_becomes_upstream_context(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "answer"}],
            "lmm_context": {"items": [{"path": "a.md", "content": "payload context"}]},
        }

        with mock.patch.dict(os.environ, {"LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1"}, clear=False):
            result, context_payload, upstream_context = context_provider.prepare_gateway_context(
                payload,
                "user: answer",
                model="ctx-model",
                stream=False,
            )

        self.assertEqual(result["status"], "retrieved_from_payload")
        self.assertIsNotNone(context_payload)
        self.assertIsInstance(upstream_context, dict)
        assert upstream_context is not None
        self.assertIn("payload context", upstream_context["content"])
        self.assertEqual(upstream_context["source"], "payload")

    def test_mcp_retrieved_context_becomes_upstream_context_with_degraded_metadata(self) -> None:
        payload = {"messages": [{"role": "user", "content": "find context"}]}
        stdout = json.dumps(
            {
                "retrieved_context": "mcp context",
                "meta": {
                    "strategy": "scan-fallback",
                    "degraded": True,
                    "suggestions": ["install sqlite fts"],
                },
            }
        )

        def command_runner(command: list[str], *, input_text: str, timeout_seconds: float, cwd: str):
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with mock.patch.dict(
            os.environ,
            {
                "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                "LMM_CONTEXT_MCP_COMMAND": "ctx-search",
            },
            clear=False,
        ):
            with mock.patch.object(context_provider, "_maybe_run_indexer", return_value={}):
                result, context_payload, upstream_context = context_provider.prepare_gateway_context(
                    payload,
                    "user: find context",
                    model="ctx-model",
                    stream=False,
                    command_runner=command_runner,
                )

        self.assertEqual(result["status"], "retrieved")
        self.assertEqual(result["search_strategy"], "scan-fallback")
        self.assertTrue(result["search_degraded"])
        self.assertIsNotNone(context_payload)
        assert upstream_context is not None
        self.assertEqual(upstream_context["content"], "mcp context")
        self.assertIn("strategy:scan-fallback", upstream_context["provenance"])
        self.assertTrue(upstream_context["metadata"]["search_degraded"])

    def test_empty_retrieval_returns_no_upstream_context(self) -> None:
        payload = {"messages": [{"role": "user", "content": "find context"}]}

        def command_runner(command: list[str], *, input_text: str, timeout_seconds: float, cwd: str):
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.dict(
            os.environ,
            {
                "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                "LMM_CONTEXT_MCP_COMMAND": "ctx-search",
            },
            clear=False,
        ):
            with mock.patch.object(context_provider, "_maybe_run_indexer", return_value={}):
                result, context_payload, upstream_context = context_provider.prepare_gateway_context(
                    payload,
                    "user: find context",
                    model="ctx-model",
                    stream=False,
                    command_runner=command_runner,
                )

        self.assertEqual(result["status"], "empty")
        self.assertFalse(result["used"])
        self.assertIsNone(context_payload)
        self.assertIsNone(upstream_context)

    def test_context_payload_reflects_encoding_state(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "answer"}],
            "lmm_context": {
                "items": [
                    {"path": "a.py", "content": "alpha beta gamma"},
                    {"path": "b.py", "content": "alpha beta gamma"},
                    {"path": "c.py", "content": "alpha beta gamma"},
                ]
            },
        }

        with mock.patch.dict(os.environ, {"LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1"}, clear=False):
            _, context_payload, _ = context_provider.prepare_gateway_context(
                payload,
                "user: answer",
                model="ctx-model",
                stream=False,
            )

        self.assertIsNotNone(context_payload)
        self.assertIn(getattr(context_payload, "encoding_status", ""), {"encoded", "skipped"})
        self.assertGreaterEqual(getattr(context_payload, "raw_context_chars", 0), 1)

    def test_prepare_gateway_context_does_not_mutate_prompt(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "answer"}],
            "lmm_context": "supporting context",
        }
        prompt = "user: answer"

        with mock.patch.dict(os.environ, {"LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1"}, clear=False):
            _, _, upstream_context = context_provider.prepare_gateway_context(
                payload,
                prompt,
                model="ctx-model",
                stream=False,
            )

        self.assertEqual(prompt, "user: answer")
        assert upstream_context is not None
        self.assertEqual(upstream_context["content"], "supporting context")


if __name__ == "__main__":
    unittest.main()
