import asyncio
import json
import logging
import os
import re
import traceback
import httpx
from datetime import datetime
from personality import GalacticPersonality

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GalacticGateway")

# Silence noisy HTTP libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class GalacticGateway:
    def __init__(self, core):
        self.core = core
        self.config = core.config.get('gateway', {})
        self.provider = self.config.get('provider', 'google')
        self.model = self.config.get('model', 'gemini-3-flash-preview')
        self.api_key = self.config.get('api_key', 'NONE')
        
        # Load Personality (dynamic: reads .md files, config, or Byte defaults)
        workspace = core.config.get('paths', {}).get('workspace', '')
        self.personality = GalacticPersonality(config=core.config, workspace=workspace)

        # Token tracking (for /status compatibility)
        self.total_tokens_in = 0
        self.total_tokens_out = 0

        # TTS voice file tracking — set by speak() when text_to_speech tool is invoked
        self.last_voice_file = None
        
        # LLM reference (for /status compatibility and model switching)
        from types import SimpleNamespace
        self.llm = SimpleNamespace(
            provider=self.provider,
            model=self.model,
            api_key=self.api_key
        )
        
        # Tool Registry
        self.tools = {}
        self.register_tools()
        
        # Conversation History
        self.history = []

        # Persistent chat log (JSONL) — survives page refreshes
        logs_dir = core.config.get('paths', {}).get('logs', './logs')
        self.history_file = os.path.join(logs_dir, 'chat_history.jsonl')
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

    def _log_chat(self, role, content, source="web"):
        """Append a chat entry to the persistent JSONL log (survives page refresh)."""
        entry = {
            "ts": datetime.now().isoformat(),
            "role": role,
            "content": content[:2000],  # Cap stored content to prevent log bloat
            "source": source,
        }
        try:
            with open(self.history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    def register_tools(self):
        """Registers available tools for the LLM."""
        self.tools = {
            "read_file": {
                "description": "Read the contents of a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file."}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_read_file
            },
            "write_file": {
                "description": "Write content to a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file."},
                        "content": {"type": "string", "description": "Content to write."}
                    },
                    "required": ["path", "content"]
                },
                "fn": self.tool_write_file
            },
            "exec_shell": {
                "description": "Execute a shell command (PowerShell).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute."}
                    },
                    "required": ["command"]
                },
                "fn": self.tool_exec_shell
            },
            "schedule_task": {
                "description": "Schedule a reminder or task execution.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the task."},
                        "delay_seconds": {"type": "number", "description": "Delay in seconds before execution."},
                        "message": {"type": "string", "description": "Message to display/log when task fires."}
                    },
                    "required": ["name", "delay_seconds", "message"]
                },
                "fn": self.tool_schedule_task
            },
            "list_tasks": {
                "description": "List all scheduled tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
                "fn": self.tool_list_tasks
            },
            "web_search": {
                "description": "Search the web.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."}
                    },
                    "required": ["query"]
                },
                "fn": self.tool_web_search
            },
            "open_browser": {
                "description": "Open a URL in the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open (e.g., https://youtube.com)."}
                    },
                    "required": ["url"]
                },
                "fn": self.tool_open_browser
            },
            "browser_search": {
                "description": "Search YouTube or other site in the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term."}
                    },
                    "required": ["query"]
                },
                "fn": self.tool_browser_search
            },
            "screenshot": {
                "description": "Take a screenshot of the current browser page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to save screenshot (optional)."}
                    }
                },
                "fn": self.tool_screenshot
            },
            "edit_file": {
                "description": "Edit a file by replacing exact text (safer than write_file).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file."},
                        "old_text": {"type": "string", "description": "Exact text to find and replace."},
                        "new_text": {"type": "string", "description": "New text to replace with."}
                    },
                    "required": ["path", "old_text", "new_text"]
                },
                "fn": self.tool_edit_file
            },
            "web_fetch": {
                "description": "Fetch and extract readable content from a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch."},
                        "mode": {"type": "string", "description": "Extract mode: markdown or text (default: markdown)."}
                    },
                    "required": ["url"]
                },
                "fn": self.tool_web_fetch
            },
            "process_start": {
                "description": "Start a background process and track it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to run."},
                        "session_id": {"type": "string", "description": "Unique ID for this process (optional)."}
                    },
                    "required": ["command"]
                },
                "fn": self.tool_process_start
            },
            "process_status": {
                "description": "Check status of a background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Process session ID."}
                    },
                    "required": ["session_id"]
                },
                "fn": self.tool_process_status
            },
            "process_kill": {
                "description": "Kill a background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Process session ID."}
                    },
                    "required": ["session_id"]
                },
                "fn": self.tool_process_kill
            },
            "analyze_image": {
                "description": "Analyze an image using vision models (OCR, description, etc).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to image file."},
                        "prompt": {"type": "string", "description": "What to analyze (default: describe image)."}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_analyze_image
            },
            "memory_search": {
                "description": "Search memory for relevant context using semantic search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to search for in memory."},
                        "top_k": {"type": "number", "description": "Number of results (default: 5)."}
                    },
                    "required": ["query"]
                },
                "fn": self.tool_memory_search
            },
            "memory_imprint": {
                "description": "Save important information to long-term memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What to remember."},
                        "tags": {"type": "string", "description": "Tags/category (optional)."}
                    },
                    "required": ["content"]
                },
                "fn": self.tool_memory_imprint
            },
            "text_to_speech": {
                "description": "Convert text to speech using ElevenLabs. Returns path to audio file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to convert to speech."},
                        "voice": {"type": "string", "description": "Voice name (default: Nova)."}
                    },
                    "required": ["text"]
                },
                "fn": self.tool_text_to_speech
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
                "fn": self.tool_browser_click
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
                "fn": self.tool_browser_type
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
                "fn": self.tool_browser_snapshot
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
                "fn": self.tool_browser_click_by_ref
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
                "fn": self.tool_browser_type_by_ref
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
                "fn": self.tool_browser_fill_form
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
                "fn": self.tool_browser_extract
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
                "fn": self.tool_browser_wait
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
                "fn": self.tool_browser_execute_js
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
                "fn": self.tool_browser_upload
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
                "fn": self.tool_browser_scroll
            },
            "browser_new_tab": {
                "description": "Open a new browser tab/window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open in new tab (optional)"}
                    }
                },
                "fn": self.tool_browser_new_tab
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
                "fn": self.tool_browser_press
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
                "fn": self.tool_browser_hover
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
                "fn": self.tool_browser_hover_by_ref
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
                "fn": self.tool_browser_scroll_into_view
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
                "fn": self.tool_browser_scroll_into_view_by_ref
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
                "fn": self.tool_browser_drag
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
                "fn": self.tool_browser_drag_by_ref
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
                "fn": self.tool_browser_select
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
                "fn": self.tool_browser_select_by_ref
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
                "fn": self.tool_browser_download
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
                "fn": self.tool_browser_download_by_ref
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
                "fn": self.tool_browser_dialog
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
                "fn": self.tool_browser_highlight
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
                "fn": self.tool_browser_highlight_by_ref
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
                "fn": self.tool_browser_resize
            },
            "browser_console_logs": {
                "description": "Get browser console logs (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "description": "Filter by level: log, warn, error, info (optional)"}
                    }
                },
                "fn": self.tool_browser_console_logs
            },
            "browser_page_errors": {
                "description": "Get JavaScript page errors (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_page_errors
            },
            "browser_network_requests": {
                "description": "Get network requests (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {"type": "string", "description": "Filter by URL pattern (optional)"}
                    }
                },
                "fn": self.tool_browser_network_requests
            },
            "browser_pdf": {
                "description": "Generate PDF of current page (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "PDF file path (optional)"}
                    }
                },
                "fn": self.tool_browser_pdf
            },
            "browser_get_local_storage": {
                "description": "Get localStorage data (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_get_local_storage
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
                "fn": self.tool_browser_set_local_storage
            },
            "browser_clear_local_storage": {
                "description": "Clear all localStorage (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_clear_local_storage
            },
            "browser_get_session_storage": {
                "description": "Get sessionStorage data (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_get_session_storage
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
                "fn": self.tool_browser_set_session_storage
            },
            "browser_clear_session_storage": {
                "description": "Clear all sessionStorage (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_clear_session_storage
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
                "fn": self.tool_browser_set_offline
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
                "fn": self.tool_browser_set_headers
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
                "fn": self.tool_browser_set_geolocation
            },
            "browser_clear_geolocation": {
                "description": "Clear geolocation override (OpenClaw parity).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                },
                "fn": self.tool_browser_clear_geolocation
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
                "fn": self.tool_browser_emulate_media
            },
            # ── New tools: Beyond OpenClaw ──────────────────────────
            "browser_set_locale": {
                "description": "Set browser locale (e.g. 'en-US', 'fr-FR', 'ja-JP'). Recreates context so language-sensitive sites respond correctly.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "locale": {"type": "string", "description": "BCP-47 locale string, e.g. 'en-US', 'de-DE'"}
                    },
                    "required": ["locale"]
                },
                "fn": self.tool_browser_set_locale
            },
            "browser_response_body": {
                "description": "Get captured HTTP response bodies for requests made by the current page. Optionally filter by URL substring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url_pattern": {"type": "string", "description": "Optional URL substring to filter responses (e.g. '/api/')"}
                    }
                },
                "fn": self.tool_browser_response_body
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
                "fn": self.tool_browser_click_coords
            },
            "browser_get_frames": {
                "description": "List all frames (iframes) on the current page, with their index, name, and URL.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_browser_get_frames
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
                "fn": self.tool_browser_frame_action
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
                "fn": self.tool_browser_trace_start
            },
            "browser_trace_stop": {
                "description": "Stop Playwright tracing and save the trace.zip file for analysis in Playwright Trace Viewer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Path to save trace.zip (default: logs/trace.zip)"}
                    }
                },
                "fn": self.tool_browser_trace_stop
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
                "fn": self.tool_browser_intercept
            },
            "browser_clear_intercept": {
                "description": "Remove all network interception rules from the current page.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_browser_clear_intercept
            },
            "browser_save_session": {
                "description": "Save the current browser session (cookies, localStorage) to a named file for reuse.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string", "description": "Name for this session (default: 'default')"}
                    }
                },
                "fn": self.tool_browser_save_session
            },
            "browser_load_session": {
                "description": "Load a previously saved browser session (restores cookies and localStorage).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string", "description": "Name of the session to load (default: 'default')"}
                    }
                },
                "fn": self.tool_browser_load_session
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
                "fn": self.tool_browser_set_proxy
            },
        }

    # --- Tool Implementations ---
    async def tool_read_file(self, args):
        path = args.get('path')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    async def tool_write_file(self, args):
        path = args.get('path')
        content = args.get('content')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def tool_exec_shell(self, args):
        command = args.get('command')
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return f"STDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}"
        except Exception as e:
            return f"Error executing command: {e}"
            
    async def tool_web_search(self, args):
        """Web search using DuckDuckGo — returns parsed, ranked results (no API key needed)."""
        query = args.get('query', '')
        if not query:
            return "[ERROR] No search query provided."
        try:
            import urllib.parse
            from bs4 import BeautifulSoup

            encoded_q = urllib.parse.quote_plus(query)
            search_url = f"https://duckduckgo.com/html/?q={encoded_q}"

            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            ) as client:
                response = await client.get(search_url)

            soup = BeautifulSoup(response.text, 'html.parser')
            results = []

            for result in soup.select('.result__body, .result')[:10]:
                title_el  = result.select_one('.result__title, .result__a')
                snippet_el = result.select_one('.result__snippet')
                url_el    = result.select_one('.result__url')

                title   = title_el.get_text(strip=True)   if title_el   else ''
                snippet = snippet_el.get_text(strip=True) if snippet_el else ''
                url     = url_el.get_text(strip=True)     if url_el     else ''

                if title and (snippet or url):
                    results.append({"title": title, "snippet": snippet, "url": url})

            if not results:
                return f"No results found for: '{query}'. Try rephrasing or use web_fetch on a specific URL."

            lines = [f"🔍 Web results for **'{query}'**:\n"]
            for i, r in enumerate(results[:8], 1):
                lines.append(f"{i}. **{r['title']}**")
                if r['snippet']:
                    lines.append(f"   {r['snippet']}")
                if r['url']:
                    lines.append(f"   🔗 {r['url']}")
                lines.append("")

            return "\n".join(lines)

        except ImportError:
            # bs4 not available: fall back to raw fetch
            return f"[Web Search] Query: {query} — Install beautifulsoup4 for parsed results."
        except Exception as e:
            return f"Web search error: {e}"
    
    async def tool_open_browser(self, args):
        """Open a URL in Playwright browser."""
        url = args.get('url')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.navigate(url)
            
            if result['status'] == 'success':
                return f"[BROWSER] Navigated to: {url}"
            else:
                return f"[ERROR] Navigation failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser navigation: {e}"
    
    async def tool_browser_search(self, args):
        """Search on current site (YouTube, Google, etc)."""
        query = args.get('query')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            # Get current page
            page = browser_plugin._get_page()
            if not page:
                return "[ERROR] No browser page open. Open a URL first."
            
            url = page.url
            
            # Handle different sites
            if "youtube.com" in url or "google.com" in url:
                # Type in search box and press enter
                selector = 'input[name="search_query"]' if "youtube.com" in url else 'input[name="q"]'
                result = await browser_plugin.type_text(selector, query, press_enter=True)
                
                if result['status'] == 'success':
                    return f"[BROWSER] Searched for: {query}"
                else:
                    return f"[ERROR] Search failed: {result.get('message', 'Unknown error')}"
            else:
                return f"[ERROR] Don't know how to search on: {url}"
                
        except Exception as e:
            return f"[ERROR] Browser search: {e}"
    
    async def tool_screenshot(self, args):
        """Take a screenshot of the browser."""
        path = args.get('path')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.screenshot(path=path, full_page=True)
            
            if result['status'] == 'success':
                return f"[BROWSER] Screenshot: {result['path']}"
            else:
                return f"[ERROR] Screenshot failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser screenshot: {e}"
    
    async def tool_browser_click(self, args):
        """Click element in browser."""
        selector = args.get('selector')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded. Check galactic_core_v2.py plugin list."
            
            result = await browser_plugin.click(selector)
            if result['status'] == 'success':
                return f"[BROWSER] Clicked: {selector}"
            else:
                return f"[ERROR] Click failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser click: {e}"
    
    async def tool_browser_type(self, args):
        """Type text into browser input field."""
        selector = args.get('selector')
        text = args.get('text')
        press_enter = args.get('press_enter', False)
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.type_text(selector, text, press_enter=press_enter)
            if result['status'] == 'success':
                return f"[BROWSER] Typed into {selector}: {text[:50]}{'...' if len(text) > 50 else ''}"
            else:
                return f"[ERROR] Type failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser type: {e}"
    
    async def tool_browser_snapshot(self, args):
        """Take OpenClaw-style snapshot for ref-based automation."""
        format_type = args.get('format', 'ai')
        interactive = args.get('interactive', False)
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.snapshot(format=format_type, interactive=interactive)
            if result['status'] == 'success':
                # Return snapshot text formatted nicely
                return f"[BROWSER SNAPSHOT - {format_type.upper()} format]\n{result['snapshot']}"
            else:
                return f"[ERROR] Snapshot failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser snapshot: {e}"
    
    async def tool_browser_click_by_ref(self, args):
        """Click element using ref from snapshot (OpenClaw-style)."""
        ref = args.get('ref')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.click_by_ref(ref)
            if result['status'] == 'success':
                return f"[BROWSER] Clicked ref={ref}"
            else:
                return f"[ERROR] Click ref={ref} failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser click by ref: {e}"
    
    async def tool_browser_type_by_ref(self, args):
        """Type text using ref from snapshot (OpenClaw-style)."""
        ref = args.get('ref')
        text = args.get('text')
        press_enter = args.get('press_enter', False)
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.type_by_ref(ref, text, press_enter=press_enter)
            if result['status'] == 'success':
                return f"[BROWSER] Typed into ref={ref}: {text[:50]}{'...' if len(text) > 50 else ''}"
            else:
                return f"[ERROR] Type ref={ref} failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser type by ref: {e}"
    
    async def tool_browser_fill_form(self, args):
        """Fill form with multiple fields."""
        import json as json_lib
        fields_str = args.get('fields')
        submit_selector = args.get('submit_selector')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            fields = json_lib.loads(fields_str)
            result = await browser_plugin.fill_form(fields, submit_selector=submit_selector)
            
            if result['status'] == 'success':
                msg = f"[BROWSER] Filled {result['filled_count']} fields"
                if result.get('submitted'):
                    msg += " and submitted form"
                return msg
            else:
                return f"[ERROR] Form fill failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser fill form: {e}"
    
    async def tool_browser_extract(self, args):
        """Extract text or attribute from page elements by selector or ref."""
        import json as json_lib
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."

            selector = args.get('selector')
            ref = args.get('ref')
            attribute = args.get('attribute', 'text')
            multiple = args.get('multiple', False)

            # Build selector from ref if needed
            if not selector and ref is not None:
                selector = f"[data-ref='{ref}']"

            if not selector:
                return "[ERROR] browser_extract requires 'selector' or 'ref'"

            # Use JS to extract the data
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

            result = await browser_plugin.execute_js(js)
            if result.get('status') == 'success':
                val = result.get('result', 'null')
                return f"[BROWSER] Extracted ({attribute}): {val}"
            else:
                return f"[ERROR] Extract failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser extract: {e}"
    
    async def tool_browser_wait(self, args):
        """Wait for element or text."""
        selector = args.get('selector')
        text = args.get('text')
        timeout = args.get('timeout', 30000)
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.wait_for(selector=selector, text=text, timeout=timeout)
            
            if result['status'] == 'success':
                return f"[BROWSER] Element/text appeared: {selector or text}"
            elif result['status'] == 'timeout':
                return f"[TIMEOUT] Waited {timeout}ms but element didn't appear"
            else:
                return f"[ERROR] Wait failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser wait: {e}"
    
    async def tool_browser_execute_js(self, args):
        """Execute JavaScript in browser."""
        script = args.get('script')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.execute_js(script)
            
            if result['status'] == 'success':
                return f"[BROWSER] JS Result: {result.get('result', 'No return value')}"
            else:
                return f"[ERROR] JS execution failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser execute JS: {e}"
    
    async def tool_browser_upload(self, args):
        """Upload file via browser."""
        selector = args.get('selector')
        file_path = args.get('file_path')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.upload_file(selector, file_path)
            
            if result['status'] == 'success':
                return f"[BROWSER] Uploaded: {file_path}"
            else:
                return f"[ERROR] Upload failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser upload: {e}"
    
    async def tool_browser_scroll(self, args):
        """Scroll browser page."""
        direction = args.get('direction', 'down')
        amount = args.get('amount')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.scroll(direction, amount)
            
            if result['status'] == 'success':
                return f"[BROWSER] Scrolled {direction}"
            else:
                return f"[ERROR] Scroll failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser scroll: {e}"
    
    async def tool_browser_new_tab(self, args):
        """Open new browser tab."""
        url = args.get('url')
        try:
            browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
            if not browser_plugin:
                return "[ERROR] BrowserExecutorPro plugin not loaded."
            
            result = await browser_plugin.new_tab(url)
            
            if result['status'] == 'success':
                return f"[BROWSER] New tab: {result['page_id']} (URL: {url or 'blank'})"
            else:
                return f"[ERROR] New tab failed: {result.get('message', 'Unknown error')}"
        except Exception as e:
            return f"[ERROR] Browser new tab: {e}"
    
    async def tool_browser_press(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.press(args.get('key'))
        return f"[BROWSER] Pressed: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_hover(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.hover(args.get('selector'))
        return f"[BROWSER] Hovered: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_hover_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.hover_by_ref(args.get('ref'))
        return f"[BROWSER] Hovered ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_scroll_into_view(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.scroll_into_view(args.get('selector'))
        return f"[BROWSER] Scrolled into view: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_scroll_into_view_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.scroll_into_view_by_ref(args.get('ref'))
        return f"[BROWSER] Scrolled into view ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_drag(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.drag(args.get('from_selector'), args.get('to_selector'))
        return f"[BROWSER] Dragged {args.get('from_selector')} to {args.get('to_selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_drag_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.drag_by_ref(args.get('from_ref'), args.get('to_ref'))
        return f"[BROWSER] Dragged ref={args.get('from_ref')} to ref={args.get('to_ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_select(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        values = args.get('values').split(',') if ',' in args.get('values', '') else args.get('values')
        result = await browser_plugin.select_option(args.get('selector'), values)
        return f"[BROWSER] Selected {values} in {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_select_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        values = args.get('values').split(',') if ',' in args.get('values', '') else args.get('values')
        result = await browser_plugin.select_option_by_ref(args.get('ref'), values)
        return f"[BROWSER] Selected {values} in ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_download(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.download(args.get('selector'), args.get('filename'))
        return f"[BROWSER] Downloaded to: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_download_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.download_by_ref(args.get('ref'), args.get('filename'))
        return f"[BROWSER] Downloaded to: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_dialog(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.dialog(args.get('action'), args.get('text'))
        return f"[BROWSER] Dialog armed: {args.get('action')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_highlight(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.highlight(args.get('selector'))
        return f"[BROWSER] Highlighted: {args.get('selector')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_highlight_by_ref(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.highlight_by_ref(args.get('ref'))
        return f"[BROWSER] Highlighted ref={args.get('ref')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_resize(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.resize_viewport(args.get('width'), args.get('height'))
        return f"[BROWSER] Resized to {args.get('width')}x{args.get('height')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_console_logs(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.get_console_logs(args.get('level'))
        if result['status'] == 'success':
            logs = result.get('logs', [])
            return f"[BROWSER] Console logs ({len(logs)} entries):\n" + "\n".join([f"[{log.get('type')}] {log.get('text')}" for log in logs[:20]])
        return f"[ERROR] {result.get('message')}"
    
    async def tool_browser_page_errors(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.get_page_errors()
        if result['status'] == 'success':
            errors = result.get('errors', [])
            return f"[BROWSER] Page errors ({len(errors)} entries):\n" + "\n".join([err.get('message', '') for err in errors[:10]])
        return f"[ERROR] {result.get('message')}"
    
    async def tool_browser_network_requests(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.get_network_requests(args.get('filter'))
        if result['status'] == 'success':
            requests = result.get('requests', [])
            return f"[BROWSER] Network requests ({len(requests)} entries):\n" + "\n".join([f"{req.get('method')} {req.get('url')}" for req in requests[:15]])
        return f"[ERROR] {result.get('message')}"
    
    async def tool_browser_pdf(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.generate_pdf(args.get('path'))
        return f"[BROWSER] PDF generated: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_get_local_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.get_local_storage()
        if result['status'] == 'success':
            storage = result.get('storage', {})
            return f"[BROWSER] localStorage ({len(storage)} items):\n" + "\n".join([f"{k}: {v}" for k, v in storage.items()])
        return f"[ERROR] {result.get('message')}"
    
    async def tool_browser_set_local_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.set_local_storage(args.get('key'), args.get('value'))
        return f"[BROWSER] Set localStorage: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_clear_local_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.clear_local_storage()
        return "[BROWSER] localStorage cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_get_session_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.get_session_storage()
        if result['status'] == 'success':
            storage = result.get('storage', {})
            return f"[BROWSER] sessionStorage ({len(storage)} items):\n" + "\n".join([f"{k}: {v}" for k, v in storage.items()])
        return f"[ERROR] {result.get('message')}"
    
    async def tool_browser_set_session_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.set_session_storage(args.get('key'), args.get('value'))
        return f"[BROWSER] Set sessionStorage: {args.get('key')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_clear_session_storage(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.clear_session_storage()
        return "[BROWSER] sessionStorage cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_set_offline(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.set_offline(args.get('offline'))
        return f"[BROWSER] Offline mode: {args.get('offline')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_set_headers(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        headers = json.loads(args.get('headers'))
        result = await browser_plugin.set_extra_http_headers(headers)
        return f"[BROWSER] Set {result.get('count')} HTTP headers" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_set_geolocation(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.set_geolocation(args.get('latitude'), args.get('longitude'), args.get('accuracy'))
        return f"[BROWSER] Geolocation set: {args.get('latitude')}, {args.get('longitude')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_clear_geolocation(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.clear_geolocation()
        return "[BROWSER] Geolocation cleared" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"
    
    async def tool_browser_emulate_media(self, args):
        browser_plugin = next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)
        if not browser_plugin:
            return "[ERROR] BrowserExecutorPro plugin not loaded."
        result = await browser_plugin.emulate_media(args.get('color_scheme'))
        return f"[BROWSER] Media emulated: {args.get('color_scheme')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    # ── New tool handlers ──────────────────────────────────────────

    def _get_browser_plugin(self):
        return next((p for p in self.core.plugins if "BrowserExecutorPro" in p.__class__.__name__), None)

    async def tool_browser_set_locale(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.set_locale(args.get('locale', 'en-US'))
        return f"[BROWSER] Locale set: {args.get('locale')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_response_body(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.get_response_body(args.get('url_pattern'))
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

    async def tool_browser_click_coords(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.click_coords(args.get('x', 0), args.get('y', 0), args.get('button', 'left'))
        return f"[BROWSER] Clicked ({args.get('x')}, {args.get('y')})" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_get_frames(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.get_frames()
        if result['status'] == 'success':
            frames = result['frames']
            if not frames:
                return "[BROWSER] No frames found (page has no iframes)."
            lines = [f"[BROWSER] {len(frames)} frame(s):"]
            for f in frames:
                lines.append(f"  [{f['index']}] name='{f['name']}' url={f['url']}")
            return "\n".join(lines)
        return f"[ERROR] {result.get('message')}"

    async def tool_browser_frame_action(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.frame_action(
            int(args.get('frame_index', 0)),
            args.get('action', 'snapshot'),
            args.get('selector'),
            args.get('text')
        )
        if result['status'] == 'success':
            content = result.get('content') or result.get('result') or ''
            return f"[BROWSER/FRAME] {result['action']} OK{': ' + content[:500] if content else ''}"
        return f"[ERROR] {result.get('message')}"

    async def tool_browser_trace_start(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.trace_start(
            screenshots=args.get('screenshots', True),
            snapshots=args.get('snapshots', True)
        )
        return "[BROWSER] Playwright tracing started." if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_trace_stop(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.trace_stop(args.get('output_path'))
        return f"[BROWSER] Trace saved: {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_intercept(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        rules = args.get('rules', [])
        result = await bp.set_intercept(rules)
        return f"[BROWSER] Intercept armed: {result.get('rules_count', 0)} rule(s)" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_clear_intercept(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.clear_intercept()
        return "[BROWSER] Intercept rules cleared." if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_save_session(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.save_session(args.get('session_name', 'default'))
        return f"[BROWSER] Session saved: {result.get('session')} → {result.get('path')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_load_session(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.load_session(args.get('session_name', 'default'))
        return f"[BROWSER] Session loaded: {result.get('session')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_browser_set_proxy(self, args):
        bp = self._get_browser_plugin()
        if not bp: return "[ERROR] BrowserExecutorPro not loaded."
        result = await bp.restart_with_proxy(
            args.get('server', ''),
            args.get('username'),
            args.get('password')
        )
        return f"[BROWSER] Proxy set: {result.get('proxy')}" if result['status'] == 'success' else f"[ERROR] {result.get('message')}"

    async def tool_schedule_task(self, args):
        """Schedule a task/reminder using the scheduler plugin."""
        name = args.get('name')
        delay_seconds = args.get('delay_seconds')
        message = args.get('message')
        
        try:
            # Check if scheduler plugin is available
            scheduler_plugin = next((p for p in self.core.plugins if "Scheduler" in p.__class__.__name__), None)
            if scheduler_plugin:
                await scheduler_plugin.schedule_task(name, delay_seconds, message)
                return f"Task '{name}' scheduled to fire in {delay_seconds} seconds."
            else:
                return "Scheduler plugin not available. Task not scheduled."
        except Exception as e:
            return f"Error scheduling task: {e}"
    
    async def tool_list_tasks(self, args):
        """List all scheduled tasks."""
        try:
            scheduler_plugin = next((p for p in self.core.plugins if "Scheduler" in p.__class__.__name__), None)
            if scheduler_plugin:
                tasks = await scheduler_plugin.list_tasks()
                if tasks:
                    return json.dumps(tasks, indent=2)
                else:
                    return "No scheduled tasks."
            else:
                return "Scheduler plugin not available."
        except Exception as e:
            return f"Error listing tasks: {e}"
    
    async def tool_edit_file(self, args):
        """Edit a file by finding and replacing exact text."""
        path = args.get('path')
        old_text = args.get('old_text')
        new_text = args.get('new_text')
        
        try:
            # Read current content
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if old_text exists
            if old_text not in content:
                return f"Error: Could not find exact text in {path}. No changes made."
            
            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: Found {count} occurrences of text. Please be more specific. No changes made."
            
            # Replace
            new_content = content.replace(old_text, new_text, 1)
            
            # Write back
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return f"[OK] Successfully edited {path} (replaced 1 occurrence)"
        except Exception as e:
            return f"Error editing file: {e}"
    
    async def tool_web_fetch(self, args):
        """Fetch and extract readable content from a URL."""
        url = args.get('url')
        mode = args.get('mode', 'markdown')
        
        try:
            import httpx
            from bs4 import BeautifulSoup
            
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, verify=False) as client:
                response = await client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                
                # Get text
                if mode == 'text':
                    text = soup.get_text(separator='\n', strip=True)
                else:  # markdown mode
                    # Basic markdown conversion
                    title = soup.find('title')
                    title_text = f"# {title.string}\n\n" if title else ""
                    
                    body = soup.find('body') or soup
                    paragraphs = body.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li'])
                    
                    text_parts = [title_text]
                    for p in paragraphs:
                        tag_name = p.name
                        text_content = p.get_text(strip=True)
                        
                        if tag_name == 'h1':
                            text_parts.append(f"\n# {text_content}\n")
                        elif tag_name == 'h2':
                            text_parts.append(f"\n## {text_content}\n")
                        elif tag_name == 'h3':
                            text_parts.append(f"\n### {text_content}\n")
                        elif tag_name == 'li':
                            text_parts.append(f"- {text_content}")
                        else:
                            text_parts.append(text_content)
                    
                    text = '\n'.join(text_parts)
                
                # Limit length
                max_chars = 8000
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[... content truncated]"
                
                return f"[DOC] Content from {url}:\n\n{text}"
        except Exception as e:
            return f"Error fetching URL: {e}"
    
    async def tool_process_start(self, args):
        """Start a background process."""
        command = args.get('command')
        session_id = args.get('session_id', f"proc_{int(asyncio.get_event_loop().time())}")
        
        try:
            # Store processes in core if not exists
            if not hasattr(self.core, 'processes'):
                self.core.processes = {}
            
            # Start process
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.core.processes[session_id] = {
                'process': process,
                'command': command,
                'started': asyncio.get_event_loop().time(),
                'stdout': [],
                'stderr': []
            }
            
            # Start log collection task
            asyncio.create_task(self._collect_process_output(session_id))
            
            return f"[RUN] Process started: {session_id}\nCommand: {command}\nPID: {process.pid}"
        except Exception as e:
            return f"Error starting process: {e}"
    
    async def _collect_process_output(self, session_id):
        """Collect output from a running process."""
        try:
            proc_info = self.core.processes.get(session_id)
            if not proc_info:
                return
            
            process = proc_info['process']
            
            # Read stdout
            if process.stdout:
                async for line in process.stdout:
                    proc_info['stdout'].append(line.decode())
            
            # Wait for completion
            await process.wait()
            proc_info['exit_code'] = process.returncode
            proc_info['finished'] = asyncio.get_event_loop().time()
            
        except Exception as e:
            await self.core.log(f"Process output collection error: {e}", priority=1)
    
    async def tool_process_status(self, args):
        """Check status of a background process."""
        session_id = args.get('session_id')
        
        try:
            if not hasattr(self.core, 'processes') or session_id not in self.core.processes:
                return f"[ERR] Process not found: {session_id}"
            
            proc_info = self.core.processes[session_id]
            process = proc_info['process']
            
            status = "running" if process.returncode is None else f"exited ({process.returncode})"
            runtime = asyncio.get_event_loop().time() - proc_info['started']
            
            stdout_preview = ''.join(proc_info['stdout'][-10:])[:500]
            
            return (
                f"[STATUS] Process Status: {session_id}\n"
                f"Command: {proc_info['command']}\n"
                f"PID: {process.pid}\n"
                f"Status: {status}\n"
                f"Runtime: {runtime:.1f}s\n"
                f"Recent output:\n{stdout_preview}"
            )
        except Exception as e:
            return f"Error checking process: {e}"
    
    async def tool_process_kill(self, args):
        """Kill a background process."""
        session_id = args.get('session_id')
        
        try:
            if not hasattr(self.core, 'processes') or session_id not in self.core.processes:
                return f"[ERR] Process not found: {session_id}"
            
            proc_info = self.core.processes[session_id]
            process = proc_info['process']
            
            if process.returncode is None:
                process.kill()
                await process.wait()
                return f"[KILL] Process killed: {session_id}"
            else:
                return f"Process already exited: {session_id} (code {process.returncode})"
        except Exception as e:
            return f"Error killing process: {e}"
    
    async def tool_analyze_image(self, args):
        """Analyze an image — routes to Gemini Vision, Ollama vision models, or any available provider."""
        path = args.get('path')
        prompt = args.get('prompt', 'Describe this image in detail. Include any text you see.')

        import base64
        from pathlib import Path

        if not path or not Path(path).exists():
            return f"[ERR] Image not found: {path}"

        provider = self.llm.provider

        if provider == "google":
            return await self._analyze_image_gemini(path, prompt)
        elif provider == "ollama":
            return await self._analyze_image_ollama(path, prompt)
        else:
            # Try Google first as universal fallback; if no key try Ollama
            google_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
            if google_key:
                return await self._analyze_image_gemini(path, prompt)
            return await self._analyze_image_ollama(path, prompt)

    async def _analyze_image_gemini(self, path, prompt):
        """Analyze image using Google Gemini Vision."""
        import base64
        from pathlib import Path
        try:
            with open(path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            suffix = Path(path).suffix.lower()
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                        '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
            mime_type = mime_map.get(suffix, 'image/jpeg')

            api_key = self.config.get('api_key') or self.core.config.get('providers', {}).get('google', {}).get('apiKey')
            if not api_key:
                return "[ERR] Google API key not configured for image analysis."

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": image_data}}
            ]}]}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                data = response.json()
                if 'candidates' in data and data['candidates']:
                    result = data['candidates'][0]['content']['parts'][0]['text']
                    return f"[VISION/Gemini] {Path(path).name}:\n\n{result}"
                return f"[ERR] Gemini vision error: {data}"
        except Exception as e:
            return f"Error analyzing image (Gemini): {e}"

    async def _analyze_image_ollama(self, path, prompt):
        """Analyze image using an Ollama vision model (llava, moondream, etc)."""
        import base64
        from pathlib import Path
        try:
            with open(path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            ollama_base = self.core.config.get('providers', {}).get('ollama', {}).get('baseUrl', 'http://127.0.0.1:11434/v1')
            if not ollama_base.rstrip('/').endswith('/v1'):
                ollama_base = ollama_base.rstrip('/') + '/v1'
            url = f"{ollama_base}/chat/completions"

            payload = {
                "model": self.llm.model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                    ]
                }]
            }

            async with httpx.AsyncClient(timeout=90.0, verify=False) as client:
                response = await client.post(url, json=payload)
                data = response.json()
                if 'choices' in data and data['choices']:
                    result = data['choices'][0]['message']['content']
                    return f"[VISION/Ollama] {Path(path).name}:\n\n{result}"
                return f"[ERR] Ollama vision error: {data}\n(Ensure you're using a vision-capable model like llava or moondream)"
        except Exception as e:
            return f"Error analyzing image (Ollama): {e}"
    
    async def tool_memory_search(self, args):
        """Search semantic memory for relevant context."""
        query = args.get('query')
        top_k = int(args.get('top_k', 5))
        
        try:
            # Access core memory (could be semantic or keyword-based)
            if hasattr(self.core, 'memory'):
                results = await self.core.memory.recall(query, top_k=top_k)
                
                if not results:
                    return f"[MEMORY] No relevant memories found for: {query}"
                
                # Format results
                formatted = [f"[MEMORY] Found {len(results)} relevant memories:\n"]
                for i, mem in enumerate(results, 1):
                    score = mem.get('relevance_score', 'N/A')
                    content_preview = mem['content'][:200] + "..." if len(mem['content']) > 200 else mem['content']
                    source = mem.get('metadata', {}).get('source', 'unknown')
                    formatted.append(f"\n{i}. [Score: {score}] ({source})\n{content_preview}\n")
                
                return "".join(formatted)
            else:
                return "[ERR] Memory system not available."
        except Exception as e:
            return f"Error searching memory: {e}"
    
    async def tool_memory_imprint(self, args):
        """Save information to long-term memory and persist to MEMORY.md."""
        content = args.get('content')
        tags = args.get('tags', '')

        try:
            if hasattr(self.core, 'memory'):
                metadata = {
                    "source": "manual_imprint",
                    "tags": tags
                }
                await self.core.memory.imprint(content, metadata)

                # Also write to MEMORY.md so it appears in every future system prompt
                try:
                    workspace = self.core.config.get('paths', {}).get('workspace', '')
                    if workspace:
                        memory_path = os.path.join(workspace, 'MEMORY.md')
                        from datetime import datetime
                        timestamp = datetime.now().strftime('%Y-%m-%d')
                        tag_str = f" [{tags}]" if tags else ""
                        entry = f"\n- {timestamp}{tag_str}: {content}"
                        # Create file with header if it doesn't exist
                        if not os.path.exists(memory_path):
                            with open(memory_path, 'w', encoding='utf-8') as f:
                                f.write("# Memory\n")
                        with open(memory_path, 'a', encoding='utf-8') as f:
                            f.write(entry)
                        # Reload personality so next prompt includes this memory
                        if hasattr(self, 'personality') and hasattr(self.personality, 'reload_memory'):
                            self.personality.reload_memory()
                except Exception:
                    pass  # MEMORY.md write is best-effort; imprint already succeeded

                return f"[MEMORY] Saved to long-term memory. Tags: {tags or 'none'}"
            else:
                return "[ERR] Memory system not available."
        except Exception as e:
            return f"Error saving to memory: {e}"
    
    async def tool_text_to_speech(self, args):
        """Convert text to speech using ElevenLabs, edge-tts (free male), or gTTS fallback."""
        text = args.get('text')
        # Voice options:
        #   'Nova'  → ElevenLabs Rachel (female, premium)
        #   'Byte'  → ElevenLabs Adam (male, premium)
        #   'Guy'   → edge-tts en-US-GuyNeural (male, FREE, no key needed)
        #   'Aria'  → edge-tts en-US-AriaNeural (female, FREE, no key needed)
        #   'gtts'  → Google TTS (female, FREE, no key needed)
        # Default pulled from config.yaml elevenlabs.voice, fallback to 'Guy'
        cfg_voice = self.core.config.get('elevenlabs', {}).get('voice', 'Guy')
        voice = args.get('voice', cfg_voice)

        try:
            import hashlib as _hashlib

            text_hash = _hashlib.md5(text.encode()).hexdigest()[:8]
            logs_dir = self.config.get('paths', {}).get('logs', './logs')
            os.makedirs(logs_dir, exist_ok=True)

            # ── ElevenLabs (premium) ─────────────────────────────────────────
            el_key = self.core.config.get('elevenlabs', {}).get('api_key', '')
            if el_key and voice in ('Nova', 'Byte', 'Default'):
                try:
                    from elevenlabs import generate, save
                    voice_map = {
                        'Nova':    '21m00Tcm4TlvDq8ikWAM',  # Rachel
                        'Byte':    'pNInz6obpgDQGcFmaJgB',  # Adam
                        'Default': '21m00Tcm4TlvDq8ikWAM',
                    }
                    output_path = os.path.join(logs_dir, f'tts_{text_hash}.mp3')
                    audio = generate(text=text, voice=voice_map.get(voice, voice_map['Default']), api_key=el_key)
                    save(audio, output_path)
                    return f"[VOICE] Generated speech: {output_path}"
                except Exception as e:
                    pass  # Fall through to free options

            # ── edge-tts (FREE — Microsoft neural voices, no key needed) ─────
            # Voices: Guy = male, Aria = female, Jenny = female, Davis = male
            edge_voice_map = {
                'Guy':   'en-US-GuyNeural',    # Natural male voice
                'Davis': 'en-US-DavisNeural',  # Expressive male voice
                'Aria':  'en-US-AriaNeural',   # Natural female voice
                'Jenny': 'en-US-JennyNeural',  # Friendly female voice
                'Byte':  'en-US-GuyNeural',    # Byte defaults to Guy when no EL key
                'Nova':  'en-US-AriaNeural',   # Nova defaults to Aria when no EL key
            }
            edge_voice_name = edge_voice_map.get(voice, 'en-US-GuyNeural')
            try:
                import edge_tts
                output_path = os.path.join(logs_dir, f'tts_{text_hash}.mp3')
                communicate = edge_tts.Communicate(text, edge_voice_name)
                await communicate.save(output_path)
                return f"[VOICE] Generated speech: {output_path}"
            except ImportError:
                pass  # edge-tts not installed, fall through to gTTS

            # ── gTTS (FREE fallback — female only) ───────────────────────────
            try:
                from gtts import gTTS
                output_path = os.path.join(logs_dir, f'tts_{text_hash}.mp3')
                gTTS(text=text, lang='en', slow=False).save(output_path)
                return f"[VOICE] Generated speech: {output_path}"
            except ImportError:
                pass

            return "[ERR] No TTS engine available. Run: pip install edge-tts"

        except Exception as e:
            return f"Error generating speech: {e}"

    # --- LLM Interaction ---

    def _extract_tool_call(self, response_text):
        """
        Robustly extract a tool-call JSON object from an LLM response.

        Handles all the messy ways local models (Qwen, Llama, Mistral, etc.) output JSON:
          • Bare JSON:                  {"tool": "...", "args": {...}}
          • Markdown fenced:            ```json\n{"tool":...}\n```
          • Inline wrapped:             "I'll use the tool: {"tool":...}"
          • Think-tag wrapped (Qwen3):  <think>...</think>{"tool":...}
          • action/action_input schema: {"action":"tool","action_input":{...}}
          • Nested tool schema:         {"name":"tool","parameters":{...}}

        Returns (tool_name, tool_args) tuple or (None, None) if no valid tool call found.
        """
        if not response_text or "{" not in response_text:
            return None, None

        # Step 1: Strip <think>...</think> blocks (Qwen3, DeepSeek-R1 emit these)
        cleaned = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

        # Step 2: Try to pull JSON from markdown code fences first (highest confidence)
        fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        candidates = []
        if fence_match:
            candidates.append(fence_match.group(1))

        # Step 3: Find ALL {...} spans in the cleaned text (greedy outer-most)
        # We look for balanced braces to handle nested objects properly
        for i, ch in enumerate(cleaned):
            if ch == '{':
                depth = 0
                for j in range(i, len(cleaned)):
                    if cleaned[j] == '{':
                        depth += 1
                    elif cleaned[j] == '}':
                        depth -= 1
                        if depth == 0:
                            candidates.append(cleaned[i:j+1])
                            break

        # Step 4: Try each candidate JSON blob
        for json_str in candidates:
            try:
                obj = json.loads(json_str)
                if not isinstance(obj, dict):
                    continue

                # Schema A: standard Galactic format {"tool": "name", "args": {...}}
                if "tool" in obj and "args" in obj:
                    return obj["tool"], obj["args"]

                # Schema B: LangChain-style {"action": "name", "action_input": {...}}
                if "action" in obj and "action_input" in obj:
                    return obj["action"], obj["action_input"]

                # Schema C: OpenAI function-call style {"name": "name", "parameters": {...}}
                if "name" in obj and "parameters" in obj and obj["name"] in self.tools:
                    return obj["name"], obj["parameters"]

                # Schema D: {"function": "name", "arguments": {...}}
                if "function" in obj and "arguments" in obj:
                    args = obj["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    return obj["function"], args

            except (json.JSONDecodeError, TypeError):
                continue

        return None, None

    def _build_system_prompt(self, context="", is_ollama=False):
        """
        Build the system prompt.  For Ollama/local models we inject:
          - Full parameter schemas (not just descriptions) so the model
            knows exact argument names and types
          - Concrete few-shot examples of correct tool-call JSON
          - Explicit instruction to output ONLY raw JSON (no markdown, no prose)
        """
        personality_prompt = self.personality.get_system_prompt()

        if is_ollama:
            # Full schema for every tool so local models know what args to pass
            tool_schemas = {}
            for name, tool in self.tools.items():
                tool_schemas[name] = {
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {})
                }
            tool_block = json.dumps(tool_schemas, indent=2)

            few_shot = (
                'EXAMPLES OF CORRECT TOOL CALLS:\n'
                '  Read a file:\n'
                '  {"tool": "read_file", "args": {"path": "C:\\\\data\\\\notes.txt"}}\n\n'
                '  Run a shell command:\n'
                '  {"tool": "exec_shell", "args": {"command": "dir C:\\\\Users"}}\n\n'
                '  Navigate browser to URL:\n'
                '  {"tool": "browser_navigate", "args": {"url": "https://example.com"}}\n\n'
                '  Take a screenshot:\n'
                '  {"tool": "browser_screenshot", "args": {}}\n\n'
                '  Search the web:\n'
                '  {"tool": "web_search", "args": {"query": "python asyncio tutorial"}}\n'
            )

            protocol = (
                "TOOL USAGE RULES — FOLLOW EXACTLY:\n"
                "1. To use a tool output ONLY a raw JSON object. NO markdown. NO prose. NO code fences.\n"
                "   CORRECT:   {\"tool\": \"read_file\", \"args\": {\"path\": \"/tmp/a.txt\"}}\n"
                "   WRONG:     ```json\\n{...}\\n```   (never use fences)\n"
                "   WRONG:     'I will read the file: {...}'  (never wrap in prose)\n"
                "2. After a tool output appears as 'Tool Output: ...' give your FINAL answer in plain text.\n"
                "3. For simple tasks: use 1 tool then answer immediately.\n"
                "4. For complex tasks: chain up to 10 tool calls, then answer.\n"
                "5. NEVER repeat a tool call with the same args — trust the output.\n"
                "6. If you don't need a tool, just answer in plain text — no JSON.\n"
            )

            system_prompt = (
                f"{personality_prompt}\n\n"
                f"AVAILABLE TOOLS (with parameter schemas):\n{tool_block}\n\n"
                f"{few_shot}\n"
                f"{protocol}\n"
                f"Context: {context}"
            )
        else:
            # Cloud models: concise descriptions are enough — they already follow JSON tool protocols
            tool_desc = json.dumps(
                {k: v['description'] for k, v in self.tools.items()}, indent=2
            )
            system_prompt = (
                f"{personality_prompt}\n\n"
                f"You have access to the following tools:\n{tool_desc}\n\n"
                f"TOOL USAGE PROTOCOL:\n"
                f"- To use a tool: respond with ONLY a JSON object: {{\"tool\": \"tool_name\", \"args\": {{...}}}}\n"
                f"- After using a tool: you'll see the output and can use another tool OR give your final answer\n"
                f"- When you have enough information: STOP using tools and give a complete answer\n"
                f"- For SIMPLE tasks (write file, read file, single command): use 1 tool then ANSWER immediately\n"
                f"- For 'systems check' queries: gather 2-3 key metrics then ANSWER, don't exhaust all tools\n"
                f"- For COMPLEX tasks (multi-step automation): you can use up to 10 tools\n"
                f"- NEVER verify what you just did - trust the tool output and respond to the user!\n"
                f"Context: {context}"
            )

        return system_prompt

    async def _send_telegram_typing_ping(self, chat_id):
        """Helper to send a typing indicator to Telegram if the bridge is active."""
        if hasattr(self.core, 'telegram_bridge'):
            try:
                await self.core.telegram_bridge.send_typing(chat_id)
            except Exception as e:
                await self.core.log(f"Telegram typing ping error: {e}", priority=1)

    async def speak(self, user_input, context="", chat_id=None):
        """
        Main entry point for user interaction.
        Implements a ReAct loop: Think -> Act -> Observe -> Answer.

        Ollama/local models get:
          - Full parameter schemas in system prompt
          - Few-shot tool-call examples
          - Robust multi-pattern JSON extraction (handles think-tags, fences, prose wrapping)
          - Full messages array passed directly (not collapsed to a string)
        """
        # Track input tokens (rough estimate: 1 token ~= 4 chars)
        self.total_tokens_in += len(user_input) // 4

        # Reset per-turn state
        self.last_voice_file = None

        self.history.append({"role": "user", "content": user_input})

        # Persist to JSONL
        source = "telegram" if chat_id else "web"
        self._log_chat("user", user_input, source=source)

        # Smart model routing — pick the best model for this task type (opt-in via config)
        model_mgr = getattr(self.core, 'model_manager', None)
        if model_mgr:
            await model_mgr.auto_route(user_input)

        # Determine if we're on a local/Ollama model
        is_ollama = (self.llm.provider == "ollama")

        # 1. Build system prompt (Ollama gets full schemas + few-shot examples)
        system_prompt = self._build_system_prompt(context=context, is_ollama=is_ollama)
        messages = [{"role": "system", "content": system_prompt}] + self.history[-5:]

        # 2. ReAct Loop
        max_turns = int(self.config.get('models', {}).get('max_turns', 50))
        turn_count = 0
        last_tool_call = None  # Track last (tool_name, json_args_str) to prevent duplicate calls
        # Tools that are legitimately called repeatedly with same args (snapshots, reads, etc.)
        _DUPLICATE_EXEMPT = {'browser_snapshot', 'web_search', 'read_file', 'memory_search'}

        for _ in range(max_turns):
            turn_count += 1
            await self._send_telegram_typing_ping(chat_id)
            response_text = await self._call_llm(messages)

            # Strip think-tags from final response text (Qwen3/DeepSeek-R1)
            display_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

            # Try to extract a tool call
            tool_name, tool_args = self._extract_tool_call(response_text)

            if tool_name is not None:
                # Duplicate-call guard (prevents infinite loops with stubborn models)
                # Exempt tools that are legitimately called repeatedly (snapshots, searches, etc.)
                call_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                if call_sig == last_tool_call and tool_name not in _DUPLICATE_EXEMPT:
                    await self.core.log(
                        f"⚠️ Duplicate tool call detected ({tool_name}), forcing final answer.",
                        priority=2
                    )
                    # Force the model to give a final answer
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            "You already called that tool with those arguments. "
                            "Please give your FINAL answer now in plain text — no more tool calls."
                        )
                    })
                    last_tool_call = None
                    continue
                last_tool_call = call_sig

                # Fuzzy tool name match: handle "browser.navigate" → "browser_navigate" etc.
                if tool_name not in self.tools:
                    normalized = tool_name.replace(".", "_").replace("-", "_").lower()
                    if normalized in self.tools:
                        tool_name = normalized
                    else:
                        # Try prefix match (e.g. model said "navigate" and we have "browser_navigate")
                        matches = [t for t in self.tools if t.endswith(f"_{normalized}") or t == normalized]
                        if len(matches) == 1:
                            tool_name = matches[0]

                await self.core.log(f"🛠️ Executing: {tool_name} {tool_args}", priority=2)

                if tool_name in self.tools:
                    try:
                        result = await self.tools[tool_name]["fn"](tool_args)
                        await self._send_telegram_typing_ping(chat_id)
                    except Exception as e:
                        result = f"[Tool Error] {tool_name} raised: {type(e).__name__}: {e}"

                    # Track TTS output so callers (telegram_bridge) can send the audio file
                    if tool_name == "text_to_speech" and "[VOICE]" in str(result):
                        voice_match = re.search(r'Generated speech.*?:\s*(.+\.mp3)', str(result))
                        if voice_match:
                            self.last_voice_file = voice_match.group(1).strip()

                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({"role": "user", "content": f"Tool Output: {result}"})
                    continue  # Loop back to LLM with result
                else:
                    tool_list_hint = ", ".join(list(self.tools.keys())[:20]) + "..."
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Error: Tool '{tool_name}' not found. "
                            f"Available tools include: {tool_list_hint} "
                            f"Please use the exact tool name from the list, then try again."
                        )
                    })
                    continue

            # No tool call detected → this is the final answer
            # Use display_text (think-tags stripped) for the history and relay
            self.history.append({"role": "assistant", "content": display_text})
            # Only emit "thought" to the web UI if this is a web chat request.
            # Telegram calls are handled by process_and_respond which emits
            # "chat_from_telegram" — emitting "thought" here too causes duplicates.
            if not chat_id:
                await self.core.relay.emit(2, "thought", display_text)

            self.total_tokens_out += len(display_text) // 4

            # Persist to JSONL
            source = "telegram" if chat_id else "web"
            self._log_chat("assistant", display_text, source=source)

            return display_text

        # Hit max turns
        error_msg = (
            f"[ABORT] Hit maximum tool call limit ({max_turns} turns). "
            f"Used {turn_count} tool calls but couldn't form a final answer. "
            f"Try simplifying your query or asking for specific info."
        )
        self.total_tokens_out += len(error_msg) // 4
        self.history.append({"role": "assistant", "content": error_msg})
        self._log_chat("assistant", error_msg, source="telegram" if chat_id else "web")
        return error_msg

    async def _call_llm(self, messages):
        """
        Route to the appropriate provider using CURRENT self.llm settings.

        Key behaviour per provider:
          • google    → collapse to prompt+context string → Gemini REST API
          • anthropic → collapse to system+messages → Anthropic Messages API
          • ollama    → pass raw messages[] array directly (preserves conversation structure)
          • nvidia/xai→ collapse to prompt+context string → OpenAI-compat REST API
        """

        # ── Ollama: pre-flight health check ──────────────────────────
        if self.llm.provider == "ollama":
            ollama_mgr = getattr(self.core, 'ollama_manager', None)
            if ollama_mgr:
                healthy = await ollama_mgr.health_check()
                if not healthy:
                    model_mgr = getattr(self.core, 'model_manager', None)
                    if model_mgr:
                        await model_mgr.handle_api_error("Ollama unreachable")
                    return (
                        "[Galactic] ⚠️ Ollama is offline or unreachable at "
                        f"{ollama_mgr.base_url}. Switched to fallback model. "
                        "Run `ollama serve` and I'll reconnect automatically."
                    )

        # ── Context-window trimming ────────────────────────────────────
        # For Ollama: auto-detect from Ollama, but per-model override wins.
        # For other providers: only trim if per-model/global context_window is set.
        ctx_override = self._get_context_window_for_model()
        if self.llm.provider == "ollama":
            ollama_mgr = getattr(self.core, 'ollama_manager', None)
            if ollama_mgr and self.core.config.get('models', {}).get('context_window_trim', True):
                ctx_limit = ctx_override or ollama_mgr.get_context_window(self.llm.model, default=32768)
                # Rough heuristic: 1 token ≈ 4 chars; leave 20% headroom for the response
                char_limit = int(ctx_limit * 4 * 0.8)
                total_chars = sum(len(m.get('content', '')) for m in messages)
                while total_chars > char_limit and len(messages) > 2:
                    messages.pop(1)  # drop oldest non-system message
                    total_chars = sum(len(m.get('content', '')) for m in messages)

        # ── Route to provider ─────────────────────────────────────────
        if self.llm.provider == "google":
            # Gemini uses a single text blob (system context + user prompt)
            prompt = messages[-1]['content']
            context_str = "\n".join(
                [f"{m['role']}: {m['content']}" for m in messages[:-1]]
            )
            return await self._call_gemini(prompt, context_str)

        elif self.llm.provider == "anthropic":
            # Anthropic Messages API: separate system field + messages array
            # Pull system message from messages[0] if it exists
            system_msg = ""
            msg_list = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    msg_list.append(m)
            return await self._call_anthropic_messages(system_msg, msg_list)

        elif self.llm.provider == "ollama":
            # Ollama supports the full OpenAI /chat/completions messages array —
            # pass it directly so multi-turn tool-call context is preserved
            return await self._call_openai_compatible_messages(messages)

        elif self.llm.provider in ["nvidia", "xai"]:
            # NVIDIA / xAI: collapse to prompt+context (these are stateless one-shot)
            prompt = messages[-1]['content']
            context_str = "\n".join(
                [f"{m['role']}: {m['content']}" for m in messages[:-1]]
            )
            return await self._call_openai_compatible(prompt, context_str)

        elif self.llm.provider in ["openai", "groq", "mistral", "cerebras",
                                    "openrouter", "huggingface", "kimi", "zai", "minimax"]:
            # OpenAI-compatible providers: pass full messages array for proper multi-turn context
            return await self._call_openai_compatible_messages(messages)

        else:
            return f"[ERROR] Unknown provider: {self.llm.provider}"
    
    async def _call_gemini(self, prompt, context):
        """Google Gemini API call."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.llm.model}:generateContent?key={self.llm.api_key}"
        payload = {"contents": [{"parts": [{"text": f"SYSTEM CONTEXT: {context}\n\nUser: {prompt}"}]}]}
        try:
            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                response = await client.post(url, json=payload)
                data = response.json()
                if 'candidates' not in data or not data['candidates']:
                    return f"[ERROR] Google API: {json.dumps(data)}"
                candidate = data['candidates'][0]
                # Gemini sometimes returns a candidate with finishReason but no content
                # (e.g. safety filter, recitation, or empty response)
                if 'content' not in candidate:
                    reason = candidate.get('finishReason', 'UNKNOWN')
                    return f"[ERROR] Google returned no content (finishReason: {reason}). Try rephrasing."
                return candidate['content']['parts'][0]['text']
        except Exception as e:
            return f"[ERROR] Google: {str(e)}"
    
    async def _call_anthropic(self, prompt, context):
        """
        Anthropic Claude API call using the NATIVE Anthropic Messages API.
        This is NOT OpenAI-compatible — it requires x-api-key + anthropic-version headers
        and uses the /v1/messages endpoint with its own response schema.
        """
        api_key = self.llm.api_key
        if not api_key or api_key == "NONE":
            api_key = self.core.config.get('providers', {}).get('anthropic', {}).get('apiKey', '')
        if not api_key:
            return "[ERROR] Anthropic API key not configured. Set providers.anthropic.apiKey in config.yaml"

        url = "https://api.anthropic.com/v1/messages"
        # OAuth tokens (Claude Pro / Claude Code) require Bearer auth + special beta headers
        if api_key.startswith("sk-ant-oat"):
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14",
                "x-app": "cli",
                "user-agent": "claude-cli/2.1.2 (external, cli)",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }

        # Anthropic separates system prompt from messages
        payload = {
            "model": self.llm.model,
            "max_tokens": 8096,
            "system": context if context else "You are a helpful AI assistant.",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()

                # Anthropic response: {"content": [{"type": "text", "text": "..."}], ...}
                if "content" in data and data["content"]:
                    text_blocks = [b["text"] for b in data["content"] if b.get("type") == "text"]
                    return "\n".join(text_blocks) if text_blocks else "[ERROR] Anthropic: Empty response"
                elif "error" in data:
                    err = data["error"]
                    return f"[ERROR] Anthropic ({err.get('type','unknown')}): {err.get('message','Unknown error')}"
                else:
                    return f"[ERROR] Anthropic: Unexpected response: {json.dumps(data)}"
        except Exception as e:
            return f"[ERROR] Anthropic: {str(e)}"

    async def _call_anthropic_messages(self, system_prompt, messages):
        """
        Anthropic Messages API with full conversation history.
        Used by _call_llm() for multi-turn Anthropic conversations (preserves tool-call context).
        """
        api_key = self.llm.api_key
        if not api_key or api_key == "NONE":
            api_key = self.core.config.get('providers', {}).get('anthropic', {}).get('apiKey', '')
        if not api_key:
            return "[ERROR] Anthropic API key not configured. Set providers.anthropic.apiKey in config.yaml"

        url = "https://api.anthropic.com/v1/messages"
        # OAuth tokens (Claude Pro / Claude Code) require Bearer auth + special beta headers
        if api_key.startswith("sk-ant-oat"):
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14",
                "x-app": "cli",
                "user-agent": "claude-cli/2.1.2 (external, cli)",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }

        # Ensure messages alternate user/assistant (Anthropic requirement)
        # Merge consecutive same-role messages
        merged = []
        for m in messages:
            if m.get("role") not in ("user", "assistant"):
                continue
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n" + m["content"]
            else:
                merged.append({"role": m["role"], "content": m["content"]})

        # Must start with user
        if not merged or merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "(conversation start)"})

        payload = {
            "model": self.llm.model,
            "max_tokens": self._get_max_tokens(default=8192),
            "system": system_prompt if system_prompt else "You are a helpful AI assistant.",
            "messages": merged,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if "content" in data and data["content"]:
                    text_blocks = [b["text"] for b in data["content"] if b.get("type") == "text"]
                    return "\n".join(text_blocks) if text_blocks else "[ERROR] Anthropic: Empty response"
                elif "error" in data:
                    err = data["error"]
                    return f"[ERROR] Anthropic ({err.get('type','unknown')}): {err.get('message','Unknown error')}"
                else:
                    return f"[ERROR] Anthropic: Unexpected response: {json.dumps(data)}"
        except Exception as e:
            return f"[ERROR] Anthropic: {str(e)}"

    def _get_provider_base_url(self, provider):
        """Return the base URL for an OpenAI-compatible provider from config."""
        providers_cfg = self.core.config.get('providers', {})
        default_urls = {
            "openai":       "https://api.openai.com/v1",
            "groq":         "https://api.groq.com/openai/v1",
            "mistral":      "https://api.mistral.ai/v1",
            "cerebras":     "https://api.cerebras.ai/v1",
            "openrouter":   "https://openrouter.ai/api/v1",
            "huggingface":  "https://api-inference.huggingface.co/v1",
            "kimi":         "https://api.kimi.com/v1",
            "zai":          "https://api.z.ai/api/paas/v4",
            "minimax":      "https://api.minimax.io/v1",
            "nvidia":       "https://integrate.api.nvidia.com/v1",
            "xai":          "https://api.x.ai/v1",
            "ollama":       "http://127.0.0.1:11434/v1",
        }
        configured = providers_cfg.get(provider, {}).get('baseUrl', '')
        base = configured or default_urls.get(provider, '')
        # Normalize Ollama URL — ensure it ends with /v1
        if provider == "ollama" and not base.rstrip('/').endswith('/v1'):
            base = base.rstrip('/') + '/v1'
        return base.rstrip('/')

    def _get_provider_api_key(self, provider):
        """Return the API key for a provider, falling back to config providers section."""
        # Use the live llm.api_key if it's set and not placeholder
        key = self.llm.api_key
        if key and key not in ("NONE", ""):
            return key
        providers_cfg = self.core.config.get('providers', {})
        provider_cfg = providers_cfg.get(provider, {})

        # NVIDIA uses a per-model keys: sub-dict (one nvapi key per model type).
        # Match the active model name against each nickname in keys: and return the
        # first one whose nickname appears anywhere in the model string.
        # e.g. model "moonshot-ai/kimi-k2-instruct" → matches nickname "kimi"
        if provider == 'nvidia':
            model_str = (getattr(self.llm, 'model', '') or '').lower()
            nvidia_keys = provider_cfg.get('keys', {}) or {}
            for nickname, nvapi_key in nvidia_keys.items():
                if nvapi_key and nickname.lower() in model_str:
                    return nvapi_key
            # Fall back to first non-empty key if no nickname matched
            for nvapi_key in nvidia_keys.values():
                if nvapi_key:
                    return nvapi_key

        return provider_cfg.get('apiKey', '') or provider_cfg.get('api_key', '')

    def _get_model_override(self, key, default=None):
        """Return a per-model override value for the active model, falling back to global config."""
        model_id = getattr(self.llm, 'model', '') or ''
        overrides = self.core.config.get('model_overrides', {}) or {}
        # Check exact model match first
        if model_id in overrides and key in (overrides[model_id] or {}):
            try:
                val = int(overrides[model_id][key])
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        # Check aliases — if model_id matches an alias value, also check by alias name
        aliases = self.core.config.get('aliases', {}) or {}
        for alias, aliased_model in aliases.items():
            # aliased_model might be "provider/model" form; strip provider prefix
            stripped = aliased_model.split('/', 1)[-1] if '/' in aliased_model else aliased_model
            if (aliased_model == model_id or stripped == model_id) and alias in overrides:
                try:
                    val = int((overrides[alias] or {}).get(key, 0))
                    if val > 0:
                        return val
                except (TypeError, ValueError):
                    pass
        return default

    def _get_max_tokens(self, default=None):
        """Return max_tokens: per-model override first, then global config, then default."""
        # Per-model override
        per_model = self._get_model_override('max_tokens')
        if per_model:
            return per_model
        # Global config
        val = self.core.config.get('models', {}).get('max_tokens', 0)
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = 0
        return val if val > 0 else default

    def _get_context_window_for_model(self, default=None):
        """Return context_window: per-model override first, then global config, then default."""
        per_model = self._get_model_override('context_window')
        if per_model:
            return per_model
        val = self.core.config.get('models', {}).get('context_window', 0)
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = 0
        return val if val > 0 else default

    async def _call_openai_compatible(self, prompt, context):
        """OpenAI-compatible API call (NVIDIA, XAI, Ollama). All URLs are config-driven."""
        url = f"{self._get_provider_base_url(self.llm.provider)}/chat/completions"

        # Ollama doesn't need auth header
        headers = {"Content-Type": "application/json"}
        if self.llm.provider not in ("ollama",):
            headers["Authorization"] = f"Bearer {self._get_provider_api_key(self.llm.provider)}"

        # Use streaming for Ollama when configured (faster feel on local hardware)
        use_streaming = (
            self.llm.provider == "ollama"
            and self.core.config.get('models', {}).get('streaming', True)
        )
        if use_streaming:
            return await self._call_openai_compatible_streaming(prompt, context, url, headers)

        payload = {
            "model": self.llm.model,
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ]
        }
        max_tokens = self._get_max_tokens()
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if 'choices' not in data:
                    return f"[ERROR] {self.llm.provider}: {json.dumps(data)}"
                return data['choices'][0]['message']['content']
        except Exception as e:
            return f"[ERROR] {self.llm.provider}: {str(e)}"

    async def _call_openai_compatible_streaming(self, prompt, context, url, headers):
        """Streaming variant – returns full text but streams internally for real-time web UI updates."""
        payload = {
            "model": self.llm.model,
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ],
            "stream": True
        }
        full_response = []
        try:
            async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    token_buf = []
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                full_response.append(delta)
                                token_buf.append(delta)
                                if len(token_buf) >= 8:
                                    await self.core.relay.emit(3, "stream_chunk", "".join(token_buf))
                                    token_buf = []
                                    await asyncio.sleep(0)
                        except json.JSONDecodeError:
                            continue
                    if token_buf:
                        await self.core.relay.emit(3, "stream_chunk", "".join(token_buf))
            return "".join(full_response)
        except Exception as e:
            return f"[ERROR] {self.llm.provider} (streaming): {str(e)}"

    async def _call_openai_compatible_messages(self, messages):
        """
        OpenAI-compatible call that passes the FULL messages array.

        Used for: Ollama (local), OpenAI, Groq, Mistral, Cerebras, OpenRouter,
                  HuggingFace, Kimi, ZAI/GLM, MiniMax — any provider using
                  the standard /chat/completions messages array format.

        Key features:
          • Passes messages[] directly (preserves multi-turn conversation context)
          • Supports streaming for Ollama and OpenAI-compatible providers
          • Reads base URL and API key from config for all providers
          • Injects max_tokens if configured
        """
        provider = self.llm.provider
        url = f"{self._get_provider_base_url(provider)}/chat/completions"

        headers = {"Content-Type": "application/json"}
        # Ollama doesn't use auth; all other providers use Bearer token
        if provider != "ollama":
            api_key = self._get_provider_api_key(provider)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            # OpenRouter requires an extra header
            if provider == "openrouter":
                headers["HTTP-Referer"] = "https://galactic-ai.local"
                headers["X-Title"] = "Galactic AI"

        use_streaming = (
            provider in ("ollama", "openai", "groq", "mistral", "cerebras", "openrouter")
            and self.core.config.get('models', {}).get('streaming', True)
        )

        max_tokens = self._get_max_tokens()

        if use_streaming:
            payload = {
                "model": self.llm.model,
                "messages": messages,
                "stream": True,
            }
            # Ollama benefits from explicit temperature in options
            if provider == "ollama":
                payload["options"] = {"temperature": 0.3}
            if max_tokens:
                payload["max_tokens"] = max_tokens
            full_response = []
            try:
                async with httpx.AsyncClient(timeout=180.0, verify=False) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        token_buf = []
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                if delta:
                                    full_response.append(delta)
                                    token_buf.append(delta)
                                    # Batch emit every 8 tokens to reduce event loop pressure
                                    if len(token_buf) >= 8:
                                        await self.core.relay.emit(3, "stream_chunk", "".join(token_buf))
                                        token_buf = []
                                        await asyncio.sleep(0)  # yield to other tasks (typing, etc.)
                            except json.JSONDecodeError:
                                continue
                        # Flush remaining buffer
                        if token_buf:
                            await self.core.relay.emit(3, "stream_chunk", "".join(token_buf))
                return "".join(full_response)
            except Exception as e:
                return f"[ERROR] {provider} (streaming): {str(e)}"
        else:
            payload = {
                "model": self.llm.model,
                "messages": messages,
                "stream": False,
            }
            if provider == "ollama":
                payload["options"] = {"temperature": 0.3}
            if max_tokens:
                payload["max_tokens"] = max_tokens
            try:
                async with httpx.AsyncClient(timeout=180.0, verify=False) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    data = response.json()
                    if 'choices' not in data:
                        return f"[ERROR] {provider}: {json.dumps(data)}"
                    return data['choices'][0]['message']['content']
            except Exception as e:
                return f"[ERROR] {provider}: {str(e)}"


