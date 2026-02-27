"""
GalacticSkill — Base class for all Galactic AI skills.

All skills (core and community) inherit from this class.
Skills self-register their tools via get_tools(), replacing
the hardcoded tool definitions in gateway_v2.py.
"""


class GalacticSkill:
    """Base class for all Galactic AI skills (core and community)."""

    # ── Metadata (override in subclass) ──────────────────────────────
    skill_name  = "unnamed_skill"
    version     = "0.1.0"
    author      = "unknown"
    description = "No description provided."
    category    = "general"          # browser, social, system, desktop, data, general
    icon        = "\u2699\ufe0f"
    is_core     = False              # Set by loader — True for skills/core/

    def __init__(self, core):
        self.core = core
        self.enabled = True

    def get_tools(self) -> dict:
        """Return tool definitions this skill provides.

        Format matches existing gateway tool dict:
        {
            "tool_name": {
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                },
                "fn": self.some_async_method
            }
        }
        """
        return {}

    async def run(self):
        """Optional background loop. Called once at startup as an asyncio task."""
        pass

    async def on_load(self):
        """Called after skill is instantiated. Use for async init."""
        pass

    async def on_unload(self):
        """Called before skill is disabled/removed. Cleanup here."""
        pass
