# Galactic AI - Telegram Bridge (Status Plus)
# Drop-in alternative to telegram_bridge.py with enhanced /status telemetry.
#
# Usage:
#   1) Stop Galactic AI / Telegram bridge.
#   2) Rename your current telegram_bridge.py -> telegram_bridge.py.bak
#   3) Copy this file to telegram_bridge.py (or adjust your loader to import this module).
#   4) Start Galactic AI and run /status in Telegram.

import asyncio
import httpx
import json
import os
import traceback
import tempfile
import time
import yaml

def _load_yaml_models(core):
    try:
        yaml_path = os.path.join(core.config.get('paths', {}).get('workspace', '.'), 'config', 'models.yaml')
        if not os.path.exists(yaml_path):
            yaml_path = os.path.join(os.path.dirname(__file__), 'config', 'models.yaml')
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            
        out_map = {}
        for prov, items in data.get('providers', {}).items():
            out_map[prov] = [(i.get('name', i['id']), i['id']) for i in items if i.get('enabled', True)]
        return out_map
    except Exception as e:
        print(f"[Telegram Bridge] Could not load config/models.yaml: {e}")
        return {}

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
        self._active_tasks = []  # Track spawned asyncio tasks for /stop
        self._component = "Telegram"

        # Track model-call telemetry (best-effort)
        self._last_model_call_ts = None
        self._last_model_ok_ts = None
        self._last_model_error_ts = None
        self._last_model_error = None

    def _track_task(self, task):
        """Track an asyncio task so /stop can cancel it."""
        self._active_tasks.append(task)
        task.add_done_callback(lambda t: self._active_tasks.remove(t) if t in self._active_tasks else None)
        return task

    async def _log(self, message, priority=3):
        """Route logs to the Telegram component log file."""
        await self.core.log(message, priority=priority, component=self._component)

    async def set_commands(self):
        commands = [
            {"command": "stop", "description": "🛑 Kill All Running Tasks"},
            {"command": "status", "description": "🛰️ System Telemetry (lite/full)"},
            {"command": "model", "description": "🧠 Shift Brain"},
            {"command": "models", "description": "⚙️ Model Config (Primary/Fallback)"},
            {"command": "browser", "description": "📺 Launch Optics"},
            {"command": "screenshot", "description": "📸 Snap Optics"},
            {"command": "cli", "description": "🦾 Shell Command"},
            {"command": "compact", "description": "🧹 Compact Context"},
            {"command": "clear", "description": "🗑️ Wipe History"},
            {"command": "reset", "description": "🗑️ Wipe History (Alias)"},
            {"command": "leads", "description": "🎯 New Leads"},
            {"command": "help", "description": "📖 Interactive Menu"},
        ]
        try:
            await self.client.post(f"{self.api_url}/setMyCommands", json={"commands": commands})
        except Exception:
            pass

    async def send_message(self, chat_id, text, reply_markup=None):
        if not text:
            return
        chunks = self._split_message(text, limit=4096)
        for chunk in chunks:
            await self._send_single_message(chat_id, chunk, reply_markup)

    async def _send_single_message(self, chat_id, text, reply_markup=None):
        """Send one message chunk, with Markdown fallback on parse failure."""
        try:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = await self.client.post(f"{self.api_url}/sendMessage", json=payload)
            result = resp.json()
            if not result.get("ok"):
                desc = str(result.get("description", ""))
                if "can't parse" in desc.lower() or "parse" in desc.lower():
                    payload.pop("parse_mode", None)
                    resp2 = await self.client.post(f"{self.api_url}/sendMessage", json=payload)
                    result2 = resp2.json()
                    if not result2.get("ok"):
                        await self._log(
                            f"Telegram API error (plain fallback): {result2.get('description', 'unknown')}",
                            priority=1,
                        )
                else:
                    await self._log(f"Telegram API error: {desc}", priority=1)
        except Exception as e:
            await self._log(f"Send message error: {e}", priority=1)

    @staticmethod
    def _split_message(text, limit=4096):
        """Split long text into chunks that fit Telegram's message size limit."""
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            split_at = text.rfind("\n\n", 0, limit)
            if split_at == -1:
                split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = text.rfind(" ", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def send_photo(self, chat_id, photo_path, caption=None):
        try:
            url = f"{self.api_url}/sendPhoto"
            with open(photo_path, "rb") as photo:
                files = {"photo": photo}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Photo Error: {e}", priority=1)

    async def send_audio(self, chat_id, audio_path, caption=None):
        try:
            url = f"{self.api_url}/sendAudio"
            with open(audio_path, "rb") as audio:
                files = {"audio": audio}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1024]
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Audio Error: {e}", priority=1)

    async def send_voice(self, chat_id, voice_path, caption=None):
        """Send an OGG voice message to Telegram."""
        try:
            url = f"{self.api_url}/sendVoice"
            with open(voice_path, "rb") as voice:
                files = {"voice": voice}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1024]
                await self.client.post(url, data=data, files=files)
        except Exception as e:
            await self._log(f"Telegram Voice Error: {e}", priority=1)

    async def _transcribe_audio(self, audio_path):
        """Transcribe audio using OpenAI Whisper API (preferred) or return None."""
        openai_key = self.core.config.get('providers', {}).get('openai', {}).get('apiKey', '')
        if openai_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.openai.com/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {openai_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-1'},
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[STT] Whisper transcribed: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"Whisper STT error: {e}", priority=2)

        groq_key = self.core.config.get('providers', {}).get('groq', {}).get('apiKey', '')
        if groq_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(audio_path, 'rb') as f:
                        r = await client.post(
                            'https://api.groq.com/openai/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {groq_key}'},
                            files={'file': (os.path.basename(audio_path), f, 'audio/ogg')},
                            data={'model': 'whisper-large-v3'},
                        )
                    if r.status_code == 200:
                        text = r.json().get('text', '').strip()
                        if text:
                            await self._log(f"[STT] Groq Whisper transcribed: {text[:80]}...", priority=2)
                            return text
            except Exception as e:
                await self._log(f"Groq STT error: {e}", priority=2)

        return None

    async def send_typing(self, chat_id):
        try:
            await self.client.post(
                f"{self.api_url}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}
            )
        except Exception:
            pass

    async def get_help_page(self, page):
        if page == "1":
            text = "🌌 **Commands (1/5) - System** 🛰️\n• `/status` - System Telemetry (lite)\n• `/status full` - System Telemetry (full)\n• `/model` - Brain\n• `/uptime` - Engine"
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
        defaults = [("Qwen3 30B 🤖", "qwen3:30b"), ("Qwen3 8B ⚡️", "qwen3:8b"), ("Qwen3 Coder 30B 🦾", "qwen3-coder:30b")]
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

            # Separate Aliases category (config.yaml -> aliases:)
            if self.core.config.get('aliases'):
                buttons.append([{ "text": "Aliases 🧷", "callback_data": "prov_aliases" }])

            row = []
            providers = self.core.config.get('providers', {})
            for p_name in providers:
                row.append({"text": f"{p_name.capitalize()}", "callback_data": f"prov_{p_name}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            return text, {"inline_keyboard": buttons}

        # Aliases submenu
        if provider == 'aliases':
            aliases = self.core.config.get('aliases', {}) or {}

            # Interpret alias targets.
            # We treat values like "openai/gpt-..." as OpenRouter model IDs by default.
            explicit_prefixes = {
                'openrouter',
                'ollama', 'nvidia', 'xai', 'groq', 'mistral', 'cerebras',
                'deepseek', 'huggingface', 'kimi', 'zai', 'minimax'
            }

            def _sort_key(item):
                k, v = item
                s = f"{k} {v}".lower()
                return (0 if 'nitro' in s else 1, k.lower())

            items = sorted(list(aliases.items()), key=_sort_key)

            text = "🧷 **Aliases**\nQuick-switch shortcuts from `config.yaml` → `aliases:`"
            buttons = []
            row = []

            for alias_name, target in items[:40]:
                t = str(target).strip()

                # Explicit provider form: provider/model...
                if '/' in t:
                    first, rest = t.split('/', 1)
                    if first in explicit_prefixes:
                        prov, mod = first, rest
                    else:
                        # Default: treat as OpenRouter model namespace
                        prov, mod = 'openrouter', t
                else:
                    # Model-only alias: default to OpenRouter
                    prov, mod = 'openrouter', t

                row.append({"text": str(alias_name), "callback_data": f"mod_{prov}|{mod}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []

            if row:
                buttons.append(row)

            buttons.append([{"text": "⬅️ Back to Providers", "callback_data": "mod_back"}])
            return text, {"inline_keyboard": buttons}

        text = f"🧠 **{provider.capitalize()} Cluster**\nSelect a specific brain to activate:"
        buttons = []
        model_map = _load_yaml_models(self.core)
        
        if provider == 'ollama':
            models = self._get_live_ollama_menu_entries()
        else:
            models = model_map.get(provider, [])
        row = []
        for label, m_id in models:
            row.append({"text": label, "callback_data": f"mod_{provider}|{m_id}"})
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([{"text": "⬅️ Back to Providers", "callback_data": "mod_back"}])
        return text, {"inline_keyboard": buttons}

    async def get_models_config_menu(self, config_type=None, provider=None):
        if not config_type:
            mm = self.core.model_manager
            models_cfg = self.core.config.get('models', {})
            current = mm.get_current_model()
            mode_indicator = "🟢" if current['mode'] == 'primary' else "🟡"
            text = (
                f"⚙️ **Model Configuration**\n\n"
                f"{mode_indicator} **Active:** {current['provider']}/{current['model']} ({current['mode']})\n\n"
                f"🎯 **Primary (Builder):** {mm.primary_provider}/{mm.primary_model}\n"
                f"🔄 **Fallback:** {mm.fallback_provider}/{mm.fallback_model}\n"
                f"🧠 **Planner:** {models_cfg.get('planner_provider', 'openrouter')}/{models_cfg.get('planner_model', 'openai/gpt-5.2')}\n"
                f"🛡️ **Planner Fallback:** {models_cfg.get('planner_fallback_provider', 'openrouter')}/{models_cfg.get('planner_fallback_model', 'openai/gpt-5.2-codex')}\n\n"
                f"**Auto-Fallback:** {'✅ Enabled' if mm.auto_fallback_enabled else '❌ Disabled'}\n"
                f"**Error Threshold:** {mm.error_threshold}\n"
                f"**Recovery Time:** {mm.recovery_time}s\n\n"
                f"Choose what to configure:"
            )
            buttons = [
                [{"text": "🎯 Set Primary (Builder)", "callback_data": "cfg_primary"}],
                [{"text": "🧠 Set Planner (Big Brain)", "callback_data": "cfg_planner"}],
                [{"text": "🛡️ Set Planner Fallback", "callback_data": "cfg_planner_fallback"}],
                [{"text": "🔄 Set Fallback Model", "callback_data": "cfg_fallback"}],
                [{"text": "🔄 Switch to Primary", "callback_data": "cfg_switch_primary"}],
                [{"text": "🟡 Switch to Fallback", "callback_data": "cfg_switch_fallback"}],
                [{"text": "⚙️ Toggle Auto-Fallback", "callback_data": "cfg_toggle_auto"}],
            ]
            return text, {"inline_keyboard": buttons}

        elif config_type == "provider":
            text = f"⚙️ **Select Provider for {provider.upper()}**"
            buttons = []
            row = []
            providers = self.core.config.get('providers', {})
            for p_name in providers:
                row.append({"text": f"{p_name.capitalize()}", "callback_data": f"cfg_{provider}_prov_{p_name}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([{"text": "⬅️ Back", "callback_data": "cfg_back"}])
            return text, {"inline_keyboard": buttons}

        elif config_type == "model":
            setting_type = provider.split("_")[0]
            provider_name = provider.split("_")[-1]
            text = f"⚙️ **Select Model from {provider_name.capitalize()}**\nSetting as **{setting_type.upper()}** model"
            model_map = _load_yaml_models(self.core)
            if provider_name == 'ollama':
                models = self._get_live_ollama_menu_entries()
            else:
                models = model_map.get(provider_name, [])
            buttons = []
            row = []
            for label, m_id in models:
                row.append({"text": label, "callback_data": f"cfg_{setting_type}_set_{provider_name}|{m_id}"})
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([{"text": "⬅️ Back", "callback_data": f"cfg_{setting_type}"}])
            return text, {"inline_keyboard": buttons}

    async def process_callback(self, chat_id, callback_query):
        data = callback_query.get("data", "")
        await self.client.post(f"{self.api_url}/answerCallbackQuery", json={"callback_query_id": callback_query["id"]})
        message_id = callback_query["message"]["message_id"]
        if data.startswith("help_"):
            page = data.split("_")[1]
            text, markup = await self.get_help_page(page)
            await self.client.post(
                f"{self.api_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
            )
        elif data.startswith("prov_"):
            provider = data.split("_")[1]
            text, markup = await self.get_model_menu(provider=provider)
            await self.client.post(
                f"{self.api_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
            )
        elif data == "mod_back":
            text, markup = await self.get_model_menu()
            await self.client.post(
                f"{self.api_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
            )
        elif data.startswith("think_"):
            level = data.split("_")[1].upper()
            self.thinking_level = level
            text, markup = await self.get_think_menu()
            await self.client.post(
                f"{self.api_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": f"✅ Thinking: `{level}`\n\n{text}", "reply_markup": markup, "parse_mode": "Markdown"},
            )
        elif data.startswith("mod_"):
            provider, model = data.split("_")[1].split("|")
            if provider.startswith('openrouter-'):
                provider = 'openrouter'
            self.core.gateway.llm.provider = provider
            self.core.gateway.llm.model = model
            if hasattr(self.core, 'model_manager'):
                self.core.model_manager._set_api_key(provider)
            current_key = getattr(self.core.gateway.llm, 'api_key', '')
            if provider != 'ollama' and (not current_key or current_key == 'NONE'):
                self.pending_api_key[chat_id] = {"provider": provider, "model": model}
                await self.send_message(
                    chat_id,
                    f"🔑 **API Key Required**\n\nNo API key configured for **{provider.capitalize()}**.\nPlease paste your API key now and I'll save it:",
                )
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": f"⏳ Waiting for {provider.capitalize()} API key...", "parse_mode": "Markdown"},
                )
            else:
                await self.send_message(chat_id, f"✅ **Shifted to {provider.capitalize()}:** `{model}`")
                text, markup = await self.get_model_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
        elif data.startswith("cfg_"):
            if data == "cfg_primary":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="primary")
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_fallback":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="fallback")
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_planner":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="planner")
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_planner_fallback":
                text, markup = await self.get_models_config_menu(config_type="provider", provider="planner_fallback")
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data.startswith("cfg_primary_prov_") or data.startswith("cfg_fallback_prov_") or data.startswith("cfg_planner_prov_") or data.startswith("cfg_planner_fallback_prov_"):
                # E.g. cfg_planner_fallback_prov_openrouter -> parts: ['cfg', 'planner', 'fallback', 'prov', 'openrouter']
                # Let's handle it more robustly
                prefix = "cfg_"
                rest = data[len(prefix):]
                # rest is like "primary_prov_openai" or "planner_fallback_prov_openrouter"
                _type, _prov = rest.rsplit("_prov_", 1)
                text, markup = await self.get_models_config_menu(config_type="model", provider=f"{_type}_prov_{_prov}")
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data.startswith("cfg_primary_set_") or data.startswith("cfg_fallback_set_") or data.startswith("cfg_planner_set_") or data.startswith("cfg_planner_fallback_set_"):
                prefix = "cfg_"
                rest = data[len(prefix):]
                setting_type, provider_and_model = rest.rsplit("_set_", 1)
                provider_name, model_id = provider_and_model.split("|")
                if provider_name.startswith('openrouter-'):
                    provider_name = 'openrouter'
                if setting_type == "primary":
                    await self.core.model_manager.set_primary(provider_name, model_id)
                    await self.send_message(chat_id, f"✅ **Primary model set:** {provider_name}/{model_id}\nNow active!")
                elif setting_type == "fallback":
                    await self.core.model_manager.set_fallback(provider_name, model_id)
                    await self.send_message(chat_id, f"✅ **Fallback model set:** {provider_name}/{model_id}")
                elif setting_type in ("planner", "planner_fallback"):
                    cfg = self.core.config
                    cfg.setdefault('models', {})
                    if setting_type == "planner":
                        cfg['models']['planner_provider'] = provider_name
                        cfg['models']['planner_model'] = model_id
                        await self.send_message(chat_id, f"✅ **Planner model set:** {provider_name}/{model_id}")
                    else:
                        cfg['models']['planner_fallback_provider'] = provider_name
                        cfg['models']['planner_fallback_model'] = model_id
                        await self.send_message(chat_id, f"✅ **Fallback Planner model set:** {provider_name}/{model_id}")
                    # Trigger save
                    if hasattr(self.core.gateway, '_save_config'):
                        self.core.gateway._save_config(cfg)
                    elif hasattr(self.core, 'web_deck'):
                        self.core.web_deck._save_config(cfg)
                text, markup = await self.get_models_config_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_switch_primary":
                await self.core.model_manager.switch_to_primary()
                await self.send_message(chat_id, "✅ **Switched to PRIMARY model**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_switch_fallback":
                await self.core.model_manager.switch_to_fallback(reason="Manual switch")
                await self.send_message(chat_id, "✅ **Switched to FALLBACK model**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_toggle_auto":
                self.core.model_manager.auto_fallback_enabled = not self.core.model_manager.auto_fallback_enabled
                status = "enabled" if self.core.model_manager.auto_fallback_enabled else "disabled"
                await self.send_message(chat_id, f"✅ **Auto-fallback {status}**")
                text, markup = await self.get_models_config_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )
            elif data == "cfg_back":
                text, markup = await self.get_models_config_menu()
                await self.client.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup, "parse_mode": "Markdown"},
                )

    # -------------------------
    # /status helpers (safe)
    # -------------------------

    @staticmethod
    def _fmt_age(ts):
        if not ts:
            return "never"
        try:
            delta = max(0, int(time.time() - float(ts)))
            if delta < 60:
                return f"{delta}s ago"
            if delta < 3600:
                return f"{delta // 60}m {delta % 60}s ago"
            return f"{delta // 3600}h {(delta % 3600) // 60}m ago"
        except Exception:
            return "unknown"

    @staticmethod
    def _safe_len_text(obj):
        if obj is None:
            return 0
        if isinstance(obj, str):
            return len(obj)
        try:
            return len(str(obj))
        except Exception:
            return 0

    @staticmethod
    def _segment_value_is_unknown(seg: str) -> bool:
        """Return True if a status line/segment's value is 'unknown' (best-effort).

        Works for:
          - "🧾 System Prompt: unknown"
          - "🧾 **System Prompt:** `unknown`"
          - pipe segments: "🧾 X: unknown" inside "A: unknown | B: 123"
        """
        try:
            if seg is None:
                return False
            s = str(seg).strip()
            if not s:
                return False

            # Strip common Markdown wrappers
            s = s.replace('`', '')
            s = s.replace('**', '')
            s = s.replace('*', '')
            s = s.strip()

            # Compare value portion if it's a key/value line
            if ':' in s:
                v = s.split(':', 1)[1].strip()
            else:
                v = s.strip()

            return v.lower() == 'unknown'
        except Exception:
            return False

    def _filter_unknown_from_status_report(self, text: str) -> str:
        """Remove any lines (or pipe segments) whose value is 'unknown'.

        Also removes now-empty section headers and collapses duplicate separators.
        """
        if not text:
            return text

        lines = str(text).splitlines()
        out = []

        # Pass 1: drop unknown lines; prune unknown segments inside pipe-delimited lines
        for line in lines:
            raw = line
            s = raw.strip()

            if not s:
                out.append(raw)
                continue

            # Keep separators always (we'll collapse duplicates later)
            if '━━━━━━━━' in s:
                out.append(raw)
                continue

            if '|' in raw:
                parts = [p.strip() for p in raw.split('|')]
                kept = [p for p in parts if not self._segment_value_is_unknown(p)]
                if not kept:
                    continue
                out.append(' | '.join(kept))
                continue

            if self._segment_value_is_unknown(raw):
                continue

            out.append(raw)

        # Pass 2: remove empty "Enhanced Telemetry" header (or similar) if it became empty
        cleaned = []
        i = 0
        while i < len(out):
            line = out[i]
            s = line.strip()
            headerish = s.replace('*', '').strip().lower() in (
                'enhanced telemetry',
                'telemetry',
            )
            if headerish:
                # Find next meaningful line
                j = i + 1
                while j < len(out) and not out[j].strip():
                    j += 1
                if j >= len(out) or '━━━━━━━━' in out[j]:
                    i += 1
                    continue
            cleaned.append(line)
            i += 1

        # Pass 3: collapse duplicate separators and trim leading/trailing blank lines
        final = []
        last_sep = False
        for line in cleaned:
            s = line.strip()
            is_sep = bool(s) and ('━━━━━━━━' in s)
            if is_sep and last_sep:
                continue
            final.append(line)
            last_sep = is_sep

        # Trim
        while final and not final[0].strip():
            final.pop(0)
        while final and not final[-1].strip():
            final.pop()

        return '\n'.join(final)

    def _get_hot_buffer_stats_from_file(self):
        """Best-effort read of hot buffer JSON file to compute raw + injected context sizes.

        Returns:
            dict: {
              raw_msg_count, raw_chars,
              injected_msg_count, injected_chars,
              path
            }
        """
        out = {
            "raw_msg_count": 0,
            "raw_chars": 0,
            "injected_msg_count": 0,
            "injected_chars": 0,
            "path": None,
        }
        try:
            cfg = self.core.config
            hb_path = (
                cfg.get('memory', {}).get('hot_buffer_file')
                or cfg.get('paths', {}).get('hot_buffer')
                or cfg.get('paths', {}).get('hot_buffer_file')
            )
            if not hb_path or not os.path.exists(hb_path):
                return out
            out["path"] = hb_path

            # The file is usually small-ish; still: load it safely.
            with open(hb_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Common formats:
            #  - list[ {role, content, ...}, ... ]
            #  - dict{ messages: [...], ... }
            if isinstance(data, dict) and isinstance(data.get('messages'), list):
                msgs = data.get('messages')
            elif isinstance(data, list):
                msgs = data
            else:
                msgs = []

            out["raw_msg_count"] = len(msgs)
            raw_chars = 0
            for m in msgs:
                if isinstance(m, dict):
                    raw_chars += len(str(m.get('content', '')))
                else:
                    raw_chars += len(str(m))
            out["raw_chars"] = raw_chars

            # Injected context = last N messages pushed into the prompt
            max_recent = (
                int(cfg.get('telemetry', {}).get('max_recent_messages', 100) or 100)
                or int(cfg.get('llm', {}).get('max_context_messages', 100) or 100)
            )
            tail = msgs[-max_recent:] if max_recent > 0 else msgs
            out["injected_msg_count"] = len(tail)
            injected_chars = 0
            for m in tail:
                if isinstance(m, dict):
                    injected_chars += len(str(m.get('content', '')))
                else:
                    injected_chars += len(str(m))
            out["injected_chars"] = injected_chars
        except Exception:
            # Stay silent; /status must never crash.
            return out
        return out

    def _get_system_prompt_chars(self):
        """Best-effort estimate of the system prompt size (chars)."""
        candidates = []
        try:
            gw = getattr(self.core, 'gateway', None)
            if gw is not None:
                for attr in (
                    'system_prompt',
                    'system_prompt_text',
                    'base_system_prompt',
                    'system_message',
                    'SYSTEM_PROMPT',
                ):
                    if hasattr(gw, attr):
                        candidates.append(getattr(gw, attr))
                # Sometimes it's on the LLM object
                llm = getattr(gw, 'llm', None)
                if llm is not None:
                    for attr in ('system_prompt', 'system_message'):
                        if hasattr(llm, attr):
                            candidates.append(getattr(llm, attr))
        except Exception:
            pass

        # Config fallback
        try:
            sys_cfg = self.core.config.get('system', {})
            for k in ('prompt', 'system_prompt'):
                if k in sys_cfg:
                    candidates.append(sys_cfg.get(k))
        except Exception:
            pass

        for c in candidates:
            if isinstance(c, str) and c.strip():
                return len(c)
        return None

    def _get_tools_schema_chars(self):
        """Best-effort size of the tools schema as JSON (chars). Returns None if not available."""
        try:
            # Try common registry/manager shapes
            for obj_name in ('tool_manager', 'tools', 'tool_registry', 'registry'):
                obj = getattr(self.core, obj_name, None)
                if not obj:
                    continue

                # Method candidates
                for meth in (
                    'get_tools_schema',
                    'get_openai_tools',
                    'get_tools',
                    'schema',
                    'export_schema',
                ):
                    if hasattr(obj, meth) and callable(getattr(obj, meth)):
                        try:
                            schema = getattr(obj, meth)()
                            s = json.dumps(schema, ensure_ascii=False)
                            return len(s)
                        except TypeError:
                            # Some methods require args; skip
                            continue
                        except Exception:
                            continue

                # Attribute candidates
                for attr in ('schema', 'tools', 'tool_definitions'):
                    if hasattr(obj, attr):
                        try:
                            schema = getattr(obj, attr)
                            s = json.dumps(schema, ensure_ascii=False)
                            return len(s)
                        except Exception:
                            continue

        except Exception:
            pass
        return None

    def _get_context_limit_tokens(self, provider: str, model: str):
        """Best-effort model context window (tokens). Returns None if unknown.

        We prefer any project-provided mapping. If not available, we avoid guessing wildly.
        """
        try:
            mm = getattr(self.core, 'model_manager', None)
            if mm:
                for meth in ('get_context_limit', 'get_model_context_limit', 'context_limit_for'):
                    if hasattr(mm, meth) and callable(getattr(mm, meth)):
                        try:
                            v = getattr(mm, meth)(provider, model)
                            if isinstance(v, (int, float)) and v > 0:
                                return int(v)
                        except Exception:
                            pass
                # Mapping attributes
                for attr in ('context_limits', 'context_windows', 'model_context_limits'):
                    m = getattr(mm, attr, None)
                    if isinstance(m, dict):
                        v = m.get(f"{provider}/{model}") or m.get(model)
                        if isinstance(v, (int, float)) and v > 0:
                            return int(v)
        except Exception:
            pass

        # Config fallback if present
        try:
            llm_cfg = self.core.config.get('llm', {})
            for k in ('context_window_tokens', 'context_limit_tokens', 'max_context_tokens'):
                v = llm_cfg.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
        except Exception:
            pass

        return None

    def _pluck_gateway_last_error(self):
        gw = getattr(self.core, 'gateway', None)
        if not gw:
            return None
        for attr in ('last_error', 'last_exception', 'error', 'last_fail_reason'):
            try:
                v = getattr(gw, attr, None)
                if v:
                    return str(v)
            except Exception:
                pass
        return None

    def _pluck_gateway_last_call_ts(self):
        gw = getattr(self.core, 'gateway', None)
        if not gw:
            return None
        for attr in (
            'last_call_ts',
            'last_request_ts',
            'last_request_time',
            'last_model_call_ts',
            'last_llm_call_ts',
        ):
            try:
                v = getattr(gw, attr, None)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v)
            except Exception:
                pass
        return None

    async def process_command(self, chat_id, cmd_text):
        parts = cmd_text.split()
        cmd = parts[0].lower().split('@')[0]

        if cmd == '/stop':
            cancelled = 0
            for task in list(self._active_tasks):
                if not task.done():
                    task.cancel()
                    cancelled += 1
            self._active_tasks.clear()
            if hasattr(self.core, 'gateway') and hasattr(self.core.gateway, '_cancel_active'):
                try:
                    self.core.gateway._cancel_active()
                except Exception:
                    pass
            await self.send_message(chat_id, f"🛑 **All Stop.** Killed {cancelled} running task(s).\nStanding by in neutral.")
            await self._log(f"[Telegram] /stop: cancelled {cancelled} tasks", priority=1)
            return

        if cmd == '/status':
            # /status args: default lite; add 'full' / '--full' / '-f' for expanded telemetry
            args = [a.strip().lower() for a in parts[1:]]
            full_mode = any(a in ('--full', 'full', '-f') for a in args)

            try:
                from datetime import datetime

                uptime = int(time.time() - self.start_time)
                now = datetime.now().strftime("%H:%M:%S")

                # System/config fields (safe)
                try:
                    sys_cfg = self.core.config.get('system', {})
                    version = str(sys_cfg.get('version', '?'))
                    mode = str(sys_cfg.get('mode', 'PRIMARY')).upper()
                    tz = str(sys_cfg.get('timezone', 'local'))
                except Exception:
                    version, mode, tz = '?', 'PRIMARY', 'local'

                # Plugins list (safe)
                plugins_list = []
                try:
                    plugins_obj = getattr(self.core, 'plugins', []) or []
                    for p in plugins_obj:
                        name = getattr(p, 'name', None) or getattr(p, '__class__', type('x', (), {})).__name__
                        plugins_list.append(str(name))
                except Exception:
                    plugins_list = []
                plugins_display = ", ".join(plugins_list) if plugins_list else "unknown"

                # Skills list (safe)
                skills_list = []
                try:
                    skills_obj = getattr(self.core, 'skills', []) or []
                    for s in skills_obj:
                        nm = getattr(s, 'skill_name', None) or getattr(s, 'name', None) or getattr(s, '__class__', type('x', (), {})).__name__
                        skills_list.append(str(nm))
                except Exception:
                    skills_list = []
                skills_display = ", ".join(skills_list) if skills_list else "unknown"

                # Memory (imprints) count (safe — handles any memory structure)
                try:
                    mem = getattr(self.core, 'memory', None)
                    if mem is None:
                        mems = 0
                    elif hasattr(mem, 'index') and isinstance(mem.index, dict):
                        mems = len(mem.index.get('memories', []))
                    elif hasattr(mem, 'search'):
                        mems = len(mem.search('', top_k=9999) or [])
                    elif hasattr(mem, '__len__'):
                        mems = len(mem)
                    else:
                        mems = 0
                except Exception:
                    mems = 0

                # Session name (safe)
                try:
                    session_name = self.core.config.get('telemetry', {}).get('session_name', 'galactic:main')
                except Exception:
                    session_name = 'galactic:main'

                # Gateway history count (safe)
                try:
                    gw_hist = len(getattr(self.core.gateway, 'history', []) or [])
                except Exception:
                    gw_hist = 0

                # Model info (safe)
                try:
                    active_provider = self.core.gateway.llm.provider
                    active_model = self.core.gateway.llm.model
                except Exception:
                    active_provider = "unknown"
                    active_model = "unknown"

                # Configured primary/fallback mode indicator (safe)
                try:
                    configured_model = self.core.model_manager.get_current_model()
                    mode_indicator = "🟢" if configured_model['mode'] == 'primary' else "🟡"
                    configured_mode = configured_model['mode'].upper()
                    model_display = f"{active_provider}/{active_model}"
                    if (active_provider != configured_model['provider'] or active_model != configured_model['model']):
                        model_display += f" (Shifted from {configured_model['provider']}/{configured_model['model']})"
                except Exception:
                    mode_indicator = "🟢"
                    configured_mode = mode
                    model_display = f"{active_provider}/{active_model}"

                # Token counts (safe)
                try:
                    tok_in = self.core.gateway.total_tokens_in / 1000
                    tok_out = self.core.gateway.total_tokens_out / 1000
                except Exception:
                    tok_in = 0.0
                    tok_out = 0.0

                # Cost tracking (safe)
                cost_info = ""
                try:
                    if hasattr(self.core, 'cost_tracker'):
                        stats = self.core.cost_tracker.get_stats()
                        today = stats.get('today_cost', 0.0)
                        month = stats.get('month_cost', 0.0)
                        cost_info = f"💰 **Cost:** `${today:.2f} today` / `${month:.2f} month`\n"
                except Exception:
                    pass

                # Live context (archiver tool if available + file stats)
                live_ctx_msgs = None
                live_ctx_chars = None
                hot_path = None
                try:
                    arch = None
                    try:
                        arch = next(
                            (s for s in getattr(self.core, 'skills', []) if getattr(s, 'skill_name', '') == 'conversation_archiver'),
                            None,
                        )
                    except Exception:
                        arch = None

                    if arch and hasattr(arch, 'tool_conversation_get_hot'):
                        hot = await arch.tool_conversation_get_hot({"limit": 1})
                        live_ctx_msgs = int(hot.get('message_count', 0) or 0)
                        live_ctx_chars = int(hot.get('total_chars', 0) or 0)
                        hot_path = str(hot.get('hot_buffer', '') or '')
                except Exception:
                    pass

                file_ctx = self._get_hot_buffer_stats_from_file()
                # Prefer archiver-reported path; otherwise file path
                hot_path = hot_path or file_ctx.get('path')

                # Split context: injected vs raw
                injected_msgs = file_ctx.get('injected_msg_count') or None
                injected_chars = file_ctx.get('injected_chars') or None
                raw_msgs = file_ctx.get('raw_msg_count') or None
                raw_chars = file_ctx.get('raw_chars') or None

                # If archiver gave us totals, treat those as raw totals.
                if live_ctx_msgs is not None:
                    raw_msgs = live_ctx_msgs
                if live_ctx_chars is not None:
                    raw_chars = live_ctx_chars

                # Prompt + tools sizing
                system_prompt_chars = self._get_system_prompt_chars()
                tools_schema_chars = self._get_tools_schema_chars()

                # Context window + % used
                context_limit_tokens = self._get_context_limit_tokens(active_provider, active_model)
                # Estimate tokens used from injected chars (most relevant to prompt) if present, else raw
                basis_chars = injected_chars if isinstance(injected_chars, int) and injected_chars > 0 else (raw_chars or 0)
                est_tokens_used = int(basis_chars / 4) if basis_chars else 0
                pct_used = None
                if context_limit_tokens and context_limit_tokens > 0:
                    pct_used = (est_tokens_used / context_limit_tokens) * 100

                # Last model call + last error
                gw_last_call = self._pluck_gateway_last_call_ts()
                if gw_last_call:
                    self._last_model_call_ts = gw_last_call

                gw_last_error = self._pluck_gateway_last_error()
                if gw_last_error:
                    self._last_model_error = gw_last_error

                last_call_age = self._fmt_age(self._last_model_call_ts)
                last_ok_age = self._fmt_age(self._last_model_ok_ts)
                last_err_age = self._fmt_age(self._last_model_error_ts)

                # Condition
                condition = "Nominal"
                if self._last_model_error and (self._last_model_error_ts and time.time() - self._last_model_error_ts < 600):
                    condition = "Degraded"

                if not full_mode:
                    lite = (
                        f"🌌 **GALACTIC AI STATUS**\n"
                        f"⏰ **Time:** `{now}` ({tz}) | 🛸 **Version:** `{version}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{mode_indicator} **Model:** `{model_display}`\n"
                        f"🔄 **Configured Mode:** `{configured_mode}` | ⚙️ **System Mode:** `{mode}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧮 **Tokens:** `{tok_in:.1f}k in` / `{tok_out:.1f}k out`\n"
                        f"{cost_info}"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🛰️ **Uptime:** `{uptime}s` | **PID:** `{os.getpid()}`\n"
                        f"✨ **Condition:** `{condition}`\n"
                        f"\nUse `/status full` for the expanded telemetry dump."
                    )
                    lite = self._filter_unknown_from_status_report(lite)
                    await self.send_message(chat_id, lite)
                    return

                # Build report
                ctx_lines = ""
                if raw_msgs is not None and raw_chars is not None:
                    ctx_lines += f"🧠 **Live Context (raw):** `{raw_msgs} msgs` | `{int(raw_chars):,} chars`\n"
                if injected_msgs is not None and injected_chars is not None:
                    ctx_lines += f"🧬 **Injected Recent Context:** `{injected_msgs} msgs` | `{int(injected_chars):,} chars`\n"
                if hot_path:
                    ctx_lines += f"🗃️ **Hot Buffer:** `{hot_path}`\n"

                prompt_lines = ""
                if system_prompt_chars is not None:
                    prompt_lines += f"🧾 **System Prompt:** `{system_prompt_chars:,} chars`\n"
                else:
                    prompt_lines += f"🧾 **System Prompt:** `unknown`\n"

                if tools_schema_chars is not None:
                    prompt_lines += f"🧰 **Tools Schema:** `{tools_schema_chars:,} chars`\n"
                else:
                    prompt_lines += f"🧰 **Tools Schema:** `unknown`\n"

                window_lines = ""
                if context_limit_tokens:
                    if pct_used is not None:
                        window_lines += f"📏 **Context Window:** `{context_limit_tokens:,} tok` | **Est Used:** `{est_tokens_used:,} tok` (`{pct_used:.1f}%`)\n"
                    else:
                        window_lines += f"📏 **Context Window:** `{context_limit_tokens:,} tok` | **Est Used:** `{est_tokens_used:,} tok`\n"
                else:
                    window_lines += f"📏 **Context Window:** `unknown` | **Est Used:** `{est_tokens_used:,} tok`\n"

                last_lines = (
                    f"🕒 **Last Model Call:** `{last_call_age}`\n"
                    f"✅ **Last OK:** `{last_ok_age}`\n"
                    f"❌ **Last Error:** `{last_err_age}`\n"
                )
                if self._last_model_error:
                    # Keep it short; no stack dumps
                    err = str(self._last_model_error)
                    if len(err) > 240:
                        err = err[:240] + "…"
                    last_lines += f"🧯 **Error Detail:** `{err}`\n"

                report = (
                    f"🌌 **GALACTIC AI SYSTEM STATUS** 🚀\n"
                    f"⏰ **Time:** `{now}` ({tz}) | 🛸 **Version:** `{version}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{mode_indicator} **Model:** `{model_display}`\n"
                    f"🔄 **Configured Mode:** `{configured_mode}` | ⚙️ **System Mode:** `{mode}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧮 **Tokens:** `{tok_in:.1f}k in` / `{tok_out:.1f}k out`\n"
                    f"{cost_info}"
                    f"📚 **Imprints:** `{mems}` | 🧵 **Session:** `{session_name}`\n"
                    f"🧾 **Gateway History:** `{gw_hist} msgs`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**Enhanced Telemetry**\n"
                    f"{ctx_lines}"
                    f"{prompt_lines}"
                    f"{window_lines}"
                    f"{last_lines}"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🛰️ **Uptime:** `{uptime}s` | **PID:** `{os.getpid()}`\n"
                    f"⚙️ **Runtime:** `Direct AsyncIO` | **Think:** `{self.thinking_level}`\n"
                    f"🧩 **Plugins:** `{plugins_display}`\n"
                    f"🧠 **Skills:** `{skills_display}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✨ **Condition:** `{condition}` ⚡️"
                )

                report = self._filter_unknown_from_status_report(report)
                await self.send_message(chat_id, report)
            except Exception as e:
                await self._log(f"/status error: {e}", priority=1)
                await self.send_message(chat_id, f"🛰️ Status check failed: `{e}`")

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
            try:
                # Determine history file path safely
                history_file = getattr(self.core.gateway, 'history_file', None)
                if not history_file or not os.path.exists(history_file):
                    # Fallback: try to find it in config
                    history_file = self.core.config.get('paths', {}).get('history', 
                                   os.path.join(self.core.config.get('paths', {}).get('logs', './logs'), 'conversation_history.json'))
                
                if os.path.exists(history_file):
                    with open(history_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    # Keep last 20 messages for summary context
                    recent_lines = lines[-20:] if len(lines) > 20 else lines
                    recent_text = "".join(recent_lines)
                    
                    # Create summary
                    summary_text = f"[Session Compact {time.strftime('%Y-%m-%d %H:%M')}] Previous conversation summarized: {recent_text[:500]}..."
                    
                    # Save to long-term memory
                    if hasattr(self.core, 'memory') and hasattr(self.core.memory, 'imprint'):
                        await self.core.memory.imprint(summary_text, {"type": "session_summary"})
                    
                    # Rewrite history file with ONLY the summary (preserves file, clears context)
                    summary_line = json.dumps({"role": "system", "content": f"Session compacted. Summary: {summary_text}"}) + "\n"
                    with open(history_file, 'w', encoding='utf-8') as f:
                        f.write(summary_line)
                    
                    # Reset gateway history if possible
                    if hasattr(self.core.gateway, 'history'):
                        self.core.gateway.history = []
                    
                    await self.send_message(chat_id, f"✅ **Compact Complete.** Summarized {len(lines)} messages into Aura. History reset.")
                else:
                    await self.send_message(chat_id, "ℹ️ No history file found. Nothing to compact.")
            except Exception as e:
                await self._log(f"/compact error: {e}", priority=1)
                await self.send_message(chat_id, f"❌ **Compact Failed:** `{e}`")

        elif cmd == '/clear' or cmd == '/reset':
            await self.send_message(chat_id, "🧹 **Clearing Session...**")
            try:
                # Determine history file path safely
                history_file = getattr(self.core.gateway, 'history_file', None)
                if not history_file:
                    # Fallback: try to find it in config
                    history_file = self.core.config.get('paths', {}).get('history', 
                                   os.path.join(self.core.config.get('paths', {}).get('logs', './logs'), 'conversation_history.json'))
                
                # Truncate history file
                if os.path.exists(history_file):
                    with open(history_file, 'w', encoding='utf-8') as f:
                        f.write("")  # Empty the file
                    await self._log(f"/clear: Truncated {history_file}", priority=2)
                
                # Reset gateway history
                if hasattr(self.core.gateway, 'history'):
                    self.core.gateway.history = []
                
                # Also clear any conversation archiver hot buffer if present
                try:
                    arch = next((s for s in getattr(self.core, 'skills', []) if getattr(s, 'skill_name', '') == 'conversation_archiver'), None)
                    if arch and hasattr(arch, 'tool_conversation_clear'):
                        await arch.tool_conversation_clear({})
                except Exception:
                    pass  # Non-fatal
                
                await self.send_message(chat_id, "✅ **Session Cleared.** History wiped. Fresh start.")
            except Exception as e:
                await self._log(f"/clear error: {e}", priority=1)
                await self.send_message(chat_id, f"❌ **Clear Failed:** `{e}`")

        elif cmd == '/leads':
            log_path = os.path.join(self.core.config['paths']['logs'], 'processed_emails.json')
            lead_count = 0
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    lead_count = len(json.load(f))
            await self.send_message(
                chat_id,
                f"🎯 **Galactic Lead Recap**\n\n• **Email Leads:** `{lead_count}`\n• **Reddit Gigs:** `Scanning...`\n\nCheck `/status` for plugin health.",
            )

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
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "")
                        if "document" in msg and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            self._track_task(asyncio.create_task(self._handle_document(chat_id, msg)))
                            continue
                        if "photo" in msg and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            self._track_task(asyncio.create_task(self._handle_photo(chat_id, msg)))
                            continue
                        if ("voice" in msg or "audio" in msg) and hasattr(self.core, 'gateway'):
                            await self.send_typing(chat_id)
                            self._track_task(asyncio.create_task(self._handle_audio(chat_id, msg)))
                            continue
                        if chat_id in self.pending_api_key and text and not text.startswith('/'):
                            pending = self.pending_api_key.pop(chat_id)
                            api_key = text.strip()
                            await self._save_provider_key(pending["provider"], api_key)
                            self.core.gateway.llm.api_key = api_key
                            self.core.gateway.llm.provider = pending["provider"]
                            self.core.gateway.llm.model = pending["model"]
                            await self.send_message(chat_id, f"✅ API key saved for **{pending['provider'].capitalize()}**! Switched to: `{pending['model']}`")
                            continue
                        if text.startswith('/'):
                            await self.process_command(chat_id, text)
                            continue
                        if text.strip().lower() == 'stop':
                            await self.process_command(chat_id, '/stop')
                            continue
                        await self.send_typing(chat_id)
                        if hasattr(self.core, 'gateway'):
                            self._track_task(asyncio.create_task(self.process_and_respond(chat_id, text)))
            except Exception as e:
                await self._log(f"Bridge Loop Error: {e}", priority=1)
            await asyncio.sleep(0.5)

    async def get_updates(self):
        try:
            r = await self.client.get(f"{self.api_url}/getUpdates", params={"offset": self.offset, "timeout": 30})
            return r.json().get("result", []) if r.json().get("ok") else []
        except Exception:
            return []

    def _get_speak_timeout(self) -> float:
        global_timeout = float(self.core.config.get('models', {}).get('speak_timeout', 600))
        tg_cfg = self.core.config.get('telegram', {})
        is_ollama = hasattr(self.core, 'gateway') and self.core.gateway.llm.provider == 'ollama'
        tg_timeout = float(tg_cfg.get('ollama_timeout_seconds', 600)) if is_ollama else float(tg_cfg.get('timeout_seconds', 120))
        return max(global_timeout, tg_timeout)

    async def _save_provider_key(self, provider: str, api_key: str):
        try:
            import yaml

            config_path = getattr(self.core, 'config_path', 'config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            if 'providers' not in cfg:
                cfg['providers'] = {}
            if provider not in cfg['providers']:
                cfg['providers'][provider] = {}
            cfg['providers'][provider]['apiKey'] = api_key
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
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
        response = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            self._last_model_call_ts = time.time()
            response = await asyncio.wait_for(self.core.gateway.speak(text, chat_id=chat_id), timeout=self._get_speak_timeout())
            self._last_model_ok_ts = time.time()
        except asyncio.CancelledError:
            response = "🛑 Task was cancelled."
            raise
        except asyncio.TimeoutError:
            provider = getattr(self.core.gateway.llm, 'provider', 'unknown')
            model = getattr(self.core.gateway.llm, 'model', 'unknown')
            t = self._get_speak_timeout()
            msg = f"speak() timed out after {t:.0f}s (provider={provider}, model={model})"
            self._last_model_error_ts = time.time()
            self._last_model_error = msg
            await self._log(f"[Telegram] {msg}", priority=1)
            response = f"⏱ Timed out after {t:.0f}s using `{provider}/{model}`.\n\nTry a simpler task or switch models with /model."
        except Exception as e:
            self._last_model_error_ts = time.time()
            self._last_model_error = str(e)
            await self._log(f"Processing Error: {e}", priority=1)
            response = f"🌌 **Byte Interference:** `{str(e)}`"
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if not response or not response.strip() or response == "[No response]":
                response = "🤔 I couldn't generate a response for that. Try rephrasing or sending again."
            try:
                await self.core.relay.emit(2, "chat_from_telegram", {"user": str(chat_id), "data": text, "response": response})
            except Exception:
                pass
            voice_file = getattr(self.core.gateway, 'last_voice_file', None)
            if voice_file and os.path.exists(voice_file):
                try:
                    await self.send_audio(chat_id, voice_file, caption=response[:200] if response else None)
                    self.core.gateway.last_voice_file = None
                except Exception as e:
                    await self._log(f"TTS Delivery Error: {e}", priority=1)
            image_file = getattr(self.core.gateway, 'last_image_file', None)
            if image_file and os.path.exists(image_file):
                try:
                    await self.send_photo(chat_id, image_file, caption=f"🎨 {os.path.basename(image_file)}")
                    self.core.gateway.last_image_file = None
                except Exception as e:
                    await self._log(f"Image Delivery Error: {e}", priority=1)
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_document(self, chat_id, msg):
        typing_task = None
        response = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            doc = msg["document"]
            file_name = doc.get("file_name", "unnamed")
            file_size = doc.get("file_size", 0)
            file_id = doc["file_id"]
            caption = msg.get("caption", "")
            if file_size > 5 * 1024 * 1024:
                await self.send_message(chat_id, f"📎 **{file_name}** is too large ({file_size // 1024}KB). Max 5 MB.")
                return
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve file from Telegram.")
                return
            file_path = file_data["result"]["file_path"]
            r = await self.client.get(f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}")
            raw = r.content
            try:
                text_content = raw.decode('utf-8', errors='replace')
            except Exception:
                text_content = '[Binary file — could not decode as text]'
            if len(text_content) > 100000:
                text_content = text_content[:100000] + '\n\n... [truncated]'
            full_msg = f"[Attached file: {file_name}]\n---\n{text_content}\n---"
            if caption:
                full_msg += f"\n\n{caption}"
            await self._log(f"[Telegram] User sent file: {file_name} ({file_size} bytes)", priority=2)
            self._last_model_call_ts = time.time()
            response = await asyncio.wait_for(self.core.gateway.speak(full_msg, chat_id=chat_id), timeout=self._get_speak_timeout())
            self._last_model_ok_ts = time.time()
        except asyncio.CancelledError:
            response = "🛑 Task was cancelled."
            raise
        except asyncio.TimeoutError:
            response = "⏱ Took too long processing that file. Please try again."
            self._last_model_error_ts = time.time()
            self._last_model_error = "document timeout"
        except Exception as e:
            await self._log(f"Document Error: {e}", priority=1)
            response = f"🌌 **Byte Interference:** `{str(e)}`"
            self._last_model_error_ts = time.time()
            self._last_model_error = str(e)
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if not response or not response.strip() or response == "[No response]":
                response = "🤔 I couldn't generate a response for that file. Try sending again."
            try:
                await self.core.relay.emit(
                    2,
                    "chat_from_telegram",
                    {"user": str(chat_id), "data": f"📎 {msg.get('document', {}).get('file_name', 'file')}", "response": response},
                )
            except Exception:
                pass
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_photo(self, chat_id, msg):
        typing_task = None
        response = None
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            photo = msg["photo"][-1]
            file_size = photo.get("file_size", 0)
            file_id = photo["file_id"]
            caption = msg.get("caption", "")
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve photo from Telegram.")
                return
            file_path = file_data["result"]["file_path"]
            r = await self.client.get(f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}")
            raw = r.content
            await self._log(f"[Telegram] User sent photo: {os.path.basename(file_path)} ({file_size} bytes)", priority=2)
            import base64

            image_b64 = base64.b64encode(raw).decode('utf-8')
            ext = os.path.splitext(file_path)[1].lower() or '.jpg'
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
            mime_type = mime_map.get(ext, 'image/jpeg')
            vision_prompt = caption if caption else "Describe this image in detail. Include any text you see."
            vision_result = await self.core.gateway._analyze_image_b64(image_b64, mime_type, vision_prompt)
            speak_msg = f"[Image Analysis Result]\n{vision_result}\n\nUser's caption/question: {caption}" if caption else f"[Image Analysis Result]\n{vision_result}"
            self._last_model_call_ts = time.time()
            response = await asyncio.wait_for(self.core.gateway.speak(speak_msg, chat_id=chat_id), timeout=self._get_speak_timeout())
            self._last_model_ok_ts = time.time()
        except asyncio.CancelledError:
            response = "🛑 Task was cancelled."
            raise
        except asyncio.TimeoutError:
            response = "⏱ Took too long analyzing that image. Please try again."
            self._last_model_error_ts = time.time()
            self._last_model_error = "photo timeout"
        except Exception as e:
            await self._log(f"Photo Error: {e}", priority=1)
            response = f"🌌 **Byte Interference (Photo):** `{str(e)}`"
            self._last_model_error_ts = time.time()
            self._last_model_error = str(e)
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if not response or not response.strip() or response == "[No response]":
                response = "🤔 I couldn't generate a response for that image. Try sending again."
            try:
                await self.core.relay.emit(2, "chat_from_telegram", {"user": str(chat_id), "data": f"📸 {msg.get('caption', 'image')}", "response": response})
            except Exception:
                pass
            try:
                await self.send_message(chat_id, response)
            except Exception as e:
                await self._log(f"Send Error: {e}", priority=1)

    async def _handle_audio(self, chat_id, msg):
        typing_task = None
        temp_file_path = None
        response = ""
        voice_reply_sent = False
        try:
            typing_task = asyncio.create_task(self.keep_typing(chat_id))
            audio_data = msg.get("voice") or msg.get("audio")
            if not audio_data:
                await self.send_message(chat_id, "❌ No audio data found.")
                return
            file_id = audio_data["file_id"]
            file_size = audio_data.get("file_size", 0)
            mime_type = audio_data.get("mime_type", "audio/ogg")
            caption = msg.get("caption", "")
            file_extension = ".ogg" if "ogg" in mime_type else ".mp3"
            r = await self.client.get(f"{self.api_url}/getFile", params={"file_id": file_id})
            file_data = r.json()
            if not file_data.get("ok"):
                await self.send_message(chat_id, "❌ Couldn't retrieve audio from Telegram.")
                return
            file_path = file_data["result"]["file_path"]
            r = await self.client.get(f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}")
            raw = r.content
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(raw)
                temp_file_path = tmp.name
            await self._log(f"[Telegram] User sent audio: {os.path.basename(temp_file_path)} ({file_size} bytes, {mime_type})", priority=2)
            transcription = await self._transcribe_audio(temp_file_path)
            if not transcription:
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
                voice_reply_sent = True
                await self.send_message(chat_id, no_key_msg)
                return
            full_msg = f"[Voice message from user]: {transcription}"
            if caption:
                full_msg += f"\n{caption}"
            self._last_model_call_ts = time.time()
            response = await asyncio.wait_for(self.core.gateway.speak(full_msg, chat_id=chat_id), timeout=self._get_speak_timeout())
            self._last_model_ok_ts = time.time()
            try:
                tts_result = await self.core.gateway.tool_text_to_speech({'text': response, 'voice': 'Byte'})
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
        except asyncio.CancelledError:
            response = "🛑 Task was cancelled."
            raise
        except asyncio.TimeoutError:
            response = "⏱ Took too long processing that voice message. Please try again."
            self._last_model_error_ts = time.time()
            self._last_model_error = "audio timeout"
        except Exception as e:
            await self._log(f"Audio Error: {e}", priority=1)
            response = f"🌌 **Byte Interference (Audio):** `{str(e)}`"
            self._last_model_error_ts = time.time()
            self._last_model_error = str(e)
        finally:
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except (asyncio.CancelledError, Exception):
                    pass
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if not response or not response.strip() or response == "[No response]":
                response = "🤔 I couldn't generate a response for that voice message. Try again."
            try:
                await self.core.relay.emit(2, "chat_from_telegram", {"user": str(chat_id), "data": f"🎤 {msg.get('caption', 'voice message')}", "response": response})
            except Exception:
                pass
            if not voice_reply_sent:
                try:
                    await self.send_message(chat_id, response)
                except Exception as e:
                    await self._log(f"Send Error: {e}", priority=1)

    async def keep_typing(self, chat_id):
        max_duration = int(self._get_speak_timeout()) + 30
        start_time = time.time()
        try:
            while True:
                if time.time() - start_time > max_duration:
                    break
                await self.send_typing(chat_id)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._log(f"Typing indicator error: {e}", priority=1)
