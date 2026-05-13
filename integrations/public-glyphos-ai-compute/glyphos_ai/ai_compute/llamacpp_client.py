from __future__ import annotations

import time
from typing import Any

import requests


class LlamaCppClient:
    """
    llama.cpp HTTP server client.

    Uses the OpenAI-compatible /v1/chat/completions route by default,
    with /health and /models for status checks.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        model: str = "gpt-3.5-turbo",
        timeout: int = 60,
        api_key: str = "sk-no-key-required",
        default_system: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self.default_system = default_system
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def is_available(self) -> bool:
        try:
            response = self._session.get(
                self._url("/health"),
                headers=self._headers(),
                timeout=5,
            )
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> dict[str, Any]:
        try:
            response = self._session.get(
                self._url("/models"),
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            return {"data": [], "error": str(exc)}

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        stream: bool = False,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        OpenAI-compatible chat-completions wrapper for llama.cpp.
        """
        started = time.perf_counter()

        messages = []
        effective_system = system or self.default_system
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if response_format is not None:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)

        try:
            response = self._session.post(
                self._url("/v1/chat/completions"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.perf_counter() - started) * 1000)

            choice0 = (data.get("choices") or [{}])[0]
            message = choice0.get("message") or {}
            content = message.get("content", "")

            usage = data.get("usage") or {}
            timings = data.get("timings") or {}

            return {
                "response": content,
                "model": data.get("model", payload["model"]),
                "latency_ms": latency_ms,
                "tokens_used": usage.get("completion_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "timings": timings,
                "raw": data,
            }
        except Exception as exc:
            return {
                "response": f"llama.cpp error: {exc}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "raw": {"error": str(exc)},
            }


def create_llamacpp_client(
    base_url: str = "http://localhost:8080",
    model: str = "gpt-3.5-turbo",
    timeout: int = 60,
    api_key: str = "sk-no-key-required",
    default_system: str | None = None,
) -> LlamaCppClient:
    return LlamaCppClient(
        base_url=base_url,
        model=model,
        timeout=timeout,
        api_key=api_key,
        default_system=default_system,
    )
