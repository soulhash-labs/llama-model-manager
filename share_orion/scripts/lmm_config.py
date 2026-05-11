#!/usr/bin/env python3
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Self-contained import: ensure sibling lmm_errors is reachable when this
# module is loaded directly (e.g. by web/app.py without scripts/ on sys.path).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_SCRIPT_DIR))

from lmm_errors import ConfigurationError  # noqa: E402


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _bool_env(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be boolean-like", variable=name, value=value)


def _int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    value = _env(name)
    if not value:
        number = default
    else:
        try:
            number = int(value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be an integer", variable=name, value=value) from exc
    if minimum is not None and number < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}", variable=name, value=number)
    if maximum is not None and number > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}", variable=name, value=number)
    return number


def _float_env(name: str, default: float, *, minimum: float | None = None) -> float:
    value = _env(name)
    if not value:
        number = default
    else:
        try:
            number = float(value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be a number", variable=name, value=value) from exc
    if minimum is not None and number < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}", variable=name, value=number)
    return number


def _url(value: str, *, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{field} must be an http(s) URL", field=field, value=value)
    return value.rstrip("/")


@dataclass(frozen=True)
class GatewayConfig:
    host: str = "127.0.0.1"
    port: int = 4010
    backend_base_url: str = "http://127.0.0.1:8081/v1"
    model_id: str = ""
    state_file: Path = Path.home() / ".local" / "state" / "llama-server" / "lmm-gateway-requests.json"
    sse_heartbeat_seconds: float = 5.0
    telemetry_recent_limit: int = 40
    mode: str = "full"
    fast_enabled: bool = True
    fast_port: int = 4011
    fast_context_timeout_ms: int = 500
    fast_context_stream_timeout_ms: int = 250

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ConfigurationError("gateway host cannot be empty", field="host")
        if self.port < 1 or self.port > 65535:
            raise ConfigurationError("gateway port out of range", field="port", value=self.port)
        _url(self.backend_base_url, field="backend_base_url")
        if self.sse_heartbeat_seconds <= 0:
            raise ConfigurationError("SSE heartbeat must be positive", field="sse_heartbeat_seconds")
        if self.telemetry_recent_limit < 1:
            raise ConfigurationError("telemetry recent limit must be positive", field="telemetry_recent_limit")
        if self.mode not in {"full", "fast"}:
            raise ConfigurationError("gateway mode must be full or fast", field="mode", value=self.mode)
        if self.fast_port < 1 or self.fast_port > 65535:
            raise ConfigurationError("fast gateway port out of range", field="fast_port", value=self.fast_port)
        if self.fast_context_timeout_ms < 1:
            raise ConfigurationError(
                "fast context timeout must be positive",
                field="fast_context_timeout_ms",
                value=self.fast_context_timeout_ms,
            )
        if self.fast_context_stream_timeout_ms < 1:
            raise ConfigurationError(
                "fast stream context timeout must be positive",
                field="fast_context_stream_timeout_ms",
                value=self.fast_context_stream_timeout_ms,
            )


@dataclass(frozen=True)
class ContextConfig:
    enabled: bool = False
    timeout_ms: int = 1500
    stream_timeout_ms: int = 500
    index_timeout_ms: int = 2000
    command: str = ""

    def __post_init__(self) -> None:
        if self.timeout_ms < 1:
            raise ConfigurationError("Context MCP timeout must be positive", field="timeout_ms", value=self.timeout_ms)
        if self.stream_timeout_ms < 1:
            raise ConfigurationError(
                "Context MCP stream timeout must be positive",
                field="stream_timeout_ms",
                value=self.stream_timeout_ms,
            )
        if self.index_timeout_ms < 0:
            raise ConfigurationError(
                "Context MCP index timeout must be non-negative",
                field="index_timeout_ms",
                value=self.index_timeout_ms,
            )


@dataclass(frozen=True)
class GlyphEncodingConfig:
    disabled: bool = False
    force_error: bool = False


@dataclass(frozen=True)
class UpdateWatcherConfig:
    enabled: bool = False
    check_interval_hours: int = 12
    lmm_repo: str = "soulhash-labs/llama-model-manager"
    llamacpp_repo: str = "ggml-org/llama.cpp"
    timeout_seconds: int = 5
    state_file: Path = Path.home() / ".local" / "state" / "llama-server" / "lmm-updates.json"

    def __post_init__(self) -> None:
        if self.check_interval_hours < 1 or self.check_interval_hours > 168:
            raise ConfigurationError(
                "Update check interval must be between 1 and 168 hours",
                field="check_interval_hours",
                value=self.check_interval_hours,
            )
        if self.timeout_seconds < 1 or self.timeout_seconds > 30:
            raise ConfigurationError(
                "Update watcher timeout must be between 1 and 30 seconds",
                field="timeout_seconds",
                value=self.timeout_seconds,
            )


@dataclass(frozen=True)
class LMMConfig:
    gateway: GatewayConfig
    context: ContextConfig
    glyph_encoding: GlyphEncodingConfig
    update_watcher: UpdateWatcherConfig


def default_state_file() -> Path:
    state_home = Path(_env("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))).expanduser()
    return state_home / "llama-server" / "lmm-gateway-requests.json"


def default_update_state_file() -> Path:
    state_home = Path(_env("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))).expanduser()
    return state_home / "llama-server" / "lmm-updates.json"


def load_lmm_config_from_env() -> LMMConfig:
    gateway = GatewayConfig(
        host=_env("LLAMA_MODEL_GATEWAY_HOST", "127.0.0.1"),
        port=_int_env("LLAMA_MODEL_GATEWAY_PORT", 4010, minimum=1, maximum=65535),
        backend_base_url=_url(
            _env("LLAMA_MODEL_BACKEND_BASE_URL", "http://127.0.0.1:8081/v1"), field="backend_base_url"
        ),
        model_id=_env("LLAMA_MODEL_GATEWAY_MODEL_ID", ""),
        state_file=Path(_env("LMM_GATEWAY_STATE_FILE", str(default_state_file()))).expanduser(),
        sse_heartbeat_seconds=_float_env("LMM_GATEWAY_SSE_HEARTBEAT_SECONDS", 5.0, minimum=0.01),
        telemetry_recent_limit=_int_env("LMM_GATEWAY_RECENT_LIMIT", 40, minimum=1, maximum=500),
        mode=_env("LMM_GATEWAY_MODE", "full"),
        fast_enabled=_bool_env("LMM_GATEWAY_FAST_ENABLED", True),
        fast_port=_int_env("LLAMA_MODEL_GATEWAY_FAST_PORT", 4011, minimum=1, maximum=65535),
        fast_context_timeout_ms=_int_env("LMM_GATEWAY_FAST_CONTEXT_TIMEOUT_MS", 500, minimum=1),
        fast_context_stream_timeout_ms=_int_env("LMM_GATEWAY_FAST_CONTEXT_STREAM_TIMEOUT_MS", 250, minimum=1),
    )
    context = ContextConfig(
        enabled=_bool_env("LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE", False),
        timeout_ms=_int_env("LMM_CONTEXT_MCP_TIMEOUT_MS", 1500, minimum=1),
        stream_timeout_ms=_int_env("LMM_CONTEXT_MCP_STREAM_TIMEOUT_MS", 500, minimum=1),
        index_timeout_ms=_int_env("LMM_CONTEXT_MCP_INDEX_TIMEOUT_MS", 2000, minimum=0),
        command=_env("LMM_CONTEXT_MCP_COMMAND", ""),
    )
    glyph_encoding = GlyphEncodingConfig(
        disabled=_bool_env("LMM_GLYPH_ENCODING_DISABLED", False),
        force_error=bool(_env("LMM_GLYPH_ENCODING_FORCE_ERROR", "")),
    )
    update_watcher = UpdateWatcherConfig(
        enabled=_bool_env("LMM_UPDATE_WATCHER_ENABLED", False),
        check_interval_hours=_int_env(
            "LMM_UPDATE_CHECK_INTERVAL_HOURS",
            12,
            minimum=1,
            maximum=168,
        ),
        lmm_repo=_env("LMM_UPDATE_LMM_REPO", "soulhash-labs/llama-model-manager"),
        llamacpp_repo=_env("LMM_UPDATE_LLAMACPP_REPO", "ggml-org/llama.cpp"),
        timeout_seconds=_int_env("LMM_UPDATE_TIMEOUT_SECONDS", 5, minimum=1, maximum=30),
        state_file=Path(_env("LMM_UPDATE_STATE_FILE", str(default_update_state_file()))).expanduser(),
    )
    return LMMConfig(
        gateway=gateway,
        context=context,
        glyph_encoding=glyph_encoding,
        update_watcher=update_watcher,
    )
