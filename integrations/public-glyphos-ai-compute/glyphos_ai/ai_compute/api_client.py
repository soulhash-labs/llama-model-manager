"""
API clients for local and external AI backends.

Phase 6-aligned notes:
- no hidden retrieval or context loading in the route path
- local config loading is explicit / opt-in
- clients return structured result mappings so router can preserve latency/tokens
- Anthropic supports both native Messages API and OpenAI-compat chat completions
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .client_base import BaseChatClient, _result
from .llamacpp_client import LlamaCppClient  # single canonical source of truth

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _load_glyphos_config(config_file: str | None = None) -> dict[str, Any]:
    """
    Explicit local config loader.

    IMPORTANT:
    This is opt-in. Callers should not trigger local file reads implicitly
    from the public route path.
    """
    config_path = Path(config_file or os.environ.get("GLYPHOS_CONFIG_FILE", "~/.glyphos/config.yaml")).expanduser()

    if not config_path.exists():
        return {}

    try:
        import yaml  # type: ignore
    except Exception:
        return {}

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _config_value(config: Mapping[str, Any], dotted: str, default: str = "") -> str:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return str(current).strip() if current is not None else default


def _as_int(value: str | int | None, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# -----------------------------------------------------------------------------
# OpenAI
# -----------------------------------------------------------------------------


class OpenAIClient(BaseChatClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_tokens: int = 1000,
        timeout: int = 30,
        base_url: str = "https://api.openai.com/v1",
    ):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str, **kwargs) -> dict[str, Any]:
        if not self.is_available():
            return _result(response=f"[OpenAI not configured] Processing: {prompt[:50]}...")

        started = time.perf_counter()
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }

        try:
            response = self._session.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")

            return _result(
                response=content,
                latency_ms=int((time.perf_counter() - started) * 1000),
                tokens_used=usage.get("completion_tokens"),
                raw=data,
                prompt_tokens=usage.get("prompt_tokens"),
                total_tokens=usage.get("total_tokens"),
                model=data.get("model", payload["model"]),
            )
        except Exception as exc:
            return _result(
                response=f"OpenAI error: {exc}",
                latency_ms=int((time.perf_counter() - started) * 1000),
                raw={"error": str(exc)},
            )


# -----------------------------------------------------------------------------
# Anthropic
# -----------------------------------------------------------------------------


class AnthropicClient(BaseChatClient):
    """
    Anthropic client supporting:
    - native Messages API
    - OpenAI-compatible chat/completions mode

    api_mode:
    - "messages"       -> POST /v1/messages
    - "chat"           -> POST /v1/chat/completions (compat mode)
    - "chat_completions" -> alias for chat
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 1000,
        timeout: int = 30,
        base_url: str = "https://api.anthropic.com/v1",
        api_mode: str = "messages",
        anthropic_version: str = "2023-06-01",
        default_system: str | None = None,
    ):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.api_mode = api_mode.strip().lower()
        self.anthropic_version = anthropic_version
        self.default_system = default_system

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _messages_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }

    def _compat_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _extract_messages_text(self, payload: Mapping[str, Any]) -> str:
        content = payload.get("content")
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == "text":
                text = block.get("text")
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)

    def generate(self, prompt: str, **kwargs) -> dict[str, Any]:
        if not self.is_available():
            return _result(response=f"[Anthropic not configured] Processing: {prompt[:50]}...")

        started = time.perf_counter()
        effective_mode = kwargs.get("api_mode", self.api_mode).strip().lower()

        if effective_mode in {"chat", "chat_completions"}:
            payload = {
                "model": kwargs.get("model", self.model),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }

            system = kwargs.get("system", self.default_system)
            if system:
                payload["messages"].insert(0, {"role": "system", "content": system})

            try:
                response = self._session.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._compat_headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                usage = data.get("usage") or {}
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")

                return _result(
                    response=content,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    tokens_used=usage.get("completion_tokens"),
                    raw=data,
                    prompt_tokens=usage.get("prompt_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    model=data.get("model", payload["model"]),
                    api_mode="chat",
                )
            except Exception as exc:
                return _result(
                    response=f"Anthropic error: {exc}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    raw={"error": str(exc)},
                    api_mode="chat",
                )

        payload = {
            "model": kwargs.get("model", self.model),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": [{"role": "user", "content": prompt}],
        }

        system = kwargs.get("system", self.default_system)
        if system:
            payload["system"] = system
        if "temperature" in kwargs and kwargs["temperature"] is not None:
            payload["temperature"] = kwargs["temperature"]

        try:
            response = self._session.post(
                f"{self.base_url}/messages",
                headers=self._messages_headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}

            return _result(
                response=self._extract_messages_text(data),
                latency_ms=int((time.perf_counter() - started) * 1000),
                tokens_used=usage.get("output_tokens"),
                raw=data,
                prompt_tokens=usage.get("input_tokens"),
                model=data.get("model", payload["model"]),
                stop_reason=data.get("stop_reason"),
                api_mode="messages",
            )
        except Exception as exc:
            return _result(
                response=f"Anthropic error: {exc}",
                latency_ms=int((time.perf_counter() - started) * 1000),
                raw={"error": str(exc)},
                api_mode="messages",
            )


# -----------------------------------------------------------------------------
# xAI
# -----------------------------------------------------------------------------


class XAIClient(BaseChatClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "grok-beta",
        max_tokens: int = 1000,
        timeout: int = 30,
        base_url: str = "https://api.x.ai/v1",
    ):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str, **kwargs) -> dict[str, Any]:
        if not self.is_available():
            return _result(response=f"[xAI not configured] Processing: {prompt[:50]}...")

        started = time.perf_counter()
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", 0.7),
        }

        try:
            response = self._session.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")

            return _result(
                response=content,
                latency_ms=int((time.perf_counter() - started) * 1000),
                tokens_used=usage.get("completion_tokens"),
                raw=data,
                prompt_tokens=usage.get("prompt_tokens"),
                total_tokens=usage.get("total_tokens"),
                model=data.get("model", payload["model"]),
            )
        except Exception as exc:
            return _result(
                response=f"xAI error: {exc}",
                latency_ms=int((time.perf_counter() - started) * 1000),
                raw={"error": str(exc)},
            )


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------


