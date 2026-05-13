#!/usr/bin/env python3
"""Bridge script for Context Mode MCP.
Spawns the MCP server via stdio and dispatches tools from the gateway.
# file: scripts/context_mcp_bridge.py
"""

from __future__ import annotations

import errno
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
    safe_name = str(name).strip() or "unknown"
    return RuntimeError(f"Context MCP server {safe_name} pipe is unavailable")


def read_stdin_json() -> dict[str, Any]:
    """
    Read a JSON object from stdin.

    Returns:
        {} if stdin is empty/whitespace only

    Raises:
        RuntimeError if stdin contains malformed JSON or a non-object payload
    """
    raw = sys.stdin.read()
    if not raw.strip():
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        preview = raw.strip()[:400]
        raise RuntimeError(f"Context MCP bridge stdin JSON malformed: {exc}; payload preview: {preview!r}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Context MCP bridge stdin payload must be a JSON object, got {type(payload).__name__}")

    return payload


def _mcp_exit_detail(proc: subprocess.Popen[str], *, limit: int = 2000) -> str:
    """
    Return a compact exit description if the child has already exited.
    Safe to call repeatedly.
    """
    if proc.poll() is None:
        return ""

    stderr_text = _mcp_stderr_snippet(proc, limit=limit)
    detail = f"Context MCP server exited (exit={proc.returncode})"
    if stderr_text:
        detail += f": {stderr_text}"
    return detail


def send_message(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    """
    Send one JSON-RPC message to the MCP child over stdin.

    Raises a detailed RuntimeError if:
    - stdin is unavailable
    - the child already exited
    - the write/flush fails
    """
    if proc.stdin is None:
        raise RuntimeError("Context MCP server stdin is unavailable")

    exit_detail = _mcp_exit_detail(proc)
    if exit_detail:
        raise RuntimeError(f"Context MCP server is not running before write; {exit_detail}")

    raw = json.dumps(payload, ensure_ascii=False) + "\n"

    try:
        proc.stdin.write(raw)
        proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError) as exc:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server stdin write failed: {exc}; {exit_detail}") from exc
        raise RuntimeError(f"Context MCP server stdin write failed: {exc}") from exc


def read_message(proc: subprocess.Popen[str], timeout: float = 10.0) -> dict[str, Any]:
    """Read a single JSON-RPC response line (NDJSON) from the MCP server stdout."""
    if proc.stdout is None:
        raise _pipe_error("stdout")

    exit_detail = _mcp_exit_detail(proc)
    if exit_detail:
        raise RuntimeError(f"Context MCP server is not running before read; {exit_detail}")

    try:
        ready = select.select([proc.stdout], [], [], timeout)
    except (OSError, ValueError) as exc:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server stdout wait failed: {exc}; {exit_detail}") from exc
        raise RuntimeError(f"Context MCP server stdout wait failed: {exc}") from exc

    if not ready[0]:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise TimeoutError(f"MCP bridge read timeout after {timeout}s; {exit_detail}")
        raise TimeoutError(f"MCP bridge read timeout after {timeout}s")

    try:
        line = proc.stdout.readline()
    except (BrokenPipeError, OSError, ValueError) as exc:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server stdout read failed: {exc}; {exit_detail}") from exc
        raise RuntimeError(f"Context MCP server stdout read failed: {exc}") from exc

    if not line:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server closed stdout; {exit_detail}")
        raise RuntimeError("Context MCP server closed stdout")

    stripped = line.strip()
    if not stripped:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server returned empty line; {exit_detail}")
        raise RuntimeError("Context MCP server returned empty line")

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        preview = stripped[:400]
        exit_detail = _mcp_exit_detail(proc)
        message = f"Context MCP server returned malformed JSON: {exc}; payload preview: {preview!r}"
        if exit_detail:
            message += f"; {exit_detail}"
        raise RuntimeError(message) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Context MCP server returned non-object JSON-RPC payload: {type(payload).__name__}")

    return payload


def request(
    proc: subprocess.Popen[str],
    payload: dict[str, Any],
    *,
    expect_id: int | str | None = None,
) -> dict[str, Any]:
    """
    Send one JSON-RPC request and wait for one JSON-RPC response.

    - surfaces process-exit details early
    - wraps read/parse errors with stderr/exit context when available
    - validates that a dict response was returned
    - optionally validates response id
    """
    exit_detail = _mcp_exit_detail(proc)
    if exit_detail:
        raise RuntimeError(f"Context MCP server is not running before request; {exit_detail}")

    send_message(proc, payload)

    try:
        response = read_message(proc)
    except (json.JSONDecodeError, TimeoutError, ValueError, OSError, RuntimeError) as exc:
        exit_detail = _mcp_exit_detail(proc)
        if exit_detail:
            raise RuntimeError(f"Context MCP server response read failed: {exc}; {exit_detail}") from exc
        raise RuntimeError(f"Context MCP server response read failed: {exc}") from exc

    if not isinstance(response, dict):
        raise RuntimeError(f"Context MCP server returned non-object response: {type(response).__name__}")

    if response.get("jsonrpc") != "2.0":
        raise RuntimeError(f"Context MCP server returned invalid JSON-RPC envelope: {response!r}")

    if expect_id is not None and response.get("id") != expect_id:
        raise RuntimeError(
            f"Context MCP server returned mismatched response id: expected {expect_id!r}, got {response.get('id')!r}"
        )

    if "error" in response and response["error"] is not None:
        raise RuntimeError(f"Context MCP server returned JSON-RPC error: {response['error']}")

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


