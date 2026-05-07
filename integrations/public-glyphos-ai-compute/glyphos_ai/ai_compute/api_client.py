"""
API clients for local and external AI backends.
"""

from __future__ import annotations

import json
import os
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


class _HttpJsonResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> _HttpJsonResponse:
    data = None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return _HttpJsonResponse(int(response.status), parsed if isinstance(parsed, dict) else {})
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return _HttpJsonResponse(int(exc.code), parsed if isinstance(parsed, dict) else {"error": raw})
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _load_glyphos_config() -> dict[str, Any]:
    config_path = Path(os.environ.get("GLYPHOS_CONFIG_FILE", "~/.glyphos/config.yaml")).expanduser()
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


def _config_value(config: dict[str, Any], dotted: str, default: str = "") -> str:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return str(current).strip() if current is not None else default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "y"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "n"}:
        return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(*names: str, default: bool = False) -> bool:
    for name in names:
        if name not in os.environ:
            continue
        return _coerce_bool(os.environ.get(name), default=default)
    return default


_RETIRED_ENV_VARS = [
    "GLYPHOS_PREFERRED_LOCAL_BACKEND",
    "GLYPHOS_OLLAMA_ENABLED",
    "GLYPHOS_OLLAMA_URL",
    "GLYPHOS_OLLAMA_MODEL",
    "GLYPHOS_OLLAMA_TIMEOUT",
    "QRBT_OLLAMA_BASE_URL",
]
for _lane in ("AURORA", "TERRAN", "STARLIGHT", "POLARIS"):
    _RETIRED_ENV_VARS.extend(
        [
            f"GLYPHOS_OLLAMA_{_lane}_URL",
            f"GLYPHOS_OLLAMA_{_lane}_MODEL",
            f"GLYPHOS_OLLAMA_{_lane}_TIMEOUT",
            f"QRBT_COUNCIL_OLLAMA_{_lane}_URL",
        ]
    )


def _warn_on_retired_configuration(config: dict[str, Any]) -> None:
    retired_config_keys: list[str] = []
    for dotted in (
        "ai_compute.local.preferred_local_backend",
        "ai_compute.routing.preferred_local_backend",
        "ai_compute.ollama.enabled",
        "ai_compute.ollama.url",
        "ai_compute.ollama.model",
        "ai_compute.ollama.timeout",
    ):
        if _config_value(config, dotted):
            retired_config_keys.append(dotted)
    for lane in ("aurora", "terran", "starlight", "polaris"):
        for suffix in ("ollama_url", "ollama_model", "ollama_timeout"):
            dotted = f"ai_compute.lanes.{lane}.{suffix}"
            if _config_value(config, dotted):
                retired_config_keys.append(dotted)

    retired_env_vars = [name for name in _RETIRED_ENV_VARS if os.environ.get(name, "").strip()]

    if retired_config_keys:
        warnings.warn(
            "Ignoring retired GlyphOS AI Compute config keys: "
            + ", ".join(sorted(retired_config_keys))
            + ". Public AI Compute is now llama.cpp-only. Remove these keys to silence this warning.",
            RuntimeWarning,
            stacklevel=2,
        )
    if retired_env_vars:
        warnings.warn(
            "Ignoring retired GlyphOS AI Compute environment variables: "
            + ", ".join(sorted(retired_env_vars))
            + ". Public AI Compute is now llama.cpp-only. Remove these variables to silence this warning.",
            RuntimeWarning,
            stacklevel=2,
        )


