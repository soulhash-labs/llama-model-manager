#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_TITLE = "LLM Model Manager"
APP_BRAND = "Local Control Surface"
HEADER_LINE = "# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes"
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
    "LLAMA_SERVER_LOG",
    "LLAMA_SERVER_WAIT_SECONDS",
    "LLAMA_SERVER_EXTRA_ARGS",
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
        "LLAMA_SERVER_LOG": "/var/log/llama-server.log",
        "LLAMA_SERVER_EXTRA_ARGS": "",
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
        self.cli_bin = self._resolve_cli_bin()

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

        command = [str(self.cli_bin), *args]
        result = subprocess.run(command, capture_output=True, text=True)
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
        return model

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
            "LLAMA_SERVER_HOST": values.get("LLAMA_SERVER_HOST", "127.0.0.1"),
            "LLAMA_SERVER_PORT": values.get("LLAMA_SERVER_PORT", "8081"),
            "LLAMA_SERVER_DEVICE": values.get("LLAMA_SERVER_DEVICE", ""),
            "LLAMA_SERVER_CONTEXT": values.get("LLAMA_SERVER_CONTEXT", "128000"),
            "LLAMA_SERVER_NGL": values.get("LLAMA_SERVER_NGL", "999"),
            "LLAMA_SERVER_BATCH": values.get("LLAMA_SERVER_BATCH", "128"),
            "LLAMA_SERVER_THREADS": values.get("LLAMA_SERVER_THREADS", "16"),
            "LLAMA_SERVER_PARALLEL": values.get("LLAMA_SERVER_PARALLEL", ""),
            "LLAMA_SERVER_LOG": values.get("LLAMA_SERVER_LOG", str(self.home / "models" / "llama-server.log")),
            "LLAMA_SERVER_EXTRA_ARGS": values.get("LLAMA_SERVER_EXTRA_ARGS", ""),
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
        claude_gateway_status = self.parse_key_values(self.run_cli("claude-gateway", "status")) if not self.demo else {}
        claude_model_id = defaults.get("CLAUDE_MODEL_ID", "").strip() or current_alias
        claude_base_url = defaults.get("CLAUDE_BASE_URL", "").strip() or f"http://{defaults.get('CLAUDE_GATEWAY_HOST', '127.0.0.1')}:{defaults.get('CLAUDE_GATEWAY_PORT', '4000')}"
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
        }

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
        return self.parse_key_values(self.run_cli("dashboard-service", "status"))

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
            }
        current = self.parse_key_values(self.run_cli("current"))
        doctor = self.parse_key_values(self.run_cli("doctor"))
        mode = self.parse_key_values(self.run_cli("mode"))
        defaults = self.defaults()
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
            "models": self.read_models(),
            "dashboard_service": self.dashboard_service_status(),
            **integration,
            "discovery_root": self.discovery_root,
            "api_base": api_base,
            "registry_file": str(self.models_file),
            "registry_exists": self.models_file.exists(),
            "defaults_file": str(self.defaults_file),
            "defaults_exists": self.defaults_file.exists(),
        }


class AppHandler(BaseHTTPRequestHandler):
    manager: Manager
    web_root: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"status": "ok"})
            return
        if parsed.path == "/api/state":
            self.send_json(self.manager.state())
            return
        if parsed.path == "/api/logs":
            query = urllib.parse.parse_qs(parsed.query)
            lines = int(query.get("lines", ["80"])[0])
            logs = self.manager.run_cli("logs", str(lines))
            self.send_json({"lines": lines, "content": logs})
            return
        if parsed.path == "/api/dashboard-service/logs":
            query = urllib.parse.parse_qs(parsed.query)
            lines = int(query.get("lines", ["100"])[0])
            logs = self.manager.run_cli("dashboard-service", "logs", str(lines))
            self.send_json({"lines": lines, "content": logs})
            return
        if parsed.path == "/api/claude-gateway/logs":
            query = urllib.parse.parse_qs(parsed.query)
            lines = int(query.get("lines", ["100"])[0])
            logs = self.manager.run_cli("claude-gateway", "logs", str(lines))
            self.send_json({"lines": lines, "content": logs})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/models/save":
                model = self.manager.save_model(payload)
                self.send_json({"ok": True, "model": model})
                return
            if parsed.path == "/api/models/delete":
                self.manager.remove_model(str(payload.get("alias", "")))
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/discover":
                root = str(payload.get("root") or self.manager.discovery_root)
                self.send_json({"ok": True, "items": self.manager.discover(root)})
                return
            if parsed.path == "/api/switch":
                target = str(payload.get("target", "")).strip()
                self.manager.run_cli("switch", target)
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/restart":
                self.manager.run_cli("restart")
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/stop":
                self.manager.run_cli("stop")
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/mode":
                target_mode = str(payload.get("mode", "")).strip()
                self.manager.run_cli("set-mode", target_mode, "--restart")
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/defaults/save":
                updates = {
                    key: str(payload.get(key, ""))
                    for key in KNOWN_DEFAULT_KEYS
                    if key in payload
                }
                self.manager.save_defaults(updates)
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/dashboard-service":
                action = str(payload.get("action", "status")).strip()
                self.manager.run_cli("dashboard-service", action)
                self.send_json({"ok": True, "service": self.manager.dashboard_service_status()})
                return
            if parsed.path == "/api/opencode/sync":
                preset = str(payload.get("preset", "balanced")).strip() or "balanced"
                result = self.manager.sync_opencode(preset)
                self.send_json({"ok": True, "result": result})
                return
            if parsed.path == "/api/openclaw/sync":
                result = self.manager.sync_openclaw()
                self.send_json({"ok": True, "result": result})
                return
            if parsed.path == "/api/claude/sync":
                result = self.manager.sync_claude()
                self.send_json({"ok": True, "result": result})
                return
            if parsed.path == "/api/glyphos/sync":
                result = self.manager.sync_glyphos()
                self.send_json({"ok": True, "result": result})
                return
            if parsed.path == "/api/claude-gateway":
                action = str(payload.get("action", "status")).strip()
                result = self.parse_key_values(self.manager.run_cli("claude-gateway", action))
                self.send_json({"ok": True, "result": result})
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown API route")
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, str(exc))
        except Exception as exc:  # pragma: no cover - last-resort handler
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

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

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"ok": False, "error": message}, status=status)

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
