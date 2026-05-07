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

from gateway import sse  # noqa: E402


def _make_mock_handler(wfile: io.BytesIO | None = None) -> mock.Mock:
    handler = mock.Mock()
    handler.wfile = wfile or io.BytesIO()
    handler.requestline = "POST /v1/chat/completions HTTP/1.1"
    handler.command = "POST"
    handler.path = "/v1/chat/completions"
    handler.headers = {}
    return handler


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

    def test_text_output_finish_reason_stop(self) -> None:
        events, tool_info = self._run_stream(["hello", " world"], payload=TOOL_DECLARATION_PAYLOAD)
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
