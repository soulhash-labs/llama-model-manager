"""
Glyph Types
===========
Python types matching the TypeScript glyph_types.ts, plus explicit
upstream-context support for harness-driven routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

# === Public context contract ===

Locality = Literal["orion-local", "lan", "cloud", "external"]
PreferredBackend = Literal["llamacpp", "openai", "anthropic", "xai", "local", "external"]


class RoutingHints(TypedDict, total=False):
    preferred_backend: PreferredBackend
    token_budget: int
    preferred_lane: str
    max_latency_ms: int


class ContextPacket(TypedDict, total=False):
    """Explicit upstream context contract for harness/orchestrator integration."""

    content: str
    locality: Locality
    freshness: float | None
    provenance: list[str]
    routing_hints: RoutingHints
    metadata: dict[str, Any]
    source: str


# === Glyph Constants ===


class Glyphs:
    """Glyph constants matching TypeScript glyph_types.ts"""

    # === ACTIONS (64) ===
    ACTION_BOOK = "⊕"
    ACTION_QUERY = "?"
    ACTION_CREATE = "+"
    ACTION_DELETE = "×"
    ACTION_UPDATE = "↔"
    ACTION_EXECUTE = "▶"
    ACTION_PAUSE = "⏸"
    ACTION_STOP = "■"
    ACTION_RESET = "⟲"
    ACTION_SYNC = "↻"
    ACTION_MERGE = "⊎"
    ACTION_SPLIT = "⊔"
    ACTION_VERIFY = "✓"
    ACTION_REJECT = "✗"
    ACTION_APPROVE = "✓"
    ACTION_DENY = "⊘"
    ACTION_GRANT = "⊕"
    ACTION_REVOKE = "⊖"
    ACTION_SUSPEND = "⊝"
    ACTION_RESUME = "⊜"
    ACTION_LOCK = "⊘"
    ACTION_UNLOCK = "⊚"
    ACTION_ARCHIVE = "⊰"
    ACTION_RESTORE = "⊱"
    ACTION_EXPORT = "⤓"
    ACTION_IMPORT = "⤒"
    ACTION_BACKUP = "◉"
    ACTION_SCAN = "⊡"
    ACTION_SEND = "➤"
    ACTION_RECEIVE = "◂"
    ACTION_BROADCAST = "◃"
    ACTION_SUBSCRIBE = "⊲"
    ACTION_PUBLISH = "⊳"
    ACTION_ENCRYPT = "⊛"
    ACTION_DECRYPT = "⊚"
    ACTION_COMPRESS = "⊜"
    ACTION_DECOMPRESS = "⊝"
    ACTION_VALIDATE = "⊠"
    ACTION_CALCULATE = "⊟"
    ACTION_PREDICT = "⊦"
    ACTION_LEARN = "⊧"
    ACTION_TEACH = "⊨"
    ACTION_ANALYZE = "⊩"
    ACTION_SYNTHESIZE = "⊪"
    ACTION_TRANSFORM = "⊫"
    ACTION_FILTER = "⊬"
    ACTION_SORT = "⊭"
    ACTION_AGGREGATE = "⊮"
    ACTION_DISAGGREGATE = "⊯"
    ACTION_TRACK = "⊰"
    ACTION_MONITOR = "⊱"
    ACTION_ALERT = "⊲"
    ACTION_LOG = "⊳"
    ACTION_REPORT = "⊴"
    ACTION_NOTIFY = "⊵"
    ACTION_REQUEST = "⊶"
    ACTION_RESPONSE = "⊷"
    ACTION_ACKNOWLEDGE = "⊸"
    ACTION_CONFIRM = "⊹"
    ACTION_CANCEL = "⊺"
    ACTION_DELAY = "⊻"
    ACTION_RETRY = "⊼"
    ACTION_TIMEOUT = "⊽"
    ACTION_REDIRECT = "⊾"
    ACTION_ROUTE = "⊿"

    # === ENTITIES (64) ===
    DEST_MARS = "MRS"
    DEST_MOON = "MON"
    DEST_EARTH = "ERTH"
    DEST_STAR = "STAR"
    DEST_PLANET = "PLNT"
    DEST_GALAXY = "GALX"
    DEST_UNIVERSE = "UNIV"
    DEST_DIMENSION = "DIM"
    DEST_REALITY = "REAL"
    DEST_AURORA = "AUR"
    DEST_TERRAN = "TER"
    DEST_STARLIGHT = "STL"
    DEST_POLARIS = "PLR"
    ENTITY_MODEL = "MDL"
    ENTITY_DATASET = "DAT"
    ENTITY_PRESET = "PRS"
    ENTITY_LICENSE = "LIC"
    ENTITY_USER = "USR"
    ENTITY_WALLET = "WAL"
    ENTITY_CONTRACT = "CTR"
    ENTITY_TOKEN = "TKN"
    ENTITY_RECEIPT = "RCP"
    ENTITY_ATTEST = "ATT"
    ENTITY_HASH = "HSH"
    ENTITY_SIGNATURE = "SIG"
    ENTITY_KEY = "KEY"
    ENTITY_NODE = "ND"
    ENTITY_CLUSTER = "CLS"
    ENTITY_SERVICE = "SVC"
    ENTITY_API = "API"
    ENTITY_ENDPOINT = "EPT"
    ENTITY_DATABASE = "DB"
    ENTITY_FILE = "FILE"
    ENTITY_IMAGE = "IMG"
    ENTITY_AUDIO = "AUD"
    ENTITY_VIDEO = "VID"
    ENTITY_TEXT = "TXT"
    ENTITY_JSON = "JSON"
    ENTITY_WORKFLOW = "WF"
    ENTITY_JOB = "JOB"
    ENTITY_TASK = "TSK"
    ENTITY_EVENT = "EVT"
    ENTITY_LOG = "LOG"
    ENTITY_METRIC = "MET"
    ENTITY_ALERT = "ALR"
    ENTITY_DASHBOARD = "DSH"
    ENTITY_REPORT = "RPT"

    # === TIME ===
    HEADER = "H"
    SEPARATOR = "|"
    END = ">"
    COHERENCE = "Ψ"  # Psi for coherence


# === Action Mapping ===
ACTION_MAP = {
    "BOOK": Glyphs.ACTION_BOOK,
    "QUERY": Glyphs.ACTION_QUERY,
    "CREATE": Glyphs.ACTION_CREATE,
    "DELETE": Glyphs.ACTION_DELETE,
    "UPDATE": Glyphs.ACTION_UPDATE,
    "EXECUTE": Glyphs.ACTION_EXECUTE,
    "PAUSE": Glyphs.ACTION_PAUSE,
    "STOP": Glyphs.ACTION_STOP,
    "RESET": Glyphs.ACTION_RESET,
    "SYNC": Glyphs.ACTION_SYNC,
    "MERGE": Glyphs.ACTION_MERGE,
    "VERIFY": Glyphs.ACTION_VERIFY,
    "APPROVE": Glyphs.ACTION_APPROVE,
    "DENY": Glyphs.ACTION_DENY,
    "GRANT": Glyphs.ACTION_GRANT,
    "REVOKE": Glyphs.ACTION_REVOKE,
    "EXPORT": Glyphs.ACTION_EXPORT,
    "IMPORT": Glyphs.ACTION_IMPORT,
    "ENCRYPT": Glyphs.ACTION_ENCRYPT,
    "DECRYPT": Glyphs.ACTION_DECRYPT,
    "VALIDATE": Glyphs.ACTION_VALIDATE,
    "CALCULATE": Glyphs.ACTION_CALCULATE,
    "PREDICT": Glyphs.ACTION_PREDICT,
    "LEARN": Glyphs.ACTION_LEARN,
    "ANALYZE": Glyphs.ACTION_ANALYZE,
    "SYNTHESIZE": Glyphs.ACTION_SYNTHESIZE,
}


# === Destination Mapping ===
DEST_MAP = {
    "MARS": Glyphs.DEST_MARS,
    "MOON": Glyphs.DEST_MOON,
    "EARTH": Glyphs.DEST_EARTH,
    "STAR": Glyphs.DEST_STAR,
    "PLANET": Glyphs.DEST_PLANET,
    "GALAXY": Glyphs.DEST_GALAXY,
    "UNIVERSE": Glyphs.DEST_UNIVERSE,
    "AURORA": Glyphs.DEST_AURORA,
    "TERRAN": Glyphs.DEST_TERRAN,
    "STARLIGHT": Glyphs.DEST_STARLIGHT,
    "POLARIS": Glyphs.DEST_POLARIS,
    "MODEL": Glyphs.ENTITY_MODEL,
    "DATASET": Glyphs.ENTITY_DATASET,
    "LICENSE": Glyphs.ENTITY_LICENSE,
    "USER": Glyphs.ENTITY_USER,
    "WALLET": Glyphs.ENTITY_WALLET,
    "CONTRACT": Glyphs.ENTITY_CONTRACT,
    "TOKEN": Glyphs.ENTITY_TOKEN,
    "HASH": Glyphs.ENTITY_HASH,
    "KEY": Glyphs.ENTITY_KEY,
    "NODE": Glyphs.ENTITY_NODE,
    "CLUSTER": Glyphs.ENTITY_CLUSTER,
    "SERVICE": Glyphs.ENTITY_SERVICE,
    "API": Glyphs.ENTITY_API,
    "DATABASE": Glyphs.ENTITY_DATABASE,
    "FILE": Glyphs.ENTITY_FILE,
    "JSON": Glyphs.ENTITY_JSON,
    "WORKFLOW": Glyphs.ENTITY_WORKFLOW,
    "TASK": Glyphs.ENTITY_TASK,
    "DASHBOARD": Glyphs.ENTITY_DASHBOARD,
    "REPORT": Glyphs.ENTITY_REPORT,
}


# === PSI Levels ===
PSI_LEVELS = ["Ψ0", "Ψ1", "Ψ2", "Ψ3", "Ψ4", "Ψ5", "Ψ6", "Ψ7", "Ψ8", "Ψ9"]


# === Data Classes ===


@dataclass
class Intent:
    """User intent to encode"""

    action: str
    destination: str
    time_slot: int = 0
    modifiers: list[str] | None = None
    coherence: float | None = None


@dataclass
class ContextPayload:
    """Carries context state (raw + encoded) through the GlyphOS pipeline.

    The router inspects this to decide whether to apply Ψ encoding.
    """

    raw_context: str = ""
    raw_context_chars: int = 0
    encoding_status: str = "none"  # "none" | "encoded" | "skipped" | "disabled" | "error_raw_fallback"
    encoded_context: str = ""
    encoding_format: str = ""  # "GE1-JSON" | "GE1-LINES"
    encoding_ratio: float = 1.0  # encoded_chars / raw_chars (lower = better)
    estimated_token_delta: int = 0
    error: str = ""


@dataclass
class GlyphPacket:
    """Complete glyph packet"""

    instance_id: str
    psi_coherence: float
    action: str
    header: str = "H"
    time_slot: str = "T00"
    destination: str = ""
    # Encoding metadata (filled by gateway, inspected by router)
    encoding_status: str = "none"  # mirrors ContextPayload.encoding_status
    encoding_format: str = ""  # "GE1-JSON" | "GE1-LINES"
    encoding_ratio: float = 1.0

    @property
    def instanceId(self) -> str:
        return self.instance_id

    @property
    def psiCoherence(self) -> float:
        return self.psi_coherence

    @property
    def timeSlot(self) -> str:
        return self.time_slot


# === Helper Functions ===


def normalize_psi(psi: float | int | None) -> float:
    try:
        value = float(psi if psi is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def psi_to_level(psi: float) -> str:
    """Convert psi value (0-1) to psi level string"""
    value = normalize_psi(psi)
    if value >= 1.0:
        return "Ψ9"
    level = min(max(int(value * 10), 0), 9)
    return PSI_LEVELS[level]


def level_to_psi(level: str) -> float:
    """Convert psi level string to psi value (0-1)"""
    try:
        return PSI_LEVELS.index(str(level).strip()) / 10
    except ValueError:
        return 0.0


def time_to_slot(t: int) -> str:
    """Convert time value to slot string"""
    try:
        value = int(t)
    except (TypeError, ValueError):
        value = 0
    value = max(0, value)
    return f"T{value:02d}"


def slot_to_time(slot: str) -> int:
    """Convert slot string to time value"""
    try:
        text = str(slot).strip().upper()
        if text.startswith("T"):
            return int(text[1:])
        return int(text)
    except ValueError:
        return 0


def normalize_time_slot(slot: str | int) -> str:
    """Normalize any slot input to canonical Txx."""
    if isinstance(slot, int):
        return time_to_slot(slot)
    return time_to_slot(slot_to_time(str(slot)))


def validate_context_packet_shape(value: Any) -> ContextPacket:
    """Validate and normalize explicit upstream harness context."""
    if value is None:
        return {}

    if not isinstance(value, dict):
        raise TypeError("ContextPacket must be mapping-like")

    out: ContextPacket = {}

    if "content" in value and value["content"] is not None:
        out["content"] = str(value["content"])

    if "locality" in value and value["locality"] is not None:
        locality = str(value["locality"]).strip()
        if locality not in {"orion-local", "lan", "cloud", "external"}:
            raise ValueError("ContextPacket.locality must be one of 'orion-local', 'lan', 'cloud', 'external'")
        out["locality"] = locality  # type: ignore[assignment]

    if "freshness" in value:
        freshness = value["freshness"]
        if freshness is None:
            out["freshness"] = None
        else:
            try:
                out["freshness"] = float(freshness)
            except (TypeError, ValueError) as exc:
                raise ValueError("ContextPacket.freshness must be float | None") from exc

    if "provenance" in value and value["provenance"] is not None:
        provenance = value["provenance"]
        if not isinstance(provenance, list):
            raise ValueError("ContextPacket.provenance must be a list[str]")
        out["provenance"] = [str(item) for item in provenance]

    if "routing_hints" in value and value["routing_hints"] is not None:
        hints = value["routing_hints"]
        if not isinstance(hints, dict):
            raise ValueError("ContextPacket.routing_hints must be a mapping")
        out["routing_hints"] = dict(hints)  # type: ignore[assignment]

    if "metadata" in value and value["metadata"] is not None:
        metadata = value["metadata"]
        if not isinstance(metadata, dict):
            raise ValueError("ContextPacket.metadata must be a mapping")
        out["metadata"] = dict(metadata)

    if "source" in value and value["source"] is not None:
        out["source"] = str(value["source"])

    return out


__all__ = [
    "Glyphs",
    "ACTION_MAP",
    "DEST_MAP",
    "PSI_LEVELS",
    "Intent",
    "ContextPayload",
    "ContextPacket",
    "RoutingHints",
    "Locality",
    "PreferredBackend",
    "GlyphPacket",
    "normalize_psi",
    "psi_to_level",
    "level_to_psi",
    "time_to_slot",
    "slot_to_time",
    "normalize_time_slot",
    "validate_context_packet_shape",
]
