#!/usr/bin/env python3
from glyphos_ai.glyph import Intent, create_packet, encode_intent

packet = create_packet("BOOK", "MARS", psi=0.85)
print(f"Complete packet: {packet}")

intent = Intent(action="QUERY", destination="EARTH", time_slot=7)
glyph = encode_intent(intent)
print(f"Intent glyph: {glyph}")

print("\nOK: basic encoding demo complete")
