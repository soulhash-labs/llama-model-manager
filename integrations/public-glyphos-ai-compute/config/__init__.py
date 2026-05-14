"""
Compatibility shim for integration-level config imports.

Canonical config loader lives at:

    glyphos_ai.config

Prefer:

    from glyphos_ai.config import load_config
"""

from __future__ import annotations

from glyphos_ai.config import (  # type: ignore[import-untyped]
    DEFAULT_CONFIG_ENV,
    DEFAULT_CONFIG_PACKAGE,
    DEFAULT_CONFIG_RESOURCE,
    ConfigError,
    deep_merge,
    default_config_path,
    get_in,
    load_config,
    load_default_config,
    load_explicit_config,
    load_yaml_file,
)

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
