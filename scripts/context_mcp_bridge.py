#!/usr/bin/env python3
"""Bridge script for Context Mode MCP.
Spawns the MCP server via stdio and dispatches tools from the gateway.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = APP_ROOT / "integrations" / "context-mode-mcp"


def _pipe_error(name: str) -> RuntimeError:
    return RuntimeError(f"Context MCP server {name} pipe is unavailable")


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Context MCP bridge stdin JSON malformed: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def send_message(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    """Send a JSON-RPC message as newline-delimited JSON (NDJSON).

    The MCP SDK StdioServerTransport uses newline-delimited JSON, not
    the Content-Length framing from earlier protocol versions.
    """
    if proc.stdin is None:
        raise _pipe_error("stdin")
    try:
        proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise RuntimeError(f"Context MCP server stdin write failed: {exc}") from exc


def read_message(proc: subprocess.Popen[str], timeout: float = 10.0) -> dict[str, Any]:
    """Read a single JSON-RPC response line (NDJSON) from the MCP server stdout."""
    if proc.stdout is None:
        raise _pipe_error("stdout")
    try:
        ready = select.select([proc.stdout], [], [], timeout)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Context MCP server stdout wait failed: {exc}") from exc
    if not ready[0]:
        raise TimeoutError(f"MCP bridge read timeout after {timeout}s")
    try:
        line = proc.stdout.readline()
    except OSError as exc:
        raise RuntimeError(f"Context MCP server stdout read failed: {exc}") from exc
    if not line:
        raise RuntimeError("Context MCP server closed stdout")
    stripped = line.strip()
    if not stripped:
        raise RuntimeError("Context MCP server returned empty line")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Context MCP server returned malformed JSON: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def request(proc: subprocess.Popen[str], payload: dict[str, Any]) -> dict[str, Any]:
    send_message(proc, payload)
    request_id = payload.get("id")
    while True:
        response = read_message(proc)
        if request_id is None or response.get("id") == request_id:
            return response


def extract_context(response: dict[str, Any]) -> dict[str, Any]:
    """Extract context text and metadata from MCP tool response.

    Returns a dict with:
    - context: text representation of search results
    - meta: search metadata (strategy, degraded, suggestions)
    - results: raw result rows if available
    """
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    if structured:
        # MCP server returns full object: {ok, tool, query, results, meta}
        # Flatten meta to top level so gateway can read it easily
        extracted: dict[str, Any] = {}
        meta = structured.get("meta")
        if isinstance(meta, dict):
            extracted["meta"] = meta
        structured_context = structured.get("context")
        if isinstance(structured_context, dict):
            extracted["context"] = structured_context
            context_items = structured_context.get("items")
            if isinstance(context_items, list):
                extracted["results"] = context_items
                text_parts: list[str] = []
                for item in context_items:
                    if isinstance(item, dict):
                        snippet = item.get("snippet") or item.get("content") or ""
                        title = item.get("title") or item.get("uri") or ""
                        if snippet:
                            text_parts.append(f"{title}: {snippet}" if title else str(snippet))
                    elif item:
                        text_parts.append(str(item))
                if text_parts:
                    extracted["text"] = "\n".join(text_parts)
            return extracted
        results = structured.get("results")
        if isinstance(results, list):
            extracted["results"] = results
        # Build text context from results
        text_parts: list[str] = []
        for item in results or []:
            if isinstance(item, dict):
                snippet = item.get("snippet") or item.get("content") or ""
                title = item.get("title") or item.get("uri") or ""
                if snippet:
                    text_parts.append(f"{title}: {snippet}" if title else str(snippet))
            elif item:
                text_parts.append(str(item))
        if text_parts:
            extracted["context"] = "\n".join(text_parts)
        return extracted

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


def _start_mcp_process(project_root: str) -> subprocess.Popen[str]:
    """Spawn and initialize the MCP server process."""
    entry = MCP_ROOT / "dist" / "index.js"
    if not entry.is_file():
        raise SystemExit(
            f"Context MCP entrypoint is missing at {entry}; run npm install/build in {MCP_ROOT}"
        )

    command = ["node", str(entry)]
    env = dict(os.environ)
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
        # Give the Node.js MCP process time to start accepting stdin.
        # Without this delay, writing immediately after spawn causes the MCP
        # process to silently ignore the input, leading to a read timeout.
        time.sleep(0.2)
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
    except (BrokenPipeError, json.JSONDecodeError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        try:
            _terminate_mcp_process(proc)
        except RuntimeError as cleanup_exc:
            raise RuntimeError(f"Context MCP initialization failed: {exc}; cleanup failed: {cleanup_exc}") from exc
        raise RuntimeError(f"Context MCP initialization failed: {exc}") from exc
    return proc


def _terminate_mcp_process(proc: subprocess.Popen[str], *, strict: bool = True) -> None:
    """Gracefully terminate the MCP server process."""
    errors: list[str] = []
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError) as exc:
        errors.append(f"terminate failed: {exc}")
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (ProcessLookupError, subprocess.TimeoutExpired, OSError) as kill_exc:
            errors.append(f"kill failed: {kill_exc}")
    for name, pipe in (("stdin", proc.stdin), ("stdout", proc.stdout), ("stderr", proc.stderr)):
        try:
            if pipe:
                pipe.close()
        except OSError as exc:
            errors.append(f"close {name} failed: {exc}")
    if errors:
        message = "Context MCP process cleanup failed: " + "; ".join(errors)
        if strict:
            raise RuntimeError(message)
        print(f"[MCP Bridge] warning: {message}", file=sys.stderr)


def _dispatch_search(gateway_request: dict[str, Any]) -> int:
    """Execute ctx_search tool."""
    query = str(gateway_request.get("query", "")).strip()
    if not query:
        print(json.dumps({"context": "", "items": []}))
        return 0

    project_root = str(gateway_request.get("project_root") or os.getcwd())
    proc = _start_mcp_process(project_root)
    try:
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
        _terminate_mcp_process(proc, strict=False)


def _dispatch_index(gateway_request: dict[str, Any]) -> int:
    """Execute ctx_index tool."""
    project_root = str(gateway_request.get("project_root") or os.getcwd())
    proc = _start_mcp_process(project_root)
    try:
        response = request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ctx_index",
                    "arguments": {
                        "title": str(gateway_request.get("title") or "Full project index"),
                        "markdown": str(gateway_request.get("markdown") or ""),
                        "uri": str(gateway_request.get("uri") or project_root),
                        "tags": list(gateway_request.get("tags", ["full-index"])),
                    },
                },
            },
        )
        result = extract_context(response)
        # For indexing, return a success signal if no error
        if "error" in result:
            print(json.dumps({"ok": False, "error": result["error"]}))
            return 1
        print(json.dumps({"ok": True, "tool": "ctx_index", **result}, separators=(",", ":")))
        return 0
    finally:
        _terminate_mcp_process(proc, strict=False)


def main() -> int:
    gateway_request = read_stdin_json()
    tool = str(gateway_request.get("tool", "ctx_search")).strip() or "ctx_search"
    print(f"[BRIDGE] Tool: {tool}", file=sys.stderr)

    if tool == "ctx_index":
        return _dispatch_index(gateway_request)
    elif tool == "ctx_search":
        return _dispatch_search(gateway_request)
    else:
        print(json.dumps({"error": f"Unsupported tool: {tool}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
