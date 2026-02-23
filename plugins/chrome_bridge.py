"""
Galactic AI -- Chrome Bridge Plugin
Bridges the AI tool system to a Chrome extension via WebSocket.

Architecture:
  - The Chrome extension connects to web_deck.py over WebSocket.
  - web_deck.py routes extension messages to this plugin via handle_ws_message().
  - This plugin sends commands to the extension and awaits results using asyncio Futures.
  - Gateway tool handlers call the convenience methods (screenshot, navigate, etc.)
    which wrap send_command() with typed arguments.
"""

import asyncio
import json
import logging
import uuid

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Base class (matches project convention)
# ──────────────────────────────────────────────────────────────────────────────
class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True

    async def run(self):
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Chrome Bridge
# ──────────────────────────────────────────────────────────────────────────────
class ChromeBridge(GalacticPlugin):
    """Python-side bridge between Galactic AI and a Chrome extension.

    The extension connects via WebSocket (handled by web_deck.py) and this
    plugin provides an async request/response layer on top of that connection.
    Each outbound command gets a unique *request_id*; the extension echoes it
    back in the result so we can resolve the correct Future.
    """

    def __init__(self, core):
        super().__init__(core)
        self.name = "ChromeBridge"

        # WebSocket state -- set by web_deck.py when the extension connects
        self.ws_connection = None
        self._connected = False

        # Pending commands: {request_id: asyncio.Future}
        self._pending: dict[str, asyncio.Future] = {}

        # Default timeout for commands (seconds)
        self.timeout: int = 30

        # Cache of known tabs: {tab_id: {"title": ..., "url": ...}}
        self._tabs: dict[int, dict] = {}

    # ── Connection property ──────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """True only when we have a live WebSocket **and** the extension said hello."""
        return self._connected and self.ws_connection is not None

    # ── Inbound message handler (called by web_deck) ─────────────────────

    async def handle_ws_message(self, msg_data: str) -> None:
        """Called by web_deck.py whenever the Chrome extension sends a message.

        Expected message shapes:
          {"type": "hello",        "capabilities": [...], "tabs": [...]}
          {"type": "result",       "id": "<request_id>", "data": {...}}
          {"type": "tabs_update",  "tabs": [...]}
          {"type": "disconnect"}
        """
        try:
            payload = json.loads(msg_data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("ChromeBridge: invalid JSON from extension: %s", exc)
            return

        msg_type = payload.get("type")

        if msg_type == "hello":
            self._connected = True
            capabilities = payload.get("capabilities", [])
            tabs = payload.get("tabs", [])
            self._update_tabs_cache(tabs)
            await self.core.log(
                f"Chrome extension connected  |  "
                f"capabilities: {capabilities}  |  "
                f"tabs: {len(self._tabs)}",
                priority=2,
                component="ChromeBridge",
            )

        elif msg_type == "result":
            request_id = payload.get("id")
            if request_id and request_id in self._pending:
                future = self._pending.pop(request_id)
                if not future.done():
                    future.set_result(payload.get("data"))
            else:
                logger.debug(
                    "ChromeBridge: received result for unknown id=%s", request_id
                )

        elif msg_type == "tabs_update":
            tabs = payload.get("tabs", [])
            self._update_tabs_cache(tabs)
            logger.debug("ChromeBridge: tabs cache refreshed (%d tabs)", len(self._tabs))

        elif msg_type == "disconnect":
            self._connected = False
            await self.core.log(
                "Chrome extension disconnected",
                priority=2,
                component="ChromeBridge",
            )

        elif msg_type == "pong":
            # Keepalive response -- nothing to do
            pass

        else:
            logger.debug("ChromeBridge: unhandled message type '%s'", msg_type)

    # ── Outbound command dispatcher ──────────────────────────────────────

    async def send_command(self, command: str, args: dict | None = None) -> dict:
        """Send a command to the Chrome extension and wait for the result.

        Returns the result dict on success, or an ``{"error": "..."}`` dict
        on connection / timeout / transport failure.
        """
        if not self.connected:
            return {"error": "Chrome extension not connected. Ensure the extension is running and connected via WebSocket."}

        request_id = uuid.uuid4().hex[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        envelope = json.dumps({
            "type": "command",
            "id": request_id,
            "command": command,
            "args": args or {},
        })

        try:
            await self.ws_connection.send_str(envelope)
        except Exception as exc:
            self._pending.pop(request_id, None)
            self._connected = False
            self.ws_connection = None
            logger.error("ChromeBridge: send failed: %s", exc)
            return {"error": f"Failed to send command '{command}': {exc}"}

        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning("ChromeBridge: command '%s' (id=%s) timed out after %ds",
                           command, request_id, self.timeout)
            return {"error": f"Command '{command}' timed out after {self.timeout}s"}
        except asyncio.CancelledError:
            return {"error": f"Command '{command}' was cancelled"}
        except Exception as exc:
            logger.error("ChromeBridge: unexpected error awaiting '%s': %s", command, exc)
            return {"error": f"Command '{command}' failed: {exc}"}
        finally:
            # Guarantee cleanup regardless of outcome
            self._pending.pop(request_id, None)

    # ── Background loop (keepalive) ──────────────────────────────────────

    async def run(self) -> None:
        """Background loop -- log status and send periodic keepalive pings."""
        await self.core.log(
            "Chrome Bridge waiting for extension connection...",
            priority=2,
            component="ChromeBridge",
        )
        while self.enabled:
            if self._connected and self.ws_connection:
                try:
                    await self.ws_connection.send_str('{"type":"ping"}')
                except Exception:
                    self._connected = False
                    self.ws_connection = None
            await asyncio.sleep(20)

    # ── Convenience methods (used by gateway tool handlers) ──────────────

    async def screenshot(self, tab_id=None):
        """Capture a screenshot of the active (or specified) tab."""
        return await self.send_command("screenshot", {"tab_id": tab_id})

    async def navigate(self, url: str, tab_id=None):
        """Navigate a tab to the given URL."""
        return await self.send_command("navigate", {"url": url, "tab_id": tab_id})

    async def read_page(self, tab_id=None, filter_val: str = 'all', depth: int = 15):
        """Get an accessibility-tree representation of the page.

        filter_val: 'all' (default) or 'interactive' (buttons/links/inputs only).
        Content.js reads this as args.filter.
        """
        return await self.send_command("read_page", {
            "tab_id": tab_id,
            "filter": filter_val,
            "depth": depth,
        })

    async def find_element(self, query: str, tab_id=None):
        """Find elements on the page using natural-language search."""
        return await self.send_command("find_element", {"query": query, "tab_id": tab_id})

    async def click(self, selector=None, ref=None, coordinate=None, tab_id=None):
        """Click an element by CSS selector, ref ID, or viewport coordinate."""
        return await self.send_command("click", {
            "selector": selector,
            "ref": ref,
            "coordinate": coordinate,
            "tab_id": tab_id,
        })

    async def type_text(self, text: str, selector=None, ref=None, clear: bool = True, tab_id=None):
        """Type text into a focused element or one identified by selector/ref."""
        return await self.send_command("type", {
            "text": text,
            "selector": selector,
            "ref": ref,
            "clear": clear,
            "tab_id": tab_id,
        })

    async def scroll(self, direction: str = "down", amount: int = 3, selector=None, tab_id=None):
        """Scroll the page or a specific element."""
        return await self.send_command("scroll", {
            "direction": direction,
            "amount": amount,
            "selector": selector,
            "tab_id": tab_id,
        })

    async def form_input(self, ref: str, value, tab_id=None):
        """Set the value of a form element identified by ref."""
        return await self.send_command("form_input", {
            "ref": ref,
            "value": value,
            "tab_id": tab_id,
        })

    async def execute_js(self, script: str, tab_id=None):
        """Execute arbitrary JavaScript in the tab's page context."""
        return await self.send_command("execute_js", {"script": script, "tab_id": tab_id})

    async def get_page_text(self, tab_id=None):
        """Extract the raw text content from the page."""
        return await self.send_command("get_page_text", {"tab_id": tab_id})

    async def tabs_list(self):
        """List all open tabs."""
        return await self.send_command("tabs_list", {})

    async def tabs_create(self, url: str | None = None):
        """Create a new tab, optionally navigating to *url*."""
        return await self.send_command("tabs_create", {"url": url})

    async def key_press(self, key: str, tab_id=None):
        """Press a keyboard key or shortcut (e.g. ``Enter``, ``ctrl+a``)."""
        return await self.send_command("key_press", {"key": key, "tab_id": tab_id})

    async def read_console(self, tab_id=None, pattern: str | None = None, level: str | None = None):
        """Read browser console messages, optionally filtered."""
        return await self.send_command("read_console", {
            "tab_id": tab_id,
            "pattern": pattern,
            "level": level,
        })

    async def read_network(self, tab_id=None, url_pattern: str | None = None):
        """Read captured network requests, optionally filtered by URL pattern."""
        return await self.send_command("read_network", {
            "tab_id": tab_id,
            "url_pattern": url_pattern,
        })

    async def hover(self, selector=None, ref=None, coordinate=None, tab_id=None):
        """Move the mouse cursor to an element without clicking."""
        return await self.send_command("hover", {
            "selector": selector,
            "ref": ref,
            "coordinate": coordinate,
            "tab_id": tab_id,
        })

    # ── Internal helpers ─────────────────────────────────────────────────

    def _update_tabs_cache(self, tabs_list: list) -> None:
        """Rebuild the internal tabs cache from a list of tab dicts."""
        self._tabs.clear()
        for tab in tabs_list:
            tab_id = tab.get("id") or tab.get("tab_id")
            if tab_id is not None:
                self._tabs[tab_id] = {
                    "title": tab.get("title", ""),
                    "url": tab.get("url", ""),
                }
