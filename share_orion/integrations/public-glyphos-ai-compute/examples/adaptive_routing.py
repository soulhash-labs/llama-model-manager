#!/usr/bin/env python3
from glyphos_ai import AdaptiveRouter
from glyphos_ai.glyph.types import GlyphPacket

class MockGlyphPacket:
    action = "QUERY"
    destination = "MODEL"
    time_slot = "T07"
    psi_coherence = 0.85

router = AdaptiveRouter()
result = router.route(MockGlyphPacket())
print(f"Target: {result.target.value}")
print(f"Reason: {result.routing_reason}")
print("OK: routing demo complete")
