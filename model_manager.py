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
        
        # Initialize PROVIDER_TIERS with safe defaults
        self.provider_tiers = {
            'google':      (1, 'gemini-2.5-flash'),
            'openai':      (1, 'gpt-4o'),
            'deepseek':    (2, 'deepseek-chat'),
            'mistral':     (2, 'mistral-large-latest'),
            'openrouter':  (3, 'google/gemini-2.5-flash'),
            'ollama':      (9, None),
        }
        
        # Mapping: task_type -> (provider, model_or_None)
        # model=None means "use best available discovered Ollama model"
        self.smart_routing_table = {
            "coding":    ("deepseek",  "deepseek-chat"),
            "reasoning": ("deepseek",  "deepseek-reasoner"),
            "creative":  ("openai",    "gpt-4.1"),
            "local":     ("ollama",    None),
            "quick":     ("google",    "gemini-2.5-flash"),
            "vision":    ("google",    "gemini-2.5-flash"),
            "math":      ("openai",    "o3-mini"),
            "chat":      ("google",    "gemini-2.5-flash"),
        }
        
        self._load_fallback_policy_from_yaml()

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

    def _load_fallback_policy_from_yaml(self):
        """Load fallback tiers and smart routing from config/models.yaml if available."""
        models_yaml_path = os.path.join(os.path.dirname(self.config_path), 'config', 'models.yaml')
        if not os.path.exists(models_yaml_path):
            return
            
        try:
            with open(models_yaml_path, 'r', encoding='utf-8') as f:
                models_data = yaml.safe_load(f)
                
            # 1. Load Fallback Tiers
            policy = models_data.get('fallback_policy', {})
            tiers_config = policy.get('tiers', {})
            
            if tiers_config:
                new_tiers = {}
                for provider, cfg in tiers_config.items():
                    if isinstance(cfg, dict):
                        new_tiers[provider] = (cfg.get('tier', 3), cfg.get('default_model'))
                    elif isinstance(cfg, (list, tuple)) and len(cfg) == 2:
                        new_tiers[provider] = tuple(cfg)
                
                if new_tiers:
                    self.provider_tiers = new_tiers
                    import logging
                    logging.info(f"Loaded {len(new_tiers)} provider tiers from models.yaml")
                    
            # 2. Load Smart Routing Table
            smart_cfg = models_data.get('smart_routing', {})
            if smart_cfg:
                new_routing = {}
                for task, cfg in smart_cfg.items():
                    if isinstance(cfg, dict):
                        new_routing[task] = (cfg.get('provider'), cfg.get('model'))
                    elif isinstance(cfg, (list, tuple)) and len(cfg) == 2:
                        new_routing[task] = tuple(cfg)
                
                if new_routing:
                    self.smart_routing_table = new_routing
                    import logging
                    logging.info(f"Loaded {len(new_routing)} smart routing entries from models.yaml")
                    
        except Exception as e:
            import logging
            logging.error(f"Error loading policy from models.yaml: {e}")

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

        for provider, (tier, default_model) in sorted(self.provider_tiers.items(), key=lambda x: x[1][0]):
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
        
        # Resolve base provider for pseudo-providers
        base_provider = provider
        if provider.startswith("openrouter-"):
            base_provider = "openrouter"

        if base_provider == "nvidia":
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
        elif base_provider == "ollama":
            self.core.gateway.llm.api_key = "NONE"
        else:
            # All other providers use apiKey field
            prov_cfg = providers_cfg.get(base_provider, {})
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

    # ─────────────────────────────────────────────────────────────────
    # Smart Model Routing (Galactic Exclusive)
    # ─────────────────────────────────────────────────────────────────

    async def auto_route(self, user_input: str):
        """
        Temporarily switch to the best model for the detected task type.
        Only active when config.models.smart_routing = true.
        """
        if not self.core.config.get('models', {}).get('smart_routing', False):
            return  # Feature is opt-in

        task_type = self.classify_task(user_input)
        routing = self.smart_routing_table.get(task_type)
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
