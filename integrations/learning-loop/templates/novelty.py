"""
Novelty Tracker + State Encoder
=================================
Standalone, importable module extracted from the Sisyphus Loop framework.

Tracks novelty of states/actions for curiosity-driven learning. Uses only
stdlib — no numpy dependency. The numpy-backed version lives in
``docs/self_learning.md`` Appendix A for advanced use.

Designed for:
- LLM action spaces (text-based states)
- Structured packet states
- System coherence states

Quick start::

    from novelty import NoveltyTracker, StateEncoder

    tracker = NoveltyTracker(capacity=10_000)
    tracker.record("analyze:routing", state_type="text")

    novelty = tracker.get_novelty("analyze:routing")   # 0.0-1.0
    visit_count = tracker.get_visit_count("analyze:routing")
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# StateEncoding
# ---------------------------------------------------------------------------


@dataclass
class StateEncoding:
    """Encoding configuration for different state types."""

    method: str = "hash"  # "hash", "embedding", "exact"
    embedding_dim: int = 128
    hash_bits: int = 64


# ---------------------------------------------------------------------------
# StateEncoder
# ---------------------------------------------------------------------------


class StateEncoder:
    """
    Encodes various state types into hashable representations.

    Supports:
    - Text prompts (hash or embed)
    - Structured objects (structural hash)
    - Tool configurations (exact match)
    - Numerical coherence states
    """

    def __init__(self, config: StateEncoding | None = None) -> None:
        self.config = config or StateEncoding()

    # -- public API ---------------------------------------------------------

    def encode(self, state: Any, state_type: str = "auto") -> str:
        """Encode *state* according to *state_type*.

        *state_type* can be one of ``"text"``, ``"structured"``,
        ``"coherence"``, ``"config"``, or ``"auto"`` (infer from type).
        """
        if state_type == "auto":
            if isinstance(state, str):
                state_type = "text"
            elif isinstance(state, dict):
                if "coherence" in state:
                    state_type = "coherence"
                elif "config_type" in state or "params" in state:
                    state_type = "config"
                else:
                    state_type = "text"
            else:
                state_type = "structured"

        if state_type == "text":
            return self._encode_text(state if isinstance(state, str) else str(state))
        if state_type == "structured":
            return self._encode_structured(state)
        if state_type == "coherence":
            if isinstance(state, dict):
                return self._encode_coherence(state.get("coherence", 0.5), state.get("secondary"))
            return self._encode_coherence(state)
        if state_type == "config":
            if isinstance(state, dict):
                return self._encode_config(state.get("config_type", "unknown"), state.get("params", {}))
            return str(state)
        return self._encode_text(str(state))

    def encode_text(self, text: str) -> str:
        """Encode a text string into a hash digest.

        Convenience wrapper around :meth:`encode` with ``state_type="text"``.
        """
        if self.config.method == "exact":
            return text
        return hashlib.sha256(text.encode()).hexdigest()[: self.config.hash_bits // 4]

    def encode_structured(self, obj: Any) -> str:
        """Encode a structured object by its key attributes."""
        return self._encode_structured(obj)

    def encode_config(self, config_type: str, params: dict[str, Any]) -> str:
        """Encode a typed configuration dictionary."""
        return self._encode_config(config_type, params)

    def encode_coherence(self, coherence: float, secondary: float | None = None) -> str:
        """Encode a coherence value (and optional secondary) into a bin label."""
        return self._encode_coherence(coherence, secondary)

    # -- internals ----------------------------------------------------------

    def _encode_text(self, text: str) -> str:
        if self.config.method == "exact":
            return text
        return hashlib.sha256(text.encode()).hexdigest()[: self.config.hash_bits // 4]

    def _encode_structured(self, obj: Any) -> str:
        fields: list[str] = []
        for attr in ("action", "type", "domain", "tool"):
            val = getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr)
            if val is not None:
                fields.append(str(val))

        for attr in ("confidence", "quality", "coherence"):
            val = getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr)
            if val is not None:
                bins = [0.0, 0.25, 0.5, 0.75, 1.0]
                val_bin = bins[min(len(bins) - 1, int(float(val) * 4))]
                fields.append(f"{attr}:{val_bin}")

        state_str = "|".join(fields)
        return hashlib.sha256(state_str.encode()).hexdigest()[:16]

    def _encode_config(self, config_type: str, params: dict[str, Any]) -> str:
        state_str = f"{config_type}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(state_str.encode()).hexdigest()[:16]

    def _encode_coherence(self, coherence: float, secondary: float | None = None) -> str:
        bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        c_bin = bins[min(len(bins) - 1, int(coherence * 5))]
        if secondary is not None:
            p_bins = [-1.0, -0.5, 0.0, 0.5, 1.0]
            p_bin = p_bins[min(len(p_bins) - 1, int((secondary + 1) * 2))]
            return f"coh:{c_bin}|sec:{p_bin}"
        return f"coh:{c_bin}"


# ---------------------------------------------------------------------------
# NoveltyTracker
# ---------------------------------------------------------------------------


class NoveltyTracker:
    """
    Tracks how novel each state is — drives exploration.

    Features:
    - Multiple state encodings
    - Temporal decay of novelty (regains novelty over time)
    - Memory management (evict least-valuable states when over capacity)

    Parameters
    ----------
    capacity:
        Maximum number of unique states before eviction begins.
    decay_rate:
        Fraction of maximum temporal boost applied per hour since last visit.
        At ``0.01`` a state gains up to 0.30 novelty boost per hour.
    encoder:
        Optional custom :class:`StateEncoder`. A default one is created if
        omitted.
    """

    def __init__(
        self,
        capacity: int = 10000,
        decay_rate: float = 0.01,
        encoder: StateEncoder | None = None,
    ) -> None:
        self.capacity = capacity
        self.decay_rate = decay_rate
        self.encoder = encoder or StateEncoder()
        self.state_counts: dict[str, int] = defaultdict(int)
        self.state_first_seen: dict[str, float] = {}
        self.state_last_seen: dict[str, float] = {}
        self.state_encounters: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # -- queries ------------------------------------------------------------

    def get_novelty(self, state: Any, state_type: str = "auto") -> float:
        """Return novelty score in ``[0, 1]`` — 1.0 = completely novel."""
        encoded = self.encoder.encode(state, state_type)
        count = self.state_counts[encoded]
        if count == 0:
            return 1.0
        base_novelty = 1.0 / (1.0 + math.log(1 + count))
        if encoded in self.state_last_seen:
            time_since_seen = time.time() - self.state_last_seen[encoded]
            temporal_boost = min(0.3, self.decay_rate * time_since_seen / 3600)
            return min(1.0, base_novelty + temporal_boost)
        return base_novelty

    def get_familiarity(self, state: Any, state_type: str = "auto") -> float:
        """Return familiarity score in ``[0, 1]`` — 1.0 = maximally familiar."""
        return 1.0 - self.get_novelty(state, state_type)

    def get_visit_count(self, state: Any, state_type: str = "auto") -> int:
        """Return how many times this state has been recorded."""
        return self.state_counts[self.encoder.encode(state, state_type)]

    def get_recency(self, state: Any, state_type: str = "auto") -> float:
        """Return recency score in ``[0, 1]`` — 1.0 = seen just now.

        Decays exponentially with a half-life of ~1 hour.
        """
        encoded = self.encoder.encode(state, state_type)
        if encoded not in self.state_last_seen:
            return 0.0
        time_since = time.time() - self.state_last_seen[encoded]
        return math.exp(-time_since / 3600)

    def get_most_novel_states(self, n: int = 10, exclude_recent_hours: float = 0.0) -> list[tuple[str, float]]:
        """Return the *n* most novel (encoded-state, score) pairs.

        Optionally exclude states last seen within *exclude_recent_hours*.
        """
        current_time = time.time()
        scored: list[tuple[str, float]] = []
        for encoded, _count in self.state_counts.items():
            if exclude_recent_hours > 0 and encoded in self.state_last_seen:
                if current_time - self.state_last_seen[encoded] < exclude_recent_hours * 3600:
                    continue
            scored.append((encoded, self.get_novelty(encoded)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    # -- mutations ----------------------------------------------------------

    def record(
        self,
        state: Any,
        state_type: str = "auto",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a visit to *state*.

        Optionally attach *metadata* (e.g. ``{"action": approach}``) which is
        stored in the encounter log but does **not** affect novelty scoring.
        """
        encoded = self.encoder.encode(state, state_type)
        current_time = time.time()
        self.state_counts[encoded] += 1
        if encoded not in self.state_first_seen:
            self.state_first_seen[encoded] = current_time
        self.state_last_seen[encoded] = current_time
        encounter: dict[str, Any] = {"time": current_time}
        if metadata:
            encounter["metadata"] = metadata
        self.state_encounters[encoded].append(encounter)
        self._maybe_evict()

    def reset(self) -> None:
        """Clear all tracking data (start fresh)."""
        self.state_counts.clear()
        self.state_first_seen.clear()
        self.state_last_seen.clear()
        self.state_encounters.clear()

    # -- housekeeping -------------------------------------------------------

    def _maybe_evict(self) -> None:
        if len(self.state_counts) <= self.capacity:
            return
        states_to_evict = len(self.state_counts) - self.capacity
        scored: list[tuple[str, float]] = []
        for encoded in self.state_counts:
            count = self.state_counts[encoded]
            novelty_sum = sum(1.0 / (1.0 + math.log(1 + c)) for c in range(1, count + 1))
            recency = self.get_recency(encoded)
            score = novelty_sum * (1.0 - recency)
            scored.append((encoded, score))
        scored.sort(key=lambda x: x[1])
        for encoded, _ in scored[:states_to_evict]:
            del self.state_counts[encoded]
            self.state_first_seen.pop(encoded, None)
            self.state_last_seen.pop(encoded, None)
            self.state_encounters.pop(encoded, None)

    def summary(self) -> dict[str, Any]:
        """Return a diagnostic summary of the tracker's state."""
        total_visits = sum(self.state_counts.values())
        unique_states = len(self.state_counts)
        return {
            "unique_states": unique_states,
            "total_visits": total_visits,
            "avg_visits_per_state": (round(total_visits / unique_states, 2) if unique_states > 0 else 0),
            "capacity": self.capacity,
            "memory_usage_pct": round(unique_states / self.capacity * 100, 1),
        }


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    tracker = NoveltyTracker(capacity=100, decay_rate=0.02)

    # ---- StateEncoder demo ----
    print("=== StateEncoder ===")
    enc = StateEncoder()
    print(f"  text:     {enc.encode('analyze aurora routing')}")
    print(f"  struct:   {enc.encode({'action': 'ANALYZE', 'domain': 'routing'})}")
    print(f"  config:   {enc.encode_config('llamacpp', {'model': 'qwen', 'ctx': 4096})}")
    print(f"  coh 0.85: {enc.encode_coherence(0.85)}")
    print(f"  coh 0.20: {enc.encode_coherence(0.20)}")

    # ---- NoveltyTracker demo ----
    print("\n=== NoveltyTracker ===")
    states = [
        "analyze:routing",
        "debug:memory",
        "refactor:auth",
        "analyze:routing",
        "test:coverage",
        "analyze:routing",
        "debug:memory",
    ]
    for i, s in enumerate(states):
        tracker.record(s, metadata={"action": f"step_{i}"})
        print(f"  record({s!r:25s}) → novelty={tracker.get_novelty(s):.3f}  visits={tracker.get_visit_count(s)}")

    print(f"\n  summary:   {tracker.summary()}")
    print(f"  most novel: {tracker.get_most_novel_states(n=3)}")

    # ---- Temporal decay demo ----
    print("\n=== Temporal decay (simulated) ===")
    tracker2 = NoveltyTracker(capacity=100, decay_rate=0.02)
    tracker2.record("debug:memory")
    tracker2.record("debug:memory")
    initial_novelty = tracker2.get_novelty("debug:memory")
    print(f"  novelty after 2 visits:         {initial_novelty:.4f}")

    # Manually wind the clock for the last-seen timestamp
    encoded = tracker2.encoder.encode("debug:memory")
    tracker2.state_last_seen[encoded] = time.time() - 7200  # 2 hours ago
    decayed_novelty = tracker2.get_novelty("debug:memory")
    print(f"  novelty after 2h no visit:       {decayed_novelty:.4f}  (boosted by temporal decay)")

    sys.exit(0)
