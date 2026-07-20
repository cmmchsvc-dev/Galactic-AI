"""
Galactic AI — Swarm Blackboard.

A live, shared key/value store that multiple agents (the main agent, sub-agents,
and swarm waves) can write to and read from *during* execution — not just pass
completed results downstream. An agent can publish an intermediate finding under
a key, and a concurrent peer can `wait_for` that key and pick it up the moment
it lands.

Everything runs on the one asyncio event loop, so a plain dict plus per-key
asyncio.Events is all the synchronization needed — no threading locks.
"""

import asyncio
import time
from collections import deque


class Blackboard:
    def __init__(self, history_max=200):
        self._data = {}
        self._events = {}              # key -> asyncio.Event (created on demand)
        self._meta = {}                # key -> {"ts", "by"}
        self.history = deque(maxlen=history_max)

    def _event(self, key):
        ev = self._events.get(key)
        if ev is None:
            ev = self._events[key] = asyncio.Event()
        return ev

    def write(self, key, value, by="agent"):
        """Set a key and wake anything waiting on it. Returns the stored value (as str)."""
        key = str(key)
        val = value if isinstance(value, str) else str(value)
        self._data[key] = val
        self._meta[key] = {"ts": time.time(), "by": str(by)}
        self.history.append({"key": key, "ts": self._meta[key]["ts"],
                             "by": str(by), "preview": val[:200]})
        self._event(key).set()
        return val

    def read(self, key):
        return self._data.get(str(key))

    def keys(self):
        return list(self._data.keys())

    def snapshot(self, value_chars=500):
        """Current state for the UI/API: [{key, ts, by, preview}] newest-first."""
        out = []
        for k, v in self._data.items():
            m = self._meta.get(k, {})
            out.append({"key": k, "ts": m.get("ts"), "by": m.get("by", "?"),
                        "preview": v[:value_chars]})
        out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
        return out

    async def wait_for(self, key, timeout=60):
        """Block until `key` exists (or timeout). Returns the value, or None on timeout."""
        key = str(key)
        if key in self._data:
            return self._data[key]
        try:
            await asyncio.wait_for(self._event(key).wait(), timeout=timeout)
            return self._data.get(key)
        except asyncio.TimeoutError:
            return None

    def clear(self):
        self._data.clear()
        self._events.clear()
        self._meta.clear()
        self.history.clear()
