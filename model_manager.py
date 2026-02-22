"""
Galactic AI - Model Manager
Handles primary/fallback model configuration, automatic switching on errors,
and intelligent multi-level fallback chain with per-provider health tracking.
"""

import asyncio
import yaml
import os
import re
from datetime import datetime, timedelta

# ── Error type constants ──────────────────────────────────────────────
ERROR_RATE_LIMIT = "RATE_LIMIT"       # 429, quota exceeded
ERROR_SERVER     = "SERVER_ERROR"      # 500, 502, 503, overloaded
ERROR_TIMEOUT    = "TIMEOUT"           # timed out, TimeoutException
ERROR_AUTH       = "AUTH_ERROR"        # 401, 403, unauthorized, invalid key
ERROR_QUOTA      = "QUOTA_EXHAUSTED"   # 402, payment required, billing
ERROR_NETWORK    = "NETWORK"           # connection refused, DNS, SSL
ERROR_EMPTY      = "EMPTY_RESPONSE"    # empty response, no content
ERROR_UNKNOWN    = "UNKNOWN"

TRANSIENT_ERRORS = {ERROR_RATE_LIMIT, ERROR_SERVER, ERROR_TIMEOUT, ERROR_NETWORK, ERROR_EMPTY}
PERMANENT_ERRORS = {ERROR_AUTH, ERROR_QUOTA}

# ── Provider capability tiers (lower = more capable, try first) ──────
# Format: provider -> (tier, default_model)
PROVIDER_TIERS = {
    'anthropic':   (1, 'claude-sonnet-4-20250514'),
    'google':      (1, 'gemini-2.5-flash'),
    'openai':      (1, 'gpt-4o'),
    'xai':         (2, 'grok-3'),
    'groq':        (2, 'llama-4-scout-17b-16e-instruct'),
    'nvidia':      (2, 'meta/llama-3.1-405b-instruct'),
    'mistral':     (2, 'mistral-large-latest'),
    'deepseek':    (2, 'deepseek-chat'),
    'cerebras':    (3, 'llama3.1-70b'),
    'openrouter':  (3, 'anthropic/claude-sonnet-4'),
    'huggingface': (3, 'Qwen/Qwen3-235B-A22B'),
    'kimi':        (3, 'moonshotai/kimi-k2.5'),
    'zai':         (3, 'z-ai/glm5'),
    'minimax':     (3, 'minimaxai/minimax-m2.1'),
    'ollama':      (9, None),   # Local fallback — always last resort
}

# Default cooldown durations (seconds) per error type
DEFAULT_COOLDOWNS = {
    ERROR_RATE_LIMIT: 60,
    ERROR_SERVER:     30,
    ERROR_TIMEOUT:    10,
    ERROR_AUTH:       86400,
    ERROR_QUOTA:      3600,
    ERROR_NETWORK:    15,
    ERROR_EMPTY:      5,
    ERROR_UNKNOWN:    10,
}


