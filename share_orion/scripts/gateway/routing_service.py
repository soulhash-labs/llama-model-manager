from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from lmm_errors import GatewayError


def create_router(*, cloud_routing_config_fn: Callable[[], tuple[list[str], str]]):
    from glyphos_ai.ai_compute.api_client import create_configured_clients  # type: ignore
    from glyphos_ai.ai_compute.router import AdaptiveRouter, RoutingConfig  # type: ignore

    clients = create_configured_clients()
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
    )
    latency_ms = round((time.perf_counter() - start) * 1000)
    if result.target.value == "fallback" or str(result.routing_reason_code).endswith(".error"):
        raise GatewayError(f"{result.target.value} route failed: {result.response}", target=result.target.value)
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
    headers = {
        "X-LMM-Route-Mode": "routed",
        "X-LMM-GlyphOS-Target": str(routed["target"]),
        "X-LMM-GlyphOS-Reason": str(routed["reason_code"]),
        "X-LMM-Encoding-Status": packet.encoding_status,
        "X-LMM-Encoding-Format": packet.encoding_format,
        "X-LMM-Route-Target": str(routed["target"]),
    }
    routed["route_start_ms"] = 0
    routed["route_duration_ms"] = round((time.perf_counter() - start) * 1000)
    return routed, headers, chunks


__all__ = ["create_router", "route_prompt", "route_prompt_stream"]
