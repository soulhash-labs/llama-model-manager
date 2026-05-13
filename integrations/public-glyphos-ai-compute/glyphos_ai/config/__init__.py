"""
GlyphOS config helpers

======================

Purpose:
- expose package-bundled default config
- allow explicit config-file loading
- support explicit deep-merge of defaults + overrides
- keep local-config reads opt-in only

Non-goals:
- no auto-loading at import time
- no hidden I/O in route path
- no global mutable singleton config state
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PACKAGE = "glyphos_ai.config"
DEFAULT_CONFIG_RESOURCE = "default.yaml"
DEFAULT_CONFIG_ENV = "GLYPHOS_CONFIG_FILE"

__all__ = [
    "DEFAULT_CONFIG_PACKAGE",
    "DEFAULT_CONFIG_RESOURCE",
    "DEFAULT_CONFIG_ENV",
    "ConfigError",
    "default_config_path",
    "load_default_config",
    "load_yaml_file",
    "load_explicit_config",
    "load_config",
    "deep_merge",
    "get_in",
]


class ConfigError(RuntimeError):
    """Raised when a config file or resource cannot be loaded or parsed."""


def _ensure_mapping(value: Any, *, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"Config from {source} must decode to a mapping/object")
    return dict(value)


def default_config_path() -> Path:
    """Return the package resource path for the bundled default config."""
    resource = files(DEFAULT_CONFIG_PACKAGE).joinpath(DEFAULT_CONFIG_RESOURCE)
    return Path(str(resource))


@lru_cache(maxsize=1)
def load_default_config() -> dict[str, Any]:
    """
    Load the bundled default config from glyphos_ai/config/default.yaml.

    Cached because the package default should be immutable for a process lifetime.
    """
    resource = files(DEFAULT_CONFIG_PACKAGE).joinpath(DEFAULT_CONFIG_RESOURCE)
    try:
        with resource.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle.read())
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Bundled config resource not found: {DEFAULT_CONFIG_PACKAGE}/{DEFAULT_CONFIG_RESOURCE}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Bundled config YAML is invalid: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to load bundled config resource: {exc}") from exc

    return _ensure_mapping(loaded, source="package default")


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """
    Load an arbitrary YAML config file from disk.

    This is explicit I/O. Callers must opt into using it.
    """
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ConfigError(f"Config file does not exist: {file_path}")

    try:
        raw = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise ConfigError(f"Failed to read config file {file_path}: {exc}") from exc

    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file {file_path}: {exc}") from exc

    return _ensure_mapping(loaded, source=str(file_path))


def load_explicit_config(config_file: str | Path | None = None) -> dict[str, Any]:
    """
    Load an explicit local/operator config.

    Resolution order:
    1. provided config_file
    2. GLYPHOS_CONFIG_FILE env var

    Returns {} if neither is set.
    """
    if config_file is not None:
        return load_yaml_file(config_file)

    env_path = os.environ.get(DEFAULT_CONFIG_ENV, "").strip()
    if env_path:
        return load_yaml_file(Path(env_path).expanduser())

    return {}


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """
    Recursively merge two config mappings.

    Rules:
    - dict + dict -> recursive merge
    - any other type -> override wins
    - inputs are never mutated
    """
    result: dict[str, Any] = deepcopy(dict(base))

    for key, value in override.items():
        if key in result and isinstance(result[key], Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(
                dict(result[key]),  # type: ignore[arg-type]
                dict(value),
            )
        else:
            result[key] = deepcopy(value)

    return result


def load_config(
    *,
    config_file: str | Path | None = None,
    allow_local_config: bool = False,
    extra_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Load the effective GlyphOS config.

    Always starts from packaged defaults.
    Local/operator config is applied only when allow_local_config=True.
    Optional in-memory overrides apply last.

    This keeps the route path deterministic by default while still allowing
    operator/UI code to opt in explicitly.
    """
    config = load_default_config()

    if allow_local_config:
        local_cfg = load_explicit_config(config_file=config_file)
        if local_cfg:
            config = deep_merge(config, local_cfg)

    if extra_overrides:
        config = deep_merge(config, dict(extra_overrides))

    return config


def get_in(mapping: Mapping[str, Any], dotted_key: str, default: Any = None) -> Any:
    """
    Read a nested value using dotted-key syntax.

    Example:
        get_in(cfg, "ai_compute.routing.default_lane")
    """
    current: Any = mapping
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current
