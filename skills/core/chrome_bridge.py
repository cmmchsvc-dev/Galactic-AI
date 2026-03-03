"""
Galactic AI -- ChromeBridge Skill (Phase 3 migration)
Bridges the AI tool system to a Chrome extension via WebSocket.

Architecture:
  - The Chrome extension connects to web_deck.py over WebSocket.
  - web_deck.py routes extension messages to this skill via handle_ws_message().
  - This skill sends commands to the extension and awaits results using asyncio Futures.
  - Tool handlers call the convenience methods (screenshot, navigate, etc.)
    which wrap send_command() with typed arguments.
"""

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from skills.base import GalacticSkill

logger = logging.getLogger(__name__)


class ChromeBridgeSkill(GalacticSkill):
    """Python-side bridge between Galactic AI and a Chrome extension.

    The extension connects via WebSocket (handled by web_deck.py) and this
    skill provides an async request/response layer on top of that connection.
    Each outbound command gets a unique *request_id*; the extension echoes it
    back in the result so we can resolve the correct Future.
    """

    skill_name  = "chrome_bridge"
    version     = "1.1.9"
    author      = "Galactic AI"
    description = "Chrome extension WebSocket bridge for real browser control."
    category    = "browser"
    icon        = "\U0001f310"

    # Legacy name used by web_deck.py to find this skill via class name check
    name = "ChromeBridge"

    def __init__(self, core):
        super().__init__(core)

        # WebSocket state -- set by web_deck.py when the extension connects
        self.ws_connection = None
        self._connected = False

        # Pending commands: {request_id: asyncio.Future}
        self._pending: dict[str, asyncio.Future] = {}

        # Default timeout for commands (seconds)
        self.timeout: int = 30

        # Cache of known tabs: {tab_id: {"title": ..., "url": ...}}
        self._tabs: dict[int, dict] = {}

        # GIF recorder state
        self._gif_recording = False
        self._gif_frames: list[bytes] = []
        self._gif_task = None  # asyncio task for polling loop

    # ── Metadata property (web_deck compat) ─────────────────────────────

    @property
    def connected(self) -> bool:
        """True only when we have a live WebSocket and the extension said hello."""
        return self._connected and self.ws_connection is not None

    # ── GalacticSkill: tool definitions ─────────────────────────────────

    def get_tools(self):
        return {
            "chrome_screenshot": {
                "description": "Take a screenshot of the active tab in the user's real Chrome browser (via Galactic Browser extension). Returns a JPEG image.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_chrome_screenshot
            },
            "chrome_navigate": {
                "description": "Navigate the user's real Chrome browser to a URL, or use 'back'/'forward' for history navigation.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string", "description": "URL to navigate to, or 'back'/'forward'"},
                }, "required": ["url"]},
                "fn": self._tool_chrome_navigate
            },
            "chrome_read_page": {
                "description": "Get an accessibility tree snapshot of the current page in the user's Chrome browser. Returns element roles, names, and ref IDs for interaction.",
                "parameters": {"type": "object", "properties": {
                    "filter": {"type": "string", "description": "Filter: 'interactive' for buttons/links/inputs only, 'all' for everything (default: all)"},
                }},
                "fn": self._tool_chrome_read_page
            },
            "chrome_find": {
                "description": "Find elements on the page by CSS selector or text content. Returns matching elements with ref IDs.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "CSS selector or text to search for"},
                }, "required": ["query"]},
                "fn": self._tool_chrome_find
            },
            "chrome_click": {
                "description": "Click an element in the user's Chrome browser by ref ID, CSS selector, or coordinates.",
                "parameters": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "Element ref ID from chrome_read_page (e.g. 'ref_1')"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                    "double_click": {"type": "boolean", "description": "Double-click instead of single click"},
                }},
                "fn": self._tool_chrome_click
            },
            "chrome_type": {
                "description": "Type text into the focused element or a specified element in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                    "ref": {"type": "string", "description": "Element ref ID to type into"},
                    "selector": {"type": "string", "description": "CSS selector of element to type into"},
                    "clear": {"type": "boolean", "description": "Clear existing content before typing (default: true)"},
                }, "required": ["text"]},
                "fn": self._tool_chrome_type
            },
            "chrome_scroll": {
                "description": "Scroll the page or a specific element in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "direction": {"type": "string", "description": "Scroll direction: up, down, left, right"},
                    "amount": {"type": "number", "description": "Scroll amount in pixels (default: 300)"},
                    "ref": {"type": "string", "description": "Element ref ID to scroll into view"},
                    "selector": {"type": "string", "description": "CSS selector of element to scroll into view"},
                }},
                "fn": self._tool_chrome_scroll
            },
            "chrome_form_input": {
                "description": "Set the value of a form element (input, select, checkbox) in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "Element ref ID"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "value": {"type": "string", "description": "Value to set"},
                }, "required": ["value"]},
                "fn": self._tool_chrome_form_input
            },
            "chrome_execute_js": {
                "description": "Execute JavaScript code in the user's Chrome browser tab. Returns the result of the last expression.",
                "parameters": {"type": "object", "properties": {
                    "code": {"type": "string", "description": "JavaScript code to execute"},
                }, "required": ["code"]},
                "fn": self._tool_chrome_execute_js
            },
            "chrome_get_text": {
                "description": "Extract all text content from the current page in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_chrome_get_text
            },
            "chrome_tabs_list": {
                "description": "List all open tabs in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_chrome_tabs_list
            },
            "chrome_tabs_create": {
                "description": "Open a new tab in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string", "description": "URL to open (default: new tab page)"},
                }},
                "fn": self._tool_chrome_tabs_create
            },
            "chrome_key_press": {
                "description": "Press keyboard key(s) in the user's Chrome browser. Supports modifiers like ctrl+a, shift+Enter.",
                "parameters": {"type": "object", "properties": {
                    "key": {"type": "string", "description": "Key to press (e.g. 'Enter', 'Tab', 'ctrl+a')"},
                    "repeat": {"type": "number", "description": "Number of times to repeat (default: 1)"},
                }, "required": ["key"]},
                "fn": self._tool_chrome_key_press
            },
            "chrome_read_console": {
                "description": "Read browser console messages from the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to filter messages"},
                    "clear": {"type": "boolean", "description": "Clear messages after reading"},
                }},
                "fn": self._tool_chrome_read_console
            },
            "chrome_read_network": {
                "description": "Read network requests made by the current page in the user's Chrome browser. Each entry includes a request_id field that can be passed to chrome_get_network_body to retrieve the full response body.",
                "parameters": {"type": "object", "properties": {
                    "url_pattern": {"type": "string", "description": "Filter by URL substring"},
                    "clear": {"type": "boolean", "description": "Clear requests after reading"},
                }},
                "fn": self._tool_chrome_read_network
            },
            "chrome_get_network_body": {
                "description": "Get the full response body for a captured network request. Use request_id from chrome_read_network output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string", "description": "Request ID from chrome_read_network output (e.g. '12345.678')"}
                    },
                    "required": ["request_id"]
                },
                "fn": self._tool_chrome_get_network_body
            },
            "chrome_hover": {
                "description": "Hover over an element in the user's Chrome browser to trigger hover states, tooltips, or menus.",
                "parameters": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "Element ref ID"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                }},
                "fn": self._tool_chrome_hover
            },
            "chrome_zoom": {
                "description": "Capture a cropped region of the Chrome browser for close inspection of small elements (icons, buttons, form fields). region=[x0,y0,x1,y1] in pixels from top-left of viewport. Returns a JPEG of just that region.",
                "parameters": {"type": "object", "properties": {
                    "region": {"type": "array", "description": "Bounding box [x0, y0, x1, y1] in pixels from viewport top-left. E.g. [0, 0, 200, 200] for top-left 200x200px"},
                }, "required": ["region"]},
                "fn": self._tool_chrome_zoom
            },
            "chrome_drag": {
                "description": "Drag from one coordinate to another in Chrome for drag-and-drop interactions, sliders, and reordering.",
                "parameters": {"type": "object", "properties": {
                    "start_x": {"type": "number", "description": "Starting X coordinate"},
                    "start_y": {"type": "number", "description": "Starting Y coordinate"},
                    "end_x": {"type": "number", "description": "Ending X coordinate"},
                    "end_y": {"type": "number", "description": "Ending Y coordinate"},
                }, "required": ["start_x", "start_y", "end_x", "end_y"]},
                "fn": self._tool_chrome_drag
            },
            "chrome_right_click": {
                "description": "Right-click at a ref, selector, or coordinates in Chrome. Triggers JavaScript-based context menus (custom dropdowns, right-click menus on apps like Reddit, Notion). Note: cannot open the native browser context menu due to browser security restrictions.",
                "parameters": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "Element ref ID from chrome_read_page"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                }},
                "fn": self._tool_chrome_right_click
            },
            "chrome_triple_click": {
                "description": "Triple-click an element in Chrome to select all its text content. Use before typing to replace existing text.",
                "parameters": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "Element ref ID from chrome_read_page"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                }},
                "fn": self._tool_chrome_triple_click
            },
            "chrome_upload": {
                "description": "Upload a local file to a <input type='file'> element. Requires the absolute file path on disk. Target with ref or selector (selector takes priority if both provided).",
                "parameters": {"type": "object", "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file to upload"},
                    "ref": {"type": "string", "description": "Element reference ID (e.g. ref_123)"},
                    "selector": {"type": "string", "description": "CSS selector for the file input"},
                }, "required": ["file_path"]},
                "fn": self._tool_chrome_upload
            },
            "chrome_resize": {
                "description": "Resize the Chrome viewport. Presets: mobile (375\u00d7812), tablet (768\u00d71024), desktop (1280\u00d7800). Or provide custom width and height in pixels.",
                "parameters": {"type": "object", "properties": {
                    "preset": {"type": "string", "description": "Device preset: mobile, tablet, or desktop"},
                    "width": {"type": "number", "description": "Custom viewport width in pixels"},
                    "height": {"type": "number", "description": "Custom viewport height in pixels"},
                }, "required": []},
                "fn": self._tool_chrome_resize
            },
            "chrome_wait_for": {
                "description": "Wait for a specific element (CSS selector) or text content to appear on the current page in the user's Chrome browser.",
                "parameters": {"type": "object", "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for"},
                    "text": {"type": "string", "description": "Text content to wait for"},
                    "timeout": {"type": "number", "description": "Max wait time in milliseconds (default: 10000)"},
                }},
                "fn": self._tool_chrome_wait_for
            },
            "chrome_wait": {
                "description": "Wait for N seconds. Use to let pages load, animations settle, or rate-limit between actions.",
                "parameters": {
                    "seconds": {"type": "number", "description": "Number of seconds to wait (max 30)"}
                },
                "required": ["seconds"],
                "fn": self._tool_chrome_wait
            },
            "chrome_gif_start": {
                "description": "Start recording the browser as an animated GIF. Captures screenshots at the specified frame rate. Call chrome_gif_stop when done, then chrome_gif_export to save.",
                "parameters": {
                    "fps": {"type": "number", "description": "Frames per second (default: 2, max: 5)"}
                },
                "required": [],
                "fn": self._tool_chrome_gif_start
            },
            "chrome_gif_stop": {
                "description": "Stop the GIF recording. Frames are kept in memory. Call chrome_gif_export to save the GIF.",
                "parameters": {},
                "required": [],
                "fn": self._tool_chrome_gif_stop
            },
            "chrome_gif_export": {
                "description": "Export the recorded frames as an animated GIF. Saves to logs/recordings/ and returns the file path.",
                "parameters": {
                    "filename": {"type": "string", "description": "Output filename (without .gif extension). Defaults to timestamp."},
                    "frame_duration_ms": {"type": "number", "description": "Duration per frame in milliseconds (default: 500)"}
                },
                "required": [],
                "fn": self._tool_chrome_gif_export
            },
        }

    # ── Tool handlers ────────────────────────────────────────────────────

    async def _tool_chrome_screenshot(self, args):
        if not self.ws_connection:
            return "[ERROR] Chrome extension not connected. Install the Galactic Browser extension and click Connect."
        result = await self.screenshot()
        if result.get('status') == 'success':
            img_data = result.get('image_b64', '')
            if not img_data:
                return "[ERROR] Chrome screenshot: no image data returned"

            # Save to images/browser/ directory (consistent with Playwright screenshot tool)
            try:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                img_subdir = Path(images_dir) / 'browser'
                img_subdir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                path = str(img_subdir / f'chrome_{ts}.jpg')
                
                # Strip data URI prefix if present
                clean_b64 = img_data.split(',', 1)[1] if ',' in img_data and img_data.startswith('data:') else img_data
                
                raw = base64.b64decode(clean_b64)
                with open(path, 'wb') as f:
                    f.write(raw)
                # Return special dict that gateway detects and renders as a vision message
                return {"__image_b64__": img_data, "path": path, "media_type": "image/jpeg",
                        "text": f"[CHROME] Screenshot saved: {path}"}
            except Exception as e:
                return f"[CHROME] Screenshot captured ({len(img_data)} chars base64) — save failed: {e}"
        return f"[ERROR] Chrome screenshot: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_zoom(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        region = args.get('region')
        if not region or len(region) != 4:
            return "[ERROR] chrome_zoom: region must be [x0, y0, x1, y1]"
        result = await self.zoom(region=region)
        if result.get('status') == 'success':
            img_data = result.get('image_b64', '')
            if not img_data:
                return "[ERROR] Chrome zoom: no image data returned"
            try:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                img_subdir = Path(images_dir) / 'browser'
                img_subdir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                path = str(img_subdir / f'chrome_zoom_{ts}.jpg')
                
                # Strip data URI prefix if present
                clean_b64 = img_data.split(',', 1)[1] if ',' in img_data and img_data.startswith('data:') else img_data
                
                with open(path, 'wb') as f:
                    f.write(base64.b64decode(clean_b64))
                return {"__image_b64__": img_data, "path": path, "media_type": "image/jpeg",
                        "text": f"[CHROME] Zoomed region {region} saved: {path}"}
            except Exception as e:
                return f"[CHROME] Zoom captured — save failed: {e}"
        return f"[ERROR] Chrome zoom: {result.get('error') or result.get('message') or 'unknown'}"

    async def _tool_chrome_navigate(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        url = args.get('url', '')
        result = await self.navigate(url)
        if result.get('status') == 'success':
            return f"[CHROME] Navigated to: {result.get('url', url)}"
        return f"[ERROR] Chrome navigate: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_read_page(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.read_page(
            tab_id=args.get('tab_id'),
            filter_val=args.get('filter', 'all'),
        )
        if result.get('status') == 'success':
            tree = result.get('tree', '')
            refs = result.get('ref_count', 0)
            return f"[CHROME] Page snapshot ({refs} refs):\n{tree}"
        return f"[ERROR] Chrome read_page: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_find(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.find_element(args.get('query', ''))
        if result.get('status') == 'success':
            elements = result.get('elements', [])
            if not elements:
                return "[CHROME] No elements found matching query."
            lines = [f"[CHROME] Found {len(elements)} element(s):"]
            for el in elements[:20]:
                ref = el.get('ref', '?')
                tag = el.get('tag', '?')
                text = (el.get('text', '') or '')[:80]
                lines.append(f"  {ref}: <{tag}> {text}")
            return "\n".join(lines)
        return f"[ERROR] Chrome find: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_click(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.click(
            ref=args.get('ref'), selector=args.get('selector'),
            x=args.get('x'), y=args.get('y'),
            double_click=args.get('double_click', False)
        )
        if result.get('status') == 'success':
            target = args.get('ref') or args.get('selector') or f"({args.get('x')},{args.get('y')})"
            return f"[CHROME] Clicked: {target}"
        return f"[ERROR] Chrome click: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_type(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.type_text(
            text=args.get('text', ''),
            ref=args.get('ref'), selector=args.get('selector'),
            clear=args.get('clear', True)
        )
        if result.get('status') == 'success':
            return f"[CHROME] Typed {len(args.get('text', ''))} chars"
        return f"[ERROR] Chrome type: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_scroll(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.scroll(
            direction=args.get('direction'), amount=args.get('amount'),
            ref=args.get('ref'), selector=args.get('selector')
        )
        if result.get('status') == 'success':
            return f"[CHROME] Scrolled {args.get('direction', 'element into view')}"
        return f"[ERROR] Chrome scroll: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_form_input(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.form_input(
            ref=args.get('ref'), selector=args.get('selector'),
            value=args.get('value', '')
        )
        if result.get('status') == 'success':
            return f"[CHROME] Form value set"
        return f"[ERROR] Chrome form_input: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_execute_js(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.execute_js(args.get('code', ''))
        if result.get('status') == 'success':
            return f"[CHROME] JS result: {result.get('result', 'undefined')}"
        return f"[ERROR] Chrome execute_js: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_get_text(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.get_page_text()
        if result.get('status') == 'success':
            text = result.get('text', '')
            return f"[CHROME] Page text ({len(text)} chars):\n{text[:5000]}"
        return f"[ERROR] Chrome get_text: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_tabs_list(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.tabs_list()
        if result.get('status') == 'success':
            tabs = result.get('tabs', [])
            lines = [f"[CHROME] {len(tabs)} tab(s):"]
            for t in tabs:
                active = " (active)" if t.get('active') else ""
                lines.append(f"  Tab {t.get('id')}: {t.get('title', 'Untitled')[:60]}{active}\n    {t.get('url', '')}")
            return "\n".join(lines)
        return f"[ERROR] Chrome tabs_list: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_tabs_create(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.tabs_create(url=args.get('url'))
        if result.get('status') == 'success':
            return f"[CHROME] New tab created: {result.get('url', 'new tab')}"
        return f"[ERROR] Chrome tabs_create: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_wait_for(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.wait_for(
            selector=args.get('selector'),
            text=args.get('text'),
            timeout=args.get('timeout', 10000)
        )
        if result.get('status') == 'success':
            target = args.get('selector') or args.get('text')
            return f"[CHROME] Wait for '{target}' succeeded"
        return f"[ERROR] Chrome wait_for: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_key_press(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.key_press(
            key=args.get('key', ''),
            repeat=args.get('repeat', 1)
        )
        if result.get('status') == 'success':
            return f"[CHROME] Key pressed: {args.get('key')}"
        return f"[ERROR] Chrome key_press: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_read_console(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.read_console(
            pattern=args.get('pattern'),
            clear=args.get('clear', False)
        )
        if result.get('status') == 'success':
            messages = result.get('messages', [])
            if not messages:
                return "[CHROME] No console messages."
            lines = [f"[CHROME] {len(messages)} console message(s):"]
            for m in messages[:50]:
                lines.append(f"  [{m.get('level', '?')}] {m.get('text', '')[:200]}")
            return "\n".join(lines)
        return f"[ERROR] Chrome read_console: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_read_network(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.read_network(
            url_pattern=args.get('url_pattern'),
            clear=args.get('clear', False)
        )
        if result.get('status') == 'success':
            requests_list = result.get('requests', [])
            if not requests_list:
                return "[CHROME] No network requests captured."
            lines = [f"[CHROME] {len(requests_list)} network request(s):"]
            for r in requests_list[:50]:
                rid = r.get('request_id') or 'n/a'
                lines.append(f"  [{rid}] {r.get('method', '?')} {r.get('status', '?')} {r.get('url', '')[:120]}")
            return "\n".join(lines)
        return f"[ERROR] Chrome read_network: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_get_network_body(self, args: dict) -> str:
        if not self.ws_connection:
            return "[ERROR] Chrome extension not connected."
        request_id = args.get("request_id", "")
        if not request_id:
            return "[ERROR] chrome_get_network_body: request_id is required"
        result = await self.send_command("get_network_body", {"request_id": request_id})
        if result.get("status") == "success":
            body = result.get("body", "")
            if result.get("base64Encoded"):
                return f"[CHROME] Response body (base64): {body[:8000]}"
            MAX_BODY = 8000
            truncated = len(body) > MAX_BODY
            display = body[:MAX_BODY]
            note = f"\n... [truncated, {len(body)} total chars]" if truncated else ""
            return f"[CHROME] Response body:\n{display}{note}"
        return f"[ERROR] chrome_get_network_body: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_hover(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.hover(
            ref=args.get('ref'), selector=args.get('selector'),
            x=args.get('x'), y=args.get('y')
        )
        if result.get('status') == 'success':
            target = args.get('ref') or args.get('selector') or f"({args.get('x')},{args.get('y')})"
            return f"[CHROME] Hovered: {target}"
        return f"[ERROR] Chrome hover: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_drag(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.send_command("drag", {
            "start_x": args.get('start_x'), "start_y": args.get('start_y'),
            "end_x": args.get('end_x'), "end_y": args.get('end_y'),
        })
        if result.get('status') == 'success':
            return (f"[CHROME] Dragged from ({args.get('start_x')},{args.get('start_y')}) "
                    f"to ({args.get('end_x')},{args.get('end_y')})")
        return f"[ERROR] Chrome drag: {result.get('error') or result.get('message') or 'unknown'}"

    async def _tool_chrome_right_click(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.send_command("right_click", {
            "ref": args.get('ref'), "selector": args.get('selector'),
            "x": args.get('x'), "y": args.get('y'),
        })
        if result.get('status') == 'success':
            target = args.get('ref') or args.get('selector') or f"({args.get('x')},{args.get('y')})"
            return f"[CHROME] Right-clicked: {target}"
        return f"[ERROR] Chrome right_click: {result.get('error') or result.get('message') or 'unknown'}"

    async def _tool_chrome_triple_click(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        result = await self.send_command("triple_click", {
            "ref": args.get('ref'), "selector": args.get('selector'),
            "x": args.get('x'), "y": args.get('y'),
        })
        if result.get('status') == 'success':
            target = args.get('ref') or args.get('selector') or f"({args.get('x')},{args.get('y')})"
            return f"[CHROME] Triple-clicked: {target}"
        return f"[ERROR] Chrome triple_click: {result.get('error') or result.get('message') or 'unknown'}"

    async def _tool_chrome_upload(self, args):
        if not self.ws_connection: return "[ERROR] Chrome extension not connected."
        file_path = args.get('file_path', '')
        if not file_path:
            return "[ERROR] chrome_upload: file_path is required"
        if not Path(file_path).exists():
            return f"[ERROR] chrome_upload: File not found: {file_path}"
        result = await self.upload_file(
            file_path=file_path,
            ref=args.get('ref'),
            selector=args.get('selector'),
        )
        if result.get('status') == 'success':
            return f"[CHROME] File uploaded: {result.get('file_path', file_path)}"
        return f"[ERROR] Chrome upload: {result.get('error') or result.get('message') or 'unknown'}"

    async def _tool_chrome_resize(self, args: dict) -> str:
        if not self.ws_connection:
            return "[ERROR] Chrome extension not connected."
        result = await self.send_command("resize_window", args)
        if result.get("status") == "success":
            return f"[CHROME] Viewport resized to {result['width']}\u00d7{result['height']}"
        return f"[ERROR] chrome_resize: {result.get('error') or result.get('message') or 'unknown error'}"

    async def _tool_chrome_wait(self, args: dict) -> str:
        try:
            seconds = float(args.get("seconds", 1))
        except (TypeError, ValueError):
            return "[ERROR] chrome_wait: seconds must be a number"
        if seconds <= 0:
            return "[ERROR] chrome_wait: seconds must be positive"
        if seconds > 30:
            seconds = 30  # cap at 30 seconds
        await asyncio.sleep(seconds)
        return f"[CHROME] Waited {seconds} seconds"

    async def _tool_chrome_gif_start(self, args: dict) -> str:
        if self._gif_recording:
            return "[CHROME] GIF recording already in progress"
        fps = float(args.get("fps", 2))
        if fps <= 0 or fps > 5:
            fps = 2
        self._gif_recording = True
        self._gif_frames = []
        interval = 1.0 / fps

        async def _poll():
            while self._gif_recording:
                try:
                    result = await self.send_command("screenshot", {})
                    if isinstance(result, dict) and result.get("__image_b64__"):
                        frame_b64 = result["__image_b64__"]
                        frame_bytes = base64.b64decode(frame_b64)
                        self._gif_frames.append(frame_bytes)
                    elif isinstance(result, dict) and result.get("image_b64"):
                        frame_b64 = result["image_b64"]
                        frame_bytes = base64.b64decode(frame_b64)
                        self._gif_frames.append(frame_bytes)
                    elif isinstance(result, str) and result.startswith("data:image"):
                        # strip data URI prefix if present
                        b64 = result.split(",", 1)[1]
                        self._gif_frames.append(base64.b64decode(b64))
                except Exception:
                    pass
                await asyncio.sleep(interval)

        self._gif_task = asyncio.create_task(_poll())
        return f"[CHROME] GIF recording started at {fps} fps"

    async def _tool_chrome_gif_stop(self, args: dict) -> str:
        if not self._gif_recording:
            return "[CHROME] No GIF recording in progress"
        self._gif_recording = False
        if self._gif_task:
            self._gif_task.cancel()
            try:
                await self._gif_task
            except asyncio.CancelledError:
                pass
            self._gif_task = None
        return f"[CHROME] GIF recording stopped. {len(self._gif_frames)} frames captured."

    async def _tool_chrome_gif_export(self, args: dict) -> str:
        if not self._gif_frames:
            return "[ERROR] chrome_gif_export: No frames to export. Use chrome_gif_start first."
        try:
            from PIL import Image
            import io
        except ImportError:
            return "[ERROR] chrome_gif_export: Pillow not installed. Run: pip install Pillow"

        frame_duration = int(args.get("frame_duration_ms", 500))
        if frame_duration < 100:
            frame_duration = 100
        if frame_duration > 3000:
            frame_duration = 3000

        filename = args.get("filename", "")
        if not filename:
            filename = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize filename
        filename = "".join(c for c in filename if c.isalnum() or c in "_-")[:64] or "recording"

        logs_dir = self.core.config.get('paths', {}).get('logs', 'logs') if hasattr(self, 'core') and self.core else 'logs'
        out_dir = Path(logs_dir) / 'recordings'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{filename}.gif"

        # Convert JPEG bytes to PIL Images
        pil_frames = []
        for frame_bytes in self._gif_frames:
            try:
                img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
                # Quantize for GIF (256 colors)
                img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
                pil_frames.append(img)
            except Exception:
                continue

        if not pil_frames:
            return "[ERROR] chrome_gif_export: Could not decode any frames"

        pil_frames[0].save(
            str(out_path),
            format="GIF",
            save_all=True,
            append_images=pil_frames[1:],
            loop=0,
            duration=frame_duration,
            optimize=False
        )

        self._gif_frames = []  # clear frames after export
        return f"[CHROME] GIF saved: {out_path} ({len(pil_frames)} frames)"

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

        Returns the result dict on success, or an {"error": "..."} dict
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

    # ── Convenience methods (used by tool handlers) ──────────────────────

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

    async def wait_for(self, selector=None, text=None, timeout=10000, tab_id=None):
        """Wait for a CSS selector or text to appear on the page."""
        return await self.send_command("wait_for", {
            "selector": selector,
            "text": text,
            "timeout": timeout,
            "tab_id": tab_id,
        })

    async def click(self, selector=None, ref=None, coordinate=None, x=None, y=None, tab_id=None, double_click=False):
        """Click an element by CSS selector, ref ID, or viewport coordinate."""
        return await self.send_command("click", {
            "selector": selector,
            "ref": ref,
            "coordinate": coordinate,
            "x": x,
            "y": y,
            "double_click": double_click,
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

    async def scroll(self, direction: str = "down", amount: int = 3, selector=None, ref=None, tab_id=None):
        """Scroll the page or a specific element."""
        return await self.send_command("scroll", {
            "direction": direction,
            "amount": amount,
            "selector": selector,
            "ref": ref,
            "tab_id": tab_id,
        })

    async def form_input(self, ref: str = None, selector: str = None, value=None, tab_id=None):
        """Set the value of a form element identified by ref or selector."""
        return await self.send_command("form_input", {
            "ref": ref,
            "selector": selector,
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

    async def key_press(self, key: str, repeat: int = 1, tab_id=None):
        """Press a keyboard key or shortcut (e.g. ``Enter``, ``ctrl+a``)."""
        return await self.send_command("key_press", {"key": key, "repeat": repeat, "tab_id": tab_id})

    async def read_console(self, tab_id=None, pattern: str | None = None, level: str | None = None, clear: bool = False):
        """Read browser console messages, optionally filtered."""
        return await self.send_command("read_console", {
            "tab_id": tab_id,
            "pattern": pattern,
            "level": level,
            "clear": clear,
        })

    async def read_network(self, tab_id=None, url_pattern: str | None = None, clear: bool = False):
        """Read captured network requests, optionally filtered by URL pattern."""
        return await self.send_command("read_network", {
            "tab_id": tab_id,
            "url_pattern": url_pattern,
            "clear": clear,
        })

    async def get_network_body(self, request_id: str, tab_id: str = None) -> dict:
        """Fetch the full response body for a captured network request by its CDP request ID."""
        args = {"request_id": request_id}
        if tab_id:
            args["tab_id"] = tab_id
        return await self.send_command("get_network_body", args)

    async def hover(self, selector=None, ref=None, coordinate=None, x=None, y=None, tab_id=None):
        """Move the mouse cursor to an element without clicking."""
        return await self.send_command("hover", {
            "selector": selector,
            "ref": ref,
            "coordinate": coordinate,
            "x": x,
            "y": y,
            "tab_id": tab_id,
        })

    async def zoom(self, region: list, tab_id=None):
        """Capture a cropped region of the active tab as a JPEG."""
        return await self.send_command("zoom", {"region": region, "tab_id": tab_id})

    async def drag(self, start_x, start_y, end_x, end_y, tab_id=None):
        """Drag from one coordinate to another."""
        return await self.send_command("drag", {
            "start_x": start_x, "start_y": start_y,
            "end_x": end_x, "end_y": end_y, "tab_id": tab_id
        })

    async def upload_file(self, file_path: str, ref: str = None, selector: str = None, tab_id: str = None) -> dict:
        """Upload a local file to a file input element via Chrome Debugger DOM.setFileInputFiles."""
        args = {"file_path": file_path}
        if ref:
            args["ref"] = ref
        if selector:
            args["selector"] = selector
        if tab_id:
            args["tab_id"] = tab_id
        return await self.send_command("upload_file", args)

    async def resize_window(self, preset: str = None, width: int = None, height: int = None) -> dict:
        """Resize the Chrome viewport using a preset or custom dimensions."""
        args = {}
        if preset:
            args["preset"] = preset
        if width is not None:
            args["width"] = width
        if height is not None:
            args["height"] = height
        return await self.send_command("resize_window", args)

    async def wait(self, seconds: float) -> str:
        """Sleep for *seconds* seconds (Python-side only, no extension command)."""
        return await self._tool_chrome_wait({"seconds": seconds})

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