def _mcp_stderr_snippet(proc: subprocess.Popen[str], *, limit: int = 2000) -> str:
    """
    Return a short stderr snippet only if the child has already exited.
    Avoids blocking on a still-running process.
    """
    if proc.stderr is None or proc.poll() is None:
        return ""
    try:
        text = proc.stderr.read() or ""
    except Exception as exc:
        return f"<unable to read stderr: {exc}>"
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _terminate_mcp_process(proc: subprocess.Popen[str], *, strict: bool = True) -> None:
    """Gracefully terminate the MCP server process.

    Tolerates common benign cleanup cases:
    - process already exited
    - stdin/stdout/stderr already closed
    - broken pipe on stdin
    - EBADF/EPIPE during pipe close
    """
    errors: list[str] = []

    def _benign_pipe_error(exc: BaseException) -> bool:
        if isinstance(exc, BrokenPipeError | ValueError):
            # Broken pipe or "I/O operation on closed file"
            return True
        if isinstance(exc, OSError) and exc.errno in {errno.EBADF, errno.EPIPE}:
            return True
        return False

    # Terminate only if still running.
    try:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except (ProcessLookupError, subprocess.TimeoutExpired, OSError) as kill_exc:
                    errors.append(f"kill failed: {kill_exc}")
            except (ProcessLookupError, OSError) as exc:
                # If it exited between poll() and terminate(), that is not fatal.
                if proc.poll() is None:
                    errors.append(f"terminate failed: {exc}")
    except Exception as exc:
        errors.append(f"process state check failed: {exc}")

    # Close pipes, but do not treat already-closed / broken-pipe conditions as fatal.
    for name, pipe in (("stdin", proc.stdin), ("stdout", proc.stdout), ("stderr", proc.stderr)):
        if pipe is None:
            continue
        try:
            if not pipe.closed:
                pipe.close()
        except Exception as exc:
            if _benign_pipe_error(exc):
                continue
            errors.append(f"close {name} failed: {exc}")

    if errors:
        message = "Context MCP process cleanup failed: " + "; ".join(errors)
        if strict:
            raise RuntimeError(message)
        print(f"[MCP Bridge] warning: {message}", file=sys.stderr)


def _start_mcp_process(project_root: str) -> subprocess.Popen[str]:
    """Spawn and initialize the MCP server process."""
    entry = MCP_ROOT / "dist" / "index.js"
    if not entry.is_file():
        raise SystemExit(f"Context MCP entrypoint is missing at {entry}; run npm install/build in {MCP_ROOT}")

    command = ["node", str(entry)]
    env = dict(os.environ)
    env["CTX_PROJECT_ROOT"] = project_root

    proc = subprocess.Popen(
        command,
        cwd=str(MCP_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            raise RuntimeError("Context MCP process did not expose stdio pipes")

        # Give the Node MCP process a brief moment to boot.
        time.sleep(0.2)

        # Early-exit check: if the child died during startup, surface real stderr now.
        if proc.poll() is not None:
            stderr_text = _mcp_stderr_snippet(proc)
            message = f"Context MCP server exited before initialize (exit={proc.returncode})"
            if stderr_text:
                message += f": {stderr_text}"
            raise RuntimeError(message)

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

        send_message(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )

        # Secondary check: some MCP servers die immediately after initialize.
        if proc.poll() is not None:
            stderr_text = _mcp_stderr_snippet(proc)
            message = f"Context MCP server exited immediately after initialize (exit={proc.returncode})"
            if stderr_text:
                message += f": {stderr_text}"
            raise RuntimeError(message)

    except (BrokenPipeError, json.JSONDecodeError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        stderr_text = _mcp_stderr_snippet(proc)
        detail = str(exc)
        if stderr_text and stderr_text not in detail:
            detail = f"{detail}; stderr: {stderr_text}"

        _terminate_mcp_process(proc, strict=False)
        raise RuntimeError(f"Context MCP initialization failed: {detail}") from exc

    return proc


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
