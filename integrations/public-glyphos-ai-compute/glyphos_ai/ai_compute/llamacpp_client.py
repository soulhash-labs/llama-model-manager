"""llama.cpp HTTP server client.

Uses the OpenAI-compatible /v1/chat/completions route by default,
with /health and /models for status checks.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from .client_base import BaseChatClient, _result

DEFAULT_LLAMACPP_BASE_URL = os.getenv(
    "LLAMACPP_BASE_URL",
    "http://127.0.0.1:8081",
)


class LlamaCppClient(BaseChatClient):
    """
    OpenAI-compatible llama.cpp client.

    Accepts base_url as either:
    - http://127.0.0.1:8081
    - http://127.0.0.1:8081/v1
    """

    def __init__(
        self,
        base_url: str = DEFAULT_LLAMACPP_BASE_URL,
        model: str = "",
        max_tokens: int = 1000,
        timeout: int = 300,
        api_key: str = "sk-no-key-required",
        default_system: str | None = None,
    ):
        super().__init__(model=model, max_tokens=max_tokens, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_system = default_system

    @property
    def _root_url(self) -> str:
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    @property
    def _v1_url(self) -> str:
        return self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

    def _models_url(self) -> str:
        return f"{self._root_url}/models"

    def _health_url(self) -> str:
        return f"{self._root_url}/health"

    def _chat_url(self) -> str:
        return f"{self._v1_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def is_available(self) -> bool:
        try:
            response = self._session.get(self._health_url(), headers=self._headers(), timeout=5)
            if response.status_code == 200:
                return True
        except Exception:
            pass

        try:
            response = self._session.get(self._models_url(), headers=self._headers(), timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        try:
            response = self._session.get(self._models_url(), headers=self._headers(), timeout=10)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            for item in models:
                if isinstance(item, dict) and item.get("id"):
                    return str(item["id"])
        except Exception:
            pass
        return "local-llama"

    def list_models(self) -> dict[str, Any]:
        try:
            response = self._session.get(self._models_url(), headers=self._headers(), timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            return {"data": [], "error": str(exc)}

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> dict[str, Any]:
        started = time.perf_counter()

        messages = []
        system = kwargs.get("system", self.default_system)
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": kwargs.get("model", self._resolve_model()),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": kwargs.get("stream", False),
        }

        if "response_format" in kwargs and kwargs["response_format"] is not None:
            payload["response_format"] = kwargs["response_format"]

        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], Mapping):
            payload.update(dict(kwargs["extra_body"]))

        try:
            response = self._session.post(
                self._chat_url(),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.perf_counter() - started) * 1000)
            choice0 = (data.get("choices") or [{}])[0]
            message = choice0.get("message") or {}
            usage = data.get("usage") or {}
            timings = data.get("timings") or {}

            return _result(
                response=message.get("content", ""),
                latency_ms=latency_ms,
                tokens_used=usage.get("completion_tokens"),
                raw=data,
                prompt_tokens=usage.get("prompt_tokens"),
                total_tokens=usage.get("total_tokens"),
                timings=timings,
                model=data.get("model", payload["model"]),
            )
        except Exception as exc:
            return _result(
                response=f"llama.cpp error: {exc}",
                latency_ms=int((time.perf_counter() - started) * 1000),
                raw={"error": str(exc)},
            )


def create_llamacpp_client(
    base_url: str = DEFAULT_LLAMACPP_BASE_URL,
    model: str = "",
    max_tokens: int = 1000,
    timeout: int = 300,
    api_key: str = "sk-no-key-required",
    default_system: str | None = None,
) -> LlamaCppClient:
    return LlamaCppClient(
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
        api_key=api_key,
        default_system=default_system,
    )


__all__ = [
    "LlamaCppClient",
    "create_llamacpp_client",
]
