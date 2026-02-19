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
                'paths': {'logs': './logs', 'plugins': './plugins'},
                'gateway': {'provider': 'placeholder', 'model': 'placeholder'}
            }
            return default_config
        with open(config_full_path, 'r') as f:
            return yaml.load(f, Loader=yaml.FullLoader) or {}

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
            ('plugins.sniper',              'SniperPlugin'),
            ('plugins.watchdog',            'WatchdogPlugin'),
            ('plugins.shell_executor',      'ShellPlugin'),
            ('plugins.browser_executor_pro','BrowserExecutorPro'),
            ('plugins.subagent_manager',    'SubAgentPlugin'),
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
        workspace_files = ['USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md']
        for file in workspace_files:
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', file)
            if os.path.exists(file_path):
                await self.memory.imprint_file(file_path)
        await self.log("Workspace Imprint Complete.", priority=2)

    async def log(self, message, priority=3):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [Core] {message}"
        print(log_entry)
        await self.relay.emit(priority, "log", log_entry)

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
        splash = """
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
║                      v0.6.0-Alpha (AsyncIO)                   ║
║                   Sovereign - Universal - Fast                ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
        # Try to print with UTF-8 encoding
        try:
            print(splash.encode('utf-8').decode('utf-8'))
        except:
            print(splash)
        await self.log(f"Launching {self.config['system']['name']} v0.6.0 (Async)...", priority=1)

        await self.setup_systems()
        await self.imprint_workspace()

        # Start Bridge (Socket Server)
        server = await asyncio.start_server(self.handle_client, '127.0.0.1', self.config['system']['port'])

        # Start Tasks
        asyncio.create_task(self.relay.route_loop())
        asyncio.create_task(self.telegram.listen_loop())
        asyncio.create_task(self.web.run())
        asyncio.create_task(self.scheduler.run())
        asyncio.create_task(self.ollama_manager.auto_discover_loop())

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
