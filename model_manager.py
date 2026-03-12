"""
Galactic AI - Model Manager
Handles primary/fallback model configuration, automatic switching on errors,
and intelligent multi-level fallback chain with per-provider health tracking.
"""

import asyncio
import yaml
import os
import re
import contextvars
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

class ModelManager:
    """
    Manages model selection with primary/fallback system.
    Automatically switches to fallback on API errors.
    Provides an intelligent multi-level fallback chain.
    """

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

    def __init__(self, core):
        self.core = core
        self.config_path = core.config_path
        
        # Load model config
        model_config = self.core.config.get('models', {})

        self.primary_provider = model_config.get('primary_provider', 'google')
        self.primary_model = model_config.get('primary_model', 'gemini-2.5-flash')

        self.fallback_provider = model_config.get('fallback_provider', 'ollama')
        self.fallback_model = model_config.get('fallback_model', 'qwen3:8b')

        # Startup diagnostic — shows exactly what was loaded and whether defaults were used
        import logging
        _pp_src = 'config' if 'primary_provider' in model_config else 'DEFAULT'
        _pm_src = 'config' if 'primary_model' in model_config else 'DEFAULT'
        _fp_src = 'config' if 'fallback_provider' in model_config else 'DEFAULT'
        _fm_src = 'config' if 'fallback_model' in model_config else 'DEFAULT'
        logging.info(
            f"ModelManager init: primary={self.primary_provider}/{self.primary_model} "
            f"[{_pp_src}/{_pm_src}] fallback={self.fallback_provider}/{self.fallback_model} "
            f"[{_fp_src}/{_fm_src}] config_path={self.config_path}"
        )

        self._session_current_mode = contextvars.ContextVar('mm_current_mode', default='primary')
        self._session_error_count = contextvars.ContextVar('mm_error_count', default=0)
        self._session_last_error_time = contextvars.ContextVar('mm_last_error_time', default=None)
        self._session_routed = contextvars.ContextVar('mm_routed', default=False)
        self._session_pre_route_state = contextvars.ContextVar('mm_pre_route_state', default=None)

        # Auto-fallback settings
        self.auto_fallback_enabled = model_config.get('auto_fallback', True)
        self.error_threshold = model_config.get('error_threshold', 3)
        self.recovery_time = model_config.get('recovery_time_seconds', 300)

        # ── Resilient manual fallback ──────────────────────────────────
        self._provider_health = {}     # {provider: {failures, last_failure, cooldown_until}}
        self._fallback_lock = asyncio.Lock()
        self._last_successful_fallback = None  # (provider, model, timestamp)
        self.cooldown_config = model_config.get('fallback_cooldowns', {})
        self.fallback_chain = [] # DISABLED

        # ── Smart routing state (Disabled) ──
        self._routed = False
        self._pre_route_state = None

    # Policy loading removed (Auto Fallback simplification)

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

        # V14: Better classification for Ollama native errors
        if "ollama" in low:
            # Treat 404 (model not found) as transient for Ollama because it usually means
            # the model is being pulled or the manager is still loading it.
            if "404" in low or "not found" in low:
                return ERROR_NETWORK # Network/Transient
            # 503 or "overloaded" is common during GPU memory swaps
            if "503" in low or "overloaded" in low or "busy" in low:
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

        # Client errors (400) - Fallback if it looks like an API/Model limitation
        if any(k in low for k in ("400", "invalid_argument", "invalid argument", "bad request",
                                   "missing a thought_signature", "thought_signature")):
            return ERROR_SERVER # Treat as transient to trigger fallback

        return ERROR_UNKNOWN

    # ─────────────────────────────────────────────────────────────────
    # Fallback Chain — Auto-Generation
    # ─────────────────────────────────────────────────────────────────

    # Fallback chain auto-generation removed as per user request

    def rebuild_fallback_chain(self):
        """No-op: All auto-fallback lists removed."""
        self.fallback_chain = []

    # ─────────────────────────────────────────────────────────────────
    # Provider Health Tracking
    # ─────────────────────────────────────────────────────────────────

    @property
    def current_mode(self): return self._session_current_mode.get()
    @current_mode.setter
    def current_mode(self, v): self._session_current_mode.set(v)

    @property
    def error_count(self): return self._session_error_count.get()
    @error_count.setter
    def error_count(self, v): self._session_error_count.set(v)

    @property
    def last_error_time(self): return self._session_last_error_time.get()
    @last_error_time.setter
    def last_error_time(self, v): self._session_last_error_time.set(v)

    @property
    def _routed(self): return self._session_routed.get()
    @_routed.setter
    def _routed(self, v): self._session_routed.set(v)

    @property
    def _pre_route_state(self): return self._session_pre_route_state.get()
    @_pre_route_state.setter
    def _pre_route_state(self, v): self._session_pre_route_state.set(v)

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
            error_type, self.DEFAULT_COOLDOWNS.get(error_type, 10)
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
        """Return provider health for API/UI consumption."""
        status = {
            'chain': [],
            'provider_health': {},
        }
        # Chain is now empty/deprecated in this simplified model.
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
        
        # Ensure internally stored provider is normalized for future comparisons
        self.fallback_provider = fallback['provider']

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

        # Store the intended provider (may be a segment like openrouter-frontier)
        self.primary_provider = primary['provider']

        return primary

    async def handle_api_error(self, error_msg):
        """Handle API error - will trigger manual fallback if configured."""
        self.error_count += 1
        self.last_error_time = datetime.now()

        # Check if should fallback
        if self.current_mode == 'primary' and self.error_count >= self.error_threshold:
            await self.switch_to_fallback(reason=f"API errors: {self.error_count}")

    def _set_api_key(self, provider):
        """Set correct API key for provider by delegating to Gateway logic."""
        key = self.core.gateway._get_provider_api_key(provider)
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
        """Save model config to config.yaml with throttle to prevent loops."""
        now = datetime.now()
        if getattr(self, '_last_save_time', None):
            if (now - self._last_save_time).total_seconds() < 5:
                await self.core.log("Skipping rapid config write, on cooldown...", priority=1)
                return
        self._last_save_time = now
        try:
            # Read current config
            with open(self.config_path, 'r', encoding='utf-8') as f:
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
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

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

            await self.core.log(
                f"💾 Model config saved → {self.primary_provider}/{self.primary_model} "
                f"(fallback: {self.fallback_provider}/{self.fallback_model}) "
                f"[{self.config_path}]",
                priority=2
            )

        except Exception as e:
            await self.core.log(f"Error saving model config: {e}", priority=1)

    # Smart routing logic removed

    async def auto_route(self, user_input: str):
        """No-op: Smart routing removed."""
        return

    def get_status_report(self):
        """Get formatted status report."""
        current = self.get_current_model()

        report = f"**Current:** {current['provider']}/{current['model']} ({current['mode']})\n"
        report += f"**Primary:** {self.primary_provider}/{self.primary_model}\n"
        report += f"**Fallback:** {self.fallback_provider}/{self.fallback_model}\n"
        report += f"**Auto-Fallback:** {'Enabled' if self.auto_fallback_enabled else 'Disabled'}\n"

        if self.current_mode == 'fallback':
            report += f"**Error Count:** {self.error_count}\n"
            if self.last_error_time:
                elapsed = int((datetime.now() - self.last_error_time).total_seconds())
                report += f"**Last Error:** {elapsed}s ago\n"

        return report
    def get_all_models(self):
        """
        Returns a flat list of all models from configured providers and discovered Ollama models.
        Each entry: {"id": "provider/model_id", "label": "Model Name"}
        Used to populate UI model selectors.
        """
        all_models = []
        providers_cfg = self.core.config.get('providers', {})
        
        # 1. Load config/models.yaml
        models_yaml_path = os.path.join(os.path.dirname(self.config_path), 'config', 'models.yaml')
        models_data = {}
        if os.path.exists(models_yaml_path):
            try:
                with open(models_yaml_path, 'r', encoding='utf-8') as f:
                    models_data = yaml.safe_load(f) or {}
            except Exception as e:
                import logging
                logging.error(f"Error loading models.yaml for get_all_models: {e}")

        available_providers = models_data.get('providers', {})
        
        # 2. Collect from configured cloud providers
        for provider, models_list in available_providers.items():
            if provider == 'ollama':
                continue # Handled below via discovery
            
            # Check if provider is configured with an API key
            prov_cfg = providers_cfg.get(provider, {})
            api_key = (prov_cfg.get('apiKey', '') or prov_cfg.get('api_key', '')
                       or prov_cfg.get('apikey', ''))
            
            # NVIDIA special case: unified key or sub-keys
            if provider == 'nvidia' and not api_key:
                sub_keys = prov_cfg.get('keys', {})
                if sub_keys and any(v for v in sub_keys.values()):
                    api_key = next((v for v in sub_keys.values() if v), '')

            if api_key and api_key not in ('', 'NONE'):
                for m in models_list:
                    if m.get('enabled', True):
                        mid = m.get('id')
                        mname = m.get('name', mid)
                        
                        # Format ID for subagent_manager.spawn(): "provider/model"
                        full_id = mid
                        if provider != 'openrouter' and '/' not in mid:
                            full_id = f"{provider}/{mid}"
                        
                        all_models.append({
                            "id": full_id,
                            "name": f"{mname} ({provider})"
                        })

        # 3. Collect from discovered Ollama models
        ollama_mgr = getattr(self.core, 'ollama_manager', None)
        if ollama_mgr and hasattr(ollama_mgr, 'discovered_models'):
            for m in ollama_mgr.discovered_models:
                all_models.append({
                    "id": f"ollama/{m}",
                    "name": f"🦙 {m} (local)"
                })
        
        return all_models

    def resolve_model_id(self, query: str) -> str:
        """
        Resolves a fuzzy model string (e.g. "Qwen3", "ollama/qwen3", or full ID)
        to the best matching unique provider/model ID.
        Returns the original query string if no better match is found.
        """
        if not query:
            return query
            
        all_models = self.get_all_models()
        query_l = query.lower().strip()
        
        # 0. Handle hf.co (Ollama) specific routing
        if query_l.startswith('hf.co/'):
            # Try to find an ollama model that has this ID or contains it
            for m in all_models:
                mid_l = m['id'].lower()
                if mid_l == f"ollama/{query_l}":
                    return m['id']
                if query_l in mid_l and m['provider'] == 'ollama':
                    return m['id']
            # If not found in all_models, but looks like a full HF path, assume Ollama
            return f"ollama/{query}"

        # 1. Exact ID match (case-insensitive)
        for m in all_models:
            mid = m['id'].lower()
            if mid == query_l:
                return m['id']
                
        # 2. Prefix match (e.g. "ollama/qwen" matches "ollama/qwen3:8b")
        # Prioritize exact prefix + tag match
        for m in all_models:
            mid = m['id'].lower()
            if mid.startswith(query_l + ":"):
                return m['id']
        
        # 3. General prefix match
        for m in all_models:
            mid = m['id'].lower()
            if mid.startswith(query_l):
                return m['id']
                
        # 4. Keyword match on name/label (e.g. "qwen3" matches "🦙 qwen3:8b (local)")
        # Split by '/' to handle case where user provided provider/part
        query_part = query_l.split('/')[-1]
        for m in all_models:
            mname = m['name'].lower()
            if query_part in mname:
                return m['id']
                
        return query
