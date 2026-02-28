"""Playwright browser automation skill for Galactic AI."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from skills.base import GalacticSkill

# Page state tracking (OpenClaw parity)
pageStates = {}

def ensurePageState(page):
    """Ensure page has state tracking for console/errors/requests/responses (OpenClaw+ parity)."""
    if page not in pageStates:
        state = {
            "console": [],
            "errors": [],
            "requests": [],
            "responses": {}   # url -> {status, headers, body, timestamp}
        }
        pageStates[page] = state

        # Console log capture — .type and .text are properties in Playwright Python, not methods
        page.on("console", lambda msg: state["console"].append({
            "type": msg.type if isinstance(msg.type, str) else str(msg.type),
            "text": msg.text if isinstance(msg.text, str) else str(msg.text),
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # JS error capture
        page.on("pageerror", lambda err: state["errors"].append({
            "message": str(err),
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # Request capture (metadata only)
        page.on("request", lambda req: state["requests"].append({
            "method": req.method,
            "url": req.url,
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # Response body capture (async — best-effort)
        async def _capture_response(resp):
            try:
                body_bytes = await resp.body()
                state["responses"][resp.url] = {
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": body_bytes.decode('utf-8', errors='replace')[:100_000],
                    "timestamp": str(asyncio.get_event_loop().time())
                }
            except Exception:
                pass  # binary / closed responses are silently skipped

        page.on("response", lambda resp: asyncio.create_task(_capture_response(resp)))

    return pageStates[page]


class BrowserProSkill(GalacticSkill):
    skill_name  = "browser_pro"
    version     = "1.1.2"
    author      = "Galactic AI"
    description = "Full Playwright browser automation (55 tools)."
    category    = "browser"
    icon        = "\U0001f310"
    name        = "BrowserExecutorPro"  # compat with web_deck and galactic_core self.browser

    def __init__(self, core):
        super().__init__(core)
        self.browser = None
        self.playwright = None
        self.context = None
        self.pages = {}  # Track multiple pages by ID
        self.active_page_id = None
        self.started = False
        self.default_timeout = 30000  # 30 seconds
        self.refs = {}  # Store ref mappings: {page_id: {ref: selector}}

    # ═══════════════════════════════════════════════════════════════════
    # get_tools() — all 55 tool definitions
    # ═══════════════════════════════════════════════════════════════════

    def get_tools(self):
        return {
            "browser_search": {
                "description": "Search YouTube or other site in the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term."}
                    },
                    "required": ["query"]
                },
                "fn": self._tool_browser_search
            },
            "browser_click": {
                "description": "Click any element on the current page (button, link, etc). Use CSS selector, XPath, or text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector (e.g., '#submit-btn', '.login-button', 'button:has-text(\"Login\")')"}
                    },
                    "required": ["selector"]
                },
                "fn": self._tool_browser_click
            },
            "browser_type": {
                "description": "Type text into any input field. Perfect for forms, search boxes, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector for input field"},
                        "text": {"type": "string", "description": "Text to type"},
                        "press_enter": {"type": "boolean", "description": "Press Enter after typing (default: false)"}
                    },
                    "required": ["selector", "text"]
                },
                "fn": self._tool_browser_type
            },
            "browser_snapshot": {
                "description": "Take OpenClaw-style snapshot of page to get element refs for automation. Returns refs like [ref=1] that can be used with ref-based actions. Essential for reliable automation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "description": "Snapshot format: 'ai' (numeric refs) or 'aria' (role refs)", "default": "ai"},
                        "interactive": {"type": "boolean", "description": "Return only interactive elements (buttons, links, inputs)", "default": False}
                    },
                    "required": []
                },
                "fn": self._tool_browser_snapshot
            },
            "browser_click_by_ref": {
                "description": "Click element using ref from snapshot (OpenClaw-style). Always take a snapshot first to get refs. More reliable than CSS selectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Numeric ref from snapshot (e.g., 1 for [ref=1])"}
                    },
                    "required": ["ref"]
                },
                "fn": self._tool_browser_click_by_ref
            },
            "browser_type_by_ref": {
                "description": "Type text into element using ref from snapshot (OpenClaw-style). Always take snapshot first. More reliable than CSS selectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Numeric ref from snapshot (e.g., 2 for [ref=2])"},
                        "text": {"type": "string", "description": "Text to type"},
                        "press_enter": {"type": "boolean", "description": "Press Enter after typing (default: false)"}
                    },
                    "required": ["ref", "text"]
                },
                "fn": self._tool_browser_type_by_ref
            },
            "browser_fill_form": {
                "description": "Fill out an entire form with multiple fields at once. Perfect for login forms, registration, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fields": {"type": "string", "description": "JSON string of fields array: [{selector, value, type}, ...]"},
                        "submit_selector": {"type": "string", "description": "Submit button selector (optional)"}
                    },
                    "required": ["fields"]
                },
                "fn": self._tool_browser_fill_form
            },
            "browser_extract": {
                "description": "Extract text or an attribute from elements on the current page. Use selector (CSS) or ref (element ref from snapshot).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector to target elements, e.g. 'a.post-title'"},
                        "ref": {"type": "integer", "description": "Element ref number from browser_snapshot"},
                        "attribute": {"type": "string", "description": "HTML attribute to extract, e.g. 'href', 'src', 'text'. Defaults to inner text."},
                        "multiple": {"type": "boolean", "description": "If true, return all matching elements. Default false (first match only)."}
                    }
                },
                "fn": self._tool_browser_extract
            },
            "browser_wait": {
                "description": "Wait for an element or text to appear on page before continuing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector to wait for (optional)"},
                        "text": {"type": "string", "description": "Text content to wait for (optional)"},
                        "timeout": {"type": "number", "description": "Max wait time in ms (default: 30000)"}
                    }
                },
                "fn": self._tool_browser_wait
            },
            "browser_execute_js": {
                "description": "Execute custom JavaScript code in the browser. Full control over page behavior.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "JavaScript code to execute"}
                    },
                    "required": ["script"]
                },
                "fn": self._tool_browser_execute_js
            },
            "browser_upload": {
                "description": "Upload a file to a file input element.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "File input selector"},
                        "file_path": {"type": "string", "description": "Path to file to upload"}
                    },
                    "required": ["selector", "file_path"]
                },
                "fn": self._tool_browser_upload
            },
            "browser_scroll": {
                "description": "Scroll the page up or down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "description": "Direction: 'up' or 'down'"},
                        "amount": {"type": "number", "description": "Pixels to scroll (optional, default: scroll to end)"}
                    },
                    "required": ["direction"]
                },
                "fn": self._tool_browser_scroll
            },
            "browser_new_tab": {
                "description": "Open a new browser tab/window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open in new tab (optional)"}
                    }
                },
                "fn": self._tool_browser_new_tab
            },
            "browser_press": {
                "description": "Press a keyboard key (OpenClaw parity). Examples: Enter, Escape, ArrowDown, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Key to press (e.g., 'Enter', 'Tab', 'Escape')"}
                    },
                    "required": ["key"]
                },
                "fn": self._tool_browser_press
            },
            "browser_hover": {
                "description": "Hover mouse over an element using CSS selector (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of element to hover"}
                    },
                    "required": ["selector"]
                },
                "fn": self._tool_browser_hover
            },
            "browser_hover_by_ref": {
                "description": "Hover over element using ref from snapshot (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Ref number from snapshot"}
                    },
                    "required": ["ref"]
                },
                "fn": self._tool_browser_hover_by_ref
            },
            "browser_scroll_into_view": {
                "description": "Scroll element into view using CSS selector (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector"}
                    },
                    "required": ["selector"]
                },
                "fn": self._tool_browser_scroll_into_view
            },
            "browser_scroll_into_view_by_ref": {
                "description": "Scroll element into view using ref (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Ref from snapshot"}
                    },
                    "required": ["ref"]
                },
                "fn": self._tool_browser_scroll_into_view_by_ref
            },
            "browser_drag": {
                "description": "Drag and drop between two elements using CSS selectors (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_selector": {"type": "string", "description": "Source element selector"},
                        "to_selector": {"type": "string", "description": "Target element selector"}
                    },
                    "required": ["from_selector", "to_selector"]
                },
                "fn": self._tool_browser_drag
            },
            "browser_drag_by_ref": {
                "description": "Drag and drop using refs from snapshot (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_ref": {"type": "integer", "description": "Source ref"},
                        "to_ref": {"type": "integer", "description": "Target ref"}
                    },
                    "required": ["from_ref", "to_ref"]
                },
                "fn": self._tool_browser_drag_by_ref
            },
            "browser_select": {
                "description": "Select option(s) in dropdown using CSS selector (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Dropdown selector"},
                        "values": {"type": "string", "description": "Value(s) to select (comma-separated for multiple)"}
                    },
                    "required": ["selector", "values"]
                },
                "fn": self._tool_browser_select
            },
            "browser_select_by_ref": {
                "description": "Select dropdown option using ref from snapshot (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Dropdown ref"},
                        "values": {"type": "string", "description": "Value(s) to select"}
                    },
                    "required": ["ref", "values"]
                },
                "fn": self._tool_browser_select_by_ref
            },
            "browser_download": {
                "description": "Download file from link using CSS selector (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Link selector"},
                        "filename": {"type": "string", "description": "Filename to save as"}
                    },
                    "required": ["selector", "filename"]
                },
                "fn": self._tool_browser_download
            },
            "browser_download_by_ref": {
                "description": "Download file using ref from snapshot (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Link ref"},
                        "filename": {"type": "string", "description": "Filename to save as"}
                    },
                    "required": ["ref", "filename"]
                },
                "fn": self._tool_browser_download_by_ref
            },
            "browser_dialog": {
                "description": "Handle upcoming dialog/alert (arming call - OpenClaw parity). Run BEFORE action that triggers dialog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action: 'accept' or 'dismiss'"},
                        "text": {"type": "string", "description": "Text for prompt dialogs (optional)"}
                    },
                    "required": ["action"]
                },
                "fn": self._tool_browser_dialog
            },
            "browser_highlight": {
                "description": "Highlight element for debugging using CSS selector (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Element selector"}
                    },
                    "required": ["selector"]
                },
                "fn": self._tool_browser_highlight
            },
            "browser_highlight_by_ref": {
                "description": "Highlight element using ref for debugging (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer", "description": "Element ref"}
                    },
                    "required": ["ref"]
                },
                "fn": self._tool_browser_highlight_by_ref
            },
            "browser_resize": {
                "description": "Resize browser viewport (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer", "description": "Viewport width"},
                        "height": {"type": "integer", "description": "Viewport height"}
                    },
                    "required": ["width", "height"]
                },
                "fn": self._tool_browser_resize
            },
            "browser_console_logs": {
                "description": "Get browser console logs (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "description": "Filter by level: log, warn, error, info (optional)"}
                    }
                },
                "fn": self._tool_browser_console_logs
            },
            "browser_page_errors": {
                "description": "Get JavaScript page errors (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_page_errors
            },
            "browser_network_requests": {
                "description": "Get network requests (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {"type": "string", "description": "Filter by URL pattern (optional)"}
                    }
                },
                "fn": self._tool_browser_network_requests
            },
            "browser_pdf": {
                "description": "Generate PDF of current page (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "PDF file path (optional)"}
                    }
                },
                "fn": self._tool_browser_pdf
            },
            "browser_get_local_storage": {
                "description": "Get localStorage data (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_get_local_storage
            },
            "browser_set_local_storage": {
                "description": "Set localStorage item (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Storage key"},
                        "value": {"type": "string", "description": "Storage value"}
                    },
                    "required": ["key", "value"]
                },
                "fn": self._tool_browser_set_local_storage
            },
            "browser_clear_local_storage": {
                "description": "Clear all localStorage (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_clear_local_storage
            },
            "browser_get_session_storage": {
                "description": "Get sessionStorage data (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_get_session_storage
            },
            "browser_set_session_storage": {
                "description": "Set sessionStorage item (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Storage key"},
                        "value": {"type": "string", "description": "Storage value"}
                    },
                    "required": ["key", "value"]
                },
                "fn": self._tool_browser_set_session_storage
            },
            "browser_clear_session_storage": {
                "description": "Clear all sessionStorage (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_clear_session_storage
            },
            "browser_set_offline": {
                "description": "Enable/disable offline mode (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "offline": {"type": "boolean", "description": "True for offline, False for online"}
                    },
                    "required": ["offline"]
                },
                "fn": self._tool_browser_set_offline
            },
            "browser_set_headers": {
                "description": "Set extra HTTP headers (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "headers": {"type": "string", "description": "JSON object of headers"}
                    },
                    "required": ["headers"]
                },
                "fn": self._tool_browser_set_headers
            },
            "browser_set_geolocation": {
                "description": "Set browser geolocation (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number", "description": "Latitude"},
                        "longitude": {"type": "number", "description": "Longitude"},
                        "accuracy": {"type": "number", "description": "Accuracy in meters (optional)"}
                    },
                    "required": ["latitude", "longitude"]
                },
                "fn": self._tool_browser_set_geolocation
            },
            "browser_clear_geolocation": {
                "description": "Clear geolocation override (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self._tool_browser_clear_geolocation
            },
            "browser_emulate_media": {
                "description": "Emulate media features like dark mode (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "color_scheme": {"type": "string", "description": "Color scheme: dark, light, or no-preference"}
                    },
                    "required": ["color_scheme"]
                },
                "fn": self._tool_browser_emulate_media
            },
            "browser_set_locale": {
                "description": "Set browser locale (e.g. 'en-US', 'fr-FR', 'ja-JP'). Recreates context so language-sensitive sites respond correctly.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "locale": {"type": "string", "description": "BCP-47 locale string, e.g. 'en-US', 'de-DE'"}
                    },
                    "required": ["locale"]
                },
                "fn": self._tool_browser_set_locale
            },
            "browser_response_body": {
                "description": "Get captured HTTP response bodies for requests made by the current page. Optionally filter by URL substring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url_pattern": {"type": "string", "description": "Optional URL substring to filter responses (e.g. '/api/')"}
                    }
                },
                "fn": self._tool_browser_response_body
            },
            "browser_click_coords": {
                "description": "Click at exact pixel coordinates (x, y). Use for canvas elements, maps, or when CSS selector-based clicking fails.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate in pixels from left"},
                        "y": {"type": "number", "description": "Y coordinate in pixels from top"},
                        "button": {"type": "string", "description": "Mouse button: left, right, or middle (default: left)"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self._tool_browser_click_coords
            },
            "browser_get_frames": {
                "description": "List all frames (iframes) on the current page, with their index, name, and URL.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_browser_get_frames
            },
            "browser_frame_action": {
                "description": "Perform an action inside an iframe. action: click | type | snapshot | evaluate.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "frame_index": {"type": "number", "description": "Frame index from browser_get_frames"},
                        "action": {"type": "string", "description": "Action: click, type, snapshot, evaluate"},
                        "selector": {"type": "string", "description": "CSS selector for click/type actions"},
                        "text": {"type": "string", "description": "Text to type, or JS expression for evaluate"}
                    },
                    "required": ["frame_index", "action"]
                },
                "fn": self._tool_browser_frame_action
            },
            "browser_trace_start": {
                "description": "Start Playwright browser tracing (records screenshots and snapshots for debugging).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "screenshots": {"type": "boolean", "description": "Capture screenshots (default: true)"},
                        "snapshots": {"type": "boolean", "description": "Capture DOM snapshots (default: true)"}
                    }
                },
                "fn": self._tool_browser_trace_start
            },
            "browser_trace_stop": {
                "description": "Stop Playwright tracing and save the trace.zip file for analysis in Playwright Trace Viewer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Path to save trace.zip (default: logs/trace.zip)"}
                    }
                },
                "fn": self._tool_browser_trace_stop
            },
            "browser_intercept": {
                "description": "Intercept network requests — block ads/trackers or mock API responses. rules = list of {pattern, action, body?, status?}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rules": {
                            "type": "array",
                            "description": "List of intercept rules. Each: {pattern: URL substring, action: 'block'|'mock', body?: str, status?: int}",
                            "items": {"type": "object"}
                        }
                    },
                    "required": ["rules"]
                },
                "fn": self._tool_browser_intercept
            },
            "browser_clear_intercept": {
                "description": "Remove all network interception rules from the current page.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_browser_clear_intercept
            },
            "browser_save_session": {
                "description": "Save the current browser session (cookies, localStorage) to a named file for reuse.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string", "description": "Name for this session (default: 'default')"}
                    }
                },
                "fn": self._tool_browser_save_session
            },
            "browser_load_session": {
                "description": "Load a previously saved browser session (restores cookies and localStorage).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string", "description": "Name of the session to load (default: 'default')"}
                    }
                },
                "fn": self._tool_browser_load_session
            },
            "browser_set_proxy": {
                "description": "Restart the browser with a proxy server. Use for anonymity, regional testing, or scraping.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "Proxy server URL, e.g. 'http://proxy.example.com:8080'"},
                        "username": {"type": "string", "description": "Proxy username (optional)"},
                        "password": {"type": "string", "description": "Proxy password (optional)"}
                    },
                    "required": ["server"]
                },
                "fn": self._tool_browser_set_proxy
            },
        }

    # ═══════════════════════════════════════════════════════════════════
    # Tool handlers — 55 methods
    # ═══════════════════════════════════════════════════════════════════

    async def _tool_browser_search(self, args):
        """Search on current site (YouTube, Google, etc)."""
        query = args.get('query')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            page = self._get_page()
            if not page:
                return "[ERROR] No browser page open. Open a URL first."
            from urllib.parse import urlparse
            url = page.url
            hostname = urlparse(url).hostname or ""
            if hostname.endswith("youtube.com") or hostname.endswith("google.com"):
                selector = 'input[name="search_query"]' if hostname.endswith("youtube.com") else 'input[name="q"]'
                result = await self.type_text(selector, query, press_enter=True)
                if result['status'] == 'success':
                    return f"[BROWSER] Searched for: {query}"
                else:
                    return f"[ERROR] Search failed: {result.get('message', 'Unknown error')}"
            else:
                return f"[ERROR] Don't know how to search on: {url}"
        except Exception as e:
            return f"[ERROR] Browser search: {e}"

    async def _tool_browser_click(self, args):
        """Click element in browser."""
        selector = args.get('selector')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.click(selector)
            if result['status'] == 'success':
                return f"[BROWSER] Clicked: {selector}"
            else:
                return f"[ERROR] Click failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser click: {e}"

    async def _tool_browser_type(self, args):
        """Type text into browser input field."""
        selector = args.get('selector')
        text = args.get('text')
        press_enter = args.get('press_enter', False)
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.type_text(selector, text, press_enter=press_enter)
            if result['status'] == 'success':
                return f"[BROWSER] Typed into {selector}: {text[:50]}{'...' if len(text) > 50 else ''}"
            else:
                return f"[ERROR] Type failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser type: {e}"

    async def _tool_browser_snapshot(self, args):
        """Take OpenClaw-style snapshot for ref-based automation."""
        format_type = args.get('format', 'ai')
        interactive = args.get('interactive', False)
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.snapshot(format=format_type, interactive=interactive)
            if result['status'] == 'success':
                return f"[BROWSER SNAPSHOT - {format_type.upper()} format]\n{result['snapshot']}"
            else:
                return f"[ERROR] Snapshot failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser snapshot: {e}"

    async def _tool_browser_click_by_ref(self, args):
        """Click element using ref from snapshot (OpenClaw-style)."""
        ref = args.get('ref')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.click_by_ref(ref)
            if result['status'] == 'success':
                return f"[BROWSER] Clicked ref={ref}"
            else:
                return f"[ERROR] Click ref={ref} failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser click by ref: {e}"

    async def _tool_browser_type_by_ref(self, args):
        """Type text using ref from snapshot (OpenClaw-style)."""
        ref = args.get('ref')
        text = args.get('text')
        press_enter = args.get('press_enter', False)
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.type_by_ref(ref, text, press_enter=press_enter)
            if result['status'] == 'success':
                return f"[BROWSER] Typed into ref={ref}: {text[:50]}{'...' if len(text) > 50 else ''}"
            else:
                return f"[ERROR] Type ref={ref} failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser type by ref: {e}"

    async def _tool_browser_fill_form(self, args):
        """Fill form with multiple fields."""
        import json as json_lib
        fields_str = args.get('fields')
        submit_selector = args.get('submit_selector')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            fields = json_lib.loads(fields_str)
            result = await self.fill_form(fields, submit_selector=submit_selector)
            if result['status'] == 'success':
                msg = f"[BROWSER] Filled {result['filled_count']} fields"
                if result.get('submitted'):
                    msg += " and submitted form"
                return msg
            else:
                return f"[ERROR] Form fill failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser fill form: {e}"

    async def _tool_browser_extract(self, args):
        """Extract text or attribute from page elements by selector or ref."""
        import json as json_lib
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            selector = args.get('selector')
            ref = args.get('ref')
            attribute = args.get('attribute', 'text')
            multiple = args.get('multiple', False)

            if not selector and ref is not None:
                selector = f"[data-ref='{ref}']"

            if not selector:
                return "[ERROR] browser_extract requires 'selector' or 'ref'"

            if attribute == 'text':
                js = f"""
                    const els = Array.from(document.querySelectorAll({json_lib.dumps(selector)}));
                    const results = els.map(e => e.innerText.trim()).filter(Boolean);
                    JSON.stringify({'multiple': multiple} ? results : results[0] || null);
                """.replace("{'multiple': multiple}", "true" if multiple else "false")
            else:
                js = f"""
                    const els = Array.from(document.querySelectorAll({json_lib.dumps(selector)}));
                    const results = els.map(e => e.getAttribute({json_lib.dumps(attribute)})).filter(Boolean);
                    JSON.stringify({'multiple': multiple} ? results : results[0] || null);
                """.replace("{'multiple': multiple}", "true" if multiple else "false")

            result = await self.execute_js(js)
            if result.get('status') == 'success':
                val = result.get('result', 'null')
                return f"[BROWSER] Extracted ({attribute}): {val}"
            else:
                return f"[ERROR] Extract failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser extract: {e}"

    async def _tool_browser_wait(self, args):
        """Wait for element or text."""
        selector = args.get('selector')
        text = args.get('text')
        timeout = args.get('timeout', 30000)
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.wait_for(selector=selector, text=text, timeout=timeout)
            if result['status'] == 'success':
                return f"[BROWSER] Element/text appeared: {selector or text}"
            elif result['status'] == 'timeout':
                return f"[TIMEOUT] Waited {timeout}ms but element didn't appear"
            else:
                return f"[ERROR] Wait failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser wait: {e}"

    async def _tool_browser_execute_js(self, args):
        """Execute JavaScript in browser."""
        script = args.get('script')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.execute_js(script)
            if result['status'] == 'success':
                return f"[BROWSER] JS Result: {result.get('result', 'No return value')}"
            else:
                return f"[ERROR] JS execution failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser execute JS: {e}"

    async def _tool_browser_upload(self, args):
        """Upload file via browser."""
        selector = args.get('selector')
        file_path = args.get('file_path')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.upload_file(selector, file_path)
            if result['status'] == 'success':
                return f"[BROWSER] Uploaded: {file_path}"
            else:
                return f"[ERROR] Upload failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser upload: {e}"

    async def _tool_browser_scroll(self, args):
        """Scroll browser page."""
        direction = args.get('direction', 'down')
        amount = args.get('amount')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.scroll(direction, amount)
            if result['status'] == 'success':
                return f"[BROWSER] Scrolled {direction}"
            else:
                return f"[ERROR] Scroll failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser scroll: {e}"

    async def _tool_browser_new_tab(self, args):
        """Open new browser tab."""
        url = args.get('url')
        try:
            if not self.started:
                return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
            result = await self.new_tab(url)
            if result['status'] == 'success':
                return f"[BROWSER] New tab: {result['page_id']} (URL: {url or 'blank'})"
            else:
                return f"[ERROR] New tab failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser new tab: {e}"

    async def _tool_browser_press(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.press(args.get('key'))
        return f"[BROWSER] Pressed: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_hover(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.hover(args.get('selector'))
        return f"[BROWSER] Hovered: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_hover_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.hover_by_ref(args.get('ref'))
        return f"[BROWSER] Hovered ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_scroll_into_view(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.scroll_into_view(args.get('selector'))
        return f"[BROWSER] Scrolled into view: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_scroll_into_view_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.scroll_into_view_by_ref(args.get('ref'))
        return f"[BROWSER] Scrolled into view ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_drag(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.drag(args.get('from_selector'), args.get('to_selector'))
        return f"[BROWSER] Dragged {args.get('from_selector')} to {args.get('to_selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_drag_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.drag_by_ref(args.get('from_ref'), args.get('to_ref'))
        return f"[BROWSER] Dragged ref={args.get('from_ref')} to ref={args.get('to_ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_select(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        values = args.get('values').split(',') if ',' in args.get('values', '') else args.get('values')
        result = await self.select_option(args.get('selector'), values)
        return f"[BROWSER] Selected {values} in {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_select_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        values = args.get('values').split(',') if ',' in args.get('values', '') else args.get('values')
        result = await self.select_option_by_ref(args.get('ref'), values)
        return f"[BROWSER] Selected {values} in ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_download(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.download(args.get('selector'), args.get('filename'))
        return f"[BROWSER] Downloaded to: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_download_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.download_by_ref(args.get('ref'), args.get('filename'))
        return f"[BROWSER] Downloaded to: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_dialog(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.dialog(args.get('action'), args.get('text'))
        return f"[BROWSER] Dialog armed: {args.get('action')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_highlight(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.highlight(args.get('selector'))
        return f"[BROWSER] Highlighted: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_highlight_by_ref(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.highlight_by_ref(args.get('ref'))
        return f"[BROWSER] Highlighted ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_resize(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.resize_viewport(args.get('width'), args.get('height'))
        return f"[BROWSER] Resized to {args.get('width')}x{args.get('height')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_console_logs(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_console_logs(args.get('level'))
        if result['status'] == 'success':
            logs = result.get('logs', [])
            return f"[BROWSER] Console logs ({len(logs)} entries):\n" + "\n".join([f"[{log.get('type')}] {log.get('text')}" for log in logs[:20]])
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_page_errors(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_page_errors()
        if result['status'] == 'success':
            errors = result.get('errors', [])
            return f"[BROWSER] Page errors ({len(errors)} entries):\n" + "\n".join([err.get('message', '') for err in errors[:10]])
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_network_requests(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_network_requests(args.get('filter'))
        if result['status'] == 'success':
            requests = result.get('requests', [])
            return f"[BROWSER] Network requests ({len(requests)} entries):\n" + "\n".join([f"{req.get('method')} {req.get('url')}" for req in requests[:15]])
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_pdf(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.generate_pdf(args.get('path'))
        return f"[BROWSER] PDF generated: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_get_local_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_local_storage()
        if result['status'] == 'success':
            storage = result.get('storage', {})
            return f"[BROWSER] localStorage ({len(storage)} items):\n" + "\n".join([f"{k}: {v}" for k, v in storage.items()])
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_local_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.set_local_storage(args.get('key'), args.get('value'))
        return f"[BROWSER] Set localStorage: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_clear_local_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.clear_local_storage()
        return "[BROWSER] localStorage cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_get_session_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_session_storage()
        if result['status'] == 'success':
            storage = result.get('storage', {})
            return f"[BROWSER] sessionStorage ({len(storage)} items):\n" + "\n".join([f"{k}: {v}" for k, v in storage.items()])
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_session_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.set_session_storage(args.get('key'), args.get('value'))
        return f"[BROWSER] Set sessionStorage: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_clear_session_storage(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.clear_session_storage()
        return "[BROWSER] sessionStorage cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_offline(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.set_offline(args.get('offline'))
        return f"[BROWSER] Offline mode: {args.get('offline')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_headers(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        headers = json.loads(args.get('headers'))
        result = await self.set_extra_http_headers(headers)
        return f"[BROWSER] Set {result.get('count')} HTTP headers" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_geolocation(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.set_geolocation(args.get('latitude'), args.get('longitude'), args.get('accuracy'))
        return f"[BROWSER] Geolocation set: {args.get('latitude')}, {args.get('longitude')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_clear_geolocation(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.clear_geolocation()
        return "[BROWSER] Geolocation cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_emulate_media(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.emulate_media(args.get('color_scheme'))
        return f"[BROWSER] Media emulated: {args.get('color_scheme')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_locale(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.set_locale(args.get('locale', 'en-US'))
        return f"[BROWSER] Locale set: {args.get('locale')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_response_body(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_response_body(args.get('url_pattern'))
        if result['status'] == 'success':
            count = result['count']
            if count == 0:
                return "[BROWSER] No response bodies captured yet. Navigate to a page first."
            lines = [f"[BROWSER] {count} response(s) captured:"]
            for url, resp in list(result['responses'].items())[:5]:
                body_preview = resp.get('body', '')[:200]
                lines.append(f"  {resp.get('status')} {url}\n    {body_preview}...")
            return "\n".join(lines)
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_click_coords(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.click_coords(args.get('x', 0), args.get('y', 0), args.get('button', 'left'))
        return f"[BROWSER] Clicked ({args.get('x')}, {args.get('y')})" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_get_frames(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.get_frames()
        if result['status'] == 'success':
            frames = result['frames']
            if not frames:
                return "[BROWSER] No frames found (page has no iframes)."
            lines = [f"[BROWSER] {len(frames)} frame(s):"]
            for f in frames:
                lines.append(f"  [{f['index']}] name='{f['name']}' url={f['url']}")
            return "\n".join(lines)
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_frame_action(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.frame_action(
            int(args.get('frame_index', 0)),
            args.get('action', 'snapshot'),
            args.get('selector'),
            args.get('text')
        )
        if result['status'] == 'success':
            content = result.get('content') or result.get('result') or ''
            return f"[BROWSER/FRAME] {result['action']} OK{': ' + content[:500] if content else ''}"
        return f"[ERROR] {result.get('message')}"

    async def _tool_browser_trace_start(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.trace_start(
            screenshots=args.get('screenshots', True),
            snapshots=args.get('snapshots', True)
        )
        return "[BROWSER] Playwright tracing started." if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_trace_stop(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.trace_stop(args.get('output_path'))
        return f"[BROWSER] Trace saved: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_intercept(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        rules = args.get('rules', [])
        result = await self.set_intercept(rules)
        return f"[BROWSER] Intercept armed: {result.get('rules_count', 0)} rule(s)" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_clear_intercept(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.clear_intercept()
        return "[BROWSER] Intercept rules cleared." if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_save_session(self, args):
        if not self.started:
            return "[ERROR] Browser not started. Use browser_search or navigate to open the browser first."
        result = await self.save_session(args.get('session_name', 'default'))
        return f"[BROWSER] Session saved: {result.get('session')} → {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_load_session(self, args):
        result = await self.load_session(args.get('session_name', 'default'))
        return f"[BROWSER] Session loaded: {result.get('session')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def _tool_browser_set_proxy(self, args):
        result = await self.restart_with_proxy(
            args.get('server', ''),
            args.get('username'),
            args.get('password')
        )
        return f"[BROWSER] Proxy set: {result.get('proxy')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    # ═══════════════════════════════════════════════════════════════════
    # Full BrowserExecutorPro implementation
    # ═══════════════════════════════════════════════════════════════════

    async def start(self):
        """Launch browser with stealth mode. Engine and headless mode are config-driven."""
        if self.started:
            return {"status": "already_running"}

        try:
            self.playwright = await async_playwright().start()

            # Read browser engine from config (chromium | firefox | webkit)
            engine_name = self.core.config.get('browser', {}).get('engine', 'chromium')
            browser_engine = getattr(self.playwright, engine_name, self.playwright.chromium)
            headless = self.core.config.get('browser', {}).get('headless', False)

            # Launch with realistic browser args (anti-detection)
            self.browser = await browser_engine.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--no-sandbox'
                ]
            )

            # Context with realistic viewport
            self.context = await self.browser.new_context(
                no_viewport=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # Create initial page
            page = await self.context.new_page()
            page_id = "page_1"
            self.pages[page_id] = page
            self.active_page_id = page_id

            # Enable state tracking (OpenClaw parity)
            ensurePageState(page)

            self.started = True
            await self.core.log("Galactic Browser PRO: Online (Anti-Detection Mode)", priority=2)
            return {"status": "started", "page_id": page_id}

        except Exception as e:
            await self.core.log(f"Browser launch failed: {e}", priority=1)
            return {"status": "error", "message": str(e)}

    def _get_page(self, page_id=None):
        """Get page by ID or return active page."""
        if page_id and page_id in self.pages:
            return self.pages[page_id]
        elif self.active_page_id and self.active_page_id in self.pages:
            return self.pages[self.active_page_id]
        else:
            return None

    async def navigate(self, url, page_id=None, wait_for="domcontentloaded"):
        """Navigate to URL with smart waiting."""
        if not self.started:
            await self.start()

        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.goto(url, timeout=self.default_timeout, wait_until=wait_for)
            await self.core.log(f"Navigated: {url}", priority=2)
            return {"status": "success", "url": url, "page_id": page_id or self.active_page_id}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click(self, selector, page_id=None, wait=True):
        """Click element by CSS selector, XPath, or text."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if wait:
                await page.wait_for_selector(selector, timeout=self.default_timeout)

            await page.click(selector)
            await self.core.log(f"Clicked: {selector}", priority=2)
            return {"status": "success", "selector": selector}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def type_text(self, selector, text, page_id=None, clear=True, press_enter=False):
        """Type text into input field. Handles both standard inputs and contenteditable divs (e.g. X.com compose box)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.wait_for_selector(selector, timeout=self.default_timeout)

            # Detect contenteditable (X.com compose, Notion, Gmail compose, etc.)
            # Standard .fill() silently does nothing on contenteditable elements.
            is_ce = await page.evaluate(
                f"""(sel => {{
                    const el = document.querySelector(sel);
                    return el ? el.isContentEditable : false;
                }})('{selector}')"""
            )

            if is_ce:
                # Click to focus, then use real keyboard events
                await page.click(selector)
                if clear:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                await page.keyboard.type(text, delay=10)
            else:
                if clear:
                    await page.fill(selector, "")  # Clear first
                await page.fill(selector, text)

            if press_enter:
                await page.press(selector, "Enter")

            await self.core.log(f"Typed into {selector}: {text[:50]}...", priority=2)
            return {"status": "success", "selector": selector, "text_length": len(text)}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def fill_form(self, fields, page_id=None, submit_selector=None):
        """Fill multiple form fields at once."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            filled = []
            for field in fields:
                selector = field.get('selector')
                value = field.get('value')
                field_type = field.get('type', 'text')  # text, checkbox, radio, select

                await page.wait_for_selector(selector, timeout=self.default_timeout)

                if field_type == 'checkbox':
                    if value:
                        await page.check(selector)
                    else:
                        await page.uncheck(selector)
                elif field_type == 'select':
                    await page.select_option(selector, value)
                else:
                    await page.fill(selector, str(value))

                filled.append(selector)
                await self.core.log(f"Filled: {selector}", priority=2)

            if submit_selector:
                await page.click(submit_selector)
                await self.core.log(f"Submitted form via: {submit_selector}", priority=2)

            return {"status": "success", "filled_count": len(filled), "submitted": bool(submit_selector)}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def extract_data(self, config, page_id=None):
        """Extract structured data from page."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            extracted = {}

            for key, rule in config.items():
                selector = rule['selector']
                attr = rule.get('attr', 'text')
                multiple = rule.get('multiple', False)

                if multiple:
                    elements = await page.query_selector_all(selector)
                    values = []
                    for el in elements:
                        if attr == 'text':
                            values.append(await el.inner_text())
                        elif attr == 'html':
                            values.append(await el.inner_html())
                        else:
                            values.append(await el.get_attribute(attr))
                    extracted[key] = values
                else:
                    element = await page.query_selector(selector)
                    if element:
                        if attr == 'text':
                            extracted[key] = await element.inner_text()
                        elif attr == 'html':
                            extracted[key] = await element.inner_html()
                        elif attr == 'table':
                            rows = await element.query_selector_all('tr')
                            table_data = []
                            for row in rows:
                                cells = await row.query_selector_all('td, th')
                                row_data = [await cell.inner_text() for cell in cells]
                                table_data.append(row_data)
                            extracted[key] = table_data
                        else:
                            extracted[key] = await element.get_attribute(attr)

            await self.core.log(f"Extracted {len(extracted)} data points", priority=2)
            return {"status": "success", "data": extracted}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def execute_js(self, script, page_id=None):
        """Execute JavaScript in page context."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            result = await page.evaluate(script)
            await self.core.log(f"Executed JS: {script[:100]}...", priority=2)
            return {"status": "success", "result": result}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def wait_for(self, selector=None, text=None, timeout=30000, page_id=None):
        """Wait for element or text to appear."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if selector:
                await page.wait_for_selector(selector, timeout=timeout)
                await self.core.log(f"Waited for: {selector}", priority=2)
            elif text:
                await page.wait_for_function(
                    f'document.body.innerText.includes("{text}")',
                    timeout=timeout
                )
                await self.core.log(f"Waited for text: {text}", priority=2)

            return {"status": "success"}

        except PlaywrightTimeout:
            return {"status": "timeout", "message": f"Timeout waiting for {selector or text}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll(self, direction="down", amount=None, page_id=None):
        """Scroll page up/down."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if direction == "down":
                if amount:
                    await page.evaluate(f"window.scrollBy(0, {amount})")
                else:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                if amount:
                    await page.evaluate(f"window.scrollBy(0, -{amount})")
                else:
                    await page.evaluate("window.scrollTo(0, 0)")

            await self.core.log(f"Scrolled {direction}", priority=2)
            return {"status": "success", "direction": direction}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot(self, path=None, full_page=True, page_id=None):
        """Capture screenshot."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if not path:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                img_subdir = Path(images_dir) / 'browser'
                img_subdir.mkdir(parents=True, exist_ok=True)
                path = str(img_subdir / 'screenshot.png')

            await page.screenshot(path=path, full_page=full_page)
            await self.core.log(f"Screenshot: {path}", priority=2)
            return {"status": "success", "path": path}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def snapshot(self, format="ai", interactive=False, compact=False, depth=6, max_chars=50000, page_id=None):
        """Take accessibility snapshot of page for automation refs."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if format == "aria" or interactive:
                snapshot = await page.accessibility.snapshot(interesting_only=interactive)

                def flatten_tree(node, indent=0, ref_counter=[0]):
                    lines = []
                    if node:
                        ref = ref_counter[0]
                        ref_counter[0] += 1

                        role = node.get('role', 'unknown')
                        name = node.get('name', '')

                        if compact and not interactive:
                            if role in ['generic', 'group'] and not name:
                                for child in node.get('children', []):
                                    lines.extend(flatten_tree(child, indent, ref_counter))
                                return lines

                        line = f"[ref=e{ref}] {role}"
                        if name:
                            line += f" \"{name}\""

                        if interactive:
                            if role in ['button', 'link', 'textbox', 'combobox', 'listbox', 'menuitem', 'checkbox', 'radio']:
                                lines.append(line)
                        else:
                            lines.append("  " * indent + line)

                        for child in node.get('children', []):
                            if indent < depth:
                                lines.extend(flatten_tree(child, indent + 1, ref_counter))

                    return lines

                if snapshot:
                    lines = flatten_tree(snapshot)
                    snapshot_text = "\n".join(lines[:1000])
                else:
                    snapshot_text = "No accessibility data available"

            else:
                snapshot_data = await page.evaluate("""() => {
                    const elements = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="menuitem"], [role="checkbox"], [role="radio"], [tabindex]');
                    let output = [];
                    let mappings = [];
                    let ref = 0;

                    elements.forEach(el => {
                        if (el.offsetParent !== null) {  // Only visible elements
                            ref++;
                            const tag = el.tagName.toLowerCase();
                            const id = el.id ? '#' + el.id : '';
                            const classes = el.className ? '.' + el.className.split(' ').filter(c => c).join('.') : '';
                            const text = el.innerText ? el.innerText.substring(0, 50).replace(/\\n/g, ' ') : '';
                            const role = el.getAttribute('role') || '';
                            const ariaLabel = el.getAttribute('aria-label') || '';

                            let line = `[ref=${ref}] <${tag}${id}${classes}>`;
                            if (ariaLabel) line += ` aria-label="${ariaLabel}"`;
                            if (role) line += ` role="${role}"`;
                            if (text) line += ` "${text}"`;

                            output.push(line);

                            // Store mapping: ref -> CSS selector
                            const selector = tag + id + classes;
                            mappings.push({ref: ref, selector: selector});
                        }
                    });

                    return {output: output.join('\\n'), mappings: mappings};
                }""")

                snapshot_text = snapshot_data['output']

                actual_page_id = page_id or self.active_page_id
                if actual_page_id:
                    ref_map = {}
                    for mapping in snapshot_data['mappings']:
                        ref_map[mapping['ref']] = mapping['selector']
                    self.refs[actual_page_id] = ref_map

            if len(snapshot_text) > max_chars:
                snapshot_text = snapshot_text[:max_chars] + "\n... (truncated)"

            await self.core.log(f"Snapshot captured ({format} format)", priority=2)
            return {"status": "success", "snapshot": snapshot_text, "format": format}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def upload_file(self, selector, file_path, page_id=None):
        """Upload file to input element."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.wait_for_selector(selector, timeout=self.default_timeout)
            await page.set_input_files(selector, file_path)

            await self.core.log(f"Uploaded: {file_path} to {selector}", priority=2)
            return {"status": "success", "file": file_path}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click_by_ref(self, ref, page_id=None):
        """Click element using ref from snapshot (OpenClaw-style)."""
        try:
            actual_page_id = page_id or self.active_page_id

            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            result = await self.click(selector, page_id=page_id)
            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def type_by_ref(self, ref, text, page_id=None, clear=True, press_enter=False):
        """Type text using ref from snapshot (OpenClaw-style)."""
        try:
            actual_page_id = page_id or self.active_page_id

            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            result = await self.type_text(selector, text, page_id=page_id, clear=clear, press_enter=press_enter)
            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def new_tab(self, url=None):
        """Create new tab/page."""
        try:
            page = await self.context.new_page()
            page_id = f"page_{len(self.pages) + 1}"
            self.pages[page_id] = page

            ensurePageState(page)

            if url:
                await page.goto(url, timeout=self.default_timeout)

            await self.core.log(f"New tab: {page_id}", priority=2)
            return {"status": "success", "page_id": page_id, "url": url}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def switch_tab(self, page_id):
        """Switch active tab."""
        if page_id in self.pages:
            self.active_page_id = page_id
            await self.core.log(f"Switched to: {page_id}", priority=2)
            return {"status": "success", "page_id": page_id}
        else:
            return {"status": "error", "message": f"Page {page_id} not found"}

    async def get_cookies(self, page_id=None):
        """Get all cookies."""
        try:
            cookies = await self.context.cookies()
            return {"status": "success", "cookies": cookies}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_cookies(self, cookies):
        """Set cookies."""
        try:
            await self.context.add_cookies(cookies)
            return {"status": "success", "count": len(cookies)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def press(self, key, page_id=None):
        """Press a keyboard key (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.keyboard.press(key)
            await self.core.log(f"Pressed key: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def hover(self, selector, page_id=None):
        """Hover over element (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.hover(selector)
            await self.core.log(f"Hovered: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def hover_by_ref(self, ref, page_id=None):
        """Hover using ref from snapshot (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            return await self.hover(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll_into_view(self, selector, page_id=None):
        """Scroll element into view (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.locator(selector).scroll_into_view_if_needed()
            await self.core.log(f"Scrolled into view: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll_into_view_by_ref(self, ref, page_id=None):
        """Scroll into view using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            return await self.scroll_into_view(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def drag(self, from_selector, to_selector, page_id=None):
        """Drag and drop (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.drag_and_drop(from_selector, to_selector)
            await self.core.log(f"Dragged {from_selector} to {to_selector}", priority=2)
            return {"status": "success", "from": from_selector, "to": to_selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def drag_by_ref(self, from_ref, to_ref, page_id=None):
        """Drag and drop using refs (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs:
                return {"status": "error", "message": "No refs found. Take a snapshot first."}

            if from_ref not in self.refs[actual_page_id] or to_ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": "Refs not found. Take a snapshot first."}

            from_selector = self.refs[actual_page_id][from_ref]
            to_selector = self.refs[actual_page_id][to_ref]
            return await self.drag(from_selector, to_selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def select_option(self, selector, values, page_id=None):
        """Select dropdown option(s) (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if isinstance(values, str):
                values = [values]

            await page.select_option(selector, values)
            await self.core.log(f"Selected {values} in {selector}", priority=2)
            return {"status": "success", "selector": selector, "values": values}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def select_option_by_ref(self, ref, values, page_id=None):
        """Select dropdown using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            return await self.select_option(selector, values, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def download(self, selector, filename, page_id=None):
        """Download file from link (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            async with page.expect_download() as download_info:
                await page.click(selector)
            download = await download_info.value

            images_dir = self.core.config.get('paths', {}).get('images', './images')
            dl_dir = Path(images_dir) / 'downloads'
            dl_dir.mkdir(parents=True, exist_ok=True)
            download_path = dl_dir / filename
            await download.save_as(download_path)
            await self.core.log(f"Downloaded: {download_path}", priority=2)
            return {"status": "success", "path": str(download_path)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def download_by_ref(self, ref, filename, page_id=None):
        """Download using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            return await self.download(selector, filename, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def dialog(self, action="accept", text=None, page_id=None):
        """Handle dialog (arming call - OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            def handle_dialog(dialog):
                if action == "accept":
                    asyncio.create_task(dialog.accept(text if text else ""))
                else:
                    asyncio.create_task(dialog.dismiss())

            page.once("dialog", handle_dialog)
            await self.core.log(f"Dialog armed: {action}", priority=2)
            return {"status": "success", "action": action}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def highlight(self, selector, page_id=None):
        """Highlight element for debugging (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.evaluate(f"""
                const el = document.querySelector('{selector}');
                if (el) {{
                    el.style.outline = '3px solid red';
                    el.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                }}
            """)
            await self.core.log(f"Highlighted: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def highlight_by_ref(self, ref, page_id=None):
        """Highlight using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}

            selector = self.refs[actual_page_id][ref]
            return await self.highlight(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def resize_viewport(self, width, height, page_id=None):
        """Resize viewport (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.set_viewport_size({"width": width, "height": height})
            await self.core.log(f"Resized viewport: {width}x{height}", priority=2)
            return {"status": "success", "width": width, "height": height}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_console_logs(self, level=None, page_id=None):
        """Get console logs (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            state = pageStates.get(page, {"console": []})
            logs = state.get("console", [])

            if level:
                logs = [log for log in logs if log.get("type") == level]

            return {"status": "success", "logs": logs, "count": len(logs)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_page_errors(self, page_id=None):
        """Get page errors (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            state = pageStates.get(page, {"errors": []})
            errors = state.get("errors", [])

            return {"status": "success", "errors": errors, "count": len(errors)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_network_requests(self, filter_pattern=None, page_id=None):
        """Get network requests (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            state = pageStates.get(page, {"requests": []})
            requests = state.get("requests", [])

            if filter_pattern:
                requests = [r for r in requests if filter_pattern in r.get("url", "")]

            return {"status": "success", "requests": requests, "count": len(requests)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def generate_pdf(self, path=None, page_id=None):
        """Generate PDF (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            if not path:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                br_dir = Path(images_dir) / 'browser'
                br_dir.mkdir(parents=True, exist_ok=True)
                path = str(br_dir / 'page.pdf')

            await page.pdf(path=path)
            await self.core.log(f"PDF generated: {path}", priority=2)
            return {"status": "success", "path": path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_local_storage(self, page_id=None):
        """Get localStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            storage = await page.evaluate("() => Object.assign({}, window.localStorage)")
            return {"status": "success", "storage": storage}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_local_storage(self, key, value, page_id=None):
        """Set localStorage item (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.evaluate(f"() => window.localStorage.setItem('{key}', '{value}')")
            await self.core.log(f"Set localStorage: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_local_storage(self, page_id=None):
        """Clear localStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.evaluate("() => window.localStorage.clear()")
            await self.core.log("Cleared localStorage", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_session_storage(self, page_id=None):
        """Get sessionStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            storage = await page.evaluate("() => Object.assign({}, window.sessionStorage)")
            return {"status": "success", "storage": storage}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_session_storage(self, key, value, page_id=None):
        """Set sessionStorage item (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.evaluate(f"() => window.sessionStorage.setItem('{key}', '{value}')")
            await self.core.log(f"Set sessionStorage: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_session_storage(self, page_id=None):
        """Clear sessionStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            await page.evaluate("() => window.sessionStorage.clear()")
            await self.core.log("Cleared sessionStorage", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_offline(self, offline=True):
        """Set offline mode (OpenClaw parity)."""
        try:
            await self.context.set_offline(offline)
            await self.core.log(f"Offline mode: {offline}", priority=2)
            return {"status": "success", "offline": offline}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_extra_http_headers(self, headers):
        """Set extra HTTP headers (OpenClaw parity)."""
        try:
            await self.context.set_extra_http_headers(headers)
            await self.core.log(f"Set {len(headers)} HTTP headers", priority=2)
            return {"status": "success", "count": len(headers)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_geolocation(self, latitude, longitude, accuracy=None):
        """Set geolocation (OpenClaw parity)."""
        try:
            geo = {"latitude": latitude, "longitude": longitude}
            if accuracy:
                geo["accuracy"] = accuracy

            await self.context.set_geolocation(geo)
            await self.core.log(f"Set geolocation: {latitude}, {longitude}", priority=2)
            return {"status": "success", "latitude": latitude, "longitude": longitude}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_geolocation(self):
        """Clear geolocation (OpenClaw parity)."""
        try:
            await self.context.clear_permissions()
            await self.core.log("Cleared geolocation", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_timezone(self, timezone_id):
        """Set browser timezone by recreating the context (OpenClaw parity - real implementation)."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}

            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass

            self.context = await self.browser.new_context(
                timezone_id=timezone_id,
                no_viewport=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)

            await self.core.log(f"Timezone set to: {timezone_id} (context recreated)", priority=2)
            return {"status": "success", "timezone": timezone_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def emulate_media(self, color_scheme=None, reduced_motion=None):
        """Emulate media features (OpenClaw parity)."""
        try:
            features = []
            if color_scheme:
                features.append({"name": "prefers-color-scheme", "value": color_scheme})
            if reduced_motion:
                features.append({"name": "prefers-reduced-motion", "value": reduced_motion})

            await self.context.emulate_media(color_scheme=color_scheme, reduced_motion=reduced_motion)
            await self.core.log(f"Emulated media: {color_scheme}", priority=2)
            return {"status": "success", "features": features}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ═══════════════════════════════════════════════════════════════════
    # NEW TOOLS — Beyond OpenClaw parity
    # ═══════════════════════════════════════════════════════════════════

    async def set_locale(self, locale):
        """Set browser locale by recreating the context (e.g. 'en-US', 'fr-FR', 'ja-JP')."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}
            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass
            self.context = await self.browser.new_context(
                locale=locale,
                no_viewport=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)
            await self.core.log(f"Locale set to: {locale} (context recreated)", priority=2)
            return {"status": "success", "locale": locale}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_response_body(self, url_pattern=None, page_id=None):
        """Get captured HTTP response bodies. Optionally filter by URL substring."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            state = pageStates.get(page, {"responses": {}})
            responses = state.get("responses", {})
            if url_pattern:
                responses = {k: v for k, v in responses.items() if url_pattern in k}
            return {"status": "success", "responses": responses, "count": len(responses)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click_coords(self, x, y, button="left", page_id=None):
        """Click at exact pixel coordinates. Useful for canvas elements or when selectors fail."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            await page.mouse.click(float(x), float(y), button=button)
            await self.core.log(f"Clicked coords ({x}, {y}) [{button}]", priority=2)
            return {"status": "success", "x": x, "y": y, "button": button}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_frames(self, page_id=None):
        """List all frames (including iframes) on the current page."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            frames = []
            for i, frame in enumerate(page.frames):
                frames.append({"index": i, "name": frame.name, "url": frame.url})
            return {"status": "success", "frames": frames, "count": len(frames)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def frame_action(self, frame_index, action, selector=None, text=None, page_id=None):
        """Perform an action inside an iframe. action: click | type | snapshot | evaluate."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            frames = page.frames
            if frame_index >= len(frames):
                return {"status": "error", "message": f"Frame {frame_index} out of range (have {len(frames)})"}
            frame = frames[frame_index]

            if action == "click":
                await frame.click(selector)
                return {"status": "success", "action": "click", "selector": selector}
            elif action == "type":
                await frame.fill(selector, text or "")
                return {"status": "success", "action": "type", "selector": selector}
            elif action == "snapshot":
                content = await frame.content()
                return {"status": "success", "action": "snapshot", "content": content[:10000]}
            elif action == "evaluate":
                result = await frame.evaluate(text or "")
                return {"status": "success", "action": "evaluate", "result": str(result)}
            else:
                return {"status": "error", "message": f"Unknown action: {action}. Use: click, type, snapshot, evaluate"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def trace_start(self, screenshots=True, snapshots=True, sources=False):
        """Start Playwright tracing (saves screenshots+snapshots for debugging)."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context — start browser first"}
            await self.context.tracing.start(
                screenshots=screenshots,
                snapshots=snapshots,
                sources=sources
            )
            await self.core.log("Playwright tracing started", priority=2)
            return {"status": "success", "screenshots": screenshots, "snapshots": snapshots}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def trace_stop(self, output_path=None, page_id=None):
        """Stop Playwright tracing and save the trace zip file."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context"}
            if not output_path:
                output_path = str(Path(self.core.config['paths']['logs']) / 'trace.zip')
            await self.context.tracing.stop(path=output_path)
            await self.core.log(f"Trace saved: {output_path}", priority=2)
            return {"status": "success", "path": output_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_intercept(self, rules, page_id=None):
        """Intercept network requests."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            self._intercept_rules = rules

            async def handle_route(route, request):
                for rule in self._intercept_rules:
                    if rule.get('pattern', '') in request.url:
                        if rule.get('action') == 'block':
                            await route.abort()
                            return
                        elif rule.get('action') == 'mock':
                            await route.fulfill(
                                status=rule.get('status', 200),
                                content_type=rule.get('content_type', 'application/json'),
                                body=rule.get('body', '{}')
                            )
                            return
                await route.continue_()

            await page.route("**/*", handle_route)
            await self.core.log(f"Network intercept armed: {len(rules)} rule(s)", priority=2)
            return {"status": "success", "rules_count": len(rules)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_intercept(self, page_id=None):
        """Remove all network interception rules."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            self._intercept_rules = []
            await page.unroute("**/*")
            await self.core.log("Network intercept cleared", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def save_session(self, session_name="default"):
        """Save browser cookies & localStorage as a named session for reuse."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context"}
            session_path = str(Path(self.core.config['paths']['logs']) / f'session_{session_name}.json')
            await self.context.storage_state(path=session_path)
            await self.core.log(f"Session saved: {session_name} → {session_path}", priority=2)
            return {"status": "success", "session": session_name, "path": session_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def load_session(self, session_name="default"):
        """Load a previously saved browser session (cookies + localStorage)."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}
            session_path = Path(self.core.config['paths']['logs']) / f'session_{session_name}.json'
            if not session_path.exists():
                return {"status": "error", "message": f"No saved session named '{session_name}'"}

            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass

            self.context = await self.browser.new_context(
                storage_state=str(session_path),
                no_viewport=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)
            await self.core.log(f"Session loaded: {session_name}", priority=2)
            return {"status": "success", "session": session_name}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def restart_with_proxy(self, server, username=None, password=None):
        """Restart the browser with a proxy server (e.g. 'http://proxy:8080')."""
        try:
            if not self.playwright:
                return {"status": "error", "message": "Playwright not started — open browser first"}

            proxy_config = {"server": server}
            if username:
                proxy_config["username"] = username
                proxy_config["password"] = password or ""

            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass

            engine_name = self.core.config.get('browser', {}).get('engine', 'chromium')
            browser_engine = getattr(self.playwright, engine_name, self.playwright.chromium)
            headless = self.core.config.get('browser', {}).get('headless', False)

            self.browser = await browser_engine.launch(
                headless=headless,
                proxy=proxy_config,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            self.context = await self.browser.new_context(
                no_viewport=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {"page_1": page}
            self.active_page_id = "page_1"
            ensurePageState(page)
            await self.core.log(f"Browser restarted with proxy: {server}", priority=2)
            return {"status": "success", "proxy": server}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def close(self):
        """Shutdown browser."""
        if self.browser:
            await self.browser.close()
            await self.playwright.stop()
            self.started = False
            await self.core.log("Browser closed", priority=2)

    async def run(self):
        """Skill background loop."""
        await self.core.log("Browser Pro Active.", priority=2)
        # browser doesn't need a background loop
        while self.enabled:
            await asyncio.sleep(30)
