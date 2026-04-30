#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import sys
from collections.abc import Iterator
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
    """Small stdlib helper for JSON request/response interactions.

    Mirrors the pattern used by the existing gateway helper:
    `urllib.request.Request` + `urlopen` + JSON decode.
    """

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


def _parse_sse_chunks(lines: list[str]) -> Iterator[str]:
    for line in lines:
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            message = json.loads(payload)
        except Exception:
            continue
        choices = message.get("choices") if isinstance(message, dict) else None
        if not isinstance(choices, list) or not choices:
            continue
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield content


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
        resolved_model = model or self._resolve_model()
        payload = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            status, response = _http_json(
                "POST", f"{self.base_url}/chat/completions", payload=payload, timeout=self.timeout
            )
        except urerror.URLError as exc:
            if _is_timeout_error(exc):
                raise ProviderTimeoutError(self.name, self.timeout) from exc
            raise ProviderError(str(exc), provider=self.name) from exc

        if status != 200:
            message = response
            if isinstance(message, dict):
                message = message.get("error") or message.get("message") or f"HTTP {status}"
            raise ProviderError(f"generate failed ({status}): {message}", provider=self.name, status=status)

        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ProviderError("generate response missing choices", provider=self.name)
        choice0 = choices[0]
        if not isinstance(choice0, dict):
            raise ProviderError("generate response choice malformed", provider=self.name)
        message = choice0.get("message")
        if not isinstance(message, dict):
            raise ProviderError("generate response message malformed", provider=self.name)
        content = message.get("content")
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
        resolved_model = model or self._resolve_model()
        payload = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
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
                lines_buffer: list[str] = []
                for chunk in response:
                    decoded = chunk.decode("utf-8", errors="replace")
                    lines_buffer.append(decoded)
                    yield from _parse_sse_chunks(lines_buffer)
                    lines_buffer.clear()
        except urerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"generate_stream failed ({exc.code}): {raw}", provider=self.name, status=exc.code
            ) from exc
        except urerror.URLError as exc:
            if _is_timeout_error(exc):
                raise ProviderTimeoutError(self.name, self.timeout) from exc
            raise ProviderError(str(exc), provider=self.name) from exc


__all__ = [
    "Provider",
    "LlamaCppProvider",
]
