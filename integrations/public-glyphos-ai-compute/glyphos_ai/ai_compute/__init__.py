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
from .semantic_decoder import (
    SemanticDecodingError,
    decode_intent_dict_from_glyphs,
    decode_intent_from_glyphs,
    parse_semantic_wire,
    semantic_decoding_manifest,
)
from .semantic_decoder import (
    SemanticIntentPayload as DecodedSemanticPayload,
)
from .semantic_encoder import (
    SemanticEncodingError,
    SemanticIntentPayload,
    encode_intent_to_glyphs,
    encode_packet_to_glyphs,
    semantic_encoding_manifest,
    semantic_payload_from_intent,
    semantic_payload_from_packet,
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
    "SemanticIntentPayload",
    "DecodedSemanticPayload",
    "SemanticEncodingError",
    "SemanticDecodingError",
    "semantic_payload_from_intent",
    "semantic_payload_from_packet",
    "encode_intent_to_glyphs",
    "encode_packet_to_glyphs",
    "decode_intent_from_glyphs",
    "decode_intent_dict_from_glyphs",
    "parse_semantic_wire",
    "semantic_encoding_manifest",
    "semantic_decoding_manifest",
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
