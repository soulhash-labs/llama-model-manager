#!/usr/bin/env python3
"""Session handoff summary generation for completed long-running sessions.

Phase 06: Long-Run Session Handoff
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HandoffSummary:
    """Human-readable summary of a completed long-running session."""

    session_id: str = ""
    run_id: str = ""
    status: str = ""
    model: str = ""
    provider: str = ""
    duration_human: str = ""
    completed_at: str = ""
    exit_result: str = ""
    prompt_preview: str = ""
    artifacts: list[str] | None = None
    upstream_session_ref: str = ""

    @classmethod
    def from_run_record(cls, record: dict[str, Any]) -> HandoffSummary:
        """Build a HandoffSummary from a RunRecord.to_dict() output."""
        prompt = str(record.get("prompt", ""))
        prompt_preview = prompt[:200] + ("…" if len(prompt) > 200 else "")

        duration_ms = record.get("duration_ms")
        if duration_ms is not None:
            duration_human = _format_duration(int(duration_ms))
        else:
            duration_human = ""

        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            artifacts = _extract_artifacts(record)

        exit_result = record.get("exit_result") or ""
        if exit_result is None:
            exit_result = ""
        exit_result = str(exit_result)

        return cls(
            session_id=str(record.get("session_id", record.get("id", ""))),
            run_id=str(record.get("id", "")),
            status=str(record.get("status", "")),
            model=str(record.get("model", "")),
            provider=str(record.get("provider", "")),
            duration_human=duration_human,
            completed_at=str(record.get("completed_at", "") or ""),
            exit_result=exit_result,
            prompt_preview=prompt_preview,
            artifacts=artifacts if artifacts else [],
            upstream_session_ref=str(record.get("upstream_session_ref", "")),
        )


def _format_duration(ms: int) -> str:
    """Convert milliseconds to human-readable duration string."""
    if ms < 0:
        return "0s"
    if ms < 1000:
        return f"{ms}ms"

    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def _extract_artifacts(record: dict[str, Any]) -> list[str]:
    """Extract artifact paths from RunRecord metadata."""
    artifacts: list[str] = []
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("artifacts", "output_files"):
            val = metadata.get(key)
            if isinstance(val, list):
                artifacts.extend(str(a) for a in val)
    return artifacts


def format_handoff_text(summary: HandoffSummary) -> str:
    """Plain text output for CLI display."""
    lines = [
        f"Session: {summary.session_id}",
        f"Run:     {summary.run_id}",
        f"Status:  {summary.status}",
        f"Model:   {summary.model}",
        f"Provider: {summary.provider}",
        f"Duration: {summary.duration_human}",
        f"Completed: {summary.completed_at}",
        f"Result:  {summary.exit_result}",
        f"Prompt:  {summary.prompt_preview}",
    ]
    if summary.upstream_session_ref:
        lines.append(f"Upstream: {summary.upstream_session_ref}")
    if summary.artifacts:
        lines.append(f"Artifacts: {', '.join(summary.artifacts)}")
    return "\n".join(lines)


def format_handoff_html(summary: HandoffSummary) -> str:
    """HTML snippet for dashboard rendering."""
    status_class = {
        "completed": "success",
        "failed": "error",
        "cancelled": "cancelled",
    }.get(summary.status.lower(), "unknown")

    artifacts_html = ""
    if summary.artifacts:
        artifacts_html = "<br>".join(f'<span class="artifact">{_escape_html(a)}</span>' for a in summary.artifacts)

    return (
        f'<div class="handoff-card status-{status_class}">'
        f'<div class="handoff-header">'
        f'<span class="handoff-model">{_escape_html(summary.model)}</span>'
        f'<span class="handoff-status status-{status_class}">{_escape_html(summary.status)}</span>'
        f"</div>"
        f'<div class="handoff-meta">'
        f'<span class="handoff-duration">{_escape_html(summary.duration_human)}</span>'
        f'<span class="handoff-completed">{_escape_html(summary.completed_at)}</span>'
        f'<span class="handoff-provider">{_escape_html(summary.provider)}</span>'
        f"</div>"
        f'<div class="handoff-prompt">{_escape_html(summary.prompt_preview)}</div>'
        f"{artifacts_html}"
        f"</div>"
    )


def _escape_html(text: str) -> str:
    """Basic HTML escaping for handoff display."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


__all__ = [
    "HandoffSummary",
    "format_handoff_text",
    "format_handoff_html",
]
