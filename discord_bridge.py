# Galactic AI - Discord Bridge
import asyncio
import os
import time
import traceback

try:
    import discord
    from discord.ext import commands
    from discord import app_commands
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


class DiscordBridge:
    """Discord bot bridge for Galactic AI — mirrors TelegramBridge / WhatsAppBridge patterns."""

    def __init__(self, core):
        self.core = core
        self.config = core.config.get('discord', {})
        self.bot_token = self.config.get('bot_token', '')
        self.start_time = time.time()
        self.bot = None
        self._processing = set()  # (channel_id, text) pairs currently in-flight
        self._component = "Discord"
        self._authorized_user_id = str(self.config.get('admin_user_id', '')).strip()

    async def _log(self, message, priority=3):
        """Route logs to the Discord component log file."""
        await self.core.log(message, priority=priority, component=self._component)

        if HAS_DISCORD and self.bot_token:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.messages = True
            intents.guilds = True
            self.bot = commands.Bot(command_prefix='!gal ', intents=intents, help_command=None)
            self._setup_events()
            self._setup_slash_commands()
        else:
            self.bot = None

    def is_configured(self) -> bool:
        """Return True if Discord bridge has minimum viable configuration."""
        return bool(HAS_DISCORD and self.bot_token)

    def _is_authorized(self, user_id, channel_id=None) -> bool:
        """Check if a Discord user is authorized to control the AI.

        Returns True if:
        1. The user_id matches admin_user_id in config.
        2. admin_user_id is not set, BUT the message is in an allowed_channels whitelist
           AND the user is NOT a bot. (Legacy fallback for channel-only security).

        Recommended: Always set admin_user_id for maximum security.
        """
        user_id = str(user_id)
        # 1. Strict user-based authorization (Primary)
        if self._authorized_user_id:
            return user_id == self._authorized_user_id

        # 2. Legacy/Channel-based fallback (Only if no admin_user_id is set)
        allowed_channels = self.config.get('allowed_channels', [])
        if allowed_channels and channel_id:
            return str(channel_id) in [str(c) for c in allowed_channels]

        # 3. Default Deny: If no admin_user_id and no allowed_channels, block everything
        return False

    # ──────────────────────────────────────────────
    #  Event handlers
    # ──────────────────────────────────────────────

    def _setup_events(self):
        """Register discord.py event handlers on self.bot."""

        @self.bot.event
        async def on_ready():
            await self._log(f"[Discord] Bot connected as {self.bot.user} (ID: {self.bot.user.id})", priority=1)
            # Sync slash commands with Discord
            try:
                synced = await self.bot.tree.sync()
                await self._log(f"[Discord] Synced {len(synced)} slash commands.", priority=2)
            except Exception as e:
                await self._log(f"[Discord] Slash command sync failed: {e}", priority=1)

        @self.bot.event
        async def on_message(message):
            # Ignore messages from the bot itself
            if message.author == self.bot.user:
                return
            # Ignore other bots
            if message.author.bot:
                return

            # Check authorization
            is_authorized = self._is_authorized(message.author.id, message.channel.id)
            text = message.content.strip()

            # Handle setup help (/id command or help) even if unauthorized
            if text.lower() in ('/id', '!gal id', 'id'):
                content = f"🆔 **Your Discord ID:** `{message.author.id}`\n"
                content += f"📍 **Channel ID:** `{message.channel.id}`\n\n"
                if not self._authorized_user_id:
                    content += "⚠️ **Security Alert:** No `admin_user_id` is configured. The bot is in a restricted state."
                await message.reply(content)
                return

            if not is_authorized:
                # Silent discard for non-authorized users to prevent bot spam
                return

            if not text:
                return

            # Dedup guard
            channel_id = str(message.channel.id)
            key = (channel_id, text)
            if key in self._processing:
                return
            self._processing.add(key)

            # Process in background task
            asyncio.create_task(self._process_and_respond(message, text, _key=key))

    # ──────────────────────────────────────────────
    #  Slash commands  (/status, /model, /help)
    # ──────────────────────────────────────────────

    def _setup_slash_commands(self):
        """Register Discord slash commands on the bot's command tree."""

        @self.bot.tree.command(name="status", description="System telemetry for Galactic AI")
        async def slash_status(interaction: discord.Interaction):
            if not self._is_authorized(interaction.user.id, interaction.channel_id):
                await interaction.response.send_message("❌ **Unauthorized**: You do not have permission to run system commands.", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                report = await self._build_status_report()
                await interaction.followup.send(report)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")

        @self.bot.tree.command(name="model", description="Show or switch the active AI model")
        @app_commands.describe(name="Model to switch to (e.g. gemini-2.5-flash, grok-4)")
        async def slash_model(interaction: discord.Interaction, name: str = None):
            if not self._is_authorized(interaction.user.id, interaction.channel_id):
                await interaction.response.send_message("❌ **Unauthorized**: Permission denied.", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                if name:
                    # Try to resolve an alias first
                    aliases = self.core.config.get('aliases', {})
                    resolved = aliases.get(name, name)
                    if '/' in resolved:
                        parts = resolved.split('/', 1)
                        provider = parts[0]
                        model = parts[1]
                    else:
                        provider = self.core.gateway.llm.provider
                        model = resolved
                    self.core.gateway.llm.provider = provider
                    self.core.gateway.llm.model = model
                    await interaction.followup.send(
                        f"**Model switched** to `{provider}/{model}`"
                    )
                    await self._log(f"[Discord] Model switched to {provider}/{model}", priority=2)
                else:
                    provider = self.core.gateway.llm.provider
                    model = self.core.gateway.llm.model
                    await interaction.followup.send(
                        f"**Active model:** `{provider}/{model}`\n"
                        f"Use `/model name:<model>` to switch."
                    )
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")

        @self.bot.tree.command(name="id", description="Get your Discord User ID and Channel ID")
        async def slash_id(interaction: discord.Interaction):
            content = f"🆔 **Your Discord ID:** `{interaction.user.id}`\n"
            content += f"📍 **Channel ID:** `{interaction.channel_id}`"
            await interaction.response.send_message(content, ephemeral=True)
        @self.bot.tree.command(name="help", description="Show available Galactic AI commands")
        async def slash_help(interaction: discord.Interaction):
            help_text = (
                "**Galactic AI  --  Discord Commands**\n\n"
                "`/status`  --  System telemetry\n"
                "`/model`  --  Show active model\n"
                "`/model name:<model>`  --  Switch model\n"
                "`/id`  --  Show your IDs for config\n"
                "`/help`  --  This help message\n\n"
                "Or just type a message to chat with the AI."
            )
            await interaction.response.send_message(help_text)

    # ──────────────────────────────────────────────
    #  Core message processing (mirrors Telegram/WhatsApp)
    # ──────────────────────────────────────────────

    async def _process_and_respond(self, message, text, _key=None):
        """Process a user message through the AI gateway and send the response back."""
        channel = message.channel
        channel_id = str(channel.id)
        user_display = str(message.author)
        response = ""
        try:
            # Show typing indicator while processing
            async with channel.typing():
                response = await asyncio.wait_for(
                    self.core.gateway.speak(text, chat_id=f"discord:{channel_id}"),
                    timeout=self._get_speak_timeout()
                )
        except asyncio.TimeoutError:
            provider = getattr(self.core.gateway.llm, 'provider', 'unknown')
            model = getattr(self.core.gateway.llm, 'model', 'unknown')
            t = self._get_speak_timeout()
            await self._log(
                f"[Discord] speak() timed out after {t:.0f}s for channel {channel_id} "
                f"(provider={provider}, model={model})",
                priority=1
            )
            response = (
                f"Timed out after {t:.0f}s using `{provider}/{model}`.\n\n"
                f"The model is running slowly. Try a simpler question, or use `/model` to switch."
            )
        except Exception as e:
            await self._log(f"[Discord] Processing error: {e}\n{traceback.format_exc()}", priority=1)
            response = f"**Error:** `{str(e)}`"
        finally:
            # Release dedup lock
            if _key:
                self._processing.discard(_key)

            # Relay to Web UI so Discord conversations show up in the web chat log
            try:
                await self.core.relay.emit(2, "chat_from_discord", {
                    "user": user_display,
                    "channel": channel_id,
                    "data": text,
                    "response": response,
                })
            except Exception:
                pass  # Non-fatal — web UI might not be connected

            # Deliver voice file if the AI used TTS
            voice_file = getattr(self.core.gateway, 'last_voice_file', None)
            if voice_file and os.path.exists(voice_file):
                try:
                    await channel.send(
                        file=discord.File(voice_file, filename=os.path.basename(voice_file))
                    )
                    self.core.gateway.last_voice_file = None
                except Exception as e:
                    await self._log(f"[Discord] Voice delivery error: {e}", priority=1)

            # Deliver generated image if present
            image_file = getattr(self.core.gateway, 'last_image_file', None)
            if image_file and os.path.exists(image_file):
                try:
                    await channel.send(
                        file=discord.File(image_file, filename=os.path.basename(image_file))
                    )
                    self.core.gateway.last_image_file = None
                except Exception as e:
                    await self._log(f"[Discord] Image delivery error: {e}", priority=1)

            # Send text response — chunk if it exceeds Discord's 2000-char limit
            if response:
                try:
                    chunks = self._chunk_text(response, 2000)
                    for chunk in chunks:
                        await channel.send(chunk)
                except Exception as e:
                    await self._log(f"[Discord] Send error: {e}", priority=1)

    # ──────────────────────────────────────────────
    #  Status report builder (shared by slash command)
    # ──────────────────────────────────────────────

    async def _build_status_report(self) -> str:
        """Build a system status report string (mirrors Telegram /status)."""
        from datetime import datetime
        uptime = int(time.time() - self.start_time)
        plugins = ", ".join([p.name for p in self.core.plugins]) or "none"
        mems = len(self.core.memory.index.get('memories', []))
        now = datetime.now().strftime("%H:%M:%S")
        provider = self.core.gateway.llm.provider
        model = self.core.gateway.llm.model
        version = self.core.config.get('system', {}).get('version', '?')
        tokens_in = self.core.gateway.total_tokens_in / 1000
        tokens_out = self.core.gateway.total_tokens_out / 1000

        report = (
            f"**GALACTIC AI SYSTEM STATUS**\n"
            f"Time: `{now}` | Version: `v{version}`\n"
            f"---\n"
            f"Model: `{provider}/{model}`\n"
            f"Tokens: `{tokens_in:.1f}k in` / `{tokens_out:.1f}k out`\n"
            f"Context: `{mems} imprints`\n"
            f"---\n"
            f"Uptime: `{uptime}s` | PID: `{os.getpid()}`\n"
            f"Plugins: `{plugins}`\n"
            f"---\n"
            f"Condition: `Nominal`"
        )
        return report

    # ──────────────────────────────────────────────
    #  Timeout helper
    # ──────────────────────────────────────────────

    def _get_speak_timeout(self) -> float:
        """Return the appropriate speak() timeout based on the active model provider.

        Ollama (local inference) gets a higher ceiling. Cloud models keep the fast default.
        """
        dc_cfg = self.core.config.get('discord', {})
        is_ollama = (
            hasattr(self.core, 'gateway') and
            self.core.gateway.llm.provider == 'ollama'
        )
        if is_ollama:
            return float(dc_cfg.get('ollama_timeout_seconds', 600))
        return float(dc_cfg.get('timeout_seconds', 120))

    # ──────────────────────────────────────────────
    #  Text chunking (Discord max = 2000 chars)
    # ──────────────────────────────────────────────

    @staticmethod
    def _chunk_text(text, max_len=2000):
        """Split text into chunks that fit Discord's message length limit."""
        if not text:
            return ['']
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Try to split at a newline
            split_idx = text.rfind('\n', 0, max_len)
            if split_idx == -1:
                split_idx = text.rfind(' ', 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip()
        return chunks

    # ──────────────────────────────────────────────
    #  Bot lifecycle
    # ──────────────────────────────────────────────

    async def run_bot(self):
        """Start the Discord bot. Called as an asyncio task from galactic_core_v2."""
        if not self.is_configured():
            return
        if not self.bot:
            await self._log("[Discord] discord.py library not installed -- skipping. Run: pip install discord.py", priority=1)
            return
        try:
            await self._log("[Discord] Starting bot...", priority=1)
            await self.bot.start(self.bot_token)
        except Exception as e:
            await self._log(f"[Discord] Bot crashed: {e}\n{traceback.format_exc()}", priority=1)

    async def stop_bot(self):
        """Gracefully close the Discord bot connection."""
        if self.bot and not self.bot.is_closed():
            try:
                await self.bot.close()
            except Exception:
                pass