class BaseChatClient:
    def __init__(self, model: str, max_tokens: int = 32768, timeout: int = 30):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class LlamaCppClient(BaseChatClient):
    """OpenAI-compatible local llama.cpp client."""

    opens_stream_before_return = True

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8081/v1",
        model: str = "",
        max_tokens: int = int(os.environ.get("LMM_DEFAULT_MAX_TOKENS", "32768")),
        timeout: int = int(os.environ.get("LLAMA_CPP_STREAM_TIMEOUT", "3600")),
    ):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self._available: bool | None = None

    def _models_url(self) -> str:
        return f"{self.base_url}/models"

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _check_availability(self) -> None:
        try:
            response = _http_json("GET", self._models_url(), timeout=2)
            self._available = response.status_code == 200
        except Exception:
            self._available = False

    def is_available(self) -> bool:
        if self._available is None:
            try:
                response = _http_json("GET", self._models_url(), timeout=2)
                self._available = response.status_code == 200
            except Exception:
                self._available = False
        return self._available

    def _reset_availability(self) -> None:
        self._available = None

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        try:
            response = _http_json("GET", self._models_url(), timeout=5)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            for item in models:
                if isinstance(item, dict) and item.get("id"):
                    return str(item["id"])
        except Exception:
            pass
        return "local-llama"

    def _chat_payload(self, prompt: str, **kwargs) -> dict[str, Any]:
        return {
            "model": kwargs.get("model", self._resolve_model()),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }

    def generate(self, prompt: str, **kwargs) -> str:
        if not self.is_available():
            raise RuntimeError("llama.cpp backend is offline")
        try:
            response = _http_json(
                "POST",
                self._chat_url(),
                payload=self._chat_payload(prompt, **kwargs),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"llama.cpp request failed: {exc}") from exc

    def stream_generate(self, prompt: str, **kwargs) -> Iterator[str]:
        if not self.is_available():
            raise RuntimeError("llama.cpp backend is offline")
        payload = self._chat_payload(prompt, **kwargs)
        payload["stream"] = True
        req = urlrequest.Request(
            self._chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlrequest.urlopen(req, timeout=self.timeout)
        except Exception as exc:
            raise RuntimeError(f"llama.cpp streaming request failed: {exc}") from exc

        def chunks() -> Iterator[str]:
            try:
                with response:
                    yield ""
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line.split(":", 1)[1].strip()
                        if not data or data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") if isinstance(event, dict) else None
                        if not isinstance(choices, list) or not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            continue
                        delta = choice.get("delta")
                        if isinstance(delta, dict) and delta.get("content"):
                            yield str(delta["content"])
                        message = choice.get("message")
                        if isinstance(message, dict) and message.get("content"):
                            yield str(message["content"])
            except Exception as exc:
                raise RuntimeError(f"llama.cpp streaming request failed: {exc}") from exc

        return chunks()


class OpenAIClient(BaseChatClient):
    def __init__(self, api_key: str | None = None, model: str = "gpt-4-turbo-preview", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            raise RuntimeError("OpenAI backend is not configured")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=[{"role": "user", "content": prompt}],
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
            )
            return response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc


class AnthropicClient(BaseChatClient):
    def __init__(self, api_key: str | None = None, model: str = "claude-3-sonnet-20240229", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            raise RuntimeError("Anthropic backend is not configured")
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=kwargs.get("model", self.model),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc


class XAIClient(BaseChatClient):
    def __init__(self, api_key: str | None = None, model: str = "grok-beta", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            raise RuntimeError("xAI backend is not configured")
        try:
            response = _http_json(
                "POST",
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                payload={
                    "model": kwargs.get("model", self.model),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"xAI request failed: {exc}") from exc


def create_configured_clients() -> dict[str, Any]:
    config = _load_glyphos_config()
    clients: dict[str, Any] = {}

    _warn_on_retired_configuration(config)

    llama_url = _env_first(
        "GLYPHOS_LLAMACPP_URL",
        default=_config_value(config, "ai_compute.llamacpp.url", default="http://127.0.0.1:8081/v1"),
    )
    llama_model = _env_first(
        "GLYPHOS_LLAMACPP_MODEL", default=_config_value(config, "ai_compute.llamacpp.model", default="")
    )
    llama_timeout = int(
        _env_first(
            "GLYPHOS_LLAMACPP_TIMEOUT", default=_config_value(config, "ai_compute.llamacpp.timeout", default="3600")
        )
        or "3600"
    )
    if (
        _env_first(
            "GLYPHOS_LLAMACPP_ENABLED", default=_config_value(config, "ai_compute.llamacpp.enabled", default="true")
        ).lower()
        != "false"
    ):
        llamacpp = LlamaCppClient(base_url=llama_url, model=llama_model, timeout=llama_timeout)
        if llamacpp.is_available():
            clients["llamacpp"] = llamacpp
        elif _env_first("GLYPHOS_LLAMACPP_ENABLED", default="true").lower() != "false":
            warnings.warn(
                f"llama.cpp backend at {llama_url} is not reachable; check that the server is running",
                RuntimeWarning,
                stacklevel=2,
            )

    lane_keys = ["aurora", "terran", "starlight", "polaris"]
    for lane in lane_keys:
        base_url = _env_first(
            f"GLYPHOS_LLAMACPP_{lane.upper()}_URL",
            default=_config_value(config, f"ai_compute.lanes.{lane}.llamacpp_url", default=""),
        )
        if not base_url:
            continue
        model = _env_first(
            f"GLYPHOS_LLAMACPP_{lane.upper()}_MODEL",
            default=_config_value(config, f"ai_compute.lanes.{lane}.llamacpp_model", default=""),
        )
        timeout = int(
            _env_first(
                f"GLYPHOS_LLAMACPP_{lane.upper()}_TIMEOUT",
                default=_config_value(config, f"ai_compute.lanes.{lane}.llamacpp_timeout", default="3600"),
            )
            or "3600"
        )
        client = LlamaCppClient(base_url=base_url, model=model, timeout=timeout)
        if client.is_available():
            clients[f"llamacpp-{lane}"] = client

    cloud_enabled = _coerce_bool(
        _env_first(
            "GLYPHOS_CLOUD_ENABLED",
            default=_config_value(config, "ai_compute.cloud.enabled", default="true"),
        ),
        default=True,
    )
    if cloud_enabled:
        for provider in ("xai", "openai", "anthropic"):
            enabled = _coerce_bool(
                _env_first(
                    f"GLYPHOS_CLOUD_{provider.upper()}_ENABLED",
                    default=_config_value(config, f"ai_compute.{provider}.enabled", default="true"),
                ),
                default=True,
            )
            if not enabled:
                continue

            if provider == "openai":
                api_key = _env_first(
                    "GLYPHOS_CLOUD_OPENAI_API_KEY",
                    "OPENAI_API_KEY",
                    default=_config_value(config, "ai_compute.openai.api_key", default=""),
                )
                model = _env_first(
                    "GLYPHOS_CLOUD_OPENAI_MODEL",
                    default=_config_value(config, "ai_compute.openai.model", default="gpt-4o"),
                )
                max_tokens = _coerce_int(
                    _env_first(
                        "GLYPHOS_CLOUD_OPENAI_MAX_TOKENS",
                        default=_config_value(config, "ai_compute.openai.max_tokens", default="1000"),
                    ),
                    default=1000,
                )
                client = OpenAIClient(api_key=api_key, model=model, max_tokens=max_tokens)
            elif provider == "anthropic":
                api_key = _env_first(
                    "GLYPHOS_CLOUD_ANTHROPIC_API_KEY",
                    "ANTHROPIC_API_KEY",
                    default=_config_value(config, "ai_compute.anthropic.api_key", default=""),
                )
                model = _env_first(
                    "GLYPHOS_CLOUD_ANTHROPIC_MODEL",
                    default=_config_value(config, "ai_compute.anthropic.model", default="claude-3-5-sonnet-latest"),
                )
                max_tokens = _coerce_int(
                    _env_first(
                        "GLYPHOS_CLOUD_ANTHROPIC_MAX_TOKENS",
                        default=_config_value(config, "ai_compute.anthropic.max_tokens", default="1000"),
                    ),
                    default=1000,
                )
                client = AnthropicClient(api_key=api_key, model=model, max_tokens=max_tokens)
            else:
                api_key = _env_first(
                    "GLYPHOS_CLOUD_XAI_API_KEY",
                    "XAI_API_KEY",
                    default=_config_value(config, "ai_compute.xai.api_key", default=""),
                )
                model = _env_first(
                    "GLYPHOS_CLOUD_XAI_MODEL",
                    default=_config_value(config, "ai_compute.xai.model", default="grok-beta"),
                )
                max_tokens = _coerce_int(
                    _env_first(
                        "GLYPHOS_CLOUD_XAI_MAX_TOKENS",
                        default=_config_value(config, "ai_compute.xai.max_tokens", default="1000"),
                    ),
                    default=1000,
                )
                client = XAIClient(api_key=api_key, model=model, max_tokens=max_tokens)

            if client.is_available():
                clients[provider] = client

    return clients
