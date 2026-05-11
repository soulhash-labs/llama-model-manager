#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
CLAUDE_GATEWAY_PATH = SCRIPTS_DIR / "claude_gateway.py"


def load_claude_gateway_module() -> object:
    spec = importlib.util.spec_from_file_location("llama_model_manager_claude_gateway", CLAUDE_GATEWAY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


class FakeUpstream:
    def __init__(self, text: str) -> None:
        self.text = text
        self.last_payload: dict | None = None

    def resolve_model_name(self) -> str:
        return "local-llama"

    def tokenize(self, text: str) -> int:
        return len(text.split())

    def chat(self, payload: dict) -> dict:
        self.last_payload = payload
        return {
            "choices": [{"message": {"content": self.text}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


class ClaudeGatewayToolTests(unittest.TestCase):
    def test_messages_payload_preserves_anthropic_tool_contract(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream("ok")
        gateway.upstream = fake

        gateway.message(
            {
                "model": "qwen",
                "system": "You are local.",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [
                    {
                        "name": "Bash",
                        "description": "Run shell commands",
                        "input_schema": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                            "required": ["command"],
                        },
                    }
                ],
                "tool_choice": {"type": "auto"},
            }
        )

        assert fake.last_payload is not None
        system = fake.last_payload["messages"][0]["content"]
        self.assertIn("[TOOL_CONTRACT]", system)
        self.assertIn("Bash", system)
        self.assertIn("Never print shell commands as plain text", system)
        self.assertIn("Never print tool_use: blocks", system)

    def test_messages_payload_preserves_tool_results_for_followup_turns(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream("summary")
        gateway.upstream = fake

        gateway.message(
            {
                "model": "qwen",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "Bash",
                                "input": {"command": "pwd"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_1",
                                "content": "/tmp/project",
                            }
                        ],
                    },
                ],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        assert fake.last_payload is not None
        rendered = "\n".join(item["content"] for item in fake.last_payload["messages"])
        self.assertIn("tool_use:", rendered)
        self.assertIn("tool_result toolu_1: /tmp/project", rendered)

    def test_message_repairs_textual_bash_commands_to_tool_use(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            'I will inspect the repo.\n\nfind . -type f -name "*.py" | head -20\n\nls -la\n'
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [
                    {
                        "name": "Bash",
                        "description": "Run shell commands",
                        "input_schema": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                            "required": ["command"],
                        },
                    }
                ],
                "tool_choice": {"type": "auto"},
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["type"], "tool_use")
        self.assertEqual(response["content"][0]["name"], "Bash")
        self.assertEqual(
            response["content"][0]["input"],
            {"command": 'find . -type f -name "*.py" | head -20\nls -la'},
        )
        self.assertEqual(response["lmm"]["tool_invocation_mode"], "textual_pseudo_call")
        self.assertTrue(response["lmm"]["repair_attempted"])
        self.assertTrue(response["lmm"]["repair_succeeded"])

    def test_message_repairs_json_bash_pseudo_call_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            json.dumps(
                {
                    "toolName": "Bash",
                    "command": 'find . -name "*harness*" -o -name "*test*" 2>/dev/null | head -50',
                }
            )
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(
            response["content"][0]["input"],
            {"command": 'find . -name "*harness*" -o -name "*test*" 2>/dev/null | head -50'},
        )

    def test_message_repairs_xml_bash_pseudo_call_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            '<Bash command="grep -r "harness" --include="*.py" --include="*.md" . -l | head -20" '
            'timeout="10000" description="Find files mentioning harness" />'
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(
            response["content"][0]["input"],
            {"command": 'grep -r "harness" --include="*.py" --include="*.md" . -l | head -20'},
        )

    def test_message_repairs_embedded_json_tool_call_block_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            '<think>\n</think>\n<tool_call>\n'
            '{"type": "tool", "arguments": {"command": "git diff --name-only"}}\n'
            "</think>"
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["input"], {"command": "git diff --name-only"})

    def test_message_repairs_tool_use_json_with_input_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream('{"type":"tool-use","tool":"Bash","input":{"command":"pwd"}}')
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["input"], {"command": "pwd"})

    def test_message_repairs_prefixed_anthropic_tool_use_text(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            'tool_use: {"type":"tool_use","id":"toolu_read_1","name":"Read",'
            '"input":{"file_path":"/home/angelo/repos/llama-model-manager-v2.1.0/scripts/claude_gateway.py"}}'
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "read the gateway"}],
                "tools": [{"name": "Read", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["type"], "tool_use")
        self.assertEqual(response["content"][0]["id"], "toolu_read_1")
        self.assertEqual(response["content"][0]["name"], "Read")
        self.assertEqual(
            response["content"][0]["input"],
            {"file_path": "/home/angelo/repos/llama-model-manager-v2.1.0/scripts/claude_gateway.py"},
        )
        self.assertEqual(response["lmm"]["tool_invocation_mode"], "textual_pseudo_call")
        self.assertTrue(response["lmm"]["repair_attempted"])
        self.assertTrue(response["lmm"]["repair_succeeded"])

    def test_message_repairs_raw_anthropic_tool_use_json_text(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            '{"type":"tool_use","id":"toolu_bash_1","name":"Bash","input":{"command":"git diff --stat"}}'
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect changes"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["id"], "toolu_bash_1")
        self.assertEqual(response["content"][0]["name"], "Bash")
        self.assertEqual(response["content"][0]["input"], {"command": "git diff --stat"})
        self.assertEqual(response["lmm"]["tool_invocation_mode"], "textual_pseudo_call")

    def test_message_repairs_tool_name_json_with_tool_input_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            '{"type":"tool-call","tool_name":"Bash","tool_input":{"command":"pwd","description":"Show cwd"}}'
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["input"], {"command": "pwd"})

    def test_message_repairs_tool_code_block_to_command_only(self) -> None:
        module = load_claude_gateway_module()
        gateway = module.ClaudeGateway("http://127.0.0.1:8081/v1")
        fake = FakeUpstream(
            '<tool_code interpreter="bash">\n'
            'lang="python"\n'
            'name="run_git_diff"\n'
            'code="git diff --name-only"\n'
            "</tool_code>"
        )
        gateway.upstream = fake

        response = gateway.message(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": "inspect files"}],
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
            }
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["input"], {"command": "git diff --name-only"})


if __name__ == "__main__":
    unittest.main()
