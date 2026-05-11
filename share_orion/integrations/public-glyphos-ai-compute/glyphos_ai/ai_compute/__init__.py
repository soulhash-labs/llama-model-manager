"""
Public AI compute surface.

Scope:
- glyph-first prompt shaping
- adaptive routing
- explicit upstream context on the public route path
- local/context payload prompt assembly helpers

Non-scope:
- retrieval
- indexing
- hidden I/O
"""

from __future__ import annotations

from .api_client import (
    AnthropicClient,
    LlamaCppClient,
    OpenAIClient,
    XAIClient,
    create_configured_clients,
)
from .glyph_to_prompt import build_prompt_from_packet, glyph_to_prompt, glyph_to_structured_json
from .router import (
    AdaptiveRouter,
    ComputeTarget,
    RoutingConfig,
    RoutingResult,
    build_router_from_env,
    route_with_configured_clients,
)

__all__ = [
    "glyph_to_prompt",
    "glyph_to_structured_json",
    "build_prompt_from_packet",
    "AdaptiveRouter",
    "ComputeTarget",
    "RoutingResult",
    "RoutingConfig",
    "build_router_from_env",
    "route_with_configured_clients",
    "LlamaCppClient",
    "OpenAIClient",
    "AnthropicClient",
    "XAIClient",
    "create_configured_clients",
]


def __getattr__(name: str):
    if name in {"OllamaClient", "create_ollama_client"}:
        from .ollama_client import OllamaClient, create_ollama_client

        removed = {
            "OllamaClient": OllamaClient,
            "create_ollama_client": create_ollama_client,
        }
        return removed[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
