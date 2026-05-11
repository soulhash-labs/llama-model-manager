#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


class LMMError(Exception):
    """Base error carrying machine-readable context for LMM Python surfaces."""

    error_type = "lmm_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": self.message, "type": self.error_type}
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(LMMError, ValueError):
    error_type = "configuration_error"


class InvalidRequestError(LMMError, ValueError):
    error_type = "invalid_request_error"


class GatewayError(LMMError):
    error_type = "lmm_gateway_error"


class ProviderError(LMMError):
    error_type = "provider_error"


class ProviderTimeoutError(ProviderError):
    error_type = "provider_timeout_error"

    def __init__(self, provider: str, timeout_seconds: float, message: str | None = None) -> None:
        super().__init__(
            message or f"{provider} timed out after {timeout_seconds}s",
            provider=provider,
            timeout_seconds=timeout_seconds,
        )


class RoutingError(LMMError):
    error_type = "routing_error"


class StorageError(LMMError):
    error_type = "storage_error"
