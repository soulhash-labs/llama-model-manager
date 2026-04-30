#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import error as urerror
from urllib import request

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from lmm_errors import ProviderError, ProviderTimeoutError  # noqa: E402


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def supports_streaming(self) -> bool: ...

    def health_check(self, timeout: float = 5.0) -> bool: ...

    def metadata(self) -> dict[str, Any]: ...

    def generate(self, prompt: str, model: str = "", max_tokens: int = 1000, temperature: float = 0.7) -> str: ...

    def generate_stream(
        self,
        prompt: str,
        model: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> Iterator[str]: ...


def _http_json(
    method: str, url: str, *, payload: dict[str, Any] | None = None, timeout: float = 5.0
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except urerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return int(exc.code), parsed if isinstance(parsed, dict) else {"error": raw}
    except urerror.URLError:
        raise


def _is_timeout_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, socket.timeout) or isinstance(reason, TimeoutError)


def _sse_content(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if not stripped.startswith("data:"):
        return None

    payload = stripped[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None

    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return None

    content = delta.get("content")
    return content if isinstance(content, str) else None


class LlamaCppProvider:
    def __init__(self, base_url: str = "http://127.0.0.1:8081/v1", model: str = "", timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or "local-llama"
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "llamacpp"

    @property
    def supports_streaming(self) -> bool:
        return True

    def _resolve_model(self) -> str:
        try:
            _, payload = _http_json("GET", f"{self.base_url}/models", timeout=self.timeout)
        except Exception:
            return self.model or "local-llama"

        models = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(models, list) and models:
            first = models[0]
            if isinstance(first, dict):
                candidate = first.get("id")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            if isinstance(first, str) and first.strip():
                return first.strip()
        return self.model or "local-llama"

    def health_check(self, timeout: float = 5.0) -> bool:
        try:
            status, _ = _http_json("GET", f"{self.base_url}/models", timeout=timeout)
        except Exception:
            return False
        return status == 200

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self._resolve_model(),
            "supports_streaming": self.supports_streaming,
        }

    def generate(self, prompt: str, model: str = "", max_tokens: int = 1000, temperature: float = 0.7) -> str:
        selected_model = model or self._resolve_model()
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            status, response = _http_json(
                "POST",
                f"{self.base_url}/chat/completions",
                payload=payload,
                timeout=self.timeout,
            )
        except urerror.URLError as exc:
            if _is_timeout_error(exc):
                raise ProviderTimeoutError(self.name, self.timeout) from exc
            raise ProviderError(str(exc), provider=self.name) from exc

        if status != 200:
            message = response if isinstance(response, dict) else {}
            if isinstance(message, dict):
                message = message.get("error") or message.get("message") or f"HTTP {status}"
            raise ProviderError(f"generate failed ({status}): {message}", provider=self.name, status=status)

        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ProviderError("generate response missing choices", provider=self.name)
        choice0 = choices[0]
        if not isinstance(choice0, dict):
            raise ProviderError("generate response choice malformed", provider=self.name)
        choice_message = choice0.get("message")
        if not isinstance(choice_message, dict):
            raise ProviderError("generate response message malformed", provider=self.name)
        content = choice_message.get("content")
        if not isinstance(content, str):
            raise ProviderError("generate response content malformed", provider=self.name)
        return content

    def generate_stream(
        self,
        prompt: str,
        model: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> Iterator[str]:
        selected_model = model or self._resolve_model()
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        request_data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                if int(response.status) != 200:
                    raw = response.read().decode("utf-8", errors="replace")
                    raise ProviderError(
                        f"generate_stream failed ({response.status}): {raw or 'non-200 response'}",
                        provider=self.name,
                        status=response.status,
                    )
                for raw_line in response:
                    token = _sse_content(raw_line.decode("utf-8", errors="replace"))
                    if token:
                        yield token
        except urerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"generate_stream failed ({exc.code}): {raw}",
                provider=self.name,
                status=exc.code,
            ) from exc
        except urerror.URLError as exc:
            if _is_timeout_error(exc):
                raise ProviderTimeoutError(self.name, self.timeout) from exc
            raise ProviderError(str(exc), provider=self.name) from exc


@dataclass
class _RegisteredProvider:
    provider: Provider
    priority: int


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: list[_RegisteredProvider] = []
        self._frozen = False

    def register(self, provider: Provider, *, priority: int = 0) -> None:
        if self._frozen:
            raise RuntimeError("provider registry is frozen")
        self._providers.append(_RegisteredProvider(provider=provider, priority=priority))

    def unregister(self, name: str) -> bool:
        original = len(self._providers)
        self._providers = [entry for entry in self._providers if entry.provider.name != name]
        return len(self._providers) < original

    def get(self, name: str) -> Provider | None:
        for entry in self._providers:
            if entry.provider.name == name:
                return entry.provider
        return None

    def list_all(self) -> list[Provider]:
        ordered = sorted(self._providers, key=lambda entry: entry.priority, reverse=True)
        return [entry.provider for entry in ordered]

    def select(self, *, streaming: bool = False, preferred: str | None = None) -> Provider | None:
        if preferred:
            for entry in self._providers:
                if entry.provider.name == preferred:
                    return entry.provider

        ordered = self.list_all()
        if streaming:
            for provider in ordered:
                if provider.supports_streaming:
                    return provider
            return None

        return ordered[0] if ordered else None

    def freeze(self) -> None:
        self._frozen = True


def create_default_registry() -> ProviderRegistry:
    backend_base_url = os.environ.get("LLAMA_MODEL_BACKEND_BASE_URL", "http://127.0.0.1:8081/v1")
    timeout_text = os.environ.get("LMM_GATEWAY_TIMEOUT_SECONDS", "300")
    try:
        timeout_seconds = float(timeout_text)
    except ValueError as exc:
        raise ValueError(f"Invalid LMM_GATEWAY_TIMEOUT_SECONDS value: {timeout_text}") from exc

    registry = ProviderRegistry()
    registry.register(
        LlamaCppProvider(base_url=backend_base_url, timeout=timeout_seconds),
        priority=10,
    )
    return registry


__all__ = [
    "Provider",
    "LlamaCppProvider",
    "ProviderRegistry",
    "create_default_registry",
]
