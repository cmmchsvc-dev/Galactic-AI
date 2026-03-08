"""
Galactic AI -- Monologue Formatter Utility
Transforms raw LLM thinking into structured, premium partitions.
"""

import re

class MonologueFormatter:
    """Utility to parse and format agent monologues into structured blocks."""
    
    BLOCKS = {
        "PLAN": "📋",
        "OBSERVATION": "👁️",
        "ANALYSIS": "🧠",
        "REFLECTION": "🔄",
        "CRITICAL": "⚠️",
        "DECISION": "🎯"
    }

    @staticmethod
    def format_text(text: str) -> str:
        """Partition raw text into emoji-prefix blocks."""
        if not text:
            return ""
            
        formatted = text
        for block, emoji in MonologueFormatter.BLOCKS.items():
            # Replace [BLOCK] or BLOCK: with emoji-prefixed version
            pattern = re.compile(rf'\[{block}\]|{block}:', re.IGNORECASE)
            formatted = pattern.sub(f"\n{emoji} **{block}**:", formatted)
            
        return formatted.strip()

    @staticmethod
    def strip_monologue(text: str) -> str:
        """Remove tags for clean final output representation."""
        if not text:
            return ""
        clean = text
        for block in MonologueFormatter.BLOCKS:
            pattern = re.compile(rf'\[{block}\]|{block}:', re.IGNORECASE)
            clean = pattern.sub("", clean)
        return clean.strip()
