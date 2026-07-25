"""
Galactic AI - LM Studio Manager

Local model support for LM Studio, mirroring OllamaManager so the two backends
are interchangeable. LM Studio exposes an OpenAI-compatible server (default
http://localhost:1234/v1), so:
  - health + discovery use the standard /v1/models endpoint (no /api/tags)
  - context windows + load-state come from LM Studio's richer /api/v0/models
    endpoint when available (best-effort; older builds just get a default)

Fully non-blocking — a down LM Studio server never stalls the core.
"""

import asyncio
import logging
import time
import httpx

logger = logging.getLogger("LMStudioManager")


class LMStudioManager:
    HEALTH_CACHE_SECONDS = 30
    DISCOVERY_INTERVAL_SECONDS = 60

    def __init__(self, core):
        self.core = core
        raw = core.config.get('providers', {}).get('lmstudio', {}).get('baseUrl', 'http://localhost:1234/v1')
        # Normalize to the /v1 OpenAI-compatible base.
        base = raw.rstrip('/')
        if not base.endswith('/v1'):
            base = base + '/v1'
        self.openai_url = base                       # e.g. http://localhost:1234/v1
        self.base_url = base.removesuffix('/v1')     # e.g. http://localhost:1234

        self.discovered_models: list[str] = []
        self.model_context_windows: dict[str, int] = {}
        self.loaded_models: list[str] = []           # models currently loaded in VRAM
        self.is_healthy: bool = False
        self._last_health_check: float = 0.0
        self._cached_health: bool = False
        self._last_model_set: set[str] = set()
        self._meta_covered: set[str] = set()    # ids the last /api/v0/models call reported
        # asyncio only holds WEAK references to tasks — an un-retained
        # create_task() can be garbage-collected mid-flight. That matters here:
        # model_context_windows is a HARD CAP downstream, so a dropped task
        # silently degrades every request to the 8192 default.
        self._bg_tasks: set = set()

    def _track(self, task):
        """Retain a fire-and-forget task so the GC can't drop it mid-flight."""
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    # ── Public API (matches OllamaManager) ───────────────────────────────────

    async def health_check(self) -> bool:
        now = time.monotonic()
        if now - self._last_health_check < self.HEALTH_CACHE_SECONDS:
            return self._cached_health
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.openai_url}/models")
                healthy = resp.status_code == 200
        except Exception:
            healthy = False

        self._cached_health = healthy
        self._last_health_check = now

        if healthy != self.is_healthy:
            self.is_healthy = healthy
            await self.core.log(
                f"🖥️ LM Studio {'ONLINE' if healthy else 'OFFLINE'} at {self.base_url}", priority=2)
            await self.core.relay.emit(2, "lmstudio_status", {
                "healthy": healthy, "base_url": self.base_url, "models": self.discovered_models,
            })
        return healthy

    async def discover_models(self) -> list[str]:
        if not await self.health_check():
            return self.discovered_models  # keep the cached list; don't wipe it
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.openai_url}/models")
                data = resp.json()
            # OpenAI list format: {"data": [{"id": "..."}], "object": "list"}
            models = [m.get('id') for m in data.get('data', []) if m.get('id')]
            # Embedding-only models can't chat — keep them out of the model picker
            models = [m for m in models if 'embed' not in m.lower()]
            self.discovered_models = models

            current_set = set(models)
            if current_set != self._last_model_set:
                if not self._last_model_set:
                    await self.core.log(
                        f"🖥️ LM Studio: {len(models)} model(s) found — {', '.join(models) or 'none'}",
                        priority=2)
                else:
                    added = current_set - self._last_model_set
                    removed = self._last_model_set - current_set
                    parts = []
                    if added:   parts.append(f"+{', '.join(added)}")
                    if removed: parts.append(f"-{', '.join(removed)}")
                    await self.core.log(f"🖥️ LM Studio models changed: {' | '.join(parts)}", priority=2)
                self._last_model_set = current_set

            # Best-effort richer metadata (context window + load state).
            # Fired only when the model set actually changed, or when a model
            # is still missing from the last successful metadata sweep — this
            # used to re-run every 60s cycle, forever, for data that barely
            # moves. The task is retained (see _track) because a dropped one
            # leaves model_context_windows empty and the hard cap at 8192.
            if not current_set.issubset(self._meta_covered):
                self._track(asyncio.create_task(self._fetch_rich_metadata()))

            await self.core.relay.emit(2, "lmstudio_models", models)
            return models
        except Exception as e:
            logger.warning(f"LM Studio model discovery failed: {e}")
            return self.discovered_models

    async def auto_discover_loop(self):
        while True:
            try:
                await self.discover_models()
            except Exception as e:
                logger.debug(f"LMStudioManager loop error: {e}")
            await asyncio.sleep(self.DISCOVERY_INTERVAL_SECONDS)

    def get_openai_base_url(self) -> str:
        return self.openai_url

    def get_context_window(self, model_name: str, default: int = 8192) -> int:
        return self.model_context_windows.get(model_name, default)

    def get_status(self) -> dict:
        return {
            "healthy": self.is_healthy,
            "base_url": self.base_url,
            "models": self.discovered_models,
            "loaded_models": self.loaded_models,
            "model_count": len(self.discovered_models),
            "context_windows": self.model_context_windows,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _fetch_rich_metadata(self):
        """LM Studio's own REST API (/api/v0/models) exposes max_context_length and
        load state. Best-effort — silently skipped on builds that don't have it.

        Records every id the endpoint reported in self._meta_covered so
        discover_models() knows this sweep is done and stops re-firing it. A
        network error leaves _meta_covered untouched, so the next discovery
        cycle retries; a clean non-200 (build without the endpoint) marks the
        known models covered so we don't poll a 404 forever.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/v0/models")
                if resp.status_code != 200:
                    self._meta_covered = set(self.discovered_models)
                    return
                data = resp.json()
            self._meta_covered = {m.get('id') for m in data.get('data', []) if m.get('id')}
            loaded = []
            for m in data.get('data', []):
                mid = m.get('id')
                if not mid:
                    continue
                if m.get('type') in ('embeddings', 'embedding'):
                    # Typed embedding model the name-based filter missed — prune it
                    if mid in self.discovered_models:
                        self.discovered_models.remove(mid)
                    continue
                # loaded_context_length is what the server will actually accept
                # right now; max_context_length is only the architectural max.
                ctx = m.get('loaded_context_length') or m.get('max_context_length')
                if ctx:
                    self.model_context_windows[mid] = int(ctx)
                if m.get('state') == 'loaded':
                    loaded.append(mid)
            self.loaded_models = loaded
        except Exception:
            pass  # best-effort
