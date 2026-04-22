"""Public AI compute surface."""

from .glyph_to_prompt import glyph_to_prompt, glyph_to_structured_json
from .router import AdaptiveRouter, ComputeTarget, RoutingResult, RoutingConfig, build_router_from_env, route_with_configured_clients
from .api_client import LlamaCppClient, OllamaClient, OpenAIClient, AnthropicClient, XAIClient, create_configured_clients

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
    "OllamaClient",
    "OpenAIClient",
    "AnthropicClient",
    "XAIClient",
    "create_configured_clients",
]
