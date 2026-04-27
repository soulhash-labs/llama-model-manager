"""
Adaptive routing across local and external AI backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any, Dict, Optional

from .api_client import create_configured_clients
from .glyph_to_prompt import glyph_to_prompt


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


def _normalize_reason_code(value: str) -> str:
    return (value or "unresolved").strip().lower().replace(" ", "_").replace("/", "_")


def _record_global_attempt(record: dict[str, Any]) -> None:
    with _GLOBAL_ROUTING_LOCK:
        attempts_by_target = _GLOBAL_ROUTING_STATE.setdefault("attempts_by_target", {})
        fallback_reason_counts = _GLOBAL_ROUTING_STATE.setdefault("fallback_reason_counts", {})
        recent_attempts = list(_GLOBAL_ROUTING_STATE.setdefault("recent_attempts", []))

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


def routing_telemetry_snapshot(limit: int = 10) -> dict[str, Any]:
    with _GLOBAL_ROUTING_LOCK:
        attempts_by_target = dict(_GLOBAL_ROUTING_STATE.get("attempts_by_target", {}))
        fallback_reason_counts = dict(_GLOBAL_ROUTING_STATE.get("fallback_reason_counts", {}))
        recent_attempts = list(_GLOBAL_ROUTING_STATE.get("recent_attempts", []))[: max(0, int(limit))]

    return {
        "attempts_by_target": attempts_by_target,
        "fallback_reason_counts": fallback_reason_counts,
        "total_attempts": sum(int(v) for v in attempts_by_target.values()),
        "recent_attempts": recent_attempts,
    }


def reset_routing_telemetry() -> None:
    with _GLOBAL_ROUTING_LOCK:
        _GLOBAL_ROUTING_STATE["attempts_by_target"] = {}
        _GLOBAL_ROUTING_STATE["fallback_reason_counts"] = {}
        _GLOBAL_ROUTING_STATE["recent_attempts"] = []


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

    def route(self, glyph_packet, prompt: Optional[str] = None) -> RoutingResult:
        if prompt is None:
            prompt = glyph_to_prompt(glyph_packet)
        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        action = glyph_packet.action

        if psi >= self.config.high_coherence_threshold and self.llamacpp:
            return self._route_llamacpp(prompt, "high coherence - prefer local llama.cpp", "high_coherence_local")

        if action in self.config.complex_actions:
            if self.anthropic:
                return self._route_anthropic(prompt, "complex action - prefer Claude", "complex_action_anthropic")
            if self.openai:
                return self._route_openai(prompt, "complex action - prefer GPT", "fallback_complex_action_openai")

        if self.llamacpp:
            return self._route_llamacpp(prompt, "default - use local llama.cpp", "default_local")
        if self.openai:
            return self._route_openai(prompt, "fallback - use OpenAI", "fallback_openai")
        if self.anthropic:
            return self._route_anthropic(prompt, "fallback - use Anthropic", "fallback_anthropic")
        if self.xai:
            return self._route_xai(prompt, "fallback - use xAI", "fallback_xai")
        return RoutingResult(
            target=ComputeTarget.FALLBACK,
            response="No compute backend available",
            routing_reason="no backends configured",
            routing_reason_code="no_backends_configured",
        )

    def _route_llamacpp(self, prompt: str, reason: str, reason_code: str) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.llamacpp.generate(prompt)
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
                routing_reason_code=reason_code,
            )

    def _route_openai(self, prompt: str, reason: str, reason_code: str) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.openai.generate(prompt)
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
                routing_reason_code=reason_code,
            )

    def _route_anthropic(self, prompt: str, reason: str, reason_code: str) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.anthropic.generate(prompt)
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
                routing_reason_code=reason_code,
            )

    def _route_xai(self, prompt: str, reason: str, reason_code: str) -> RoutingResult:
        start = time.perf_counter()
        try:
            response = self.xai.generate(prompt)
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
                routing_reason_code=reason_code,
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


def route_with_configured_clients(glyph_packet, prompt: Optional[str] = None, config: Optional[RoutingConfig] = None) -> RoutingResult:
    router = build_router_from_env(config=config, glyph_packet=glyph_packet)
    return router.route(glyph_packet, prompt=prompt)
