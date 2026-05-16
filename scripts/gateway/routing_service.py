from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from lmm_errors import GatewayError

_client_cache: dict[str, Any] | None = None
_client_cache_lock = threading.Lock()

# Learning Loop persistence store — set by gateway at startup
_persistence_store: Any = None

# Unified telemetry callback — set by gateway to merge routing events
# into the gateway telemetry store (closes the architectural gap between
# GlyphOS routing telemetry and gateway request telemetry).
_telemetry_callback: Callable[[dict[str, Any]], None] | None = None


def set_persistence_store(store: Any) -> None:
    """Set the Learning Loop persistence store for outcome recording."""
    global _persistence_store
    _persistence_store = store


def set_telemetry_callback(callback: Callable[[dict[str, Any]], None] | None) -> None:
    """Set unified telemetry callback to merge routing events into gateway telemetry."""
    global _telemetry_callback
    _telemetry_callback = callback


def _emit_routing_event(event: dict[str, Any]) -> None:
    """Emit a routing event to the unified telemetry callback if configured."""
    if _telemetry_callback is not None:
        try:
            _telemetry_callback(event)
        except Exception:
            pass


def _record_outcome(domain: str, approach: str, success: bool, latency_ms: float) -> None:
    """Record routing outcome to persistence store if available."""
    if _persistence_store is None:
        return
    try:
        _persistence_store.record_outcome(domain, approach, success=success, latency_ms=latency_ms)
    except Exception:
        pass


def create_router(*, cloud_routing_config_fn: Callable[[], tuple[list[str], str]]):
    from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore
    from glyphos_ai.ai_compute.router import AdaptiveRouter, RoutingConfig  # type: ignore

    global _client_cache
    if _client_cache is None:
        with _client_cache_lock:
            if _client_cache is None:
                _client_cache = create_configured_clients()
    clients = _client_cache
    cloud_fallback_order, preferred_cloud = cloud_routing_config_fn()
    return AdaptiveRouter(
        llamacpp_client=clients.get("llamacpp"),
        openai_client=clients.get("openai"),
        anthropic_client=clients.get("anthropic"),
        xai_client=clients.get("xai"),
        config=RoutingConfig(cloud_fallback_order=cloud_fallback_order, preferred_cloud=preferred_cloud),
    )


def _gateway_packet(model: str, context_payload: Any = None):
    from glyphos_ai.glyph.types import GlyphPacket  # type: ignore

    return GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
        encoding_status=context_payload.encoding_status if context_payload else "none",
        encoding_format=context_payload.encoding_format if context_payload else "",
        encoding_ratio=context_payload.encoding_ratio if context_payload else 1.0,
    )


def route_prompt(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    *,
    context_payload: Any = None,
    upstream_context: dict[str, Any] | None = None,
    create_router_fn: Callable[[], Any],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    packet = _gateway_packet(model, context_payload)
    start = time.perf_counter()
    router = create_router_fn()
    result = router.route(
        packet,
        prompt=prompt,
        context_payload=context_payload,
        upstream_context=upstream_context,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
    )
    latency_ms = round((time.perf_counter() - start) * 1000)
    if result.target.value == "fallback" or str(result.routing_reason_code).endswith(".error"):
        _record_outcome("routing", result.target.value, success=False, latency_ms=latency_ms)
        _emit_routing_event({
            "event": "route",
            "target": result.target.value,
            "reason_code": result.routing_reason_code,
            "reason": result.routing_reason,
            "success": False,
            "latency_ms": latency_ms,
            "model": model,
            "encoding_status": packet.encoding_status,
            "encoding_format": packet.encoding_format,
            "encoding_ratio": packet.encoding_ratio,
        })
        raise GatewayError(f"{result.target.value} route failed: {result.response}", target=result.target.value)
    _record_outcome("routing", result.target.value, success=True, latency_ms=latency_ms)
    if tools:
        _record_outcome("tool_call", result.target.value, success=bool(result.tool_calls), latency_ms=latency_ms)
    _emit_routing_event({
        "event": "route",
        "target": result.target.value,
        "reason_code": result.routing_reason_code,
        "reason": result.routing_reason,
        "success": True,
        "latency_ms": latency_ms,
        "model": model,
        "encoding_status": packet.encoding_status,
        "encoding_format": packet.encoding_format,
        "encoding_ratio": packet.encoding_ratio,
    })
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": result.target.value,
        "X-LMM-GlyphOS-Reason": result.routing_reason_code,
        "X-LMM-Encoding-Status": packet.encoding_status,
        "X-LMM-Encoding-Format": packet.encoding_format,
        "X-LMM-Route-Target": result.target.value,
    }
    return {
        "text": result.response,
        "target": result.target.value,
        "reason_code": result.routing_reason_code,
        "reason": result.routing_reason,
        "latency_ms": latency_ms,
        "route_start_ms": 0,
        "route_duration_ms": latency_ms,
        "tool_calls": result.tool_calls,
    }, headers


def route_prompt_stream(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    *,
    context_payload: Any = None,
    upstream_context: dict[str, Any] | None = None,
    create_router_fn: Callable[[], Any],
) -> tuple[dict[str, Any], dict[str, str], Iterator[str]]:
    packet = _gateway_packet(model, context_payload)
    start = time.perf_counter()
    router = create_router_fn()
    routed, chunks = router.route_stream(
        packet,
        prompt=prompt,
        context_payload=context_payload,
        upstream_context=upstream_context,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    route_duration_ms = round((time.perf_counter() - start) * 1000)
    _emit_routing_event({
        "event": "route_stream",
        "target": str(routed.get("target", "unknown")),
        "reason_code": str(routed.get("reason_code", "unknown")),
        "success": True,
        "latency_ms": route_duration_ms,
        "model": model,
        "encoding_status": packet.encoding_status,
        "encoding_format": packet.encoding_format,
        "encoding_ratio": packet.encoding_ratio,
    })
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": str(routed["target"]),
        "X-LMM-GlyphOS-Reason": str(routed["reason_code"]),
        "X-LMM-Encoding-Status": packet.encoding_status,
        "X-LMM-Encoding-Format": packet.encoding_format,
        "X-LMM-Route-Target": str(routed["target"]),
    }
    routed["route_start_ms"] = 0
    routed["route_duration_ms"] = route_duration_ms
    return routed, headers, chunks


__all__ = ["create_router", "route_prompt", "route_prompt_stream"]
