"""
Adaptive routing across local and external AI backends.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import fcntl
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, Iterator, Optional

from .api_client import create_configured_clients
from .glyph_to_prompt import glyph_to_prompt, build_prompt_from_packet


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

    def __post_init__(self) -> None:
        if self.complex_actions is None:
            self.complex_actions = ["ANALYZE", "SYNTHESIZE", "PREDICT", "LEARN"]


@dataclass
class RoutingResult:
    target: ComputeTarget
    response: str
    routing_reason: str
    routing_reason_code: str
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None


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
            recent_attempts = sorted(recent_attempts, key=lambda item: float(item.get("time", 0)) if isinstance(item, dict) else 0, reverse=True)
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


class AdaptiveRouter:
    _ATTEMPT_HISTORY_LIMIT = 24

    def __init__(
        self,
        llamacpp_client=None,
        openai_client=None,
        anthropic_client=None,
        xai_client=None,
        config: Optional[RoutingConfig] = None,
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
        latency_ms: Optional[int] = None,
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
        del self._attempt_history[self._ATTEMPT_HISTORY_LIMIT:]

        _record_global_attempt(record)

    def routing_telemetry(self) -> dict[str, Any]:
        return {
            "attempts_by_target": dict(self._attempts_by_target),
            "fallback_reason_counts": dict(self._fallback_reason_counts),
            "total_attempts": sum(self._attempts_by_target.values()),
            "recent_attempts": list(self._attempt_history),
        }

    def route(self, glyph_packet, prompt: Optional[str] = None, context_payload=None, **generation_kwargs: Any) -> RoutingResult:
        """Route a glyph packet to the appropriate backend.

        When context_payload is provided, encoding is applied ONLY for
        local llama.cpp targets. Cloud backends always receive raw context.
        When context_payload is None (backward compat), behavior is unchanged.
        """
        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        action = glyph_packet.action

        # --- Determine target first, then apply encoding ---
        if psi >= self.config.high_coherence_threshold and self.llamacpp:
            target = ComputeTarget.LOCAL_LLAMACPP
            reason = "high coherence - prefer local llama.cpp"
            reason_code = "high_coherence_local"
        elif action in self.config.complex_actions:
            if self.anthropic:
                target = ComputeTarget.EXTERNAL_ANTHROPIC
                reason = "complex action - prefer Claude"
                reason_code = "complex_action_anthropic"
            elif self.openai:
                target = ComputeTarget.EXTERNAL_OPENAI
                reason = "complex action - prefer GPT"
                reason_code = "fallback_complex_action_openai"
            elif self.llamacpp:
                target = ComputeTarget.LOCAL_LLAMACPP
                reason = "complex action - local fallback"
                reason_code = "complex_action_local"
            else:
                target = None
        elif self.llamacpp:
            target = ComputeTarget.LOCAL_LLAMACPP
            reason = "default - use local llama.cpp"
            reason_code = "default_local"
        elif self.openai:
            target = ComputeTarget.EXTERNAL_OPENAI
            reason = "fallback - use OpenAI"
            reason_code = "fallback_openai"
        elif self.anthropic:
            target = ComputeTarget.EXTERNAL_ANTHROPIC
            reason = "fallback - use Anthropic"
            reason_code = "fallback_anthropic"
        elif self.xai:
            target = ComputeTarget.EXTERNAL_XAI
            reason = "fallback - use xAI"
            reason_code = "fallback_xai"
        else:
            return RoutingResult(
                target=ComputeTarget.FALLBACK,
                response="No compute backend available",
                routing_reason="no backends configured",
                routing_reason_code="no_backends_configured",
            )

        # --- Build prompt with encoding awareness ---
        if context_payload is not None:
            # Encode ONLY for local llama.cpp; cloud gets raw context
            if target == ComputeTarget.LOCAL_LLAMACPP:
                # Local: use encoding-aware prompt builder (may include Ψ)
                built_prompt = build_prompt_from_packet(glyph_packet, context_payload, prompt or "")
                # Mirror encoding decision into the packet for telemetry
                glyph_packet.encoding_status = context_payload.encoding_status
                glyph_packet.encoding_format = context_payload.encoding_format
                glyph_packet.encoding_ratio = context_payload.encoding_ratio
            else:
                # Cloud: force raw context, skip encoding
                from glyphos_ai.glyph.types import ContextPayload
                raw_context = getattr(context_payload, "raw_context", "")
                raw_cp = ContextPayload(
                    raw_context=raw_context,
                    raw_context_chars=len(raw_context),
                    encoding_status="skipped",
                )
                built_prompt = build_prompt_from_packet(glyph_packet, raw_cp, prompt or "")
                glyph_packet.encoding_status = "skipped"
                glyph_packet.encoding_format = ""
                glyph_packet.encoding_ratio = 1.0
        else:
            # Backward compat: no context_payload, use old behavior
            built_prompt = prompt if prompt is not None else glyph_to_prompt(glyph_packet)

        # --- Execute route ---
        if target == ComputeTarget.LOCAL_LLAMACPP:
            return self._route_llamacpp(built_prompt, reason, reason_code, **generation_kwargs)
        elif target == ComputeTarget.EXTERNAL_OPENAI:
            return self._route_openai(built_prompt, reason, reason_code, **generation_kwargs)
        elif target == ComputeTarget.EXTERNAL_ANTHROPIC:
            return self._route_anthropic(built_prompt, reason, reason_code, **generation_kwargs)
        elif target == ComputeTarget.EXTERNAL_XAI:
            return self._route_xai(built_prompt, reason, reason_code, **generation_kwargs)
        else:
            return RoutingResult(
                target=ComputeTarget.FALLBACK,
                response="No compute backend available",
                routing_reason="no backends configured",
                routing_reason_code="no_backends_configured",
            )

    def route_stream(self, glyph_packet, prompt: Optional[str] = None, context_payload=None, **generation_kwargs: Any) -> tuple[dict[str, Any], Iterator[str]]:
        """Stream routing with encoding awareness.

        Streaming is only available for local llama.cpp.
        When context_payload is provided, encoding is applied for local target.
        """
        if self.llamacpp:
            # Streaming only works with local llama.cpp — always encode if payload present
            if context_payload is not None:
                built_prompt = build_prompt_from_packet(glyph_packet, context_payload, prompt or "")
                glyph_packet.encoding_status = context_payload.encoding_status
                glyph_packet.encoding_format = context_payload.encoding_format
                glyph_packet.encoding_ratio = context_payload.encoding_ratio
            else:
                built_prompt = prompt if prompt is not None else glyph_to_prompt(glyph_packet)

            psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
            if psi >= self.config.high_coherence_threshold:
                reason = "high coherence - prefer local llama.cpp"
                reason_code = "high_coherence_local"
            else:
                reason = "default - use local llama.cpp"
                reason_code = "default_local"
            return self._route_llamacpp_stream(built_prompt, reason, reason_code, **generation_kwargs)

        raise RuntimeError("no streaming-capable local llama.cpp backend is configured")

    def _route_llamacpp_stream(self, prompt: str, reason: str, reason_code: str, **generation_kwargs: Any) -> tuple[dict[str, Any], Iterator[str]]:
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
            self._track_route(ComputeTarget.LOCAL_LLAMACPP, reason_code, latency_ms=round((time.perf_counter() - start) * 1000))
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
            self._track_route(ComputeTarget.EXTERNAL_OPENAI, reason_code, latency_ms=round((time.perf_counter() - start) * 1000))
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
            self._track_route(ComputeTarget.EXTERNAL_ANTHROPIC, reason_code, latency_ms=round((time.perf_counter() - start) * 1000))
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
            self._track_route(ComputeTarget.EXTERNAL_XAI, reason_code, latency_ms=round((time.perf_counter() - start) * 1000))
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

    def get_status(self) -> Dict[str, bool]:
        return {
            "llamacpp": self.llamacpp is not None,
            "openai": self.openai is not None,
            "anthropic": self.anthropic is not None,
            "xai": self.xai is not None,
        }


def _packet_destination(glyph_packet: Any) -> str:
    return str(getattr(glyph_packet, 'destination', '') or '').strip().upper()


def _select_lane(clients: Dict[str, Any], prefix: str, glyph_packet: Any):
    mapping = {
        'AURORA': f'{prefix}-aurora',
        'TERRAN': f'{prefix}-terran',
        'STARLIGHT': f'{prefix}-starlight',
        'POLARIS': f'{prefix}-polaris',
    }
    preferred = mapping.get(_packet_destination(glyph_packet))
    if preferred and preferred in clients:
        return clients[preferred]
    return clients.get(prefix)


def build_router_from_env(config: Optional[RoutingConfig] = None, glyph_packet: Any | None = None) -> AdaptiveRouter:
    clients = create_configured_clients()
    selected_llamacpp = _select_lane(clients, 'llamacpp', glyph_packet) if glyph_packet is not None else clients.get('llamacpp')
    return AdaptiveRouter(
        llamacpp_client=selected_llamacpp,
        openai_client=clients.get('openai'),
        anthropic_client=clients.get('anthropic'),
        xai_client=clients.get('xai'),
        config=config,
    )


def route_with_configured_clients(
    glyph_packet,
    prompt: Optional[str] = None,
    config: Optional[RoutingConfig] = None,
    **generation_kwargs: Any,
) -> RoutingResult:
    router = build_router_from_env(config=config, glyph_packet=glyph_packet)
    return router.route(glyph_packet, prompt=prompt, **generation_kwargs)
