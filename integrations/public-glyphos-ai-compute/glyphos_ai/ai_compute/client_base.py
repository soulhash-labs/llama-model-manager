"""
Shared base types for AI compute clients.

Important:
    This module must not import api_client.py, llamacpp_client.py, or any
    provider-specific client. It is intentionally dependency-light so provider
    modules can depend on it without creating import cycles.

Current dependency graph:

    api_client.py -> client_base.py           (BaseChatClient, _result)
    api_client.py -> llamacpp_client.py        (LlamaCppClient)
    llamacpp_client.py -> client_base.py       (BaseChatClient, _result)
    client_base.py -> no project imports
"""

from __future__ import annotations

from typing import Any

import requests


def _result(
    *,
    response: str,
    latency_ms: int | None = None,
    tokens_used: int | None = None,
    raw: Any | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "response": response,
        "latency_ms": latency_ms,
        "tokens_used": tokens_used,
        "raw": raw,
    }
    payload.update(extra)
    return payload


class BaseChatClient:
    def __init__(self, model: str, max_tokens: int = 1000, timeout: int = 30):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._session = requests.Session()

    def generate(self, prompt: str, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        """Close the underlying HTTP session to free connection pool resources."""
        self._session.close()

    def __del__(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


__all__ = [
    "BaseChatClient",
    "_result",
]