class ModelManager:
    """
    Manages model selection with primary/fallback system.
    Automatically switches to fallback on API errors.
    Provides an intelligent multi-level fallback chain.
    """

    def __init__(self, core):
        self.core = core
        self.config_path = core.config_path

        # Load model config
        model_config = core.config.get('models', {})

        self.primary_provider = model_config.get('primary_provider', 'google')
        self.primary_model = model_config.get('primary_model', 'gemini-2.5-flash')

        self.fallback_provider = model_config.get('fallback_provider', 'ollama')
        self.fallback_model = model_config.get('fallback_model', 'qwen3:8b')

        self.current_mode = 'primary'  # 'primary' or 'fallback'
        self.error_count = 0
        self.last_error_time = None

        # Auto-fallback settings
        self.auto_fallback_enabled = model_config.get('auto_fallback', True)
        self.error_threshold = model_config.get('error_threshold', 3)
        self.recovery_time = model_config.get('recovery_time_seconds', 300)

        # ── Resilient fallback chain ──────────────────────────────────
        self._provider_health = {}     # {provider: {failures, last_failure, cooldown_until}}
        self._fallback_lock = asyncio.Lock()
        self._last_successful_fallback = None  # (provider, model, timestamp)
        self.cooldown_config = model_config.get('fallback_cooldowns', {})
        self.fallback_chain = self._load_fallback_chain(model_config)

        # ── Smart routing state (restored after each speak() call) ──
        self._routed = False           # True if auto_route() switched the model
        self._pre_route_state = None   # {'provider', 'model', 'api_key'} before routing

    # ─────────────────────────────────────────────────────────────────
    # Error Classification
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def classify_error(error_msg: str) -> str:
        """Classify an [ERROR] string into an error type constant."""
        low = error_msg.lower()

        # Rate limit / quota (429)
        if any(k in low for k in ("429", "rate_limit", "rate limit", "quota exceeded",
                                   "resource_exhausted", "too many requests")):
            return ERROR_RATE_LIMIT

        # Server errors (500/502/503)
        if any(k in low for k in ("500", "502", "503", "server error", "service unavailable",
                                   "overloaded", "internal error", "bad gateway")):
            return ERROR_SERVER

        # Timeouts
        if any(k in low for k in ("timed out", "timeout", "timeoutexception", "readtimeout",
                                   "connecttimeout")):
            return ERROR_TIMEOUT

        # Auth errors (401/403)
        if any(k in low for k in ("401", "403", "unauthorized", "forbidden", "invalid_api_key",
                                   "invalid api key", "authentication")):
            return ERROR_AUTH

        # Quota / billing (402)
        if any(k in low for k in ("402", "payment required", "billing", "insufficient",
                                   "credit", "exceeded your")):
            return ERROR_QUOTA

        # Network errors
        if any(k in low for k in ("connection", "refused", "dns", "ssl", "network",
                                   "unreachable", "reset by peer")):
            return ERROR_NETWORK

        # Empty response
        if any(k in low for k in ("empty response", "no content", "empty reply",
                                   "empty result", "no candidates", "generated no")):
            return ERROR_EMPTY

        return ERROR_UNKNOWN

    # ─────────────────────────────────────────────────────────────────
    # Fallback Chain — Auto-Generation
    # ─────────────────────────────────────────────────────────────────

    def _load_fallback_chain(self, model_config):
        """
        Load fallback chain from config, or auto-generate from configured providers.
        Manual override: set models.fallback_chain in config.yaml.
        """
        explicit = model_config.get('fallback_chain')
        if explicit and isinstance(explicit, list) and len(explicit) > 0:
            return explicit
        return self._build_fallback_chain()

    def _build_fallback_chain(self):
        """
        Auto-generate a fallback chain based on which providers have API keys.
        Orders by capability tier (cloud-first, most capable first, local last).
        Excludes the primary and configured fallback models (they're tried before the chain).
        """
        providers_cfg = self.core.config.get('providers', {})
        chain = []

        for provider, (tier, default_model) in sorted(PROVIDER_TIERS.items(), key=lambda x: x[1][0]):
            # Skip primary and configured fallback — they're handled before the chain
            if provider == self.primary_provider:
                continue
            if provider == self.fallback_provider:
                continue

            # Check if provider has an API key configured
            if provider == 'ollama':
                # Ollama doesn't need an API key — check if it's available
                ollama_mgr = getattr(self.core, 'ollama_manager', None)
                if ollama_mgr and ollama_mgr.discovered_models:
                    # Use the first discovered model
                    chain.append({
                        'provider': 'ollama',
                        'model': ollama_mgr.discovered_models[0],
                        'tier': tier,
                    })
                continue

            prov_cfg = providers_cfg.get(provider, {})
            api_key = (prov_cfg.get('apiKey', '') or prov_cfg.get('api_key', '')
                       or prov_cfg.get('apikey', ''))

            # NVIDIA: also check unified key or sub-keys
            if provider == 'nvidia' and not api_key:
                sub_keys = prov_cfg.get('keys', {})
                if sub_keys and any(v for v in sub_keys.values()):
                    api_key = next((v for v in sub_keys.values() if v), '')

            if api_key and api_key not in ('', 'NONE'):
                chain.append({
                    'provider': provider,
                    'model': default_model,
                    'tier': tier,
                })

        return chain

    def rebuild_fallback_chain(self):
        """Rebuild the chain (called after model switch or config change)."""
        model_config = self.core.config.get('models', {})
        self.fallback_chain = self._load_fallback_chain(model_config)

    # ─────────────────────────────────────────────────────────────────
    # Provider Health Tracking
    # ─────────────────────────────────────────────────────────────────

    def _get_health(self, provider):
        """Get or create health record for a provider."""
        if provider not in self._provider_health:
            self._provider_health[provider] = {
                'failures': 0,
                'last_failure': None,
                'cooldown_until': None,
            }
        return self._provider_health[provider]

    def _is_provider_available(self, provider):
        """Check if a provider is NOT in cooldown."""
        health = self._provider_health.get(provider)
        if not health or not health.get('cooldown_until'):
            return True
        return datetime.now() >= health['cooldown_until']

    def _record_provider_failure(self, provider, error_type):
        """Record a failure for a provider, set cooldown."""
        health = self._get_health(provider)
        health['failures'] += 1
        health['last_failure'] = datetime.now()

        # Set cooldown based on error type
        cooldown_secs = self.cooldown_config.get(
            error_type, DEFAULT_COOLDOWNS.get(error_type, 10)
        )
        health['cooldown_until'] = datetime.now() + timedelta(seconds=cooldown_secs)

    def _record_provider_success(self, provider):
        """Record a success — clear failure state."""
        health = self._get_health(provider)
        health['failures'] = 0
        health['cooldown_until'] = None

    async def check_recovery(self):
        """Clear expired cooldowns (called periodically by core)."""
        now = datetime.now()
        for provider, health in self._provider_health.items():
            if health.get('cooldown_until') and now >= health['cooldown_until']:
                health['cooldown_until'] = None
                health['failures'] = 0

        # Also check if it's time to retry the primary model (legacy behavior)
        if self.current_mode == 'fallback' and self.last_error_time:
            elapsed = (now - self.last_error_time).total_seconds()
            if elapsed >= self.recovery_time:
                await self.core.log("⏰ Recovery time elapsed — retrying primary model", priority=2)
                await self.switch_to_primary()

    def get_fallback_status(self):
        """Return fallback chain + provider health for API/UI consumption."""
        status = {
            'chain': [],
            'provider_health': {},
        }
        for entry in self.fallback_chain:
            p = entry['provider']
            available = self._is_provider_available(p)
            health = self._provider_health.get(p, {})
            status['chain'].append({
                'provider': p,
                'model': entry['model'],
                'tier': entry.get('tier', 9),
                'available': available,
                'failures': health.get('failures', 0),
            })
        for p, h in self._provider_health.items():
            status['provider_health'][p] = {
                'failures': h.get('failures', 0),
                'cooldown_until': h['cooldown_until'].isoformat() if h.get('cooldown_until') else None,
                'last_failure': h['last_failure'].isoformat() if h.get('last_failure') else None,
            }
        return status

    # ─────────────────────────────────────────────────────────────────
    # Core Model Switching (preserved from v0.9.1)
    # ─────────────────────────────────────────────────────────────────

    def get_current_model(self):
        """Get current active model (primary or fallback)."""
        if self.current_mode == 'primary':
            return {
                'provider': self.primary_provider,
                'model': self.primary_model,
                'mode': 'primary'
            }
        else:
            return {
                'provider': self.fallback_provider,
                'model': self.fallback_model,
                'mode': 'fallback'
            }

    async def switch_to_fallback(self, reason=""):
        """Switch to fallback model."""
        if self.current_mode == 'fallback':
            return  # Already on fallback

        self.current_mode = 'fallback'
        fallback = self.get_current_model()

        await self.core.log(
            f"🔄 Switched to FALLBACK model: {fallback['provider']}/{fallback['model']}"
            f"{f' (Reason: {reason})' if reason else ''}",
            priority=2
        )

        # Update gateway LLM reference
        self.core.gateway.llm.provider = fallback['provider']
        self.core.gateway.llm.model = fallback['model']
        self._set_api_key(fallback['provider'])

        return fallback

    async def switch_to_primary(self):
        """Switch to primary model (or refresh gateway if primary model was changed)."""
        self.current_mode = 'primary'
        self.error_count = 0
        primary = self.get_current_model()

        await self.core.log(
            f"🔄 Switched to PRIMARY model: {primary['provider']}/{primary['model']}",
            priority=2
        )

        # Update gateway LLM reference
        self.core.gateway.llm.provider = primary['provider']
        self.core.gateway.llm.model = primary['model']
        self._set_api_key(primary['provider'])

        return primary

    async def handle_api_error(self, error_msg):
        """Handle API error - may trigger fallback."""
        self.error_count += 1
        self.last_error_time = datetime.now()

        if not self.auto_fallback_enabled:
            return

        # Check if should fallback
        if self.current_mode == 'primary' and self.error_count >= self.error_threshold:
            await self.switch_to_fallback(reason=f"API errors: {self.error_count}")

    def _set_api_key(self, provider):
        """Set correct API key for provider."""
        providers_cfg = self.core.config.get('providers', {})

        if provider == "nvidia":
            # Route to the correct NVIDIA API key based on the active model name
            # Try unified key first
            nvidia_cfg = providers_cfg.get('nvidia', {})
            unified = nvidia_cfg.get('apiKey', '') or nvidia_cfg.get('api_key', '')
            if unified:
                self.core.gateway.llm.api_key = unified
                return
            keys = nvidia_cfg.get('keys', {})
            model = self.core.gateway.llm.model or ''
            model_lower = model.lower()
            key_routing = [
                (['qwen'],                  'qwen'),
                (['z-ai', 'glm'],           'glm'),
                (['moonshotai', 'kimi'],     'kimi'),
                (['stepfun'],               'stepfun'),
                (['deepseek'],              'deepseek'),
            ]
            selected_key = None
            for fragments, key_name in key_routing:
                if any(frag in model_lower for frag in fragments):
                    selected_key = keys.get(key_name)
                    break
            all_keys = list(keys.values())
            self.core.gateway.llm.api_key = selected_key or (all_keys[0] if all_keys else "NONE")
        elif provider == "ollama":
            self.core.gateway.llm.api_key = "NONE"
        else:
            # All other providers use apiKey field
            prov_cfg = providers_cfg.get(provider, {})
            key = prov_cfg.get('apiKey', '') or prov_cfg.get('api_key', '') or prov_cfg.get('apikey', '')
            self.core.gateway.llm.api_key = key or "NONE"

    async def set_primary(self, provider, model):
        """Set new primary model and switch to it."""
        self.primary_provider = provider
        self.primary_model = model
        await self._save_config()
        await self.switch_to_primary()
        self.rebuild_fallback_chain()

    async def set_fallback(self, provider, model):
        """Set new fallback model (doesn't switch to it)."""
        self.fallback_provider = provider
        self.fallback_model = model
        await self._save_config()
        self.rebuild_fallback_chain()

        await self.core.log(
            f"✅ Fallback model updated: {provider}/{model}",
            priority=2
        )

    async def _save_config(self):
        """Save model config to config.yaml."""
        try:
            # Read current config
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Update models section
            if 'models' not in config:
                config['models'] = {}

            config['models']['primary_provider'] = self.primary_provider
            config['models']['primary_model'] = self.primary_model
            config['models']['fallback_provider'] = self.fallback_provider
            config['models']['fallback_model'] = self.fallback_model

            # Also sync gateway section so startup reads are consistent
            if 'gateway' not in config:
                config['gateway'] = {}
            config['gateway']['provider'] = self.primary_provider
            config['gateway']['model'] = self.primary_model

            # Write back
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

            # Sync in-memory config so subsequent saves by other code paths
            # (e.g. web_deck toggle saves) don't overwrite with stale values
            self.core.config.setdefault('models', {})
            self.core.config['models']['primary_provider'] = self.primary_provider
            self.core.config['models']['primary_model'] = self.primary_model
            self.core.config['models']['fallback_provider'] = self.fallback_provider
            self.core.config['models']['fallback_model'] = self.fallback_model
            self.core.config.setdefault('gateway', {})
            self.core.config['gateway']['provider'] = self.primary_provider
            self.core.config['gateway']['model'] = self.primary_model

            await self.core.log("💾 Model config saved", priority=2)

        except Exception as e:
            await self.core.log(f"Error saving model config: {e}", priority=1)

    # ─────────────────────────────────────────────────────────────────
    # Smart Model Routing (Galactic Exclusive)
    # ─────────────────────────────────────────────────────────────────

    # Mapping: task_type -> (provider, model_or_None)
    # model=None means "use best available discovered Ollama model"
    SMART_ROUTING_TABLE = {
        "coding":    ("nvidia",    "qwen/qwen3-coder-480b-a35b-instruct"),
        "reasoning": ("nvidia",    "deepseek-ai/deepseek-v3.2"),
        "creative":  ("xai",       "grok-4"),
        "local":     ("ollama",    None),
        "quick":     ("groq",      "llama-4-scout-17b-16e-instruct"),
        "vision":    ("google",    "gemini-2.5-flash"),
        "math":      ("openai",    "o3-mini"),
        "chat":      ("google",    "gemini-2.5-flash"),
    }

    SMART_ROUTING_KEYWORDS = {
        "coding": ["write code", "debug", "python", "javascript", "typescript", "script",
                   "function", "class", "implement", "fix this code", "refactor", "compile"],
        "reasoning": ["analyze", "reason through", "step by step", "think about", "evaluate",
                      "compare", "pros and cons", "should i", "logical"],
        "creative": ["write a story", "poem", "creative", "fiction", "imagine", "brainstorm",
                     "generate ideas", "song lyrics"],
        "local": ["local", "offline", "private", "no cloud", "on-device", "ollama"],
        "quick": ["quick", "fast", "briefly", "short answer", "tldr", "summarize in one",
                  "one sentence", "brief"],
        "vision": ["image", "screenshot", "picture", "photo", "analyze this image", "what do you see"],
    }

    def classify_task(self, user_input: str) -> str:
        """Classify a user message into a task type for smart routing.

        Strips attached file content (Telegram documents, pasted code blocks)
        so classification is based on the user's intent, not file contents.
        """
        text = user_input

        # Strip Telegram-style attached file blocks: "[Attached file: X]\n---\n...\n---"
        import re
        text = re.sub(
            r'\[Attached file:[^\]]*\]\s*\n-{3,}\n.*?\n-{3,}',
            '', text, flags=re.DOTALL
        )

        # Strip markdown code blocks (``` ... ```)
        text = re.sub(r'```[\s\S]*?```', '', text)

        # If nothing left after stripping, default (don't classify based on file content)
        text = text.strip()
        if not text:
            return "default"

        lower = text.lower()
        for task_type, keywords in self.SMART_ROUTING_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return task_type
        return "default"

    async def auto_route(self, user_input: str):
        """
        Temporarily switch to the best model for the detected task type.
        Only active when config.models.smart_routing = true.
        """
        if not self.core.config.get('models', {}).get('smart_routing', False):
            return  # Feature is opt-in

        task_type = self.classify_task(user_input)
        routing = self.SMART_ROUTING_TABLE.get(task_type)
        if not routing or task_type == "default":
            return  # No change for unclassified tasks

        provider, model = routing

        # For ollama: pick first discovered model
        if provider == "ollama" and model is None:
            ollama_mgr = getattr(self.core, 'ollama_manager', None)
            if ollama_mgr and ollama_mgr.discovered_models:
                model = ollama_mgr.discovered_models[0]
            else:
                return  # No Ollama models available, skip

        # Availability guard: don't route to providers in cooldown or missing API keys
        if not self._is_provider_available(provider):
            await self.core.log(
                f"Smart routing: {provider} is in cooldown, skipping route",
                priority=3
            )
            return

        if provider != 'ollama':
            providers_cfg = self.core.config.get('providers', {})
            prov_cfg = providers_cfg.get(provider, {})
            api_key = (prov_cfg.get('apiKey', '') or prov_cfg.get('api_key', '')
                       or prov_cfg.get('apikey', ''))
            if provider == 'nvidia' and not api_key:
                sub_keys = prov_cfg.get('keys', {})
                api_key = next((v for v in sub_keys.values() if v), '') if sub_keys else ''
            if not api_key or api_key == 'NONE':
                await self.core.log(
                    f"Smart routing: {provider} has no API key, skipping route",
                    priority=3
                )
                return

        if model:
            # Save current state so speak() can restore after the request
            self._pre_route_state = {
                'provider': self.core.gateway.llm.provider,
                'model': self.core.gateway.llm.model,
                'api_key': getattr(self.core.gateway.llm, 'api_key', 'NONE'),
            }
            self._routed = True

            self.core.gateway.llm.provider = provider
            self.core.gateway.llm.model = model
            self._set_api_key(provider)
            await self.core.log(
                f"🎯 Smart routing: {provider}/{model} (task: {task_type})",
                priority=3
            )

    def get_status_report(self):
        """Get formatted status report."""
        current = self.get_current_model()

        report = f"**Current:** {current['provider']}/{current['model']} ({current['mode']})\n"
        report += f"**Primary:** {self.primary_provider}/{self.primary_model}\n"
        report += f"**Fallback:** {self.fallback_provider}/{self.fallback_model}\n"
        report += f"**Auto-Fallback:** {'Enabled' if self.auto_fallback_enabled else 'Disabled'}\n"
        smart = self.core.config.get('models', {}).get('smart_routing', False)
        report += f"**Smart Routing:** {'Enabled' if smart else 'Disabled'}\n"

        if self.fallback_chain:
            report += f"**Fallback Chain:** {len(self.fallback_chain)} models\n"
            for i, entry in enumerate(self.fallback_chain, 1):
                avail = "🟢" if self._is_provider_available(entry['provider']) else "🔴"
                report += f"  {i}. {avail} {entry['provider']}/{entry['model']}\n"

        if self.current_mode == 'fallback':
            report += f"**Error Count:** {self.error_count}\n"
            if self.last_error_time:
                elapsed = int((datetime.now() - self.last_error_time).total_seconds())
                report += f"**Last Error:** {elapsed}s ago\n"

        return report
