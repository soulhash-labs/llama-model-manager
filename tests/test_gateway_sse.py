#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gateway import protocol_normalizers, sse  # noqa: E402


def _make_mock_handler(wfile: io.BytesIO | None = None) -> mock.Mock:
    handler = mock.Mock()
    handler.wfile = wfile or io.BytesIO()
    handler.requestline = "POST /v1/chat/completions HTTP/1.1"
    handler.command = "POST"
    handler.path = "/v1/chat/completions"
    handler.headers = {}
    return handler


class CloseAwareChunks:
    def __init__(self, items: list[str], *, fail_after: int | None = None) -> None:
        self.items = items
        self.fail_after = fail_after
        self.index = 0
        self.closed = False

    def __iter__(self) -> "CloseAwareChunks":
        return self

    def __next__(self) -> str:
        if self.closed:
            raise StopIteration
        if self.fail_after is not None and self.index >= self.fail_after:
            raise RuntimeError("upstream connection dropped")
        if self.index >= len(self.items):
            raise StopIteration
        item = self.items[self.index]
        self.index += 1
        return item

    def close(self) -> None:
        self.closed = True


class DisconnectingWriter(io.BytesIO):
    def __init__(self, *, fail_after_writes: int) -> None:
        super().__init__()
        self.fail_after_writes = fail_after_writes
        self.write_count = 0

    def write(self, data: bytes) -> int:
        self.write_count += 1
        if self.write_count > self.fail_after_writes:
            raise BrokenPipeError("client went away")
        return super().write(data)


class ProtocolNormalizerTests(unittest.TestCase):
    def test_none_content_normalizes_to_empty_text(self) -> None:
        self.assertEqual(protocol_normalizers.messages_to_prompt([{"role": "user", "content": None}]), "")
        self.assertEqual(protocol_normalizers.anthropic_messages_to_text([{"role": "user", "content": None}]), "")

    def test_none_items_in_content_lists_are_ignored(self) -> None:
        prompt = protocol_normalizers.messages_to_prompt(
            [{"role": "user", "content": [None, {"type": "text", "text": None}, {"type": "text", "text": "ok"}]}]
        )

        self.assertEqual(prompt, "user: ok")


def _read_sse_events(data: bytes) -> list[dict]:
    events: list[dict] = []
    for raw in data.split(b"\n\n"):
        if not raw.strip():
            continue
        event: dict[str, str | None] = {"event": None, "data": None}
        for line in raw.split(b"\n"):
            if line.startswith(b"event: "):
                event["event"] = line[7:].decode()
            elif line.startswith(b"data: "):
                event["data"] = line[6:].decode()
            elif line.startswith(b":"):
                pass
            else:
                text = line.decode()
                if text.startswith("data: "):
                    event["data"] = text[6:]
                elif text.startswith("event: "):
                    event["event"] = text[7:]
        if event["data"] is not None:
            events.append(event)
    return events


TOOL_DECLARATION_PAYLOAD = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "use a tool"}],
    "stream": True,
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ],
}

TASK_TOOL_DECLARATION_PAYLOAD = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "invoke task"}],
    "stream": True,
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "task",
                "description": "Delegate work to a subagent",
                "parameters": {"type": "object"},
            },
        }
    ],
}

BASH_TOOL_DECLARATION_PAYLOAD = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "use bash"}],
    "stream": True,
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "Bash",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ],
}

OPENCODE_TOOL_DECLARATION_PAYLOAD = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "continue after background task"}],
    "stream": True,
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "background_output",
                "description": "Read background task output",
                "parameters": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ast_grep_search",
                "description": "Search code structurally",
                "parameters": {"type": "object"},
            },
        },
    ],
}


class StreamCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started = time.time()

    def _run_stream(self, chunks: list[str], *, payload: dict | None = None) -> tuple[dict, dict | None]:
        wfile = io.BytesIO()
        handler = _make_mock_handler(wfile)
        text, ok, err, lat, tool_info = sse.stream_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=iter(chunks),
            headers={},
            payload=payload,
        )
        wfile.seek(0)
        events = _read_sse_events(wfile.read())
        return events, tool_info

    def test_upstream_exception_closes_iterator(self) -> None:
        chunks = CloseAwareChunks(["partial"], fail_after=1)
        handler = _make_mock_handler()
        text, ok, err, _lat, tool_info = sse.stream_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=chunks,
            headers={},
        )

        self.assertEqual(text, "partial")
        self.assertFalse(ok)
        self.assertIn("RuntimeError", err)
        self.assertIn("upstream connection dropped", err)
        self.assertTrue(chunks.closed)
        self.assertIsNone(tool_info)

    def test_client_disconnect_closes_iterator(self) -> None:
        chunks = CloseAwareChunks(["one", "two", "three"])
        handler = _make_mock_handler(DisconnectingWriter(fail_after_writes=3))
        text, ok, err, _lat, tool_info = sse.stream_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=chunks,
            headers={},
        )

        self.assertFalse(ok)
        self.assertIn("client disconnected", err)
        self.assertTrue(chunks.closed)
        self.assertIsNone(tool_info)

    def test_text_output_finish_reason_stop(self) -> None:
        events, tool_info = self._run_stream(["hello", " world"], payload=TOOL_DECLARATION_PAYLOAD)
        content = "".join(
            json.loads(e["data"])["choices"][0].get("delta", {}).get("content", "")
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        )
        self.assertEqual(content, "hello world")
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        last_choice = terminal[-1] if terminal else {}
        data = json.loads(last_choice.get("data", "{}")) if last_choice.get("data") else {}
        choices = data.get("choices", [])
        finish = choices[0].get("finish_reason") if choices else None
        self.assertEqual(finish, "stop")
        self.assertIsNone(tool_info)

    def test_tool_call_output_finish_reason_tool_calls(self) -> None:
        tool_output = json.dumps({"tool_call": {"function": {"name": "get_weather", "arguments": {"city": "NYC"}}}})
        events, tool_info = self._run_stream([tool_output], payload=TOOL_DECLARATION_PAYLOAD)
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        last_choice = terminal[-1] if terminal else {}
        data = json.loads(last_choice.get("data", "{}")) if last_choice.get("data") else {}
        choices = data.get("choices", [])
        finish = choices[0].get("finish_reason") if choices else None
        self.assertEqual(finish, "tool_calls")
        self.assertIsNotNone(tool_info)
        self.assertTrue(tool_info.get("detected"))
        self.assertEqual(tool_info.get("name"), "get_weather")
        self.assertEqual(tool_info.get("mode"), "structured")

    def test_textual_task_pseudo_call_finish_reason_tool_calls(self) -> None:
        tool_output = (
            'task(subagent_type="explore", run_in_background=true, load_skills=[], '
            'description="E2E task harness smoke test", prompt="Reply with exactly E2E_OK.")'
        )
        events, tool_info = self._run_stream([tool_output], payload=TASK_TOOL_DECLARATION_PAYLOAD)
        content = "".join(
            json.loads(e["data"])["choices"][0].get("delta", {}).get("content", "")
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        )
        self.assertNotIn("task(", content)
        tool_deltas = [
            json.loads(e["data"])["choices"][0].get("delta", {}).get("tool_calls", [])
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        ]
        tool_calls = [call for delta in tool_deltas for call in delta]
        self.assertEqual(tool_calls[0]["function"]["name"], "task")
        self.assertEqual(json.loads(tool_calls[0]["function"]["arguments"])["subagent_type"], "explore")
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        last_choice = terminal[-1] if terminal else {}
        data = json.loads(last_choice.get("data", "{}")) if last_choice.get("data") else {}
        choices = data.get("choices", [])
        finish = choices[0].get("finish_reason") if choices else None
        self.assertEqual(finish, "tool_calls")
        self.assertIsNotNone(tool_info)
        self.assertTrue(tool_info.get("detected"))
        self.assertEqual(tool_info.get("name"), "task")
        self.assertEqual(tool_info.get("mode"), "textual_pseudo_call")

    def test_textual_bash_pseudo_call_streams_tool_call_delta_not_text(self) -> None:
        tool_output = "```bash\nls *.py *.ts *.js *.tsx *.json 2>/dev/null | head -3\n```"
        events, tool_info = self._run_stream([tool_output], payload=BASH_TOOL_DECLARATION_PAYLOAD)
        content = "".join(
            json.loads(e["data"])["choices"][0].get("delta", {}).get("content", "")
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        )
        self.assertNotIn("ls *.py", content)
        tool_deltas = [
            json.loads(e["data"])["choices"][0].get("delta", {}).get("tool_calls", [])
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        ]
        tool_calls = [call for delta in tool_deltas for call in delta]
        self.assertEqual(tool_calls[0]["function"]["name"], "Bash")
        self.assertEqual(
            json.loads(tool_calls[0]["function"]["arguments"])["command"],
            "ls *.py *.ts *.js *.tsx *.json 2>/dev/null | head -3",
        )
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        data = json.loads(terminal[-1]["data"])
        self.assertEqual(data["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(tool_info.get("mode"), "textual_pseudo_call")

    def test_openai_function_json_text_streams_tool_call_delta_not_text(self) -> None:
        tool_output = (
            '<think>\n</think>\n'
            '{"type":"function","function":{"name":"background_output",'
            '"arguments":{"task_id":"bg_12f8dc06"}}}'
        )
        events, tool_info = self._run_stream([tool_output], payload=OPENCODE_TOOL_DECLARATION_PAYLOAD)
        content = "".join(
            json.loads(e["data"])["choices"][0].get("delta", {}).get("content", "")
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        )
        self.assertNotIn("background_output", content)
        tool_deltas = [
            json.loads(e["data"])["choices"][0].get("delta", {}).get("tool_calls", [])
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        ]
        tool_calls = [call for delta in tool_deltas for call in delta]
        self.assertEqual(tool_calls[0]["function"]["name"], "background_output")
        self.assertEqual(json.loads(tool_calls[0]["function"]["arguments"]), {"task_id": "bg_12f8dc06"})
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        data = json.loads(terminal[-1]["data"])
        self.assertEqual(data["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(tool_info.get("mode"), "textual_pseudo_call")

    def test_malformed_openai_function_json_text_keeps_spilled_arguments(self) -> None:
        tool_output = (
            '{"type":"function","function":{"name":"ast_grep_search","arguments":'
            '{"pattern":"name\\\\s*:\\\\s*lan-guard"} '
            '"lang":"json","globs":["**/package.json"]}}'
        )
        events, tool_info = self._run_stream([tool_output], payload=OPENCODE_TOOL_DECLARATION_PAYLOAD)
        tool_deltas = [
            json.loads(e["data"])["choices"][0].get("delta", {}).get("tool_calls", [])
            for e in events
            if e.get("data") and "[DONE]" not in e["data"] and json.loads(e["data"]).get("choices")
        ]
        tool_calls = [call for delta in tool_deltas for call in delta]
        self.assertEqual(tool_calls[0]["function"]["name"], "ast_grep_search")
        arguments = json.loads(tool_calls[0]["function"]["arguments"])
        self.assertEqual(arguments["lang"], "json")
        self.assertEqual(arguments["globs"], ["**/package.json"])
        self.assertIn("lan-guard", arguments["pattern"])
        self.assertEqual(tool_info.get("mode"), "textual_pseudo_call")

    def test_no_payload_no_tool_detection(self) -> None:
        events, tool_info = self._run_stream([json.dumps({"tool_call": {"name": "get_weather"}})])
        terminal = [e for e in events if e.get("data") and "[DONE]" not in e["data"]]
        last_choice = terminal[-1] if terminal else {}
        data = json.loads(last_choice.get("data", "{}")) if last_choice.get("data") else {}
        choices = data.get("choices", [])
        finish = choices[0].get("finish_reason") if choices else None
        self.assertEqual(finish, "stop")
        self.assertIsNone(tool_info)


class StreamAnthropicCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started = time.time()

    def _run_stream(self, chunks: list[str], *, payload: dict | None = None) -> tuple[list[dict], dict | None]:
        wfile = io.BytesIO()
        handler = _make_mock_handler(wfile)
        text, ok, err, lat, tool_info = sse.stream_anthropic_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=iter(chunks),
            headers={},
            payload=payload,
        )
        wfile.seek(0)
        events = _read_sse_events(wfile.read())
        return events, tool_info

    def test_upstream_exception_closes_iterator(self) -> None:
        chunks = CloseAwareChunks(["partial"], fail_after=1)
        handler = _make_mock_handler()
        text, ok, err, _lat, tool_info = sse.stream_anthropic_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=chunks,
            headers={},
        )

        self.assertEqual(text, "partial")
        self.assertFalse(ok)
        self.assertIn("RuntimeError", err)
        self.assertIn("upstream connection dropped", err)
        self.assertTrue(chunks.closed)
        self.assertIsNone(tool_info)

    def test_client_disconnect_closes_iterator(self) -> None:
        chunks = CloseAwareChunks(["one", "two", "three"])
        handler = _make_mock_handler(DisconnectingWriter(fail_after_writes=4))
        text, ok, err, _lat, tool_info = sse.stream_anthropic_completion(
            handler,
            started=self.started,
            model="test-model",
            chunks=chunks,
            headers={},
        )

        self.assertFalse(ok)
        self.assertIn("client disconnected", err)
        self.assertTrue(chunks.closed)
        self.assertIsNone(tool_info)

    def test_text_output_stop_reason_end_turn(self) -> None:
        payload = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "tools": [{"name": "get_weather", "description": "Get weather", "input_schema": {"type": "object"}}],
        }
        events, tool_info = self._run_stream(["hello", " world"], payload=payload)
        msg_delta = [e for e in events if e.get("event") == "message_delta"]
        self.assertTrue(msg_delta)
        data = json.loads(msg_delta[-1]["data"])
        self.assertEqual(data["delta"]["stop_reason"], "end_turn")
        self.assertIsNone(tool_info)

    def test_tool_call_output_stop_reason_tool_use(self) -> None:
        payload = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "use tool"}],
            "stream": True,
            "tools": [{"name": "get_weather", "description": "Get weather", "input_schema": {"type": "object"}}],
        }
        tool_output = json.dumps({"tool_call": {"name": "get_weather", "arguments": {"city": "NYC"}}})
        events, tool_info = self._run_stream([tool_output], payload=payload)
        msg_delta = [e for e in events if e.get("event") == "message_delta"]
        self.assertTrue(msg_delta)
        data = json.loads(msg_delta[-1]["data"])
        self.assertEqual(data["delta"]["stop_reason"], "tool_use")
        self.assertIsNotNone(tool_info)
        self.assertTrue(tool_info.get("detected"))
        self.assertEqual(tool_info.get("name"), "get_weather")
        self.assertEqual(tool_info.get("mode"), "structured")

    def test_no_payload_no_tool_detection(self) -> None:
        tool_output = json.dumps({"tool_call": {"name": "get_weather"}})
        events, tool_info = self._run_stream([tool_output])
        msg_delta = [e for e in events if e.get("event") == "message_delta"]
        self.assertTrue(msg_delta)
        data = json.loads(msg_delta[-1]["data"])
        self.assertEqual(data["delta"]["stop_reason"], "end_turn")
        self.assertIsNone(tool_info)


if __name__ == "__main__":
    unittest.main()
