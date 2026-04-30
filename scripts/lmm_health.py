#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from lmm_config import GatewayConfig  # noqa: E402


@dataclass
class ComponentHealth:
    name: str
    status: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass
class RuntimeReport:
    version: str
    uptime_seconds: int | float
    components: dict[str, ComponentHealth]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "components": {name: component.to_dict() for name, component in self.components.items()},
            "timestamp": self.timestamp,
        }


def _iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class HealthChecker:
    def __init__(self, backend_url: str, config: GatewayConfig) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.config = config
        self._started_at = time.time()

    def check_all(self) -> dict[str, ComponentHealth]:
        return {
            "backend": self._check_backend(),
            "storage": self._check_storage(),
            "context": self._check_context(),
        }

    def _check_backend(self) -> ComponentHealth:
        try:
            request = urlrequest.Request(f"{self.backend_url}/models", method="GET")
            with urlrequest.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return ComponentHealth("backend", "healthy", "backend responded to /models")
                return ComponentHealth("backend", "unhealthy", f"backend /models returned {response.status}")
        except HTTPError as exc:
            return ComponentHealth("backend", "unhealthy", f"backend /models returned {exc.code}")
        except URLError as exc:
            return ComponentHealth("backend", "unhealthy", str(exc))
        except Exception as exc:
            return ComponentHealth("backend", "unhealthy", str(exc))

    def _run_record_path(self) -> Path:
        return Path(
            os.environ.get(
                "LMM_RUN_RECORDS_FILE",
                str(Path.home() / ".local" / "state" / "llama-server" / "lmm-run-records.json"),
            )
        ).expanduser()

    def _check_storage(self) -> ComponentHealth:
        path = self._run_record_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".healthcheck",
                delete=True,
            ) as marker:
                marker.write("ok")
                marker.flush()
            return ComponentHealth("storage", "healthy", "run record store path is writable")
        except Exception as exc:
            return ComponentHealth("storage", "unhealthy", f"run record store path not writable: {exc}")

    def _check_context(self) -> ComponentHealth:
        def fallback_context_status() -> str:
            from lmm_config import load_lmm_config_from_env

            context_config = load_lmm_config_from_env().context
            if not context_config.enabled:
                return "disabled"
            app_root = Path(__file__).resolve().parents[1]
            mcp_root = app_root / "integrations" / "context-mode-mcp"
            if not (mcp_root / "package.json").is_file():
                return "missing"
            if context_config.command:
                return "command_configured"
            bridge_path = app_root / "scripts" / "context_mcp_bridge.py"
            if not bridge_path.is_file():
                return "missing_bridge"
            if not (mcp_root / "dist" / "index.js").is_file():
                return "missing_dist"
            return "bridge_ready"

        try:
            from glyphos_openai_gateway import context_status

            status, _ = context_status()
        except Exception:
            try:
                status = fallback_context_status()
            except Exception as exc:
                return ComponentHealth("context", "unhealthy", f"context pipeline unavailable: {exc}")

        if status in {"bridge_ready", "disabled", "command_configured"}:
            return ComponentHealth("context", "healthy", f"context pipeline status: {status}")
        if status in {"missing", "missing_bridge", "missing_dist"}:
            return ComponentHealth("context", "degraded", f"context pipeline status: {status}")
        return ComponentHealth("context", "unhealthy", f"context pipeline status: {status}")

    def is_healthy(self) -> bool:
        return "unhealthy" not in {component.status for component in self.check_all().values()}

    def is_ready(self) -> bool:
        return all(component.status == "healthy" for component in self.check_all().values())

    def get_runtime_report(self) -> RuntimeReport:
        return RuntimeReport(
            version="1",
            uptime_seconds=round(time.time() - self._started_at),
            components=self.check_all(),
            timestamp=_iso_timestamp(),
        )