def create_configured_clients(
    *,
    config: dict[str, Any] | None = None,
    allow_local_config: bool = False,
    config_file: str | None = None,
) -> dict[str, Any]:
    """
    Build clients from:
    1. explicit config dict
    2. env vars
    3. optional local config file (opt-in only)

    Default is side-effect-light:
    - no local file read unless allow_local_config=True
    """
    effective_config = config or (_load_glyphos_config(config_file=config_file) if allow_local_config else {})

    clients: dict[str, Any] = {}

    preferred_local = _env_first(
        "GLYPHOS_PREFERRED_LOCAL_BACKEND",
        default=_config_value(
            effective_config,
            "ai_compute.routing.preferred_local_backend",
            default=_config_value(
                effective_config,
                "ai_compute.local.preferred_local_backend",
                default="llamacpp",
            ),
        ),
    )
    clients["_preferred_local_backend"] = preferred_local

    # ----------------- llama.cpp -----------------
    llama_url = _env_first(
        "GLYPHOS_LLAMACPP_URL",
        default=_config_value(
            effective_config,
            "ai_compute.llamacpp.url",
            default="http://127.0.0.1:8081",
        ),
    )
    llama_model = _env_first(
        "GLYPHOS_LLAMACPP_MODEL",
        default=_config_value(effective_config, "ai_compute.llamacpp.model", default=""),
    )
    llama_timeout = _as_int(
        _env_first(
            "GLYPHOS_LLAMACPP_TIMEOUT",
            default=_config_value(effective_config, "ai_compute.llamacpp.timeout", default="300"),
        ),
        300,
    )
    llama_enabled = (
        _env_first(
            "GLYPHOS_LLAMACPP_ENABLED",
            default=_config_value(effective_config, "ai_compute.llamacpp.enabled", default="true"),
        ).lower()
        != "false"
    )

    if llama_enabled:
        llamacpp = LlamaCppClient(
            base_url=llama_url,
            model=llama_model,
            timeout=llama_timeout,
        )
        if llamacpp.is_available():
            clients["llamacpp"] = llamacpp

    lane_keys = ["aurora", "terran", "starlight", "polaris"]

    for lane in lane_keys:
        base_url = _env_first(
            f"GLYPHOS_LLAMACPP_{lane.upper()}_URL",
            default=_config_value(effective_config, f"ai_compute.lanes.{lane}.llamacpp_url", default=""),
        )
        if not base_url:
            continue
        model = _env_first(
            f"GLYPHOS_LLAMACPP_{lane.upper()}_MODEL",
            default=_config_value(effective_config, f"ai_compute.lanes.{lane}.llamacpp_model", default=""),
        )
        timeout = _as_int(
            _env_first(
                f"GLYPHOS_LLAMACPP_{lane.upper()}_TIMEOUT",
                default=_config_value(effective_config, f"ai_compute.lanes.{lane}.llamacpp_timeout", default="300"),
            ),
            300,
        )
        client = LlamaCppClient(base_url=base_url, model=model, timeout=timeout)
        if client.is_available():
            clients[f"llamacpp-{lane}"] = client

    # ----------------- OpenAI -----------------
    openai_enabled = (
        _env_first(
            "GLYPHOS_OPENAI_ENABLED",
            default=_config_value(effective_config, "ai_compute.openai.enabled", default="false"),
        ).lower()
        == "true"
    )
    if openai_enabled:
        openai = OpenAIClient(
            api_key=_env_first(
                "OPENAI_API_KEY",
                default=_config_value(effective_config, "ai_compute.openai.api_key", default=""),
            ),
            model=_env_first(
                "GLYPHOS_OPENAI_MODEL",
                default=_config_value(effective_config, "ai_compute.openai.model", default="gpt-4o-mini"),
            ),
            timeout=_as_int(
                _env_first(
                    "GLYPHOS_OPENAI_TIMEOUT",
                    default=_config_value(effective_config, "ai_compute.openai.timeout", default="30"),
                ),
                30,
            ),
            base_url=_env_first(
                "GLYPHOS_OPENAI_BASE_URL",
                default=_config_value(
                    effective_config, "ai_compute.openai.base_url", default="https://api.openai.com/v1"
                ),
            ),
        )
        if openai.is_available():
            clients["openai"] = openai

    # ----------------- Anthropic -----------------
    anthropic_enabled = (
        _env_first(
            "GLYPHOS_ANTHROPIC_ENABLED",
            default=_config_value(effective_config, "ai_compute.anthropic.enabled", default="false"),
        ).lower()
        == "true"
    )
    if anthropic_enabled:
        anthropic = AnthropicClient(
            api_key=_env_first(
                "ANTHROPIC_API_KEY",
                default=_config_value(effective_config, "ai_compute.anthropic.api_key", default=""),
            ),
            model=_env_first(
                "GLYPHOS_ANTHROPIC_MODEL",
                default=_config_value(effective_config, "ai_compute.anthropic.model", default="claude-sonnet-4-5"),
            ),
            timeout=_as_int(
                _env_first(
                    "GLYPHOS_ANTHROPIC_TIMEOUT",
                    default=_config_value(effective_config, "ai_compute.anthropic.timeout", default="30"),
                ),
                30,
            ),
            base_url=_env_first(
                "GLYPHOS_ANTHROPIC_BASE_URL",
                default=_config_value(
                    effective_config, "ai_compute.anthropic.base_url", default="https://api.anthropic.com/v1"
                ),
            ),
            api_mode=_env_first(
                "GLYPHOS_ANTHROPIC_API_MODE",
                default=_config_value(effective_config, "ai_compute.anthropic.api_mode", default="messages"),
            ),
            anthropic_version=_env_first(
                "GLYPHOS_ANTHROPIC_VERSION",
                default=_config_value(effective_config, "ai_compute.anthropic.version", default="2023-06-01"),
            ),
        )
        if anthropic.is_available():
            clients["anthropic"] = anthropic

    # ----------------- xAI -----------------
    xai_enabled = (
        _env_first(
            "GLYPHOS_XAI_ENABLED",
            default=_config_value(effective_config, "ai_compute.xai.enabled", default="false"),
        ).lower()
        == "true"
    )
    if xai_enabled:
        xai = XAIClient(
            api_key=_env_first(
                "XAI_API_KEY",
                default=_config_value(effective_config, "ai_compute.xai.api_key", default=""),
            ),
            model=_env_first(
                "GLYPHOS_XAI_MODEL",
                default=_config_value(effective_config, "ai_compute.xai.model", default="grok-beta"),
            ),
            timeout=_as_int(
                _env_first(
                    "GLYPHOS_XAI_TIMEOUT",
                    default=_config_value(effective_config, "ai_compute.xai.timeout", default="30"),
                ),
                30,
            ),
            base_url=_env_first(
                "GLYPHOS_XAI_BASE_URL",
                default=_config_value(effective_config, "ai_compute.xai.base_url", default="https://api.x.ai/v1"),
            ),
        )
        if xai.is_available():
            clients["xai"] = xai

    return clients


__all__ = [
    "BaseChatClient",
    "LlamaCppClient",
    "OpenAIClient",
    "AnthropicClient",
    "XAIClient",
    "create_configured_clients",
]
