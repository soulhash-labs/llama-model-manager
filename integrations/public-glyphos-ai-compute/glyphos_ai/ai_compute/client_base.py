"""
Shared client primitives extracted from api_client.py to break the circular
import between api_client and llamacpp_client.

api_client imports LlamaCppClient from llamacpp_client, and llamacpp_client
imports BaseChatClient + _result from here — no cycle.
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


__all__ = [
    "BaseChatClient",
    "_result",
]
