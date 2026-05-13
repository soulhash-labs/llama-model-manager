"""
GlyphOS AI Compute
==================

Public package surface for glyph-first routing and prompt shaping.

Scope:
- glyph-first prompt shaping
- explicit, injected upstream context
- adaptive routing across configured inference backends

Non-scope:
- retrieval
- indexing
- search
- hidden I/O
- implicit context loading

All grounded context must be supplied by the upstream harness / orchestrator.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

try:
    __version__ = _pkg_version("glyphos-ai-compute")
except PackageNotFoundError:
    __version__ = "0.0.0"


# ---------------------------------------------------------------------------
# Public glyph contract surface
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Prompt shaping
# ---------------------------------------------------------------------------
from .ai_compute.glyph_to_prompt import (
    glyph_to_prompt,
    glyph_to_structured_json,
)

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
from .ai_compute.router import (
    AdaptiveRouter,
    ComputeTarget,
    RoutingConfig,
    RoutingResult,
    build_router_from_env,
    route_with_configured_clients,
)
from .glyph.codec import (
    GlyphCodecError,
    ParsedToken,
    bytes_to_glyph_stream,
    bytes_to_json,
    decode_bytes_to_entries,
    decode_bytes_to_glyphs,
    decode_bytes_to_names,
    dump_json,
    encode_entries_to_bytes,
    encode_glyphs_to_bytes,
    encode_names_to_bytes,
    glyph_stream_to_bytes,
    glyph_stream_to_json,
    normalize_glyph_stream,
    tokenize_glyph_stream,
)

# ---------------------------------------------------------------------------
# Public glyph registry / codec surface
# ---------------------------------------------------------------------------
from .glyph.registry import (
    GlyphEntry,
    GlyphRegistry,
    GlyphRegistryError,
    load_registry,
)
from .glyph.types import (
    ACTION_MAP,
    DEST_MAP,
    PSI_LEVELS,
    ContextPacket,
    GlyphPacket,
    Glyphs,
    Intent,
    Locality,
    PreferredBackend,
    RoutingHints,
    action_to_glyph,
    destination_to_glyph,
    level_to_psi,
    normalize_psi,
    normalize_time_slot,
    packet_to_compat_dict,
    psi_to_level,
    slot_to_time,
    time_to_slot,
    validate_context_packet_shape,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # package
    "__version__",
    # public types
    "ACTION_MAP",
    "DEST_MAP",
    "PSI_LEVELS",
    "ContextPacket",
    "GlyphPacket",
    "Glyphs",
    "Intent",
    "Locality",
    "PreferredBackend",
    "RoutingHints",
    "action_to_glyph",
    "destination_to_glyph",
    "level_to_psi",
    "normalize_psi",
    "normalize_time_slot",
    "packet_to_compat_dict",
    "psi_to_level",
    "slot_to_time",
    "time_to_slot",
    "validate_context_packet_shape",
    # glyph registry / codec
    "GlyphEntry",
    "GlyphRegistry",
    "GlyphRegistryError",
    "load_registry",
    "GlyphCodecError",
    "ParsedToken",
    "bytes_to_glyph_stream",
    "bytes_to_json",
    "decode_bytes_to_entries",
    "decode_bytes_to_glyphs",
    "decode_bytes_to_names",
    "dump_json",
    "encode_entries_to_bytes",
    "encode_glyphs_to_bytes",
    "encode_names_to_bytes",
    "glyph_stream_to_bytes",
    "glyph_stream_to_json",
    "normalize_glyph_stream",
    "tokenize_glyph_stream",
    # prompt shaping
    "glyph_to_prompt",
    "glyph_to_structured_json",
    # routing
    "AdaptiveRouter",
    "ComputeTarget",
    "RoutingConfig",
    "RoutingResult",
    "build_router_from_env",
    "route_with_configured_clients",
]
