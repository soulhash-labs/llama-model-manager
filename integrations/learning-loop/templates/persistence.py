"""
Persistence Store
==================
JSON save/load for per-task-type approach mappings and session state.

This is the **single most practical concept** from the Learning Loop framework
(see ``docs/self_learning.md#7-persistence``). Persisting approach–task
performance associations lets an agent make better decisions immediately —
no Q-tables, no vector embeddings, just a small JSON file.

Tier-aware: all keys are prefixed with ``tier_N:`` so strategies are scoped
to hardware capability.  A Tier 1 machine learns different approaches than
a Tier 4, and they never contaminate each other.

Quick start::

    from persistence import PersistenceStore

    store = PersistenceStore("agent_state.json", tier=3)
    store.record_outcome("code_review", "thorough", success=True, latency_ms=3200)
    store.record_outcome("code_review", "fast", success=True, latency_ms=800)
    store.record_outcome("debugging", "thorough", success=False, latency_ms=15000)

    # Later, ask the store what to do (automatically scoped to tier 3):
    best = store.recommend_approach("code_review")
    print(best)  # "fast" — better success rate *and* lower latency
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_STATE_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"),
    "llama-model-manager",
    "agent_state.json",
)

DEFAULT_TIER_CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"),
    "llama-model-manager",
    "agent-tier.yaml",
)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ApproachStats:
    """Statistics for a single approach within a task domain."""

    best_approach: str
    success_rate: float = 0.0
    samples: int = 0
    avg_latency_ms: float = 0.0
    last_used: float = 0.0  # unix timestamp

    def score(self, latency_weight: float = 0.3) -> float:
        """Composite score for ranking approaches.

        Higher is better. Penalizes latency proportionally to
        *latency_weight*.
        """
        if self.samples == 0:
            return 0.0
        latency_factor = max(0.0, 1.0 - self.avg_latency_ms / 30000)
        return self.success_rate * (1.0 - latency_weight) + latency_factor * latency_weight


@dataclass
class PersistenceState:
    """The full persisted state of the learning loop."""

    per_domain_strategies: dict[str, ApproachStats] = field(default_factory=dict)
    novelty_scores: dict[str, float] = field(default_factory=dict)
    session_count: int = 0
    total_tasks: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0


# ---------------------------------------------------------------------------
# PersistenceStore
# ---------------------------------------------------------------------------


class PersistenceStore:
    """Thread-safe persistence for cross-session learning.

    Serialises per-task-type approach maps, novelty scores, and session
    metadata to a JSON file.  Uses atomic-write (write to temp, rename) so a
    crash at any point never corrupts the last good state.

    When *tier* is set, all domain keys are prefixed with ``tier_N:`` so
    strategies are scoped to hardware capability.

    Parameters
    ----------
    path:
        Filesystem path to the JSON state file.  Created on first write if it
        does not exist.  Defaults to global ``~/.config/llama-model-manager/agent_state.json``.
    tier:
        Hardware tier (1-4).  All keys prefixed with ``tier_{tier}:``.
        If ``None``, no prefix is applied (legacy behaviour).
    tier_config_path:
        Path to ``agent-tier.yaml``.  If *tier* is ``None`` and this file
        exists, the tier is read from it automatically.  Defaults to global
        ``~/.config/llama-model-manager/agent-tier.yaml``.
    auto_save:
        If True, flush to disk after every mutation.  Set to False if you
        prefer to call :meth:`save` explicitly after a batch of updates.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        tier: int | None = None,
        tier_config_path: str | os.PathLike[str] | None = None,
        auto_save: bool = True,
    ) -> None:
        self._path = Path(path) if path is not None else DEFAULT_STATE_PATH
        self._auto_save = auto_save
        self._lock = threading.Lock()
        self._state = PersistenceState()

        # Resolve tier: explicit param > tier_config_path > None
        self._tier = tier
        if self._tier is None and tier_config_path is not None:
            self._tier = self._read_tier_config(Path(tier_config_path))

        self._load()

    # -- tier helpers -------------------------------------------------------

    @staticmethod
    def _read_tier_config(config_path: Path) -> int | None:
        """Read tier number from agent-tier.yaml (simple key lookup)."""
        if not config_path.exists():
            return None
        try:
            text = config_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("tier:") or line.startswith("Tier:"):
                    val = line.split(":", 1)[1].strip().rstrip("#").strip()
                    return int(val)
        except (ValueError, OSError):
            pass
        return None

    @property
    def tier(self) -> int | None:
        """Current hardware tier, or ``None`` if not set."""
        return self._tier

    def _tier_prefix(self) -> str:
        """Return ``tier_N:`` prefix or empty string."""
        return f"tier_{self._tier}:" if self._tier is not None else ""

    # -- public API ---------------------------------------------------------

    # -- domain/approach tracking --

    def record_outcome(
        self,
        domain: str,
        approach: str,
        *,
        success: bool,
        latency_ms: float | None = None,
    ) -> None:
        """Record one outcome for *domain* x *approach*, scoped to current tier."""
        with self._lock:
            key = f"{self._tier_prefix()}{domain}:{approach}"
            stats = self._state.per_domain_strategies.get(key)
            if stats is None:
                stats = ApproachStats(best_approach=approach)
                self._state.per_domain_strategies[key] = stats

            old_samples = stats.samples
            old_successes = old_samples * stats.success_rate

            stats.samples += 1
            stats.success_rate = (old_successes + (1.0 if success else 0.0)) / stats.samples
            if latency_ms is not None:
                stats.avg_latency_ms = (
                    ((old_samples * stats.avg_latency_ms) + latency_ms) / stats.samples
                    if old_samples > 0
                    else latency_ms
                )
            stats.last_used = time.time()

            self._state.total_tasks += 1
            self._save()

    def recommend_approach(self, domain: str) -> str | None:
        """Return the approach with the highest composite score for *domain*,
        scoped to current tier.  Returns ``None`` if no data exists yet."""
        with self._lock:
            prefix = self._tier_prefix()
            candidates = [
                (key, stats)
                for key, stats in self._state.per_domain_strategies.items()
                if key.startswith(f"{prefix}{domain}:")
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda kv: kv[1].score(), reverse=True)
            return candidates[0][0].split(":", 1)[1]

    def domain_summary(self, domain: str) -> list[dict[str, Any]]:
        """Return a list of approach stats dicts for *domain*, scoped to tier."""
        with self._lock:
            prefix = self._tier_prefix()
            result = []
            for key, stats in self._state.per_domain_strategies.items():
                if key.startswith(f"{prefix}{domain}:"):
                    entry = asdict(stats)
                    entry["approach"] = key.split(":", 1)[1]
                    entry["score"] = round(stats.score(), 4)
                    result.append(entry)
            return result

    def tier_summary(self) -> dict[str, Any]:
        """Return all approach stats for the current tier."""
        with self._lock:
            prefix = self._tier_prefix()
            result: dict[str, list[dict[str, Any]]] = {}
            for key, stats in self._state.per_domain_strategies.items():
                if key.startswith(prefix):
                    domain = key[len(prefix) :].split(":", 1)[0]
                    if domain not in result:
                        result[domain] = []
                    entry = asdict(stats)
                    entry["approach"] = key.split(":", 1)[1]
                    entry["score"] = round(stats.score(), 4)
                    result[domain].append(entry)
            return result

    def compare_tiers(self) -> dict[str, dict[str, Any]]:
        """Return a comparison of approaches across all tiers."""
        with self._lock:
            tiers: dict[str, dict[str, list[dict[str, Any]]]] = {}
            for key, stats in self._state.per_domain_strategies.items():
                if key.startswith("tier_"):
                    parts = key.split(":", 1)
                    tier_label = parts[0]  # e.g. "tier_3"
                    domain = parts[1].split(":", 1)[0] if ":" in parts[1] else parts[1]
                    if tier_label not in tiers:
                        tiers[tier_label] = {}
                    if domain not in tiers[tier_label]:
                        tiers[tier_label][domain] = []
                    entry = asdict(stats)
                    entry["approach"] = parts[1].split(":", 1)[1] if ":" in parts[1] else parts[1]
                    entry["score"] = round(stats.score(), 4)
                    tiers[tier_label][domain].append(entry)
            return tiers

    # -- novelty scores --

    def set_novelty(self, key: str, score: float) -> None:
        """Set a named novelty score."""
        with self._lock:
            self._state.novelty_scores[key] = score
            self._save()

    def get_novelty(self, key: str) -> float | None:
        """Return a named novelty score, or ``None`` if not set."""
        with self._lock:
            return self._state.novelty_scores.get(key)

    # -- session tracking --

    def increment_session(self) -> int:
        """Bump the session counter and return the new count."""
        with self._lock:
            self._state.session_count += 1
            self._save()
            return self._state.session_count

    # -- I/O ---------------------------------------------------------------

    def save(self) -> None:
        """Explicitly flush state to disk."""
        with self._lock:
            self._save()

    def reload(self) -> None:
        """Discard in-memory changes and reload from disk."""
        with self._lock:
            self._load()

    @property
    def state(self) -> PersistenceState:
        """Return a copy of the current state (thread-safe)."""
        with self._lock:
            return PersistenceState(
                per_domain_strategies=dict(self._state.per_domain_strategies),
                novelty_scores=dict(self._state.novelty_scores),
                session_count=self._state.session_count,
                total_tasks=self._state.total_tasks,
                created_at=self._state.created_at,
                updated_at=self._state.updated_at,
            )

    # -- internals ----------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._state = PersistenceState(created_at=time.time(), updated_at=time.time())
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._state = PersistenceState(created_at=time.time(), updated_at=time.time())
            return

        strategies = {}
        for key, entry in raw.get("per_domain_strategies", {}).items():
            if isinstance(entry, dict):
                strategies[key] = ApproachStats(**entry)
        self._state = PersistenceState(
            per_domain_strategies=strategies,
            novelty_scores=dict(raw.get("novelty_scores", {})),
            session_count=int(raw.get("session_count", 0)),
            total_tasks=int(raw.get("total_tasks", 0)),
            created_at=float(raw.get("created_at", time.time())),
            updated_at=float(raw.get("updated_at", time.time())),
        )

    def _save(self) -> None:
        if not self._auto_save:
            return
        self._state.updated_at = time.time()
        raw = {
            "per_domain_strategies": {key: asdict(stats) for key, stats in self._state.per_domain_strategies.items()},
            "novelty_scores": dict(self._state.novelty_scores),
            "session_count": self._state.session_count,
            "total_tasks": self._state.total_tasks,
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
        }
        # Atomic write: write to .tmp, then rename.
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self._path)


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        # Tier 3 demo
        store = PersistenceStore(tmp_path, tier=3)

        print("=== recording outcomes (Tier 3) ===")
        store.record_outcome("code_review", "thorough", success=True, latency_ms=3200)
        store.record_outcome("code_review", "thorough", success=True, latency_ms=2900)
        store.record_outcome("code_review", "fast", success=True, latency_ms=500)
        store.record_outcome("code_review", "fast", success=True, latency_ms=700)
        store.record_outcome("code_review", "fast", success=False, latency_ms=600)
        store.record_outcome("debugging", "thorough", success=False, latency_ms=15000)
        store.record_outcome("debugging", "thorough", success=True, latency_ms=8000)
        store.record_outcome("debugging", "binary_search", success=True, latency_ms=2000)
        store.record_outcome("debugging", "binary_search", success=True, latency_ms=1500)
        store.record_outcome("subagent", "spawn", success=True, latency_ms=5000)
        store.record_outcome("marathon_session", "long_run", success=True, latency_ms=32400000)

        print(f"  total_tasks = {store.state.total_tasks}")
        print(f"  tier = {store.tier}")

        for domain in ("code_review", "debugging", "subagent", "data_analysis"):
            best = store.recommend_approach(domain)
            summary = store.domain_summary(domain)
            print(f"  domain={domain!r:20s} best={best!r:20s} data={summary}")

        print("\n=== tier summary ===")
        print(f"  {store.tier_summary()}")

        print("\n=== session tracking ===")
        print(f"  session after increment: {store.increment_session()}")
        print(f"  session after increment: {store.increment_session()}")

        print("\n=== on-disk content ===")
        raw = Path(tmp_path).read_text(encoding="utf-8")
        print(raw[:600])

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    sys.exit(0)
