"""
Galactic AI — Memory Capture Agent + Life-Log
=============================================

Event-driven, NOT a background timer. Nothing here runs on a schedule.

1. ON-MENTION MEMORY CAPTURE
   Every time YOU send Byte a message, this quietly checks (cheaply) whether you
   just shared a durable personal fact, preference, relationship, or identity
   detail — and if so, saves it to semantic memory so Byte remembers it later.
   Runs as a fire-and-forget task off the response path, gated by a keyword
   pre-filter so most messages cost nothing, and de-duped so the same fact is
   never saved twice. If a message is just chit-chat, nothing is saved.

2. LIFE-LOG (on demand only)
   `write_lifelog_now` distills recent activity into a dated LIFELOG.md entry;
   `recall_lifelog` answers "what did I work on this week?". Neither runs
   automatically — they only fire when you (or Byte, via the tools) ask.

Design rules: grounded (never invents facts), isolated (all model calls go
through gateway.speak_isolated so they can't corrupt the live session), and
crash-proof (capture failures log and are swallowed — they never affect chat).
"""

import asyncio
import os
import time
from datetime import datetime


class AmbientAgent:
    KNOWN_PROVIDERS = {"openrouter", "ollama", "nvidia", "groq", "mistral",
                       "anthropic", "google", "openai", "deepseek", "xai"}

    # Cheap keyword pre-filter: only messages that look personal reach the model.
    PERSONAL_MARKERS = (
        "remember", "my name", "call me", "i'm ", "i am ", "my ",
        "i like", "i love", "i hate", "i prefer", "favorite", "favourite",
        "i live", "i work", "i own", "i drive", "i have", "i've ", "i use",
        "birthday", "note that", "for future reference", "don't forget",
    )

    def __init__(self, core):
        self.core = core
        self.gw = core.gateway
        amb = (core.config.get('ambient', {}) or {})
        self.enabled = amb.get('enabled', True)
        self.capture_personal = amb.get('capture_personal', True)
        self._tools_registered = False
        self.register()

    # ── model resolution ─────────────────────────────────────────────

    def _cheap_model(self):
        m = self.core.config.get('models', {}) or {}
        target = (m.get('summarizer_model') or m.get('planner_fallback_model'))
        prov = (m.get('summarizer_provider') or m.get('planner_fallback_provider'))
        if not target:
            return None, None
        t = str(target).strip()
        if "/" in t and t.split("/", 1)[0].lower() in self.KNOWN_PROVIDERS:
            return t.split("/", 1)
        return prov, t

    async def _ask(self, prompt, context, session_id, timeout=90):
        prov, model = self._cheap_model()
        try:
            return await asyncio.wait_for(
                self.gw.speak_isolated(
                    prompt, context=context,
                    override_provider=prov, override_model=model,
                    use_lock=True, skip_planning=True, session_id=session_id,
                    # Every job in this file is "read text, return one sentence".
                    # The prompts already say "do NOT call any tools", but that's
                    # advice, not enforcement: on 2026-07-26 this agent called
                    # chrome_navigate / chrome_read_page / chrome_type while the
                    # MAIN agent was filling a form in the same browser, and the
                    # two fought over the page. Declaring nothing makes it
                    # impossible rather than merely discouraged.
                    no_tools=True,
                    # No persona either — a fact extractor doesn't need one, and
                    # it keeps the isolated prompt small and cheap.
                    plain_persona=True,
                ),
                timeout=timeout,
            )
        except Exception as e:
            await self.core.log(f"[Capture] model call failed: {e}", priority=3)
            return ""

    def _workspace(self):
        return self.core.config.get('paths', {}).get('workspace', '.') or '.'

    # ── ON-MENTION memory capture (event-driven) ─────────────────────

    async def capture_from_message(self, user_text):
        """Called once per user message. Saves a durable personal fact IF the
        message contains one; otherwise does nothing. Safe to fire-and-forget."""
        if not (self.enabled and self.capture_personal):
            return
        text = (user_text or "").strip()
        if len(text) < 4 or len(text) > 4000:
            return
        low = text.lower()
        if not any(mark in low for mark in self.PERSONAL_MARKERS):
            return  # no personal signal → zero cost, no model call

        prompt = (
            "Extract any DURABLE personal fact, preference, relationship, or identity detail the user just "
            "shared that is worth remembering long-term. Return it as ONE concise third-person statement "
            "(e.g. \"User's name is Chong.\" or \"User drives a 1966 F100 with a 352 FE engine.\"). "
            "Capture only lasting facts — names, preferences, people/pets, possessions, habits, goals. "
            "If the message is just chit-chat with nothing durable to remember, reply with exactly: NONE\n\n"
            f"USER MESSAGE:\n{text}"
        )
        fact = str(await self._ask(
            prompt,
            context="You extract durable personal facts. Reply with plain text only — do NOT call any tools.",
            session_id="ambient", timeout=60)).strip()

        if not fact or fact.upper().startswith("NONE") or fact.startswith("[ERROR]") or len(fact) < 6:
            return
        fact = fact.strip().strip('"').strip()

        # De-dupe: skip if we already have a near-identical personal memory.
        try:
            if self.core.memory:
                hits = await self.core.memory.query_memory(fact, n_results=1, category="personal")
                if hits and (hits[0].get("distance") or 1.0) < 0.08:
                    return
        except Exception:
            pass

        try:
            if self.core.memory:
                await self.core.memory.save_memory(
                    fact, category="personal",
                    metadata={"captured": datetime.now().isoformat(), "source": "on_mention"},
                    silent=True)
                await self.core.log(f"🧠 Remembered: {fact}", priority=2)
                try:
                    await self.core.relay.emit(2, "memory_captured", {"text": fact})
                except Exception:
                    pass
        except Exception as e:
            await self.core.log(f"[Capture] save failed: {e}", priority=3)

    # ── LIFE-LOG (on demand only) ────────────────────────────────────

    def _read_recent_chat(self, since_seconds=86400, cap=60):
        import json
        hf = getattr(self.gw, 'history_file', None)
        if not hf or not os.path.exists(hf):
            return []
        cutoff = time.time() - since_seconds
        out = []
        try:
            with open(hf, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    ts = e.get("ts")
                    keep = True
                    if isinstance(ts, str):
                        try:
                            keep = datetime.fromisoformat(ts).timestamp() >= cutoff
                        except Exception:
                            keep = True
                    if keep and e.get("content"):
                        out.append(f"[{e.get('role', '?')}] {str(e.get('content'))[:400]}")
        except Exception:
            return []
        return out[-cap:]

    async def generate_lifelog(self, force=False):
        turns = self._read_recent_chat()
        if not turns and not force:
            return None
        body = "CONVERSATIONS (last 24h):\n" + ("\n".join(turns) or "(none)")
        prompt = (
            "Write a short first-person journal entry (Byte's voice, 3-6 sentences) summarizing what the user "
            "and Byte worked on and figured out recently. Be specific and factual — concrete tasks, files, "
            "decisions, and any unfinished threads worth resuming. No fluff, no headers.\n\n" + body[:12000]
        )
        entry = str(await self._ask(
            prompt,
            context="You are Byte writing a work journal. Reply with plain text only — do NOT call any tools.",
            session_id="s-lifelog", timeout=150)).strip()
        if not entry or entry.startswith("[ERROR]"):
            return None

        stamp = datetime.now().strftime("%Y-%m-%d %A")
        try:
            path = os.path.join(self._workspace(), "LIFELOG.md")
            header = "" if os.path.exists(path) else "# Galactic Life-Log\n_Journal — written on demand._\n"
            with open(path, "a", encoding="utf-8") as f:
                if header:
                    f.write(header)
                f.write(f"\n## {stamp}\n\n{entry}\n")
        except Exception as e:
            await self.core.log(f"[Life-Log] write failed: {e}", priority=2)
        try:
            if self.core.memory:
                await self.core.memory.save_memory(
                    f"Life-log for {stamp}:\n{entry}",
                    category="life_log", metadata={"date": stamp}, silent=True)
        except Exception:
            pass
        await self.core.log(f"📓 Life-Log written for {stamp}.", priority=2)
        return entry

    async def recall_lifelog(self, query="", days=7):
        try:
            if not self.core.memory:
                return "Memory system unavailable."
            if query:
                hits = await self.core.memory.query_memory(query, n_results=8, category="life_log")
                if hits:
                    return "\n\n".join(h["content"] for h in hits)
            path = os.path.join(self._workspace(), "LIFELOG.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    txt = f.read()
                blocks = txt.split("\n## ")
                if len(blocks) > 1:
                    tail = blocks[-days:]
                    return "## " + "\n## ".join(b.strip() for b in tail if b.strip())
                return txt.strip()
            return "No life-log entries yet."
        except Exception as e:
            return f"[ERROR] recall_lifelog: {e}"

    # ── gateway tools (usable from CLI + deck chat) ──────────────────

    def register(self):
        if self._tools_registered:
            return
        tools = {
            "recall_lifelog": {
                "description": "Recall the user's life-log / work journal and captured personal facts. Use to "
                               "answer 'what did I work on this week?' or 'what do you know about me?'. Optional "
                               "'query' does a semantic search over past entries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Optional topic to search the journal for."},
                        "days": {"type": "integer", "description": "How many recent entries to return (default 7)."},
                    },
                },
                "fn": self._tool_recall_lifelog,
            },
            "write_lifelog_now": {
                "description": "Generate a life-log journal entry right now from recent activity.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_write_lifelog,
            },
        }
        try:
            self.gw.tools.update(tools)
            self._tools_registered = True
        except Exception:
            pass

    async def _tool_recall_lifelog(self, args):
        return await self.recall_lifelog(
            query=str(args.get("query", "")).strip(),
            days=int(args.get("days") or 7),
        )

    async def _tool_write_lifelog(self, args):
        entry = await self.generate_lifelog(force=True)
        return f"📓 Life-log written:\n\n{entry}" if entry else "Nothing to log yet."
