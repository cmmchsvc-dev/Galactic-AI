import asyncio
import json
import os
import signal
import sys
import yaml
import time
import logging
from datetime import datetime

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

class GalacticCore:
    def __init__(self, config_path='config.yaml'):
        self.config_path = config_path
        self.config = self.load_config()
        self.plugins = []
        self.clients = []
        self.relay = GalacticRelay(self)
        self.running = True
        self.loop = None
        self.start_time = time.time()

    def load_config(self):
        config_full_path = os.path.abspath(self.config_path)
        if not os.path.exists(config_full_path):
            default_config = {
                'system': {'name': 'Galactic Core', 'port': 9999},
                'paths': {'logs': './logs', 'images': './images', 'plugins': './plugins'},
                'gateway': {'provider': 'placeholder', 'model': 'placeholder'}
            }
            return default_config
        with open(config_full_path, 'r') as f:
            config = yaml.load(f, Loader=yaml.FullLoader) or {}

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
        sys_defaults = {'update_check_interval': 21600, 'version': '1.0.5'}
        if 'system' not in config:
            config['system'] = {'name': 'Galactic AI', 'port': 9999}
            config['system'].update(sys_defaults)
            migrated = True
        else:
            for key, value in sys_defaults.items():
                if key not in config['system']:
                    config['system'][key] = value
                    migrated = True

        # Save migrated config
        if migrated:
            try:
                with open(config_full_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            except Exception:
                pass  # Non-fatal — config still works in memory

        return config

    async def setup_systems(self):
        """Initialize core sub-systems."""
        from gateway_v2 import GalacticGateway
        from memory_module_v2 import GalacticMemory
        from telegram_bridge import TelegramBridge
        from web_deck import GalacticWebDeck
        from scheduler import GalacticScheduler
        from model_manager import ModelManager
        
        self.memory = GalacticMemory(self)
        self.gateway = GalacticGateway(self)
        self.model_manager = ModelManager(self)

        # Ollama Manager — robust local model support (health, discovery, context windows)
        from ollama_manager import OllamaManager
        self.ollama_manager = OllamaManager(self)
        await self.ollama_manager.health_check()
        await self.ollama_manager.discover_models()

        self.telegram = TelegramBridge(self)
        self.web = GalacticWebDeck(self)
        self.scheduler = GalacticScheduler(self)

        # Set initial model from ModelManager
        initial_model = self.model_manager.get_current_model()
        self.gateway.llm.provider = initial_model['provider']
        self.gateway.llm.model = initial_model['model']
        self.model_manager._set_api_key(initial_model['provider'])
        
        # Initialize Plugins — all optional, missing files are skipped gracefully
        _BUILTIN_PLUGINS = [
            ('plugins.shell_executor',      'ShellPlugin'),
            ('plugins.browser_executor_pro','BrowserExecutorPro'),
            ('plugins.subagent_manager',    'SubAgentPlugin'),
            ('plugins.desktop_tool',        'DesktopTool'),
        ]
        loaded_plugin_names = []
        for module_path, class_name in _BUILTIN_PLUGINS:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self.plugins.append(cls(self))
                loaded_plugin_names.append(class_name)
            except ModuleNotFoundError:
                await self.log(f"[Plugin] {class_name} not found — skipping (remove the file to disable permanently)", priority=3)
            except Exception as e:
                await self.log(f"[Plugin] {class_name} failed to load: {e}", priority=2)

        # Ensure browser executor is available (after plugins are loaded)
        browser_plugin = next((p for p in self.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if browser_plugin:
            self.browser = browser_plugin

        await self.log(f"Systems initialized. Plugins loaded: {', '.join(loaded_plugin_names) or 'none'}", priority=2)

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
        print(log_entry)

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

        await self.relay.emit(priority, "log", log_entry)

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
            self.clients.remove(writer)
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

            await asyncio.sleep(max(interval, 3600))

    @staticmethod
    def _version_newer(latest, current):
        """Compare semver strings. Returns True if latest > current."""
        try:
            l = [int(x) for x in latest.split('.')]
            c = [int(x) for x in current.split('.')]
            return l > c
        except (ValueError, AttributeError):
            return False

    async def shutdown(self):
        """Graceful shutdown — close all subsystems cleanly."""
        if not self.running:
            return
        self.running = False
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] [Core] Shutting down Galactic AI...")

        # Cancel all background tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

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

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [Core] Galactic AI shut down cleanly. See you among the stars.")

    async def main_loop(self):
        self.loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown (Ctrl+C)
        shutdown_event = asyncio.Event()

        def _signal_handler():
            if shutdown_event.is_set():
                return  # Already shutting down
            shutdown_event.set()

        # Windows uses signal.signal(); Unix can use loop.add_signal_handler()
        if sys.platform == 'win32':
            # On Windows, asyncio signal handling is limited — use signal module
            def _win_handler(sig, frame):
                _signal_handler()
            signal.signal(signal.SIGINT, _win_handler)
            signal.signal(signal.SIGTERM, _win_handler)
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                self.loop.add_signal_handler(sig, _signal_handler)

        # GALACTIC AI SPLASH SCREEN
        splash = f"""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ██████╗  █████╗ ██╗      █████╗  ██████╗████████╗██╗ ██████╗║
║  ██╔════╝ ██╔══██╗██║     ██╔══██╗██╔════╝╚══██╔══╝██║██╔════╝║
║  ██║  ███╗███████║██║     ███████║██║        ██║   ██║██║     ║
║  ██║   ██║██╔══██║██║     ██╔══██║██║        ██║   ██║██║     ║
║  ╚██████╔╝██║  ██║███████╗██║  ██║╚██████╗   ██║   ██║╚██████╗║
║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝   ╚═╝   ╚═╝ ╚═════╝║
║                                                               ║
║               * * *  AUTOMATION SUITE  * * *                  ║
║                      v{self.config.get('system',{}).get('version','?')}                                   ║
║                   Sovereign - Universal - Fast                ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
        # Try to print with UTF-8 encoding
        try:
            print(splash.encode('utf-8').decode('utf-8'))
        except:
            print(splash)
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
                    import yaml
                    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
                except Exception:
                    pass
            # Auto-add Windows Firewall rule for the Control Deck port
            if os.name == 'nt':
                await self._ensure_firewall_rule(port)

        # Start Bridge (Socket Server)
        server = await asyncio.start_server(self.handle_client, '127.0.0.1', self.config['system']['port'])

        # Start Tasks
        asyncio.create_task(self.relay.route_loop())
        asyncio.create_task(self.telegram.listen_loop())
        asyncio.create_task(self.web.run())
        asyncio.create_task(self.scheduler.run())
        asyncio.create_task(self.ollama_manager.auto_discover_loop())
        asyncio.create_task(self._recovery_check_loop())
        asyncio.create_task(self._update_check_loop())

        # Start Plugins
        for plugin in self.plugins:
            asyncio.create_task(plugin.run())

        await self.log(f"All systems online. Control Deck → http://{self.config.get('web', {}).get('host', '127.0.0.1')}:{self.config.get('web', {}).get('port', 17789)}", priority=1)
        await self.log("Press Ctrl+C to shut down.", priority=3)

        # Wait for shutdown signal instead of serve_forever
        async with server:
            await shutdown_event.wait()
            server.close()
            await server.wait_closed()
            await self.shutdown()

if __name__ == "__main__":
    core = GalacticCore()
    try:
        asyncio.run(core.main_loop())
    except (KeyboardInterrupt, SystemExit):
        pass  # Already handled by signal handler — exit cleanly
