from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lmm_config import load_lmm_config_from_env

from .protocol_normalizers import compact_json, message_summary

APP_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = APP_ROOT / "integrations" / "public-glyphos-ai-compute"

CommandRunner = Callable[
    [list[str]],
    subprocess.CompletedProcess[str],
]


def context_mcp_root() -> Path:
    return APP_ROOT / "integrations" / "context-mode-mcp"


def context_mcp_bridge_path() -> Path:
    return APP_ROOT / "scripts" / "context_mcp_bridge.py"


def context_mcp_db_path() -> Path:
    import hashlib

    project_root = os.getcwd()
    project_hash = hashlib.sha256(project_root.encode()).hexdigest()[:16]
    return Path.home() / ".claude" / "context-mode" / "sessions" / f"{project_hash}.db"


def run_context_command(
    command: list[str], *, input_text: str, timeout_seconds: float, cwd: str
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(command, timeout_seconds, output=stdout, stderr=stderr) from exc
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _maybe_run_indexer(timeout_seconds: float) -> dict[str, Any]:
    empty = {"indexed": 0, "skipped": 0, "errors": 0, "duration_ms": 0}
    mcp_entry = context_mcp_root() / "dist" / "index.js"
    if not mcp_entry.is_file():
        return empty

    node_bin = shutil.which("node")
    if not node_bin:
        return empty

    try:
        completed = subprocess.run(
            [node_bin, str(mcp_entry), "--index-project"],
            cwd=str(context_mcp_root()),
            env={**os.environ, "CTX_PROJECT_ROOT": os.getcwd()},
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
        try:
            result = json.loads(completed.stdout.strip())
            if isinstance(result, dict):
                return {
                    "indexed": int(result.get("indexed", 0)),
                    "skipped": int(result.get("skipped", 0)),
                    "errors": int(result.get("errors", 0)),
                    "duration_ms": int(result.get("duration_ms", 0)),
                }
        except (json.JSONDecodeError, ValueError):
            pass
        return empty
    except Exception:
        return empty


def context_status() -> tuple[str, bool]:
    context_config = load_lmm_config_from_env().context
    if not context_config.enabled:
        return "disabled", False
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        return "missing", False
    if context_config.command:
        return "command_configured", False
    if not context_mcp_bridge_path().is_file():
        return "missing_bridge", False
    if not (root / "dist" / "index.js").is_file():
        return "missing_dist", False
    return "bridge_ready", False


def extract_payload_context(payload: dict[str, Any]) -> Any:
    metadata = payload.get("metadata")
    candidates = [
        payload.get("lmm_context"),
        payload.get("retrieved_context"),
        payload.get("context"),
    ]
    if isinstance(metadata, dict):
        candidates.extend(
            [
                metadata.get("lmm_context"),
                metadata.get("retrieved_context"),
                metadata.get("context"),
            ]
        )
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return candidate
    return ""


def context_to_text(context: Any) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context.strip()
    return compact_json(context)


def command_context_from_output(raw: str) -> dict[str, Any]:
    default = {"context": "", "meta": {}}
    raw = raw.strip()
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"context": raw, "meta": {}}
    if not isinstance(parsed, dict):
        return {"context": str(parsed), "meta": {}}

    meta = parsed.get("meta")
    if isinstance(meta, dict):
        meta = {
            "strategy": str(meta.get("strategy", "unknown")),
            "degraded": bool(meta.get("degraded", False)),
            "suggestions": meta.get("suggestions") if isinstance(meta.get("suggestions"), list) else [],
        }
    else:
        meta = {}

    for key in ("retrieved_context", "context", "text", "markdown"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return {"context": value, "meta": meta}
        if isinstance(value, dict) and value:
            return {"context": json.dumps(value), "meta": meta}
        if isinstance(value, list) and value:
            return {"context": str(value), "meta": meta}

    items = parsed.get("items") or parsed.get("results") or parsed.get("snippets")
    if isinstance(items, list):
        pieces: list[str] = []
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("snippet")
                title = item.get("title") or item.get("path") or item.get("uri")
                if text:
                    pieces.append(f"{title}: {text}" if title else str(text))
            elif item:
                pieces.append(str(item))
        return {"context": "\n".join(pieces), "meta": meta}

    return default


def retrieve_context(
    payload: dict[str, Any],
    prompt: str,
    *,
    model: str,
    stream: bool,
    gateway_mode: str = "full",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = run_context_command,
) -> dict[str, Any]:
    context_config = load_lmm_config_from_env().context
    started = time.perf_counter()
    result: dict[str, Any] = {
        "status": "disabled",
        "used": False,
        "context": "",
        "source": "",
        "error": "",
        "latency_ms": 0,
    }
    if not context_config.enabled:
        return result
    root = context_mcp_root()
    if not (root / "package.json").is_file():
        result.update({"status": "missing"})
        return result

    payload_context = extract_payload_context(payload)
    if payload_context:
        text = context_to_text(payload_context)
        result.update(
            {
                "status": "retrieved_from_payload",
                "used": bool(text),
                "context": text,
                "source": "payload",
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    command = context_config.command
    if not command:
        bridge = context_mcp_bridge_path()
        if not bridge.is_file():
            result.update(
                {
                    "status": "missing_bridge",
                    "source": "context-mode-mcp",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            return result
        if not (root / "dist" / "index.js").is_file():
            result.update(
                {
                    "status": "missing_dist",
                    "source": "context-mode-mcp",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            return result
        command = f"{sys.executable} {bridge}"
    if not command:
        result.update(
            {
                "status": "available_no_context",
                "source": "context-mode-mcp",
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    gateway_config = load_lmm_config_from_env().gateway
    if gateway_mode == "fast":
        timeout_ms = gateway_config.fast_context_stream_timeout_ms if stream else gateway_config.fast_context_timeout_ms
    else:
        timeout_ms = context_config.stream_timeout_ms if stream else context_config.timeout_ms
    request_payload = {
        "tool": "ctx_search",
        "query": prompt[-4000:],
        "limit": 8,
        "model": model,
        "stream": stream,
        "message_summary": message_summary(payload.get("messages", [])),
        "project_root": os.getcwd(),
    }

    index_timeout_ms = 0 if stream or gateway_mode == "fast" else context_config.index_timeout_ms
    if index_timeout_ms > 0:
        index_started = time.perf_counter()
        index_result = _maybe_run_indexer(timeout_seconds=index_timeout_ms / 1000)
        result["indexer"] = index_result
        result["indexer_latency_ms"] = round((time.perf_counter() - index_started) * 1000)
    else:
        result["indexer"] = {"indexed": 0, "skipped": 0, "errors": 0, "duration_ms": 0}
        result["indexer_latency_ms"] = 0
        if stream or gateway_mode == "fast":
            result["search_degraded"] = True
            reason = "fast lane preflight budget" if gateway_mode == "fast" else "stream preflight budget"
            result["search_suggestions"] = [f"indexing skipped for {reason}"]

    try:
        completed = command_runner(
            shlex.split(command),
            input_text=compact_json(request_payload),
            timeout_seconds=timeout_ms / 1000,
            cwd=str(root),
        )
        if completed.returncode != 0:
            result.update({"status": "error", "source": "context-mode-mcp", "error": "context_command_failed"})
            return result
        extracted = command_context_from_output(completed.stdout)
        text = context_to_text(extracted.get("context", ""))
        search_meta = extracted.get("meta", {})
        result.update(
            {
                "status": "retrieved" if text else "empty",
                "used": bool(text),
                "context": text,
                "source": "context-mode-mcp",
                "search_strategy": search_meta.get("strategy", ""),
                "search_degraded": bool(result.get("search_degraded", False) or search_meta.get("degraded", False)),
                "search_suggestions": [
                    *list(result.get("search_suggestions", [])),
                    *(search_meta.get("suggestions") if isinstance(search_meta.get("suggestions"), list) else []),
                ],
            }
        )
        return result
    except subprocess.TimeoutExpired:
        result.update(
            {
                "status": "timeout",
                "source": "context-mode-mcp",
                "error": f"timeout after {timeout_ms}ms",
                "search_degraded": True,
                "search_suggestions": [f"context preflight exceeded {timeout_ms}ms budget"],
            }
        )
        return result
    except Exception as exc:
        result.update({"status": "error", "source": "context-mode-mcp", "error": exc.__class__.__name__})
        return result
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)


def build_context_payload(context_result: dict[str, Any]) -> Any:
    raw_context = str(context_result.get("context") or "") if context_result.get("used") else ""
    try:
        if str(INTEGRATION_ROOT) not in sys.path:
            sys.path.insert(0, str(INTEGRATION_ROOT))
        from glyphos_ai.glyph.context_encoding import encode_context  # type: ignore

        encoding_config = load_lmm_config_from_env().glyph_encoding
        return encode_context(
            raw_context,
            disabled=bool(encoding_config.disabled),
            force_error=bool(encoding_config.force_error),
        )
    except Exception as exc:
        return SimpleNamespace(
            raw_context=raw_context,
            raw_context_chars=len(raw_context),
            encoding_status="error_raw_fallback",
            encoded_context="",
            encoding_format="",
            encoding_ratio=1.0,
            estimated_token_delta=0,
            error=str(exc)[:400],
        )


def context_payload_to_encoding_result(context_payload: Any) -> dict[str, Any]:
    raw_context = str(getattr(context_payload, "raw_context", ""))
    encoded_context = str(getattr(context_payload, "encoded_context", ""))
    status = str(getattr(context_payload, "encoding_status", "skipped"))
    return {
        "status": status,
        "used": status == "encoded" and bool(encoded_context),
        "raw_context_chars": int(getattr(context_payload, "raw_context_chars", len(raw_context))),
        "encoded_context_chars": len(encoded_context),
        "estimated_token_delta": int(getattr(context_payload, "estimated_token_delta", 0)),
        "encoding_ratio": float(getattr(context_payload, "encoding_ratio", 1.0)),
        "encoded_context": encoded_context,
        "encoding_format": str(getattr(context_payload, "encoding_format", "")),
        "error": str(getattr(context_payload, "error", "")),
        "latency_ms": int(getattr(context_payload, "latency_ms", 0) or 0),
    }


def glyph_encode_context(context: str) -> dict[str, Any]:
    started = time.perf_counter()
    payload = build_context_payload({"used": bool(context.strip()), "context": context})
    result = context_payload_to_encoding_result(payload)
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def build_upstream_context(context_result: dict[str, Any]) -> dict[str, Any] | None:
    raw = str(context_result.get("context") or "").strip()
    if not raw:
        return None

    source = str(context_result.get("source", "")).strip()
    provenance: list[str] = []
    if source:
        provenance.append(source)

    search_strategy = str(context_result.get("search_strategy", "")).strip()
    if search_strategy:
        provenance.append(f"strategy:{search_strategy}")

    metadata = {
        "context_status": str(context_result.get("status", "")),
        "search_degraded": bool(context_result.get("search_degraded", False)),
        "search_suggestions": context_result.get("search_suggestions", []),
    }

    return {
        "content": raw,
        "locality": "external",
        "provenance": provenance,
        "metadata": metadata,
        "source": source,
    }


def prepare_gateway_context(
    payload: dict[str, Any],
    prompt: str,
    *,
    model: str,
    stream: bool,
    gateway_mode: str = "full",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = run_context_command,
) -> tuple[dict[str, Any], Any | None, dict[str, Any] | None]:
    started = time.perf_counter()
    context_result = retrieve_context(
        payload,
        prompt,
        model=model,
        stream=stream,
        gateway_mode=gateway_mode,
        command_runner=command_runner,
    )
    context_done = time.perf_counter()
    context_payload = build_context_payload(context_result) if context_result.get("used") else None
    payload_done = time.perf_counter()
    upstream_context = build_upstream_context(context_result)
    context_result["context_preflight_ms"] = round((context_done - started) * 1000)
    context_result["context_payload_build_ms"] = round((payload_done - context_done) * 1000)
    return context_result, context_payload, upstream_context


def _context_payload_value(context_payload: Any | None, name: str, default: Any) -> Any:
    if context_payload is None:
        return default
    return getattr(context_payload, name, default)


def assemble_prompt_raw(raw_prompt: str, context_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    context = str(context_result.get("context") or "").strip()
    if not context:
        return raw_prompt, {
            "assembly_status": "raw_prompt",
            "assembled_prompt_chars": len(raw_prompt),
            "context_block_chars": 0,
        }
    context_block = "\n".join(
        [
            "[Retrieved Context]",
            context,
        ]
    )
    assembled = "\n\n".join(
        [
            "System: Use retrieved context only as supporting evidence. The latest user instruction below overrides retrieved or encoded context.",
            context_block,
            "[Conversation and latest user request]",
            raw_prompt,
        ]
    )
    return assembled, {
        "assembly_status": "raw_context",
        "assembled_prompt_chars": len(assembled),
        "context_block_chars": len(context_block),
    }


def assemble_prompt(
    raw_prompt: str, context_result: dict[str, Any], encoding_result: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    context = str(context_result.get("context") or "").strip()
    if not context:
        return raw_prompt, {
            "assembly_status": "raw_prompt",
            "assembled_prompt_chars": len(raw_prompt),
            "context_block_chars": 0,
        }
    if encoding_result.get("used"):
        context_block = "\n".join(
            [
                "[Glyph Encoding v1]",
                "Decode this compact context before reasoning. Key aliases: p=path, f=file, t=title, u=uri, c=content, x=text, s=snippet, m=summary, r=score.",
                str(encoding_result.get("encoded_context", "")),
            ]
        )
        assembly_status = "glyph_encoded_context"
    else:
        context_block = "\n".join(
            [
                "[Retrieved Context]",
                context,
            ]
        )
        assembly_status = "raw_context"
    assembled = "\n\n".join(
        [
            "System: Use retrieved context only as supporting evidence. The latest user instruction below overrides retrieved or encoded context.",
            context_block,
            "[Conversation and latest user request]",
            raw_prompt,
        ]
    )
    return assembled, {
        "assembly_status": assembly_status,
        "assembled_prompt_chars": len(assembled),
        "context_block_chars": len(context_block),
    }


def prepare_gateway_pipeline(
    payload: dict[str, Any],
    raw_prompt: str,
    *,
    model: str,
    stream: bool,
    gateway_mode: str = "full",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = run_context_command,
) -> tuple[str, dict[str, Any]]:
    pipeline_started = time.perf_counter()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    request_lifecycle = {
        "messages": message_summary(payload.get("messages", [])),
        "model": model,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768"))),
        "stream": stream,
        "gateway_mode": gateway_mode,
        "harness_identity": "",
        "workspace_present": bool(payload.get("workspace") or metadata.get("workspace")),
        "session_present": bool(payload.get("session") or metadata.get("session")),
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
    }
    context_result, context_payload, upstream_context = prepare_gateway_context(
        payload,
        raw_prompt,
        model=model,
        stream=stream,
        gateway_mode=gateway_mode,
        command_runner=command_runner,
    )
    context_finished = time.perf_counter()
    encoding_result = context_payload_to_encoding_result(context_payload) if context_payload is not None else {}
    raw_ctx = str(context_result.get("context") or "") if context_result.get("used") else ""
    assembled_prompt, assembly = assemble_prompt_raw(raw_prompt, context_result)
    pipeline_finished = time.perf_counter()

    pipeline_mode = "routed-full" if context_result.get("used") else "routed-basic"
    pipeline = {
        "mode": pipeline_mode,
        "gateway_mode": gateway_mode,
        "request": request_lifecycle,
        "context_status": context_result.get("status", "unknown"),
        "context_used": bool(context_result.get("used")),
        "context_source": context_result.get("source", ""),
        "context_error": context_result.get("error", ""),
        "context_latency_ms": context_result.get("latency_ms", 0),
        "context_preflight_ms": context_result.get("context_preflight_ms", context_result.get("latency_ms", 0)),
        "context_payload_build_ms": context_result.get("context_payload_build_ms", 0),
        "context_indexer_latency_ms": context_result.get("indexer_latency_ms", 0),
        "search_strategy": context_result.get("search_strategy", ""),
        "search_degraded": bool(context_result.get("search_degraded", False)),
        "search_suggestions": context_result.get("search_suggestions", []),
        "timing": {
            "gateway_mode": pipeline_mode,
            "gateway_lane": gateway_mode,
            "context_preflight_start_ms": 0,
            "context_preflight_duration_ms": round((context_finished - pipeline_started) * 1000),
            "prompt_assembly_duration_ms": round((pipeline_finished - context_finished) * 1000),
            "pipeline_total_ms": round((pipeline_finished - pipeline_started) * 1000),
        },
        "glyph_encoding_status": encoding_result.get("status", "skipped"),
        "glyph_encoding_used": bool(encoding_result.get("used")),
        "raw_context_chars": encoding_result.get("raw_context_chars", 0),
        "encoded_context_chars": encoding_result.get("encoded_context_chars", 0),
        "estimated_token_delta": encoding_result.get("estimated_token_delta", 0),
        "encoding_ratio": encoding_result.get("encoding_ratio", 1.0),
        "glyph_encoding_error": encoding_result.get("error", ""),
        "glyph_encoding_latency_ms": encoding_result.get("latency_ms", 0),
        "context_payload_raw": raw_ctx,
        "context_payload_encoded": _context_payload_value(context_payload, "encoded_context", ""),
        "context_payload_encoding_status": _context_payload_value(context_payload, "encoding_status", "none"),
        "context_payload_encoding_format": _context_payload_value(context_payload, "encoding_format", ""),
        "context_payload_encoding_ratio": _context_payload_value(context_payload, "encoding_ratio", 1.0),
        "upstream_context": upstream_context,
        **assembly,
    }
    return assembled_prompt, pipeline


__all__ = [
    "assemble_prompt",
    "assemble_prompt_raw",
    "build_context_payload",
    "build_upstream_context",
    "command_context_from_output",
    "context_mcp_bridge_path",
    "context_mcp_db_path",
    "context_mcp_root",
    "context_payload_to_encoding_result",
    "context_status",
    "context_to_text",
    "extract_payload_context",
    "glyph_encode_context",
    "prepare_gateway_context",
    "prepare_gateway_pipeline",
    "retrieve_context",
    "run_context_command",
]
