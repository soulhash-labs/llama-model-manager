"""
Adaptive routing across local and external AI backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None


class AdaptiveRouter:
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

    def route(self, glyph_packet, prompt: Optional[str] = None) -> RoutingResult:
        if prompt is None:
            prompt = glyph_to_prompt(glyph_packet)
        psi = self._packet_value(glyph_packet, "psi_coherence", "psiCoherence", 0.5)
        action = glyph_packet.action

        if psi >= self.config.high_coherence_threshold and self.llamacpp:
            return self._route_llamacpp(prompt, "high coherence - prefer local llama.cpp")

        if action in self.config.complex_actions:
            if self.anthropic:
                return self._route_anthropic(prompt, "complex action - prefer Claude")
            if self.openai:
                return self._route_openai(prompt, "complex action - prefer GPT")

        if self.llamacpp:
            return self._route_llamacpp(prompt, "default - use local llama.cpp")
        if self.openai:
            return self._route_openai(prompt, "fallback - use OpenAI")
        if self.anthropic:
            return self._route_anthropic(prompt, "fallback - use Anthropic")
        if self.xai:
            return self._route_xai(prompt, "fallback - use xAI")
        return RoutingResult(target=ComputeTarget.FALLBACK, response="No compute backend available", routing_reason="no backends configured")

    def _route_llamacpp(self, prompt: str, reason: str) -> RoutingResult:
        try:
            response = self.llamacpp.generate(prompt)
            return RoutingResult(target=ComputeTarget.LOCAL_LLAMACPP, response=response, routing_reason=reason)
        except Exception as exc:
            return RoutingResult(target=ComputeTarget.LOCAL_LLAMACPP, response=f"llama.cpp error: {exc}", routing_reason=f"{reason} - error")

    def _route_openai(self, prompt: str, reason: str) -> RoutingResult:
        try:
            response = self.openai.generate(prompt)
            return RoutingResult(target=ComputeTarget.EXTERNAL_OPENAI, response=response, routing_reason=reason)
        except Exception as exc:
            return RoutingResult(target=ComputeTarget.EXTERNAL_OPENAI, response=f"OpenAI error: {exc}", routing_reason=f"{reason} - error")

    def _route_anthropic(self, prompt: str, reason: str) -> RoutingResult:
        try:
            response = self.anthropic.generate(prompt)
            return RoutingResult(target=ComputeTarget.EXTERNAL_ANTHROPIC, response=response, routing_reason=reason)
        except Exception as exc:
            return RoutingResult(target=ComputeTarget.EXTERNAL_ANTHROPIC, response=f"Anthropic error: {exc}", routing_reason=f"{reason} - error")

    def _route_xai(self, prompt: str, reason: str) -> RoutingResult:
        try:
            response = self.xai.generate(prompt)
            return RoutingResult(target=ComputeTarget.EXTERNAL_XAI, response=response, routing_reason=reason)
        except Exception as exc:
            return RoutingResult(target=ComputeTarget.EXTERNAL_XAI, response=f"xAI error: {exc}", routing_reason=f"{reason} - error")

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
