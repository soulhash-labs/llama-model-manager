from __future__ import annotations

import os
import threading
from typing import Any

from lmm_updates import UpdateChecker

from lmm_config import load_lmm_config_from_env
from lmm_health import ComponentHealth, HealthChecker
from lmm_notifications import NotificationType, create_notification_manager

from .http_utils import http_json
from .telemetry import load_gateway_state


def normalize_cloud_provider(raw: str) -> str:
    provider = str(raw or "").strip().lower()
    if provider in {"openai", "anthropic", "xai"}:
        return provider
    return ""


def parse_cloud_fallback_order(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list | tuple):
        values = list(raw)
    else:
        values = str(raw).split(",")
    providers: list[str] = []
    for value in values:
        provider = normalize_cloud_provider(str(value))
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "y"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "n"}:
        return False
    return default


def load_glyphos_config() -> dict[str, Any]:
    from glyphos_ai.ai_compute.api_client import _load_glyphos_config as integration_load_config  # type: ignore

    return integration_load_config()


def cloud_routing_config() -> tuple[list[str], str]:
    config = load_glyphos_config()
    cloud_root = config.get("ai_compute", {}).get("cloud", {}) if isinstance(config, dict) else {}
    preferred_raw = os.environ.get("GLYPHOS_CLOUD_PREFERRED", "").strip()
    if not preferred_raw and isinstance(config, dict):
        preferred_raw = (
            str(config.get("ai_compute", {}).get("cloud", {}).get("preferred_cloud", "")).strip()
            if isinstance(cloud_root, dict)
            else ""
        )
    if not preferred_raw and isinstance(config, dict):
        preferred_raw = (
            str(config.get("ai_compute", {}).get("cloud", {}).get("preferred_provider", "")).strip()
            if isinstance(cloud_root, dict)
            else ""
        )
    preferred_cloud = (
        normalize_cloud_provider(preferred_raw)
        or normalize_cloud_provider(os.environ.get("GLYPHOS_CLOUD_PREFERRED_PROVIDER", ""))
        or "xai"
    )

    fallback_order = os.environ.get("GLYPHOS_CLOUD_FALLBACK_ORDER", "").strip()
    if not fallback_order and isinstance(config, dict):
        cloud_root = config.get("ai_compute", {}).get("cloud", {})
        fallback_order = cloud_root.get("fallback_order", "") if isinstance(cloud_root, dict) else ""
    return (
        parse_cloud_fallback_order(fallback_order),
        preferred_cloud,
    )


def provider_status(enabled: bool, configured: bool, client: Any, reason: str) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "configured": bool(configured),
        "available": bool(client is not None),
        "model": getattr(client, "model", ""),
        "max_tokens": getattr(client, "max_tokens", 0),
        "reason": reason,
    }


def get_cloud_provider_status() -> dict[str, Any]:
    status = {"xai": {}, "openai": {}, "anthropic": {}}
    try:
        from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore
    except Exception:
        return status

    try:
        clients = create_configured_clients()
    except Exception:
        clients = {}
    config = load_glyphos_config()
    cloud_root = config.get("ai_compute", {}).get("cloud", {}) if isinstance(config, dict) else {}
    cloud_root_enabled = coerce_bool(cloud_root.get("enabled"), default=True)

    for provider in ("xai", "openai", "anthropic"):
        provider_key = provider.upper()
        cfg_provider = (
            config.get("ai_compute", {}).get(provider, {}) if isinstance(config.get("ai_compute", {}), dict) else {}
        )
        cfg_enabled = cfg_provider.get("enabled", "true") if isinstance(cfg_provider, dict) else "true"
        enabled = coerce_bool(
            os.environ.get(f"GLYPHOS_CLOUD_{provider_key}_ENABLED"),
            default=coerce_bool(cfg_enabled, default=True),
        )
        if not cloud_root_enabled:
            enabled = False
        api_key = os.environ.get(f"GLYPHOS_CLOUD_{provider_key}_API_KEY") or os.environ.get(
            f"{provider_key}_API_KEY", ""
        )
        if not api_key and isinstance(cfg_provider, dict):
            api_key = cfg_provider.get("api_key", "")
        configured = bool(enabled and str(api_key).strip())
        client = clients.get(provider) if isinstance(clients, dict) else None
        if client is not None:
            reason = "ready"
        elif not enabled:
            reason = "disabled"
        elif not configured:
            reason = "api_key_missing"
        else:
            reason = "not_available"
        status[provider] = provider_status(enabled=enabled, configured=configured, client=client, reason=reason)

    return status


