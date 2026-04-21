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
        self.config_dir = Path(os.environ.get("XDG_CONFIG_HOME", self.home / ".config")) / "llama-server"
        self.defaults_file = Path(os.environ.get("LLAMA_DEFAULTS_FILE", self.config_dir / "defaults.env"))
        self.models_file = Path(os.environ.get("LLAMA_MODELS_FILE", self.config_dir / "models.tsv"))
        self.discovery_root = os.environ.get("LLAMA_MODEL_DISCOVERY_ROOT", str(self.home / "models"))
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
        }

    def state(self) -> dict[str, Any]:
        if self.demo:
            return {
                **DEMO_STATE,
                "demo": True,
                "defaults": dict(DEMO_STATE["defaults"]),
                "current": dict(DEMO_STATE["current"]),
                "doctor": dict(DEMO_STATE["doctor"]),
                "mode": dict(DEMO_STATE["mode"]),
                "models": [dict(model) for model in DEMO_STATE["models"]],
                "registry_file": str(self.models_file),
                "registry_exists": True,
                "defaults_file": str(self.defaults_file),
                "defaults_exists": True,
            }
        current = self.parse_key_values(self.run_cli("current"))
        doctor = self.parse_key_values(self.run_cli("doctor"))
        mode = self.parse_key_values(self.run_cli("mode"))
        defaults = self.defaults()
        api_base = f"http://{defaults['LLAMA_SERVER_HOST']}:{defaults['LLAMA_SERVER_PORT']}/v1"
        current_model_name = Path(current["model"]).name if current.get("model") else "<model>"

        return {
            "title": APP_TITLE,
            "brand": APP_BRAND,
            "demo": False,
            "defaults": defaults,
            "current": current,
            "doctor": doctor,
            "mode": mode,
            "models": self.read_models(),
            "discovery_root": self.discovery_root,
            "api_base": api_base,
            "opencode_model": f"llamacpp/{current_model_name}",
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
    parser.add_argument("--demo", action="store_true", help="Serve sanitized demo data for screenshots and public docs")
    args = parser.parse_args(argv)

    web_root = Path(__file__).resolve().parent
    manager = Manager(web_root, demo=args.demo)

    handler = type("AppHandlerImpl", (AppHandler,), {})
    handler.manager = manager
    handler.web_root = web_root

    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError:
        url = f"http://{args.host}:{args.port}/"
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
