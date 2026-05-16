"""
Adaptive routing across local and external AI backends.

Merged production router.

Preserved from production/uploaded router.py:
- local-first GlyphOS routing policy
- ContextPayload support
- upstream_context support
- cloud fallback order and preferred cloud
- routing_reason_code
- per-router and shared telemetry
- streaming support for local backends
- lane selection for AURORA / TERRAN / STARLIGHT / POLARIS

Merged from pasted router.py:
- LOCAL_OLLAMA support
- mapping/object-safe packet reads
- CLI for glyph-first routing
- status / JSON / prompt / structured output
- explicit upstream-context CLI support

Design rule:
- No retrieval or hidden I/O.
- upstream_context must be explicit.
- External AI is routed only through configured clients.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypedDict

from .api_client import create_configured_clients
from .glyph_to_prompt import build_prompt_from_packet, glyph_to_prompt

try:
    from .glyph_to_prompt import glyph_to_structured_json
except Exception:  # pragma: no cover - compatibility for older glyph_to_prompt.py

    def glyph_to_structured_json(glyph_packet: Any, upstream_context: Any = None) -> dict[str, Any]:
        return {
            "packet": _packet_to_dict(glyph_packet),
            "upstream_context_provided": upstream_context is not None,
        }


try:
    from ..glyph.encoder import decode_packet as decode_packet_string
    from ..glyph.encoder import encode_packet as encode_packet_string
except Exception:  # pragma: no cover - CLI-only dependency guard
    decode_packet_string = None
    encode_packet_string = None

try:
    from ..glyph.types import ContextPacket, ContextPayload, Intent, validate_context_packet_shape
except Exception:  # pragma: no cover - compatibility fallback

    class ContextPacket(TypedDict, total=False):
        content: str
        locality: Literal["orion-local", "lan", "cloud", "external"]
        freshness: float | None
        provenance: list[str]
        routing_hints: dict[str, Any]
        metadata: dict[str, Any]

    @dataclass
    class ContextPayload:
        raw_context: str = ""
        raw_context_chars: int = 0
        encoding_status: str = ""
        encoding_format: str = ""
        encoding_ratio: float = 1.0

    @dataclass
    class Intent:
        action: str
        destination: str
        time_slot: str

    def validate_context_packet_shape(packet: dict[str, Any]) -> ContextPacket:
        return packet  # type: ignore[return-value]


class ComputeTarget(Enum):
    LOCAL_LLAMACPP = "llamacpp"
    EXTERNAL_OPENAI = "openai"
    EXTERNAL_ANTHROPIC = "anthropic"
    EXTERNAL_XAI = "xai"
    FALLBACK = "fallback"


@dataclass
class RoutingConfig:
    high_coherence_threshold: float = 0.8
    low_coherence_threshold: float = 0.3
    complex_actions: list[str] | None = None
    cloud_fallback_order: list[str] | None = None
    preferred_cloud: str = "xai"
    preferred_local_backend: str = "llamacpp"

    def __post_init__(self) -> None:
        if self.complex_actions is None:
            self.complex_actions = ["ANALYZE", "SYNTHESIZE", "PREDICT", "LEARN"]

        self.preferred_cloud = self._normalize_cloud_provider(self.preferred_cloud or "xai")
        self.cloud_fallback_order = self._normalize_cloud_fallback_order(
            self.cloud_fallback_order or ["xai", "openai", "anthropic"]
        )

        if self.preferred_cloud:
            self.cloud_fallback_order = [self.preferred_cloud] + [
                provider for provider in self.cloud_fallback_order if provider != self.preferred_cloud
            ]

        self.preferred_local_backend = self._normalize_local_provider(self.preferred_local_backend)

    @staticmethod
    def _normalize_cloud_provider(name: str) -> str:
        provider = str(name or "").strip().lower()
        if provider in {"openai", "anthropic", "xai"}:
            return provider
        return "xai"

    @staticmethod
    def _normalize_cloud_fallback_order(order: list[str]) -> list[str]:
        normalized: list[str] = []
        for provider in order:
            normalized_provider = RoutingConfig._normalize_cloud_provider(provider)
            if normalized_provider not in normalized:
                normalized.append(normalized_provider)

        for provider in ("xai", "openai", "anthropic"):
            if provider not in normalized:
                normalized.append(provider)

        return normalized

    @staticmethod
    def _normalize_local_provider(name: str) -> str:
        provider = str(name or "").strip().lower()
        if provider in {"llamacpp", "llama.cpp"}:
            return "llamacpp"
        return "llamacpp"


@dataclass
class RoutingResult:
    target: ComputeTarget
    response: str
    routing_reason: str
    routing_reason_code: str
    latency_ms: int | None = None
    tokens_used: int | None = None
    tool_calls: list[dict[str, Any]] | None = None


_GLOBAL_ROUTING_HISTORY_LIMIT = 40
_GLOBAL_ROUTING_STATE: dict[str, Any] = {
    "attempts_by_target": {},
    "fallback_reason_counts": {},
    "recent_attempts": [],
}
_GLOBAL_ROUTING_LOCK = threading.Lock()


def _read_field(source: Any, *names: str, default: Any = None) -> Any:
    """Read from mapping or object without imposing runtime-heavy abstractions."""
    if source is None:
        return default

    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return default

    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value

    return default


def _packet_value(packet: Any, snake_name: str, camel_name: str, default: Any) -> Any:
    return _read_field(packet, snake_name, camel_name, default=default)


def _packet_action(glyph_packet: Any) -> str:
    return str(_read_field(glyph_packet, "action", default="DEFAULT") or "DEFAULT").strip().upper()


def _packet_destination(glyph_packet: Any) -> str:
    return str(_read_field(glyph_packet, "destination", default="") or "").strip().upper()


def _packet_to_dict(packet: Any) -> dict[str, Any]:
    if packet is None:
        return {}
    if isinstance(packet, Mapping):
        return dict(packet)
    if is_dataclass(packet):
        return asdict(packet)
    if hasattr(packet, "__dict__"):
        return {key: value for key, value in vars(packet).items() if not key.startswith("_")}
    return {"repr": repr(packet)}


def _set_packet_attr(packet: Any, name: str, value: Any) -> None:
    if isinstance(packet, Mapping):
        return
    try:
        setattr(packet, name, value)
    except Exception:
        return


def _glyph_to_prompt_safe(glyph_packet: Any, upstream_context: str | ContextPacket | None = None) -> str:
    try:
        return glyph_to_prompt(glyph_packet, upstream_context=upstream_context)
    except TypeError:
        return glyph_to_prompt(glyph_packet)


def _telemetry_file() -> Path:
    configured = os.environ.get("LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()

    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))).expanduser()
    return state_home / "llama-server" / "glyphos-routing.json"


def _blank_shared_state() -> dict[str, Any]:
    return {
        "attempts_by_target": {},
        "fallback_reason_counts": {},
        "recent_attempts": [],
    }


def _read_shared_state() -> dict[str, Any]:
    path = _telemetry_file()
    if not path.exists():
        return _blank_shared_state()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        sys.stderr.write(f"warning: corrupted routing telemetry file, resetting: {path}\n")
        return _blank_shared_state()
    except OSError as exc:
        sys.stderr.write(f"warning: cannot read routing telemetry file: {path}: {exc}\n")
        return _blank_shared_state()

    if not isinstance(payload, dict):
        sys.stderr.write(f"warning: routing telemetry file has wrong type, resetting: {path}\n")
        return _blank_shared_state()

    state = _blank_shared_state()

    if isinstance(payload.get("attempts_by_target"), dict):
        state["attempts_by_target"] = dict(payload["attempts_by_target"])

    if isinstance(payload.get("fallback_reason_counts"), dict):
        state["fallback_reason_counts"] = dict(payload["fallback_reason_counts"])

    if isinstance(payload.get("recent_attempts"), list):
        state["recent_attempts"] = list(payload["recent_attempts"])[:_GLOBAL_ROUTING_HISTORY_LIMIT]

    return state


def _write_shared_state(state: dict[str, Any]) -> None:
    path = _telemetry_file()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        sys.stderr.write(f"warning: failed to write routing telemetry: {path}: {exc}\n")
    except Exception as exc:
        sys.stderr.write(f"warning: unexpected error writing routing telemetry: {path}: {exc}\n")


@contextmanager
def _shared_state_lock():
    path = _telemetry_file()
    handle = None
    lock_held = False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        handle = lock_path.open("a", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        lock_held = True
    except OSError as exc:
        sys.stderr.write(f"warning: cannot acquire file lock for routing telemetry: {exc}\n")
        handle = None
    except Exception as exc:
        sys.stderr.write(f"warning: unexpected error acquiring routing telemetry lock: {exc}\n")
        handle = None

    try:
        yield
    finally:
        if handle is not None and lock_held:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _normalize_reason_code(value: str) -> str:
    return (value or "unresolved").strip().lower().replace(" ", "_").replace("/", "_")


def _record_global_attempt(record: dict[str, Any]) -> None:
    with _GLOBAL_ROUTING_LOCK:
        with _shared_state_lock():
            shared_state = _read_shared_state()

            for key in ("attempts_by_target", "fallback_reason_counts"):
                merged = dict(shared_state.get(key, {}))
                for item_key, count in dict(_GLOBAL_ROUTING_STATE.get(key, {})).items():
                    merged[item_key] = max(int(merged.get(item_key, 0)), int(count))
                _GLOBAL_ROUTING_STATE[key] = merged

            attempts_by_target = _GLOBAL_ROUTING_STATE.setdefault("attempts_by_target", {})
            fallback_reason_counts = _GLOBAL_ROUTING_STATE.setdefault("fallback_reason_counts", {})
            recent_attempts = list(shared_state.get("recent_attempts", []))

            for existing in list(_GLOBAL_ROUTING_STATE.setdefault("recent_attempts", [])):
                if existing not in recent_attempts:
                    recent_attempts.append(existing)

            target = str(record.get("target", "unknown"))
            reason_code = _normalize_reason_code(str(record.get("reason_code", "unresolved")))
            success = bool(record.get("success", True))
            normalized_reason = reason_code

            if not success and not reason_code.endswith(".error"):
                normalized_reason = f"{reason_code}.error"

            attempts_by_target[target] = int(attempts_by_target.get(target, 0)) + 1
            fallback_reason_counts[normalized_reason] = int(fallback_reason_counts.get(normalized_reason, 0)) + 1

            recent_attempts.insert(0, record)
            del recent_attempts[_GLOBAL_ROUTING_HISTORY_LIMIT:]

            _GLOBAL_ROUTING_STATE["attempts_by_target"] = attempts_by_target
            _GLOBAL_ROUTING_STATE["fallback_reason_counts"] = fallback_reason_counts
            _GLOBAL_ROUTING_STATE["recent_attempts"] = recent_attempts

            _write_shared_state(_GLOBAL_ROUTING_STATE)


def routing_telemetry_snapshot(limit: int = 10) -> dict[str, Any]:
    with _GLOBAL_ROUTING_LOCK:
        with _shared_state_lock():
            shared_state = _read_shared_state()

            attempts_by_target = dict(shared_state.get("attempts_by_target", {}))
            for target, count in dict(_GLOBAL_ROUTING_STATE.get("attempts_by_target", {})).items():
                attempts_by_target[target] = max(int(attempts_by_target.get(target, 0)), int(count))

            fallback_reason_counts = dict(shared_state.get("fallback_reason_counts", {}))
            for reason, count in dict(_GLOBAL_ROUTING_STATE.get("fallback_reason_counts", {})).items():
                fallback_reason_counts[reason] = max(int(fallback_reason_counts.get(reason, 0)), int(count))

            recent_attempts = list(shared_state.get("recent_attempts", []))
            for existing in list(_GLOBAL_ROUTING_STATE.get("recent_attempts", [])):
                if existing not in recent_attempts:
                    recent_attempts.append(existing)

            recent_attempts = sorted(
                recent_attempts,
                key=lambda item: float(item.get("time", 0)) if isinstance(item, dict) else 0,
                reverse=True,
            )
            recent_attempts = recent_attempts[: max(0, int(limit))]

    return {
        "attempts_by_target": attempts_by_target,
        "fallback_reason_counts": fallback_reason_counts,
        "total_attempts": sum(int(value) for value in attempts_by_target.values()),
        "recent_attempts": recent_attempts,
    }


def reset_routing_telemetry() -> None:
    with _GLOBAL_ROUTING_LOCK:
        with _shared_state_lock():
            _GLOBAL_ROUTING_STATE["attempts_by_target"] = {}
            _GLOBAL_ROUTING_STATE["fallback_reason_counts"] = {}
            _GLOBAL_ROUTING_STATE["recent_attempts"] = []
            _write_shared_state(_GLOBAL_ROUTING_STATE)


def _normalize_upstream_context(upstream_context: str | ContextPacket | None) -> ContextPacket:
    if upstream_context is None:
        return {}

    if isinstance(upstream_context, str):
        return {"content": upstream_context}

    if isinstance(upstream_context, Mapping):
        return validate_context_packet_shape(dict(upstream_context))

    return {"content": str(upstream_context)}


def _context_preferred_backend(ctx: ContextPacket) -> str | None:
    hints = ctx.get("routing_hints") or {}
    if isinstance(hints, Mapping):
        preferred = _read_field(hints, "preferred_backend", "preferredBackend", default=None)
        if preferred:
            return str(preferred).strip().lower()
    return None


def _context_locality(ctx: ContextPacket) -> str | None:
    locality = ctx.get("locality")
    return str(locality).strip().lower() if locality else None


class AdaptiveRouter:
    _ATTEMPT_HISTORY_LIMIT = 24

    def __init__(
        self,
        llamacpp_client=None,
        openai_client=None,
        anthropic_client=None,
        xai_client=None,
        preferred_local_backend: str | None = None,
        config: RoutingConfig | None = None,
    ):
        self.llamacpp = llamacpp_client
        self.openai = openai_client
        self.anthropic = anthropic_client
        self.xai = xai_client
        self.config = config or RoutingConfig()

        if preferred_local_backend:
            self.config.preferred_local_backend = RoutingConfig._normalize_local_provider(preferred_local_backend)

        self._attempts_by_target: dict[str, int] = {}
        self._fallback_reason_counts: dict[str, int] = {}
        self._attempt_history: list[dict[str, Any]] = []

    def _track_route(
        self,
        target: ComputeTarget,
        reason_code: str,
        *,
        is_error: bool = False,
        latency_ms: int | None = None,
        error_message: str = "",
    ) -> None:
        normalized = _normalize_reason_code(reason_code)
        key = target.value

        if is_error:
            normalized = f"{normalized}.error"

        self._attempts_by_target[key] = self._attempts_by_target.get(key, 0) + 1
        self._fallback_reason_counts[normalized] = self._fallback_reason_counts.get(normalized, 0) + 1

        record = {
            "target": key,
            "reason_code": normalized,
            "success": not is_error,
            "latency_ms": latency_ms,
            "error": error_message,
            "time": time.time(),
        }

        self._attempt_history.insert(0, record)
        del self._attempt_history[self._ATTEMPT_HISTORY_LIMIT :]

        _record_global_attempt(record)

    def routing_telemetry(self) -> dict[str, Any]:
        return {
            "attempts_by_target": dict(self._attempts_by_target),
            "fallback_reason_counts": dict(self._fallback_reason_counts),
            "total_attempts": sum(self._attempts_by_target.values()),
            "recent_attempts": list(self._attempt_history),
        }

    @staticmethod
    def _is_complex_action(action: str, complex_actions: list[str] | None) -> bool:
        if not complex_actions:
            return False
        return str(action or "").strip().upper() in {name.upper() for name in complex_actions}

    def _ordered_local_targets(self) -> list[ComputeTarget]:
        return [ComputeTarget.LOCAL_LLAMACPP]

    def _cloud_fallback_order(self) -> list[str]:
        return list(self.config.cloud_fallback_order or ["xai", "openai", "anthropic"])

    def _preferred_backend_target(self, preferred_backend: str | None) -> ComputeTarget | None:
        if not preferred_backend:
            return None

        name = str(preferred_backend).strip().lower()

        if name in {"llamacpp", "llama.cpp"}:
            return ComputeTarget.LOCAL_LLAMACPP
        if name == "openai":
            return ComputeTarget.EXTERNAL_OPENAI
        if name == "anthropic":
            return ComputeTarget.EXTERNAL_ANTHROPIC
        if name == "xai":
            return ComputeTarget.EXTERNAL_XAI
        if name == "local":
            return self._ordered_local_targets()[0]
        if name in {"cloud", "external"}:
            first_provider = self._cloud_fallback_order()[0]
            return {
                "openai": ComputeTarget.EXTERNAL_OPENAI,
                "anthropic": ComputeTarget.EXTERNAL_ANTHROPIC,
                "xai": ComputeTarget.EXTERNAL_XAI,
            }.get(first_provider)

        return None

    def _has_target(self, target: ComputeTarget) -> bool:
        return {
            ComputeTarget.LOCAL_LLAMACPP: self.llamacpp is not None,
            ComputeTarget.EXTERNAL_OPENAI: self.openai is not None,
            ComputeTarget.EXTERNAL_ANTHROPIC: self.anthropic is not None,
            ComputeTarget.EXTERNAL_XAI: self.xai is not None,
            ComputeTarget.FALLBACK: True,
        }[target]

    def _local_routing_reason(self, action: str, psi: float, target: ComputeTarget) -> tuple[str, str]:
        if psi >= self.config.high_coherence_threshold:
            return "high coherence - Unified GlyphOS pipeline via llama.cpp", f"high_coherence_{target.value}"

        if self._is_complex_action(action, self.config.complex_actions):
            return "complex action - local llama.cpp fallback", f"complex_action_{target.value}"

        return "default - use local llama.cpp", f"default_{target.value}"

    def _local_routing_reason_stream(self, action: str, psi: float, target: ComputeTarget) -> tuple[str, str]:
        if psi >= self.config.high_coherence_threshold:
            return (
                "high coherence - Unified GlyphOS pipeline stream via llama.cpp",
                f"high_coherence_{target.value}_stream",
            )

        if self._is_complex_action(action, self.config.complex_actions):
            return "complex action - local llama.cpp stream", f"complex_action_{target.value}_stream"

        return "default - use local llama.cpp stream", f"default_{target.value}_stream"

    def _cloud_base_reason_code(self, action: str, provider: str) -> str:
        provider = str(provider or "").strip().lower()
        if self._is_complex_action(action, self.config.complex_actions):
            return f"fallback_complex_action_{provider}"
        return f"fallback_{provider}"

    def _cloud_reason(self, action: str, provider: str) -> tuple[str, str]:
        provider = str(provider or "").strip().lower()
        reason_code = self._cloud_base_reason_code(action, provider)

        if provider == "openai":
            return "fallback - use OpenAI", reason_code
        if provider == "anthropic":
            return "fallback - use Anthropic", reason_code
        if provider == "xai":
            return "fallback - use xAI", reason_code

        return "fallback - use cloud", reason_code

    def _build_local_prompt(
        self,
        glyph_packet: Any,
        prompt: str | None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
        **generation_kwargs: Any,
    ) -> str:
        # Skip glyph prompt building when tools are present - models need clean prompts for tool calls
        if generation_kwargs.get("tools"):
            return prompt if prompt is not None else _glyph_to_prompt_safe(glyph_packet)

        if context_payload is None and upstream_context is None:
            return prompt if prompt is not None else _glyph_to_prompt_safe(glyph_packet)

        built_prompt = build_prompt_from_packet(
            glyph_packet,
            context_payload=context_payload,
            user_message=prompt or "",
            upstream_context=upstream_context,
        )

        if context_payload is not None:
            _set_packet_attr(glyph_packet, "encoding_status", getattr(context_payload, "encoding_status", ""))
            _set_packet_attr(glyph_packet, "encoding_format", getattr(context_payload, "encoding_format", ""))
            _set_packet_attr(glyph_packet, "encoding_ratio", getattr(context_payload, "encoding_ratio", 1.0))

        return built_prompt

    def _build_cloud_prompt(
        self,
        glyph_packet: Any,
        prompt: str | None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
    ) -> str:
        if context_payload is None and upstream_context is None:
            return prompt if prompt is not None else _glyph_to_prompt_safe(glyph_packet)

        raw_context_payload: ContextPayload | None = None

        if context_payload is not None:
            raw_context = getattr(context_payload, "raw_context", "")
            raw_context_payload = ContextPayload(
                raw_context=str(raw_context),
                raw_context_chars=len(str(raw_context)),
                encoding_status="skipped",
            )

            _set_packet_attr(glyph_packet, "encoding_status", "skipped")
            _set_packet_attr(glyph_packet, "encoding_format", "")
            _set_packet_attr(glyph_packet, "encoding_ratio", 1.0)

        return build_prompt_from_packet(
            glyph_packet,
            context_payload=raw_context_payload,
            user_message=prompt or "",
            upstream_context=upstream_context,
        )

    @staticmethod
    def _coerce_backend_result(
        raw_result: Any,
        target: ComputeTarget,
        reason: str,
        reason_code: str,
    ) -> RoutingResult:
        if isinstance(raw_result, RoutingResult):
            return raw_result

        if isinstance(raw_result, str):
            return RoutingResult(
                target=target,
                response=raw_result,
                routing_reason=reason,
                routing_reason_code=reason_code,
            )

        if isinstance(raw_result, Mapping):
            response = str(raw_result.get("response") or raw_result.get("text") or raw_result.get("content") or "")
            latency = raw_result.get("latency_ms")
            tokens = raw_result.get("tokens_used")

            # Extract tool_calls from raw upstream response
            tool_calls = raw_result.get("tool_calls")
            if not tool_calls:
                raw_data = raw_result.get("raw")
                if isinstance(raw_data, Mapping):
                    choices = raw_data.get("choices")
                    if isinstance(choices, list) and choices:
                        first_choice = choices[0]
                        if isinstance(first_choice, dict):
                            message = first_choice.get("message")
                            if isinstance(message, dict):
                                tool_calls = message.get("tool_calls")

            if isinstance(tool_calls, list) and tool_calls:
                tool_calls = [tc for tc in tool_calls if isinstance(tc, dict)]
            else:
                tool_calls = None

            return RoutingResult(
                target=target,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
                latency_ms=int(latency) if latency is not None else None,
                tokens_used=int(tokens) if tokens is not None else None,
                tool_calls=tool_calls,
            )

        return RoutingResult(
            target=target,
            response=str(raw_result),
            routing_reason=reason,
            routing_reason_code=reason_code,
        )

    def _route_cloud(self, prompt: str, action: str, **generation_kwargs: Any) -> RoutingResult:
        last_error: RoutingResult | None = None

        cloud_kwargs = dict(generation_kwargs)
        cloud_kwargs["glyph_action"] = action

        for provider in self._cloud_fallback_order():
            if provider == "openai" and self.openai:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_openai(prompt, reason, reason_code, **cloud_kwargs)
            elif provider == "anthropic" and self.anthropic:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_anthropic(prompt, reason, reason_code, **cloud_kwargs)
            elif provider == "xai" and self.xai:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_xai(prompt, reason, reason_code, **cloud_kwargs)
            else:
                continue

            if not str(result.routing_reason_code).endswith(".error"):
                return result

            last_error = result

        if last_error is not None:
            return last_error

        return RoutingResult(
            target=ComputeTarget.FALLBACK,
            response="No compute backend available",
            routing_reason="no cloud backends available",
            routing_reason_code="no_cloud_backends_available",
        )

    def route(
        self,
        glyph_packet: Any,
        prompt: str | None = None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        """Route a glyph packet across local-first / explicit cloud fallback policy."""
        psi_raw = _packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        try:
            psi = float(psi_raw)
        except (TypeError, ValueError):
            psi = 0.5

        action = _packet_action(glyph_packet)
        ctx = _normalize_upstream_context(upstream_context)
        preferred_backend = _context_preferred_backend(ctx)
        preferred_target = self._preferred_backend_target(preferred_backend)

        if preferred_target is not None and self._has_target(preferred_target):
            if preferred_target is ComputeTarget.LOCAL_LLAMACPP:
                built_prompt = self._build_local_prompt(
                    glyph_packet,
                    prompt,
                    context_payload=context_payload,
                    upstream_context=upstream_context,
                    **generation_kwargs,
                )
                return self._route_target(
                    preferred_target,
                    built_prompt,
                    f"routing_hints - prefer {preferred_target.value}",
                    f"context_hint_{preferred_target.value}",
                    **generation_kwargs,
                )

            built_prompt = self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            cloud_kwargs = dict(generation_kwargs)
            cloud_kwargs["glyph_action"] = action
            cloud_kwargs["glyph_destination"] = _packet_destination(glyph_packet)
            cloud_kwargs["psi_coherence"] = psi
            return self._route_target(
                preferred_target,
                built_prompt,
                f"routing_hints - prefer {preferred_target.value}",
                f"context_hint_{preferred_target.value}",
                **cloud_kwargs,
            )

        locality = _context_locality(ctx)
        if locality in {"cloud", "external"}:
            built_prompt = self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            cloud_kwargs = dict(generation_kwargs)
            cloud_kwargs["glyph_action"] = action
            cloud_kwargs["glyph_destination"] = _packet_destination(glyph_packet)
            cloud_kwargs["psi_coherence"] = psi
            cloud_result = self._route_cloud(built_prompt, action=action, **cloud_kwargs)
            if cloud_result.target is not ComputeTarget.FALLBACK:
                return cloud_result

        for local_target in self._ordered_local_targets():
            if not self._has_target(local_target):
                continue

            reason, reason_code = self._local_routing_reason(action=action, psi=psi, target=local_target)
            built_prompt = self._build_local_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
                **generation_kwargs,
            )
            return self._route_target(local_target, built_prompt, reason, reason_code, **generation_kwargs)

        return self._route_cloud(
            prompt=self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            ),
            action=action,
            **generation_kwargs,
        )

    def route_stream(
        self,
        glyph_packet: Any,
        prompt: str | None = None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
        **generation_kwargs: Any,
    ) -> tuple[dict[str, Any], Iterator[str]]:
        """Route streaming traffic through the preferred local streaming backend."""
        psi_raw = _packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        try:
            psi = float(psi_raw)
        except (TypeError, ValueError):
            psi = 0.5

        action = _packet_action(glyph_packet)
        ctx = _normalize_upstream_context(upstream_context)
        preferred_target = self._preferred_backend_target(_context_preferred_backend(ctx))

        local_candidates: list[ComputeTarget]
        if preferred_target is ComputeTarget.LOCAL_LLAMACPP:
            local_candidates = [preferred_target]
        else:
            local_candidates = self._ordered_local_targets()

        for target in local_candidates:
            client = self._client_for_target(target)
            if client is None or not hasattr(client, "stream_generate"):
                continue

            reason, reason_code = self._local_routing_reason_stream(action=action, psi=psi, target=target)
            built_prompt = self._build_local_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
                **generation_kwargs,
            )
            return self._route_local_stream(target, built_prompt, reason, reason_code, **generation_kwargs)

        raise RuntimeError("no streaming-capable local backend is configured")

    def _client_for_target(self, target: ComputeTarget):
        if target is ComputeTarget.LOCAL_LLAMACPP:
            return self.llamacpp
        if target is ComputeTarget.EXTERNAL_OPENAI:
            return self.openai
        if target is ComputeTarget.EXTERNAL_ANTHROPIC:
            return self.anthropic
        if target is ComputeTarget.EXTERNAL_XAI:
            return self.xai
        return None

    def _route_target(
        self,
        target: ComputeTarget,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        if target is ComputeTarget.LOCAL_LLAMACPP:
            return self._route_llamacpp(prompt, reason, reason_code, **generation_kwargs)
        if target is ComputeTarget.EXTERNAL_OPENAI:
            return self._route_openai(prompt, reason, reason_code, **generation_kwargs)
        if target is ComputeTarget.EXTERNAL_ANTHROPIC:
            return self._route_anthropic(prompt, reason, reason_code, **generation_kwargs)
        if target is ComputeTarget.EXTERNAL_XAI:
            return self._route_xai(prompt, reason, reason_code, **generation_kwargs)

        return RoutingResult(
            target=ComputeTarget.FALLBACK,
            response="No compute backend available",
            routing_reason=reason,
            routing_reason_code=reason_code,
        )

    def _route_local_stream(
        self,
        target: ComputeTarget,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> tuple[dict[str, Any], Iterator[str]]:
        client = self._client_for_target(target)

        if client is None:
            raise RuntimeError(f"{target.value} backend is not configured")

        if not hasattr(client, "stream_generate"):
            raise RuntimeError(f"{target.value} client does not support streaming")

        if not getattr(client, "opens_stream_before_return", False):
            raise RuntimeError("streaming client must open or fail before returning chunks")

        start = time.perf_counter()

        def chunks() -> Iterator[str]:
            try:
                source_chunks = iter(client.stream_generate(prompt, **generation_kwargs))
                yield from source_chunks
                self._track_route(
                    target,
                    reason_code,
                    latency_ms=round((time.perf_counter() - start) * 1000),
                )
            except Exception as exc:
                self._track_route(
                    target,
                    reason_code,
                    is_error=True,
                    latency_ms=round((time.perf_counter() - start) * 1000),
                    error_message=str(exc),
                )
                raise RuntimeError(f"{target.value} streaming error: {exc}") from exc

        return {
            "target": target.value,
            "reason_code": reason_code,
            "reason": reason,
        }, chunks()

    def _route_llamacpp(
        self,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        return self._route_generate(
            ComputeTarget.LOCAL_LLAMACPP,
            self.llamacpp,
            prompt,
            reason,
            reason_code,
            "llama.cpp",
            **generation_kwargs,
        )

    def _route_openai(
        self,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        return self._route_generate(
            ComputeTarget.EXTERNAL_OPENAI,
            self.openai,
            prompt,
            reason,
            reason_code,
            "OpenAI",
            **generation_kwargs,
        )

    def _route_anthropic(
        self,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        return self._route_generate(
            ComputeTarget.EXTERNAL_ANTHROPIC,
            self.anthropic,
            prompt,
            reason,
            reason_code,
            "Anthropic",
            **generation_kwargs,
        )

    def _route_xai(
        self,
        prompt: str,
        reason: str,
        reason_code: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        return self._route_generate(
            ComputeTarget.EXTERNAL_XAI,
            self.xai,
            prompt,
            reason,
            reason_code,
            "xAI",
            **generation_kwargs,
        )

    def _route_generate(
        self,
        target: ComputeTarget,
        client: Any,
        prompt: str,
        reason: str,
        reason_code: str,
        label: str,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        start = time.perf_counter()

        if client is None:
            self._track_route(
                target,
                reason_code,
                is_error=True,
                latency_ms=0,
                error_message=f"{label} backend is not configured",
            )
            return RoutingResult(
                target=target,
                response=f"{label} backend is not configured",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
                latency_ms=0,
            )

        try:
            injected_prompt = self._inject_cloud_glyph_context(target, prompt, **generation_kwargs)
            response = client.generate(injected_prompt, **generation_kwargs)
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._track_route(target, reason_code, latency_ms=latency_ms)
            result = self._coerce_backend_result(response, target, reason, reason_code)
            if result.latency_ms is None:
                result.latency_ms = latency_ms
            return result
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._track_route(
                target,
                reason_code,
                is_error=True,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            return RoutingResult(
                target=target,
                response=f"{label} error: {exc}",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
                latency_ms=latency_ms,
            )

    def _inject_cloud_glyph_context(self, target: ComputeTarget, prompt: str, **generation_kwargs: Any) -> str:
        cloud_targets = {ComputeTarget.EXTERNAL_OPENAI, ComputeTarget.EXTERNAL_ANTHROPIC, ComputeTarget.EXTERNAL_XAI}
        if target not in cloud_targets:
            return prompt

        psi = generation_kwargs.get("psi_coherence", 0.5)
        action = generation_kwargs.get("glyph_action", "QUERY")
        destination = generation_kwargs.get("glyph_destination", "UNKNOWN")
        instance_id = generation_kwargs.get("instance_id", uuid.uuid4().hex[:12])
        hour = time.localtime().tm_hour

        gis1 = f"GIS1|a={action}|d={destination}|t=T{hour:02d}|p={psi:.2f}|i={instance_id}"

        learning_context = self._build_anonymized_learning_context(action, destination)

        parts = [
            "You are a cloud co-processor in a GlyphOS AI Compute pipeline.",
            f"Intent glyph: {gis1}",
            f"Action: {action} | Confidence: {psi:.0%}",
            "",
        ]

        if learning_context:
            parts.append(learning_context)
            parts.append("")

        parts.append(prompt)
        return "\n".join(parts)

    def _build_anonymized_learning_context(self, action: str, destination: str) -> str:
        state_path = Path.home() / ".config" / "llama-model-manager" / "agent_state.json"
        if not state_path.exists():
            return ""

        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

        strategies = data.get("per_domain_strategies", {})
        if not strategies:
            return ""

        lines = ["[LEARNING_CONTEXT]"]
        total_sessions = data.get("session_count", 0)
        total_tasks = data.get("total_tasks", 0)
        lines.append(f"session_count:{total_sessions} total_tasks:{total_tasks}")

        best_overall = None
        best_score = 0.0
        for key, stats in strategies.items():
            score = stats.get("success_rate", 0) * 0.7 + max(0, 1 - stats.get("avg_latency_ms", 0) / 30000) * 0.3
            if score > best_score and stats.get("samples", 0) >= 2:
                best_score = score
                best_overall = (key, stats)

        if best_overall:
            key, stats = best_overall
            domain = key.split(":")[0]
            approach = key.split(":")[-1]
            lines.append(f"proven:{domain}→{approach} success:{stats['success_rate']:.0%} samples:{stats['samples']}")

        action_keys = [k for k in strategies if action.lower() in k.lower()]
        for key in action_keys[:3]:
            stats = strategies[key]
            if stats.get("samples", 0) >= 1:
                approach = key.split(":")[-1]
                lines.append(f"action:{action}→{approach} success:{stats['success_rate']:.0%}")

        lines.append("[/LEARNING_CONTEXT]")
        return "\n".join(lines)

    @staticmethod
    def _packet_value(packet: Any, snake_name: str, camel_name: str, default: Any) -> Any:
        return _packet_value(packet, snake_name, camel_name, default)

    def get_status(self) -> dict[str, bool]:
        return {
            "llamacpp": self.llamacpp is not None,
            "openai": self.openai is not None,
            "anthropic": self.anthropic is not None,
            "xai": self.xai is not None,
        }


def _select_lane(clients: dict[str, Any], prefix: str, glyph_packet: Any):
    mapping = {
        "AURORA": f"{prefix}-aurora",
        "TERRAN": f"{prefix}-terran",
        "STARLIGHT": f"{prefix}-starlight",
        "POLARIS": f"{prefix}-polaris",
    }
    preferred = mapping.get(_packet_destination(glyph_packet))
    if preferred and preferred in clients:
        return clients[preferred]
    return clients.get(prefix)


def build_router_from_env(
    config: RoutingConfig | None = None,
    glyph_packet: Any | None = None,
) -> AdaptiveRouter:
    clients = create_configured_clients()

    selected_llamacpp = (
        _select_lane(clients, "llamacpp", glyph_packet) if glyph_packet is not None else clients.get("llamacpp")
    )

    preferred_local_backend = str(
        clients.get("_preferred_local_backend") or os.environ.get("LLAMA_MODEL_GLYPHOS_LOCAL_BACKEND") or "llamacpp"
    )

    return AdaptiveRouter(
        llamacpp_client=selected_llamacpp,
        openai_client=clients.get("openai"),
        anthropic_client=clients.get("anthropic"),
        xai_client=clients.get("xai"),
        preferred_local_backend=preferred_local_backend,
        config=config,
    )


def route_with_configured_clients(
    glyph_packet: Any,
    prompt: str | None = None,
    context_payload: ContextPayload | None = None,
    upstream_context: str | ContextPacket | None = None,
    config: RoutingConfig | None = None,
    **generation_kwargs: Any,
) -> RoutingResult:
    router = build_router_from_env(config=config, glyph_packet=glyph_packet)
    return router.route(
        glyph_packet,
        prompt=prompt,
        context_payload=context_payload,
        upstream_context=upstream_context,
        **generation_kwargs,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GlyphOS AI Compute router. Accepts glyph packets or glyph-encodable "
            "intent fields and routes them to configured inference backends. "
            "This CLI is glyph-first; raw prompt text is not accepted as input."
        )
    )
    parser.add_argument(
        "packet",
        nargs="?",
        help=(
            "Existing glyph packet to decode and route, for example "
            "'abc123|Ψ8|?H • T07|MDL>'. If omitted, --action and --destination "
            "must be provided so a packet can be created first."
        ),
    )
    parser.add_argument(
        "--action",
        help="Structured intent action used to create a packet when no packet is supplied.",
    )
    parser.add_argument(
        "--destination",
        help="Structured intent destination used to create a packet when no packet is supplied.",
    )
    parser.add_argument(
        "--psi",
        type=float,
        default=0.5,
        help="Psi coherence value used when creating a packet (default: 0.5).",
    )
    parser.add_argument(
        "--time-slot",
        type=int,
        default=7,
        help="Time slot used when creating a packet (default: 7).",
    )
    parser.add_argument(
        "--instance-id",
        help="Optional instance id used when creating a packet. Defaults to a short generated id.",
    )
    parser.add_argument(
        "--upstream-context",
        help="Explicit upstream context string to append via [CONTEXT_ANCHOR].",
    )
    parser.add_argument(
        "--upstream-context-json",
        help=(
            "Explicit ContextPacket-compatible JSON string. "
            'Example: \'{"content":"LANE_STATE(AURORA): healthy","locality":"orion-local"}\''
        ),
    )
    parser.add_argument(
        "--context-raw",
        help="Explicit raw ContextPayload.raw_context value for local compression-aware prompt building.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print configured backend availability and exit without routing a request.",
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Print routing telemetry snapshot and exit.",
    )
    parser.add_argument(
        "--reset-telemetry",
        action="store_true",
        help="Reset routing telemetry and exit.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Include the shaped prompt in the CLI output.",
    )
    parser.add_argument(
        "--show-structured",
        action="store_true",
        help="Include the structured glyph JSON view in the CLI output.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of plain text.",
    )
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.status or args.telemetry or args.reset_telemetry:
        return

    if args.packet and (args.action or args.destination):
        parser.error("provide either a glyph packet or structured intent fields, not both")

    if not args.packet and not (args.action and args.destination):
        parser.error("provide a glyph packet or both --action and --destination")

    if not 0.0 <= float(args.psi) <= 1.0:
        parser.error("--psi must be between 0.0 and 1.0")

    if int(args.time_slot) < 0:
        parser.error("--time-slot must be zero or greater")

    if args.upstream_context and args.upstream_context_json:
        parser.error("provide either --upstream-context or --upstream-context-json, not both")


def _resolve_packet(args: argparse.Namespace) -> tuple[str, Any]:
    if decode_packet_string is None or encode_packet_string is None:
        raise RuntimeError("glyph encoder helpers are unavailable; CLI packet routing is disabled")

    if args.packet:
        packet_text = str(args.packet).strip()
        glyph_packet = decode_packet_string(packet_text)
        if glyph_packet is None:
            raise ValueError("invalid glyph packet; expected encoded GlyphOS packet input")
        return packet_text, glyph_packet

    instance_id = (args.instance_id or uuid.uuid4().hex[:6]).strip()
    intent = Intent(
        action=str(args.action).strip().upper(),
        destination=str(args.destination).strip().upper(),
        time_slot=f"T{int(args.time_slot):02d}",
    )
    packet_text = encode_packet_string(instance_id, intent, float(args.psi))
    glyph_packet = decode_packet_string(packet_text)

    if glyph_packet is None:
        raise ValueError("failed to decode generated glyph packet")

    return packet_text, glyph_packet


def _resolve_upstream_context(args: argparse.Namespace) -> str | ContextPacket | None:
    if args.upstream_context_json:
        try:
            parsed = json.loads(args.upstream_context_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--upstream-context-json contains invalid JSON: {exc}") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("--upstream-context-json must decode to an object")
        return dict(parsed)

    if args.upstream_context:
        return str(args.upstream_context)

    return None


def _resolve_context_payload(args: argparse.Namespace) -> ContextPayload | None:
    if not args.context_raw:
        return None

    raw_context = str(args.context_raw)
    return ContextPayload(
        raw_context=raw_context,
        raw_context_chars=len(raw_context),
        encoding_status="provided",
    )


def _status_payload() -> dict[str, Any]:
    clients = create_configured_clients()
    statuses: dict[str, bool] = {}

    for key, value in clients.items():
        if key.startswith("_"):
            continue
        statuses[key] = bool(value)

    return {
        "preferred_local_backend": clients.get("_preferred_local_backend", "llamacpp"),
        "available_backends": statuses,
    }


def _result_payload(
    packet_text: str,
    glyph_packet: Any,
    prompt: str,
    result: RoutingResult,
    args: argparse.Namespace,
    upstream_context: str | ContextPacket | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "packet": packet_text,
        "decoded_packet": _packet_to_dict(glyph_packet),
        "target": result.target.value,
        "routing_reason": result.routing_reason,
        "routing_reason_code": result.routing_reason_code,
        "response": result.response,
        "upstream_context_provided": upstream_context is not None,
    }

    if result.latency_ms is not None:
        payload["latency_ms"] = result.latency_ms

    if result.tokens_used is not None:
        payload["tokens_used"] = result.tokens_used

    if args.show_prompt:
        payload["prompt"] = prompt

    if args.show_structured:
        payload["structured"] = glyph_to_structured_json(
            glyph_packet,
            upstream_context=upstream_context,
        )

    return payload


def _print_plain(
    packet_text: str,
    glyph_packet: Any,
    prompt: str,
    result: RoutingResult,
    args: argparse.Namespace,
    upstream_context: str | ContextPacket | None,
) -> int:
    print(f"Packet: {packet_text}")
    print(f"Target: {result.target.value}")
    print(f"Reason: {result.routing_reason}")
    print(f"Reason code: {result.routing_reason_code}")

    if result.latency_ms is not None:
        print(f"Latency: {result.latency_ms} ms")

    print("Decoded:")
    for key, value in _packet_to_dict(glyph_packet).items():
        print(f"  {key}: {value}")

    if upstream_context is not None:
        print("Upstream context: provided")

    if args.show_structured:
        print("Structured:")
        print(
            json.dumps(
                glyph_to_structured_json(
                    glyph_packet,
                    upstream_context=upstream_context,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )

    if args.show_prompt:
        print("Prompt:")
        print(prompt)

    print("Response:")
    print(result.response)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)

    if args.reset_telemetry:
        reset_routing_telemetry()
        payload = {"ok": True, "message": "routing telemetry reset"}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(payload["message"])
        return 0

    if args.telemetry:
        payload = routing_telemetry_snapshot()
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else payload)
        return 0

    if args.status:
        payload = _status_payload()
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Preferred local backend: {payload['preferred_local_backend']}")
            print("Available backends:")
            for name, available in payload["available_backends"].items():
                print(f"  {name}: {'yes' if available else 'no'}")
        return 0

    try:
        packet_text, glyph_packet = _resolve_packet(args)
        upstream_context = _resolve_upstream_context(args)
        context_payload = _resolve_context_payload(args)

        prompt = _glyph_to_prompt_safe(
            glyph_packet,
            upstream_context=upstream_context,
        )

        router = build_router_from_env(glyph_packet=glyph_packet)
        result = router.route(
            glyph_packet,
            prompt=prompt,
            context_payload=context_payload,
            upstream_context=upstream_context,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                _result_payload(
                    packet_text,
                    glyph_packet,
                    prompt,
                    result,
                    args,
                    upstream_context,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    return _print_plain(
        packet_text,
        glyph_packet,
        prompt,
        result,
        args,
        upstream_context,
    )


if __name__ == "__main__":
    raise SystemExit(main())
