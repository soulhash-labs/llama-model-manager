"""
Adaptive routing across local and external AI backends.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..glyph.types import ContextPacket, ContextPayload, validate_context_packet_shape
from .api_client import create_configured_clients
from .glyph_to_prompt import build_prompt_from_packet, glyph_to_prompt


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

    def __post_init__(self) -> None:
        if self.complex_actions is None:
            self.complex_actions = ["ANALYZE", "SYNTHESIZE", "PREDICT", "LEARN"]
        self.preferred_cloud = self._normalize_cloud_provider(self.preferred_cloud or "xai")
        self.cloud_fallback_order = self._normalize_cloud_fallback_order(
            self.cloud_fallback_order or ["xai", "openai", "anthropic"]
        )
        if self.preferred_cloud:
            self.cloud_fallback_order = [self.preferred_cloud] + [
                p for p in self.cloud_fallback_order if p != self.preferred_cloud
            ]

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


@dataclass
class RoutingResult:
    target: ComputeTarget
    response: str
    routing_reason: str
    routing_reason_code: str
    latency_ms: int | None = None
    tokens_used: int | None = None


_GLOBAL_ROUTING_HISTORY_LIMIT = 40
_GLOBAL_ROUTING_STATE: dict[str, Any] = {
    "attempts_by_target": {},
    "fallback_reason_counts": {},
    "recent_attempts": [],
}
_GLOBAL_ROUTING_LOCK = threading.Lock()


def _telemetry_file() -> Path:
    configured = os.environ.get("LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
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
    except Exception:
        return _blank_shared_state()
    if not isinstance(payload, dict):
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
    except Exception:
        return


@contextmanager
def _shared_state_lock():
    path = _telemetry_file()
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        handle = lock_path.open("a", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except Exception:
        handle = None
    try:
        yield
    finally:
        if handle is not None:
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
        "total_attempts": sum(int(v) for v in attempts_by_target.values()),
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
    if isinstance(hints, dict):
        preferred = hints.get("preferred_backend")
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
        config: RoutingConfig | None = None,
    ):
        self.llamacpp = llamacpp_client
        self.openai = openai_client
        self.anthropic = anthropic_client
        self.xai = xai_client
        self.config = config or RoutingConfig()
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

    def _cloud_fallback_order(self) -> list[str]:
        return list(self.config.cloud_fallback_order or ["xai", "openai", "anthropic"])

    def _local_routing_reason(self, action: str, psi: float) -> tuple[str, str]:
        if psi >= self.config.high_coherence_threshold:
            return "high coherence - Unified GlyphOS pipeline", "high_coherence_glyphos_pipeline"
        if self._is_complex_action(action, self.config.complex_actions):
            return "complex action - local fallback", "complex_action_local"
        return "default - use local llama.cpp", "default_local"

    def _local_routing_reason_stream(self, action: str, psi: float) -> tuple[str, str]:
        if psi >= self.config.high_coherence_threshold:
            return "high coherence - Unified GlyphOS pipeline", "high_coherence_glyphos_pipeline"
        if self._is_complex_action(action, self.config.complex_actions):
            return "complex action - local stream", "complex_action_local_stream"
        return "default - use local llama.cpp", "default_local"

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
        glyph_packet,
        prompt: str | None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
    ) -> str:
        if context_payload is None and upstream_context is None:
            return prompt if prompt is not None else glyph_to_prompt(glyph_packet)

        built_prompt = build_prompt_from_packet(
            glyph_packet,
            context_payload=context_payload,
            user_message=prompt or "",
            upstream_context=upstream_context,
        )
        if context_payload is not None:
            glyph_packet.encoding_status = getattr(context_payload, "encoding_status", "")
            glyph_packet.encoding_format = getattr(context_payload, "encoding_format", "")
            glyph_packet.encoding_ratio = getattr(context_payload, "encoding_ratio", 1.0)
        return built_prompt

    def _build_cloud_prompt(
        self,
        glyph_packet,
        prompt: str | None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
    ) -> str:
        if context_payload is None and upstream_context is None:
            return prompt if prompt is not None else glyph_to_prompt(glyph_packet)

        raw_context_payload: ContextPayload | None = None
        if context_payload is not None:
            raw_context = getattr(context_payload, "raw_context", "")
            raw_context_payload = ContextPayload(
                raw_context=str(raw_context),
                raw_context_chars=len(str(raw_context)),
                encoding_status="skipped",
            )
            glyph_packet.encoding_status = "skipped"
            glyph_packet.encoding_format = ""
            glyph_packet.encoding_ratio = 1.0

        return build_prompt_from_packet(
            glyph_packet,
            context_payload=raw_context_payload,
            user_message=prompt or "",
            upstream_context=upstream_context,
        )

    def _route_cloud(self, prompt: str, action: str, **generation_kwargs: Any) -> RoutingResult:
        last_error: RoutingResult | None = None
        for provider in self._cloud_fallback_order():
            if provider == "openai" and self.openai:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_openai(prompt, reason, reason_code, **generation_kwargs)
            elif provider == "anthropic" and self.anthropic:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_anthropic(prompt, reason, reason_code, **generation_kwargs)
            elif provider == "xai" and self.xai:
                reason, reason_code = self._cloud_reason(action, provider)
                result = self._route_xai(prompt, reason, reason_code, **generation_kwargs)
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
        glyph_packet,
        prompt: str | None = None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
        **generation_kwargs: Any,
    ) -> RoutingResult:
        """Route a glyph packet across local-first / cloud fallback policy."""
        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        action = glyph_packet.action
        ctx = _normalize_upstream_context(upstream_context)
        preferred_backend = _context_preferred_backend(ctx)

        if preferred_backend == "llamacpp" and self.llamacpp:
            built_prompt = self._build_local_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            return self._route_llamacpp(
                built_prompt,
                "routing_hints - prefer local llama.cpp",
                "context_hint_llamacpp",
                **generation_kwargs,
            )

        if preferred_backend == "openai" and self.openai:
            built_prompt = self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            return self._route_openai(
                built_prompt,
                "routing_hints - prefer OpenAI",
                "context_hint_openai",
                **generation_kwargs,
            )

        if preferred_backend == "anthropic" and self.anthropic:
            built_prompt = self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            return self._route_anthropic(
                built_prompt,
                "routing_hints - prefer Anthropic",
                "context_hint_anthropic",
                **generation_kwargs,
            )

        if preferred_backend == "xai" and self.xai:
            built_prompt = self._build_cloud_prompt(
                glyph_packet,
                prompt,
                context_payload=context_payload,
                upstream_context=upstream_context,
            )
            return self._route_xai(
                built_prompt,
                "routing_hints - prefer xAI",
                "context_hint_xai",
                **generation_kwargs,
            )

        if not self.llamacpp:
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

        reason, reason_code = self._local_routing_reason(action=action, psi=psi)
        built_prompt = self._build_local_prompt(
            glyph_packet,
            prompt,
            context_payload=context_payload,
            upstream_context=upstream_context,
        )
        return self._route_llamacpp(built_prompt, reason, reason_code, **generation_kwargs)

    def route_stream(
        self,
        glyph_packet,
        prompt: str | None = None,
        context_payload: ContextPayload | None = None,
        upstream_context: str | ContextPacket | None = None,
        **generation_kwargs: Any,
    ) -> tuple[dict[str, Any], Iterator[str]]:
        """Route streaming traffic with local-first policy."""
        if not self.llamacpp:
            raise RuntimeError("no streaming-capable local llama.cpp backend is configured")

        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        reason, reason_code = self._local_routing_reason_stream(
            action=str(getattr(glyph_packet, "action", "")), psi=psi
        )
        built_prompt = self._build_local_prompt(
            glyph_packet,
            prompt,
            context_payload=context_payload,
            upstream_context=upstream_context,
        )
        return self._route_llamacpp_stream(built_prompt, reason, reason_code, **generation_kwargs)

    def _route_llamacpp_stream(
        self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any
    ) -> tuple[dict[str, Any], Iterator[str]]:
        if not hasattr(self.llamacpp, "stream_generate"):
            raise RuntimeError("local llama.cpp client does not support streaming")
        start = time.perf_counter()
        if not getattr(self.llamacpp, "opens_stream_before_return", False):
            raise RuntimeError("streaming client must open or fail before returning chunks")
        source_chunks = iter(self.llamacpp.stream_generate(prompt, **generation_kwargs))

        def chunks() -> Iterator[str]:
            try:
                yield from source_chunks
                self._track_route(
                    ComputeTarget.LOCAL_LLAMACPP,
                    reason_code,
                    latency_ms=round((time.perf_counter() - start) * 1000),
                )
            except Exception as exc:
                self._track_route(
                    ComputeTarget.LOCAL_LLAMACPP,
                    reason_code,
                    is_error=True,
                    latency_ms=round((time.perf_counter() - start) * 1000),
                    error_message=str(exc),
                )
                raise RuntimeError(f"llama.cpp streaming error: {exc}") from exc

        return {
            "target": ComputeTarget.LOCAL_LLAMACPP.value,
            "reason_code": reason_code,
            "reason": reason,
        }, chunks()

    def _route_llamacpp(self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.llamacpp.generate(prompt, **generation_kwargs)
            self._track_route(
                ComputeTarget.LOCAL_LLAMACPP, reason_code, latency_ms=round((time.perf_counter() - start) * 1000)
            )
            return RoutingResult(
                target=ComputeTarget.LOCAL_LLAMACPP,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
            )
        except Exception as exc:
            self._track_route(
                ComputeTarget.LOCAL_LLAMACPP,
                reason_code,
                is_error=True,
                latency_ms=round((time.perf_counter() - start) * 1000),
                error_message=str(exc),
            )
            return RoutingResult(
                target=ComputeTarget.LOCAL_LLAMACPP,
                response=f"llama.cpp error: {exc}",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
            )

    def _route_openai(self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.openai.generate(prompt, **generation_kwargs)
            self._track_route(
                ComputeTarget.EXTERNAL_OPENAI, reason_code, latency_ms=round((time.perf_counter() - start) * 1000)
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_OPENAI,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
            )
        except Exception as exc:
            self._track_route(
                ComputeTarget.EXTERNAL_OPENAI,
                reason_code,
                is_error=True,
                latency_ms=round((time.perf_counter() - start) * 1000),
                error_message=str(exc),
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_OPENAI,
                response=f"OpenAI error: {exc}",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
            )

    def _route_anthropic(self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.anthropic.generate(prompt, **generation_kwargs)
            self._track_route(
                ComputeTarget.EXTERNAL_ANTHROPIC, reason_code, latency_ms=round((time.perf_counter() - start) * 1000)
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_ANTHROPIC,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
            )
        except Exception as exc:
            self._track_route(
                ComputeTarget.EXTERNAL_ANTHROPIC,
                reason_code,
                is_error=True,
                latency_ms=round((time.perf_counter() - start) * 1000),
                error_message=str(exc),
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_ANTHROPIC,
                response=f"Anthropic error: {exc}",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
            )

    def _route_xai(self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.xai.generate(prompt, **generation_kwargs)
            self._track_route(
                ComputeTarget.EXTERNAL_XAI, reason_code, latency_ms=round((time.perf_counter() - start) * 1000)
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_XAI,
                response=response,
                routing_reason=reason,
                routing_reason_code=reason_code,
            )
        except Exception as exc:
            self._track_route(
                ComputeTarget.EXTERNAL_XAI,
                reason_code,
                is_error=True,
                latency_ms=round((time.perf_counter() - start) * 1000),
                error_message=str(exc),
            )
            return RoutingResult(
                target=ComputeTarget.EXTERNAL_XAI,
                response=f"xAI error: {exc}",
                routing_reason=f"{reason} - error",
                routing_reason_code=f"{reason_code}.error",
            )

    @staticmethod
    def _packet_value(packet: Any, snake_name: str, camel_name: str, default: Any) -> Any:
        snake_value = getattr(packet, snake_name, None)
        if snake_value is not None:
            return snake_value
        camel_value = getattr(packet, camel_name, None)
        if camel_value is not None:
            return camel_value
        return default

    def get_status(self) -> dict[str, bool]:
        return {
            "llamacpp": self.llamacpp is not None,
            "openai": self.openai is not None,
            "anthropic": self.anthropic is not None,
            "xai": self.xai is not None,
        }


def _packet_destination(glyph_packet: Any) -> str:
    return str(getattr(glyph_packet, "destination", "") or "").strip().upper()


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


def build_router_from_env(config: RoutingConfig | None = None, glyph_packet: Any | None = None) -> AdaptiveRouter:
    clients = create_configured_clients()
    selected_llamacpp = (
        _select_lane(clients, "llamacpp", glyph_packet) if glyph_packet is not None else clients.get("llamacpp")
    )
    return AdaptiveRouter(
        llamacpp_client=selected_llamacpp,
        openai_client=clients.get("openai"),
        anthropic_client=clients.get("anthropic"),
        xai_client=clients.get("xai"),
        config=config,
    )


def route_with_configured_clients(
    glyph_packet,
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
