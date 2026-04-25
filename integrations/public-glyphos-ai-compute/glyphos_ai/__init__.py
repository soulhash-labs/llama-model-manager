"""
GlyphOS AI Compute
==================
Public package for glyph encoding, coherence primitives, and AI routing.
"""

__version__ = "1.2.0"

from glyphos_ai.glyph.encoder import GlyphEncoder, encode_intent, encode_packet, decode_packet, create_packet
from glyphos_ai.glyph.types import GlyphPacket, Intent, PSI_LEVELS
from glyphos_ai.glyph.pulse import PulseService, PsiCoherenceService, create_pulse
from glyphos_ai.ai_compute.router import AdaptiveRouter, ComputeTarget, build_router_from_env, route_with_configured_clients
from glyphos_ai.ai_compute.api_client import (
    OpenAIClient,
    AnthropicClient,
    XAIClient,
    LlamaCppClient,
    create_configured_clients,
)
from glyphos_ai.ai_compute.glyph_to_prompt import glyph_to_prompt

__all__ = [
    "GlyphEncoder",
    "encode_intent",
    "encode_packet",
    "decode_packet",
    "create_packet",
    "GlyphPacket",
    "Intent",
    "PSI_LEVELS",
    "PulseService",
    "PsiCoherenceService",
    "create_pulse",
    "AdaptiveRouter",
    "ComputeTarget",
    "build_router_from_env",
    "route_with_configured_clients",
    "OpenAIClient",
    "AnthropicClient",
    "XAIClient",
    "LlamaCppClient",
    "create_configured_clients",
    "glyph_to_prompt",
]


def __getattr__(name: str):
    if name == "OllamaClient":
        from glyphos_ai.ai_compute.ollama_client import OllamaClient

        return OllamaClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
