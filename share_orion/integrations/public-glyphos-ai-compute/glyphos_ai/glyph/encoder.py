"""
Glyph Encoder
=============
Encodes user intents into glyph strings for privacy and bandwidth optimization.

Format: {instance_id}|Ψ{level}|{action}{header} • {time_slot}|{destination}>
Example: abc123|Ψ7|⊕H • T07|MRS>
"""

import uuid
import re
from typing import Optional
from .types import (
    Intent, GlyphPacket, Glyphs, ACTION_MAP, DEST_MAP,
    PSI_LEVELS, psi_to_level, time_to_slot
)


class GlyphEncoder:
    """Encodes intents to glyphs and decodes glyphs back to intents"""
    
    @staticmethod
    def encode_intent(intent: Intent) -> str:
        """Encode an Intent to glyph string
        
        Args:
            intent: Intent to encode
            
        Returns:
            Glyph string in format: ⊕H • T07|MRS>
        """
        action = ACTION_MAP.get(intent.action, Glyphs.ACTION_QUERY)
        header = Glyphs.HEADER
        time = time_to_slot(intent.time_slot)
        destination = DEST_MAP.get(intent.destination, "UNK")
        
        return f"{action}{header} • {time}|{destination}>"
    
    @staticmethod
    def encode_psi(psi: float) -> str:
        """Encode ψ (psi) coherence level
        
        Args:
            psi: Coherence value (0-1)
            
        Returns:
            Psi glyph string: Ψ7
        """
        return psi_to_level(psi)
    
    @staticmethod
    def encode_packet(
        instance_id: str,
        intent: Intent,
        psi: float
    ) -> str:
        """Encode a complete glyph packet
        
        Args:
            instance_id: Instance identifier
            intent: Intent to encode
            psi: Coherence value (0-1)
            
        Returns:
            Complete glyph packet: abc123|Ψ7|⊕H•T07|MRS>
        """
        glyph_intent = GlyphEncoder.encode_intent(intent)
        glyph_psi = GlyphEncoder.encode_psi(psi)
        
        return f"{instance_id}|{glyph_psi}|{glyph_intent}"
    
    @staticmethod
    def decode_intent(glyph: str) -> Optional[Intent]:
        """Decode a glyph string to Intent
        
        Args:
            glyph: Glyph string to decode (e.g., ⊕H • T07|MRS>)
            
        Returns:
            Intent object or None if invalid
        """
        # Parse format: ⊕H • T07|MRS>
        match = re.match(
            r"^([⊕?+×↔▶⏸■⟲↻⊎⊔✓✗⊕⊖⊝⊜⊘⊚⊰⊱⤓⤒◉◎⊡➤◂◃⊲⊳⊛⊚⊜⊝⊠⊦⊧⊨⊩⊪⊬⊭⊮⊯⊰⊱⊲⊳⊸⊹⊺⊻⊼⊽⊾⊿]+)H • (T\d+) \|([A-Z]+)>$",
            glyph
        )
        
        if not match:
            return None
        
        action_glyph, time, destination = match.groups()
        
        # Reverse lookup action
        action = "QUERY"
        for act, gl in ACTION_MAP.items():
            if gl == action_glyph:
                action = act
                break
        
        # Reverse lookup destination
        dest = "UNKNOWN"
        for d, code in DEST_MAP.items():
            if code == destination:
                dest = d
                break
        
        # Parse time slot
        time_slot = int(time.replace("T", ""))
        
        return Intent(action=action, destination=dest, time_slot=time_slot)
    
    @staticmethod
    def decode_packet(packet: str) -> Optional[GlyphPacket]:
        """Decode a glyph packet to GlyphPacket
        
        Args:
            packet: Glyph packet to decode
            
        Returns:
            GlyphPacket object or None if invalid
        """
        match = re.match(
            r"^([A-Za-z0-9]+)\|Ψ(\d)\|([⊕?+×↔▶⏸■⟲↻⊎⊔✓✗⊕⊖⊝⊜⊘⊚⊰⊱⤓⤒◉◎⊡➤◂◃⊲⊳⊛⊚⊜⊝⊠⊦⊧⊨⊩⊪⊬⊭⊮⊯⊰⊱⊲⊳⊸⊹⊺⊻⊼⊽⊾⊿]+)H • (T\d+)\|([A-Z]+)>$",
            packet
        )
        
        if not match:
            return None
        
        instance_id, psi_str, glyph_part, time, destination = match.groups()
        
        # Extract action
        action_glyph_match = re.match(
            r"^([⊕?+×↔▶⏸■⟲↻⊎⊔✓✗⊕⊖⊝⊜⊘⊚⊰⊱⤓⤒◉◎⊡➤◂◃⊲⊳⊛⊚⊜⊝⊠⊦⊧⊨⊩⊪⊬⊭⊮⊯⊰⊱⊲⊳⊸⊹⊺⊻⊼⊽⊾⊿]+)",
            glyph_part
        )
        action_glyph = action_glyph_match.group(1) if action_glyph_match else "⊕"
        
        action = "QUERY"
        for act, gl in ACTION_MAP.items():
            if gl == action_glyph:
                action = act
                break
        
        # Reverse lookup destination
        dest = "UNKNOWN"
        for d, code in DEST_MAP.items():
            if code == destination:
                dest = d
                break
        
        return GlyphPacket(
            instance_id=instance_id,
            psi_coherence=int(psi_str) / 10,
            action=action,
            header="H",
            time_slot=time,
            destination=dest,
        )


