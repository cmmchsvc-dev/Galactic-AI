import asyncio
import json
import os
import signal
import sys
import yaml
import time
import logging
from datetime import datetime

# Enable VT processing for ANSI colors on Windows
if os.name == 'nt':
    os.system("")

# Silence noisy HTTP libraries globally — logs go to web UI, not terminal
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("aiohttp.server").setLevel(logging.WARNING)

class GalacticRelay:
    def __init__(self, core):
        self.core = core
        self.queue = asyncio.PriorityQueue()

    async def emit(self, priority, msg_type, data):
        await self.queue.put((priority, time.time(), json.dumps({"type": msg_type, "data": data})))

    async def route_loop(self):
        while True:
            priority, ts, raw_payload = await self.queue.get()
            payload = json.loads(raw_payload)
            payload["ts"] = ts
            encoded = (json.dumps(payload) + "\n").encode()

            # Broadcast to all connected adapters
            disconnected = []
            for client in self.core.clients:
                try:
                    client.write(encoded)
                    # Timeout drain so a stalled web client can't block the event loop
                    await asyncio.wait_for(client.drain(), timeout=2.0)
                except (asyncio.TimeoutError, Exception):
                    disconnected.append(client)

            for d in disconnected:
                try:
                    self.core.clients.remove(d)
                except ValueError:
                    pass
            self.queue.task_done()

try:
    from version import VERSION as _GALACTIC_VERSION
except Exception:
    _GALACTIC_VERSION = "2.1.0"


