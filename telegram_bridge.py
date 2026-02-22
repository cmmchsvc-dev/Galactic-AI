# Galactic AI - Telegram Bridge
import asyncio
import httpx
import json
import os
import traceback
import tempfile
import time

class TelegramBridge:
    """The high-frequency command deck for Galactic AI."""
    def __init__(self, core):
        self.core = core
        self.config = core.config.get('telegram', {})
        self.bot_token = self.config.get('bot_token')
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.offset = 0
        self.client = httpx.AsyncClient(timeout=60.0)
        self.start_time = time.time()
        self.thinking_level = "LOW"
        self.verbose = False
        self.pending_api_key = {}  # {chat_id: {"provider": str, "model": str}}
        self._component = "Telegram"

    async def _log(self, message, priority=3):
        """Route logs to the Telegram component log file."""
        await self.core.log(message, priority=priority, component=self._component)

    async def set_commands(self):
        commands = [
            {"command": "status", "description": "🛰️ System Telemetry"},
            {"command": "model", "description": "🧠 Shift Brain"},
            {"command": "models", "description": "⚙️ Model Config (Primary/Fallback)"},
            {"command": "browser", "description": "📺 Launch Optics"},
            {"command": "screenshot", "description": "📸 Snap Optics"},
            {"command": "cli", "description": "🦾 Shell Command"},
            {"command": "compact", "description": "🧹 Compact Context"},
            {"command": "leads", "description": "🎯 New Leads"},
            {"command": "help", "description": "📖 Interactive Menu"}
        ]
        try:
            await self.client.post(f"{self.api_url}/setMyCommands", json={"commands": commands})
        except: pass

    async def send_message(self, chat_id, text, reply_markup=None):
        try:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup: payload["reply_markup"] = reply_markup
            await self.client.post(f"{self.api_url}/sendMessage", json=payload)
        except: pass

    async def send_photo(self, chat_id, photo_path, caption=None):
        try:
            url = f"{self.api_url}/sendPhoto"
            with open(photo_path, "rb") as photo:
                files = {"photo": photo}
                data = {"chat_id": chat_id}
                if caption: data["caption"] = caption
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Photo Error: {e}", priority=1)

    async def send_audio(self, chat_id, audio_path, caption=None):
        try:
            url = f"{self.api_url}/sendAudio"
            with open(audio_path, "rb") as audio:
                files = {"audio": audio}
                data = {"chat_id": chat_id}
                if caption: data["caption"] = caption[:1024]  # Telegram caption limit
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Audio Error: {e}", priority=1)

    async def send_voice(self, chat_id, voice_path, caption=None):
        """Send an OGG voice message to Telegram (shows as voice note with waveform)."""
        try:
            url = f"{self.api_url}/sendVoice"
            with open(voice_path, "rb") as voice:
                files = {"voice": voice}
                data = {"chat_id": chat_id}
                if caption: data["caption"] = caption[:1024]
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Voice Error: {e}", priority=1)

    async def _transcribe_audio(self, audio_path):
        """Transcribe audio using OpenAI Whisper API (preferred) or return None."""
        # Try OpenAI Whisper API
        openai_key = self.core.config.get('providers', {}).get('openai', {}).get('apiKey', '')
        if openai_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.openai.com/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {openai_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-1'}
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[STT] Whisper transcribed: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"Whisper STT error: {e}", priority=2)

        # Try Groq Whisper (free, fast) — same OpenAI-compatible endpoint
        groq_key = self.core.config.get('providers', {}).get('groq', {}).get('apiKey', '')
        if groq_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.groq.com/openai/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {groq_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-large-v3'}
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[STT] Groq Whisper transcribed: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"Groq STT error: {e}", priority=2)

        return None  # No transcription available

    async def send_typing(self, chat_id):
        try:
            await self.client.post(f"{self.api_url}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
        except: pass

    async def get_help_page(self, page):
        if page == "1":
            text = "🌌 **Commands (1/5) - System** 🛰️\n• `/status` - Vitals\n• `/model` - Brain\n• `/uptime` - Engine"
            buttons = [[{"text": "Next ➡️", "callback_data": "help_2"}]]
        elif page == "2":
            text = "🌌 **Commands (2/5) - Session** 🧹\n• `/reset` - Clear\n• `/compact` - Aura Imprint\n• `/stop` - Shutdown"
            buttons = [[{"text": "⬅️ Back", "callback_data": "help_1"}, {"text": "Next ➡️", "callback_data": "help_3"}]]
        elif page == "3":
            text = "🌌 **Commands (3/5) - Cognitive** 🧠\n• `/think` - Reasoning\n• `/verbose` - Log Feed\n• `/identity` - Swap"
            buttons = [[{"text": "⬅️ Back", "callback_data": "help_2"}, {"text": "Next ➡️", "callback_data": "help_4"}]]
        elif page == "4":
            text = "🌌 **Commands (4/5) - Mechanical** 🦾\n• `/browser` - YouTube\n• `/screenshot` - Snap\n• `/cli [cmd]` - Shell"
            buttons = [[{"text": "⬅️ Back", "callback_data": "help_3"}, {"text": "Next ➡️", "callback_data": "help_5"}]]
        else:
            text = "🌌 **Commands (5/5) - Automation** 🎯\n• `/sniper` - Leads\n• `/watchdog` - Emails\n• `/leads` - Recap"
            buttons = [[{"text": "⬅️ Back", "callback_data": "help_4"}, {"text": "Start 🔄", "callback_data": "help_1"}]]
        return text, {"inline_keyboard": buttons}

    def _get_live_ollama_menu_entries(self):
        """Return live Ollama model list from OllamaManager, falling back to static defaults."""
        defaults = [
            ("Qwen3 30B 🤖", "qwen3:30b"),
            ("Qwen3 8B ⚡️", "qwen3:8b"),
            ("Qwen3 Coder 30B 🦾", "qwen3-coder:30b")
        ]
        try:
            mgr = getattr(self.core, 'ollama_manager', None)
            if mgr and mgr.discovered_models:
                return [(f"{m} 🤖", m) for m in mgr.discovered_models[:10]]
        except Exception:
            pass
        return defaults

    async def get_think_menu(self):
        text = f"🧠 **Cognitive Control**\nCurrent: `{self.thinking_level}`\nChoose reasoning depth:"
        buttons = [[{"text": "Low (Fast) ⚡️", "callback_data": "think_low"}, {"text": "High (Deep) 🧠", "callback_data": "think_high"}]]
        return text, {"inline_keyboard": buttons}

    async def get_model_menu(self, provider=None):
        if not provider:
            text = "🧠 **Brain Matrix: Select Provider**\nChoose a core cluster to explore:"
            buttons = []
            row = []
            providers = self.core.config.get('providers', {})
            for p_name in providers:
                row.append({"text": f"{p_name.capitalize()}", "callback_data": f"prov_{p_name}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
            return text, {"inline_keyboard": buttons}
        
        text = f"🧠 **{provider.capitalize()} Cluster**\nSelect a specific brain to activate:"
        buttons = []
        model_map = {
            "anthropic": [
                ("Claude Opus 4.6 👑 [LATEST]", "claude-opus-4-6"),
                ("Claude Sonnet 4.6 🌟", "claude-sonnet-4-6"),
                ("Claude Haiku 4.5 ⚡️", "claude-haiku-4-5"),
                ("Claude Sonnet 4.5 🚀", "claude-sonnet-4-5"),
                ("Claude Opus 4.5 🏛️", "claude-opus-4-5"),
            ],
            "google": [
                ("Gemini 3.1 Pro 🧠 [LATEST]", "gemini-3.1-pro-preview"),
                ("Gemini 3 Flash ⚡️", "gemini-3-flash-preview"),
                ("Gemini 3 Pro 🧠", "gemini-3-pro-preview"),
                ("Gemini 2.5 Flash 🏎️", "gemini-2.5-flash"),
                ("Gemini 2.5 Pro 🦾", "gemini-2.5-pro"),
                ("Gemini 2.0 Flash ⚡️", "gemini-2.0-flash"),
            ],
            "openai": [
                ("GPT-4o 🧠 [LATEST]", "gpt-4o"),
                ("GPT-4.1 🌟", "gpt-4.1"),
                ("GPT-4o Mini ⚡️", "gpt-4o-mini"),
                ("o3 Mini 🧮", "o3-mini"),
                ("o1 🏛️", "o1"),
            ],
            "nvidia": [
                ("GLM-5 (Thinking) 🧠", "z-ai/glm5"),
                ("Kimi K2.5 (Thinking) 🌙", "moonshotai/kimi-k2.5"),
                ("Qwen 3.5 397B (Thinking) 🦾", "qwen/qwen3.5-397b-a17b"),
                ("Nemotron 30B (Reasoning) ⚛️", "nvidia/nemotron-3-nano-30b-a3b"),
                ("Nemotron Nano VL 👁️", "nvidia/nemotron-nano-12b-v2-vl"),
                ("StepFun 3.5 Flash ⚡️", "stepfun-ai/step-3.5-flash"),
                ("MiniMax M2.1 🎯", "minimaxai/minimax-m2.1"),
                ("DeepSeek V3.2 (Math) 🚀", "deepseek-ai/deepseek-v3.2"),
                ("Llama 405B 🏛️", "meta/llama-3.1-405b-instruct"),
                ("Phi-3.5 Vision (OCR) 👁️", "microsoft/phi-3.5-vision-instruct"),
                ("Gemma 3 27B 🌌", "google/gemma-3-27b-it"),
                ("Mistral Large 3 🌊", "mistralai/mistral-large-3-675b-instruct-2512"),
                ("Qwen 480B Coder 🦾", "qwen/qwen3-coder-480b-a35b-instruct"),
            ],
            "xai": [
                ("Grok 4 🧠 [LATEST]", "grok-4"),
                ("Grok 4 Fast ⚡️", "grok-4-fast"),
                ("Grok 3 🌌", "grok-3"),
                ("Grok 3 Mini 🎯", "grok-3-mini"),
            ],
            "deepseek": [
                ("DeepSeek V3 🧠 [LATEST]", "deepseek-chat"),
                ("DeepSeek R1 (Reasoning) 🧮", "deepseek-reasoner"),
            ],
            "groq": [
                ("Llama 4 Scout 17B ⚡️ [FAST]", "llama-4-scout-17b-16e-instruct"),
                ("Llama 4 Maverick 17B 🦾", "llama-4-maverick-17b-128e-instruct"),
                ("Llama 3.3 70B 🏛️", "llama-3.3-70b-versatile"),
                ("DeepSeek R1 70B 🧮", "deepseek-r1-distill-llama-70b"),
                ("Qwen 3 32B 🧠", "qwen-3-32b"),
            ],
            "mistral": [
                ("Mistral Small 3.1 ⚡️", "mistral-small-latest"),
                ("Codestral (Code) 🦾", "codestral-latest"),
                ("Devstral (Agents) 🤖", "devstral-small-latest"),
                ("Mistral Large 2 🏛️", "mistral-large-latest"),
                ("Magistral Medium 🧠", "magistral-medium-latest"),
            ],
            "cerebras": [
                ("Llama 3.3 70B ⚡️ [FAST]", "llama3.3-70b"),
                ("Llama 3.1 8B 🏎️", "llama3.1-8b"),
                ("Qwen 3 32B 🧠", "qwen-3-32b"),
            ],
            "openrouter": [
                ("Claude Opus 4.6 👑", "anthropic/claude-opus-4-6"),
                ("Claude Sonnet 4.6 🌟", "anthropic/claude-sonnet-4-6"),
                ("GPT-4o 🧠", "openai/gpt-4o"),
                ("Gemini 2.5 Pro 🦾", "google/gemini-2.5-pro"),
                ("DeepSeek V3 🚀", "deepseek/deepseek-chat"),
            ],
            "huggingface": [
                ("Qwen3 235B 🧠", "Qwen/Qwen3-235B-A22B"),
                ("Llama 4 Scout ⚡️", "meta-llama/Llama-4-Scout-17B-16E-Instruct"),
                ("DeepSeek V3 🚀", "deepseek-ai/DeepSeek-V3-0324"),
            ],
            "kimi": [
                ("Kimi K2.5 🌙", "moonshot-v1-auto"),
            ],
            "zai": [
                ("GLM-4 Plus 🧠", "glm-4-plus"),
            ],
            "minimax": [
                ("MiniMax Text-01 🎯", "MiniMax-Text-01"),
            ],
            "ollama": self._get_live_ollama_menu_entries()
        }

        models = model_map.get(provider, [])
        row = []
        for label, m_id in models:
            row.append({"text": label, "callback_data": f"mod_{provider}|{m_id}"})
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([{"text": "⬅️ Back to Providers", "callback_data": "mod_back"}])
        return text, {"inline_keyboard": buttons}

    async def get_models_config_menu(self, config_type=None, provider=None):
        """Model configuration menu with primary/fallback settings."""
        if not config_type:
            # Main menu - show current config
            mm = self.core.model_manager
            current = mm.get_current_model()
            mode_indicator = "🟢" if current['mode'] == 'primary' else "🟡"
            
            text = (
                f"⚙️ **Model Configuration**\n\n"
                f"{mode_indicator} **Active:** {current['provider']}/{current['model']} ({current['mode']})\n\n"
                f"🎯 **Primary:** {mm.primary_provider}/{mm.primary_model}\n"
                f"🔄 **Fallback:** {mm.fallback_provider}/{mm.fallback_model}\n\n"
                f"**Auto-Fallback:** {'✅ Enabled' if mm.auto_fallback_enabled else '❌ Disabled'}\n"
                f"**Error Threshold:** {mm.error_threshold}\n"
                f"**Recovery Time:** {mm.recovery_time}s\n\n"
                f"Choose what to configure:"
            )
            
            buttons = [
                [{"text": "🎯 Set Primary Model", "callback_data": "cfg_primary"}],
                [{"text": "🔄 Set Fallback Model", "callback_data": "cfg_fallback"}],
                [{"text": "🔄 Switch to Primary", "callback_data": "cfg_switch_primary"}],
                [{"text": "🟡 Switch to Fallback", "callback_data": "cfg_switch_fallback"}],
                [{"text": "⚙️ Toggle Auto-Fallback", "callback_data": "cfg_toggle_auto"}]
            ]
            return text, {"inline_keyboard": buttons}
        
        elif config_type == "provider":
            # Select provider for primary/fallback
            text = f"⚙️ **Select Provider for {provider.upper()}**"
            buttons = []
            row = []
            providers = self.core.config.get('providers', {})
            for p_name in providers:
                row.append({"text": f"{p_name.capitalize()}", "callback_data": f"cfg_{provider}_prov_{p_name}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
            buttons.append([{"text": "⬅️ Back", "callback_data": "cfg_back"}])
            return text, {"inline_keyboard": buttons}
        
        elif config_type == "model":
            # Select specific model for primary/fallback
            setting_type = provider.split("_")[0]  # 'primary' or 'fallback'
            provider_name = provider.split("_")[-1]
            
            text = f"⚙️ **Select Model from {provider_name.capitalize()}**\nSetting as **{setting_type.upper()}** model"
            
            model_map = {
                "anthropic": [
                    ("Opus 4.6 👑", "claude-opus-4-6"),
                    ("Sonnet 4.6 🌟", "claude-sonnet-4-6"),
                    ("Haiku 4.5 ⚡️", "claude-haiku-4-5"),
                    ("Sonnet 4.5 🚀", "claude-sonnet-4-5"),
                ],
                "google": [
                    ("Gemini 3.1 Pro 🧠", "gemini-3.1-pro-preview"),
                    ("Gemini 3 Flash ⚡️", "gemini-3-flash-preview"),
                    ("Gemini 3 Pro 🧠", "gemini-3-pro-preview"),
                    ("Gemini 2.5 Flash 🏎️", "gemini-2.5-flash"),
                    ("Gemini 2.5 Pro 🦾", "gemini-2.5-pro"),
                ],
                "openai": [
                    ("GPT-4o 🧠", "gpt-4o"),
                    ("GPT-4.1 🌟", "gpt-4.1"),
                    ("GPT-4o Mini ⚡️", "gpt-4o-mini"),
                    ("o3 Mini 🧮", "o3-mini"),
                ],
                "nvidia": [
                    ("GLM-5 Thinking 🧠", "z-ai/glm5"),
                    ("Kimi K2.5 Thinking 🌙", "moonshotai/kimi-k2.5"),
                    ("Qwen 3.5 397B 🦾", "qwen/qwen3.5-397b-a17b"),
                    ("Nemotron 30B ⚛️", "nvidia/nemotron-3-nano-30b-a3b"),
                    ("StepFun 3.5 Flash ⚡️", "stepfun-ai/step-3.5-flash"),
                    ("DeepSeek V3.2 🚀", "deepseek-ai/deepseek-v3.2"),
                    ("Llama 405B 🏛️", "meta/llama-3.1-405b-instruct"),
                    ("Phi-3.5 Vision 👁️", "microsoft/phi-3.5-vision-instruct"),
                    ("Qwen 480B Coder 🦾", "qwen/qwen3-coder-480b-a35b-instruct"),
                ],
                "xai": [
                    ("Grok 4 🧠", "grok-4"),
                    ("Grok 4 Fast ⚡️", "grok-4-fast"),
                ],
                "deepseek": [
                    ("DeepSeek V3 🧠", "deepseek-chat"),
                    ("DeepSeek R1 🧮", "deepseek-reasoner"),
                ],
                "groq": [
                    ("Llama 4 Scout ⚡️", "llama-4-scout-17b-16e-instruct"),
                    ("Llama 3.3 70B 🏛️", "llama-3.3-70b-versatile"),
                    ("DeepSeek R1 70B 🧮", "deepseek-r1-distill-llama-70b"),
                ],
                "mistral": [
                    ("Mistral Small 3.1 ⚡️", "mistral-small-latest"),
                    ("Mistral Large 2 🏛️", "mistral-large-latest"),
                    ("Codestral 🦾", "codestral-latest"),
                ],
                "cerebras": [
                    ("Llama 3.3 70B ⚡️", "llama3.3-70b"),
                    ("Qwen 3 32B 🧠", "qwen-3-32b"),
                ],
                "openrouter": [
                    ("Claude Opus 4.6 👑", "anthropic/claude-opus-4-6"),
                    ("GPT-4o 🧠", "openai/gpt-4o"),
                    ("DeepSeek V3 🚀", "deepseek/deepseek-chat"),
                ],
                "huggingface": [
                    ("Qwen3 235B 🧠", "Qwen/Qwen3-235B-A22B"),
                    ("Llama 4 Scout ⚡️", "meta-llama/Llama-4-Scout-17B-16E-Instruct"),
                ],
                "kimi": [("Kimi K2.5 🌙", "moonshot-v1-auto")],
                "zai": [("GLM-4 Plus 🧠", "glm-4-plus")],
                "minimax": [("MiniMax Text-01 🎯", "MiniMax-Text-01")],
                "ollama": self._get_live_ollama_menu_entries()
            }
            
            models = model_map.get(provider_name, [])
            buttons = []
            row = []
            for label, m_id in models:
                row.append({"text": label, "callback_data": f"cfg_{setting_type}_set_{provider_name}|{m_id}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
            buttons.append([{"text": "⬅️ Back", "callback_data": f"cfg_{setting_type}"}])
            return text, {"inline_keyboard": buttons}

    async def process_callback(self, chat_id, callback_query):
        data = callback_query.get("data", "")
        await self.client.post(f"{self.api_url}/answerCallbackQuery", json={"callback_query_id": callback_query["id"]})
        message_id = callback_query["message"]["message_id"]

        if data.startswith("help_"):
            page = data.split("_")[1]
            text, markup = await self.get_help_page(page)
            await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
        elif data.startswith("prov_"):
            provider = data.split("_")[1]
            text, markup = await self.get_model_menu(provider=provider)
            await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
        elif data == "mod_back":
            text, markup = await self.get_model_menu()
            await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
        elif data.startswith("think_"):
            level = data.split("_")[1].upper()
            self.thinking_level = level
            text, markup = await self.get_think_menu()
            await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": f"✅ Thinking: `{level}`\n\n{text}", "reply_markup": markup, "parse_mode": "Markdown"})
        elif data.startswith("mod_"):
            provider, model = data.split("_")[1].split("|")
            self.core.gateway.llm.provider = provider
            self.core.gateway.llm.model = model
            # Use centralized key setter (handles all providers including nvidia sub-keys)
            if hasattr(self.core, 'model_manager'):
                self.core.model_manager._set_api_key(provider)
            # Check if API key is actually configured
            current_key = getattr(self.core.gateway.llm, 'api_key', '')
            if provider != 'ollama' and (not current_key or current_key == 'NONE'):
                # No API key — prompt user to enter one
                self.pending_api_key[chat_id] = {"provider": provider, "model": model}
                await self.send_message(
                    chat_id,
                    f"🔑 **API Key Required**\n\n"
                    f"No API key configured for **{provider.capitalize()}**.\n"
                    f"Please paste your API key now and I'll save it:"
                )
                await self.client.post(f"{self.api_url}/editMessageText", json={
                    "chat_id": chat_id, "message_id": message_id,
                    "text": f"⏳ Waiting for {provider.capitalize()} API key...",
                    "parse_mode": "Markdown"
                })
            else:
                await self.send_message(chat_id, f"✅ **Shifted to {provider.capitalize()}:** `{model}`")
                text, markup = await self.get_model_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
        elif data.startswith("cfg_"):
            # Model configuration callbacks
            if data == "cfg_primary":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="primary")
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data == "cfg_fallback":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="fallback")
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data.startswith("cfg_primary_prov_") or data.startswith("cfg_fallback_prov_"):
                parts = data.split("_")
                setting_type = parts[1]  # 'primary' or 'fallback'
                provider_name = parts[3]
                text, markup = await self.get_models_config_menu(config_type="model", provider=f"{setting_type}_prov_{provider_name}")
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data.startswith("cfg_primary_set_") or data.startswith("cfg_fallback_set_"):
                parts = data.split("_")
                setting_type = parts[1]  # 'primary' or 'fallback'
                provider_and_model = parts[3]  # 'provider|model'
                provider_name, model_id = provider_and_model.split("|")
                
                if setting_type == "primary":
                    await self.core.model_manager.set_primary(provider_name, model_id)
                    await self.send_message(chat_id, f"✅ **Primary model set:** {provider_name}/{model_id}\nNow active!")
                else:
                    await self.core.model_manager.set_fallback(provider_name, model_id)
                    await self.send_message(chat_id, f"✅ **Fallback model set:** {provider_name}/{model_id}")
                
                text, markup = await self.get_models_config_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data == "cfg_switch_primary":
                await self.core.model_manager.switch_to_primary()
                await self.send_message(chat_id, "✅ **Switched to PRIMARY model**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data == "cfg_switch_fallback":
                await self.core.model_manager.switch_to_fallback(reason="Manual switch")
                await self.send_message(chat_id, "✅ **Switched to FALLBACK model**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data == "cfg_toggle_auto":
                self.core.model_manager.auto_fallback_enabled = not self.core.model_manager.auto_fallback_enabled
                status = "enabled" if self.core.model_manager.auto_fallback_enabled else "disabled"
                await self.send_message(chat_id, f"✅ **Auto-fallback {status}**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})
            elif data == "cfg_back":
                text, markup = await self.get_models_config_menu()
                await self.client.post(f"{self.api_url}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"})

    async def process_command(self, chat_id, cmd_text):
        parts = cmd_text.split()
        cmd = parts[0].lower().split('@')[0]
        
        if cmd == '/status':
            from datetime import datetime
            uptime = int(time.time() - self.start_time)
            plugins = ", ".join([p.name for p in self.core.plugins])
            mems = len(self.core.memory.index.get('memories', []))
            
            # Get current timestamp with seconds
            now = datetime.now().strftime("%H:%M:%S")
            
            # Get ACTUAL active model (what's really being used RIGHT NOW)
            active_provider = self.core.gateway.llm.provider
            active_model = self.core.gateway.llm.model
            
            # Get configured model info for comparison
            configured_model = self.core.model_manager.get_current_model()
            mode_indicator = "🟢" if configured_model['mode'] == 'primary' else "🟡"
            
            # Show if active model differs from configured
            model_display = f"{active_provider}/{active_model}"
            if (active_provider != configured_model['provider'] or 
                active_model != configured_model['model']):
                model_display += f" (Shifted from {configured_model['provider']}/{configured_model['model']})"
            
            report = (
                f"🌌 **GALACTIC AI SYSTEM STATUS** 🚀\n"
                f"⏰ **Time:** `{now}` | 🛸 **Version:** `v{self.core.config.get('system', {}).get('version', '?')}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{mode_indicator} **Model:** `{model_display}`\n"
                f"🔄 **Configured Mode:** `{configured_model['mode'].upper()}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧮 **Tokens:** `{self.core.gateway.total_tokens_in/1000:.1f}k in` / `{self.core.gateway.total_tokens_out/1000:.1f}k out`\n"
                f"📚 **Context:** `{mems} imprints` | 🧵 **Session:** `galactic:main`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛰️ **Uptime:** `{uptime}s` | **PID:** `{os.getpid()}`\n"
                f"⚙️ **Runtime:** `Direct AsyncIO` | **Think:** `{self.thinking_level}`\n"
                f"🧩 **Plugins:** `{plugins}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ **Condition:** `Nominal` ⚡️"
            )
            await self.send_message(chat_id, report)

        elif cmd == '/screenshot':
            browser = next((p for p in self.core.plugins if p.name == "BrowserExecutor"), None)
            if browser:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                path = os.path.join(images_dir, 'browser', 'screenshot.png')
                await browser.take_screenshot(path)
                await self.send_photo(chat_id, path, caption="📸 **Optics Snapshot captured.**")
            else:
                await self.send_message(chat_id, "📺 Browser Optics not loaded.")

        elif cmd == '/cli':
            if len(parts) > 1:
                command = " ".join(parts[1:])
                shell = next((p for p in self.core.plugins if p.name == "ShellExecutor"), None)
                if shell:
                    output = await shell.execute(command)
                    await self.send_message(chat_id, f"🦾 **Shell Output:**\n\n```\n{output[:3000]}\n```")
            else:
                await self.send_message(chat_id, "Usage: `/cli [powershell command]`")

        elif cmd == '/compact':
            await self.send_message(chat_id, "🧹 **Compacting Session...** Imprinting summary to Aura.")
            history_file = self.core.gateway.history_file
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    lines = f.readlines()[-20:]
                summary = f"Recent Session Summary: {len(lines)} messages compacted."
                await self.core.memory.imprint(summary, {"type": "session_summary"})
                os.remove(history_file)
                await self.send_message(chat_id, "✅ **Compact Complete.** Local memory indexed and chat history cleared.")

        elif cmd == '/leads':
            log_path = os.path.join(self.core.config['paths']['logs'], 'processed_emails.json')
            lead_count = 0
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    lead_count = len(json.load(f))
            await self.send_message(chat_id, f"🎯 **Galactic Lead Recap**\n\n• **Email Leads:** `{lead_count}`\n• **Reddit Gigs:** `Scanning...`\n\nCheck `/status` for plugin health.")

        elif cmd == '/think':
            text, markup = await self.get_think_menu()
            await self.send_message(chat_id, text, reply_markup=markup)
        elif cmd == '/model':
            text, markup = await self.get_model_menu()
            await self.send_message(chat_id, text, reply_markup=markup)
        elif cmd == '/models':
            text, markup = await self.get_models_config_menu()
            await self.send_message(chat_id, text, reply_markup=markup)
        elif cmd == '/help':
            text, markup = await self.get_help_page("1")
            await self.send_message(chat_id, text, reply_markup=markup)
        elif cmd == '/browser':
            if hasattr(self.core, 'gateway'):
                await self.core.gateway.speak("open youtube")

    async def listen_loop(self):
        await self._log("Telegram Bridge: Listening...", priority=1)
        await self.set_commands()
        while self.core.running:
            try:
                updates = await self.get_updates()
                for update in updates:
                    self.offset = update["update_id"] + 1
                    if "callback_query" in update:
                        await self.process_callback(update["callback_query"]["message"]["chat"]["id"], update["callback_query"])
                    elif "message" in update:
                        msg = update["message"]; chat_id = msg["chat"]["id"]; text = msg.get("text", "")
                        # Handle document/file attachments
                        if "document" in msg and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            asyncio.create_task(self._handle_document(chat_id, msg))
                            continue
                        # Handle photo attachments
                        if "photo" in msg and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            asyncio.create_task(self._handle_photo(chat_id, msg))
                            continue
                        # Handle audio/voice attachments
                        if ("voice" in msg or "audio" in msg) and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            asyncio.create_task(self._handle_audio(chat_id, msg))
                            continue
                        # Intercept API key text if we're waiting for one
                        if chat_id in self.pending_api_key and text and not text.startswith('/'):
                            pending = self.pending_api_key.pop(chat_id)
                            api_key = text.strip()
                            await self._save_provider_key(pending["provider"], api_key)
                            self.core.gateway.llm.api_key = api_key
                            self.core.gateway.llm.provider = pending["provider"]
                            self.core.gateway.llm.model = pending["model"]
                            await self.send_message(
                                chat_id,
                                f"✅ API key saved for **{pending['provider'].capitalize()}**! "
                                f"Switched to: `{pending['model']}`"
                            )
                            continue
                        if text.startswith('/'):
                            await self.process_command(chat_id, text)
                            continue
                        await self.send_typing(chat_id)
                        if hasattr(self.core, 'gateway'):
                            asyncio.create_task(self.process_and_respond(chat_id, text))
            except Exception as e:
                await self._log(f"Bridge Loop Error: {e}", priority=1)
            await asyncio.sleep(0.5)

    async def get_updates(self):
        try:
            r = await self.client.get(f"{self.api_url}/getUpdates", params={"offset": self.offset, "timeout": 30})
            return r.json().get("result", []) if r.json().get("ok") else []
        except: return []

    def _get_speak_timeout(self) -> float:
        """Return the speak() timeout for Telegram calls.

        Uses the global speak_timeout from config.models as the authoritative
        ceiling.  The gateway's own asyncio.wait_for() already enforces this
        limit, but Telegram wraps the call in its own wait_for too — if the
        Telegram timeout is shorter than the gateway timeout, the task gets
        killed early even though the agent is still working.

        Priority:
          1. config.models.speak_timeout  (global ceiling — default 600s)
          2. Telegram-specific overrides (only if they are LARGER):
             - ollama_timeout_seconds for local models
             - timeout_seconds for cloud models
        """
        global_timeout = float(
            self.core.config.get('models', {}).get('speak_timeout', 600)
        )
        tg_cfg = self.core.config.get('telegram', {})
        is_ollama = (
            hasattr(self.core, 'gateway') and
            self.core.gateway.llm.provider == 'ollama'
        )
        if is_ollama:
            tg_timeout = float(tg_cfg.get('ollama_timeout_seconds', 600))
        else:
            tg_timeout = float(tg_cfg.get('timeout_seconds', 120))

        # Use whichever is larger — never cut off a task that the gateway
        # is still allowed to work on
        return max(global_timeout, tg_timeout)

    async def _save_provider_key(self, provider: str, api_key: str):
        """Persist an API key for a provider to config.yaml and update in-memory config."""
        try:
            import yaml
            config_path = getattr(self.core, 'config_path', 'config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            # Ensure providers section exists
            if 'providers' not in cfg:
                cfg['providers'] = {}
            if provider not in cfg['providers']:
                cfg['providers'][provider] = {}
            cfg['providers'][provider]['apiKey'] = api_key
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            # Update in-memory config
            if 'providers' not in self.core.config:
                self.core.config['providers'] = {}
            if provider not in self.core.config['providers']:
                self.core.config['providers'][provider] = {}
            self.core.config['providers'][provider]['apiKey'] = api_key
            await self._log(f"Telegram Bridge: Saved API key for {provider}", priority=1)
        except Exception as e:
            await self._log(f"Telegram Bridge: Failed to save API key for {provider}: {e}", priority=1)

    async def process_and_respond(self, chat_id, text):
        typing_task = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            response = await asyncio.wait_for(
                self.core.gateway.speak(text, chat_id=chat_id),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            provider = getattr(self.core.gateway.llm, 'provider', 'unknown')
            model = getattr(self.core.gateway.llm, 'model', 'unknown')
            t = self._get_speak_timeout()
            await self._log(
                f"[Telegram] speak() timed out after {t:.0f}s for chat {chat_id} "
                f"(provider={provider}, model={model})",
                priority=1
            )
            response = (
                f"⏱ Timed out after {t:.0f}s using `{provider}/{model}`.\n\n"
                f"The model or a browser tool is running very slowly. "
                f"Try a simpler task, or switch to a faster model with /model."
            )
        except Exception as e:
            await self._log(f"Processing Error: {e}", priority=1)
            response = f"🌌 **Byte Interference:** `{str(e)}`"
        finally:
            # ALWAYS cancel typing, even on errors
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass  # Ignore any other errors during cleanup
            # Relay to Web UI so Telegram conversations show up in the web chat log
            try:
                await self.core.relay.emit(2, "chat_from_telegram", {
                    "user": str(chat_id),
                    "data": text,
                    "response": response,
                })
            except Exception:
                pass  # Non-fatal — web UI might not be connected
            # Check if the AI used TTS tool — deliver the audio file
            voice_file = getattr(self.core.gateway, 'last_voice_file', None)
            if voice_file and os.path.exists(voice_file):
                try:
                    await self.send_audio(chat_id, voice_file, caption=response[:200] if response else None)
                    self.core.gateway.last_voice_file = None
                except Exception as e:
                    await self._log(f"TTS Delivery Error: {e}", priority=1)
            # Check if the AI generated an image — deliver it via send_photo
            image_file = getattr(self.core.gateway, 'last_image_file', None)
            if image_file and os.path.exists(image_file):
                try:
                    await self.send_photo(chat_id, image_file, caption=f"🎨 {os.path.basename(image_file)}")
                    self.core.gateway.last_image_file = None
                except Exception as e:
                    await self._log(f"Image Delivery Error: {e}", priority=1)
            # Send text response (always — user sees text alongside any audio/image)
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_document(self, chat_id, msg):
        """Download a Telegram document attachment, read its text, and send to the AI."""
        typing_task = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            doc = msg["document"]
            file_name = doc.get("file_name", "unnamed")
            file_size = doc.get("file_size", 0)
            file_id = doc["file_id"]
            caption = msg.get("caption", "")

            # Reject large files (5 MB max)
            if file_size > 5 * 1024 * 1024:
                await self.send_message(chat_id, f"📎 **{file_name}** is too large ({file_size // 1024}KB). Max 5 MB.")
                return

            # Get file path from Telegram
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve file from Telegram.")
                return
            file_path = file_data["result"]["file_path"]

            # Download file content
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            r = await self.client.get(download_url)
            raw = r.content

            # Decode as text
            try:
                text_content = raw.decode('utf-8', errors='replace')
            except Exception:
                text_content = '[Binary file — could not decode as text]'

            # Truncate if huge
            if len(text_content) > 100000:
                text_content = text_content[:100000] + '\n\n... [truncated — file exceeds 100K characters]'

            # Build message for the AI
            full_msg = f"[Attached file: {file_name}]\n---\n{text_content}\n---"
            if caption:
                full_msg += f"\n\n{caption}"

            await self._log(f"[Telegram] User sent file: {file_name} ({file_size} bytes)", priority=2)

            response = await asyncio.wait_for(
                self.core.gateway.speak(full_msg, chat_id=chat_id),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            await self._log(f"[Telegram] Document speak() timed out for chat {chat_id}", priority=1)
            response = "⏱ Took too long processing that file. Please try again."
        except Exception as e:
            await self._log(f"Document Error: {e}", priority=1)
            response = f"🌌 **Byte Interference:** `{str(e)}`"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Relay to Web UI
            try:
                await self.core.relay.emit(2, "chat_from_telegram", {
                    "user": str(chat_id),
                    "data": f"📎 {msg.get('document', {}).get('file_name', 'file')}",
                    "response": response,
                })
            except Exception:
                pass
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_photo(self, chat_id, msg):
        """Download a Telegram photo, analyze it directly with vision, then relay to AI."""
        typing_task = None
        response = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            photo_array = msg["photo"]
            photo = photo_array[-1]  # largest resolution
            file_size = photo.get("file_size", 0)
            file_id = photo["file_id"]
            caption = msg.get("caption", "")

            # Get file path from Telegram
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve photo from Telegram.")
                return
            file_path = file_data["result"]["file_path"]

            # Download raw bytes (no temp file needed)
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            r = await self.client.get(download_url)
            raw = r.content

            await self._log(f"[Telegram] User sent photo: {os.path.basename(file_path)} ({file_size} bytes)", priority=2)

            # Analyze image immediately — no temp file, no race condition
            import base64
            image_b64 = base64.b64encode(raw).decode('utf-8')
            ext = os.path.splitext(file_path)[1].lower() or '.jpg'
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                        '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
            mime_type = mime_map.get(ext, 'image/jpeg')

            vision_prompt = caption if caption else "Describe this image in detail. Include any text you see."
            vision_result = await self.core.gateway._analyze_image_b64(image_b64, mime_type, vision_prompt)

            # Pass vision result to speak() as rich context
            if caption:
                speak_msg = (
                    f"[Image Analysis Result]\n{vision_result}\n\n"
                    f"User's caption/question: {caption}"
                )
            else:
                speak_msg = f"[Image Analysis Result]\n{vision_result}"

            response = await asyncio.wait_for(
                self.core.gateway.speak(speak_msg, chat_id=chat_id),
                timeout=self._get_speak_timeout()
            )
        except asyncio.TimeoutError:
            await self._log(f"[Telegram] Photo speak() timed out for chat {chat_id}", priority=1)
            response = "⏱ Took too long analyzing that image. Please try again."
        except Exception as e:
            await self._log(f"Photo Error: {e}", priority=1)
            response = f"🌌 **Byte Interference (Photo):** `{str(e)}`"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass

            try:
                await self.core.relay.emit(2, "chat_from_telegram", {
                    "user": str(chat_id),
                    "data": f"📸 {msg.get('caption', 'image')}",
                    "response": response,
                })
            except Exception:
                pass
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_audio(self, chat_id, msg):
        """Download a Telegram audio/voice attachment, transcribe it, process, and reply with voice."""
        typing_task = None
        temp_file_path = None
        response = ""
        voice_reply_sent = False
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))

            # Determine if it's a voice or audio message
            audio_data = msg.get("voice") or msg.get("audio")
            if not audio_data:
                await self.send_message(chat_id, "❌ No audio data found.")
                return

            file_size = audio_data.get("file_size", 0)
            file_id = audio_data["file_id"]
            mime_type = audio_data.get("mime_type", "audio/ogg")
            caption = msg.get("caption", "")

            file_extension = ".ogg" if "ogg" in mime_type else ".mp3"

            # Get file path from Telegram
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve audio from Telegram.")
                return
            file_path = file_data["result"]["file_path"]

            # Download file content
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            r = await self.client.get(download_url)
            raw = r.content

            # Save to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file.write(raw)
                temp_file_path = temp_file.name

            await self._log(f"[Telegram] User sent audio: {os.path.basename(temp_file_path)} ({file_size} bytes, {mime_type})", priority=2)

            # ─── Step 1: Transcribe using STT (Whisper/Groq) ───
            transcription = await self._transcribe_audio(temp_file_path)

            if not transcription:
                # Tell the user directly — don't run this through the AI
                has_openai = bool(self.core.config.get('providers', {}).get('openai', {}).get('apiKey', ''))
                has_groq = bool(self.core.config.get('providers', {}).get('groq', {}).get('apiKey', ''))
                if not has_openai and not has_groq:
                    no_key_msg = (
                        "🎤 Voice received, but I can't transcribe it yet.\n\n"
                        "To enable voice messages, add an OpenAI or Groq API key in the Control Deck → Setup Wizard → Step 2.\n\n"
                        "Groq transcription is free: https://console.groq.com/keys"
                    )
                else:
                    no_key_msg = "🎤 Got your voice message, but transcription failed. Please try again."
                voice_reply_sent = True  # prevents double-send in finally block
                await self.send_message(chat_id, no_key_msg)
                return

            full_msg = f"[Voice message from user]: {transcription}"
            if caption:
                full_msg += f"\n{caption}"

            # ─── Step 2: Get AI response ───
            response = await asyncio.wait_for(
                self.core.gateway.speak(full_msg, chat_id=chat_id),
                timeout=self._get_speak_timeout()
            )

            # ─── Step 3: Voice in → Voice out (auto-TTS with male Byte voice) ───
            if transcription and hasattr(self.core, 'gateway'):
                try:
                    tts_result = await self.core.gateway.tool_text_to_speech({
                        'text': response,
                        'voice': 'Byte'  # Male voice (Adam) for voice replies
                    })
                    if '[VOICE]' in str(tts_result):
                        import re
                        m = re.search(r'Generated speech.*?:\s*(.+\.mp3)', str(tts_result))
                        if m:
                            voice_path = m.group(1).strip()
                            if os.path.exists(voice_path):
                                await self.send_audio(chat_id, voice_path, caption=response[:200])
                                voice_reply_sent = True
                except Exception as e:
                    await self._log(f"Auto-TTS voice reply error: {e}", priority=2)

        except asyncio.TimeoutError:
            await self._log(f"[Telegram] Audio speak() timed out for chat {chat_id}", priority=1)
            response = "⏱ Took too long processing that voice message. Please try again."
        except Exception as e:
            await self._log(f"Audio Error: {e}", priority=1)
            response = f"🌌 **Byte Interference (Audio):** `{str(e)}`"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            try:
                await self.core.relay.emit(2, "chat_from_telegram", {
                    "user": str(chat_id),
                    "data": f"🎤 {msg.get('caption', 'voice message')}",
                    "response": response,
                })
            except Exception:
                pass

            # Send text response only if voice reply wasn't already sent
            if not voice_reply_sent:
                try:
                    await self.send_message(chat_id, response)
                except Exception as e:
                    await self._log(f"Send Error: {e}", priority=1)

    async def keep_typing(self, chat_id):
        """Keep sending typing indicator every 4 seconds, scaled to the active model's timeout."""
        max_duration = int(self._get_speak_timeout()) + 30  # always outlasts speak()
        start_time = time.time()
        try:
            while True:
                # Safety timeout check
                if time.time() - start_time > max_duration:
                    await self._log(f"Typing indicator timeout after {max_duration}s", priority=1)
                    break
                await self.send_typing(chat_id)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            # Clean exit when cancelled (expected)
            pass
        except Exception as e:
            # Log any unexpected errors but don't crash
            await self._log(f"Typing indicator error: {e}", priority=1)
