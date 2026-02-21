"""
Galactic AI - Model Manager
Handles primary/fallback model configuration and automatic switching on errors
"""

import asyncio
import yaml
import os
from datetime import datetime

class ModelManager:
    """
    Manages model selection with primary/fallback system.
    Automatically switches to fallback on API errors.
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
        self.recovery_time = model_config.get('recovery_time_seconds', 300)  # 5 minutes
    
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
        """Switch back to primary model."""
        if self.current_mode == 'primary':
            return  # Already on primary
        
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
    
    async def check_recovery(self):
        """Check if enough time has passed to retry primary model."""
        if self.current_mode == 'fallback' and self.last_error_time:
            elapsed = (datetime.now() - self.last_error_time).total_seconds()
            
            if elapsed >= self.recovery_time:
                await self.core.log("⏰ Recovery time elapsed - attempting primary model", priority=2)
                await self.switch_to_primary()
    
    def _set_api_key(self, provider):
        """Set correct API key for provider."""
        providers_cfg = self.core.config.get('providers', {})

        if provider == "nvidia":
            # Smart key routing: match model name fragments to named keys
            from nvidia_gateway import resolve_nvidia_key
            keys = providers_cfg.get('nvidia', {}).get('keys', {})
            model = self.core.gateway.llm.model or ''
            self.core.gateway.llm.api_key = resolve_nvidia_key(model, keys)
        elif provider == "ollama":
            self.core.gateway.llm.api_key = "NONE"
        else:
            # All other providers (google, anthropic, openai, xai, groq, mistral, cerebras,
            # openrouter, huggingface, kimi, zai, minimax) use apiKey field
            prov_cfg = providers_cfg.get(provider, {})
            key = prov_cfg.get('apiKey', '') or prov_cfg.get('api_key', '') or prov_cfg.get('apikey', '')
            self.core.gateway.llm.api_key = key or "NONE"
    
    async def set_primary(self, provider, model):
        """Set new primary model and switch to it."""
        self.primary_provider = provider
        self.primary_model = model
        await self._save_config()
        await self.switch_to_primary()
    
    async def set_fallback(self, provider, model):
        """Set new fallback model (doesn't switch to it)."""
        self.fallback_provider = provider
        self.fallback_model = model
        await self._save_config()
        
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
            
            # Write back
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            
            await self.core.log("💾 Model config saved", priority=2)
            
        except Exception as e:
            await self.core.log(f"Error saving model config: {e}", priority=1)
    
    # ─────────────────────────────────────────────────────────────────
    # Smart Model Routing (Galactic Exclusive)
    # ─────────────────────────────────────────────────────────────────

    # Mapping: task_type -> (provider, model_or_None)
    # model=None means "use best available discovered Ollama model"
    SMART_ROUTING_TABLE = {
        # 🧠 Heavy reasoning & analysis → Llama 3.1 405B (NVIDIA's biggest open model)
        "reasoning": ("nvidia",    "meta/llama-3.1-405b-instruct"),
        # 💻 Code generation → Qwen 480B Coder (purpose-built, massive)
        "coding":    ("nvidia",    "qwen/qwen3-coder-480b-a35b-instruct"),
        # 👁️ Vision / image analysis → Phi-3.5 Vision (purpose-built for image reasoning)
        "vision":    ("nvidia",    "microsoft/phi-3.5-vision-instruct"),
        # ✨ Creative writing → Grok 4 (strong creative model)
        "creative":  ("xai",       "grok-4"),
        # 💬 General chat → Gemma 3 27B via NVIDIA (fast, capable, multimodal)
        "chat":      ("nvidia",    "google/gemma-3-27b-it"),
        # ⚡ Quick answers → Groq (fastest inference on planet Earth)
        "quick":     ("groq",      "llama-4-scout-17b-16e-instruct"),
        # 🔒 Local / private → Ollama (never leaves your machine)
        "local":     ("ollama",    None),
        # 🔢 Math / logic → DeepSeek V3 (exceptional at math & structured reasoning)
        "math":      ("nvidia",    "deepseek-ai/deepseek-v3.2"),
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
        "vision": ["image", "screenshot", "picture", "photo", "analyze this image", "what do you see",
                    "look at", "describe this", "read this image", "what's in", "ocr", "scan this",
                    "identify", "vision", "phi", "what is shown", "visual"],
    }

    def classify_task(self, user_input: str) -> str:
        """Classify a user message into a task type for smart routing."""
        lower = user_input.lower()
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

        if model:
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

        if self.current_mode == 'fallback':
            report += f"**Error Count:** {self.error_count}\n"
            if self.last_error_time:
                elapsed = int((datetime.now() - self.last_error_time).total_seconds())
                report += f"**Last Error:** {elapsed}s ago\n"
        
        return report
