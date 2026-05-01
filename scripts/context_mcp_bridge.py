#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = APP_ROOT / "integrations" / "context-mode-mcp"


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def send_message(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    """Send a JSON-RPC message as a newline-delimited line (MCP SDK 1.x stdio protocol)."""
    raw = json.dumps(payload, separators=(",", ":"))
    assert proc.stdin is not None
    proc.stdin.write(raw + "\n")
    proc.stdin.flush()


def read_message(proc: subprocess.Popen[str], timeout: float = 10.0) -> dict[str, Any]:
    """Read a single JSON-RPC response line from the MCP server stdout with timeout safety."""
    assert proc.stdout is not None
    while True:
        ready = select.select([proc.stdout], [], [], timeout)
        if not ready[0]:
            raise TimeoutError(f"MCP bridge read timeout after {timeout}s")
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Context MCP server closed stdout")
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            # Log stray output but continue (shouldn't happen with clean stdout)
            print(f"[MCP Bridge] Non-JSON line: {stripped[:200]}", file=sys.stderr)
            continue


def request(proc: subprocess.Popen[str], payload: dict[str, Any]) -> dict[str, Any]:
    send_message(proc, payload)
    request_id = payload.get("id")
    while True:
        response = read_message(proc)
        if request_id is None or response.get("id") == request_id:
            return response


def extract_context(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    if structured:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    try:
                        parsed = json.loads(text)
                        return parsed if isinstance(parsed, dict) else {"context": text}
                    except json.JSONDecodeError:
                        return {"context": text}
    return {}


def main() -> int:
    gateway_request = read_stdin_json()
    query = str(gateway_request.get("query", "")).strip()
    if not query:
        print(json.dumps({"context": "", "items": []}))
        return 0
    entry = MCP_ROOT / "dist" / "index.js"
    if not entry.is_file():
        raise SystemExit("Context MCP entrypoint is missing; run npm install/build in integrations/context-mode-mcp")

    command = ["node", str(entry)]
    env = dict(os.environ)

    # Pass the project root to the MCP server so it indexes/searches the correct DB.
    # The gateway sets this in the request payload; fallback to cwd if not provided.
    project_root = str(gateway_request.get("project_root") or os.getcwd())
    env["CTX_PROJECT_ROOT"] = project_root

    proc = subprocess.Popen(
        command,
        cwd=str(MCP_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    try:
        request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lmm-context-mcp-bridge", "version": "1.0.0"},
                },
            },
        )
        send_message(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        response = request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ctx_search",
                    "arguments": {
                        "query": query,
                        "limit": int(gateway_request.get("limit") or 8),
                    },
                },
            },
        )
        context = extract_context(response)
        print(json.dumps(context, separators=(",", ":")))
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