# === Convenience Functions ===

def encode_intent(intent: Intent | str, destination: str | None = None, time_slot: int = 0) -> str:
    """Encode an Intent or simple action/destination tuple to a glyph string."""
    if isinstance(intent, Intent):
        normalized = intent
    else:
        normalized = Intent(action=str(intent), destination=str(destination or "UNKNOWN"), time_slot=int(time_slot))
    return GlyphEncoder.encode_intent(normalized)


def encode_packet(instance_id: str, intent: Intent, psi: float) -> str:
    """Encode a complete glyph packet"""
    return GlyphEncoder.encode_packet(instance_id, intent, psi)


def decode_packet(packet: str) -> Optional[GlyphPacket]:
    """Decode a glyph packet"""
    return GlyphEncoder.decode_packet(packet)


def create_packet(action: str, destination: str, psi: float = 0.5, time_slot: int = 7) -> str:
    """Quick create a glyph packet
    
    Args:
        action: Action (BOOK, QUERY, EXECUTE, etc.)
        destination: Destination (MARS, EARTH, MODEL, etc.)
        psi: Coherence value (0-1)
        time_slot: Time slot (0-9), default 7
        
    Returns:
        Complete glyph packet string
    """
    instance_id = uuid.uuid4().hex[:6]
    intent = Intent(action=action, destination=destination, time_slot=time_slot)
    return encode_packet(instance_id, intent, psi)


# === Quick Access ===

GlyphEncoder_book = lambda dest, t=0: encode_intent(Intent("BOOK", dest, t))
GlyphEncoder_query = lambda dest, t=0: encode_intent(Intent("QUERY", dest, t))
GlyphEncoder_execute = lambda dest, t=0: encode_intent(Intent("EXECUTE", dest, t))
GlyphEncoder_verify = lambda dest, t=0: encode_intent(Intent("VERIFY", dest, t))


# === CLI Entry Point ===

def main():
    """CLI entry point for glyph-encode."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Glyph Encoder - Encode intents to glyph strings")
    parser.add_argument("action", choices=["BOOK", "QUERY", "EXECUTE", "ANALYZE", "SYNTHESIZE"], 
                        help="Action to encode")
    parser.add_argument("destination", help="Destination (MARS, EARTH, etc.)")
    parser.add_argument("-p", "--psi", type=float, default=0.5, help="Psi coherence (0-1)")
    parser.add_argument("-t", "--time-slot", type=int, default=0, help="Time slot (0-9)")
    parser.add_argument("--packet", action="store_true", help="Output full packet instead of glyph")
    
    args = parser.parse_args()
    
    intent = Intent(
        action=args.action,
        destination=args.destination,
        time_slot=args.time_slot,
    )
    
    if args.packet:
        result = encode_packet(uuid.uuid4().hex[:6], intent, args.psi)
    else:
        result = encode_intent(intent)
    
    print(result)
    return 0


if __name__ == "__main__":
    main()
