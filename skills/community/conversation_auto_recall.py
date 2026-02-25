from __future__ import annotations

import asyncio
import json
import re
import types
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skills.base import GalacticSkill


_STOPWORDS = {
    "a","an","and","are","as","at","be","but","by","for","from","has","have","he","her","his","i",
    "if","in","into","is","it","its","me","my","no","not","of","on","or","our","she","so","that",
    "the","their","them","then","there","these","they","this","to","was","we","were","what","when","where",
    "which","who","why","will","with","you","your","yours","im","ive","id","dont","cant","wont","does","did",
}


@dataclass
class _Match:
    ts: str
    role: str
    source: str
    content: str
    path: str
    score: int


class ConversationAutoRecallSkill(GalacticSkill):
    """Automatic conversation recall.

    Hooks GalacticGateway.speak() so when the user asks "remember"-type questions,
    we search the archived conversation store under logs/conversations and inject
    the most relevant snippets into `context` BEFORE the LLM call.

    No core file edits; patch is runtime-only.
    """

    skill_name = "conversation_auto_recall"
    version = "1.0.0"
    author = "Chesley + Byte"
    description = "Auto-recalls relevant snippets from archived conversations and injects them into context."
    category = "memory"
    icon = "🧠"

    # Tuneables
    max_snippets = 10
    max_files_scan = 60          # newest archive session files to scan when needed
    max_keywords = 10
    min_keyword_len = 4

    def __init__(self, core):
        super().__init__(core)

        logs_dir = (core.config.get("paths", {}) or {}).get("logs", "./logs")
        self.base_dir = (Path(logs_dir).resolve() / "conversations")
        self.hot_path = self.base_dir / "hot_buffer.json"
        self.session_info_path = self.base_dir / "current_session.json"

        self._orig_speak = None
        self._patched = False

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
            "conversation_auto_recall_status": {
                "description": "Show whether auto-recall is installed and what files it uses.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_status,
            },
        }

    async def tool_status(self, args: dict):
        current = self._get_current_session_file()
        return {
            "patched_gateway_speak": bool(self._patched),
            "conversations_dir": str(self.base_dir),
            "hot_buffer": str(self.hot_path),
            "current_session_file": str(current) if current else None,
            "max_snippets": self.max_snippets,
            "max_files_scan": self.max_files_scan,
        }

    # ── Patch ─────────────────────────────────────────────────────────

    def _install_patch(self):
        gw = getattr(self.core, "gateway", None)
        if not gw or not hasattr(gw, "speak"):
            return

        self._orig_speak = gw.speak
        orig = self._orig_speak

        async def patched(self_gateway, user_input, context="", chat_id=None, images=None):
            try:
                if isinstance(user_input, str) and self._should_recall(user_input):
                    recall_block = await self._build_recall_block(user_input)
                    if recall_block:
                        if context:
                            context = context + "\n\n" + recall_block
                        else:
                            context = recall_block
            except Exception:
                # Never let recall break the chat.
                pass

            return await orig(user_input, context=context, chat_id=chat_id, images=images)

        try:
            gw.speak = types.MethodType(patched, gw)
            self._patched = True
        except Exception:
            self._patched = False

    # ── Recall logic ──────────────────────────────────────────────────

    def _should_recall(self, text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False

        # Strong triggers
        triggers = [
            "remember", "recall", "last time", "previous session", "earlier", "before", "yesterday",
            "what did i say", "what did you say", "you said", "i said", "we talked", "we discussed",
            "what was that", "what was the error", "what error", "where did", "when did",
        ]
        if any(x in t for x in triggers):
            return True

        # If user explicitly references a past artifact/error string
        if "bodypartreader" in t or "takes 1 positional argument" in t:
            return True

        # "Do you remember ..." patterns
        if t.startswith("do you remember") or t.startswith("can you remember"):
            return True

        # Otherwise keep it off to avoid needless scans
        return False

    def _extract_keywords(self, text: str) -> List[str]:
        # Keep words, numbers, some symbols inside tokens
        words = re.findall(r"[a-zA-Z0-9_\-]{%d,}" % self.min_keyword_len, (text or "").lower())
        words = [w for w in words if w not in _STOPWORDS]
        if not words:
            return []

        # Prefer rarer/longer-ish terms: count then sort by (freq desc, len desc)
        c = Counter(words)
        ranked = sorted(c.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
        out = []
        for w, _ in ranked:
            if w not in out:
                out.append(w)
            if len(out) >= self.max_keywords:
                break
        return out

    def _load_hot_messages(self) -> List[Dict[str, Any]]:
        try:
            if self.hot_path.exists():
                data = json.loads(self.hot_path.read_text(encoding="utf-8", errors="replace"))
                msgs = data.get("messages", [])
                if isinstance(msgs, list):
                    return msgs
        except Exception:
            pass
        return []

    def _get_current_session_file(self) -> Optional[Path]:
        try:
            if self.session_info_path.exists():
                data = json.loads(self.session_info_path.read_text(encoding="utf-8", errors="replace"))
                sf = data.get("session_file")
                if sf:
                    p = Path(sf)
                    if p.exists():
                        return p
        except Exception:
            pass
        # Fallback: newest session_*.jsonl
        try:
            files = list(self.base_dir.glob("*/*session_*.jsonl"))
            if not files:
                return None
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return files[0]
        except Exception:
            return None

    def _iter_archive_files(self, include_current: bool = False) -> List[Path]:
        try:
            files = list(self.base_dir.glob("*/*session_*.jsonl"))
            if not files:
                return []
            current = self._get_current_session_file()
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            out = []
            for fp in files:
                if not include_current and current and fp.resolve() == current.resolve():
                    continue
                out.append(fp)
                if len(out) >= self.max_files_scan:
                    break
            return out
        except Exception:
            return []

    def _score_content(self, content_lower: str, keywords: List[str]) -> int:
        score = 0
        for kw in keywords:
            if kw in content_lower:
                score += 1
        return score

    def _snip(self, text: str, keywords: List[str], width: int = 220) -> str:
        if not text:
            return ""
        tl = text.lower()
        # Pick first keyword hit position
        idx = None
        for kw in keywords:
            pos = tl.find(kw)
            if pos != -1:
                idx = pos
                break
        if idx is None:
            return text[:width] + ("..." if len(text) > width else "")
        start = max(0, idx - (width // 2))
        end = min(len(text), start + width)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

    async def _build_recall_block(self, user_input: str) -> str:
        # Build keyword set. Also include a couple “special” tokens if present.
        keywords = self._extract_keywords(user_input)
        # Keep a couple obvious special patterns
        if "bodypartreader" in user_input.lower() and "bodypartreader" not in keywords:
            keywords.insert(0, "bodypartreader")
        if not keywords:
            return ""

        # Decide scan depth
        t = user_input.lower()
        deep = any(x in t for x in ["previous session", "last session", "last time", "earlier", "before", "yesterday"]) 

        matches: List[_Match] = []

        # 1) Hot buffer (fast)
        for e in reversed(self._load_hot_messages()):
            content = str(e.get("content", ""))
            cl = content.lower()
            score = self._score_content(cl, keywords)
            if score <= 0:
                continue
            matches.append(_Match(
                ts=str(e.get("ts", "")),
                role=str(e.get("role", "")),
                source=str(e.get("source", "")),
                content=content,
                path=str(self.hot_path),
                score=score,
            ))
            if len(matches) >= self.max_snippets * 2:
                break

        # 2) Current session file
        session_fp = self._get_current_session_file()
        if session_fp and session_fp.exists():
            try:
                # Keep last matching snippets by scanning forward and using bounded list
                tmp: List[_Match] = []
                with open(session_fp, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            e = json.loads(line)
                        except Exception:
                            continue
                        content = str(e.get("content", ""))
                        cl = content.lower()
                        score = self._score_content(cl, keywords)
                        if score <= 0:
                            continue
                        tmp.append(_Match(
                            ts=str(e.get("ts", "")),
                            role=str(e.get("role", "")),
                            source=str(e.get("source", "")),
                            content=content,
                            path=str(session_fp),
                            score=score,
                        ))
                        if len(tmp) > (self.max_snippets * 3):
                            tmp = tmp[-(self.max_snippets * 3):]
                matches.extend(tmp)
            except Exception:
                pass

        # 3) Archives (only if deep OR we found very little so far)
        if deep or len(matches) < max(2, self.max_snippets // 3):
            for fp in self._iter_archive_files(include_current=False):
                try:
                    tmp: List[_Match] = []
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            try:
                                e = json.loads(line)
                            except Exception:
                                continue
                            content = str(e.get("content", ""))
                            cl = content.lower()
                            score = self._score_content(cl, keywords)
                            if score <= 0:
                                continue
                            tmp.append(_Match(
                                ts=str(e.get("ts", "")),
                                role=str(e.get("role", "")),
                                source=str(e.get("source", "")),
                                content=content,
                                path=str(fp),
                                score=score,
                            ))
                            if len(tmp) > (self.max_snippets * 2):
                                tmp = tmp[-(self.max_snippets * 2):]
                    if tmp:
                        matches.extend(tmp)
                    if len(matches) >= self.max_snippets * 4:
                        break
                except Exception:
                    continue

        if not matches:
            return ""

        # Rank: higher score first, then newest timestamp-ish
        # (ts is ISO string, so lexical sort works)
        matches.sort(key=lambda m: (m.score, m.ts), reverse=True)

        # De-dupe by (role, content)
        seen = set()
        final: List[_Match] = []
        for m in matches:
            sig = (m.role, m.content)
            if sig in seen:
                continue
            seen.add(sig)
            final.append(m)
            if len(final) >= self.max_snippets:
                break

        # Build a compact recall block injected into the model's system context.
        lines = []
        lines.append("# Conversation Recall (auto)")
        lines.append(f"User asked: {user_input}")
        lines.append("Use the snippets below as factual prior-session context. If unsure, say so.")
        lines.append("")

        for i, m in enumerate(final, 1):
            snippet = self._snip(m.content, keywords)
            # Keep path minimal: just filename (privacy + prompt size)
            try:
                pshort = Path(m.path).name
            except Exception:
                pshort = m.path
            lines.append(f"[{i}] {m.ts} | {m.role} | {m.source} | score={m.score} | {pshort}")
            lines.append(f"    {snippet}")

        return "\n".join(lines)
