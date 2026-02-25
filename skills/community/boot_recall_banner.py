from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from skills.base import GalacticSkill


class BootRecallBannerSkill(GalacticSkill):
    """Show the last N hot-buffer messages immediately after boot.

    Prints a banner to console and writes it to:
      <logs>/conversations/boot_recall_banner.txt

    Reads:
      <logs>/conversations/hot_buffer.json

    Config (optional) in config.yaml:
      conversation:
        boot_recall_messages: 10
    """

    skill_name = "boot_recall_banner"
    version = "1.0.0"
    author = "Chesley + Byte"
    description = "Prints the last N hot-buffer messages on boot (and writes them to a file)."
    category = "memory"
    icon = "🧾"

    DEFAULT_N = 10
    MAX_LINE_CHARS = 350

    def __init__(self, core):
        super().__init__(core)

        logs_dir = Path((core.config.get("paths", {}) or {}).get("logs", "./logs")).resolve()
        self.conv_dir = logs_dir / "conversations"
        self.conv_dir.mkdir(parents=True, exist_ok=True)

        self.hot_path = self.conv_dir / "hot_buffer.json"
        self.out_path = self.conv_dir / "boot_recall_banner.txt"

        cfg = (core.config.get("conversation", {}) or {})
        self.n = int(cfg.get("boot_recall_messages", self.DEFAULT_N) or self.DEFAULT_N)
        self.n = max(1, min(50, self.n))

        # Run even if on_load isn't awaited by a given loader path.
        self._thread = threading.Thread(target=self._run_once, name="boot_recall_banner", daemon=True)
        self._thread.start()

    async def on_load(self):
        return

    def get_tools(self) -> dict:
        return {
            "boot_recall_show": {
                "description": "Return the last N messages from the hot buffer (same content as boot banner).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "How many messages to show."}
                    },
                },
                "fn": self.tool_show,
            }
        }

    def _run_once(self):
        # Small delay so core finishes printing its normal boot lines first.
        time.sleep(1.0)
        try:
            banner = self._format_banner(self._read_hot())
            if not banner.strip():
                return

            print(banner)

            try:
                self.out_path.write_text(banner + "\n", encoding="utf-8")
            except Exception:
                pass
        except Exception:
            return

    def _read_hot(self) -> Dict[str, Any]:
        if not self.hot_path.exists():
            return {"messages": []}
        try:
            return json.loads(self.hot_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {"messages": []}

    def _format_banner(self, hot_payload: Dict[str, Any]) -> str:
        msgs: List[Dict[str, Any]] = hot_payload.get("messages", []) or []
        if not msgs:
            return ""

        recent = msgs[-self.n :]
        lines = []
        for m in recent:
            ts = str(m.get("ts", ""))[:19]
            role = str(m.get("role", "?")).upper()
            source = str(m.get("source", ""))
            content = str(m.get("content", ""))
            content = content.replace("\r", " ").replace("\n", " ").strip()
            if len(content) > self.MAX_LINE_CHARS:
                content = content[: self.MAX_LINE_CHARS] + " …"
            if source:
                lines.append(f"[{ts}] {role}({source}): {content}")
            else:
                lines.append(f"[{ts}] {role}: {content}")

        header = (
            "\n" + "=" * 78
            + f"\nBOOT RECALL (last {len(recent)} messages) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            + f"hot buffer: {self.hot_path}\n"
            + f"written to: {self.out_path}\n"
            + "=" * 78
        )
        return header + "\n" + "\n".join(lines) + "\n" + ("=" * 78)

    async def tool_show(self, args: dict):
        limit = int(args.get("limit", self.n) or self.n)
        limit = max(1, min(200, limit))
        hot = self._read_hot()
        msgs = (hot.get("messages", []) or [])[-limit:]
        return {
            "hot_buffer": str(self.hot_path),
            "limit": limit,
            "message_count_in_hot": len(hot.get("messages", []) or []),
            "messages": msgs,
            "boot_banner_file": str(self.out_path),
        }
