"""
Galactic AI - Ollama Manager
Provides robust, stable local model support:
- Health checking with caching
- Auto-discovery of all installed models
- Context-window awareness per model
- Auto-reconnect and background polling
- Remote/custom-port Ollama instance support (reads baseUrl from config)
"""

import asyncio
import json
import logging
import time
import httpx

logger = logging.getLogger("OllamaManager")


class OllamaManager:
    """
    Manages all Ollama lifecycle concerns: health, discovery, context-window tracking.
    Designed to be fully non-blocking — a failed Ollama instance never stalls the core.
    """

    HEALTH_CACHE_SECONDS = 30      # Don't hammer /api/version on every LLM call
    DISCOVERY_INTERVAL_SECONDS = 60  # Re-scan for newly pulled models

    def __init__(self, core):
        self.core = core

        # Build base URL from config (strip /v1 if present to get the raw Ollama host)
        raw = core.config.get('providers', {}).get('ollama', {}).get('baseUrl', 'http://127.0.0.1:11434/v1')
        self.base_url = raw.rstrip('/').removesuffix('/v1')   # e.g. "http://127.0.0.1:11434"
        self.openai_url = self.base_url + '/v1'               # for OpenAI-compat endpoint

        self.discovered_models: list[str] = []
        self.model_context_windows: dict[str, int] = {}
        self.is_healthy: bool = False
        self._last_health_check: float = 0.0
        self._cached_health: bool = False
        self._last_model_set: set[str] = set()  # Track changes — only log when models change

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """
        Returns True if Ollama is reachable at the configured base URL.
        Result is cached for HEALTH_CACHE_SECONDS to avoid per-call overhead.
        """
        now = time.monotonic()
        if now - self._last_health_check < self.HEALTH_CACHE_SECONDS:
            return self._cached_health

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/version")
                healthy = resp.status_code == 200
        except Exception:
            healthy = False

        self._cached_health = healthy
        self._last_health_check = now

        if healthy != self.is_healthy:
            self.is_healthy = healthy
            status_word = "ONLINE" if healthy else "OFFLINE"
            await self.core.log(f"🤖 Ollama {status_word} at {self.base_url}", priority=2)

            # Broadcast health change to web UI
            await self.core.relay.emit(2, "ollama_status", {
                "healthy": healthy,
                "base_url": self.base_url,
                "models": self.discovered_models,
            })

        return healthy

    async def discover_models(self) -> list[str]:
        """
        Queries /api/tags to get all locally installed Ollama models.
        Also fetches context-window size for each model via /api/show.
        Broadcasts the list to the web UI and imprints it into memory.
        """
        if not await self.health_check():
            return self.discovered_models  # return cached list, don't wipe it

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                data = resp.json()

            models = [m['name'] for m in data.get('models', [])]
            self.discovered_models = models

            # Only log to terminal when models actually change (added/removed)
            current_set = set(models)
            if current_set != self._last_model_set:
                added = current_set - self._last_model_set
                removed = self._last_model_set - current_set
                if not self._last_model_set:
                    # First discovery — print once
                    await self.core.log(
                        f"🤖 Ollama: {len(models)} model(s) found — {', '.join(models) or 'none'}",
                        priority=2
                    )
                else:
                    # Models changed — report the diff
                    parts = []
                    if added:
                        parts.append(f"+{', '.join(added)}")
                    if removed:
                        parts.append(f"-{', '.join(removed)}")
                    await self.core.log(
                        f"🤖 Ollama models changed ({len(models)} total): {' | '.join(parts)}",
                        priority=2
                    )
                self._last_model_set = current_set

                # Only imprint into memory when models change
                if hasattr(self.core, 'memory') and models:
                    content = f"Ollama local models available: {', '.join(models)}"
                    try:
                        await self.core.memory.imprint(content, tags="ollama,models,local")
                    except Exception:
                        pass  # memory imprint is best-effort

            # Fetch context windows in parallel (fire-and-forget, best-effort)
            asyncio.create_task(self._fetch_context_windows(models))

            # Always broadcast to web UI so the model grid stays fresh
            await self.core.relay.emit(2, "ollama_models", models)

            return models

        except Exception as e:
            logger.warning(f"Ollama model discovery failed: {e}")
            return self.discovered_models

    async def auto_discover_loop(self):
        """
        Background task: polls Ollama every DISCOVERY_INTERVAL_SECONDS.
        Started by galactic_core_v2.py via asyncio.create_task().
        """
        while True:
            try:
                await self.discover_models()
            except Exception as e:
                logger.debug(f"OllamaManager loop error: {e}")
            await asyncio.sleep(self.DISCOVERY_INTERVAL_SECONDS)

    def get_openai_base_url(self) -> str:
        """Return the /v1-suffixed URL for use by the OpenAI-compat gateway call."""
        return self.openai_url

    def get_context_window(self, model_name: str, default: int = 32768) -> int:
        """Return the context window size for a model, or a safe default."""
        return self.model_context_windows.get(model_name, default)

    def get_status(self) -> dict:
        """Return a status dict for the /status endpoint and Telegram /status command."""
        return {
            "healthy": self.is_healthy,
            "base_url": self.base_url,
            "models": self.discovered_models,
            "model_count": len(self.discovered_models),
            "context_windows": self.model_context_windows,
        }

    # ─────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────

    async def _fetch_context_windows(self, models: list[str]):
        """
        Best-effort: for each model call POST /api/show to extract context_length
        from the modelinfo blob.  Results stored in self.model_context_windows.
        """
        for model_name in models:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/show",
                        json={"name": model_name}
                    )
                    data = resp.json()
                    # Ollama returns nested modelinfo with arch-specific keys
                    model_info = data.get('model_info', {})
                    ctx = (
                        model_info.get('llama.context_length')
                        or model_info.get('context_length')
                        or data.get('parameters', {}).get('num_ctx')
                    )
                    if ctx:
                        self.model_context_windows[model_name] = int(ctx)
            except Exception:
                pass  # best-effort
