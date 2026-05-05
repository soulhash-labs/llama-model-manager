from __future__ import annotations

from typing import Any


def build_upstream_context(context_result: dict[str, Any]) -> dict[str, Any] | None:
    """Convert gateway retrieval output into the public ContextPacket shape."""
    raw = str(context_result.get("context") or "").strip()
    if not raw:
        return None

    source = str(context_result.get("source", "")).strip()
    provenance: list[str] = []
    if source:
        provenance.append(source)

    search_strategy = str(context_result.get("search_strategy", "")).strip()
    if search_strategy:
        provenance.append(f"strategy:{search_strategy}")

    metadata = {
        "context_status": str(context_result.get("status", "")),
        "search_degraded": bool(context_result.get("search_degraded", False)),
        "search_suggestions": context_result.get("search_suggestions", []),
    }

    return {
        "content": raw,
        "locality": "external",
        "provenance": provenance,
        "metadata": metadata,
        "source": source,
    }
