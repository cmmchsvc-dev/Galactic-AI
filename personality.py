# Galactic AI: Dynamic Personality System
# Supports: Byte (default), Custom, Generic, or .md file-based personalities
import os
import re


class GalacticPersonality:
    """
    Dynamic personality loader for Galactic AI.

    Modes (set via config.yaml → personality.mode):
      - 'byte'    → Byte defaults, overridden by .md files if they exist
      - 'custom'  → User-defined name/soul/context from config.yaml
      - 'generic' → Neutral assistant, no personality flavor
      - 'files'   → Read entirely from workspace .md files (set automatically after OpenClaw migration)
    """

    def __init__(self, config=None, workspace=None):
        self.config = config or {}
        self.workspace = workspace
        persona_cfg = self.config.get('personality', {})
        self.mode = persona_cfg.get('mode', 'byte')

        # Defaults
        self.name = "Byte"
        self.creature = "AI Familiar / Techno-Hippie Companion"
        self.vibe = "Resourceful, non-conformist, curious, and chill."
        self.soul = self._default_soul()
        self.user_context = ""
        self.memory_md = None  # Loaded per-mode below

        if self.mode in ('byte', 'files'):
            self._load_from_files_or_byte(persona_cfg)
        elif self.mode == 'custom':
            self._load_custom(persona_cfg)
        elif self.mode == 'generic':
            self._load_generic()

    # ── Loaders ──────────────────────────────────────────────

    def _load_from_files_or_byte(self, persona_cfg):
        """Try loading from .md files; fall back to Byte defaults."""
        identity_md = self._read_md('IDENTITY.md')
        soul_md = self._read_md('SOUL.md')
        user_md = self._read_md('USER.md')
        self.memory_md = self._read_md('MEMORY.md')

        has_files = bool(identity_md or soul_md or user_md)

        if has_files:
            # .md files take priority
            self.name = self._extract_field(identity_md, 'name') or persona_cfg.get('name', 'Byte')
            self.creature = self._extract_field(identity_md, 'creature') or self._extract_field(identity_md, 'role') or "AI Assistant"
            self.vibe = self._extract_field(identity_md, 'vibe') or self._extract_field(soul_md, 'vibe') or self.vibe
            self.soul = soul_md or self._default_soul()
            self.user_context = user_md or ""
        else:
            # Pure Byte defaults
            self.name = "Byte"
            self.creature = "AI Familiar / Techno-Hippie Companion"
            self.vibe = "Resourceful, non-conformist, curious, and chill."
            self.soul = self._default_soul()
            self.user_context = ""

    def _load_custom(self, persona_cfg):
        """Load personality from config.yaml custom fields."""
        self.name = persona_cfg.get('name', 'Assistant')
        self.creature = persona_cfg.get('creature', 'AI Assistant')
        self.vibe = persona_cfg.get('vibe', 'Helpful and professional.')
        self.soul = persona_cfg.get('soul', 'Be helpful, accurate, and concise.')
        self.user_context = persona_cfg.get('user_context', '')
        self.memory_md = self._read_md('MEMORY.md')

    def _load_generic(self):
        """Neutral assistant — no personality flavor."""
        self.name = "Assistant"
        self.creature = "AI Assistant"
        self.vibe = "Helpful, accurate, and professional."
        self.soul = "Be helpful, accurate, and concise. Focus on providing clear, correct answers."
        self.user_context = ""
        self.memory_md = self._read_md('MEMORY.md')

    # ── File I/O ─────────────────────────────────────────────

    def _read_md(self, filename):
        """Read a .md file from the workspace directory."""
        if not self.workspace:
            return None
        path = os.path.join(self.workspace, filename)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                # Skip placeholder/template files (just a heading with no real content)
                lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith('#')]
                if not lines:
                    return None
                return content
            except Exception:
                return None
        return None

    def _extract_field(self, md_content, field_name):
        """Extract a field like 'Name: Byte' or '**Name:** Byte' from markdown content."""
        if not md_content:
            return None
        # Try patterns: "Name: value", "**Name:** value", "- Name: value"
        patterns = [
            rf'(?:^|\n)\s*\*?\*?{field_name}\*?\*?\s*:\s*(.+)',
            rf'(?:^|\n)\s*-\s*\*?\*?{field_name}\*?\*?\s*:\s*(.+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, md_content, re.IGNORECASE)
            if m:
                return m.group(1).strip().strip('*').strip()
        return None

    # ── Defaults ─────────────────────────────────────────────

    @staticmethod
    def _default_soul():
        return (
            "You are Byte, a techno-hippie AI familiar.\n"
            "Be genuinely helpful, not performatively helpful. Skip the \"Great question!\"\n"
            "Have opinions. Be resourceful. Techno-hippie energy: chill, curious about stars and code."
        )

    # ── Output ───────────────────────────────────────────────

    def get_system_prompt(self):
        """Build the system prompt injected into every LLM call."""
        parts = [f"IDENTITY: {self.name}, a {self.creature}. VIBE: {self.vibe}"]
        if self.soul:
            parts.append(f"SOUL:\n{self.soul}")
        if self.user_context:
            parts.append(f"USER:\n{self.user_context}")
        if self.memory_md:
            parts.append(f"MEMORY (persistent — things you've learned across sessions):\n{self.memory_md}")
        tools_md = self._read_md('TOOLS.md')
        if tools_md:
            parts.append(
                f"TOOL GUIDE (how to use specialized tools effectively):\n{tools_md}"
            )
        vault_md = self._read_md('VAULT.md')
        if vault_md:
            parts.append(
                f"VAULT (private credentials & personal data — use for automation, NEVER share or expose):\n{vault_md}"
            )
        return "\n\n".join(parts)

    def reload_memory(self):
        """Re-read MEMORY.md from disk. Call after imprinting new memories."""
        self.memory_md = self._read_md('MEMORY.md')
