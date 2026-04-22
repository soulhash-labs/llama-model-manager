"""
API clients for local and external AI backends.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests


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


class BaseChatClient:
    def __init__(self, model: str, max_tokens: int = 1000, timeout: int = 30):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class LlamaCppClient(BaseChatClient):
    """OpenAI-compatible local llama.cpp client."""

    def __init__(self, base_url: str = "http://127.0.0.1:8081/v1", model: str = "", max_tokens: int = 1000, timeout: int = 300):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self._available = False
        self._check_availability()

    def _models_url(self) -> str:
        return f"{self.base_url}/models"

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _check_availability(self) -> None:
        try:
            response = requests.get(self._models_url(), timeout=2)
            self._available = response.status_code == 200
        except Exception:
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        try:
            response = requests.get(self._models_url(), timeout=5)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            for item in models:
                if isinstance(item, dict) and item.get("id"):
                    return str(item["id"])
        except Exception:
            pass
        return "local-llama"

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            return f"[llama.cpp offline] Processing: {prompt[:50]}..."
        try:
            response = requests.post(
                self._chat_url(),
                json={
                    "model": kwargs.get("model", self._resolve_model()),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": kwargs.get("temperature", 0.7),
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            return f"llama.cpp error: {exc}"


class OllamaClient(BaseChatClient):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3:70b", max_tokens: int = 500, timeout: int = 30):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self._available = False
        self._check_availability()

    def _check_availability(self) -> None:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            self._available = response.status_code == 200
        except Exception:
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            return f"[Ollama offline] Processing: {prompt[:50]}..."
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": kwargs.get("model", self.model),
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get("temperature", 0.7),
                        "num_predict": kwargs.get("max_tokens", self.max_tokens),
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as exc:
            return f"Ollama error: {exc}"


class OpenAIClient(BaseChatClient):
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4-turbo-preview", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            return f"[OpenAI not configured] Processing: {prompt[:50]}..."
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
            return f"OpenAI error: {exc}"


class AnthropicClient(BaseChatClient):
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-sonnet-20240229", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            return f"[Anthropic not configured] Processing: {prompt[:50]}..."
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
            return f"Anthropic error: {exc}"


class XAIClient(BaseChatClient):
    def __init__(self, api_key: Optional[str] = None, model: str = "grok-beta", max_tokens: int = 1000):
        super().__init__(model=model, max_tokens=max_tokens, timeout=30)
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, **kwargs) -> str:
        if not self._available:
            return f"[xAI not configured] Processing: {prompt[:50]}..."
        try:
            response = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": kwargs.get("model", self.model),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            return f"xAI error: {exc}"


def create_configured_clients() -> Dict[str, Any]:
    config = _load_glyphos_config()
    clients: Dict[str, Any] = {}

    preferred_local = _env_first('GLYPHOS_PREFERRED_LOCAL_BACKEND', default=_config_value(config, 'ai_compute.routing.preferred_local_backend', default='llamacpp'))
    clients['_preferred_local_backend'] = preferred_local

    llama_url = _env_first('GLYPHOS_LLAMACPP_URL', default=_config_value(config, 'ai_compute.llamacpp.url', default='http://127.0.0.1:8081/v1'))
    llama_model = _env_first('GLYPHOS_LLAMACPP_MODEL', default=_config_value(config, 'ai_compute.llamacpp.model', default=''))
    llama_timeout = int(_env_first('GLYPHOS_LLAMACPP_TIMEOUT', default=_config_value(config, 'ai_compute.llamacpp.timeout', default='300')) or '300')
    if _env_first('GLYPHOS_LLAMACPP_ENABLED', default=_config_value(config, 'ai_compute.llamacpp.enabled', default='true')).lower() != 'false':
        llamacpp = LlamaCppClient(base_url=llama_url, model=llama_model, timeout=llama_timeout)
        if llamacpp.is_available():
            clients['llamacpp'] = llamacpp

    lane_keys = ['aurora', 'terran', 'starlight', 'polaris']
    for lane in lane_keys:
        base_url = _env_first(f'GLYPHOS_LLAMACPP_{lane.upper()}_URL', default=_config_value(config, f'ai_compute.lanes.{lane}.llamacpp_url', default=''))
        if not base_url:
            continue
        model = _env_first(f'GLYPHOS_LLAMACPP_{lane.upper()}_MODEL', default=_config_value(config, f'ai_compute.lanes.{lane}.llamacpp_model', default=''))
        timeout = int(_env_first(f'GLYPHOS_LLAMACPP_{lane.upper()}_TIMEOUT', default=_config_value(config, f'ai_compute.lanes.{lane}.llamacpp_timeout', default='300')) or '300')
        client = LlamaCppClient(base_url=base_url, model=model, timeout=timeout)
        if client.is_available():
            clients[f'llamacpp-{lane}'] = client

    ollama_url = _env_first('GLYPHOS_OLLAMA_URL', 'QRBT_OLLAMA_BASE_URL', default=_config_value(config, 'ai_compute.ollama.url', default='http://localhost:11434'))
    ollama_model = _env_first('GLYPHOS_OLLAMA_MODEL', default=_config_value(config, 'ai_compute.ollama.model', default='llama3:70b'))
    ollama_timeout = int(_env_first('GLYPHOS_OLLAMA_TIMEOUT', default=_config_value(config, 'ai_compute.ollama.timeout', default='30')) or '30')
    if _env_first('GLYPHOS_OLLAMA_ENABLED', default=_config_value(config, 'ai_compute.ollama.enabled', default='true')).lower() != 'false':
        ollama = OllamaClient(base_url=ollama_url, model=ollama_model, timeout=ollama_timeout)
        if ollama.is_available():
            clients['ollama'] = ollama

    for lane in lane_keys:
        base_url = _env_first(f'GLYPHOS_OLLAMA_{lane.upper()}_URL', f'QRBT_COUNCIL_OLLAMA_{lane.upper()}_URL', default=_config_value(config, f'ai_compute.lanes.{lane}.ollama_url', default=''))
        if not base_url:
            continue
        model = _env_first(f'GLYPHOS_OLLAMA_{lane.upper()}_MODEL', default=_config_value(config, f'ai_compute.lanes.{lane}.ollama_model', default='llama3:70b'))
        timeout = int(_env_first(f'GLYPHOS_OLLAMA_{lane.upper()}_TIMEOUT', default=_config_value(config, f'ai_compute.lanes.{lane}.ollama_timeout', default='30')) or '30')
        client = OllamaClient(base_url=base_url, model=model, timeout=timeout)
        if client.is_available():
            clients[f'ollama-{lane}'] = client

    openai = OpenAIClient()
    if openai.is_available():
        clients['openai'] = openai
    anthropic = AnthropicClient()
    if anthropic.is_available():
        clients['anthropic'] = anthropic
    xai = XAIClient()
    if xai.is_available():
        clients['xai'] = xai
    return clients
