"""
Glyph Types
===========
Python types matching the TypeScript glyph_types.ts, plus
explicit upstream-context support for harness-driven routing.

This merged version keeps the current live-repo shape:
- GlyphPacket
- ContextPayload (gateway/local compression path)
- helper maps and PSI/time helpers

And adds:
- ContextPacket
- RoutingHints
- validation helpers
- compatibility helpers
- packet construction / export helpers

without forcing a repo-wide redesign.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypedDict

# === Public context contract ==================================================

Locality = Literal["orion-local", "lan", "cloud", "external"]
PreferredBackend = Literal["llamacpp", "openai", "anthropic", "xai", "local", "external"]


class RoutingHints(TypedDict, total=False):
    preferred_backend: PreferredBackend
    token_budget: int
    preferred_lane: str
    max_latency_ms: int


class ContextPacket(TypedDict, total=False):
    """
    Explicit upstream context contract for harness/orchestrator integration.

    This is distinct from ContextPayload:
    - ContextPacket = public injected context from the harness
    - ContextPayload = internal gateway/local encoding state
    """

    content: str
    locality: Locality
    freshness: float | None
    provenance: list[str]
    routing_hints: RoutingHints
    metadata: dict[str, Any]
    source: str


# === Glyph Constants ==========================================================


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
    ACTION_APPROVE = "☑"
    ACTION_DENY = "⊘"
    ACTION_GRANT = "⊕"
    ACTION_REVOKE = "⊖"
    ACTION_SUSPEND = "⊝"
    ACTION_RESUME = "⊜"
    ACTION_LOCK = "🔒"
    ACTION_UNLOCK = "🔓"
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
    ACTION_COMPRESS = "⊞"
    ACTION_DECOMPRESS = "⊟"
    ACTION_VALIDATE = "⊠"
    ACTION_CALCULATE = "⊡"
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
    ACTION_TRACK = "◎"
    ACTION_MONITOR = "⊡"
    ACTION_ALERT = "⚠"
    ACTION_LOG = "📋"
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

    # === ENTITIES / DESTINATIONS (64) ===
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

    # === PACKET FRAMING ===
    HEADER = "H"
    SEPARATOR = "|"
    END = ">"
    COHERENCE = "Ψ"


# === Action Mapping ===========================================================

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

# === Destination Mapping ======================================================

DEST_MAP = {
    "MARS": Glyphs.DEST_MARS,
    "MOON": Glyphs.DEST_MOON,
    "EARTH": Glyphs.DEST_EARTH,
    "STAR": Glyphs.DEST_STAR,
    "PLANET": Glyphs.DEST_PLANET,
    "GALAXY": Glyphs.DEST_GALAXY,
    "UNIVERSE": Glyphs.DEST_UNIVERSE,
    "DIMENSION": Glyphs.DEST_DIMENSION,
    "REALITY": Glyphs.DEST_REALITY,
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

# === PSI Levels ===============================================================

PSI_LEVELS = [f"Ψ{i}" for i in range(10)]


# === Data Classes =============================================================


@dataclass
class Intent:
    """User intent to encode"""

    action: str
    destination: str
    time_slot: int = 0
    modifiers: list[str] | None = None
    coherence: float | None = None

    def normalized(self) -> Intent:
        return Intent(
            action=str(self.action).strip().upper(),
            destination=str(self.destination).strip().upper(),
            time_slot=max(0, int(self.time_slot)),
            modifiers=[str(m).strip() for m in (self.modifiers or []) if str(m).strip()],
            coherence=normalize_psi(self.coherence) if self.coherence is not None else None,
        )


@dataclass
class ContextPayload:
    """
    Carries context state (raw + encoded) through the GlyphOS pipeline.

    The router inspects this to decide whether to apply Ψ encoding.
    """

    raw_context: str = ""
    raw_context_chars: int = 0
    encoding_status: str = "none"  # none|encoded|skipped|disabled|error_raw_fallback
    encoded_context: str = ""
    encoding_format: str = ""  # GE1-JSON | GE1-LINES
    encoding_ratio: float = 1.0  # encoded_chars / raw_chars (lower = better)
    estimated_token_delta: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        if self.raw_context_chars == 0 and self.raw_context:
            self.raw_context_chars = len(self.raw_context)


@dataclass
class GlyphPacket:
    """Complete glyph packet"""

    instance_id: str
    psi_coherence: float
    action: str
    header: str = Glyphs.HEADER
    time_slot: str = "T00"
    destination: str = ""
    modifiers: list[str] | None = None
    # Encoding metadata (filled by gateway, inspected by router)
    encoding_status: str = "none"
    encoding_format: str = ""
    encoding_ratio: float = 1.0
    packet_version: int = 1

    def __post_init__(self) -> None:
        self.instance_id = str(self.instance_id).strip()
        self.psi_coherence = normalize_psi(self.psi_coherence)
        self.action = str(self.action).strip().upper()
        self.header = str(self.header).strip() or Glyphs.HEADER
        self.time_slot = normalize_time_slot(self.time_slot)
        self.destination = str(self.destination).strip().upper()
        self.modifiers = [str(m).strip() for m in (self.modifiers or []) if str(m).strip()]
        self.encoding_status = str(self.encoding_status).strip() or "none"
        self.encoding_format = str(self.encoding_format).strip()
        try:
            self.encoding_ratio = float(self.encoding_ratio)
        except (TypeError, ValueError):
            self.encoding_ratio = 1.0
        self.packet_version = int(self.packet_version)

    @property
    def instanceId(self) -> str:
        return self.instance_id

    @property
    def psiCoherence(self) -> float:
        return self.psi_coherence

    @property
    def timeSlot(self) -> str:
        return self.time_slot

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_intent(cls, instance_id: str, intent: Intent, psi_coherence: float) -> GlyphPacket:
        normalized = intent.normalized()
        return cls(
            instance_id=instance_id,
            psi_coherence=psi_coherence,
            action=normalized.action,
            time_slot=time_to_slot(normalized.time_slot),
            destination=normalized.destination,
            modifiers=normalized.modifiers,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> GlyphPacket:
        return cls(
            instance_id=str(value.get("instance_id", value.get("instanceId", ""))),
            psi_coherence=float(value.get("psi_coherence", value.get("psiCoherence", 0.5))),
            action=str(value.get("action", "DEFAULT")),
            header=str(value.get("header", Glyphs.HEADER)),
            time_slot=str(value.get("time_slot", value.get("timeSlot", "T00"))),
            destination=str(value.get("destination", "")),
            modifiers=list(value.get("modifiers", [])) if isinstance(value.get("modifiers"), list) else [],
            encoding_status=str(value.get("encoding_status", value.get("encodingStatus", "none"))),
            encoding_format=str(value.get("encoding_format", value.get("encodingFormat", ""))),
            encoding_ratio=float(value.get("encoding_ratio", value.get("encodingRatio", 1.0))),
            packet_version=int(value.get("packet_version", value.get("packetVersion", 1))),
        )


# === Helper Functions =========================================================


def normalize_psi(psi: float | int | None) -> float:
    try:
        value = float(psi if psi is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def psi_to_level(psi: float) -> str:
    """Convert psi value (0-1) to psi level string."""
    value = normalize_psi(psi)
    if value >= 1.0:
        return "Ψ9"
    level = min(max(int(value * 10), 0), 9)
    return PSI_LEVELS[level]


def level_to_psi(level: str) -> float:
    """Convert psi level string to psi value (0-1)."""
    try:
        return PSI_LEVELS.index(str(level).strip()) / 10
    except ValueError:
        return 0.0


def time_to_slot(t: int) -> str:
    """Convert time value to slot string."""
    try:
        value = int(t)
    except (TypeError, ValueError):
        value = 0
    value = max(0, value)
    return f"T{value:02d}"


def slot_to_time(slot: str) -> int:
    """Convert slot string to time value."""
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


def validate_context_packet_shape(value: Any) -> ContextPacket | dict[str, Any]:
    """
    Validate explicit upstream harness context.

    Accepts:
    - None
    - mapping-like objects

    Returns a normalized ContextPacket dict.
    """
    if value is None:
        return {}

    if not isinstance(value, Mapping):
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
        if not isinstance(hints, Mapping):
            raise ValueError("ContextPacket.routing_hints must be a mapping")
        out["routing_hints"] = dict(hints)  # type: ignore[assignment]

    if "metadata" in value and value["metadata"] is not None:
        metadata = value["metadata"]
        if not isinstance(metadata, Mapping):
            raise ValueError("ContextPacket.metadata must be a mapping")
        out["metadata"] = dict(metadata)

    if "source" in value and value["source"] is not None:
        out["source"] = str(value["source"])

    return out


def action_to_glyph(action: str) -> str:
    """Encode a canonical action name to its compatibility glyph."""
    return ACTION_MAP.get(str(action).strip().upper(), Glyphs.ACTION_QUERY)


def destination_to_glyph(destination: str) -> str:
    """Encode a canonical destination/entity name to its compatibility token."""
    return DEST_MAP.get(str(destination).strip().upper(), str(destination).strip().upper())


def packet_to_compat_dict(packet: GlyphPacket) -> dict[str, Any]:
    """
    Produce a dict containing both snake_case and camelCase fields
    for interop with older callers.
    """
    return {
        "instance_id": packet.instance_id,
        "instanceId": packet.instance_id,
        "psi_coherence": packet.psi_coherence,
        "psiCoherence": packet.psi_coherence,
        "action": packet.action,
        "header": packet.header,
        "time_slot": packet.time_slot,
        "timeSlot": packet.time_slot,
        "destination": packet.destination,
        "modifiers": list(packet.modifiers or []),
        "encoding_status": packet.encoding_status,
        "encodingStatus": packet.encoding_status,
        "encoding_format": packet.encoding_format,
        "encodingFormat": packet.encoding_format,
        "encoding_ratio": packet.encoding_ratio,
        "encodingRatio": packet.encoding_ratio,
        "packet_version": packet.packet_version,
        "packetVersion": packet.packet_version,
    }


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
    "action_to_glyph",
    "destination_to_glyph",
    "packet_to_compat_dict",
]
