"""
GlyphOS AI Compute
==================
Public package for glyph encoding, coherence primitives, and AI routing.
"""

__version__ = "1.2.0"

from glyphos_ai.ai_compute.api_client import (
    AnthropicClient,
    LlamaCppClient,
    OpenAIClient,
    XAIClient,
    create_configured_clients,
)
from glyphos_ai.ai_compute.glyph_to_prompt import build_prompt_from_packet, glyph_to_prompt, glyph_to_structured_json
from glyphos_ai.ai_compute.router import (
    AdaptiveRouter,
    ComputeTarget,
    RoutingResult,
    build_router_from_env,
    route_with_configured_clients,
)
from glyphos_ai.glyph.encoder import GlyphEncoder, create_packet, decode_packet, encode_intent, encode_packet
from glyphos_ai.glyph.pulse import PsiCoherenceService, PulseService, create_pulse
from glyphos_ai.glyph.types import PSI_LEVELS, ContextPacket, ContextPayload, GlyphPacket, Intent, RoutingHints

__all__ = [
    "GlyphEncoder",
    "encode_intent",
    "encode_packet",
    "decode_packet",
    "create_packet",
    "GlyphPacket",
    "Intent",
    "PSI_LEVELS",
    "ContextPayload",
    "ContextPacket",
    "RoutingHints",
    "PulseService",
    "PsiCoherenceService",
    "create_pulse",
    "AdaptiveRouter",
    "ComputeTarget",
    "RoutingResult",
    "build_router_from_env",
    "route_with_configured_clients",
    "OpenAIClient",
    "AnthropicClient",
    "XAIClient",
    "LlamaCppClient",
    "create_configured_clients",
    "glyph_to_prompt",
    "glyph_to_structured_json",
    "build_prompt_from_packet",
]


def __getattr__(name: str):
    if name == "OllamaClient":
        from glyphos_ai.ai_compute.ollama_client import OllamaClient

        return OllamaClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
