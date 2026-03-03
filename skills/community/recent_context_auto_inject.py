from __future__ import annotations

import json
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from skills.base import GalacticSkill


class RecentContextAutoInjectSkill(GalacticSkill):
    """Auto-inject the last N characters from the hot buffer on the first user turn after boot.

    Reads: <logs>/conversations/hot_buffer.json
    Injects: last N characters (default 7000) into context
    Injects only ONCE per process boot (first gateway.speak call)

    Optional config.yaml:
      conversation:
        auto_inject_recent_chars: 7000
    """

    skill_name = "recent_context_auto_inject"
    version = "1.0.0"
    author = "Chesley + Byte"
    description = "Auto-inject last N characters of recent conversation from hot_buffer.json on boot."
    category = "memory"
    icon = "🧠"

    DEFAULT_CHARS = 7000

    def __init__(self, core):
        super().__init__(core)

        logs_dir = Path((core.config.get("paths", {}) or {}).get("logs", "./logs")).resolve()
        self.conv_dir = logs_dir / "conversations"
        self.hot_path = self.conv_dir / "hot_buffer.json"

        cfg = (core.config.get("conversation", {}) or {})
        self.n_chars = int(cfg.get("auto_inject_recent_chars", self.DEFAULT_CHARS) or self.DEFAULT_CHARS)
        self.n_chars = max(500, min(50_000, self.n_chars))

        self._orig_speak = None
        self._patched = False
        self._injected_once = False

        # Some loader paths may instantiate skills without awaiting on_load.
        self._install_patch()

    async def on_load(self):
        self._install_patch()

    async def on_unload(self):
        gw = getattr(self.core, "gateway", None)
        if gw and self._patched and self._orig_speak:
            try:
                gw.speak = self._orig_speak
            except Exception:
                pass

    def get_tools(self) -> dict:
        return {
            "recent_context_auto_inject_status": {
                "description": "Show whether recent-context auto-injection is installed and its settings.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_status,
            },
        }

    async def tool_status(self, args: dict):
        return {
            "patched_gateway_speak": bool(self._patched),
            "injected_once_this_boot": bool(self._injected_once),
            "hot_buffer_path": str(self.hot_path),
            "auto_inject_recent_chars": self.n_chars,
        }

    # ── Patch ─────────────────────────────────────────────────────────

    def _install_patch(self):
        if self._patched:
            return

        gw = getattr(self.core, "gateway", None)
        if not gw or not hasattr(gw, "speak"):
            return

        self._orig_speak = gw.speak
        orig = self._orig_speak

        async def patched(self_gateway, user_input, context: str = "", chat_id=None, images=None):
            if not self._injected_once:
                try:
                    block = self._build_inject_block()
                    if block:
                        context = (block + "\n\n" + context) if context else block
                except Exception:
                    pass
                finally:
                    self._injected_once = True

            return await orig(user_input, context=context, chat_id=chat_id, images=images)

        try:
            gw.speak = types.MethodType(patched, gw)
            self._patched = True
        except Exception:
            self._patched = False

    # ── Hot buffer → text ─────────────────────────────────────────────

    def _read_hot_messages(self) -> List[Dict[str, Any]]:
        if not self.hot_path.exists():
            return []
        try:
            payload = json.loads(self.hot_path.read_text(encoding="utf-8", errors="replace"))
            msgs = payload.get("messages", [])
            return msgs if isinstance(msgs, list) else []
        except Exception:
            return []

    def _format_messages(self, msgs: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for m in msgs:
            ts = str(m.get("ts", ""))
            role = str(m.get("role", "?")).upper()
            source = str(m.get("source", ""))
            content = str(m.get("content", ""))

            # Masking is OFF (by request). Keep raw content and preserve newlines.
            if source:
                parts.append(f"[{ts}] {role}({source}):\n{content}")
            else:
                parts.append(f"[{ts}] {role}:\n{content}")
            parts.append("")

        return "\n".join(parts).strip()

    def _build_inject_block(self) -> str:
        msgs = self._read_hot_messages()
        if not msgs:
            return ""

        text = self._format_messages(msgs)
        if not text:
            return ""

        if len(text) > self.n_chars:
            text = text[-self.n_chars :]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"# AUTO-INJECTED RECENT CONTEXT (last {self.n_chars} chars) — {now}\n"
            f"# source: {self.hot_path}\n"
            f"---\n"
            f"{text}\n"
            f"---\n"
            f"# END AUTO-INJECTED RECENT CONTEXT"
        )
