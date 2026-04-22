"""
Glyph Types
===========
Python types matching the TypeScript glyph_types.ts
"""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


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
    modifiers: Optional[List[str]] = None
    coherence: Optional[float] = None


@dataclass
class GlyphPacket:
    """Complete glyph packet"""
    instance_id: str
    psi_coherence: float
    action: str
    header: str = "H"
    time_slot: str = "T00"
    destination: str = ""


# === Helper Functions ===

def psi_to_level(psi: float) -> str:
    """Convert psi value (0-1) to psi level string"""
    level = min(max(int(psi * 10), 0), 9)
    return PSI_LEVELS[level]


def level_to_psi(level: str) -> float:
    """Convert psi level string to psi value (0-1)"""
    try:
        return PSI_LEVELS.index(level) / 10
    except ValueError:
        return 0.0


def time_to_slot(t: int) -> str:
    """Convert time value to slot string"""
    return f"T{t:02d}"


def slot_to_time(slot: str) -> int:
    """Convert slot string to time value"""
    try:
        return int(slot.replace("T", ""))
    except ValueError:
        return 0