#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4


APP_TITLE = "LLM Model Manager"
APP_BRAND = "Local Control Surface"
HEADER_LINE = "# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes"
PHASE0_SCHEMA_VERSION = 1
MAX_ACTIVITY_EVENTS = 100
DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024
DEFAULT_CLI_TIMEOUT_SECONDS = 60
KNOWN_DEFAULT_KEYS = [
    "LLAMA_SERVER_BIN",
    "LLAMA_SERVER_HOST",
    "LLAMA_SERVER_PORT",
    "LLAMA_SERVER_DEVICE",
    "LLAMA_SERVER_CONTEXT",
    "LLAMA_SERVER_NGL",
    "LLAMA_SERVER_BATCH",
    "LLAMA_SERVER_THREADS",
    "LLAMA_SERVER_PARALLEL",
    "GGML_CUDA_ENABLE_UNIFIED_MEMORY",
    "LLAMA_SERVER_LOG",
    "LLAMA_SERVER_WAIT_SECONDS",
    "LLAMA_SERVER_EXTRA_ARGS",
    "LLAMA_MODEL_SYNC_OPENCODE",
    "LLAMA_MODEL_SYNC_CLAUDE",
    "LLAMA_MODEL_SYNC_OPENCLAW",
    "LLAMA_MODEL_SYNC_GLYPHOS",
    "OPENCLAW_PROFILE",
    "OPENCLAW_API_KEY",
    "CLAUDE_GATEWAY_HOST",
    "CLAUDE_GATEWAY_PORT",
    "CLAUDE_GATEWAY_LOG",
    "CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS",
    "CLAUDE_BASE_URL",
    "CLAUDE_MODEL_ID",
    "CLAUDE_AUTH_TOKEN",
    "CLAUDE_API_KEY",
]


