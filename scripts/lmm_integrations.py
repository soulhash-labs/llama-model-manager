#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class Integration:
    """Base class for detecting and reporting external integration status."""

    name: str = ""

    def get_status(self) -> dict[str, Any]:
        return {"name": self.name, "status": "unknown"}

    def is_available(self) -> bool:
        return self.get_status().get("status") == "available"


class OpenCodeIntegration(Integration):
    name = "opencode"

    def get_status(self) -> dict[str, Any]:
        binary = shutil.which("opencode")
        if not binary:
            return {"name": self.name, "status": "not_found"}
        try:
            result = subprocess.run(
                ["opencode", "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {
                    "name": self.name,
                    "status": "available",
                    "version": result.stdout.decode().strip(),
                    "binary": binary,
                }
        except Exception:
            pass
        return {"name": self.name, "status": "not_found", "binary": binary}

    def is_available(self) -> bool:
        return self.get_status().get("status") == "available"


class ClaudeCodeIntegration(Integration):
    name = "claude-code"

    def get_status(self) -> dict[str, Any]:
        binary = shutil.which("claude")
        if not binary:
            return {"name": self.name, "status": "not_found"}
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {
                    "name": self.name,
                    "status": "available",
                    "version": result.stdout.decode().strip(),
                    "binary": binary,
                }
        except Exception:
            pass
        return {"name": self.name, "status": "not_found", "binary": binary}

    def is_available(self) -> bool:
        return self.get_status().get("status") == "available"


class GlyphosIntegration(Integration):
    name = "glyphos"

    def get_status(self) -> dict[str, Any]:
        config_path = Path.home() / ".glyphos" / "config.yaml"
        if config_path.exists():
            return {
                "name": self.name,
                "status": "available",
                "config_path": str(config_path),
            }
        return {"name": self.name, "status": "not_found"}

    def is_available(self) -> bool:
        return self.get_status().get("status") == "available"


class IntegrationManager:
    """Registry for detecting and querying integration status.

    Caches status results for a configurable TTL to avoid repeated
    subprocess calls on every dashboard poll.
    """

    def __init__(self, cache_ttl: float = 30.0) -> None:
        self._integrations: dict[str, Integration] = {}
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_ttl = cache_ttl

    def register(self, integration: Integration) -> None:
        self._integrations[integration.name] = integration

    def get(self, name: str) -> Integration | None:
        return self._integrations.get(name)

    def get_status(self, name: str) -> dict[str, Any]:
        integration = self.get(name)
        if not integration:
            return {"name": name, "status": "unknown"}
        now = time.time()
        cached = self._cache.get(name)
        if cached is not None and (now - cached[0]) < self._cache_ttl:
            return cached[1]
        status = integration.get_status()
        self._cache[name] = (now, status)
        return status

    def invalidate_cache(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    def is_available(self, name: str) -> bool:
        return self.get_status(name).get("status") == "available"

    def list_all(self) -> list[dict[str, Any]]:
        return [self.get_status(name) for name in self._integrations]

    def list_available(self) -> list[dict[str, Any]]:
        return [s for s in self.list_all() if s.get("status") == "available"]


def create_default_manager() -> IntegrationManager:
    """Return an IntegrationManager pre-registered with all known integrations."""
    manager = IntegrationManager()
    manager.register(OpenCodeIntegration())
    manager.register(ClaudeCodeIntegration())
    manager.register(GlyphosIntegration())
    return manager


__all__ = [
    "Integration",
    "OpenCodeIntegration",
    "ClaudeCodeIntegration",
    "GlyphosIntegration",
    "IntegrationManager",
    "create_default_manager",
]