class GatewayRuntime:
    def __init__(self, *, backend_base_url: str, model_id: str = "") -> None:
        self.backend_base_url = backend_base_url.rstrip("/")
        self.model_id = model_id
        self._health = HealthChecker(backend_url=backend_base_url, config=load_lmm_config_from_env())

    def health(self) -> dict[str, Any]:
        fallback_order, preferred_cloud = cloud_routing_config()
        return {
            "ok": True,
            "service": "lmm-glyphos-openai-gateway",
            "cloud_routing": {
                "preferred_cloud": preferred_cloud,
                "fallback_order": fallback_order,
            },
            "cloud_providers": get_cloud_provider_status(),
        }

    def health_payload(self) -> dict[str, Any]:
        return self.health()

    def list_models(self) -> tuple[int, dict[str, Any]]:
        try:
            return http_json("GET", f"{self.backend_base_url}/models", timeout=5)
        except Exception as exc:
            model = self.model_id or "local-llama"
            return 200, {
                "object": "list",
                "data": [{"id": model, "object": "model", "owned_by": "lmm"}],
                "warning": str(exc),
            }

    def telemetry(self) -> dict[str, Any]:
        return load_gateway_state()

    @property
    def health_checker(self) -> HealthChecker:
        return self._health

    def health_check(self) -> dict[str, ComponentHealth]:
        return self.health_checker.check_all()


def maybe_start_update_watcher(server: Any, *, watcher_config: Any) -> None:
    current_version = os.environ.get("LMM_VERSION", "v2.1.0")
    checker = UpdateChecker(
        current_lmm_version=current_version,
        lmm_repo=watcher_config.lmm_repo,
        llamacpp_repo=watcher_config.llamacpp_repo,
        timeout=watcher_config.timeout_seconds,
        state_file=watcher_config.state_file,
    )
    server.update_checker = checker
    interval_seconds = int(watcher_config.check_interval_hours) * 3600
    if interval_seconds < 60:
        interval_seconds = 60

    def periodic_check() -> None:
        try:
            lmm_result = checker.check_lmm_update()
            llamacpp_result = checker.check_llamacpp_update()
        except Exception:
            lmm_result = None
            llamacpp_result = None

        manager = create_notification_manager(True)
        if manager is not None:
            if lmm_result and lmm_result.update_available:
                manager.notify(
                    "LMM update available",
                    f"Current: {lmm_result.current_version}. Latest: {lmm_result.latest_version}.",
                    NotificationType.UPDATE_AVAILABLE,
                )
            if llamacpp_result and llamacpp_result.update_available:
                manager.notify(
                    "llama.cpp update available",
                    f"Current: {llamacpp_result.current_version}. Latest: {llamacpp_result.latest_version}.",
                    NotificationType.UPDATE_AVAILABLE,
                )

        timer = threading.Timer(interval_seconds, periodic_check)
        timer.daemon = True
        server.update_timer = timer
        timer.start()

    initial_timer = threading.Timer(0, periodic_check)
    initial_timer.daemon = True
    server.update_timer = initial_timer
    initial_timer.start()


__all__ = [
    "GatewayRuntime",
    "cloud_routing_config",
    "coerce_bool",
    "get_cloud_provider_status",
    "load_glyphos_config",
    "maybe_start_update_watcher",
    "normalize_cloud_provider",
    "parse_cloud_fallback_order",
    "provider_status",
]
