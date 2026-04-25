"""Public AI compute surface."""

from .glyph_to_prompt import glyph_to_prompt, glyph_to_structured_json
from .router import AdaptiveRouter, ComputeTarget, RoutingResult, RoutingConfig, build_router_from_env, route_with_configured_clients
from .api_client import LlamaCppClient, OpenAIClient, AnthropicClient, XAIClient, create_configured_clients

__all__ = [
    "glyph_to_prompt",
    "glyph_to_structured_json",
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