class ValidationError(ValueError):
    """Structured validation failure for request/route payload validation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CommandTimeoutError(RuntimeError):
    def __init__(self, command: str, timeout_seconds: int):
        self.code = "command_timeout"
        self.command = command
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Command timed out after {timeout_seconds}s: {command}"
        )


def env_int(name: str, fallback: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return fallback
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return fallback


def parse_api_token() -> str:
    return os.environ.get("LLAMA_MODEL_WEB_API_TOKEN", "").strip()


def parse_allowed_hosts() -> set[str]:
    raw_hosts = os.environ.get("LLAMA_MODEL_WEB_ALLOWED_HOSTS", "").strip()
    if not raw_hosts:
        return set()
    return {
        item.strip().lower()
        for item in raw_hosts.split(",")
        if item.strip()
    }


def default_operation_activity_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "updated_at": "",
        "events": [],
    }


def parse_cli_timeout_seconds() -> int:
    return max(5, env_int("LLAMA_MODEL_WEB_CLI_TIMEOUT_SECONDS", DEFAULT_CLI_TIMEOUT_SECONDS))


def parse_max_request_bytes() -> int:
    return max(1024, env_int("LLAMA_MODEL_WEB_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES))


API_POST_PAYLOAD_SCHEMAS: dict[str, dict[str, Any]] = {
    "/api/models/save": {
        "allowed": {
            "alias", "path", "mmproj", "extra_args", "context", "ngl", "batch", "threads", "parallel", "device", "notes", "extra",
        },
        "required": {"path"},
    },
    "/api/models/delete": {
        "allowed": {"alias"},
        "required": {"alias"},
    },
    "/api/discover": {
        "allowed": {"root"},
    },
    "/api/remote/search": {
        "allowed": {"query", "limit", "cache_ttl_seconds"},
        "int_fields": {"limit", "cache_ttl_seconds"},
    },
    "/api/switch": {
        "allowed": {"target"},
        "required": {"target"},
    },
    "/api/restart": {
        "allowed": set(),
    },
    "/api/stop": {
        "allowed": set(),
    },
    "/api/mode": {
        "allowed": {"mode"},
        "required": {"mode"},
    },
    "/api/defaults/save": {
        "allowed": set(KNOWN_DEFAULT_KEYS),
    },
    "/api/dashboard-service": {
        "allowed": {"action"},
        "required": set(),
    },
    "/api/opencode/sync": {
        "allowed": {"preset"},
    },
    "/api/openclaw/sync": {
        "allowed": set(),
    },
    "/api/claude/sync": {
        "allowed": set(),
    },
    "/api/glyphos/sync": {
        "allowed": set(),
    },
    "/api/claude-gateway": {
        "allowed": {"action"},
    },
    "/api/downloads/start": {
        "allowed": {"repo_id", "artifact_name", "destination_root", "resume_partial_path", "resume_source_job_id"},
        "required": {"repo_id", "artifact_name"},
    },
    "/api/downloads/cancel": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
    "/api/downloads/retry": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
    "/api/downloads/resume": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
    "/api/downloads/cleanup": {
        "allowed": {"max_age_seconds"},
        "int_fields": {"max_age_seconds"},
    },
    "/api/downloads/cleanup-duplicates": {
        "allowed": set(),
    },
    "/api/downloads/delete-orphans": {
        "allowed": {"paths"},
    },
    "/api/downloads/recover": {
        "allowed": set(),
    },
    "/api/downloads/pause-queue": {
        "allowed": set(),
    },
    "/api/downloads/resume-queue": {
        "allowed": set(),
    },
    "/api/downloads/policy": {
        "allowed": {"max_active_downloads"},
        "int_fields": {"max_active_downloads"},
        "required": {"max_active_downloads"},
    },
    "/api/downloads/remove-queued": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
    "/api/downloads/clear-queued": {
        "allowed": set(),
    },
    "/api/downloads/prioritize-queued": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
    "/api/downloads/deprioritize-queued": {
        "allowed": {"id"},
        "required": {"id"},
        "str_fields": {"id"},
    },
}

DEMO_STATE = {
    "title": APP_TITLE,
    "brand": APP_BRAND,
    "defaults": {
        "LLAMA_SERVER_HOST": "127.0.0.1",
        "LLAMA_SERVER_PORT": "8081",
        "LLAMA_SERVER_DEVICE": "",
        "LLAMA_SERVER_CONTEXT": "128000",
        "LLAMA_SERVER_NGL": "999",
        "LLAMA_SERVER_BATCH": "128",
        "LLAMA_SERVER_THREADS": "16",
        "LLAMA_SERVER_PARALLEL": "1",
        "GGML_CUDA_ENABLE_UNIFIED_MEMORY": "",
        "LLAMA_SERVER_LOG": "/var/log/llama-server.log",
        "LLAMA_SERVER_EXTRA_ARGS": "",
        "LLAMA_MODEL_SYNC_OPENCODE": "1",
        "LLAMA_MODEL_SYNC_CLAUDE": "0",
        "LLAMA_MODEL_SYNC_OPENCLAW": "0",
        "LLAMA_MODEL_SYNC_GLYPHOS": "0",
    },
    "current": {
        "pid": "28142",
        "alias": "qwen36-35b-q2",
        "model": "/models/qwen/Qwen3.6-35-Q2_M.gguf",
        "log": "/var/log/llama-server.log",
        "configured_mode": "single-client",
        "configured_parallel": "1",
        "active_mode": "single-client",
        "active_parallel": "1",
        "active_context": "128000",
        "active_ngl": "999",
        "active_batch": "128",
        "active_threads": "16",
        "active_device": "cuda0",
        "cuda_unified_memory": "disabled",
        "auto_fit_override_reason": "",
        "health": "ok (http://127.0.0.1:8081/health)",
    },
    "doctor": {
        "pid": "28142",
        "alias": "qwen36-35b-q2",
        "model": "/models/qwen/Qwen3.6-35-Q2_M.gguf",
        "health": "ok",
        "host_os": "linux",
        "host_arch": "x86_64",
        "host_backends": "cpu,cuda",
        "defaults_file": "/etc/llama-server/defaults.env",
        "registry_file": "/etc/llama-server/models.tsv",
        "log": "/var/log/llama-server.log",
        "binary_ok": "yes",
        "binary": "/opt/llama-model-manager/runtime/llama-server/linux-x86_64-cuda/llama-server",
        "binary_source": "bundled",
        "binary_backend": "cuda",
        "binary_status": "compatible",
        "binary_message": "validated bundled NVIDIA CUDA binary",
        "binary_label": "NVIDIA CUDA",
        "endpoint": "http://127.0.0.1:8081/v1",
        "build_info": "b1-e365e65",
        "offload": "offloaded 41/41 layers to GPU",
        "kv_buffer": "2500.00 MiB",
        "graph_splits": "2",
        "gpu_memory": "NVIDIA RTX: 14.3 GiB used / 24.0 GiB total (9.7 GiB free)",
        "system_memory": "RAM: 42.0 GiB available / 128.0 GiB total",
        "fit_posture": "gpu-fit",
        "fit_guidance": "GPU-fit: enough VRAM for a GPU-heavy posture; still lower context if KV cache allocation fails.",
        "cuda_unified_memory": "disabled",
        "auto_fit_override_reason": "",
        "gpu_process_count": "1",
        "gpu_processes": "pid=28142 port=8081 context=128000 ngl=999 model=/models/qwen/Qwen3.6-35-Q2_M.gguf",
        "startup_category": "",
        "startup_diagnosis": "",
        "startup_suggested_fix": "",
        "server": "http://127.0.0.1:8081",
    },
    "mode": {
        "configured_mode": "single-client",
        "configured_parallel": "1",
        "active_parallel": "1",
        "active_mode": "single-client",
    },
    "models": [
        {
            "alias": "qwen36-35b-q2",
            "path": "/models/qwen/Qwen3.6-35-Q2_M.gguf",
            "extra": "",
            "mmproj": "",
            "extra_args": "",
            "context": "",
            "ngl": "",
            "batch": "",
            "threads": "",
            "parallel": "",
            "device": "",
            "notes": "Primary long-context coding profile",
            "exists": "yes",
        },
        {
            "alias": "qwen35-9b-q8",
            "path": "/models/qwen/Qwen3.5-9B-Q8_0.gguf",
            "extra": "",
            "mmproj": "",
            "extra_args": "",
            "context": "65536",
            "ngl": "999",
            "batch": "128",
            "threads": "12",
            "parallel": "1",
            "device": "cuda0",
            "notes": "Fast iteration profile",
            "exists": "yes",
        },
        {
            "alias": "gemma4-e4b-q8",
            "path": "/models/gemma/Gemma-4-E4B-Q8_K_P.gguf",
            "extra": "--mmproj /models/gemma/mmproj-Gemma-4-E4B-f16.gguf",
            "mmproj": "/models/gemma/mmproj-Gemma-4-E4B-f16.gguf",
            "extra_args": "",
            "context": "",
            "ngl": "",
            "batch": "",
            "threads": "",
            "parallel": "",
            "device": "",
            "notes": "Vision and audio profile",
            "exists": "yes",
        },
    ],
    "discovery_root": "/models",
    "api_base": "http://127.0.0.1:8081/v1",
    "opencode_model": "llamacpp/Qwen3.6-35-Q2_M.gguf",
}

DEMO_DISCOVERY = [
    {
        "alias": "mistral-small-24b-q4",
        "path": "/models/mistral/Mistral-Small-24B-Q4.gguf",
        "mmproj": "",
        "extra_args": "",
        "extra": "",
        "imported": "no",
        "exists": "yes",
    },
    {
        "alias": "gemma4-e4b-q8",
        "path": "/models/gemma/Gemma-4-E4B-Q8_K_P.gguf",
        "mmproj": "/models/gemma/mmproj-Gemma-4-E4B-f16.gguf",
        "extra_args": "",
        "extra": "--mmproj /models/gemma/mmproj-Gemma-4-E4B-f16.gguf",
        "imported": "yes",
        "exists": "yes",
    },
]

DEMO_LOG = """main: model loaded
main: server is listening on http://127.0.0.1:8081
srv  update_slots: all slots are idle
"""


def default_remote_models_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "provider": "huggingface",
        "query": "",
        "fetched_at": "",
        "items": [],
    }


def default_download_jobs_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "updated_at": "",
        "items": [],
    }


def default_runtime_profiles_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "items": [],
    }


def default_validation_results_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "items": [],
    }


def default_host_capability_store() -> dict[str, Any]:
    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "host_os": "",
        "host_arch": "",
        "host_backends": [],
        "preferred_backend": "",
        "memory_bytes": 0,
        "memory_human": "0 B",
        "binary_ok": "unknown",
        "selected_binary": {},
    }


class Manager:
    def __init__(self, app_root: Path, *, demo: bool = False) -> None:
        self.app_root = app_root
        self.demo = demo
        self.home = Path.home()
        self.xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", self.home / ".config"))
        self.xdg_state_home = Path(os.environ.get("XDG_STATE_HOME", self.home / ".local" / "state"))
        self.config_dir = self.xdg_config_home / "llama-server"
        self.defaults_file = Path(os.environ.get("LLAMA_DEFAULTS_FILE", self.config_dir / "defaults.env"))
        self.models_file = Path(os.environ.get("LLAMA_MODELS_FILE", self.config_dir / "models.tsv"))
        self.discovery_root = os.environ.get("LLAMA_MODEL_DISCOVERY_ROOT", str(self.home / "models"))
        self.opencode_config_file = Path(os.environ.get("OPENCODE_CONFIG_FILE", self.xdg_config_home / "opencode" / "opencode.json"))
        self.opencode_model_state_file = Path(os.environ.get("OPENCODE_MODEL_STATE_FILE", self.xdg_state_home / "opencode" / "model.json"))
        self.claude_settings_file = Path(os.environ.get("CLAUDE_SETTINGS_FILE", self.home / ".claude" / "settings.json"))
        self.glyphos_config_file = Path(os.environ.get("GLYPHOS_CONFIG_FILE", self.home / ".glyphos" / "config.yaml"))
        self.remote_models_file = self.xdg_state_home / "llama-server" / "remote-models.json"
        self.download_jobs_file = self.xdg_state_home / "llama-server" / "download-jobs.json"
        self.download_policy_file = self.xdg_state_home / "llama-server" / "download-policy.json"
        self.operation_activity_file = self.xdg_state_home / "llama-server" / "operation-activity.json"
        self.runtime_profiles_file = self.config_dir / "runtime-profiles.json"
        self.validation_results_file = self.xdg_state_home / "llama-server" / "validation-results.json"
        self.host_capability_file = self.xdg_state_home / "llama-server" / "host-capability.json"
        self.operation_activity_lock = threading.RLock()
        self.runtime_root = Path(os.environ.get("LLAMA_SERVER_RUNTIME_DIR", self.app_root.parent / "runtime")) / "llama-server"
        self.cli_bin = self._resolve_cli_bin()
        self.download_lock = threading.RLock()
        self.download_threads: dict[str, threading.Thread] = {}
        self.download_cancel_events: dict[str, threading.Event] = {}
        self.max_active_downloads = self.initial_max_active_downloads()
        self.download_queue_paused = self.initial_download_queue_paused()
        if not self.demo and self.download_jobs_file.exists():
            self.recover_stale_download_jobs()

    def _resolve_cli_bin(self) -> Path:
        env_bin = os.environ.get("LLAMA_MODEL_BIN")
        if env_bin:
            return Path(env_bin)

        sibling = (self.app_root.parent / "bin" / "llama-model").resolve()
        if sibling.exists():
            return sibling

        found = shutil.which("llama-model")
        if found:
            return Path(found)

        return Path.home() / ".local" / "bin" / "llama-model"

    def run_cli(self, *args: str) -> str:
        if self.demo:
            return ""
        if not self.cli_bin.exists():
            raise RuntimeError(f"llama-model not found: {self.cli_bin}")

        timeout_seconds = parse_cli_timeout_seconds()

        command = [str(self.cli_bin), *args]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            command_text = " ".join(shlex.quote(item) for item in command)
            raise CommandTimeoutError(command_text, timeout_seconds) from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "unknown llama-model error"
            raise RuntimeError(message)
        return result.stdout

    def parse_key_values(self, text: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
        return data

    def load_json_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def parse_env_file(self, path: Path) -> dict[str, str]:
        data: dict[str, str] = {}
        if not path.exists():
            return data

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            raw_value = raw_value.strip()
            if raw_value == "":
                data[key] = ""
                continue
            try:
                parsed = shlex.split(raw_value, posix=True)
                if len(parsed) <= 1:
                    data[key] = parsed[0] if parsed else ""
                else:
                    data[key] = " ".join(shlex.quote(part) for part in parsed)
            except ValueError:
                data[key] = raw_value.strip("\"'")
        return data

    def format_shell_value(self, value: str) -> str:
        return shlex.quote(value)

    def save_defaults(self, updates: dict[str, str]) -> None:
        if self.demo:
            return
        self.defaults_file.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = []
        if self.defaults_file.exists():
            existing_lines = self.defaults_file.read_text(encoding="utf-8").splitlines()

        remaining = dict(updates)
        output_lines: list[str] = []
        for raw_line in existing_lines:
            if "=" not in raw_line or raw_line.lstrip().startswith("#"):
                output_lines.append(raw_line)
                continue
            key, _ = raw_line.split("=", 1)
            key = key.strip()
            if key in remaining:
                output_lines.append(f"{key}={self.format_shell_value(remaining.pop(key))}")
            else:
                output_lines.append(raw_line)

        if not output_lines:
            output_lines.append("# llama-model-manager v2 defaults")

        for key in KNOWN_DEFAULT_KEYS:
            if key in remaining:
                output_lines.append(f"{key}={self.format_shell_value(remaining.pop(key))}")

        for key, value in remaining.items():
            output_lines.append(f"{key}={self.format_shell_value(value)}")

        self.defaults_file.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")

    def read_models(self) -> list[dict[str, str]]:
        if self.demo:
            return [dict(model) for model in DEMO_STATE["models"]]
        models: list[dict[str, str]] = []
        if not self.models_file.exists():
            return models

        for raw_line in self.models_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = raw_line.split("\t")
            parts.extend([""] * (10 - len(parts)))
            alias, path, extra, context, ngl, batch, threads, parallel, device, notes = parts[:10]
            split_extra = self.split_extra(extra)
            models.append(
                {
                    "alias": alias,
                    "path": path,
                    "extra": extra,
                    "mmproj": split_extra["mmproj"],
                    "extra_args": split_extra["extra_args"],
                    "context": context,
                    "ngl": ngl,
                    "batch": batch,
                    "threads": threads,
                    "parallel": parallel,
                    "device": device,
                    "notes": notes,
                    "exists": "yes" if Path(path).is_file() else "no",
                }
            )
        return models

    def write_models(self, models: list[dict[str, str]]) -> None:
        if self.demo:
            return
        self.models_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [HEADER_LINE]
        for model in models:
            fields = [
                model.get("alias", ""),
                model.get("path", ""),
                model.get("extra", ""),
                model.get("context", ""),
                model.get("ngl", ""),
                model.get("batch", ""),
                model.get("threads", ""),
                model.get("parallel", ""),
                model.get("device", ""),
                model.get("notes", ""),
            ]
            while len(fields) > 3 and fields[-1] == "":
                fields.pop()
            lines.append("\t".join(fields))
        self.models_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def sanitize_alias(self, raw: str) -> str:
        raw = Path(raw).name
        if raw.endswith(".gguf"):
            raw = raw[:-5]
        alias = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
        alias = re.sub(r"-{2,}", "-", alias)
        return alias

    def model_family_token(self, path: str) -> str:
        name = Path(path).name.lower().replace("_", "-").replace(".", "-")
        match = re.search(r"qwen3-5-([0-9]+b)", name) or re.search(r"qwen35-([0-9]+b)", name)
        if match:
            return f"qwen3.5-{match.group(1)}"
        match = re.search(r"gemma-4-(e[0-9]+b)", name) or re.search(r"gemma4-(e[0-9]+b)", name)
        if match:
            return f"gemma4-{match.group(1)}"
        match = re.search(r"(?:^|[^a-z0-9])(e?[0-9]+b)(?:[^a-z0-9]|$)", name)
        return match.group(1) if match else ""

    def mmproj_matches_model_filename(self, model_path: str, mmproj_path: str) -> bool:
        model_token = self.model_family_token(model_path)
        mmproj_token = self.model_family_token(mmproj_path)
        return not model_token or not mmproj_token or model_token == mmproj_token

    def validate_mmproj_for_model(self, model_path: str, mmproj_path: str) -> None:
        if mmproj_path and not self.mmproj_matches_model_filename(model_path, mmproj_path):
            raise ValueError(
                "mmproj appears to target a different model family: "
                f"{Path(mmproj_path).name} for {Path(model_path).name}"
            )

    def split_extra(self, extra: str) -> dict[str, str]:
        extra = extra.strip()
        if not extra:
            return {"mmproj": "", "extra_args": ""}

        try:
            tokens = shlex.split(extra, posix=True)
        except ValueError:
            return {"mmproj": "", "extra_args": extra}

        mmproj = ""
        remaining_tokens: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == "--mmproj" and index + 1 < len(tokens):
                mmproj = tokens[index + 1]
                index += 2
                continue
            remaining_tokens.append(token)
            index += 1

        return {
            "mmproj": mmproj,
            "extra_args": " ".join(shlex.quote(part) for part in remaining_tokens),
        }

    def build_extra(self, mmproj: str, extra_args: str) -> str:
        parts = []
        if mmproj.strip():
            parts.extend(["--mmproj", shlex.quote(mmproj.strip())])
        if extra_args.strip():
            parts.append(extra_args.strip())
        return " ".join(parts).strip()

    def save_model(self, payload: dict[str, Any]) -> dict[str, str]:
        if self.demo:
            return {
                "alias": self.sanitize_alias(str(payload.get("alias") or payload.get("path") or "")),
                "path": str(payload.get("path", "")),
                "extra": self.build_extra(str(payload.get("mmproj", "")).strip(), str(payload.get("extra_args", ""))),
                "context": str(payload.get("context", "")).strip(),
                "ngl": str(payload.get("ngl", "")).strip(),
                "batch": str(payload.get("batch", "")).strip(),
                "threads": str(payload.get("threads", "")).strip(),
                "parallel": str(payload.get("parallel", "")).strip(),
                "device": str(payload.get("device", "")).strip(),
                "notes": str(payload.get("notes", "")).strip(),
            }
        alias = self.sanitize_alias(str(payload.get("alias") or payload.get("path") or ""))
        if not alias:
            raise ValueError("Alias is required")

        model_path = str(Path(str(payload.get("path", ""))).expanduser())
        if not model_path:
            raise ValueError("Model path is required")
        resolved_model_path = str(Path(model_path).resolve())
        if not Path(resolved_model_path).is_file():
            raise ValueError(f"Model not found: {resolved_model_path}")

        mmproj = str(payload.get("mmproj", "")).strip()
        if mmproj:
            mmproj = str(Path(mmproj).expanduser().resolve())
            if not Path(mmproj).is_file():
                raise ValueError(f"mmproj not found: {mmproj}")
            self.validate_mmproj_for_model(resolved_model_path, mmproj)

        model = {
            "alias": alias,
            "path": resolved_model_path,
            "extra": self.build_extra(mmproj, str(payload.get("extra_args", ""))),
            "context": str(payload.get("context", "")).strip(),
            "ngl": str(payload.get("ngl", "")).strip(),
            "batch": str(payload.get("batch", "")).strip(),
            "threads": str(payload.get("threads", "")).strip(),
            "parallel": str(payload.get("parallel", "")).strip(),
            "device": str(payload.get("device", "")).strip(),
            "notes": str(payload.get("notes", "")).strip(),
        }

        models = self.read_models()
        replaced = False
        for index, existing in enumerate(models):
            if existing["alias"] == alias:
                models[index] = {**existing, **model, "mmproj": mmproj, "extra_args": str(payload.get("extra_args", "")).strip(), "exists": "yes"}
                replaced = True
                break
        if not replaced:
            models.append({**model, "mmproj": mmproj, "extra_args": str(payload.get("extra_args", "")).strip(), "exists": "yes"})

        self.write_models(models)
        return {
            **model,
            "mmproj": mmproj,
            "extra_args": str(payload.get("extra_args", "")).strip(),
            "exists": "yes",
        }

    def remove_model(self, alias: str) -> None:
        if self.demo:
            return
        models = self.read_models()
        kept = [model for model in models if model["alias"] != alias]
        if len(kept) == len(models):
            raise ValueError(f"Unknown model alias: {alias}")
        self.write_models(kept)

    def guess_mmproj(self, model_path: Path) -> str:
        candidates = sorted(model_path.parent.glob("*mmproj*.gguf"))
        return str(candidates[0].resolve()) if candidates else ""

    def discover(self, root: str) -> list[dict[str, str]]:
        if self.demo:
            return [dict(item) for item in DEMO_DISCOVERY]
        discovery_root = Path(root).expanduser().resolve()
        if not discovery_root.is_dir():
            raise ValueError(f"Discover root not found: {discovery_root}")

        existing_aliases = {model["alias"] for model in self.read_models()}
        existing_paths = {Path(model["path"]).resolve() for model in self.read_models() if model["path"]}

        results: list[dict[str, str]] = []
        for candidate in sorted(discovery_root.rglob("*.gguf")):
            if "mmproj" in candidate.name.lower():
                continue
            resolved = candidate.resolve()
            mmproj = self.guess_mmproj(resolved)
            alias = self.sanitize_alias(candidate.name)
            imported = "yes" if resolved in existing_paths or alias in existing_aliases else "no"
            results.append(
                {
                    "alias": alias,
                    "path": str(resolved),
                    "mmproj": mmproj,
                    "extra_args": "",
                    "extra": self.build_extra(mmproj, ""),
                    "imported": imported,
                    "exists": "yes",
                }
            )
        return results

    def defaults(self) -> dict[str, str]:
        if self.demo:
            return dict(DEMO_STATE["defaults"])
        values = self.parse_env_file(self.defaults_file)
        return {
            "LLAMA_SERVER_BIN": values.get("LLAMA_SERVER_BIN", ""),
            "LLAMA_SERVER_HOST": values.get("LLAMA_SERVER_HOST", "127.0.0.1"),
            "LLAMA_SERVER_PORT": values.get("LLAMA_SERVER_PORT", "8081"),
            "LLAMA_SERVER_DEVICE": values.get("LLAMA_SERVER_DEVICE", ""),
            "LLAMA_SERVER_CONTEXT": values.get("LLAMA_SERVER_CONTEXT", "128000"),
            "LLAMA_SERVER_NGL": values.get("LLAMA_SERVER_NGL", "999"),
            "LLAMA_SERVER_BATCH": values.get("LLAMA_SERVER_BATCH", "128"),
            "LLAMA_SERVER_THREADS": values.get("LLAMA_SERVER_THREADS", "16"),
            "LLAMA_SERVER_PARALLEL": values.get("LLAMA_SERVER_PARALLEL", ""),
            "GGML_CUDA_ENABLE_UNIFIED_MEMORY": values.get("GGML_CUDA_ENABLE_UNIFIED_MEMORY", ""),
            "LLAMA_SERVER_LOG": values.get("LLAMA_SERVER_LOG", str(self.home / "models" / "llama-server.log")),
            "LLAMA_SERVER_WAIT_SECONDS": values.get("LLAMA_SERVER_WAIT_SECONDS", "300"),
            "LLAMA_SERVER_EXTRA_ARGS": values.get("LLAMA_SERVER_EXTRA_ARGS", ""),
            "LLAMA_MODEL_SYNC_OPENCODE": values.get("LLAMA_MODEL_SYNC_OPENCODE", "1"),
            "LLAMA_MODEL_SYNC_CLAUDE": values.get("LLAMA_MODEL_SYNC_CLAUDE", "0"),
            "LLAMA_MODEL_SYNC_OPENCLAW": values.get("LLAMA_MODEL_SYNC_OPENCLAW", "0"),
            "LLAMA_MODEL_SYNC_GLYPHOS": values.get("LLAMA_MODEL_SYNC_GLYPHOS", "0"),
            "OPENCLAW_PROFILE": values.get("OPENCLAW_PROFILE", ""),
            "OPENCLAW_API_KEY": values.get("OPENCLAW_API_KEY", "llama-local"),
            "CLAUDE_GATEWAY_HOST": values.get("CLAUDE_GATEWAY_HOST", "127.0.0.1"),
            "CLAUDE_GATEWAY_PORT": values.get("CLAUDE_GATEWAY_PORT", "4000"),
            "CLAUDE_GATEWAY_LOG": values.get("CLAUDE_GATEWAY_LOG", str(self.home / "models" / "claude-gateway.log")),
            "CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS": values.get("CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "1800"),
            "CLAUDE_BASE_URL": values.get("CLAUDE_BASE_URL", ""),
            "CLAUDE_MODEL_ID": values.get("CLAUDE_MODEL_ID", ""),
            "CLAUDE_AUTH_TOKEN": values.get("CLAUDE_AUTH_TOKEN", ""),
            "CLAUDE_API_KEY": values.get("CLAUDE_API_KEY", ""),
        }

    def iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def human_bytes(self, value: int) -> str:
        if value <= 0:
            return "0 B"
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        amount = float(value)
        for unit in units:
            if amount < 1024.0 or unit == units[-1]:
                if unit == "B":
                    return f"{int(amount)} {unit}"
                return f"{amount:.1f} {unit}"
            amount /= 1024.0
        return f"{value} B"

    def parse_extra_cli_args(self, extra_args: str) -> list[str]:
        extra_args = extra_args.strip()
        if not extra_args:
            return []
        return shlex.split(extra_args, posix=True)

    def read_json_store(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(default)
        if not isinstance(payload, dict):
            return dict(default)
        return payload

    def initial_download_queue_paused(self) -> bool:
        env_value = os.environ.get("LLAMA_MODEL_DOWNLOAD_QUEUE_PAUSED", "").strip().lower()
        if env_value in {"1", "true", "yes"}:
            return True
        if env_value in {"0", "false", "no"}:
            return False
        store = self.read_json_store(self.download_policy_file, {"queue_paused": False})
        return bool(store.get("queue_paused"))

    def initial_max_active_downloads(self) -> int:
        env_value = os.environ.get("LLAMA_MODEL_MAX_ACTIVE_DOWNLOADS", "").strip()
        if env_value:
            try:
                return max(1, int(env_value))
            except ValueError:
                return 2
        store = self.read_json_store(self.download_policy_file, {"max_active_downloads": 2})
        try:
            return max(1, int(store.get("max_active_downloads") or 2))
        except (TypeError, ValueError):
            return 2

    def write_json_store(self, path: Path, payload: dict[str, Any]) -> None:
        if self.demo:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".llama-json.",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)

    def normalize_items_store(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        store = self.read_json_store(path, default)
        needs_write = not path.exists()
        if not isinstance(store.get("items"), list):
            store = {**dict(default), **store, "items": []}
            needs_write = True
        if needs_write:
            self.write_json_store(path, store)
        return store

    def read_operation_activity_store(self) -> dict[str, Any]:
        store = self.read_json_store(self.operation_activity_file, default_operation_activity_store())
        raw_events = store.get("events")
        if isinstance(raw_events, list):
            source = raw_events
            needs_write = False
        else:
            source = store.get("items") if isinstance(store.get("items"), list) else []
            needs_write = True

        normalized_events = [
            event for event in source
            if isinstance(event, dict)
        ]
        normalized = {
            "schema_version": PHASE0_SCHEMA_VERSION,
            "updated_at": str(store.get("updated_at", "")),
            "events": normalized_events[:MAX_ACTIVITY_EVENTS],
        }
        if needs_write or normalized_events != source:
            self.write_json_store(self.operation_activity_file, normalized)
        return normalized

    def record_operation_activity(
        self,
        *,
        route: str,
        action: str,
        actor_source: str,
        status: str,
        duration_ms: float,
        retry_count: int = 0,
        error_code: str = "",
        error_message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "id": str(uuid4()),
            "route": route,
            "action": action,
            "actor_source": actor_source,
            "status": status,
            "duration_ms": float(duration_ms),
            "retry_count": retry_count,
            "error_code": error_code,
            "error_message": error_message,
            "details": details or {},
            "happened_at": self.iso_now(),
        }
        with self.operation_activity_lock:
            store = self.read_operation_activity_store()
            events = list(store.get("events", []))
            events.insert(0, payload)
            del events[MAX_ACTIVITY_EVENTS:]
            self.write_json_store(
                self.operation_activity_file,
                {
                    "schema_version": PHASE0_SCHEMA_VERSION,
                    "updated_at": self.iso_now(),
                    "events": events,
                },
            )

    def runtime_profile_from_manifest(self, manifest_path: Path) -> dict[str, Any]:
        metadata = self.parse_env_file(manifest_path)
        profile_id = manifest_path.parent.name
        return {
            "id": profile_id,
            "os": metadata.get("LLAMA_BUNDLE_OS", ""),
            "arch": metadata.get("LLAMA_BUNDLE_ARCH", ""),
            "backend": metadata.get("LLAMA_BUNDLE_BACKEND", ""),
            "label": metadata.get("LLAMA_BUNDLE_LABEL", profile_id),
            "source_ref": metadata.get("LLAMA_BUNDLE_SOURCE_REF", ""),
            "built_at": metadata.get("LLAMA_BUNDLE_BUILT_AT", ""),
            "binary_path": str((manifest_path.parent / "llama-server").resolve()),
            "manifest_path": str(manifest_path.resolve()),
        }

    def discover_runtime_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        if not self.runtime_root.exists():
            return profiles
        for manifest_path in sorted(self.runtime_root.glob("*/llama-server.compat.env")):
            profiles.append(self.runtime_profile_from_manifest(manifest_path))
        return profiles

    def read_runtime_profiles_store(self) -> dict[str, Any]:
        discovered = self.discover_runtime_profiles()
        store = self.read_json_store(self.runtime_profiles_file, default_runtime_profiles_store())
        if not isinstance(store.get("items"), list):
            store = default_runtime_profiles_store()
        if discovered:
            store = {
                "schema_version": PHASE0_SCHEMA_VERSION,
                "items": discovered,
            }
            self.write_json_store(self.runtime_profiles_file, store)
        elif not self.runtime_profiles_file.exists():
            self.write_json_store(self.runtime_profiles_file, store)
        return store

    def read_validation_results_store(self) -> dict[str, Any]:
        return self.normalize_items_store(self.validation_results_file, default_validation_results_store())

    def read_download_jobs_store(self) -> dict[str, Any]:
        with self.download_lock:
            store = self.normalize_items_store(self.download_jobs_file, default_download_jobs_store())
            normalized_items: list[dict[str, Any]] = []
            queued_position = 0
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                annotated = self.annotate_job_resume_state(dict(item))
                if str(annotated.get("status", "")) == "queued":
                    queued_position += 1
                    annotated["queue_position"] = queued_position
                else:
                    annotated["queue_position"] = 0
                annotated["can_prioritize"] = False
                annotated["can_deprioritize"] = False
                normalized_items.append(annotated)
            queued_indexes = [
                index for index, item in enumerate(normalized_items)
                if str(item.get("status", "")) == "queued"
            ]
            for queued_order, item_index in enumerate(queued_indexes):
                can_prioritize = queued_order > 0
                can_deprioritize = queued_order < len(queued_indexes) - 1
                normalized_items[item_index]["can_prioritize"] = can_prioritize
                normalized_items[item_index]["can_deprioritize"] = can_deprioritize
            # These fields are view-only; do not persist them on read (avoids disk churn on /api/state).
            return {
                **store,
                "items": normalized_items,
            }

    def write_download_jobs_store(self, store: dict[str, Any]) -> None:
        with self.download_lock:
            ephemeral = {"partial_bytes", "resume_available", "queue_position", "can_prioritize", "can_deprioritize"}
            persisted_items: list[dict[str, Any]] = []
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                persisted_items.append({key: value for key, value in item.items() if key not in ephemeral})
            normalized = {
                "schema_version": PHASE0_SCHEMA_VERSION,
                "updated_at": str(store.get("updated_at", "")),
                "items": persisted_items,
            }
            self.write_json_store(self.download_jobs_file, normalized)

    def normalize_host_capability_store(self, store: dict[str, Any], doctor: dict[str, str] | None = None) -> dict[str, Any]:
        doctor = doctor or {}
        raw_backends = store.get("host_backends", doctor.get("host_backends", []))
        if isinstance(raw_backends, str):
            host_backends = [part.strip() for part in raw_backends.split(",") if part.strip()]
        elif isinstance(raw_backends, list):
            host_backends = [str(part).strip() for part in raw_backends if str(part).strip()]
        else:
            host_backends = []

        preferred_backend = str(store.get("preferred_backend") or doctor.get("binary_backend") or (host_backends[0] if host_backends else "")).strip()
        try:
            memory_bytes = int(store.get("memory_bytes") or 0)
        except (TypeError, ValueError):
            memory_bytes = 0

        selected_binary = store.get("selected_binary", {})
        if not isinstance(selected_binary, dict):
            selected_binary = {}
        selected_binary = {
            **selected_binary,
            "path": str(selected_binary.get("path") or doctor.get("binary", "")).strip(),
            "source": str(selected_binary.get("source") or doctor.get("binary_source", "")).strip(),
            "backend": str(selected_binary.get("backend") or doctor.get("binary_backend", "")).strip(),
            "status": str(selected_binary.get("status") or doctor.get("binary_status", "")).strip(),
            "label": str(selected_binary.get("label") or doctor.get("binary_label", "")).strip(),
            "message": str(selected_binary.get("message") or doctor.get("binary_message", "")).strip(),
            "manifest_path": str(selected_binary.get("manifest_path") or doctor.get("binary_manifest", "")).strip(),
        }

        return {
            "schema_version": PHASE0_SCHEMA_VERSION,
            "host_os": str(store.get("host_os") or doctor.get("host_os", "")).strip(),
            "host_arch": str(store.get("host_arch") or doctor.get("host_arch", "")).strip(),
            "host_backends": host_backends,
            "preferred_backend": preferred_backend,
            "memory_bytes": memory_bytes,
            "memory_human": self.human_bytes(memory_bytes),
            "binary_ok": str(store.get("binary_ok") or doctor.get("binary_ok", "unknown")).strip(),
            "selected_binary": selected_binary,
        }

    def read_host_capability_store(self, doctor: dict[str, str] | None = None) -> dict[str, Any]:
        store = self.read_json_store(self.host_capability_file, default_host_capability_store())
        normalized = self.normalize_host_capability_store(store, doctor)
        self.write_json_store(self.host_capability_file, normalized)
        return normalized

    def phase0_contracts(self, doctor: dict[str, str] | None = None) -> dict[str, Any]:
        doctor = doctor or {}
        remote_models = self.normalize_items_store(self.remote_models_file, default_remote_models_store())
        download_jobs = self.read_download_jobs_store()
        runtime_profiles = self.read_runtime_profiles_store()
        validation_results = self.read_validation_results_store()
        host_capability = self.read_host_capability_store(doctor)
        remote_items = [
            item for item in remote_models.get("items", [])
            if isinstance(item, dict)
        ]
        remote_models = {
            **remote_models,
            "items": self.annotate_remote_models(remote_items, host_capability),
        }
        return {
            "remote_models": remote_models,
            "download_jobs": download_jobs,
            "download_storage": self.download_storage_summary(download_jobs),
            "download_policy": self.download_policy_summary(download_jobs),
            "operation_activity": self.read_operation_activity_store(),
            "runtime_profiles": runtime_profiles,
            "validation_results": validation_results,
            "host_capability": host_capability,
        }

    def download_policy_summary(self, download_jobs: dict[str, Any]) -> dict[str, Any]:
        items = [item for item in download_jobs.get("items", []) if isinstance(item, dict)]
        queued = [item for item in items if str(item.get("status", "")) == "queued"]
        running = [item for item in items if str(item.get("status", "")) == "running"]
        active = [item for item in items if str(item.get("status", "")) in {"queued", "running"}]
        active_artifacts: dict[str, list[str]] = {}
        for item in active:
            key = f"{item.get('repo_id', '')}/{item.get('artifact_name', '')}"
            active_artifacts.setdefault(key, []).append(str(item.get("id", "")))
        duplicate_active = [
            {"artifact": artifact, "job_ids": job_ids}
            for artifact, job_ids in sorted(active_artifacts.items())
            if artifact.strip("/") and len(job_ids) > 1
        ]
        next_queued = queued[0] if queued else {}
        return {
            "max_active_downloads": self.max_active_downloads,
            "queue_paused": self.download_queue_paused,
            "active_downloads": len(active),
            "running_downloads": len(running),
            "queued_downloads": len(queued),
            "next_queued_job": {
                "id": str(next_queued.get("id", "")),
                "repo_id": str(next_queued.get("repo_id", "")),
                "artifact_name": str(next_queued.get("artifact_name", "")),
            } if next_queued else {},
            "available_slots": 0 if self.download_queue_paused else max(self.max_active_downloads - len(running), 0),
            "at_capacity": len(running) >= self.max_active_downloads,
            "duplicate_active_artifacts": duplicate_active,
            "duplicate_active_count": len(duplicate_active),
        }

    def download_storage_summary(self, download_jobs: dict[str, Any]) -> dict[str, Any]:
        partial_bytes = 0
        completed_paths: dict[str, list[str]] = {}
        referenced_paths: set[str] = set()
        download_roots: set[Path] = set()
        for model in self.read_models():
            model_path = str(model.get("path", "")).strip()
            if model_path:
                referenced_paths.add(str(Path(model_path).expanduser().resolve()))
            mmproj_path = str(model.get("mmproj", "")).strip()
            if mmproj_path:
                referenced_paths.add(str(Path(mmproj_path).expanduser().resolve()))
        for item in download_jobs.get("items", []):
            if not isinstance(item, dict):
                continue
            partial_bytes += int(item.get("partial_bytes") or 0)
            destination_root = str(item.get("destination_root", "")).strip()
            if destination_root:
                download_roots.add(Path(destination_root).expanduser().resolve())
            local_path = str(item.get("local_path", "")).strip()
            if str(item.get("status", "")) == "completed" and local_path:
                resolved_local_path = str(Path(local_path).expanduser().resolve())
                referenced_paths.add(resolved_local_path)
                completed_paths.setdefault(resolved_local_path, []).append(str(item.get("id", "")))
            mmproj_local_path = str(item.get("mmproj_local_path", "")).strip()
            if str(item.get("status", "")) == "completed" and mmproj_local_path:
                referenced_paths.add(str(Path(mmproj_local_path).expanduser().resolve()))
        duplicates = [
            {"path": path, "job_ids": job_ids}
            for path, job_ids in sorted(completed_paths.items())
            if len(job_ids) > 1
        ]
        duplicate_job_records = sum(max(len(item["job_ids"]) - 1, 0) for item in duplicates)
        orphaned = self.orphaned_download_artifacts(download_roots, referenced_paths)
        return {
            "partial_bytes": partial_bytes,
            "partial_human": self.human_bytes(partial_bytes),
            "duplicate_completed_artifacts": duplicates,
            "duplicate_completed_count": len(duplicates),
            "duplicate_completed_job_records": duplicate_job_records,
            "duplicate_cleanup_mode": "advisory",
            "duplicate_cleanup_guidance": (
                "Duplicate completed entries point at the same artifact path. "
                "They are advisory only; model files are not removed automatically."
            ),
            "orphaned_artifacts": orphaned["items"],
            "orphaned_artifact_count": len(orphaned["items"]),
            "orphaned_artifact_bytes": orphaned["bytes"],
            "orphaned_artifact_human": self.human_bytes(orphaned["bytes"]),
            "orphaned_cleanup_mode": "advisory",
            "orphaned_cleanup_guidance": (
                "Orphaned artifacts are files under known download roots that are not referenced by "
                "the registry or completed jobs. They are advisory only; files are not removed automatically."
            ),
        }

    def orphaned_download_artifacts(self, roots: set[Path], referenced_paths: set[str]) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        total_bytes = 0
        for root in sorted(roots):
            if not root.is_dir():
                continue
            try:
                candidates = sorted(root.rglob("*.gguf"))
            except OSError:
                continue
            for candidate in candidates:
                try:
                    resolved = str(candidate.resolve())
                    size_bytes = candidate.stat().st_size
                except OSError:
                    continue
                if resolved in referenced_paths:
                    continue
                total_bytes += size_bytes
                items.append({
                    "path": resolved,
                    "size_bytes": size_bytes,
                    "size_human": self.human_bytes(size_bytes),
                })
        return {
            "items": items,
            "bytes": total_bytes,
        }

    def validation_index(self, validation_results: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in validation_results.get("items", []):
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip()
            model_path = str(item.get("model_path", "")).strip()
            index[(alias, model_path)] = item
        return index

    def annotate_models_with_validation(
        self,
        models: list[dict[str, Any]],
        validation_results: dict[str, Any],
    ) -> list[dict[str, Any]]:
        validation_map = self.validation_index(validation_results)
        annotated: list[dict[str, Any]] = []
        for model in models:
            entry = dict(model)
            validation = validation_map.get((entry.get("alias", ""), entry.get("path", "")), {})
            entry["validation_status"] = str(validation.get("status", "")).strip()
            entry["validation_summary"] = str(validation.get("summary", "")).strip()
            annotated.append(entry)
        return annotated

    def compatibility_estimate(
        self,
        *,
        size_bytes: int,
        host_capability: dict[str, Any],
        context: str = "",
        device: str = "",
    ) -> dict[str, str]:
        host_backends = [str(item).lower() for item in host_capability.get("host_backends", [])]
        preferred_backend = str(host_capability.get("preferred_backend", "")).lower()
        memory_bytes = int(host_capability.get("memory_bytes") or 0)
        memory_human = str(host_capability.get("memory_human") or self.human_bytes(memory_bytes))
        requested_device = device.strip().lower()

        if requested_device.startswith("cuda") and "cuda" not in host_backends:
            return {
                "compatibility_status": "likely-incompatible",
                "compatibility_summary": f"Model requests cuda but host only provides {', '.join(host_backends) or 'unknown backends'}.",
            }

        if memory_bytes > 0 and size_bytes <= memory_bytes:
            summary = f"Artifact size {self.human_bytes(size_bytes)} fits within detected memory budget {memory_human}."
            if preferred_backend:
                summary = f"{summary} Preferred backend is {preferred_backend}."
            if context:
                summary = f"{summary} Advertised context {context}."
            return {
                "compatibility_status": "good-fit",
                "compatibility_summary": summary,
            }

        if memory_bytes > 0:
            return {
                "compatibility_status": "likely-tight",
                "compatibility_summary": f"Artifact size {self.human_bytes(size_bytes)} may exceed practical memory budget {memory_human}.",
            }

        return {
            "compatibility_status": "unknown",
            "compatibility_summary": f"Artifact size {self.human_bytes(size_bytes)}. Host memory was not detected.",
        }

    def sibling_metadata_map(self, siblings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for sibling in siblings:
            if not isinstance(sibling, dict):
                continue
            name = str(sibling.get("rfilename", "")).strip()
            if name:
                mapping[name] = sibling
        return mapping

    def remote_artifact_metadata(self, sibling_map: dict[str, dict[str, Any]], artifact_name: str) -> dict[str, Any]:
        return sibling_map.get(artifact_name, {})

    def sibling_size_bytes(self, metadata: dict[str, Any]) -> int:
        try:
            size = metadata.get("size")
            if size is not None:
                return int(size)
        except (TypeError, ValueError):
            pass
        lfs = metadata.get("lfs")
        if isinstance(lfs, dict):
            try:
                size = lfs.get("size")
                if size is not None:
                    return int(size)
            except (TypeError, ValueError):
                return 0
        return 0

    def normalize_remote_model_artifacts(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Explode one Hugging Face model record into artifact-specific download rows."""
        repo_id = str(raw.get("id", "")).strip()
        if not repo_id:
            return []
        siblings = raw.get("siblings", [])
        if not isinstance(siblings, list):
            return []

        sibling_map = self.sibling_metadata_map([sib for sib in siblings if isinstance(sib, dict)])
        gguf_names = sorted(
            name for name in sibling_map.keys()
            if name.endswith(".gguf") and "mmproj" not in name.lower()
        )
        if not gguf_names:
            return []
        mmproj_names = sorted(
            name for name in sibling_map.keys()
            if name.endswith(".gguf") and "mmproj" in name.lower()
        )
        mmproj_artifact_name = mmproj_names[0] if mmproj_names else ""
        mmproj_size_bytes = self.sibling_size_bytes(self.remote_artifact_metadata(sibling_map, mmproj_artifact_name)) if mmproj_artifact_name else 0

        gguf_meta = raw.get("gguf", {})
        architecture = str(gguf_meta.get("architecture", "")).strip() if isinstance(gguf_meta, dict) else ""
        context_value = ""
        if isinstance(gguf_meta, dict) and gguf_meta.get("context_length") is not None:
            context_value = str(gguf_meta.get("context_length"))

        source_url = f"https://huggingface.co/{repo_id}"
        items: list[dict[str, Any]] = []
        for artifact_name in gguf_names[:50]:
            artifact_meta = self.remote_artifact_metadata(sibling_map, artifact_name)
            size_bytes = self.sibling_size_bytes(artifact_meta)
            quant_match = re.search(r"-(Q[^.]+)\.gguf$", artifact_name, re.IGNORECASE)
            quant = quant_match.group(1) if quant_match else ""
            resolved_url = f"{source_url}/resolve/main/{urllib.parse.quote(artifact_name)}"
            mmproj_url = f"{source_url}/resolve/main/{urllib.parse.quote(mmproj_artifact_name)}" if mmproj_artifact_name else ""
            items.append({
                "repo_id": repo_id,
                "artifact_name": artifact_name,
                "alias": self.sanitize_alias(artifact_name),
                "download_url": resolved_url,
                "source_url": source_url,
                "quant": quant,
                "architecture": architecture,
                "context": context_value,
                "size_bytes": int(size_bytes or 0),
                "size_human": self.human_bytes(int(size_bytes or 0)),
                "gated": "yes" if bool(raw.get("gated")) else "no",
                "private": "yes" if bool(raw.get("private")) else "no",
                "downloads": int(raw.get("downloads") or 0),
                "likes": int(raw.get("likes") or 0),
                "last_modified": str(raw.get("lastModified", "")).strip(),
                "mmproj_artifact_name": mmproj_artifact_name,
                "mmproj_download_url": mmproj_url,
                "mmproj_size_bytes": int(mmproj_size_bytes or 0),
                "mmproj_sha256": "",
                "sha256": "",
            })
        return items

    def normalize_remote_model_entry(
        self,
        raw: dict[str, Any],
        *,
        size_bytes_override: int = 0,
    ) -> dict[str, Any] | None:
        repo_id = str(raw.get("id", "")).strip()
        if not repo_id:
            return None
        siblings = raw.get("siblings", [])
        if not isinstance(siblings, list):
            return None

        gguf_names = sorted(
            name
            for name in (
                str(item.get("rfilename", "")).strip()
                for item in siblings
                if isinstance(item, dict)
            )
            if name.endswith(".gguf") and "mmproj" not in name.lower()
        )
        if not gguf_names:
            return None

        artifact_name = gguf_names[0]
        mmproj_names = sorted(name for name in (
            str(item.get("rfilename", "")).strip()
            for item in siblings
            if isinstance(item, dict)
        ) if name.endswith(".gguf") and "mmproj" in name.lower())
        mmproj_artifact_name = mmproj_names[0] if mmproj_names else ""
        quant_match = re.search(r"-(Q[^.]+)\.gguf$", artifact_name, re.IGNORECASE)
        quant = quant_match.group(1) if quant_match else ""
        gguf_meta = raw.get("gguf", {})
        architecture = str(gguf_meta.get("architecture", "")).strip() if isinstance(gguf_meta, dict) else ""
        context_value = ""
        if isinstance(gguf_meta, dict) and gguf_meta.get("context_length") is not None:
            context_value = str(gguf_meta.get("context_length"))

        size_bytes = int(size_bytes_override or 0)
        source_url = f"https://huggingface.co/{repo_id}"
        resolved_url = f"{source_url}/resolve/main/{urllib.parse.quote(artifact_name)}"
        mmproj_url = f"{source_url}/resolve/main/{urllib.parse.quote(mmproj_artifact_name)}" if mmproj_artifact_name else ""
        return {
            "repo_id": repo_id,
            "artifact_name": artifact_name,
            "alias": self.sanitize_alias(artifact_name),
            "download_url": resolved_url,
            "source_url": source_url,
            "quant": quant,
            "architecture": architecture,
            "context": context_value,
            "size_bytes": size_bytes,
            "size_human": self.human_bytes(size_bytes),
            "gated": "yes" if bool(raw.get("gated")) else "no",
            "private": "yes" if bool(raw.get("private")) else "no",
            "downloads": int(raw.get("downloads") or 0),
            "likes": int(raw.get("likes") or 0),
            "last_modified": str(raw.get("lastModified", "")).strip(),
            "mmproj_artifact_name": mmproj_artifact_name,
            "mmproj_download_url": mmproj_url,
            "mmproj_size_bytes": 0,
            "mmproj_sha256": "",
            "sha256": "",
        }

    def annotate_remote_models(
        self,
        items: list[dict[str, Any]],
        host_capability: dict[str, Any],
    ) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        for item in items:
            entry = dict(item)
            size_bytes = int(entry.get("size_bytes") or 0)
            entry["size_human"] = self.human_bytes(size_bytes)
            estimate = self.compatibility_estimate(
                size_bytes=size_bytes,
                host_capability=host_capability,
                context=str(entry.get("context", "")),
                device=str(entry.get("device", "")),
            )
            entry.update(estimate)
            annotated.append(entry)
        return annotated

    def remote_models_from_huggingface(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        encoded_query = urllib.parse.quote(query)
        limit = max(1, min(int(limit or 30), 60))
        url = f"https://huggingface.co/api/models?search={encoded_query}&limit={limit}&full=1"
        headers = {"User-Agent": "llama-model-manager/3"}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except Exception as exc:
            raise RuntimeError(f"Remote search failed: {exc}") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Remote search returned invalid JSON") from exc
        return payload if isinstance(payload, list) else []

    def search_remote_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Fetch and persist a remote-model search cache, returning an annotated store."""
        query = str(payload.get("query", "")).strip()
        limit = int(payload.get("limit") or 30)
        refresh = bool(payload.get("refresh"))
        cache_ttl_seconds = int(payload.get("cache_ttl_seconds") or 10 * 60)
        if self.demo:
            store = self.normalize_items_store(self.remote_models_file, default_remote_models_store())
            store["items"] = self.annotate_remote_models(
                [item for item in store.get("items", []) if isinstance(item, dict)],
                self.read_host_capability_store({}),
            )
            return store

        if not query:
            store = self.normalize_items_store(self.remote_models_file, default_remote_models_store())
            store["items"] = self.annotate_remote_models(
                [item for item in store.get("items", []) if isinstance(item, dict)],
                self.read_host_capability_store({}),
            )
            return store

        if not refresh and self.remote_models_file.exists():
            store = self.normalize_items_store(self.remote_models_file, default_remote_models_store())
            store_query = str(store.get("query", "")).strip()
            if store_query == query:
                try:
                    age_seconds = max(0.0, time.time() - self.remote_models_file.stat().st_mtime)
                except OSError:
                    age_seconds = None
                if age_seconds is not None and age_seconds < max(cache_ttl_seconds, 0):
                    host_capability = self.read_host_capability_store({})
                    store_items = [item for item in store.get("items", []) if isinstance(item, dict)]
                    return {
                        **store,
                        "items": self.annotate_remote_models(store_items, host_capability),
                    }

        raw_items = self.remote_models_from_huggingface(query, limit=limit)
        flattened: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            for item in self.normalize_remote_model_artifacts(raw):
                key = (str(item.get("repo_id", "")), str(item.get("artifact_name", "")))
                if not key[0] or not key[1] or key in seen:
                    continue
                seen.add(key)
                flattened.append(item)
            if len(flattened) >= 200:
                break

        store = {
            "schema_version": PHASE0_SCHEMA_VERSION,
            "provider": "huggingface",
            "query": query,
            "fetched_at": self.iso_now(),
            "items": flattened,
        }
        self.write_json_store(self.remote_models_file, store)
        host_capability = self.read_host_capability_store({})
        return {
            **store,
            "items": self.annotate_remote_models(flattened, host_capability),
        }

    def remote_items_index(self, store: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in store.get("items", []):
            if not isinstance(item, dict):
                continue
            repo_id = str(item.get("repo_id", "")).strip()
            artifact_name = str(item.get("artifact_name", "")).strip()
            if repo_id and artifact_name:
                index[(repo_id, artifact_name)] = item
        return index

    def ensure_destination_root(self, raw_root: str) -> Path:
        root = Path(raw_root or self.discovery_root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    def remote_repo_path(self, destination_root: Path, repo_id: str) -> Path:
        parts = [part for part in repo_id.split("/") if part]
        return destination_root / "huggingface" / Path(*parts)

    def upsert_download_job(self, job: dict[str, Any]) -> dict[str, Any]:
        # Hold the lock across lookup + create + persist to avoid duplicate workers/races.
        # Scheduling/enqueue is intentionally handled by the lifecycle callers.
        with self.download_lock:
            job = self.annotate_job_resume_state(job)
            store = self.read_download_jobs_store()
            items = [item for item in store.get("items", []) if isinstance(item, dict)]
            updated = False
            for index, existing in enumerate(items):
                if str(existing.get("id", "")) == str(job.get("id", "")):
                    merged = {**existing, **job}
                    terminal = {"completed", "failed", "cancelled"}
                    existing_status = str(existing.get("status", "")).strip()
                    merged_status = str(merged.get("status", "")).strip()
                    if existing_status in terminal and merged_status not in terminal:
                        # Once a job is terminal, do not allow worker progress updates to revert it.
                        merged["status"] = existing_status
                        merged["completed_at"] = str(existing.get("completed_at", "")).strip()
                        existing_error = str(existing.get("error", "")).strip()
                        if existing_error:
                            merged["error"] = existing_error
                    if bool(existing.get("cancel_requested")):
                        merged["cancel_requested"] = True
                    items[index] = merged
                    updated = True
                    break
            if not updated:
                items.insert(0, job)
            store["items"] = items[:24]
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return job

    def _download_cancel_event(self, job_id: str, *, create: bool = False) -> threading.Event | None:
        with self.download_lock:
            event = self.download_cancel_events.get(job_id)
            if event is None and create:
                event = threading.Event()
                self.download_cancel_events[job_id] = event
        return event

    def _register_download_controls(
        self,
        job_id: str,
        *,
        thread: threading.Thread,
        event: threading.Event | None = None,
    ) -> threading.Event:
        with self.download_lock:
            if event is None:
                event = self.download_cancel_events.get(job_id)
            if event is None:
                event = threading.Event()
            self.download_threads[job_id] = thread
            self.download_cancel_events[job_id] = event
        return event

    def _clear_download_controls(self, job_id: str) -> None:
        with self.download_lock:
            self.download_threads.pop(job_id, None)
            self.download_cancel_events.pop(job_id, None)

    def _alive_download_thread_count(self) -> int:
        with self.download_lock:
            # A Thread is not "alive" until it has been started. We register workers under the lock and
            # start them after releasing it, so avoid evicting not-yet-started threads here.
            stale = [
                job_id
                for job_id, worker in self.download_threads.items()
                if worker.ident is not None and not worker.is_alive()
            ]
            for job_id in stale:
                self.download_threads.pop(job_id, None)
                self.download_cancel_events.pop(job_id, None)
            return len(self.download_threads)

    def _schedule_downloads(self) -> None:
        workers_to_start: list[threading.Thread] = []
        with self.download_lock:
            if self.download_queue_paused:
                return
            slots = max(self.max_active_downloads - self._alive_download_thread_count(), 0)
            if slots <= 0:
                return
            store = self.read_download_jobs_store()
            for item in store.get("items", []):
                if slots <= 0:
                    break
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id", "")).strip()
                if not job_id or str(item.get("status", "")) != "queued":
                    continue
                if job_id in self.download_threads:
                    continue
                worker = threading.Thread(target=self.download_remote_model_job, args=(job_id,), daemon=True)
                self._register_download_controls(job_id, thread=worker)
                workers_to_start.append(worker)
                slots -= 1
        for worker in workers_to_start:
            worker.start()

    def set_download_queue_paused(self, paused: bool) -> dict[str, Any]:
        with self.download_lock:
            self.download_queue_paused = paused
            self.write_download_policy_store()
        if not paused:
            self._schedule_downloads()
        return self.download_policy_summary(self.read_download_jobs_store())

    def write_download_policy_store(self) -> None:
        self.write_json_store(
            self.download_policy_file,
            {
                "schema_version": PHASE0_SCHEMA_VERSION,
                "updated_at": self.iso_now(),
                "queue_paused": self.download_queue_paused,
                "max_active_downloads": self.max_active_downloads,
            },
        )

    def set_max_active_downloads(self, value: int) -> dict[str, Any]:
        with self.download_lock:
            self.max_active_downloads = max(1, int(value))
            self.write_download_policy_store()
        self._schedule_downloads()
        return self.download_policy_summary(self.read_download_jobs_store())

    def pause_download_queue(self) -> dict[str, Any]:
        return self.set_download_queue_paused(True)

    def resume_download_queue(self) -> dict[str, Any]:
        return self.set_download_queue_paused(False)

    def remove_queued_download_job(self, job_id: str) -> dict[str, Any]:
        with self.download_lock:
            store = self.read_download_jobs_store()
            job = self._find_download_job_from_store(store, job_id)
            if job is None:
                raise ValueError("Download job not found")
            if str(job.get("status", "")) != "queued":
                raise ValueError("Only queued download jobs can be removed")
            items = [
                item for item in store.get("items", [])
                if not (isinstance(item, dict) and str(item.get("id", "")) == job_id)
            ]
            store["items"] = items
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        self._schedule_downloads()
        return job

    def clear_queued_download_jobs(self) -> dict[str, Any]:
        removed: list[str] = []
        with self.download_lock:
            store = self.read_download_jobs_store()
            kept: list[dict[str, Any]] = []
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("status", "")) == "queued":
                    removed.append(str(item.get("id", "")))
                    continue
                kept.append(item)
            store["items"] = kept
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return {
            "removed": removed,
        }

    def prioritize_queued_download_job(self, job_id: str) -> dict[str, Any]:
        with self.download_lock:
            store = self.read_download_jobs_store()
            items = [item for item in store.get("items", []) if isinstance(item, dict)]
            target = next((item for item in items if str(item.get("id", "")) == job_id), None)
            if target is None:
                raise ValueError("Download job not found")
            if str(target.get("status", "")) != "queued":
                raise ValueError("Only queued download jobs can be prioritized")

            prioritized: list[dict[str, Any]] = []
            inserted = False
            for item in items:
                if str(item.get("id", "")) == job_id:
                    continue
                if not inserted and str(item.get("status", "")) == "queued":
                    prioritized.append(target)
                    inserted = True
                prioritized.append(item)
            if not inserted:
                prioritized.append(target)
            store["items"] = prioritized
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return target

    def deprioritize_queued_download_job(self, job_id: str) -> dict[str, Any]:
        with self.download_lock:
            store = self.read_download_jobs_store()
            items = [item for item in store.get("items", []) if isinstance(item, dict)]
            target_index = next((index for index, item in enumerate(items) if str(item.get("id", "")) == job_id), -1)
            if target_index < 0:
                raise ValueError("Download job not found")
            target = items[target_index]
            if str(target.get("status", "")) != "queued":
                raise ValueError("Only queued download jobs can be deprioritized")
            next_queued_index = next(
                (
                    index for index in range(target_index + 1, len(items))
                    if str(items[index].get("status", "")) == "queued"
                ),
                -1,
            )
            if next_queued_index >= 0:
                items[target_index], items[next_queued_index] = items[next_queued_index], items[target_index]
                store["items"] = items
                store["updated_at"] = self.iso_now()
                self.write_download_jobs_store(store)
        return target

    def _find_download_job_from_store(self, store: dict[str, Any], job_id: str) -> dict[str, Any] | None:
        for item in store.get("items", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "")) == job_id:
                return item
        return None

    def find_download_job(self, job_id: str) -> dict[str, Any] | None:
        with self.download_lock:
            return self._find_download_job_from_store(self.read_download_jobs_store(), job_id)

    def active_download_for(self, repo_id: str, artifact_name: str) -> dict[str, Any] | None:
        with self.download_lock:
            store = self.read_download_jobs_store()
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("repo_id", "")) != repo_id or str(item.get("artifact_name", "")) != artifact_name:
                    continue
                if str(item.get("status", "")) in {"queued", "running"}:
                    return item
        return None

    def is_download_cancelled(self, job_id: str) -> bool:
        with self.download_lock:
            event = self.download_cancel_events.get(job_id)
        if event is not None and event.is_set():
            return True
        item = self.find_download_job(job_id)
        if item is None:
            return True
        return str(item.get("status", "")).strip() == "cancelled"

    def partial_bytes(self, job: dict[str, Any]) -> int:
        partial_path = Path(str(job.get("partial_path", "")))
        try:
            if partial_path.is_file():
                return partial_path.stat().st_size
        except OSError:
            return 0
        return 0

    def annotate_job_resume_state(self, job: dict[str, Any]) -> dict[str, Any]:
        partial_bytes = self.partial_bytes(job)
        status = str(job.get("status", "")).strip()
        job["partial_bytes"] = partial_bytes
        job["resume_available"] = status in {"cancelled", "failed"} and partial_bytes > 0
        return job

    def cleanup_stale_partial_downloads(self, *, max_age_seconds: int = 7 * 24 * 60 * 60) -> dict[str, Any]:
        now = time.time()
        removed: list[str] = []
        kept: list[str] = []
        with self.download_lock:
            store = self.read_download_jobs_store()
            items: list[dict[str, Any]] = []
            active_partials = {
                str(item.get("partial_path", ""))
                for item in store.get("items", [])
                if isinstance(item, dict) and str(item.get("status", "")) in {"queued", "running"}
            }
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                job = dict(item)
                status = str(job.get("status", "")).strip()
                partial_path_text = str(job.get("partial_path", "")).strip()
                partial_path = Path(partial_path_text) if partial_path_text else None
                if status in {"cancelled", "failed"} and partial_path is not None and partial_path_text not in active_partials:
                    try:
                        if partial_path.is_file() and now - partial_path.stat().st_mtime >= max_age_seconds:
                            partial_path.unlink()
                            removed.append(partial_path_text)
                    except OSError:
                        kept.append(partial_path_text)
                items.append(self.annotate_job_resume_state(job))
            store["items"] = items
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return {
            "removed": removed,
            "kept": kept,
        }

    def cleanup_duplicate_completed_job_records(self) -> dict[str, Any]:
        removed: list[str] = []
        kept: list[str] = []
        seen_paths: set[str] = set()
        with self.download_lock:
            store = self.read_download_jobs_store()
            items: list[dict[str, Any]] = []
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                job = dict(item)
                local_path = str(job.get("local_path", "")).strip()
                if str(job.get("status", "")) == "completed" and local_path:
                    if local_path in seen_paths:
                        removed.append(str(job.get("id", "")))
                        continue
                    seen_paths.add(local_path)
                    kept.append(str(job.get("id", "")))
                items.append(self.annotate_job_resume_state(job))
            store["items"] = items
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return {
            "removed": removed,
            "kept": kept,
        }

    def delete_orphaned_download_artifacts(self, paths: list[str] | None = None) -> dict[str, Any]:
        removed: list[str] = []
        skipped: list[str] = []
        with self.download_lock:
            store = self.read_download_jobs_store()
            storage = self.download_storage_summary(store)
            orphaned_paths = {str(item.get("path", "")) for item in storage.get("orphaned_artifacts", [])}
            requested_paths = orphaned_paths if paths is None else {str(path) for path in paths}
            for path_text in sorted(requested_paths):
                if path_text not in orphaned_paths:
                    skipped.append(path_text)
                    continue
                try:
                    path = Path(path_text)
                    if path.is_file():
                        path.unlink()
                        removed.append(path_text)
                    else:
                        skipped.append(path_text)
                except OSError:
                    skipped.append(path_text)
        return {
            "removed": removed,
            "skipped": skipped,
        }

    def recover_stale_download_jobs(self) -> dict[str, Any]:
        recovered: list[str] = []
        with self.download_lock:
            store = self.read_download_jobs_store()
            items: list[dict[str, Any]] = []
            for item in store.get("items", []):
                if not isinstance(item, dict):
                    continue
                job = dict(item)
                job_id = str(job.get("id", "")).strip()
                status = str(job.get("status", "")).strip()
                worker = self.download_threads.get(job_id)
                if status == "running" and (worker is None or not worker.is_alive()):
                    job.update({
                        "status": "failed",
                        "completed_at": self.iso_now(),
                        "error": "Download worker is not active. Resume or retry this job.",
                    })
                    self._clear_download_controls(job_id)
                    recovered.append(job_id)
                items.append(self.annotate_job_resume_state(job))
            store["items"] = items
            store["updated_at"] = self.iso_now()
            self.write_download_jobs_store(store)
        return {
            "recovered": recovered,
        }

    def streamed_download(self, url: str, destination: Path, job: dict[str, Any]) -> dict[str, Any]:
        job_id = str(job.get("id", ""))
        resume_from = int(job.get("resume_from_bytes") or 0)
        headers = {"User-Agent": "llama-model-manager/3"}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            total = int(response.headers.get("Content-Length") or 0)
            appending = resume_from > 0 and int(getattr(response, "status", 200)) == 206
            bytes_downloaded = resume_from if appending else 0
            if appending:
                job["bytes_total"] = resume_from + total
                mode = "ab"
                job["reuse_reason"] = f"resumed partial download from {resume_from} bytes"
            else:
                job["bytes_total"] = total
                mode = "wb"
                if resume_from > 0:
                    job["reuse_reason"] = "remote server ignored range resume; restarted download"
            last_flush = time.monotonic()
            with destination.open(mode) as handle:
                while True:
                    if self.is_download_cancelled(job_id):
                        raise RuntimeError("download cancelled")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    bytes_downloaded += len(chunk)
                    job["bytes_downloaded"] = bytes_downloaded
                    expected_total = int(job.get("bytes_total") or 0)
                    if expected_total > 0:
                        job["progress"] = round(min(bytes_downloaded / expected_total, 1.0), 4)
                    now = time.monotonic()
                    if now - last_flush >= 0.1:
                        self.upsert_download_job(self.annotate_job_resume_state(job))
                        last_flush = now
            job["bytes_downloaded"] = bytes_downloaded
            job["bytes_total"] = total or bytes_downloaded
            if appending:
                job["bytes_total"] = max(int(job.get("bytes_total") or 0), bytes_downloaded)
            job["progress"] = 1.0 if bytes_downloaded else 0.0
        return job

    def maybe_reuse_existing_download(self, *, destination_path: Path, expected_size: int) -> bool:
        if not destination_path.exists():
            return False
        if expected_size > 0 and destination_path.stat().st_size != expected_size:
            return False
        return True

    def sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def verify_downloaded_artifact(self, path: Path, *, expected_size: int = 0, expected_sha256: str = "") -> str:
        if expected_size > 0 and path.stat().st_size != expected_size:
            raise ValueError(f"size mismatch for {path.name}: expected {expected_size} bytes, got {path.stat().st_size}")
        if expected_sha256:
            actual_sha256 = self.sha256_file(path)
            if actual_sha256 != expected_sha256:
                raise ValueError(f"sha256 mismatch for {path.name}")
            return "sha256 verified"
        if expected_size > 0:
            return "size verified"
        return "upstream checksum unavailable"

    def download_remote_model_job(self, job_id: str) -> None:
        store = self.read_download_jobs_store()
        job = self._find_download_job_from_store(store, job_id)
        if job is None:
            self._clear_download_controls(job_id)
            return
        status = str(job.get("status", "")).strip()
        if status != "queued":
            self._clear_download_controls(job_id)
            self._schedule_downloads()
            return
        if bool(job.get("cancel_requested")):
            job.update({
                "status": "cancelled",
                "completed_at": self.iso_now(),
                "error": "Download was cancelled by operator.",
            })
            self.upsert_download_job(job)
            self._clear_download_controls(job_id)
            self._schedule_downloads()
            return

        destination_path = Path(str(job.get("destination_path", "")))
        partial_path = Path(str(job.get("partial_path", "")))
        mmproj_destination_path = Path(str(job.get("mmproj_destination_path", ""))) if str(job.get("mmproj_destination_path", "")) else None
        mmproj_partial_path = Path(str(job.get("mmproj_partial_path", ""))) if str(job.get("mmproj_partial_path", "")) else None
        primary_reused = False
        mmproj_reused = False
        try:
            job.update({
                "status": "running",
                "started_at": self.iso_now(),
                "error": "",
            })
            self.upsert_download_job(job)

            reused_existing = self.maybe_reuse_existing_download(
                destination_path=destination_path,
                expected_size=int(job.get("bytes_total") or 0),
            )
            if reused_existing:
                primary_reused = True
                job.update({
                    "bytes_downloaded": int(job.get("bytes_total") or destination_path.stat().st_size),
                    "progress": 1.0,
                    "reuse_reason": "primary file already existed at destination",
                })
            else:
                partial_path.parent.mkdir(parents=True, exist_ok=True)
                self.streamed_download(str(job.get("download_url", "")), partial_path, job)
                partial_path.replace(destination_path)

            if self.is_download_cancelled(job_id):
                raise RuntimeError("download cancelled")

            job["verification_summary"] = self.verify_downloaded_artifact(
                destination_path,
                expected_size=int(job.get("bytes_total") or 0),
                expected_sha256=str(job.get("sha256", "")),
            )

            mmproj_path = ""
            if mmproj_destination_path is not None and mmproj_partial_path is not None:
                mmproj_expected_size = int(job.get("mmproj_bytes_total") or 0)
                if self.maybe_reuse_existing_download(destination_path=mmproj_destination_path, expected_size=mmproj_expected_size):
                    mmproj_reused = True
                    mmproj_path = str(mmproj_destination_path)
                    job["mmproj_reuse_reason"] = "mmproj file already existed at destination"
                else:
                    mmproj_partial_path.parent.mkdir(parents=True, exist_ok=True)
                    mmproj_job = {
                        **job,
                        "bytes_downloaded": int(job.get("bytes_downloaded") or 0),
                        "bytes_total": mmproj_expected_size,
                    }
                    if self.is_download_cancelled(job_id):
                        raise RuntimeError("download cancelled")
                    self.streamed_download(str(job.get("mmproj_download_url", "")), mmproj_partial_path, mmproj_job)
                    mmproj_partial_path.replace(mmproj_destination_path)
                    mmproj_path = str(mmproj_destination_path)
                if mmproj_path:
                    if self.is_download_cancelled(job_id):
                        raise RuntimeError("download cancelled")
                    job["mmproj_verification_summary"] = self.verify_downloaded_artifact(
                        Path(mmproj_path),
                        expected_size=int(job.get("mmproj_bytes_total") or 0),
                        expected_sha256=str(job.get("mmproj_sha256", "")),
                    )

            imported_model = self.save_model(
                {
                    "alias": str(job.get("alias", "")),
                    "path": str(destination_path),
                    "mmproj": mmproj_path,
                    "notes": f"Imported from {job.get('repo_id', '')}",
                }
            )
            job.update({
                "status": "completed",
                "completed_at": self.iso_now(),
                "local_path": str(destination_path),
                "mmproj_local_path": mmproj_path,
                "imported_alias": imported_model.get("alias", ""),
                "notes": imported_model.get("notes", ""),
            })
            self._clear_download_controls(job_id)
            self.upsert_download_job(job)
        except Exception as exc:
            was_cancelled = self.is_download_cancelled(job_id)
            if was_cancelled:
                job.update({
                    "cancel_requested": True,
                    "status": "cancelled",
                    "completed_at": self.iso_now(),
                    "error": "Download was cancelled by operator.",
                })
            else:
                job.update({
                    "status": "failed",
                    "completed_at": self.iso_now(),
                    "error": str(exc),
                })
            try:
                if not was_cancelled and partial_path.exists():
                    partial_path.unlink()
                if mmproj_partial_path is not None and mmproj_partial_path.exists():
                    mmproj_partial_path.unlink()
                if not primary_reused and destination_path.exists():
                    destination_path.unlink()
                if not mmproj_reused and mmproj_destination_path is not None and mmproj_destination_path.exists():
                    mmproj_destination_path.unlink()
            except OSError:
                pass
            self._clear_download_controls(job_id)
            self.upsert_download_job(job)
        finally:
            self._clear_download_controls(job_id)
            self._schedule_downloads()

    def start_remote_download(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.demo:
            return {
                "id": "demo-job",
                "status": "queued",
                "repo_id": str(payload.get("repo_id", "")),
                "artifact_name": str(payload.get("artifact_name", "")),
                "destination_root": str(payload.get("destination_root", self.discovery_root)),
            }

        with self.download_lock:
            return self._start_remote_download_locked(payload)

    def _start_remote_download_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Lock-scoped implementation for start/retry/resume to keep enqueue atomic."""
        repo_id = str(payload.get("repo_id", "")).strip()
        artifact_name = str(payload.get("artifact_name", "")).strip()
        if not repo_id or not artifact_name:
            raise ValueError("Remote repo and artifact are required")
        parts = [part for part in repo_id.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("Remote repo identifier is invalid")
        if (
            artifact_name in {".", ".."}
            or "/" in artifact_name
            or "\\" in artifact_name
            or Path(artifact_name).name != artifact_name
        ):
            raise ValueError("Remote artifact name is invalid")

        remote_store = self.normalize_items_store(self.remote_models_file, default_remote_models_store())
        remote_item = self.remote_items_index(remote_store).get((repo_id, artifact_name))
        if remote_item is None:
            raise ValueError("Remote model is not available in the current search cache. Search again before downloading.")

        # Serialize this lookup/creation window to prevent duplicate starts for the same artifact.
        existing = self.active_download_for(repo_id, artifact_name)
        if existing is not None:
            return existing

        destination_root = self.ensure_destination_root(str(payload.get("destination_root", self.discovery_root)))
        destination_dir = self.remote_repo_path(destination_root, repo_id)
        job_id = uuid4().hex[:12]
        destination_path = destination_dir / artifact_name
        resume_partial_path = str(payload.get("resume_partial_path", "")).strip()
        if resume_partial_path:
            partial_path = Path(resume_partial_path).expanduser()
            if not partial_path.is_absolute():
                raise ValueError("Resume path must be absolute")
            if not partial_path.name.endswith(".part"):
                raise ValueError("Resume path must point at a .part file")
            dest_real = Path(os.path.realpath(str(destination_dir)))
            candidate_real = Path(os.path.realpath(str(partial_path)))
            try:
                candidate_real.relative_to(dest_real)
            except ValueError as exc:
                raise ValueError("Resume path must be inside the destination directory") from exc
        else:
            partial_path = destination_dir / f"{artifact_name}.{job_id}.part"
        resume_from_bytes = 0
        if resume_partial_path:
            try:
                resume_from_bytes = partial_path.stat().st_size if partial_path.is_file() else 0
            except OSError:
                resume_from_bytes = 0
        mmproj_artifact_name = str(remote_item.get("mmproj_artifact_name", "")).strip()
        if (
            mmproj_artifact_name
            and (
                mmproj_artifact_name in {".", ".."}
                or "/" in mmproj_artifact_name
                or "\\" in mmproj_artifact_name
                or Path(mmproj_artifact_name).name != mmproj_artifact_name
            )
        ):
            mmproj_artifact_name = ""
        mmproj_destination_path = destination_dir / mmproj_artifact_name if mmproj_artifact_name else None
        mmproj_partial_path = destination_dir / f"{mmproj_artifact_name}.{job_id}.part" if mmproj_artifact_name else None
        alias = str(remote_item.get("alias") or self.sanitize_alias(artifact_name))
        bytes_total = int(remote_item.get("size_bytes") or 0)

        # Keep job creation + upsert + scheduler handoff atomic under the same lock for state consistency.
        job = {
            "id": job_id,
            "provider": "huggingface",
            "repo_id": repo_id,
            "artifact_name": artifact_name,
            "alias": alias,
            "download_url": str(remote_item.get("download_url", "")),
            "source_url": str(remote_item.get("source_url", "")),
            "sha256": str(remote_item.get("sha256", "")),
            "destination_root": str(destination_root),
            "destination_path": str(destination_path),
            "partial_path": str(partial_path),
            "mmproj_artifact_name": mmproj_artifact_name,
            "mmproj_download_url": str(remote_item.get("mmproj_download_url", "")),
            "mmproj_destination_path": str(mmproj_destination_path) if mmproj_destination_path else "",
            "mmproj_partial_path": str(mmproj_partial_path) if mmproj_partial_path else "",
            "mmproj_bytes_total": int(remote_item.get("mmproj_size_bytes") or 0),
            "mmproj_sha256": str(remote_item.get("mmproj_sha256", "")),
            "bytes_downloaded": resume_from_bytes,
            "bytes_total": bytes_total,
            "progress": round(min(resume_from_bytes / bytes_total, 1.0), 4) if bytes_total > 0 else 0.0,
            "status": "queued",
            "created_at": self.iso_now(),
            "cancel_requested": False,
            "resume_from_bytes": resume_from_bytes,
            "resume_source_job_id": str(payload.get("resume_source_job_id", "")).strip(),
            "imported_alias": "",
            "reuse_reason": "",
            "mmproj_reuse_reason": "",
            "verification_summary": "",
            "mmproj_verification_summary": "",
            "error": "",
            "local_path": "",
            "mmproj_local_path": "",
            "notes": "",
        }
        self.upsert_download_job(job)
        self._schedule_downloads()
        return job

    def cancel_download_job(self, job_id: str) -> dict[str, Any]:
        if self.demo:
            return {
                "id": str(job_id),
                "status": "cancelled",
                "repo_id": "",
                "artifact_name": "",
                "error": "",
            }

        with self.download_lock:
            store = self.read_download_jobs_store()
            job = self._find_download_job_from_store(store, job_id)
            if job is None:
                raise ValueError("Download job not found")

            status = str(job.get("status", "")).strip()
            if status in {"completed", "failed", "cancelled"}:
                return job

            terminal_view = {
                **job,
                "cancel_requested": True,
                "status": "cancelled",
                "error": "Download was cancelled by operator.",
                "completed_at": self.iso_now(),
            }
            if status == "queued" and job_id not in self.download_threads:
                self.upsert_download_job(terminal_view)
                self._schedule_downloads()
                return terminal_view
            # For running jobs, persist the terminal view immediately so API responses match stored state.
            # Worker progress updates must not be able to revert this terminal status (enforced in upsert).
            self.upsert_download_job(terminal_view)
            event = self._download_cancel_event(job_id, create=True)
            if event is not None:
                event.set()
            return terminal_view

    def retry_download_job(self, job_id: str) -> dict[str, Any]:
        with self.download_lock:
            store = self.read_download_jobs_store()
            job = self._find_download_job_from_store(store, job_id)
            if job is None:
                raise ValueError("Download job not found")

            status = str(job.get("status", "")).strip()
            if status in {"queued", "running"}:
                return job
            if bool(job.get("cancel_requested")) and (job_id in self.download_threads or job_id in self.download_cancel_events):
                return job

            repo_id = str(job.get("repo_id", "")).strip()
            artifact_name = str(job.get("artifact_name", "")).strip()
            if not repo_id or not artifact_name:
                raise ValueError("Download snapshot missing repo/artifact identifiers")

            return self._start_remote_download_locked(self._download_retry_payload(
                repo_id=repo_id,
                artifact_name=artifact_name,
                destination_root=str(job.get("destination_root", self.discovery_root)),
            ))

    def _download_retry_payload(
        self,
        *,
        repo_id: str,
        artifact_name: str,
        destination_root: str,
        resume_partial_path: str = "",
        resume_source_job_id: str = "",
    ) -> dict[str, Any]:
        """Build a normalized payload for starting a (re)queued or resumed download."""
        payload: dict[str, Any] = {
            "repo_id": repo_id,
            "artifact_name": artifact_name,
            "destination_root": destination_root,
        }
        if resume_partial_path:
            payload["resume_partial_path"] = resume_partial_path
        if resume_source_job_id:
            payload["resume_source_job_id"] = resume_source_job_id
        return payload

    def resume_download_job(self, job_id: str) -> dict[str, Any]:
        with self.download_lock:
            store = self.read_download_jobs_store()
            job = self._find_download_job_from_store(store, job_id)
            if job is None:
                raise ValueError("Download job not found")

            status = str(job.get("status", "")).strip()
            if status in {"queued", "running"}:
                return job
            if job_id in self.download_threads or job_id in self.download_cancel_events:
                return job

            partial_path = Path(str(job.get("partial_path", "")))
            try:
                partial_bytes = partial_path.stat().st_size if partial_path.is_file() else 0
            except OSError:
                partial_bytes = 0
            if partial_bytes <= 0:
                raise ValueError("No resumable partial download is available")

            repo_id = str(job.get("repo_id", "")).strip()
            artifact_name = str(job.get("artifact_name", "")).strip()
            if not repo_id or not artifact_name:
                raise ValueError("Download snapshot missing repo/artifact identifiers")

            return self._start_remote_download_locked(self._download_retry_payload(
                repo_id=repo_id,
                artifact_name=artifact_name,
                destination_root=str(job.get("destination_root", self.discovery_root)),
                resume_partial_path=str(partial_path),
                resume_source_job_id=job_id,
            ))

    def integration_state(self, defaults: dict[str, str], current: dict[str, str], mode: dict[str, str]) -> dict[str, Any]:
        current_model_name = Path(current.get("model", "")).name if current.get("model") else ""
        current_alias = current.get("alias", "") if current.get("alias") and current.get("alias") != "custom" else ""
        opencode_config = self.load_json_file(self.opencode_config_file)
        opencode_provider = opencode_config.get("provider", {}).get("llamacpp", {}) if isinstance(opencode_config.get("provider"), dict) else {}
        opencode_options = opencode_provider.get("options", {}) if isinstance(opencode_provider.get("options"), dict) else {}
        opencode_timeout = str(opencode_options.get("timeout", "")) if opencode_options.get("timeout") is not None else ""
        opencode_chunk_timeout = str(opencode_options.get("chunkTimeout", "")) if opencode_options.get("chunkTimeout") is not None else ""
        if opencode_timeout == "7200000" and opencode_chunk_timeout == "300000":
            opencode_preset = "long-run"
        elif opencode_timeout == "1800000" and opencode_chunk_timeout == "60000":
            opencode_preset = "balanced"
        elif opencode_timeout or opencode_chunk_timeout:
            opencode_preset = "custom"
        else:
            opencode_preset = ""
        opencode_note = ""
        if opencode_preset == "long-run":
            configured_mode = mode.get("configured_mode", "") if isinstance(mode, dict) else ""
            if configured_mode != "single-client":
                opencode_note = "single-client recommended for long local reasoning sessions"
            else:
                opencode_note = "long-run preset active"
        openclaw_profile = defaults.get("OPENCLAW_PROFILE", "").strip() or "main"
        if openclaw_profile == "main":
            openclaw_config_file = self.home / ".openclaw" / "openclaw.json"
        else:
            openclaw_config_file = self.home / f".openclaw-{openclaw_profile}" / "openclaw.json"
        claude_gateway_status: dict[str, str] = {}
        if not self.demo:
            try:
                claude_gateway_status = self.parse_key_values(self.run_cli("claude-gateway", "status"))
            except Exception:
                claude_gateway_status = {}
        claude_model_id = defaults.get("CLAUDE_MODEL_ID", "").strip() or current_alias
        claude_base_url = defaults.get("CLAUDE_BASE_URL", "").strip() or f"http://{defaults.get('CLAUDE_GATEWAY_HOST', '127.0.0.1')}:{defaults.get('CLAUDE_GATEWAY_PORT', '4000')}"
        glyphos_telemetry = self.glyphos_telemetry_snapshot(limit=12)
        return {
            "opencode_model": f"llamacpp/{current_model_name}" if current_model_name else "",
            "opencode_config_file": str(self.opencode_config_file),
            "opencode_config_exists": self.opencode_config_file.exists(),
            "opencode_state_file": str(self.opencode_model_state_file),
            "opencode_state_exists": self.opencode_model_state_file.exists(),
            "opencode_timeout_ms": opencode_timeout,
            "opencode_chunk_timeout_ms": opencode_chunk_timeout,
            "opencode_preset": opencode_preset,
            "opencode_note": opencode_note,
            "openclaw_model": f"llamacpp/{current_alias}" if current_alias else "",
            "openclaw_profile": openclaw_profile,
            "openclaw_sync_note": "direct llama.cpp provider",
            "openclaw_config_file": str(openclaw_config_file),
            "openclaw_config_exists": openclaw_config_file.exists(),
            "claude_settings_file": str(self.claude_settings_file),
            "claude_settings_exists": self.claude_settings_file.exists(),
            "claude_model_id": claude_model_id,
            "claude_base_url": claude_base_url,
            "claude_gateway": claude_gateway_status,
            "glyphos_config_file": str(self.glyphos_config_file),
            "glyphos_config_exists": self.glyphos_config_file.exists(),
            "glyphos_model": current_model_name,
            "glyphos_routing_preference": "llamacpp",
            "glyphos_telemetry": glyphos_telemetry,
        }

    def glyphos_telemetry_snapshot(self, *, limit: int = 10) -> dict[str, Any]:
        baseline_routing = {
            "attempts_by_target": {},
            "fallback_reason_counts": {},
            "total_attempts": 0,
            "recent_attempts": [],
        }
        snapshot: dict[str, Any] = {"available": False, "routing": baseline_routing}
        if self.demo:
            return snapshot

        # Prefer installed package import; fall back to repo-local integration path.
        integration_root = (self.app_root.parent / "integrations" / "public-glyphos-ai-compute").resolve()
        candidates: list[str] = []
        if str(integration_root) not in sys.path and integration_root.is_dir():
            candidates.append(str(integration_root))
        candidates.append("")

        last_error: Exception | None = None
        for prepend in candidates:
            try:
                if prepend:
                    sys.path.insert(0, prepend)
                from glyphos_ai.ai_compute.router import routing_telemetry_snapshot  # type: ignore
                routing = routing_telemetry_snapshot(limit=int(limit))
                if not isinstance(routing, dict):
                    routing = dict(baseline_routing)
                else:
                    routing = {**baseline_routing, **routing}
                snapshot = {"available": True, "routing": routing}
                return snapshot
            except Exception as exc:
                last_error = exc
            finally:
                if prepend:
                    try:
                        sys.path.remove(prepend)
                    except ValueError:
                        pass

        if last_error is not None:
            snapshot["error"] = str(last_error)
        return snapshot

    def sync_opencode(self, preset: str = "balanced") -> dict[str, str]:
        return self.parse_key_values(self.run_cli("sync-opencode", "--preset", preset))

    def sync_openclaw(self) -> dict[str, str]:
        return self.parse_key_values(self.run_cli("sync-openclaw"))

    def sync_claude(self) -> dict[str, str]:
        return self.parse_key_values(self.run_cli("sync-claude"))

    def sync_glyphos(self) -> dict[str, str]:
        return self.parse_key_values(self.run_cli("sync-glyphos"))

    def dashboard_service_status(self) -> dict[str, str]:
        if self.demo:
            return {
                "supported": "yes",
                "manager_reachable": "yes",
                "installable": "yes",
                "installed": "yes",
                "enabled": "yes",
                "active": "yes",
                "logs_available": "yes",
                "status": "running",
                "unit": "llama-model-web.service",
                "unit_file": str(self.home / ".config" / "systemd" / "user" / "llama-model-web.service"),
                "url": "http://127.0.0.1:8765/",
                "host": "127.0.0.1",
                "port": "8765",
                "message": "Background dashboard service is running.",
            }
        try:
            return self.parse_key_values(self.run_cli("dashboard-service", "status"))
        except Exception:
            return {
                "supported": "unknown",
                "manager_reachable": "no",
                "installed": "unknown",
                "enabled": "unknown",
                "active": "unknown",
                "status": "unavailable",
                "message": "Dashboard service status is unavailable.",
            }

    def state(self) -> dict[str, Any]:
        if self.demo:
            return {
                **DEMO_STATE,
                "demo": True,
                "meta": {
                    "home_dir": str(self.home),
                    "dashboard_service_managed": False,
                },
                "defaults": dict(DEMO_STATE["defaults"]),
                "current": dict(DEMO_STATE["current"]),
                "doctor": dict(DEMO_STATE["doctor"]),
                "mode": dict(DEMO_STATE["mode"]),
                "models": [dict(model) for model in DEMO_STATE["models"]],
                "dashboard_service": self.dashboard_service_status(),
                "remote_models": default_remote_models_store(),
                "download_jobs": default_download_jobs_store(),
                "download_storage": self.download_storage_summary(default_download_jobs_store()),
                "download_policy": self.download_policy_summary(default_download_jobs_store()),
                "runtime_profiles": default_runtime_profiles_store(),
                "validation_results": default_validation_results_store(),
                "host_capability": default_host_capability_store(),
                "registry_file": str(self.models_file),
                "registry_exists": True,
                "defaults_file": str(self.defaults_file),
                "defaults_exists": True,
                "opencode_config_file": str(self.opencode_config_file),
                "opencode_config_exists": True,
                "opencode_state_file": str(self.opencode_model_state_file),
                "opencode_state_exists": True,
                "openclaw_model": "llamacpp/qwen36-35b-q2",
                "openclaw_profile": "main",
                "openclaw_sync_note": "direct llama.cpp provider",
                "openclaw_config_file": str(self.home / ".openclaw" / "openclaw.json"),
                "openclaw_config_exists": True,
                "claude_settings_file": str(self.claude_settings_file),
                "claude_settings_exists": True,
                "claude_model_id": "qwen35-9b-q8",
                "claude_base_url": "http://127.0.0.1:4000",
                "claude_gateway": {"running": "yes", "url": "http://127.0.0.1:4000", "model_id": "qwen35-9b-q8", "log": "/var/log/claude-gateway.log", "upstream_timeout_seconds": "1800"},
                "glyphos_telemetry": {"available": False, "routing": {"attempts_by_target": {}, "fallback_reason_counts": {}, "total_attempts": 0, "recent_attempts": []}},
            }
        current = self.parse_key_values(self.run_cli("current"))
        doctor = self.parse_key_values(self.run_cli("doctor"))
        mode = self.parse_key_values(self.run_cli("mode"))
        defaults = self.defaults()
        phase0 = self.phase0_contracts(doctor)
        integration = self.integration_state(defaults, current, mode)
        api_base = f"http://{defaults['LLAMA_SERVER_HOST']}:{defaults['LLAMA_SERVER_PORT']}/v1"
        current_model_name = Path(current["model"]).name if current.get("model") else "<model>"

        return {
            "title": APP_TITLE,
            "brand": APP_BRAND,
            "demo": False,
            "meta": {
                "home_dir": str(self.home),
                "dashboard_service_managed": os.environ.get("LLAMA_MODEL_WEB_SERVICE") == "1",
            },
            "defaults": defaults,
            "current": current,
            "doctor": doctor,
            "mode": mode,
            "models": self.annotate_models_with_validation(self.read_models(), phase0["validation_results"]),
            "dashboard_service": self.dashboard_service_status(),
            **integration,
            **phase0,
            "discovery_root": self.discovery_root,
            "api_base": api_base,
            "registry_file": str(self.models_file),
            "registry_exists": self.models_file.exists(),
            "defaults_file": str(self.defaults_file),
            "defaults_exists": self.defaults_file.exists(),
        }


REMOTE_AND_DOWNLOAD_POST_ROUTES = {
    "/api/remote/search": lambda manager, payload: {
        "remote_models": manager.search_remote_models(payload),
    },
    "/api/downloads/start": lambda manager, payload: {
        "job": manager.start_remote_download(payload),
    },
    "/api/downloads/cancel": lambda manager, payload: {
        "job": manager.cancel_download_job(str(payload.get("id", ""))),
    },
    "/api/downloads/retry": lambda manager, payload: {
        "job": manager.retry_download_job(str(payload.get("id", ""))),
    },
    "/api/downloads/resume": lambda manager, payload: {
        "job": manager.resume_download_job(str(payload.get("id", ""))),
    },
    "/api/downloads/cleanup": lambda manager, payload: manager.cleanup_stale_partial_downloads(
        max_age_seconds=int(payload.get("max_age_seconds", 7 * 24 * 60 * 60))
    ),
    "/api/downloads/cleanup-duplicates": lambda manager, payload: manager.cleanup_duplicate_completed_job_records(),
    "/api/downloads/delete-orphans": lambda manager, payload: manager.delete_orphaned_download_artifacts(
        payload.get("paths") if isinstance(payload.get("paths"), list) else None
    ),
    "/api/downloads/recover": lambda manager, payload: manager.recover_stale_download_jobs(),
    "/api/downloads/pause-queue": lambda manager, payload: {
        "download_policy": manager.pause_download_queue(),
    },
    "/api/downloads/resume-queue": lambda manager, payload: {
        "download_policy": manager.resume_download_queue(),
    },
    "/api/downloads/policy": lambda manager, payload: {
        "download_policy": manager.set_max_active_downloads(
            int(payload.get("max_active_downloads", manager.max_active_downloads))
        ),
    },
    "/api/downloads/remove-queued": lambda manager, payload: {
        "job": manager.remove_queued_download_job(str(payload.get("id", ""))),
    },
    "/api/downloads/clear-queued": lambda manager, payload: manager.clear_queued_download_jobs(),
    "/api/downloads/prioritize-queued": lambda manager, payload: {
        "job": manager.prioritize_queued_download_job(str(payload.get("id", ""))),
    },
    "/api/downloads/deprioritize-queued": lambda manager, payload: {
        "job": manager.deprioritize_queued_download_job(str(payload.get("id", ""))),
    },
}


def remote_and_download_post_route_payload(path: str, manager: Manager, payload: dict[str, Any]) -> dict[str, Any] | None:
    handler = REMOTE_AND_DOWNLOAD_POST_ROUTES.get(path)
    if handler is None:
        return None
    try:
        return handler(manager, payload)
    except ValueError as exc:
        raise ValidationError("invalid_request", str(exc)) from exc


class AppHandler(BaseHTTPRequestHandler):
    manager: Manager
    web_root: Path

    def _is_local_client(self) -> bool:
        host = str(self.client_address[0]).strip()
        if not host:
            return False
        if host in {"127.0.0.1", "::1", "localhost"}:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _normalize_allowed_host(self, raw_host: str) -> str:
        return raw_host.strip().lower().strip("[]")

    def _is_allowed_client(self) -> bool:
        allowed_hosts = parse_allowed_hosts()
        if not allowed_hosts:
            return True
        host = str(self.client_address[0]).strip().lower()
        normalized_host = self._normalize_allowed_host(host)

        for allowed in allowed_hosts:
            allowed_host = self._normalize_allowed_host(allowed)
            if allowed_host in {"localhost", "127.0.0.1", "::1"} and self._is_local_client():
                return True
            if allowed_host == normalized_host:
                return True
            try:
                if ipaddress.ip_address(normalized_host) == ipaddress.ip_address(allowed_host):
                    return True
            except ValueError:
                continue

        return False

    def _request_token(self) -> str:
        token = parse_api_token()
        if not token:
            return ""
        supplied = self.headers.get("X-LLAMA-MODEL-MANAGER-TOKEN", "")
        if supplied:
            return supplied.strip()
        auth_header = self.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""

    def _authorize_api_request(self, route: str) -> None:
        if route not in {
            "/api/state",
            "/api/logs",
            "/api/dashboard-service/logs",
            "/api/claude-gateway/logs",
        }:
            if not self._is_allowed_client():
                raise ValidationError("client_not_allowed", "Client host not allowed to call the API")

        token = parse_api_token()
        if not token:
            return
        if self._is_local_client():
            return

        provided = self._request_token()
        if not provided:
            raise ValidationError("missing_api_token", "Missing or empty API token")
        if provided != token:
            raise ValidationError("invalid_api_token", "Invalid API token")

    @staticmethod
    def _route_activity_action(route: str) -> str:
        return route.split("/")[-1].replace("-", "_") or "api"

    def _response_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        if "job" in payload and isinstance(payload["job"], dict):
            summary["job_id"] = str(payload["job"].get("id", ""))
        if "remote_models" in payload and isinstance(payload["remote_models"], dict):
            summary["remote_count"] = len(payload["remote_models"].get("items", []))
        if "result" in payload and isinstance(payload["result"], dict):
            summary["result_keys"] = sorted(payload["result"].keys())
        return summary

    def _validate_post_payload(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = API_POST_PAYLOAD_SCHEMAS.get(route)
        if not schema:
            return payload

        allowed = schema.get("allowed", set())
        required = schema.get("required", set())
        int_fields = schema.get("int_fields", set())
        str_fields = schema.get("str_fields", set())

        if allowed:
            unknown = [key for key in payload if key not in allowed]
            if unknown:
                raise ValidationError("unknown_field", f"Unknown field(s) for {route}: {', '.join(sorted(unknown))}")

        for field in required:
            if field not in payload:
                raise ValidationError("missing_required_field", f"Missing required field: {field}")
            if field in str_fields:
                continue
            if str(payload.get(field, "")).strip() == "":
                raise ValidationError("missing_required_field", f"Missing required field: {field}")

        for field in str_fields:
            if field not in payload:
                continue
            value = payload.get(field)
            if not isinstance(value, str) or value.strip() == "":
                raise ValidationError("invalid_field_type", f"Field '{field}' must be a non-empty string")
            payload[field] = value.strip()

        for field in int_fields:
            if field not in payload:
                continue
            try:
                payload[field] = int(payload[field])
            except (TypeError, ValueError):
                raise ValidationError("invalid_field_type", f"Field '{field}' must be an integer")

        return payload

    def _parse_lines_query(self, raw_lines: str | None, *, default: int = 80) -> int:
        value_text = (str(raw_lines).strip() if raw_lines is not None else str(default))
        try:
            value = int(value_text)
        except ValueError as exc:
            raise ValidationError("invalid_query_param", "Query parameter 'lines' must be an integer") from exc
        if value < 0:
            raise ValidationError("invalid_query_param", "Query parameter 'lines' must be non-negative")
        return value

    def _track_api_activity(
        self,
        *,
        route: str,
        start: float,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        if os.environ.get("LLAMA_MODEL_WEB_DISABLE_ACTIVITY_LOG", "").strip().lower() in {"1", "true", "yes"}:
            return
        if not hasattr(self.manager, "record_operation_activity"):
            return
        duration_ms = (time.perf_counter() - start) * 1000.0
        action = self._route_activity_action(route)
        status = "success" if error is None else "error"
        error_code = getattr(error, "code", "") if error is not None else ""
        error_message = str(error) if error is not None else ""

        actor_source = "local" if self._is_local_client() else "remote"
        if status == "error":
            self.manager.record_operation_activity(
                route=route,
                action=action,
                actor_source=actor_source,
                status=status,
                duration_ms=duration_ms,
                retry_count=0,
                error_code=error_code,
                error_message=error_message,
                details={"error": error_message},
            )
            return

        if status == "success" and response is not None:
            self.manager.record_operation_activity(
                route=route,
                action=action,
                actor_source=actor_source,
                status=status,
                duration_ms=duration_ms,
                retry_count=0,
                details=self._response_summary(response),
            )

    def _dispatch_post_route(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        if route == "/api/models/save":
            model = self.manager.save_model(payload)
            return {"ok": True, "model": model}
        if route == "/api/models/delete":
            self.manager.remove_model(str(payload.get("alias", "")))
            return {"ok": True}
        if route == "/api/discover":
            root = str(payload.get("root") or self.manager.discovery_root)
            return {"ok": True, "items": self.manager.discover(root)}

        route_payload = remote_and_download_post_route_payload(route, self.manager, payload)
        if route_payload is not None:
            return {"ok": True, **route_payload}
        if route == "/api/switch":
            target = str(payload.get("target", "")).strip()
            self.manager.run_cli("switch", target)
            return {"ok": True}
        if route == "/api/restart":
            self.manager.run_cli("restart")
            return {"ok": True}
        if route == "/api/stop":
            self.manager.run_cli("stop")
            return {"ok": True}
        if route == "/api/mode":
            target_mode = str(payload.get("mode", "")).strip()
            self.manager.run_cli("set-mode", target_mode, "--restart")
            return {"ok": True}
        if route == "/api/defaults/save":
            updates = {
                key: str(payload.get(key, ""))
                for key in KNOWN_DEFAULT_KEYS
                if key in payload
            }
            self.manager.save_defaults(updates)
            return {"ok": True}
        if route == "/api/dashboard-service":
            action = str(payload.get("action", "status")).strip()
            self.manager.run_cli("dashboard-service", action)
            return {"ok": True, "service": self.manager.dashboard_service_status()}
        if route == "/api/opencode/sync":
            preset = str(payload.get("preset", "balanced")).strip() or "balanced"
            result = self.manager.sync_opencode(preset)
            return {"ok": True, "result": result}
        if route == "/api/openclaw/sync":
            result = self.manager.sync_openclaw()
            return {"ok": True, "result": result}
        if route == "/api/claude/sync":
            result = self.manager.sync_claude()
            return {"ok": True, "result": result}
        if route == "/api/glyphos/sync":
            result = self.manager.sync_glyphos()
            return {"ok": True, "result": result}
        if route == "/api/claude-gateway":
            action = str(payload.get("action", "status")).strip()
            result = self.parse_key_values(self.manager.run_cli("claude-gateway", action))
            return {"ok": True, "result": result}
        raise ValidationError("unknown_route", f"Unknown API route: {route}")

    def _status_for_error(self, error: Exception) -> HTTPStatus:
        if isinstance(error, ValidationError):
            if error.code in {"missing_api_token", "invalid_api_token"}:
                return HTTPStatus.UNAUTHORIZED
            if error.code == "unknown_route":
                return HTTPStatus.NOT_FOUND
            if error.code == "payload_too_large":
                return HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            if error.code == "client_not_allowed":
                return HTTPStatus.FORBIDDEN
            return HTTPStatus.BAD_REQUEST
        if isinstance(error, CommandTimeoutError):
            return HTTPStatus.GATEWAY_TIMEOUT
        if isinstance(error, ValueError):
            return HTTPStatus.BAD_REQUEST
        if isinstance(error, RuntimeError):
            return HTTPStatus.BAD_GATEWAY
        return HTTPStatus.INTERNAL_SERVER_ERROR

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"status": "ok"})
            return
        if parsed.path.startswith("/api/"):
            try:
                self._authorize_api_request(parsed.path)
                if parsed.path == "/api/state":
                    self.send_json(self.manager.state())
                    return
                if parsed.path == "/api/logs":
                    query = urllib.parse.parse_qs(parsed.query)
                    lines = self._parse_lines_query(query.get("lines", [None])[0], default=80)
                    logs = self.manager.run_cli("logs", str(lines))
                    self.send_json({"lines": lines, "content": logs})
                    return
                if parsed.path == "/api/dashboard-service/logs":
                    query = urllib.parse.parse_qs(parsed.query)
                    lines = self._parse_lines_query(query.get("lines", [None])[0], default=100)
                    logs = self.manager.run_cli("dashboard-service", "logs", str(lines))
                    self.send_json({"lines": lines, "content": logs})
                    return
                if parsed.path == "/api/claude-gateway/logs":
                    query = urllib.parse.parse_qs(parsed.query)
                    lines = self._parse_lines_query(query.get("lines", [None])[0], default=100)
                    logs = self.manager.run_cli("claude-gateway", "logs", str(lines))
                    self.send_json({"lines": lines, "content": logs})
                    return
                raise ValidationError("unknown_route", f"Unknown API route: {parsed.path}")
            except Exception as exc:
                status = self._status_for_error(exc)
                self.send_error_json(status, str(exc), code=getattr(exc, "code", "unknown_error"))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        started = time.perf_counter()
        response: dict[str, Any] | None = None
        response_error: Exception | None = None
        try:
            self._authorize_api_request(route)
            payload = self.read_json_body()
            payload = self._validate_post_payload(route, payload)
            response = self._dispatch_post_route(route, payload)
            self.send_json(response)
        except Exception as exc:
            response_error = exc
            status = self._status_for_error(exc)
            self.send_error_json(status, str(exc), code=getattr(exc, "code", "unknown_error"))
        finally:
            if route.startswith("/api/"):
                if response_error is not None:
                    self._track_api_activity(route=route, start=started, error=response_error)
                elif response is not None:
                    self._track_api_activity(route=route, start=started, response=response)

    def read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValidationError("invalid_content_length", "Content-Length must be an integer") from exc

        if length < 0:
            raise ValidationError("invalid_content_length", "Content-Length must be non-negative")

        max_bytes = parse_max_request_bytes()
        if length > max_bytes:
            raise ValidationError("payload_too_large", f"Request body exceeds limit of {max_bytes} bytes")

        body = self.rfile.read(length) if length else b"{}"
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("invalid_body", "Invalid JSON body") from exc
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValidationError("invalid_body", "JSON body must be an object")
        return payload

    def serve_static(self, raw_path: str) -> None:
        path = raw_path if raw_path != "/" else "/index.html"
        requested = (self.web_root / path.lstrip("/")).resolve()
        if not str(requested).startswith(str(self.web_root.resolve())) or not requested.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return

        if requested.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif requested.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif requested.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        else:
            content_type = "application/octet-stream"

        data = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: HTTPStatus, message: str, code: str | None = None) -> None:
        payload = {"ok": False, "error": message}
        if code:
            payload["code"] = code
        self.send_json(payload, status=status)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Launch the LLM Model Manager web dashboard")
    parser.add_argument("--host", default=os.environ.get("LLAMA_MODEL_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LLAMA_MODEL_WEB_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--require-bind", action="store_true", help="exit non-zero if the dashboard port is already occupied")
    parser.add_argument("--demo", action="store_true", help="Serve sanitized demo data for screenshots and public docs")
    args = parser.parse_args(argv)

    web_root = Path(__file__).resolve().parent
    manager = Manager(web_root, demo=args.demo)

    handler = type("AppHandlerImpl", (AppHandler,), {})
    handler.manager = manager
    handler.web_root = web_root

    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        url = f"http://{args.host}:{args.port}/"
        if args.require_bind:
            print(f"{APP_TITLE} could not bind {url}: {exc}", file=sys.stderr)
            return 1
        if not args.no_browser:
            webbrowser.open(url)
        print(f"{APP_TITLE} already appears to be running at {url}")
        return 0

    url = f"http://{args.host}:{args.port}/"
    print(f"{APP_TITLE} listening on {url}")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