class GalacticCore:
    """The central orchestrator for Galactic AI.
    Integrates Gateway, ModelManager, Skills, and Dashboard.
    """
    NAME    = "Galactic AI"
    VERSION = _GALACTIC_VERSION  # single source of truth: version.py
    PORT    = 9999

    def __init__(self, config_path='config.yaml'):
        import config_loader
        self.config_path = os.path.abspath(config_path)
        # Live values (keys, tokens, tuned settings) live in the gitignored
        # overlay; config.yaml stays a tracked, sanitized template.
        self.local_config_path = config_loader.local_path_for(self.config_path)
        self.config = self.load_config()
        self.skills = []
        self.clients = []
        self.relay = GalacticRelay(self)
        self.running = True
        self.loop = None
        self.start_time = time.time()

    @property
    def plugins(self):
        """Legacy alias for self.skills — read-only on purpose.

        These used to be two separate lists kept in sync by a mirroring loop in
        load_skills(), which meant they could (and did) drift. There is exactly
        one collection of loaded skills; `plugins` is just the older name for it,
        kept so the ~38 existing `core.plugins` call sites keep working.
        """
        return self.skills

    def get_skill(self, name):
        """Look up a loaded skill by its skill_name."""
        return next((s for s in self.skills if getattr(s, 'skill_name', '') == name), None)

    def load_config(self):
        import config_loader
        config = config_loader.load_config(self.config_path)
        if not config:
            config = {
                'system': {'name': 'Galactic AI', 'version': '2.0.0', 'port': 9999},
                'paths': {'logs': './logs', 'images': './images', 'plugins': './plugins'},
                'gateway': {'provider': 'placeholder', 'model': 'placeholder'}
            }
            # Still continue to migration to ensure sections like 'models' are added

        # ── Auto-migrate: add missing config sections from newer versions ────
        migrated = False
        defaults = {
            'gmail':    {'email': '', 'app_password': '', 'check_interval': 60, 'notify_telegram': True},
            'discord':  {'bot_token': '', 'allowed_channels': [], 'admin_user_id': '', 'timeout_seconds': 120, 'ollama_timeout_seconds': 600},
            'whatsapp': {'phone_number_id': '', 'access_token': '', 'verify_token': '', 'webhook_secret': '', 'api_version': 'v21.0'},
            'webhooks': {'secret': ''},
            'web':      {'enabled': True, 'host': '127.0.0.1', 'port': 17789, 'password_hash': '', 'remote_access': False},
            'elevenlabs': {'api_key': '', 'voice': 'Guy'},
            'models':   {'auto_fallback': True, 'streaming': True, 'smart_routing': False, 'max_turns': 50, 'speak_timeout': 600,
                         'fallback_cooldowns': {'RATE_LIMIT': 60, 'SERVER_ERROR': 30, 'TIMEOUT': 10, 'AUTH_ERROR': 86400, 'QUOTA_EXHAUSTED': 3600}},
            'tool_timeouts': {'exec_shell': 120, 'execute_python': 60, 'generate_image': 180},
            'aliases':  {},
            'social_media': {
                'twitter': {'consumer_key': '', 'consumer_secret': '', 'access_token': '', 'access_token_secret': ''},
                'reddit':  {'client_id': '', 'client_secret': '', 'username': '', 'password': '', 'user_agent': 'GalacticAI/2.0.0'},
            },
            'chrome_bridge': {'enabled': True, 'timeout': 30},
        }
        for section, section_defaults in defaults.items():
            if section not in config:
                config[section] = section_defaults
                migrated = True
            elif isinstance(section_defaults, dict) and isinstance(config[section], dict):
                # Add missing keys within existing sections
                for key, value in section_defaults.items():
                    if key not in config[section]:
                        config[section][key] = value
                        migrated = True

        # Ensure system section has newer keys
        sys_defaults = {'update_check_interval': 21600, 'version': '2.0.0', 'port': 9999}
        if 'system' not in config:
            config['system'] = {'name': 'Galactic AI'}
            config['system'].update(sys_defaults)
            migrated = True
        else:
            for key, value in sys_defaults.items():
                if key not in config['system']:
                    config['system'][key] = value
                    migrated = True

        # Code version is the single source of truth — a stale value in either
        # config file (or one written by an older running process) must never
        # surface in the UI/terminal/API.
        if config.get('system', {}).get('version') != self.VERSION:
            config.setdefault('system', {})['version'] = self.VERSION
            migrated = True

        # Save migrated config — to the overlay, never the tracked template
        if migrated:
            try:
                config_loader.save_config(config, self.config_path)
            except Exception:
                pass  # Non-fatal — config still works in memory

        return config

    def save_config(self):
        """
        Thread-safe configuration persistence.
        Re-reads the merged config before writing to prevent overwriting
        concurrent on-disk changes (like version bumps from other processes).
        Writes go to the gitignored overlay (config.local.yaml) only.
        """
        import config_loader
        try:
            # 1. Read the latest merged state from disk (template + overlay)
            disk_config = config_loader.load_config(self.config_path)

            # 2. Update disk state with in-memory state.
            # We treat in-memory as the source of truth for logic, but disk might
            # have metadata (like a version bump from another process) we
            # shouldn't revert. A shallow .update() replaced whole top-level
            # SECTIONS, so a stale in-memory 'models' dict silently wiped another
            # process's write — exactly what this method's docstring promises not
            # to do. deep_merge keeps per-key resolution instead.
            # Direction matters: base=disk, overlay=in-memory, so in-memory wins
            # for the keys it defines and disk survives for the ones it doesn't.
            # _OVERLAY_AUTHORITATIVE keys (model_overrides, aliases) are still
            # replaced wholesale by the in-memory value, so DELETIONS STICK.
            disk_config = config_loader.deep_merge(disk_config, self.config)

            # Ensure critical fields like version are synchronized
            if 'system' in disk_config:
                disk_config['system']['version'] = self.VERSION

            # 3. Atomic write to the overlay
            if not config_loader.save_config(disk_config, self.config_path):
                return False

            # 4. Sync our in-memory config to match disk
            self.config = disk_config
            return True
        except Exception as e:
            print(f"[Core] Error saving config: {e}")
            return False

    async def setup_systems(self):
        """Initialize core sub-systems."""
        try:
            from gateway_v3 import GalacticGateway
            from telegram_bridge import TelegramBridge
            from web_deck import GalacticWebDeck
            from scheduler import GalacticScheduler
            from model_manager import ModelManager

            await self.log("Initializing core systems...", priority=2)

            # Memory: full semantic engine when the ML stack is installed,
            # otherwise a keyword-based Lite engine so a Lite install still
            # boots and still remembers things.
            from memory_fallback import load_memory
            self.memory, self.memory_is_lite = load_memory(self)
            if self.memory_is_lite:
                await self.log("🧠 Lite memory active (keyword recall). "
                               "Install semantic memory: python install.py --add memory", priority=2)
            
            self.gateway = GalacticGateway(self)
            self.gateway.galactic_memory = self.memory # Link them

            # Cost tracking (persistent JSONL)
            from gateway_v3 import CostTracker
            logs_dir = self.config.get('paths', {}).get('logs', './logs')
            self.cost_tracker = CostTracker(logs_dir)
            self.cost_tracker.attach_core(self)  # enables budget alerts
            
            self.model_manager = ModelManager(self)

            # Ollama Manager — robust local model support (health, discovery, context windows)
            from ollama_manager import OllamaManager
            self.ollama_manager = OllamaManager(self)
            try:
                await self.ollama_manager.health_check()
                await self.ollama_manager.discover_models()
            except Exception as e:
                await self.log(f"Ollama health check failed: {e}", priority=1)

            # LM Studio Manager — the other local backend, interchangeable with Ollama.
            # Opt-in: only activates when the user has a providers.lmstudio section,
            # so users who don't run LM Studio never poll for it.
            self.lmstudio_manager = None
            _lms_cfg = self.config.get('providers', {}).get('lmstudio')
            if _lms_cfg and _lms_cfg.get('enabled', True):
                try:
                    from lmstudio_manager import LMStudioManager
                    self.lmstudio_manager = LMStudioManager(self)
                    await self.lmstudio_manager.health_check()
                    await self.lmstudio_manager.discover_models()
                except Exception as e:
                    await self.log(f"LM Studio health check failed: {e}", priority=1)

            self.telegram = TelegramBridge(self)

            # Optional bridges — instantiated always (cheap), started later only
            # when their config.enabled flag is set. Non-fatal on import error.
            self.discord = None
            self.gmail = None
            try:
                from discord_bridge import DiscordBridge
                self.discord = DiscordBridge(self)
            except Exception as e:
                await self.log(f"Discord bridge unavailable: {e}", priority=2)
            try:
                from gmail_bridge import GmailBridge
                self.gmail = GmailBridge(self)
            except Exception as e:
                await self.log(f"Gmail bridge unavailable: {e}", priority=2)

            self.web_deck = GalacticWebDeck(self)
            self.web = self.web_deck # Legacy alias
            self.scheduler = GalacticScheduler(self)

            # Ambient Agent + Life-Log — proactive background awareness.
            # Non-fatal: a failure here must never block core startup.
            try:
                from ambient_agent import AmbientAgent
                self.ambient_agent = AmbientAgent(self)
            except Exception as e:
                self.ambient_agent = None
                await self.log(f"Ambient Agent unavailable: {e}", priority=2)

            # Set initial model from ModelManager
            initial_model = self.model_manager.get_current_model()
            self.gateway.provider = initial_model['provider']
            self.gateway.model = initial_model['model']
            # Clear context vars in the main task just in case
            self.gateway.llm.provider = None
            self.gateway.llm.model = None
            self.model_manager._set_api_key(initial_model['provider'])
            await self.log(
                f"Model loaded: {initial_model['provider']}/{initial_model['model']} "
                f"(fallback: {self.model_manager.fallback_provider}/{self.model_manager.fallback_model})",
                priority=2
            )
            
            await self.log("Systems initialized. Core capabilities running as Skills.", priority=2)

            # Load Skills (runs alongside plugins during migration)
            await self.load_skills()
        except Exception as e:
            await self.log(f"CRITICAL: Failed to setup systems: {e}", priority=1)
            import traceback
            await self.log(traceback.format_exc(), priority=1)
            raise

    def _load_skill(self, module_path, class_name, is_core=False):
        """Import and instantiate a single skill. Appends to self.skills on success."""
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            skill = cls(self)
            skill.is_core = is_core
            self.skills.append(skill)
            return skill
        except ModuleNotFoundError as e:
            print(f"[Skill] {class_name} missing dependency: {e} — skipping")
            return None
        except Exception as e:
            print(f"[Skill] {class_name} failed to load: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _run_skill_on_load(self, skill):
        """Invoke a skill's on_load() hook.

        on_load() is part of the documented skill contract (skills/base.py) and
        the runtime-creation path in gateway_tools.py has always awaited it — but
        the normal boot path never did, so any skill doing async init worked when
        created live and silently died on every reboot. Handles both sync and
        async implementations, and LOGS failures rather than swallowing them.
        """
        hook = getattr(skill, 'on_load', None)
        if not callable(hook):
            return
        name = getattr(skill, 'skill_name', skill.__class__.__name__)
        try:
            import inspect
            result = hook()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            await self.log(f"⚠️ Skill '{name}' on_load() failed: {e}", priority=1)
            import traceback
            await self.log(traceback.format_exc(), priority=1)

    def _read_registry(self):
        """Read skills/registry.json. Returns dict with 'installed' list."""
        import json as _json
        registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills', 'registry.json')
        try:
            with open(registry_path, 'r') as f:
                return _json.load(f)
        except (FileNotFoundError, ValueError):
            return {"installed": []}

    def _write_registry(self, data):
        """Write skills/registry.json."""
        import json as _json
        registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills', 'registry.json')
        with open(registry_path, 'w') as f:
            _json.dump(data, f, indent=2)

    async def load_skills(self):
        """Discover and load all skills (core + community).
        Called from setup_systems() after plugins are loaded.
        As plugins are migrated, they move from _BUILTIN_PLUGINS to CORE_SKILLS here.
        """
        self.skills = []

        # Core skills — add entries here as plugins are migrated
        CORE_SKILLS = [
            ('skills.core.watchdog',         'WatchdogSkill'),
            ('skills.core.shell_executor',   'ShellSkill'),
            ('skills.core.desktop_tool',     'DesktopSkill'),
            ('skills.core.voice_agent',      'VoiceAgentSkill'),
            ('skills.core.screen_awareness', 'ScreenAwarenessSkill'),  # used by voice "look at my screen"
            ('skills.core.chrome_bridge',    'ChromeBridgeSkill'),   # Phase 3
            ('skills.core.social_media',     'SocialMediaSkill'),    # Phase 3
            ('skills.core.subagent_manager', 'SubAgentSkill'),       # Phase 3
            ('skills.core.browser_pro',    'BrowserProSkill'),     # Phase 4
            ('skills.core.system_tools',     'SystemSkill'),
            ('skills.core.self_healing',     'SelfHealingSkill'),
            ('skills.core.forge',            'ForgeSkill'),
            ('skills.core.gpu_offloader',    'GPUOffloader'),
            ('skills.core.neural_indexer',   'NeuralIndexer'),
            ('skills.core.forge_sentinel',   'ForgeSentinel'),
            ('skills.core.tensor_context',   'TensorContext'),
            ('skills.core.reasoning_agent',  'ReasoningAgentSkill'),
        ]
        loaded_skill_names = []
        for module_path, class_name in CORE_SKILLS:
            skill = self._load_skill(module_path, class_name, is_core=True)
            if skill:
                await self._run_skill_on_load(skill)
                loaded_skill_names.append(skill.skill_name)

        # Community skills from registry.json
        registry = self._read_registry()
        for entry in registry.get('installed', []):
            module = f"skills.community.{entry['module']}"
            skill = self._load_skill(module, entry['class'], is_core=False)
            if skill:
                await self._run_skill_on_load(skill)
                loaded_skill_names.append(skill.skill_name)

        # Register all skill-provided tools into gateway
        if self.skills:
            self.gateway.register_skill_tools(self.skills)
            await self.log(f"Skills loaded: {', '.join(loaded_skill_names)}", priority=2)

        # (self.plugins is a read-only property aliasing self.skills — no
        # mirroring loop needed, and the two can no longer drift.)

        # Re-check for browser skill now that skills are loaded
        if not getattr(self, 'browser', None):
            browser_skill = self.get_skill('browser_pro')
            if browser_skill:
                self.browser = browser_skill

    async def imprint_workspace(self):
        """Initial memory imprint of key personality files."""
        await self.log("Starting Workspace Memory Imprint...", priority=2)
        workspace_files = ['USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md', 'VAULT.md']
        for file in workspace_files:
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', file)
            if os.path.exists(file_path):
                await self.memory.imprint_file(file_path)
        await self.log("Workspace Imprint Complete.", priority=2)

    def _rotate_if_needed(self, path, max_bytes=2_000_000, max_lines=5000):
        """Trim a log file if it exceeds max_bytes. Keeps the last max_lines lines."""
        try:
            if os.path.getsize(path) > max_bytes:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines[-max_lines:])
        except Exception:
            pass

    async def log(self, message, priority=3, component=None):
        """Write a log entry to system_log.txt (plain text, UI-compatible) and,
        if component= is given, also to a daily-rotated structured JSON component log.

        Backwards compatible: all existing callers with no component= kwarg continue
        to work identically. component= is used by bridges and subsystems to route
        their logs to dedicated files (e.g. logs/telegram_2026-02-21.log).
        """
        comp_label = component or "Core"
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{comp_label}] {message}"
        sys.stdout.write('\r\033[K' + log_entry + '\n')
        sys.stdout.flush()

        logs_dir = self.config.get('paths', {}).get('logs', './logs')
        os.makedirs(logs_dir, exist_ok=True)

        # 1. Always write plain-text entry to system_log.txt (UI backwards compat)
        try:
            log_file = os.path.join(logs_dir, 'system_log.txt')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
            self._rotate_if_needed(log_file)
        except Exception:
            pass

        # 2. Write structured JSON entry to daily component log
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            comp_slug = comp_label.lower().replace(' ', '_')
            comp_file = os.path.join(logs_dir, f"{comp_slug}_{date_str}.log")
            json_entry = json.dumps({
                "ts": datetime.now().isoformat(timespec='seconds'),
                "level": "INFO",
                "component": comp_label,
                "msg": message,
            })
            with open(comp_file, 'a', encoding='utf-8') as f:
                f.write(json_entry + '\n')
            self._rotate_if_needed(comp_file)
        except Exception:
            pass

    async def update_status(self, message: str, percent: float = None):
        """Update the current terminal line in place (progress bar style)."""
        bar = ""
        if percent is not None:
            width = 20
            filled = int(width * (percent / 100))
            bar = f" |[\033[92m{'█' * filled}\033[90m{'░' * (width - filled)}\033[0m] {percent:3.0f}%| "
        
        sys.stdout.write(f"\r\033[K{bar}{message}")
        sys.stdout.flush()

    async def _ensure_firewall_rule(self, port: int):
        """Add a Windows Firewall inbound rule for the Control Deck port if one doesn't exist."""
        import subprocess
        rule_name = "Galactic AI Control Deck"
        try:
            # Check if rule already exists
            check = subprocess.run(
                ['powershell', '-Command',
                 f'Get-NetFirewallRule -DisplayName "{rule_name}" -ErrorAction SilentlyContinue'],
                capture_output=True, text=True, timeout=10
            )
            if rule_name in check.stdout:
                return  # Rule already exists

            # Add the rule (private profile only for LAN safety)
            result = subprocess.run(
                ['powershell', '-Command',
                 f'New-NetFirewallRule -DisplayName "{rule_name}" '
                 f'-Direction Inbound -LocalPort {port} -Protocol TCP '
                 f'-Action Allow -Profile Private '
                 f'-Description "Allow Galactic AI remote access on LAN"'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                await self.log(f"Firewall rule added for port {port} (private networks)", priority=1)
            else:
                # May need admin privileges — that's OK, just inform user
                await self.log(
                    f"Could not auto-add firewall rule (may need admin). "
                    f"Run as admin or manually allow port {port} in Windows Firewall.",
                    priority=1
                )
        except Exception as e:
            await self.log(f"Firewall check skipped: {e}", priority=2)

    async def handle_client(self, reader, writer):
        self.clients.append(writer)
        addr = writer.get_extra_info('peername')
        await self.log(f"Interface Linked: {addr}", priority=2)
        try:
            while True:
                data = await reader.read(100)
                if not data: break
        except ConnectionResetError:
            pass
        finally:
            try:
                self.clients.remove(writer)
            except ValueError:
                pass  # Already removed by route_loop on drain timeout
            writer.close()
            await writer.wait_closed()

    async def _recovery_check_loop(self):
        """Periodically clear expired provider cooldowns and check recovery."""
        while self.running:
            await asyncio.sleep(30)
            try:
                if hasattr(self, 'model_manager'):
                    await self.model_manager.check_recovery()
            except Exception:
                pass

    async def _update_check_loop(self):
        """Check GitHub for new Galactic AI releases and notify user."""
        import httpx
        repo = "cmmchsvc-dev/Galactic-AI"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

        # Initial delay — let the system finish booting before first check
        await asyncio.sleep(15)

        while self.running:
            try:
                interval = self.config.get('system', {}).get('update_check_interval', 21600)
                if interval <= 0:
                    await asyncio.sleep(3600)  # Re-check config in 1h
                    continue

                current_version = self.config.get('system', {}).get('version', '0.0.0')
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
                    if r.status_code == 200:
                        data = r.json()
                        latest_tag = data.get('tag_name', '').lstrip('v')
                        if latest_tag and self._version_newer(latest_tag, current_version):
                            await self.relay.emit(2, "update_available", {
                                "current": current_version,
                                "latest": latest_tag,
                                "url": data.get('html_url', ''),
                                "name": data.get('name', ''),
                            })
                            await self.log(
                                f"🆕 Update available: v{latest_tag} (current: v{current_version}). "
                                f"Run ./update.ps1 or ./update.sh to update.",
                                priority=2
                            )
            except Exception:
                pass  # Network issues shouldn't interrupt normal operation

            await asyncio.sleep(max(interval if 'interval' in dir() else 21600, 3600))

    @staticmethod
    def _version_newer(latest, current):
        """Compare semver strings. Returns True if latest > current."""
        try:
            l = [int(x) for x in latest.split('.')]
            c = [int(x) for x in current.split('.')]
            return l > c
        except (ValueError, AttributeError):
            return False

    async def _terminal_input_loop(self):
        """Non-blocking terminal input listener for Escape key."""
        if os.name != 'nt':
            return # Only implemented for Windows for now
            
        import msvcrt
        while self.running:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    # 27 is the ASCII code for Escape
                    if ch == b'\x1b':
                        # A REAL Escape keypress is a lone \x1b. But \x1b is also
                        # the first byte of every VT/ANSI sequence the terminal
                        # can push onto stdin — cursor-position replies, focus
                        # in/out, bracketed paste. Treating those as Escape would
                        # silently kill every running task. Settle briefly, and
                        # if more bytes follow, it was a sequence: drain, ignore.
                        await asyncio.sleep(0.02)
                        if msvcrt.kbhit():
                            while msvcrt.kbhit():
                                msvcrt.getch()
                            continue
                        gateway = getattr(self, 'gateway', None)
                        if gateway and gateway._active_tasks:
                            gateway._cancel_reason = "terminal_escape"
                            count = 0
                            for t in list(gateway._active_tasks):
                                if not t.done():
                                    t.cancel()
                                    count += 1
                            if count > 0:
                                await self.log(f"🚫 Escape pressed in terminal. Aborting {count} task(s)...", priority=2)
                        
                        # Stop Voice Agent TTS if it is currently speaking
                        for skill in self.skills:
                            if getattr(skill, 'skill_name', '') == 'voice_agent':
                                skill._abort_speaking = True
                                skill._current_speak_run = getattr(skill, '_current_speak_run', 0) + 1
            except Exception:
                pass
            await asyncio.sleep(0.1)

    async def _preflight_report(self):
        """One-glance boot health summary — answers "why isn't X working?"
        before you have to ask. Best-effort: never blocks or fails startup."""
        checks = await self.diagnostics()
        icon = {'ok': '✓', 'warn': '⚠', 'info': '•'}
        lines = [f"{icon.get(c['status'], '•')} {c['label']}: {c['detail']}" for c in checks]
        try:
            await self.log("🩺 Preflight:\n   " + "\n   ".join(lines), priority=2)
        except Exception:
            pass

    async def diagnostics(self):
        """Structured health checks. Powers the boot preflight, /api/doctor,
        and the deck's Run Diagnostics button. Each entry:
        {status: ok|warn|info, label, detail}. Never raises."""
        out = []

        def add(status, label, detail):
            out.append({'status': status, 'label': label, 'detail': str(detail)})

        try:
            has_overlay = os.path.exists(getattr(self, 'local_config_path', '') or '')
            add('ok' if has_overlay else 'warn', 'Version / config',
                f"v{self.VERSION} — " + ("template + gitignored local overlay" if has_overlay
                                         else "template only (no config.local.yaml — secrets may be unset)"))
        except Exception as e:
            add('warn', 'Version / config', e)

        try:
            provs = []
            for name, p in (self.config.get('providers') or {}).items():
                if name == 'ollama':
                    continue
                key = (p or {}).get('apiKey') or (p or {}).get('api_key') or ''
                if key and not str(key).startswith('YOUR_'):
                    provs.append(name)
            add('ok' if provs else 'info', 'Cloud providers',
                f"{len(provs)} with keys: {', '.join(sorted(provs)) if provs else 'none (local-only mode)'}")
        except Exception as e:
            add('warn', 'Cloud providers', e)

        try:
            om = getattr(self, 'ollama_manager', None)
            models = list(getattr(om, 'discovered_models', []) or []) if om else []
            add('ok' if models else 'warn', 'Ollama',
                f"{len(models)} local models" if models else "no models found — is Ollama running?")
        except Exception as e:
            add('warn', 'Ollama', e)

        try:
            lm = getattr(self, 'lmstudio_manager', None)
            if lm:
                lmodels = list(getattr(lm, 'discovered_models', []) or [])
                add('ok' if lmodels else 'warn', 'LM Studio',
                    f"{len(lmodels)} local models" if lmodels else "enabled but no models — is LM Studio's server running?")
        except Exception as e:
            add('warn', 'LM Studio', e)

        try:
            gw = getattr(self, 'gateway', None)
            add('ok', 'Active model', f"{gw.llm.provider}/{gw.llm.model}" if gw else 'gateway not ready')
        except Exception as e:
            add('warn', 'Active model', e)

        try:
            import importlib.util
            if importlib.util.find_spec('faster_whisper') is not None:
                add('ok', 'Local STT', 'faster-whisper installed — voice stays on this machine')
            else:
                add('warn', 'Local STT', 'faster-whisper NOT installed — voice falls back to cloud '
                                         '(pip install faster-whisper)')
        except Exception as e:
            add('warn', 'Local STT', e)

        try:
            va = self.config.get('voice_agent', {}) or {}
            engine = va.get('engine', 'edge-tts')
            status, note = 'ok', ''
            if engine == 'fish-speech' and not va.get('fish_speech_api_key'):
                status, note = 'warn', ' (no fish.audio key — will fall back)'
            elif engine == 'elevenlabs' and not (self.config.get('elevenlabs', {}) or {}).get('api_key'):
                status, note = 'warn', ' (no ElevenLabs key — will fall back)'
            wake = 'ON (mic live)' if va.get('wake_word_enabled', True) else 'OFF'
            add(status, 'Voice', f"TTS {engine}{note} | wake word {wake}")
        except Exception as e:
            add('warn', 'Voice', e)

        try:
            on = [n for n in ('telegram', 'discord', 'gmail', 'whatsapp')
                  if (self.config.get(n, {}) or {}).get('enabled')]
            add('ok' if on else 'info', 'Bridges',
                ', '.join(on) + ' enabled' if on else 'none enabled')
        except Exception as e:
            add('warn', 'Bridges', e)

        try:
            add('ok', 'Skills', f"{len(getattr(self, 'skills', []) or [])} loaded")
        except Exception as e:
            add('warn', 'Skills', e)

        try:
            mem = getattr(self, 'memory', None)
            if mem:
                counts = await mem.category_counts()
                code = counts.pop('codebase_index', 0)
                personal = sum(counts.values())
                add('ok', 'Memory',
                    f"{personal:,} personal/conversation memories, {code:,} code-index chunks")
            else:
                add('warn', 'Memory', 'memory system unavailable')
        except Exception as e:
            add('warn', 'Memory', e)

        try:
            import shutil as _sh
            logs_dir = self.config.get('paths', {}).get('logs', './logs')
            free_gb = _sh.disk_usage(os.path.abspath(logs_dir) if os.path.exists(logs_dir) else '.').free / 1e9
            add('ok' if free_gb > 5 else 'warn', 'Disk',
                f"{free_gb:.0f} GB free" + ('' if free_gb > 5 else ' — low, memory/logs may fail to write'))
        except Exception as e:
            add('warn', 'Disk', e)

        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            drive_tmp = os.path.join(repo_dir, '.tmp.driveupload')
            if os.path.isdir(drive_tmp):
                # The folder's own mtime changes when sync is switched off, so
                # judge by the newest file INSIDE it — that only advances while
                # Drive is actually staging uploads.
                newest = 0.0
                for root, _dirs, files in os.walk(drive_tmp):
                    for f in files:
                        try:
                            newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                        except OSError:
                            pass
                age_h = (time.time() - newest) / 3600 if newest else 1e9
                if age_h < 2:
                    add('warn', 'Google Drive',
                        'repo appears to be actively syncing — risk of .git corruption '
                        '(see scripts/move_out_of_drive.ps1)')
                else:
                    add('info', 'Google Drive',
                        f'sync inactive ({age_h/24:.0f}d idle) — leftover .tmp.driveupload is safe to delete')
        except Exception:
            pass

        return out

    async def shutdown(self):
        """Graceful shutdown — close all subsystems cleanly."""
        if not self.running:
            return
        self.running = False
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] [Core] Shutting down Galactic AI...")

        # Schedule a hard exit fallback — if graceful shutdown takes too long,
        # force-kill the process. This prevents hanging on in-flight HTTP requests.
        def _force_exit():
            import time
            time.sleep(8)
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [Core] Graceful shutdown timed out — forcing exit.")
            os._exit(0)
        import threading
        exit_timer = threading.Thread(target=_force_exit, daemon=True)
        exit_timer.start()

        # Close optional bridges cleanly.
        try:
            if getattr(self, 'gmail', None):
                self.gmail.running = False
            if getattr(self, 'discord', None):
                await self.discord.stop_bot()
        except Exception:
            pass

        # Release the gateway's dedicated disk-I/O thread pool.
        try:
            io_pool = getattr(getattr(self, 'gateway', None), '_io_pool', None)
            if io_pool:
                io_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        # Cancel all background tasks (with timeout — don't wait forever)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [Core] Some tasks didn't cancel in 5s, continuing shutdown...")

        # Close Telegram client
        try:
            if hasattr(self, 'telegram') and hasattr(self.telegram, 'client'):
                await self.telegram.client.aclose()
        except Exception:
            pass

        # Close browser if open
        try:
            if hasattr(self, 'browser') and hasattr(self.browser, 'close'):
                await self.browser.close()
        except Exception:
            pass

        # Clean up aiohttp web server (release port)
        try:
            if hasattr(self, 'web') and hasattr(self.web, '_runner') and self.web._runner:
                await self.web._runner.cleanup()
        except Exception:
            pass

        # Clean up XTTS server
        try:
            if hasattr(self, 'xtts_process') and self.xtts_process:
                self.xtts_process.terminate()
            if hasattr(self, 'xtts_log_file') and self.xtts_log_file:
                self.xtts_log_file.close()
        except Exception:
            pass

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [Core] Galactic AI shut down cleanly. See you among the stars.")

    async def main_loop(self):
        self.loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown (Ctrl+C / Control Deck)
        shutdown_event = asyncio.Event()
        self.shutdown_event = shutdown_event  # Expose so web_deck can trigger it

        def _signal_handler():
            if shutdown_event.is_set():
                return  # Already shutting down
            shutdown_event.set()

        # Windows uses signal.signal(); Unix can use loop.add_signal_handler()
        try:
            if sys.platform == 'win32':
                # On Windows, asyncio signal handling is limited — use signal module
                def _win_handler(sig, frame):
                    _signal_handler()
                signal.signal(signal.SIGINT, _win_handler)
                signal.signal(signal.SIGTERM, _win_handler)
            else:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    self.loop.add_signal_handler(sig, _signal_handler)
        except ValueError:
            # Expected if not running in the main thread (e.g. GUI launcher)
            pass

        # GALACTIC AI SPLASH SCREEN
        ver = self.config.get('system',{}).get('version','?')
        full_splash = f"""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ██████╗  █████╗ ██╗      █████╗  ██████╗████████╗██╗ ██████╗║
║  ██╔════╝ ██╔══██╗██║     ██╔══██╗██╔════╝╚══██╔══╝██║██╔════╝║
║  ██║  ███╗███████║██║     ███████║██║        ██║   ██║██║     ║
║  ██║   ██║██╔══██║██║     ██╔══██║██║        ██║   ██║██║     ║
║  ╚██████╔╝██║  ██║███████╗██║  ██║╚██████╗   ██║   ██║╚██████╗║
║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝   ╚═╝   ╚═╝ ╚═════╝║
║                                                               ║
║                       v{ver:<39}║
║                  Sovereign - Universal - Fast                 ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
        def _gradient(text, start_hex, end_hex):
            # Check for TrueColor support
            has_truecolor = os.environ.get('COLORTERM') in ('truecolor', '24bit')
            # Windows Terminal, VS Code, iTerm, etc.
            is_modern = any(x in os.environ for x in ['WT_SESSION', 'TERM_PROGRAM', 'VSCODE_GIT_IPC_HANDLE'])
            
            if not has_truecolor and not is_modern and os.name != 'nt':
                # Only fallback to flat color if we are fairly sure it's legacy/basic
                return f"\033[1;36m{text}\033[0m"

            start = tuple(int(start_hex[i:i+2], 16) for i in (0, 2, 4))
            end = tuple(int(end_hex[i:i+2], 16) for i in (0, 2, 4))
            lines = text.strip('\n').split('\n')
            max_len = max(len(line) for line in lines) if lines else 1
            res = []
            for line in lines:
                colored = ""
                for x, char in enumerate(line):
                    ratio = x / max_len if max_len > 0 else 0
                    r = int(start[0] + (end[0] - start[0]) * ratio)
                    g = int(start[1] + (end[1] - start[1]) * ratio)
                    b = int(start[2] + (end[2] - start[2]) * ratio)
                    colored += f"\033[38;2;{r};{g};{b}m{char}"
                colored += "\033[0m"
                res.append(colored)
            return '\n'.join(res)

        splash = "\n" + _gradient(full_splash, "00F0FF", "8A2BE2") + "\n"
        
        # Try to print with UTF-8 encoding
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            print(splash)
        except Exception:
            # Fallback to plain text if UTF-8 fails
            print("\n" + full_splash.replace("║", "|").replace("═", "=").replace("╔", "+").replace("╗", "+").replace("╚", "+").replace("╝", "+") + "\n")
        await self.log(f"Launching {self.config['system']['name']} v{self.config.get('system',{}).get('version','?')} (Async)...", priority=1)

        await self.setup_systems()
        await self.imprint_workspace()

        # Remote access warning
        web_cfg = self.config.get('web', {})
        if web_cfg.get('remote_access', False):
            port = web_cfg.get('port', 17789)
            await self.log(f"REMOTE ACCESS ENABLED - Galactic AI is accessible from the network on port {port}", priority=1)
            # Auto-generate JWT secret if missing
            if not web_cfg.get('jwt_secret'):
                from remote_access import generate_api_secret
                web_cfg['jwt_secret'] = generate_api_secret()
                self.config['web'] = web_cfg
                try:
                    self.save_config()  # writes to the gitignored overlay
                except Exception:
                    pass
            # Auto-add Windows Firewall rule for the Control Deck port
            if os.name == 'nt':
                await self._ensure_firewall_rule(port)

        # Console window title: name + version + deck port (Windows)
        if os.name == 'nt':
            try:
                import ctypes
                _deck_port = self.config.get('web', {}).get('port', 17789)
                ctypes.windll.kernel32.SetConsoleTitleW(
                    f"Galactic AI v{self.VERSION} — Control Deck :{_deck_port}")
            except Exception:
                pass

        # Start Bridge (Socket Server)
        server_port = self.config.get('system', {}).get('port', 9999)
        server = await asyncio.start_server(self.handle_client, '127.0.0.1', server_port)



        # Start Tasks
        asyncio.create_task(self.relay.route_loop())
        asyncio.create_task(self.telegram.listen_loop())
        asyncio.create_task(self.web.run())
        asyncio.create_task(self.scheduler.run())
        asyncio.create_task(self.ollama_manager.auto_discover_loop())
        if getattr(self, 'lmstudio_manager', None):
            asyncio.create_task(self.lmstudio_manager.auto_discover_loop())
        asyncio.create_task(self._recovery_check_loop())
        asyncio.create_task(self._update_check_loop())
        asyncio.create_task(self._terminal_input_loop())

        # Optional bridges — only start when enabled AND configured.
        if self.discord and self.config.get('discord', {}).get('enabled') and self.discord.is_configured():
            asyncio.create_task(self.discord.run_bot())
            await self.log("💬 Discord bridge starting…", priority=2)
        gmail_cfg = self.config.get('gmail', {})
        if self.gmail and gmail_cfg.get('enabled') and gmail_cfg.get('email') and gmail_cfg.get('app_password'):
            asyncio.create_task(self.gmail.poll_loop())
            await self.log("📧 Gmail bridge starting…", priority=2)

        # Start Skills
        for skill in self.skills:
            asyncio.create_task(skill.run())

        await self._preflight_report()
        await self.log(f"All systems online. Control Deck → http://{self.config.get('web', {}).get('host', '127.0.0.1')}:{self.config.get('web', {}).get('port', 17789)}", priority=1)
        await self.log("Press Ctrl+C to shut down.", priority=3)

        # Wait for shutdown signal instead of serve_forever
        async with server:
            await shutdown_event.wait()
            server.close()
            await server.wait_closed()
            await self.shutdown()

if __name__ == "__main__":
    if sys.platform == 'win32':
        # Workaround for annoying asyncio closed pipe / event loop closed exceptions on shutdown
        import asyncio, functools
        from asyncio.proactor_events import _ProactorBasePipeTransport
        
        def silence_event_loop_closed(func):
            @functools.wraps(func)
            def wrapper(self, *args, **kwargs):
                try:
                    return func(self, *args, **kwargs)
                except (RuntimeError, ValueError):
                    pass
            return wrapper
            
        def silence_connection_reset(func):
            @functools.wraps(func)
            def wrapper(self, *args, **kwargs):
                try:
                    return func(self, *args, **kwargs)
                except ConnectionResetError:
                    pass
            return wrapper
            
        _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
        if hasattr(_ProactorBasePipeTransport, '_call_connection_lost'):
            _ProactorBasePipeTransport._call_connection_lost = silence_connection_reset(_ProactorBasePipeTransport._call_connection_lost)
        try:
            from asyncio.base_subprocess import BaseSubprocessTransport
            BaseSubprocessTransport.__del__ = silence_event_loop_closed(BaseSubprocessTransport.__del__)
        except ImportError:
            pass

    def _write_crash_log(exc: BaseException, origin: str) -> str:
        """Persist a crash report so a dead console window never eats the
        reason. Returns the file path (or '' on failure)."""
        import traceback as _tb
        try:
            crash_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'crashes')
            os.makedirs(crash_dir, exist_ok=True)
            path = os.path.join(crash_dir, f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"Galactic AI v{GalacticCore.VERSION} crash report\n")
                f.write(f"Time   : {datetime.now().isoformat()}\n")
                f.write(f"Origin : {origin}\n")
                f.write(f"Python : {sys.version}\n\n")
                f.write("".join(_tb.format_exception(type(exc), exc, exc.__traceback__)))
            return path
        except Exception:
            return ''

    # Background (daemon) thread crashes shouldn't vanish silently either.
    import threading as _threading
    def _thread_crash_hook(args):
        if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            return
        p = _write_crash_log(args.exc_value, f"thread:{getattr(args.thread, 'name', '?')}")
        if p:
            print(f"[Core] Background thread crashed — report saved: {p}")
    _threading.excepthook = _thread_crash_hook

    core = GalacticCore()
    try:
        asyncio.run(core.main_loop())
    except (KeyboardInterrupt, SystemExit):
        pass  # Already handled by signal handler — exit cleanly
    except Exception as e:
        p = _write_crash_log(e, "main loop")
        print(f"\n[Core] FATAL: {e.__class__.__name__}: {e}")
        if p:
            print(f"[Core] Full crash report saved: {p}")
        raise

