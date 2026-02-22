import asyncio
import json
import logging
import os
import re
import time
import traceback
import uuid
import httpx
from datetime import datetime
from personality import GalacticPersonality
from model_manager import (TRANSIENT_ERRORS, PERMANENT_ERRORS,
                           ERROR_RATE_LIMIT, ERROR_TIMEOUT, ERROR_AUTH)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GalacticGateway")

# Silence noisy HTTP libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# NVIDIA models that require extra body params for thinking/reasoning.
# These are injected into the payload when the active model is on this list.
_NVIDIA_THINKING_MODELS = {
    "z-ai/glm5":              {"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}},
    "moonshotai/kimi-k2.5":   {"chat_template_kwargs": {"thinking": True}},
    "qwen/qwen3.5-397b-a17b": {"chat_template_kwargs": {"enable_thinking": True}},
    "nvidia/nemotron-3-nano-30b-a3b": {
        "reasoning_budget": 16384,
        "chat_template_kwargs": {"enable_thinking": True},
    },
}

class GalacticGateway:
    def __init__(self, core):
        self.core = core
        self.config = core.config.get('gateway', {})
        # Prefer models.primary_provider/model (canonical source of truth written by
        # ModelManager._save_config), fall back to legacy gateway.* fields, and only
        # use hardcoded defaults when the config has never been written at all.
        models_cfg = core.config.get('models', {})
        self.provider = (
            models_cfg.get('primary_provider')
            or self.config.get('provider')
            or 'google'
        )
        self.model = (
            models_cfg.get('primary_model')
            or self.config.get('model')
            or 'gemini-2.5-flash'
        )
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

        # Anti-spin: flag indicating an active speak() call is in progress
        self._speaking = False
        # Queued model switch: if user switches model during active speak(), apply after
        self._queued_switch = None
        # Lock to serialize sub-agent speak_isolated() calls (prevents concurrent state corruption)
        self._speak_lock = asyncio.Lock()
        
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

            # ── Desktop automation (OS-level via pyautogui) ──────────────
            "desktop_screenshot": {
                "description": "Capture the entire desktop screen (not just browser). Automatically analyzes the screenshot with vision so you can 'see' and describe what is on screen. Use this to observe the desktop before clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "Optional region as 'x,y,width,height' (e.g. '0,0,1920,1080'). Omit for full screen."},
                        "save_path": {"type": "string", "description": "Optional file path to save PNG."}
                    }
                },
                "fn": self.tool_desktop_screenshot
            },
            "desktop_click": {
                "description": "Click the mouse at desktop pixel coordinates (x, y). Use after desktop_screenshot to interact with any UI element on screen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X pixel coordinate from left edge"},
                        "y": {"type": "number", "description": "Y pixel coordinate from top edge"},
                        "button": {"type": "string", "description": "Mouse button: left, right, or middle (default: left)"},
                        "clicks": {"type": "integer", "description": "Number of clicks — 1=single, 2=double (default: 1)"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self.tool_desktop_click
            },
            "desktop_type": {
                "description": "Type text at the current cursor/focus position on the desktop. Click a text field first with desktop_click.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type"},
                        "interval": {"type": "number", "description": "Seconds between keystrokes (default: 0.05)"}
                    },
                    "required": ["text"]
                },
                "fn": self.tool_desktop_type
            },
            "desktop_move": {
                "description": "Move the mouse cursor to desktop coordinates without clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "duration": {"type": "number", "description": "Move duration in seconds (default: 0.2)"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self.tool_desktop_move
            },
            "desktop_scroll": {
                "description": "Scroll the mouse wheel. Positive = up, negative = down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "clicks": {"type": "integer", "description": "Scroll amount (positive=up, negative=down)"},
                        "x": {"type": "number", "description": "Optional X to scroll at"},
                        "y": {"type": "number", "description": "Optional Y to scroll at"}
                    },
                    "required": ["clicks"]
                },
                "fn": self.tool_desktop_scroll
            },
            "desktop_hotkey": {
                "description": "Press a keyboard shortcut (e.g. 'ctrl,c' for Ctrl+C, 'alt,tab' for Alt+Tab, 'win,r' for Run dialog).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {"type": "string", "description": "Comma-separated keys, e.g. 'ctrl,c' or 'alt,tab' or 'win,d'"}
                    },
                    "required": ["keys"]
                },
                "fn": self.tool_desktop_hotkey
            },
            "desktop_drag": {
                "description": "Click and drag from one desktop coordinate to another.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_x": {"type": "number", "description": "Start X"},
                        "from_y": {"type": "number", "description": "Start Y"},
                        "to_x": {"type": "number", "description": "End X"},
                        "to_y": {"type": "number", "description": "End Y"},
                        "duration": {"type": "number", "description": "Drag duration in seconds (default: 0.5)"}
                    },
                    "required": ["from_x", "from_y", "to_x", "to_y"]
                },
                "fn": self.tool_desktop_drag
            },
            "desktop_locate": {
                "description": "Find an image template on the desktop screen (template matching). Returns the coordinates where found.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_path": {"type": "string", "description": "Path to PNG image to search for on screen"},
                        "confidence": {"type": "number", "description": "Match confidence 0.0-1.0 (default: 0.8)"}
                    },
                    "required": ["image_path"]
                },
                "fn": self.tool_desktop_locate
            },

            # ── NVIDIA FLUX image generation ──────────────────────────────
            "generate_image": {
                "description": "Generate an image using FLUX AI via NVIDIA. Returns the path to the saved PNG file. Models: 'black-forest-labs/flux.1-schnell' (fast, 4 steps) or 'black-forest-labs/flux.1-dev' (quality, 50 steps).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Image description / prompt"},
                        "model": {"type": "string", "description": "FLUX model ID (default: flux.1-schnell)"},
                        "width": {"type": "integer", "description": "Image width in pixels (default: 1024)"},
                        "height": {"type": "integer", "description": "Image height in pixels (default: 1024)"},
                        "steps": {"type": "integer", "description": "Diffusion steps — schnell default 4, dev default 50"}
                    },
                    "required": ["prompt"]
                },
                "fn": self.tool_generate_image
            },

            # ── Stable Diffusion 3.5 image generation ─────────────────────────
            "generate_image_sd35": {
                "description": "Generate an image using Stable Diffusion 3.5 Large via NVIDIA NIM. Higher quality, different style than FLUX. Returns path to saved image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt":          {"type": "string",  "description": "Image description / prompt"},
                        "negative_prompt": {"type": "string",  "description": "Things to avoid in the image (optional)"},
                        "width":           {"type": "integer", "description": "Image width in pixels (default: 1024, max: 1536)"},
                        "height":          {"type": "integer", "description": "Image height in pixels (default: 1024, max: 1536)"},
                        "steps":           {"type": "integer", "description": "Diffusion steps (default: 40, range: 10-100)"},
                        "cfg_scale":       {"type": "number",  "description": "Guidance scale (default: 5.0, range: 1-20)"},
                        "seed":            {"type": "integer", "description": "Random seed (0 = random)"},
                    },
                    "required": ["prompt"]
                },
                "fn": self.tool_generate_image_sd35
            },

            # ── Google Imagen image generation ────────────────────────────────
            "generate_image_imagen": {
                "description": "Generate an image using Google Imagen 4 via the Google Generative AI API. High-quality photorealistic images. Returns path to saved image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt":         {"type": "string",  "description": "Image description / prompt"},
                        "model":          {"type": "string",  "description": "Imagen model to use: imagen-4-ultra (best), imagen-4 (standard), imagen-4-fast (quick). Default: imagen-4"},
                        "aspect_ratio":   {"type": "string",  "description": "Aspect ratio: 1:1, 16:9, 9:16, 4:3, 3:4. Default: 1:1"},
                        "number_of_images": {"type": "integer", "description": "Number of images to generate (1-4, default: 1)"},
                    },
                    "required": ["prompt"]
                },
                "fn": self.tool_generate_image_imagen
            },

            # ── File & system utilities ────────────────────────────────────────
            "list_dir": {
                "description": "List files and directories at a path with sizes, dates, and types. Better than exec_shell for directory listings.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string",  "description": "Directory path to list (default: current working directory)"},
                        "pattern": {"type": "string",  "description": "Optional glob pattern to filter, e.g. '*.py' or '*.txt'"},
                        "recurse": {"type": "boolean", "description": "Recurse into subdirectories (default: false)"},
                    },
                    "required": []
                },
                "fn": self.tool_list_dir
            },
            "find_files": {
                "description": "Find files matching a name pattern recursively under a directory. Faster and safer than exec_shell find/dir.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string", "description": "Root directory to search from (default: current working directory)"},
                        "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.log', '**/*.py', 'config.*'"},
                        "limit":   {"type": "integer", "description": "Maximum results to return (default: 100)"},
                    },
                    "required": ["pattern"]
                },
                "fn": self.tool_find_files
            },
            "hash_file": {
                "description": "Compute SHA256 (default), MD5, or SHA1 checksum of a file. Useful for verifying downloads or detecting changes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "Path to the file"},
                        "algorithm": {"type": "string", "description": "Hash algorithm: sha256 (default), md5, sha1"},
                    },
                    "required": ["path"]
                },
                "fn": self.tool_hash_file
            },
            "diff_files": {
                "description": "Show a unified diff between two text files, or between a file and a string. Great for reviewing changes before overwriting.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path_a":  {"type": "string", "description": "Path to first file"},
                        "path_b":  {"type": "string", "description": "Path to second file (if comparing two files)"},
                        "text_b":  {"type": "string", "description": "String content to compare against path_a (if not comparing two files)"},
                        "context": {"type": "integer", "description": "Lines of context around changes (default: 3)"},
                    },
                    "required": ["path_a"]
                },
                "fn": self.tool_diff_files
            },
            "zip_create": {
                "description": "Create a ZIP archive from a file or directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source":      {"type": "string", "description": "File or directory path to archive"},
                        "destination": {"type": "string", "description": "Output .zip file path (default: source + '.zip')"},
                    },
                    "required": ["source"]
                },
                "fn": self.tool_zip_create
            },
            "zip_extract": {
                "description": "Extract a ZIP archive to a directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source":      {"type": "string", "description": "Path to the .zip file"},
                        "destination": {"type": "string", "description": "Directory to extract into (default: same directory as zip)"},
                    },
                    "required": ["source"]
                },
                "fn": self.tool_zip_extract
            },
            "image_info": {
                "description": "Get metadata about an image file: dimensions, format, file size, color mode. Does NOT send the image to any AI — pure local metadata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to image file"},
                    },
                    "required": ["path"]
                },
                "fn": self.tool_image_info
            },

            # ── Clipboard ─────────────────────────────────────────────────────
            "clipboard_get": {
                "description": "Read the current text content of the OS clipboard.",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "fn": self.tool_clipboard_get
            },
            "clipboard_set": {
                "description": "Write text to the OS clipboard so the user can paste it anywhere.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to put on the clipboard"},
                    },
                    "required": ["text"]
                },
                "fn": self.tool_clipboard_set
            },

            # ── Desktop notifications ─────────────────────────────────────────
            "notify": {
                "description": "Send a desktop notification (toast/balloon) to the user's screen. Works on Windows, macOS, and Linux.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title":   {"type": "string", "description": "Notification title"},
                        "message": {"type": "string", "description": "Notification body text"},
                        "sound":   {"type": "boolean", "description": "Play a sound (default: false)"},
                    },
                    "required": ["title", "message"]
                },
                "fn": self.tool_notify
            },

            # ── Window management ─────────────────────────────────────────────
            "window_list": {
                "description": "List all currently open application windows with their titles, process names, and window IDs.",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "fn": self.tool_window_list
            },
            "window_focus": {
                "description": "Bring a window to the foreground and focus it by title substring or window ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Partial window title to match (case-insensitive)"},
                        "hwnd":  {"type": "integer", "description": "Exact window handle/ID from window_list"},
                    },
                    "required": []
                },
                "fn": self.tool_window_focus
            },
            "window_resize": {
                "description": "Resize and/or move an application window by title or window ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title":  {"type": "string",  "description": "Partial window title to match"},
                        "hwnd":   {"type": "integer", "description": "Window handle from window_list"},
                        "x":      {"type": "integer", "description": "Left position (pixels from screen left)"},
                        "y":      {"type": "integer", "description": "Top position (pixels from screen top)"},
                        "width":  {"type": "integer", "description": "Window width in pixels"},
                        "height": {"type": "integer", "description": "Window height in pixels"},
                    },
                    "required": []
                },
                "fn": self.tool_window_resize
            },

            # ── HTTP / API ────────────────────────────────────────────────────
            "http_request": {
                "description": "Make a raw HTTP request (GET, POST, PUT, DELETE, PATCH) to any URL. Supports custom headers, JSON body, and form data. Great for calling REST APIs directly.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method":  {"type": "string", "description": "HTTP method: GET, POST, PUT, DELETE, PATCH (default: GET)"},
                        "url":     {"type": "string", "description": "Full URL including protocol"},
                        "headers": {"type": "object", "description": "Request headers as key-value pairs"},
                        "json":    {"type": "object", "description": "JSON body (sets Content-Type: application/json automatically)"},
                        "data":    {"type": "string", "description": "Raw string body"},
                        "params":  {"type": "object", "description": "URL query parameters as key-value pairs"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
                    },
                    "required": ["url"]
                },
                "fn": self.tool_http_request
            },

            # ── QR code ───────────────────────────────────────────────────────
            "qr_generate": {
                "description": "Generate a QR code image from any text or URL. Saves to logs/ and returns the file path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text":       {"type": "string",  "description": "Text or URL to encode in the QR code"},
                        "size":       {"type": "integer", "description": "Box size in pixels (default: 10)"},
                        "border":     {"type": "integer", "description": "Border width in boxes (default: 4)"},
                        "error_correction": {"type": "string", "description": "Error correction level: L, M, Q, H (default: M)"},
                    },
                    "required": ["text"]
                },
                "fn": self.tool_qr_generate
            },

            # ── Environment variables ─────────────────────────────────────────
            "env_get": {
                "description": "Read an environment variable value. Returns all env vars if no name specified (filtered list, excludes secrets).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Environment variable name (e.g. PATH, HOME). Omit to list all."},
                    },
                    "required": []
                },
                "fn": self.tool_env_get
            },
            "env_set": {
                "description": "Set an environment variable for the current process (affects subprocesses spawned from this session).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":  {"type": "string", "description": "Environment variable name"},
                        "value": {"type": "string", "description": "Value to set"},
                    },
                    "required": ["name", "value"]
                },
                "fn": self.tool_env_set
            },

            # ── System info ────────────────────────────────────────────────────
            "system_info": {
                "description": "Get detailed system information: CPU, RAM, disk usage, OS version, uptime, Python version, and running process count.",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "fn": self.tool_system_info
            },
            "kill_process_by_name": {
                "description": "Kill all running processes matching a name or partial name (e.g. 'chrome', 'notepad'). More convenient than process_kill which needs an ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":  {"type": "string",  "description": "Process name or partial name to match (case-insensitive)"},
                        "force": {"type": "boolean", "description": "Force kill (SIGKILL/taskkill /F). Default: false (graceful SIGTERM)"},
                    },
                    "required": ["name"]
                },
                "fn": self.tool_kill_process_by_name
            },

            # ── Color picker ───────────────────────────────────────────────────
            "color_pick": {
                "description": "Sample the pixel color at exact desktop screen coordinates. Returns hex, RGB, and HSL values. Useful for UI automation color verification.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate (pixels from left edge of screen)"},
                        "y": {"type": "integer", "description": "Y coordinate (pixels from top edge of screen)"},
                    },
                    "required": ["x", "y"]
                },
                "fn": self.tool_color_pick
            },

            # ── Text / data utilities ──────────────────────────────────────────
            "text_transform": {
                "description": "Transform text: convert case, encode/decode base64, URL-encode/decode, count words/lines/chars, reverse, strip, wrap, or extract regex matches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text":      {"type": "string", "description": "Input text to transform"},
                        "operation": {"type": "string", "description": "Operation: upper, lower, title, snake_case, camel_case, base64_encode, base64_decode, url_encode, url_decode, reverse, count, strip, regex_extract, json_format, csv_to_json"},
                        "pattern":   {"type": "string", "description": "Regex pattern (for regex_extract operation)"},
                    },
                    "required": ["text", "operation"]
                },
                "fn": self.tool_text_transform
            },

            # ── New v0.9.2 tools ─────────────────────────────────────────
            "execute_python": {
                "description": "Execute Python code in a subprocess and return stdout/stderr. Use for data processing, calculations, CSV/JSON manipulation, or quick scripts. Timeout: 60s default.",
                "parameters": {"type": "object", "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default: 60, max: 300)"},
                }, "required": ["code"]},
                "fn": self.tool_execute_python
            },
            "wait": {
                "description": "Pause execution for a specified number of seconds. Use between actions that need settling time, or to wait before retrying something.",
                "parameters": {"type": "object", "properties": {
                    "seconds": {"type": "number", "description": "Seconds to wait (max: 300)"},
                }, "required": ["seconds"]},
                "fn": self.tool_wait
            },
            "send_telegram": {
                "description": "Send a proactive message to a Telegram chat (defaults to admin). Useful for alerts, task completion notifications, and automation reports.",
                "parameters": {"type": "object", "properties": {
                    "message": {"type": "string", "description": "Message text (Markdown supported)"},
                    "chat_id": {"type": "string", "description": "Chat ID (default: admin_chat_id from config)"},
                    "image_path": {"type": "string", "description": "Optional path to image to attach"},
                }, "required": ["message"]},
                "fn": self.tool_send_telegram
            },
            "read_pdf": {
                "description": "Extract text content from a PDF file. Returns plain text of all pages (or specific page range).",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path to PDF file"},
                    "pages": {"type": "string", "description": "Page range: '1-5', '3', 'all' (default: all)"},
                }, "required": ["path"]},
                "fn": self.tool_read_pdf
            },
            "read_csv": {
                "description": "Read CSV file and return contents as JSON rows with headers. Great for data analysis.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path to CSV file"},
                    "limit": {"type": "integer", "description": "Max rows to return (default: 200)"},
                    "delimiter": {"type": "string", "description": "Delimiter character (default: comma)"},
                }, "required": ["path"]},
                "fn": self.tool_read_csv
            },
            "write_csv": {
                "description": "Write JSON rows to a CSV file. Takes a list of dictionaries as rows.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Output CSV file path"},
                    "rows": {"type": "array", "description": "Array of {key: value} objects"},
                    "append": {"type": "boolean", "description": "Append to existing file (default: false)"},
                }, "required": ["path", "rows"]},
                "fn": self.tool_write_csv
            },
            "read_excel": {
                "description": "Read Excel file (.xlsx) and return contents as JSON rows. Requires openpyxl.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path to .xlsx file"},
                    "sheet": {"type": "string", "description": "Sheet name (default: first sheet)"},
                    "limit": {"type": "integer", "description": "Max rows to return (default: 100)"},
                }, "required": ["path"]},
                "fn": self.tool_read_excel
            },
            "regex_search": {
                "description": "Search file contents using regex. Returns matching lines with file paths and line numbers. Faster and safer than exec_shell grep.",
                "parameters": {"type": "object", "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "File or directory to search in"},
                    "file_pattern": {"type": "string", "description": "Glob to filter files, e.g. '*.py' (default: all)"},
                    "limit": {"type": "integer", "description": "Max results (default: 50)"},
                }, "required": ["pattern", "path"]},
                "fn": self.tool_regex_search
            },
            "image_resize": {
                "description": "Resize an image to specified dimensions. Supports PNG, JPEG, WebP, BMP.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path to source image"},
                    "width": {"type": "integer", "description": "Target width in pixels"},
                    "height": {"type": "integer", "description": "Target height in pixels"},
                    "output_path": {"type": "string", "description": "Output path (default: adds _resized suffix)"},
                }, "required": ["path"]},
                "fn": self.tool_image_resize
            },
            "image_convert": {
                "description": "Convert image between formats (PNG, JPEG, WebP, BMP, TIFF).",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path to source image"},
                    "format": {"type": "string", "description": "Target format: png, jpeg, webp, bmp"},
                    "output_path": {"type": "string", "description": "Output path (default: same name, new extension)"},
                    "quality": {"type": "integer", "description": "JPEG/WebP quality 1-100 (default: 85)"},
                }, "required": ["path", "format"]},
                "fn": self.tool_image_convert
            },
            "git_status": {
                "description": "Run 'git status' in a directory. Returns working tree status.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path (default: workspace)"},
                }, "required": []},
                "fn": self.tool_git_status
            },
            "git_diff": {
                "description": "Run 'git diff' to show changes. Returns unified diff output.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path (default: workspace)"},
                    "staged": {"type": "boolean", "description": "Show staged changes only (default: false)"},
                }, "required": []},
                "fn": self.tool_git_diff
            },
            "git_log": {
                "description": "Show recent git commit history.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path (default: workspace)"},
                    "count": {"type": "integer", "description": "Number of commits (default: 10)"},
                }, "required": []},
                "fn": self.tool_git_log
            },
            "git_commit": {
                "description": "Stage files and create a git commit.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path (default: workspace)"},
                    "message": {"type": "string", "description": "Commit message"},
                    "files": {"type": "array", "description": "Files to stage (default: all changed files)"},
                }, "required": ["message"]},
                "fn": self.tool_git_commit
            },
            "spawn_subagent": {
                "description": "Spawn an isolated sub-agent to handle a task in the background. Returns a session ID to check later.",
                "parameters": {"type": "object", "properties": {
                    "task": {"type": "string", "description": "Task description for the sub-agent"},
                    "agent_type": {"type": "string", "description": "Agent role: researcher, coder, analyst (default: researcher)"},
                }, "required": ["task"]},
                "fn": self.tool_spawn_subagent
            },
            "check_subagent": {
                "description": "Check the status and result of a previously spawned sub-agent.",
                "parameters": {"type": "object", "properties": {
                    "session_id": {"type": "string", "description": "Session ID from spawn_subagent"},
                }, "required": ["session_id"]},
                "fn": self.tool_check_subagent
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

    # Core files that should never be overwritten by the AI agent
    _PROTECTED_FILES = {
        'gateway_v2.py', 'galactic_core_v2.py', 'web_deck.py', 'model_manager.py',
        'remote_access.py', 'personality.py', 'memory_module_v2.py', 'scheduler.py',
        'nvidia_gateway.py', 'splash.py', 'telegram_bridge.py', 'discord_bridge.py',
        'whatsapp_bridge.py', 'gmail_bridge.py', 'imprint_engine.py', 'ollama_manager.py',
        'requirements.txt', 'config.yaml', 'personality.yaml',
        'install.ps1', 'install.sh', 'update.ps1', 'update.sh',
        'launch.ps1', 'launch.sh', '.gitignore', 'LICENSE',
    }

    async def tool_write_file(self, args):
        path = args.get('path')
        content = args.get('content')
        try:
            # Guard: prevent overwriting core system files
            filename = os.path.basename(path)
            if filename in self._PROTECTED_FILES:
                return (
                    f"[BLOCKED] Cannot overwrite protected core file '{filename}'. "
                    f"Create a new file with a different name instead."
                )
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

    # ── Desktop tool implementations ─────────────────────────────────────────

    def _get_desktop_plugin(self):
        """Helper to retrieve DesktopTool plugin."""
        return next((p for p in self.core.plugins if p.__class__.__name__ == "DesktopTool"), None)

    async def tool_desktop_screenshot(self, args):
        """Capture full desktop screen and analyze with vision."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded. Install pyautogui: pip install pyautogui"
        try:
            region_str = args.get('region')
            region = None
            if region_str:
                parts = [int(v.strip()) for v in region_str.split(',')]
                if len(parts) == 4:
                    region = tuple(parts)
            save_path = args.get('save_path')
            result = await desktop.screenshot(region=region, save_path=save_path)
            if result['status'] != 'success':
                return f"[ERROR] Desktop screenshot failed: {result.get('message')}"

            # Automatically analyze with vision so the LLM can "see" the screen
            try:
                vision_result = await self._analyze_image_b64(
                    result['b64'], 'image/png',
                    'Describe what is visible on this desktop screenshot in detail. '
                    'Identify all windows, applications, buttons, text, icons, taskbar items, '
                    'and any other UI elements. Note the approximate pixel coordinates of key '
                    'elements so they can be clicked with desktop_click.'
                )
            except Exception as ve:
                vision_result = f"[Vision analysis failed: {ve}] Screenshot saved at {result['path']} — use analyze_image tool with that path to retry."
            return (
                f"[DESKTOP] Screenshot: {result['path']} "
                f"(full {result['width']}x{result['height']} px, "
                f"vision at {result.get('vision_width', result['width'])}x{result.get('vision_height', result['height'])} px)\n\n"
                f"Vision Analysis:\n{vision_result}"
            )
        except Exception as e:
            return f"[ERROR] Desktop screenshot: {e}"

    async def tool_desktop_click(self, args):
        """Click at desktop coordinates."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        x = args.get('x')
        y = args.get('y')
        button = args.get('button', 'left')
        clicks = int(args.get('clicks', 1))
        result = await desktop.click(x, y, button=button, clicks=clicks)
        if result['status'] == 'success':
            return f"[DESKTOP] Clicked ({x}, {y}) with {button} button x{clicks}"
        return f"[ERROR] Desktop click: {result.get('message')}"

    async def tool_desktop_type(self, args):
        """Type text at current cursor position."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        text = args.get('text', '')
        interval = float(args.get('interval', 0.05))
        result = await desktop.type_text(text, interval=interval)
        if result['status'] == 'success':
            preview = text[:80] + ('...' if len(text) > 80 else '')
            return f"[DESKTOP] Typed: {preview}"
        return f"[ERROR] Desktop type: {result.get('message')}"

    async def tool_desktop_move(self, args):
        """Move mouse to coordinates."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        x = args.get('x')
        y = args.get('y')
        duration = float(args.get('duration', 0.2))
        result = await desktop.move(x, y, duration=duration)
        if result['status'] == 'success':
            return f"[DESKTOP] Moved mouse to ({x}, {y})"
        return f"[ERROR] Desktop move: {result.get('message')}"

    async def tool_desktop_scroll(self, args):
        """Scroll mouse wheel."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        clicks = int(args.get('clicks', 3))
        x = args.get('x')
        y = args.get('y')
        result = await desktop.scroll(clicks, x=x, y=y)
        if result['status'] == 'success':
            direction = "up" if clicks > 0 else "down"
            return f"[DESKTOP] Scrolled {direction} {abs(clicks)} clicks"
        return f"[ERROR] Desktop scroll: {result.get('message')}"

    async def tool_desktop_hotkey(self, args):
        """Press a keyboard shortcut."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        keys_str = args.get('keys', '')
        keys = [k.strip() for k in keys_str.split(',')]
        result = await desktop.hotkey(*keys)
        if result['status'] == 'success':
            return f"[DESKTOP] Pressed hotkey: {'+'.join(keys)}"
        return f"[ERROR] Desktop hotkey: {result.get('message')}"

    async def tool_desktop_drag(self, args):
        """Drag from one coordinate to another."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        from_x = args.get('from_x')
        from_y = args.get('from_y')
        to_x = args.get('to_x')
        to_y = args.get('to_y')
        duration = float(args.get('duration', 0.5))
        result = await desktop.drag(from_x, from_y, to_x, to_y, duration=duration)
        if result['status'] == 'success':
            return f"[DESKTOP] Dragged ({from_x},{from_y}) -> ({to_x},{to_y})"
        return f"[ERROR] Desktop drag: {result.get('message')}"

    async def tool_desktop_locate(self, args):
        """Find an image on screen via template matching."""
        desktop = self._get_desktop_plugin()
        if not desktop:
            return "[ERROR] DesktopTool plugin not loaded."
        # Accept both 'image_path' and 'template' (common alias LLMs use)
        image_path = args.get('image_path') or args.get('template', '')
        confidence = float(args.get('confidence', 0.8))
        result = await desktop.locate_on_screen(image_path, confidence=confidence)
        if result['status'] == 'success':
            return (
                f"[DESKTOP] Found at ({result['x']},{result['y']}) "
                f"size {result['width']}x{result['height']}. "
                f"Center: ({result['center_x']},{result['center_y']})"
            )
        elif result['status'] == 'not_found':
            return f"[DESKTOP] Image not found on screen: {image_path}"
        return f"[ERROR] Desktop locate: {result.get('message')}"

    async def tool_generate_image(self, args):
        """Generate an image using FLUX via NVIDIA's GenAI API."""
        import base64 as _b64, time as _time
        prompt = args.get('prompt', '')
        if not prompt:
            return "[ERROR] generate_image requires a 'prompt' argument."
        model = args.get('model', 'black-forest-labs/flux.1-schnell')
        # Strip nvidia/ prefix if user passed the alias path
        if model.startswith('nvidia/'):
            model = model[len('nvidia/'):]
        width = int(args.get('width', 1024))
        height = int(args.get('height', 1024))
        is_schnell = 'schnell' in model
        steps = int(args.get('steps', 4 if is_schnell else 50))

        # FLUX schnell and dev each have their own API key.
        # fluxDevApiKey → flux.1-dev, fluxApiKey → flux.1-schnell, apiKey → fallback.
        nvidia_cfg = self.core.config.get('providers', {}).get('nvidia', {})
        if not is_schnell:
            nvidia_key = (
                nvidia_cfg.get('fluxDevApiKey') or
                nvidia_cfg.get('fluxApiKey') or
                nvidia_cfg.get('apiKey') or ''
            )
        else:
            nvidia_key = (
                nvidia_cfg.get('fluxApiKey') or
                nvidia_cfg.get('apiKey') or ''
            )
        if not nvidia_key:
            return "[ERROR] NVIDIA FLUX key not found — add providers.nvidia.fluxApiKey (schnell) or fluxDevApiKey (dev) to config.yaml"

        url = f"https://ai.api.nvidia.com/v1/genai/{model}"
        headers = {
            "Authorization": f"Bearer {nvidia_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        # Build payload — schnell doesn't support cfg_scale or mode fields
        payload = {"prompt": prompt, "width": width, "height": height, "seed": 0, "steps": steps}
        if not is_schnell:
            payload["mode"] = "base"
            payload["cfg_scale"] = 5  # dev default per NVIDIA docs (1-9 range)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 401:
                    return f"[ERROR] NVIDIA GenAI 401 Unauthorized — key used: nvapi-...{nvidia_key[-8:]}. Check that your NVIDIA API key has access to the FLUX model at ai.api.nvidia.com."
                if r.status_code == 500:
                    return f"[ERROR] NVIDIA GenAI HTTP 500 — their inference server is down right now. Do NOT retry. Report this to the user and suggest trying again in a few minutes or switching to flux.1-schnell."
                if r.status_code != 200:
                    return f"[ERROR] NVIDIA GenAI HTTP {r.status_code}: {r.text[:500]}"
                data = r.json()

            artifact = data.get('artifacts', [{}])[0]
            finish = artifact.get('finishReason', '')
            if finish == 'CONTENT_FILTERED':
                return "⚠️ Image generation blocked by content filter. Try a different prompt."
            b64 = artifact.get('base64', '')
            if not b64:
                return f"[ERROR] Image generation failed: {json.dumps(data)}"

            # API returns JPEG data
            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = os.path.join(images_dir, 'flux')
            os.makedirs(img_subdir, exist_ok=True)
            fname = f"flux_{int(_time.time())}.jpg"
            path = os.path.join(img_subdir, fname)
            with open(path, 'wb') as f:
                f.write(_b64.b64decode(b64))
            # Signal Telegram bridge and web deck to deliver the image directly
            self.last_image_file = path
            return f"✅ Image generated and saved to: {path}\nModel: {model}\nPrompt: {prompt}"
        except Exception as e:
            return f"[ERROR] generate_image: {str(e)}"

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

        # Normalize alternative parameter formats LLMs sometimes use
        old_text = args.get('old_text')
        if old_text is None:
            old_text = args.get('old')
        new_text = args.get('new_text')
        if new_text is None:
            new_text = args.get('new')

        # Handle replacements array: {replacements: [{old/old_text, new/new_text}]}
        if old_text is None and 'replacements' in args:
            replacements = args['replacements']
            if isinstance(replacements, list) and len(replacements) > 0:
                first = replacements[0]
                old_text = first.get('old_text') or first.get('old')
                new_text = first.get('new_text') or first.get('new')

        if not path:
            return "Error: 'path' parameter is required."
        if old_text is None or new_text is None:
            return ("Error: 'old_text' and 'new_text' parameters are required. "
                    "Accepted formats: {old_text, new_text} or {old, new} or "
                    "{replacements: [{old, new}]}.")

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
        """Analyze an image — routes to the active provider's vision endpoint."""
        path = args.get('path')
        prompt = args.get('prompt', 'Describe this image in detail. Include any text you see.')

        import base64
        from pathlib import Path

        if not path or not Path(path).exists():
            return f"[ERR] Image not found: {path}"

        # Read file and detect MIME type (no hardcoded JPEG)
        with open(path, 'rb') as f:
            raw = f.read()
        image_b64 = base64.b64encode(raw).decode('utf-8')
        suffix = Path(path).suffix.lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                    '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
        mime_type = mime_map.get(suffix, 'image/jpeg')

        return await self._analyze_image_b64(image_b64, mime_type, prompt)

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

    # ── Vision routing (base64 pipeline) ─────────────────────────────────────
    # These methods accept pre-encoded base64 + MIME type, eliminating the
    # temp-file race condition from _handle_photo.

    async def _analyze_image_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Route image analysis to the best available provider (base64 input)."""
        provider = self.llm.provider
        if provider == "google":
            return await self._analyze_image_gemini_b64(image_b64, mime_type, prompt)
        elif provider == "anthropic":
            return await self._analyze_image_anthropic_b64(image_b64, mime_type, prompt)
        elif provider == "nvidia":
            return await self._analyze_image_nvidia_b64(image_b64, mime_type, prompt)
        elif provider == "ollama":
            return await self._analyze_image_ollama_b64(image_b64, mime_type, prompt)
        else:
            # xai, groq, openai, openrouter, etc. — try Google first, then OpenAI-compat
            google_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
            if google_key:
                return await self._analyze_image_gemini_b64(image_b64, mime_type, prompt)
            return await self._analyze_image_openai_b64(image_b64, mime_type, prompt)

    async def _analyze_image_gemini_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Analyze image using Google Gemini Vision (base64 input)."""
        try:
            api_key = self.config.get('api_key') or self.core.config.get('providers', {}).get('google', {}).get('apiKey')
            if not api_key:
                return "[ERR] Google API key not configured for image analysis."

            # Use active model if Google, else fall back to gemini-2.5-flash
            vision_model = self.llm.model if self.llm.provider == "google" else "gemini-2.5-flash"

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{vision_model}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": image_b64}}
            ]}]}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                data = response.json()
                if 'candidates' in data and data['candidates']:
                    result = data['candidates'][0]['content']['parts'][0]['text']
                    return f"[VISION/Gemini/{vision_model}]\n\n{result}"
                return f"[ERR] Gemini vision error: {data}"
        except Exception as e:
            return f"Error analyzing image (Gemini): {e}"

    async def _analyze_image_anthropic_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Analyze image using Anthropic Claude vision (native multimodal format)."""
        try:
            api_key = self._get_provider_api_key("anthropic")
            if not api_key:
                return "[ERR] Anthropic API key not configured."

            url = "https://api.anthropic.com/v1/messages"
            if api_key.startswith("sk-ant-oat"):
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
                }
            else:
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                }

            vision_model = self.llm.model if self.llm.provider == "anthropic" else "claude-sonnet-4-6"

            payload = {
                "model": vision_model,
                "max_tokens": 1024,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_b64,
                        }},
                        {"type": "text", "text": prompt}
                    ]
                }]
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if "content" in data and data["content"]:
                    text_blocks = [b["text"] for b in data["content"] if b.get("type") == "text"]
                    return f"[VISION/Anthropic/{vision_model}]\n\n" + "\n".join(text_blocks)
                return f"[ERR] Anthropic vision error: {data}"
        except Exception as e:
            return f"Error analyzing image (Anthropic): {e}"

    async def _analyze_image_nvidia_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Analyze image using NVIDIA vision endpoint (phi-3.5-vision-instruct)."""
        try:
            api_key = self._get_provider_api_key("nvidia")
            if not api_key:
                return "[ERR] NVIDIA API key not configured."

            vision_model = "microsoft/phi-3.5-vision-instruct"
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": vision_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                    ]
                }],
                "max_tokens": 1024,
                "temperature": 0.2,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if 'choices' in data and data['choices']:
                    result = data['choices'][0]['message']['content']
                    return f"[VISION/NVIDIA/{vision_model}]\n\n{result}"
                return f"[ERR] NVIDIA vision error: {data}"
        except Exception as e:
            return f"Error analyzing image (NVIDIA): {e}"

    async def _analyze_image_ollama_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Analyze image using Ollama vision model (correct MIME type)."""
        try:
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
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                    ]
                }]
            }

            async with httpx.AsyncClient(timeout=90.0, verify=False) as client:
                response = await client.post(url, json=payload)
                data = response.json()
                if 'choices' in data and data['choices']:
                    result = data['choices'][0]['message']['content']
                    return f"[VISION/Ollama]\n\n{result}"
                return f"[ERR] Ollama vision error: {data}\n(Ensure you're using a vision-capable model like llava or moondream)"
        except Exception as e:
            return f"Error analyzing image (Ollama): {e}"

    async def _analyze_image_openai_b64(self, image_b64: str, mime_type: str, prompt: str) -> str:
        """Analyze image via OpenAI-compatible multimodal format (xai, groq, openai, etc.)."""
        try:
            provider = self.llm.provider
            url = f"{self._get_provider_base_url(provider)}/chat/completions"
            api_key = self._get_provider_api_key(provider)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

            payload = {
                "model": self.llm.model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                    ]
                }],
                "max_tokens": 1024,
            }

            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if 'choices' in data and data['choices']:
                    result = data['choices'][0]['message']['content']
                    return f"[VISION/{provider.upper()}]\n\n{result}"
                return f"[ERR] {provider} vision error: {data}"
        except Exception as e:
            return f"Error analyzing image ({self.llm.provider}): {e}"

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
                "7. BEFORE writing scripts: read config.yaml for real credentials. NEVER use placeholder values.\n"
                "8. NEVER overwrite requirements.txt, config.yaml, or core .py files. Create NEW files with unique names.\n"
                "9. NEVER run scripts with while True loops or sleep() via exec_shell — they timeout. Tell the user how to launch them.\n"
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
                f"- For COMPLEX tasks (multi-step automation): plan your approach FIRST, then execute. Target under 15 tool calls\n"
                f"- NEVER verify what you just did — trust the tool output and respond to the user!\n"
                f"- If a tool fails or times out: do NOT retry the same approach. Explain the failure and try a different strategy\n"
                f"- If you write a file: deliver it to the user. Do NOT immediately run it to test — let the user verify\n"
                f"- NEVER launch long-running background processes via exec_shell — they timeout after 120s. Write the script and tell the user how to run it\n"
                f"- If stuck after 3+ failed attempts: STOP. Tell the user what you tried, what went wrong, and ask for guidance\n"
                f"\nCRITICAL RULES:\n"
                f"- BEFORE writing any script: read config.yaml to get real credentials (Telegram token, API keys, etc.). NEVER use placeholder values like 'YOUR_TOKEN_HERE'\n"
                f"- NEVER overwrite requirements.txt, config.yaml, or any core .py file unless explicitly asked. Create NEW files with unique names for scripts\n"
                f"- When asked to 'create a script': write ONE complete file with all logic, then STOP. Do not write multiple draft versions\n"
                f"- NEVER run a script that has a while True loop or sleep() via exec_shell — it WILL timeout. Tell the user how to launch it instead\n"
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

    async def _emit_trace(self, phase, turn, **kwargs):
        """Emit a structured agent_trace event to all connected WS clients."""
        payload = {"phase": phase, "turn": turn, "ts": time.time()}
        payload.update(kwargs)
        await self.core.relay.emit(3, "agent_trace", payload)

    async def speak(self, user_input, context="", chat_id=None, images=None):
        """
        Main entry point for user interaction.
        Implements a ReAct loop: Think -> Act -> Observe -> Answer.

        images: optional list of {name, mime, b64} dicts for vision-capable models.
          When provided, the user message is built as a multimodal content array
          (text + base64 image parts) compatible with OpenAI/Anthropic/Google vision APIs.

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

        # Build user message — multimodal content array if images are attached
        if images:
            content = []
            if user_input:
                content.append({"type": "text", "text": user_input})
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['mime']};base64,{img['b64']}"
                    }
                })
            self.history.append({"role": "user", "content": content})
        else:
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

        # 2. ReAct Loop (with wall-clock timeout)
        max_turns = int(self.config.get('models', {}).get('max_turns', 50))
        speak_timeout = float(self.core.config.get('models', {}).get('speak_timeout', 600))
        turn_count = 0
        last_tool_call = None  # Track last (tool_name, json_args_str) to prevent duplicate calls
        # Tools that are legitimately called repeatedly with same args (snapshots, reads, etc.)
        _DUPLICATE_EXEMPT = {'browser_snapshot', 'web_search', 'read_file', 'memory_search', 'generate_image'}

        # ── Anti-spin guardrails ──
        consecutive_failures = 0   # Consecutive tool errors/timeouts
        recent_tools = []          # Rolling window of last 6 tool names
        _nudge_half_sent = False   # Track whether 50% nudge was sent
        _nudge_80_sent = False     # Track whether 80% nudge was sent

        # Mark that the gateway is actively processing (prevents model switching mid-task)
        self._speaking = True

        # Unique session ID for tracing this speak() invocation
        trace_sid = str(uuid.uuid4())[:8]
        await self._emit_trace("session_start", 0, session_id=trace_sid,
                               query=user_input[:500])

        # ── Inner function: entire ReAct loop wrapped with wall-clock timeout ──
        async def _react_loop():
            nonlocal turn_count, last_tool_call, messages
            nonlocal consecutive_failures, recent_tools, _nudge_half_sent, _nudge_80_sent

            for _ in range(max_turns):
                turn_count += 1
                await self._emit_trace("turn_start", turn_count, session_id=trace_sid)

                # ── Progressive backpressure: nudge the AI to wrap up ──
                half_mark = max_turns // 2
                eighty_mark = int(max_turns * 0.8)
                if turn_count == half_mark and not _nudge_half_sent:
                    _nudge_half_sent = True
                    messages.append({
                        "role": "user",
                        "content": (
                            f"⚠️ You've used {turn_count} of {max_turns} tool turns. "
                            f"Start wrapping up — deliver what you have so far."
                        )
                    })
                    await self.core.log(
                        f"⚠️ Agent nudge: {turn_count}/{max_turns} turns used (50%)",
                        priority=2
                    )
                elif turn_count == eighty_mark and not _nudge_80_sent:
                    _nudge_80_sent = True
                    messages.append({
                        "role": "user",
                        "content": (
                            f"🛑 {turn_count}/{max_turns} turns used. "
                            f"Give your FINAL answer NOW. Summarize what you accomplished "
                            f"and what remains to be done."
                        )
                    })
                    await self.core.log(
                        f"🛑 Agent nudge: {turn_count}/{max_turns} turns used (80%)",
                        priority=1
                    )

                await self._send_telegram_typing_ping(chat_id)
                response_text = await self._call_llm_resilient(messages)

                # Capture think-tag content before stripping (for Thinking tab)
                think_match = re.search(r'<think>(.*?)</think>', response_text, re.DOTALL)
                if think_match:
                    await self._emit_trace("thinking", turn_count, session_id=trace_sid,
                                           content=think_match.group(1).strip()[:5000])

                # Emit raw LLM response
                await self._emit_trace("llm_response", turn_count, session_id=trace_sid,
                                       content=response_text[:3000])

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
                        await self._emit_trace("duplicate_blocked", turn_count, session_id=trace_sid,
                                               tool=tool_name)
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
                        # Emit tool_call trace before executing
                        await self._emit_trace("tool_call", turn_count, session_id=trace_sid,
                                               tool=tool_name,
                                               args=tool_args if isinstance(tool_args, dict) else str(tool_args)[:1000])
                        tool_timeout = self._get_tool_timeout(tool_name)
                        try:
                            result = await asyncio.wait_for(
                                self.tools[tool_name]["fn"](tool_args),
                                timeout=tool_timeout
                            )
                            await self._send_telegram_typing_ping(chat_id)
                            await self._emit_trace("tool_result", turn_count, session_id=trace_sid,
                                                   tool=tool_name, result=str(result)[:3000], success=True)
                        except asyncio.TimeoutError:
                            result = f"[Tool Timeout] {tool_name} exceeded {tool_timeout}s limit and was killed."
                            await self.core.log(f"⏱ Tool timeout: {tool_name} after {tool_timeout}s", priority=1)
                            await self._emit_trace("tool_result", turn_count, session_id=trace_sid,
                                                   tool=tool_name, result=result, success=False)
                        except Exception as e:
                            result = f"[Tool Error] {tool_name} raised: {type(e).__name__}: {e}"
                            await self._emit_trace("tool_result", turn_count, session_id=trace_sid,
                                                   tool=tool_name, result=str(result)[:3000], success=False)

                        # Track TTS output so callers (telegram_bridge) can send the audio file
                        if tool_name == "text_to_speech" and "[VOICE]" in str(result):
                            voice_match = re.search(r'Generated speech.*?:\s*(.+\.mp3)', str(result))
                            if voice_match:
                                self.last_voice_file = voice_match.group(1).strip()

                        # ── Anti-spin: track consecutive failures ──
                        result_str = str(result)
                        if result_str.startswith("[Tool Error]") or result_str.startswith("[Tool Timeout]"):
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0

                        # ── Anti-spin: track tool-type repetition ──
                        recent_tools.append(tool_name)
                        if len(recent_tools) > 6:
                            recent_tools.pop(0)

                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content": f"Tool Output: {result}"})

                        # ── Circuit breaker: 3+ consecutive failures ──
                        if consecutive_failures >= 3:
                            await self.core.log(
                                f"🔌 Circuit breaker: {consecutive_failures} consecutive tool failures",
                                priority=1
                            )
                            await self._emit_trace("circuit_breaker", turn_count, session_id=trace_sid,
                                                   failures=consecutive_failures)
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"⚠️ {consecutive_failures} consecutive tool failures. "
                                    f"STOP calling tools. Explain to the user what you were trying to do, "
                                    f"what went wrong, and suggest next steps or ask for guidance."
                                )
                            })
                            consecutive_failures = 0  # Reset after intervention

                        # ── Tool-type repetition guard ──
                        if len(recent_tools) >= 5:
                            from collections import Counter
                            tool_counts = Counter(recent_tools)
                            most_common_tool, most_common_count = tool_counts.most_common(1)[0]
                            if most_common_count >= 4 and most_common_tool not in _DUPLICATE_EXEMPT:
                                await self.core.log(
                                    f"🔄 Tool repetition guard: {most_common_tool} called "
                                    f"{most_common_count}x in last {len(recent_tools)} turns",
                                    priority=1
                                )
                                await self._emit_trace("repetition_guard", turn_count, session_id=trace_sid,
                                                       tool=most_common_tool, count=most_common_count)
                                messages.append({
                                    "role": "user",
                                    "content": (
                                        f"You've called {most_common_tool} {most_common_count} times in the "
                                        f"last {len(recent_tools)} turns without resolving the issue. "
                                        f"Try a completely different approach or explain the situation to the user."
                                    )
                                })
                                recent_tools.clear()  # Reset after intervention

                        continue  # Loop back to LLM with result
                    else:
                        await self._emit_trace("tool_not_found", turn_count, session_id=trace_sid,
                                               tool=tool_name)
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
                await self._emit_trace("final_answer", turn_count, session_id=trace_sid,
                                       content=display_text[:3000])
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
            await self._emit_trace("session_abort", turn_count, session_id=trace_sid,
                                   reason="max_turns_exceeded")
            error_msg = (
                f"[ABORT] Hit maximum tool call limit ({max_turns} turns). "
                f"Used {turn_count} tool calls but couldn't form a final answer. "
                f"Try simplifying your query or asking for specific info."
            )
            self.total_tokens_out += len(error_msg) // 4
            self.history.append({"role": "assistant", "content": error_msg})
            self._log_chat("assistant", error_msg, source="telegram" if chat_id else "web")
            return error_msg

        # ── Execute the ReAct loop with wall-clock timeout ──
        try:
            return await asyncio.wait_for(_react_loop(), timeout=speak_timeout)
        except asyncio.TimeoutError:
            await self._emit_trace("session_abort", turn_count, session_id=trace_sid,
                                   reason="speak_timeout")
            timeout_msg = (
                f"⏱ Task exceeded the maximum execution time ({int(speak_timeout)}s). "
                f"Completed {turn_count} turns before timeout. "
                f"Try breaking your request into smaller steps."
            )
            self.total_tokens_out += len(timeout_msg) // 4
            self.history.append({"role": "assistant", "content": timeout_msg})
            self._log_chat("assistant", timeout_msg, source="telegram" if chat_id else "web")
            return timeout_msg
        finally:
            # ── Always clear speaking flag and restore smart routing ──
            self._speaking = False

            # Restore model if smart routing switched it for this request
            if model_mgr and getattr(model_mgr, '_routed', False):
                pre = getattr(model_mgr, '_pre_route_state', None)
                if pre:
                    self.llm.provider = pre['provider']
                    self.llm.model = pre['model']
                    self.llm.api_key = pre['api_key']
                    await self.core.log(
                        f"🔄 Smart routing restored: {pre['provider']}/{pre['model']}",
                        priority=3
                    )
                model_mgr._routed = False

            # Apply any queued model switch that arrived while we were speaking
            queued = getattr(self, '_queued_switch', None)
            if queued:
                q_provider, q_model = queued
                self._queued_switch = None
                if model_mgr:
                    model_mgr.primary_provider = q_provider
                    model_mgr.primary_model = q_model
                    model_mgr.current_mode = 'primary'
                    self.llm.provider = q_provider
                    self.llm.model = q_model
                    model_mgr._set_api_key(q_provider)
                    await model_mgr._save_config()
                    await self.core.log(
                        f"🔄 Queued model switch applied: {q_provider}/{q_model}",
                        priority=2
                    )

    # ── Isolated speak for sub-agents ─────────────────────────────────

    async def speak_isolated(self, user_input, context="", chat_id=None, images=None):
        """
        Run speak() with isolated state for sub-agents.
        Saves and restores all mutable gateway state so concurrent calls
        don't corrupt the main agent's session.
        Serialized via _speak_lock to prevent sub-agents from interfering
        with each other.
        """
        async with self._speak_lock:
            # Snapshot current state
            saved_speaking = self._speaking
            saved_history = self.history
            saved_provider = self.llm.provider
            saved_model = self.llm.model
            saved_api_key = self.llm.api_key
            saved_queued = self._queued_switch

            # Snapshot model_manager routing state
            model_mgr = getattr(self.core, 'model_manager', None)
            saved_routed = getattr(model_mgr, '_routed', False) if model_mgr else False
            saved_pre_route = getattr(model_mgr, '_pre_route_state', None) if model_mgr else None

            try:
                # Use isolated history (sub-agent has no prior conversation)
                self.history = []
                self._speaking = False
                self._queued_switch = None
                if model_mgr:
                    model_mgr._routed = False
                    model_mgr._pre_route_state = None

                return await self.speak(user_input, context=context, chat_id=chat_id, images=images)
            finally:
                # Restore all state
                self._speaking = saved_speaking
                self.history = saved_history
                self.llm.provider = saved_provider
                self.llm.model = saved_model
                self.llm.api_key = saved_api_key
                self._queued_switch = saved_queued
                if model_mgr:
                    model_mgr._routed = saved_routed
                    model_mgr._pre_route_state = saved_pre_route

    # ── Tool timeout defaults ────────────────────────────────────────
    _TOOL_TIMEOUTS = {
        'exec_shell': 120, 'execute_python': 60, 'open_browser': 60,
        'web_fetch': 30, 'web_search': 15, 'browser_click': 30,
        'browser_type': 15, 'browser_wait': 60, 'browser_extract': 30,
        'browser_snapshot': 30, 'browser_fill_form': 30,
        'browser_execute_js': 30, 'browser_pdf': 30,
        'desktop_screenshot': 15, 'desktop_click': 10, 'desktop_type': 15,
        'generate_image': 180, 'generate_image_sd35': 180,
        'generate_image_imagen': 180, 'analyze_image': 60,
        'text_to_speech': 30, 'spawn_subagent': 5, 'memory_search': 10,
        'memory_imprint': 10, 'wait': 310, 'read_file': 10, 'write_file': 10,
        'edit_file': 10, 'find_files': 30, 'list_dir': 10,
        'read_pdf': 30, 'read_csv': 15, 'read_excel': 15, 'write_csv': 15,
        'regex_search': 30, 'send_telegram': 15,
        'git_status': 15, 'git_diff': 15, 'git_commit': 30, 'git_log': 15,
        'image_resize': 15, 'image_convert': 15, 'http_request': 60,
    }

    def _get_tool_timeout(self, tool_name):
        """Per-tool timeout: config override > built-in default > 60s."""
        overrides = self.core.config.get('tool_timeouts', {})
        return overrides.get(tool_name, self._TOOL_TIMEOUTS.get(tool_name, 60))

    # ── Resilient LLM call with fallback chain ───────────────────────

    async def _call_llm_resilient(self, messages):
        """
        Wrapper around _call_llm that detects [ERROR] responses and
        transparently retries / walks the fallback chain.
        On the happy path (no error), this adds zero overhead.
        """
        result = await self._call_llm(messages)

        # Happy path — no error
        if not isinstance(result, str) or not result.startswith("[ERROR]"):
            return result

        # Error detected — check if fallback is enabled
        model_mgr = getattr(self.core, 'model_manager', None)
        if not model_mgr or not model_mgr.auto_fallback_enabled:
            return result  # Fallback disabled — return error as-is

        error_type = model_mgr.classify_error(result)
        await self.core.log(
            f"⚠️ LLM error ({error_type}): {self.llm.provider}/{self.llm.model} — {result[:150]}",
            priority=1
        )

        # For transient errors, retry the SAME model once with a short delay
        if error_type in TRANSIENT_ERRORS:
            delay = 2.0 if error_type == ERROR_RATE_LIMIT else 1.0
            await asyncio.sleep(delay)
            retry = await self._call_llm(messages)
            if not isinstance(retry, str) or not retry.startswith("[ERROR]"):
                await self.core.log(f"✅ Retry succeeded for {self.llm.provider}", priority=2)
                return retry

        # Record the failure on the current provider
        model_mgr._record_provider_failure(self.llm.provider, error_type)

        # Walk the fallback chain
        return await self._walk_fallback_chain(messages, error_type)

    async def _walk_fallback_chain(self, messages, original_error_type):
        """
        Try each model in the fallback chain until one succeeds.
        Provider/model is restored to the original state after every attempt.
        """
        model_mgr = self.core.model_manager

        # Save current (user-selected) state — ALWAYS restored at end
        orig_provider = self.llm.provider
        orig_model    = self.llm.model
        orig_key      = self.llm.api_key

        chain = model_mgr.fallback_chain
        last_error = None

        async with model_mgr._fallback_lock:
            # Check shortcut cache — if a fallback worked recently, try it first
            if model_mgr._last_successful_fallback:
                fb_p, fb_m, fb_ts = model_mgr._last_successful_fallback
                if (datetime.now() - fb_ts).total_seconds() < 60:
                    # Try the cached fallback first
                    self.llm.provider = fb_p
                    self.llm.model = fb_m
                    model_mgr._set_api_key(fb_p)
                    try:
                        result = await self._call_llm(messages)
                        if not isinstance(result, str) or not result.startswith("[ERROR]"):
                            model_mgr._record_provider_success(fb_p)
                            model_mgr._last_successful_fallback = (fb_p, fb_m, datetime.now())
                            await self.core.log(
                                f"⚡ Fallback cache hit: {fb_p}/{fb_m} (orig: {orig_provider}/{orig_model})",
                                priority=2
                            )
                            await self.core.relay.emit(2, "model_fallback", {
                                "original": f"{orig_provider}/{orig_model}",
                                "fallback": f"{fb_p}/{fb_m}",
                                "reason": original_error_type,
                            })
                            # Restore original state
                            self.llm.provider = orig_provider
                            self.llm.model = orig_model
                            self.llm.api_key = orig_key
                            return result
                    except Exception as e:
                        await self.core.log(
                            f"Fallback cache miss ({fb_p}/{fb_m}): {type(e).__name__}: {e}",
                            priority=3
                        )

            # Walk the full chain
            for entry in chain:
                provider = entry['provider']
                model    = entry['model']

                # Skip the provider that just failed
                if provider == orig_provider and model == orig_model:
                    continue

                # Skip providers in cooldown
                if not model_mgr._is_provider_available(provider):
                    continue

                # Skip Ollama if offline (avoid 180s timeout on dead server)
                if provider == 'ollama':
                    ollama_mgr = getattr(self.core, 'ollama_manager', None)
                    if ollama_mgr:
                        healthy = await ollama_mgr.health_check()
                        if not healthy:
                            continue

                # Swap to fallback
                self.llm.provider = provider
                self.llm.model = model
                model_mgr._set_api_key(provider)

                await self.core.log(f"🔄 Fallback → trying {provider}/{model}...", priority=2)

                try:
                    result = await self._call_llm(messages)

                    if not isinstance(result, str) or not result.startswith("[ERROR]"):
                        # Success!
                        model_mgr._record_provider_success(provider)
                        model_mgr._last_successful_fallback = (provider, model, datetime.now())
                        await self.core.log(
                            f"✅ Fallback SUCCESS: {provider}/{model} "
                            f"(original: {orig_provider}/{orig_model})",
                            priority=1
                        )
                        await self.core.relay.emit(2, "model_fallback", {
                            "original": f"{orig_provider}/{orig_model}",
                            "fallback": f"{provider}/{model}",
                            "reason": original_error_type,
                        })
                        # Restore original model for next call
                        self.llm.provider = orig_provider
                        self.llm.model = orig_model
                        self.llm.api_key = orig_key
                        return result
                    else:
                        # This fallback also failed
                        fb_error = model_mgr.classify_error(result)
                        model_mgr._record_provider_failure(provider, fb_error)
                        last_error = result

                except Exception as e:
                    last_error = f"[ERROR] Fallback {provider}: {e}"
                    model_mgr._record_provider_failure(provider, "UNKNOWN")

            # All exhausted — restore and return failure
            self.llm.provider = orig_provider
            self.llm.model = orig_model
            self.llm.api_key = orig_key

        total_tried = len(chain) + 1  # +1 for original
        return (
            f"[Galactic] All {total_tried} models in the fallback chain failed. "
            f"Last error: {(last_error or 'unknown')[:200]}. "
            f"Check API keys and service status, or try again in a few minutes."
        )

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

        # NVIDIA: prefer the unified apiKey (works for all 500+ models on build.nvidia.com).
        # Fall back to the legacy per-model keys: sub-dict for backwards compatibility
        # with installs that have the old multi-key format.
        if provider == 'nvidia':
            # 1. Unified single key (new setup wizard path)
            single_key = provider_cfg.get('apiKey', '') or provider_cfg.get('api_key', '')
            if single_key:
                return single_key
            # 2. Legacy keys: sub-dict — match nickname against active model name
            model_str = (getattr(self.llm, 'model', '') or '').lower()
            nvidia_keys = provider_cfg.get('keys', {}) or {}
            for nickname, nvapi_key in nvidia_keys.items():
                if nvapi_key and nickname.lower() in model_str:
                    return nvapi_key
            # 3. Fall back to first non-empty legacy key
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

        # FLUX models are image-generation only — they don't support chat/completions.
        # Auto-invoke generate_image with the user's prompt instead of erroring.
        if self.llm.provider == "nvidia" and "flux" in self.llm.model.lower():
            return await self.tool_generate_image({
                "prompt": prompt,
                "model": self.llm.model,
            })

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

        # Inject thinking/reasoning params for NVIDIA models that require them
        if self.llm.provider == "nvidia":
            extra = _NVIDIA_THINKING_MODELS.get(self.llm.model, {})
            if extra:
                payload.update(extra)

        try:
            async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                if 'choices' not in data:
                    return f"[ERROR] {self.llm.provider}: {json.dumps(data)}"
                msg = data['choices'][0]['message']
                content = (msg.get('content') or '').strip()
                reasoning = (msg.get('reasoning_content') or '').strip()
                if content:
                    return content
                elif reasoning:
                    return f"[Reasoning]\n{reasoning}"
                else:
                    return '[No response]'
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


    # ═══════════════════════════════════════════════════════════════════════════
    # ── v0.8.0 NEW TOOLS — Ultimate Automation Suite ──────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════

    async def tool_generate_image_sd35(self, args):
        """Generate an image using Stable Diffusion 3.5 Large via NVIDIA NIM."""
        import base64 as _b64, time as _time
        prompt = args.get('prompt', '')
        if not prompt:
            return "[ERROR] generate_image_sd35 requires a 'prompt' argument."
        negative_prompt = args.get('negative_prompt', '')
        width    = int(args.get('width', 1024))
        height   = int(args.get('height', 1024))
        steps    = int(args.get('steps', 40))
        cfg_scale = float(args.get('cfg_scale', 5.0))
        seed     = int(args.get('seed', 0))

        nvidia_cfg = self.core.config.get('providers', {}).get('nvidia', {})
        nvidia_key = nvidia_cfg.get('apiKey', '')
        if not nvidia_key:
            return "[ERROR] No nvidia.apiKey found in config.yaml"

        url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3.5-large"
        headers = {
            "Authorization": f"Bearer {nvidia_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "prompt": prompt,
            "mode": "base",
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "seed": seed,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 401:
                    return f"[ERROR] NVIDIA SD3.5 401 Unauthorized — check your apiKey in config.yaml"
                if r.status_code == 500:
                    return "[ERROR] NVIDIA SD3.5 HTTP 500 — inference server error. Try again in a few minutes."
                if r.status_code != 200:
                    return f"[ERROR] NVIDIA SD3.5 HTTP {r.status_code}: {r.text[:500]}"
                data = r.json()

            artifact = data.get('artifacts', [{}])[0]
            finish = artifact.get('finishReason', '')
            if finish == 'CONTENT_FILTERED':
                return "⚠️ Image blocked by content filter. Try a different prompt."
            b64 = artifact.get('base64', '')
            if not b64:
                return f"[ERROR] SD3.5 generation failed: {json.dumps(data)}"

            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = os.path.join(images_dir, 'sd35')
            os.makedirs(img_subdir, exist_ok=True)
            fname = f"sd35_{int(_time.time())}.jpg"
            path = os.path.join(img_subdir, fname)
            with open(path, 'wb') as f:
                f.write(_b64.b64decode(b64))
            self.last_image_file = path
            return f"✅ SD3.5 image generated: {path}\nModel: stable-diffusion-3.5-large\nPrompt: {prompt}"
        except Exception as e:
            return f"[ERROR] generate_image_sd35: {e}"

    async def tool_generate_image_imagen(self, args):
        """Generate an image using Google Imagen 4 via the google-genai SDK."""
        import time as _time
        prompt       = args.get('prompt', '')
        model        = args.get('model', 'imagen-4')
        aspect_ratio = args.get('aspect_ratio', '1:1')
        n_images     = int(args.get('number_of_images', 1))

        if not prompt:
            return "[ERROR] generate_image_imagen: 'prompt' is required."

        # Map user-friendly names to SDK model identifiers
        model_map = {
            'imagen-4':       'imagen-4.0-generate-001',
            'imagen-4-ultra': 'imagen-4.0-ultra-generate-001',
            'imagen-4-fast':  'imagen-4.0-fast-generate-001',
        }
        sdk_model = model_map.get(model, 'imagen-4.0-generate-001')

        google_cfg = self.core.config.get('providers', {}).get('google', {})
        api_key = google_cfg.get('apiKey', '')
        if not api_key:
            return "[ERROR] generate_image_imagen: No Google API key configured. Add it at providers.google.apiKey in config.yaml."

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            result = client.models.generate_images(
                model=sdk_model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=max(1, min(4, n_images)),
                    aspect_ratio=aspect_ratio,
                    safety_filter_level="BLOCK_ONLY_HIGH",
                    person_generation="ALLOW_ADULT",
                ),
            )

            if not result.generated_images:
                return "[ERROR] Imagen returned no images. Check your prompt for policy violations."

            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = os.path.join(images_dir, 'imagen')
            os.makedirs(img_subdir, exist_ok=True)

            saved = []
            for i, gen_img in enumerate(result.generated_images):
                fname = f"imagen_{int(_time.time())}_{i}.png"
                path = os.path.join(img_subdir, fname)
                # Use .save() if available, else write raw bytes
                if hasattr(gen_img.image, 'save'):
                    gen_img.image.save(path)
                else:
                    with open(path, 'wb') as f:
                        f.write(gen_img.image.image_bytes)
                saved.append(path)

            # Deliver the first image inline via Control Deck / Telegram
            self.last_image_file = saved[0]
            paths_str = '\n'.join(f"  {p}" for p in saved)
            return f"✅ Imagen image(s) generated ({model}):\n{paths_str}\nPrompt: {prompt}"
        except ImportError:
            return "[ERROR] google-genai not installed. Run: pip install google-genai"
        except Exception as e:
            return f"[ERROR] generate_image_imagen: {e}"

    async def tool_list_dir(self, args):
        """List directory contents with sizes and dates."""
        import glob as _glob, stat as _stat
        from datetime import datetime as _dt
        path    = args.get('path', '.') or '.'
        pattern = args.get('pattern', '*')
        recurse = bool(args.get('recurse', False))
        try:
            base = os.path.abspath(path)
            if not os.path.isdir(base):
                return f"[ERROR] Not a directory: {base}"
            search = os.path.join(base, '**', pattern) if recurse else os.path.join(base, pattern)
            entries = _glob.glob(search, recursive=recurse)
            if not entries:
                return f"No files match '{pattern}' in {base}"
            lines = [f"{'TYPE':<5} {'SIZE':>10}  {'MODIFIED':<20}  NAME"]
            lines.append('-' * 70)
            for e in sorted(entries)[:500]:
                try:
                    st   = os.stat(e)
                    kind = 'DIR ' if os.path.isdir(e) else 'FILE'
                    size = '' if os.path.isdir(e) else f"{st.st_size:,}"
                    mtime = _dt.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    name = os.path.relpath(e, base)
                    lines.append(f"{kind:<5} {size:>10}  {mtime:<20}  {name}")
                except Exception:
                    pass
            if len(entries) > 500:
                lines.append(f"... (showing 500 of {len(entries)} matches)")
            return '\n'.join(lines)
        except Exception as e:
            return f"[ERROR] list_dir: {e}"

    async def tool_find_files(self, args):
        """Find files matching a glob pattern recursively."""
        import glob as _glob
        path    = args.get('path', '.') or '.'
        pattern = args.get('pattern', '*')
        limit   = int(args.get('limit', 100))
        try:
            base = os.path.abspath(path)
            if '**' in pattern or '/' in pattern or '\\' in pattern:
                search = os.path.join(base, pattern)
            else:
                search = os.path.join(base, '**', pattern)
            results = _glob.glob(search, recursive=True)
            results = [os.path.relpath(r, base) for r in sorted(results)]
            total = len(results)
            results = results[:limit]
            if not results:
                return f"No files found matching '{pattern}' under {base}"
            out = '\n'.join(results)
            if total > limit:
                out += f"\n... ({total - limit} more results — increase limit to see all)"
            return f"Found {total} file(s):\n{out}"
        except Exception as e:
            return f"[ERROR] find_files: {e}"

    async def tool_hash_file(self, args):
        """Compute a file's hash checksum."""
        import hashlib as _hl
        path = args.get('path', '')
        algo = args.get('algorithm', 'sha256').lower()
        algos = {'sha256': _hl.sha256, 'md5': _hl.md5, 'sha1': _hl.sha1}
        if algo not in algos:
            return f"[ERROR] Unsupported algorithm '{algo}'. Choose: sha256, md5, sha1"
        try:
            h = algos[algo]()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            size = os.path.getsize(path)
            return f"{algo.upper()}: {h.hexdigest()}\nFile: {path}\nSize: {size:,} bytes"
        except Exception as e:
            return f"[ERROR] hash_file: {e}"

    async def tool_diff_files(self, args):
        """Show unified diff between two files or a file and a string."""
        import difflib as _diff
        path_a  = args.get('path_a', '')
        path_b  = args.get('path_b', '')
        text_b  = args.get('text_b', None)
        context = int(args.get('context', 3))
        try:
            with open(path_a, 'r', encoding='utf-8', errors='replace') as f:
                lines_a = f.readlines()
            if path_b:
                with open(path_b, 'r', encoding='utf-8', errors='replace') as f:
                    lines_b = f.readlines()
                label_b = path_b
            elif text_b is not None:
                lines_b = [l if l.endswith('\n') else l + '\n' for l in text_b.splitlines()]
                label_b = '<new content>'
            else:
                return "[ERROR] Provide path_b or text_b to compare against."
            diff = list(_diff.unified_diff(lines_a, lines_b, fromfile=path_a, tofile=label_b, n=context))
            if not diff:
                return "✅ Files are identical — no differences found."
            return ''.join(diff)
        except Exception as e:
            return f"[ERROR] diff_files: {e}"

    async def tool_zip_create(self, args):
        """Create a ZIP archive from a file or directory."""
        import zipfile as _zip, time as _time
        source = args.get('source', '')
        dest   = args.get('destination', '') or source.rstrip('/\\') + '.zip'
        try:
            source = os.path.abspath(source)
            dest   = os.path.abspath(dest)
            if not os.path.exists(source):
                return f"[ERROR] Source does not exist: {source}"
            with _zip.ZipFile(dest, 'w', compression=_zip.ZIP_DEFLATED) as zf:
                if os.path.isdir(source):
                    for root, dirs, files in os.walk(source):
                        for file in files:
                            fp = os.path.join(root, file)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(source)))
                else:
                    zf.write(source, os.path.basename(source))
            size = os.path.getsize(dest)
            return f"✅ Created: {dest}\nSize: {size:,} bytes"
        except Exception as e:
            return f"[ERROR] zip_create: {e}"

    async def tool_zip_extract(self, args):
        """Extract a ZIP archive."""
        import zipfile as _zip
        source = args.get('source', '')
        dest   = args.get('destination', '') or os.path.dirname(os.path.abspath(source))
        try:
            source = os.path.abspath(source)
            dest   = os.path.abspath(dest)
            os.makedirs(dest, exist_ok=True)
            with _zip.ZipFile(source, 'r') as zf:
                names = zf.namelist()
                zf.extractall(dest)
            return f"✅ Extracted {len(names)} files to: {dest}"
        except Exception as e:
            return f"[ERROR] zip_extract: {e}"

    async def tool_image_info(self, args):
        """Get image metadata without loading to AI."""
        path = args.get('path', '')
        try:
            from PIL import Image as _Image
            size = os.path.getsize(path)
            with _Image.open(path) as img:
                w, h   = img.size
                fmt    = img.format or 'UNKNOWN'
                mode   = img.mode
                info   = img.info
            exif_str = ''
            if 'exif' in info:
                exif_str = ' (EXIF data present)'
            return (
                f"File:       {path}\n"
                f"Format:     {fmt}\n"
                f"Dimensions: {w} x {h} px\n"
                f"Color mode: {mode}\n"
                f"File size:  {size:,} bytes ({size/1024:.1f} KB){exif_str}"
            )
        except ImportError:
            # Fallback without PIL — just file size + extension
            ext = os.path.splitext(path)[1].upper().lstrip('.')
            size = os.path.getsize(path) if os.path.exists(path) else 0
            return f"File: {path}\nFormat: {ext}\nFile size: {size:,} bytes\n(Install Pillow for full metadata: pip install Pillow)"
        except Exception as e:
            return f"[ERROR] image_info: {e}"

    async def tool_clipboard_get(self, args):
        """Read text from the OS clipboard."""
        try:
            import subprocess as _sp, sys as _sys
            if _sys.platform == 'win32':
                result = await asyncio.create_subprocess_exec(
                    'powershell', '-Command', 'Get-Clipboard',
                    stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                stdout, _ = await result.communicate()
                text = stdout.decode('utf-8', errors='replace').strip()
            elif _sys.platform == 'darwin':
                result = await asyncio.create_subprocess_exec(
                    'pbpaste', stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                stdout, _ = await result.communicate()
                text = stdout.decode('utf-8', errors='replace').strip()
            else:
                # Linux — try xclip then xsel
                try:
                    result = await asyncio.create_subprocess_exec(
                        'xclip', '-selection', 'clipboard', '-o',
                        stdout=_sp.PIPE, stderr=_sp.PIPE
                    )
                    stdout, _ = await result.communicate()
                    text = stdout.decode('utf-8', errors='replace').strip()
                except FileNotFoundError:
                    result = await asyncio.create_subprocess_exec(
                        'xsel', '--clipboard', '--output',
                        stdout=_sp.PIPE, stderr=_sp.PIPE
                    )
                    stdout, _ = await result.communicate()
                    text = stdout.decode('utf-8', errors='replace').strip()
            if not text:
                return "(Clipboard is empty)"
            return f"Clipboard content ({len(text)} chars):\n{text}"
        except Exception as e:
            return f"[ERROR] clipboard_get: {e}"

    async def tool_clipboard_set(self, args):
        """Write text to the OS clipboard."""
        text = args.get('text', '')
        try:
            import subprocess as _sp, sys as _sys
            if _sys.platform == 'win32':
                proc = await asyncio.create_subprocess_exec(
                    'powershell', '-Command', f'Set-Clipboard -Value @"\n{text}\n"@',
                    stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                await proc.communicate()
            elif _sys.platform == 'darwin':
                proc = await asyncio.create_subprocess_exec(
                    'pbcopy', stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                await proc.communicate(input=text.encode('utf-8'))
            else:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        'xclip', '-selection', 'clipboard',
                        stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE
                    )
                    await proc.communicate(input=text.encode('utf-8'))
                except FileNotFoundError:
                    proc = await asyncio.create_subprocess_exec(
                        'xsel', '--clipboard', '--input',
                        stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE
                    )
                    await proc.communicate(input=text.encode('utf-8'))
            return f"✅ Copied {len(text)} characters to clipboard."
        except Exception as e:
            return f"[ERROR] clipboard_set: {e}"

    async def tool_notify(self, args):
        """Send a desktop notification."""
        import sys as _sys
        title   = args.get('title', 'Galactic AI')
        message = args.get('message', '')
        sound   = bool(args.get('sound', False))
        try:
            if _sys.platform == 'win32':
                # Use PowerShell toast on Windows 10/11
                ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip(5000, '{title.replace("'", "")}', '{message.replace("'", "")}', [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Milliseconds 5500
$notify.Dispose()
""".strip()
                import subprocess as _sp
                proc = await asyncio.create_subprocess_exec(
                    'powershell', '-Command', ps_script,
                    stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                await proc.communicate()
            elif _sys.platform == 'darwin':
                import subprocess as _sp
                proc = await asyncio.create_subprocess_exec(
                    'osascript', '-e',
                    f'display notification "{message}" with title "{title}"',
                    stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                await proc.communicate()
            else:
                import subprocess as _sp
                proc = await asyncio.create_subprocess_exec(
                    'notify-send', title, message,
                    stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                await proc.communicate()
            return f"✅ Notification sent: '{title}' — {message}"
        except Exception as e:
            return f"[ERROR] notify: {e}"

    async def tool_window_list(self, args):
        """List all open windows."""
        import sys as _sys
        try:
            if _sys.platform == 'win32':
                import ctypes, ctypes.wintypes as _wt
                EnumWindows        = ctypes.windll.user32.EnumWindows
                GetWindowTextW     = ctypes.windll.user32.GetWindowTextW
                GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
                IsWindowVisible    = ctypes.windll.user32.IsWindowVisible
                GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                windows = []
                def callback(hwnd, lParam):
                    if IsWindowVisible(hwnd):
                        length = GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            GetWindowTextW(hwnd, buf, length + 1)
                            pid = ctypes.c_ulong()
                            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            windows.append((int(hwnd), buf.value, pid.value))
                    return True
                EnumWindows(EnumWindowsProc(callback), 0)
                if not windows:
                    return "No visible windows found."
                lines = [f"{'HWND':>10}  {'PID':>7}  TITLE"]
                lines.append('-' * 70)
                for hwnd, title, pid in sorted(windows, key=lambda x: x[1].lower()):
                    lines.append(f"{hwnd:>10}  {pid:>7}  {title[:60]}")
                return '\n'.join(lines)
            else:
                import subprocess as _sp
                proc = await asyncio.create_subprocess_exec(
                    'wmctrl', '-l', stdout=_sp.PIPE, stderr=_sp.PIPE
                )
                stdout, _ = await proc.communicate()
                return stdout.decode('utf-8', errors='replace').strip() or "No windows found (wmctrl output was empty)"
        except Exception as e:
            return f"[ERROR] window_list: {e}"

    async def tool_window_focus(self, args):
        """Bring a window to the foreground."""
        import sys as _sys
        title = args.get('title', '')
        hwnd  = args.get('hwnd', None)
        try:
            if _sys.platform == 'win32':
                import ctypes
                if hwnd:
                    target_hwnd = int(hwnd)
                else:
                    # Find by title substring
                    EnumWindows = ctypes.windll.user32.EnumWindows
                    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
                    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
                    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                    found = []
                    def callback(h, lParam):
                        if IsWindowVisible(h):
                            length = GetWindowTextLengthW(h)
                            if length > 0:
                                buf = ctypes.create_unicode_buffer(length + 1)
                                GetWindowTextW(h, buf, length + 1)
                                if title.lower() in buf.value.lower():
                                    found.append((int(h), buf.value))
                        return True
                    EnumWindows(EnumWindowsProc(callback), 0)
                    if not found:
                        return f"[ERROR] No window found matching '{title}'"
                    target_hwnd = found[0][0]
                # Restore if minimized, then set foreground
                ctypes.windll.user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(target_hwnd)
                return f"✅ Focused window HWND={target_hwnd}"
            else:
                import subprocess as _sp
                cmd = ['wmctrl', '-a', title] if title else ['wmctrl', '-ia', str(hwnd)]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=_sp.PIPE, stderr=_sp.PIPE)
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    return f"[ERROR] wmctrl: {stderr.decode().strip()}"
                return f"✅ Window focused"
        except Exception as e:
            return f"[ERROR] window_focus: {e}"

    async def tool_window_resize(self, args):
        """Resize and/or move a window."""
        import sys as _sys
        title  = args.get('title', '')
        hwnd   = args.get('hwnd', None)
        x      = args.get('x', None)
        y      = args.get('y', None)
        width  = args.get('width', None)
        height = args.get('height', None)
        try:
            if _sys.platform == 'win32':
                import ctypes
                if hwnd:
                    target_hwnd = int(hwnd)
                else:
                    EnumWindows = ctypes.windll.user32.EnumWindows
                    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
                    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
                    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                    found = []
                    def callback(h, lParam):
                        if IsWindowVisible(h):
                            length = GetWindowTextLengthW(h)
                            if length > 0:
                                buf = ctypes.create_unicode_buffer(length + 1)
                                GetWindowTextW(h, buf, length + 1)
                                if title.lower() in buf.value.lower():
                                    found.append(int(h))
                        return True
                    EnumWindows(EnumWindowsProc(callback), 0)
                    if not found:
                        return f"[ERROR] No window found matching '{title}'"
                    target_hwnd = found[0]
                # Get current rect
                import ctypes.wintypes as _wt
                rect = _wt.RECT()
                ctypes.windll.user32.GetWindowRect(target_hwnd, ctypes.byref(rect))
                nx = x      if x      is not None else rect.left
                ny = y      if y      is not None else rect.top
                nw = width  if width  is not None else (rect.right - rect.left)
                nh = height if height is not None else (rect.bottom - rect.top)
                ctypes.windll.user32.MoveWindow(target_hwnd, int(nx), int(ny), int(nw), int(nh), True)
                return f"✅ Window moved/resized: pos=({nx},{ny}) size={nw}x{nh}"
            else:
                import subprocess as _sp
                if title:
                    geo = ''
                    if width and height:
                        geo = f"{width}x{height}"
                        if x is not None and y is not None:
                            geo += f"+{x}+{y}"
                    proc = await asyncio.create_subprocess_exec(
                        'wmctrl', '-r', title, '-e', f"0,{x or -1},{y or -1},{width or -1},{height or -1}",
                        stdout=_sp.PIPE, stderr=_sp.PIPE
                    )
                    _, stderr = await proc.communicate()
                    if proc.returncode != 0:
                        return f"[ERROR] wmctrl: {stderr.decode().strip()}"
                    return "✅ Window resized"
                return "[ERROR] Provide title or hwnd"
        except Exception as e:
            return f"[ERROR] window_resize: {e}"

    async def tool_http_request(self, args):
        """Make a raw HTTP request to any URL."""
        method  = args.get('method', 'GET').upper()
        url     = args.get('url', '')
        headers = args.get('headers', {})
        body_json = args.get('json', None)
        body_data = args.get('data', None)
        params  = args.get('params', None)
        timeout = int(args.get('timeout', 30))
        if not url:
            return "[ERROR] http_request requires a 'url' argument."
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs = {'headers': headers or {}}
                if params:
                    kwargs['params'] = params
                if body_json is not None:
                    kwargs['json'] = body_json
                elif body_data is not None:
                    kwargs['content'] = body_data.encode() if isinstance(body_data, str) else body_data
                r = await client.request(method, url, **kwargs)
            ct = r.headers.get('content-type', '')
            if 'application/json' in ct:
                try:
                    body = json.dumps(r.json(), indent=2)[:8000]
                except Exception:
                    body = r.text[:8000]
            else:
                body = r.text[:8000]
            return (
                f"HTTP {r.status_code} {r.reason_phrase}\n"
                f"Content-Type: {ct}\n"
                f"Headers: {dict(r.headers)}\n\n"
                f"{body}"
            )
        except Exception as e:
            return f"[ERROR] http_request: {e}"

    async def tool_qr_generate(self, args):
        """Generate a QR code and save it as a PNG image."""
        text  = args.get('text', '')
        size  = int(args.get('size', 10))
        border = int(args.get('border', 4))
        ec_map = {'L': 1, 'M': 0, 'Q': 3, 'H': 2}
        ec    = ec_map.get(args.get('error_correction', 'M').upper(), 0)
        if not text:
            return "[ERROR] qr_generate requires 'text' argument."
        try:
            import qrcode as _qr
            import time as _time
            qr = _qr.QRCode(
                version=None,
                error_correction=ec,
                box_size=size,
                border=border,
            )
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = os.path.join(images_dir, 'qr')
            os.makedirs(img_subdir, exist_ok=True)
            fname = f"qr_{int(_time.time())}.png"
            path  = os.path.join(img_subdir, fname)
            img.save(path)
            self.last_image_file = path
            return f"✅ QR code saved to: {path}\nContent: {text[:80]}"
        except ImportError:
            return "[ERROR] qrcode library not installed. Run: pip install qrcode[pil]"
        except Exception as e:
            return f"[ERROR] qr_generate: {e}"

    async def tool_env_get(self, args):
        """Read environment variable(s)."""
        name = args.get('name', '')
        _SKIP = {'PATH', 'PYTHONPATH', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA',
                 'COMSPEC', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS'}
        if name:
            val = os.environ.get(name)
            if val is None:
                return f"Environment variable '{name}' is not set."
            return f"{name}={val}"
        else:
            lines = []
            for k, v in sorted(os.environ.items()):
                if any(secret in k.upper() for secret in ['KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'PASS']):
                    lines.append(f"{k}=<hidden>")
                else:
                    lines.append(f"{k}={v[:120]}")
            return '\n'.join(lines)

    async def tool_env_set(self, args):
        """Set an environment variable for this session."""
        name  = args.get('name', '')
        value = args.get('value', '')
        if not name:
            return "[ERROR] env_set requires 'name' argument."
        os.environ[name] = value
        return f"✅ Set {name}={value}"

    async def tool_system_info(self, args):
        """Return detailed system hardware and OS information."""
        import platform as _pl, time as _tm
        try:
            import psutil as _ps
            cpu_count  = _ps.cpu_count(logical=True)
            cpu_phys   = _ps.cpu_count(logical=False)
            cpu_pct    = _ps.cpu_percent(interval=0.3)
            mem        = _ps.virtual_memory()
            disk       = _ps.disk_usage('/')
            boot_time  = _ps.boot_time()
            uptime_s   = int(_tm.time() - boot_time)
            uptime_str = f"{uptime_s//3600}h {(uptime_s%3600)//60}m"
            proc_count = len(_ps.pids())
            ram_total  = f"{mem.total / (1024**3):.1f} GB"
            ram_used   = f"{mem.used / (1024**3):.1f} GB ({mem.percent:.0f}%)"
            disk_total = f"{disk.total / (1024**3):.1f} GB"
            disk_used  = f"{disk.used / (1024**3):.1f} GB ({disk.percent:.0f}%)"
            psutil_info = (
                f"CPU:          {cpu_phys} physical / {cpu_count} logical cores @ {cpu_pct:.1f}% usage\n"
                f"RAM:          {ram_used} / {ram_total}\n"
                f"Disk (/):     {disk_used} / {disk_total}\n"
                f"Uptime:       {uptime_str}\n"
                f"Processes:    {proc_count} running\n"
            )
        except ImportError:
            psutil_info = "(Install psutil for CPU/RAM stats: pip install psutil)\n"
        import sys as _sys
        return (
            f"OS:           {_pl.system()} {_pl.release()} ({_pl.version()[:60]})\n"
            f"Machine:      {_pl.machine()} / {_pl.processor()[:60]}\n"
            f"Python:       {_sys.version.split()[0]} ({_sys.executable})\n"
            + psutil_info
        )

    async def tool_kill_process_by_name(self, args):
        """Kill processes by name substring."""
        name  = args.get('name', '').lower()
        force = bool(args.get('force', False))
        if not name:
            return "[ERROR] kill_process_by_name requires 'name' argument."
        try:
            import psutil as _ps
            killed = []
            for proc in _ps.process_iter(['pid', 'name', 'cmdline']):
                try:
                    pname = (proc.info['name'] or '').lower()
                    if name in pname:
                        if force:
                            proc.kill()
                        else:
                            proc.terminate()
                        killed.append(f"PID {proc.pid}: {proc.info['name']}")
                except (_ps.NoSuchProcess, _ps.AccessDenied):
                    pass
            if not killed:
                return f"No processes found matching '{name}'"
            return f"✅ Terminated {len(killed)} process(es):\n" + '\n'.join(killed)
        except ImportError:
            # Fallback to taskkill / kill
            import subprocess as _sp
            import sys as _sys
            if _sys.platform == 'win32':
                flag = '/F' if force else ''
                cmd = ['taskkill', '/IM', f'*{name}*', flag] if flag else ['taskkill', '/IM', f'*{name}*']
                proc = await asyncio.create_subprocess_exec(*[c for c in cmd if c], stdout=_sp.PIPE, stderr=_sp.PIPE)
                stdout, stderr = await proc.communicate()
                return stdout.decode('utf-8', errors='replace').strip() or stderr.decode('utf-8', errors='replace').strip()
            else:
                sig = '-9' if force else '-15'
                proc = await asyncio.create_subprocess_exec('pkill', sig, '-f', name, stdout=_sp.PIPE, stderr=_sp.PIPE)
                stdout, stderr = await proc.communicate()
                return f"pkill exit {proc.returncode}: {(stdout+stderr).decode(errors='replace').strip() or 'Done'}"
        except Exception as e:
            return f"[ERROR] kill_process_by_name: {e}"

    async def tool_color_pick(self, args):
        """Sample pixel color at screen coordinates."""
        x = int(args.get('x', 0))
        y = int(args.get('y', 0))
        try:
            import pyautogui as _pag
            import colorsys as _cs
            pixel = _pag.screenshot().getpixel((x, y))
            r, g, b = pixel[0], pixel[1], pixel[2]
            h, s, v = _cs.rgb_to_hsv(r/255, g/255, b/255)
            return (
                f"Pixel at ({x}, {y}):\n"
                f"  Hex:  #{r:02X}{g:02X}{b:02X}\n"
                f"  RGB:  rgb({r}, {g}, {b})\n"
                f"  HSV:  hsl({h*360:.0f}°, {s*100:.0f}%, {v*100:.0f}%)"
            )
        except Exception as e:
            return f"[ERROR] color_pick: {e}"

    async def tool_text_transform(self, args):
        """Transform text in various ways."""
        import re as _re, json as _json, urllib.parse as _up, base64 as _b64, csv as _csv, io as _io
        text      = args.get('text', '')
        operation = args.get('operation', '').lower().replace(' ', '_')
        pattern   = args.get('pattern', '')
        try:
            if operation == 'upper':
                return text.upper()
            elif operation == 'lower':
                return text.lower()
            elif operation == 'title':
                return text.title()
            elif operation == 'snake_case':
                return _re.sub(r'[\s\-]+', '_', _re.sub(r'(?<!^)(?=[A-Z])', '_', text)).lower()
            elif operation == 'camel_case':
                parts = _re.split(r'[\s_\-]+', text)
                return parts[0].lower() + ''.join(p.title() for p in parts[1:])
            elif operation == 'base64_encode':
                return _b64.b64encode(text.encode('utf-8')).decode('ascii')
            elif operation == 'base64_decode':
                return _b64.b64decode(text).decode('utf-8', errors='replace')
            elif operation == 'url_encode':
                return _up.quote(text, safe='')
            elif operation == 'url_decode':
                return _up.unquote(text)
            elif operation == 'reverse':
                return text[::-1]
            elif operation == 'count':
                lines = text.splitlines()
                words = text.split()
                non_space = len(text.replace(' ', '').replace('\n', ''))
                return (f"Characters: {len(text):,}\n"
                        f"Words:      {len(words):,}\n"
                        f"Lines:      {len(lines):,}\n"
                        f"Non-space:  {non_space:,}")
            elif operation == 'strip':
                return text.strip()
            elif operation == 'regex_extract':
                if not pattern:
                    return "[ERROR] regex_extract requires a 'pattern' argument."
                matches = _re.findall(pattern, text)
                if not matches:
                    return "No matches found."
                return f"Found {len(matches)} match(es):\n" + '\n'.join(str(m) for m in matches[:100])
            elif operation == 'json_format':
                try:
                    parsed = _json.loads(text)
                    return _json.dumps(parsed, indent=2, ensure_ascii=False)
                except Exception as e:
                    return f"[ERROR] Invalid JSON: {e}"
            elif operation == 'csv_to_json':
                reader = _csv.DictReader(_io.StringIO(text))
                rows = list(reader)
                return _json.dumps(rows, indent=2, ensure_ascii=False)
            else:
                ops = ['upper','lower','title','snake_case','camel_case','base64_encode','base64_decode',
                       'url_encode','url_decode','reverse','count','strip','regex_extract','json_format','csv_to_json']
                return f"[ERROR] Unknown operation '{operation}'. Available: {', '.join(ops)}"
        except Exception as e:
            return f"[ERROR] text_transform ({operation}): {e}"

    # ── New v0.9.2 Tool Implementations ──────────────────────────────

    async def tool_execute_python(self, args):
        """Execute Python code in a subprocess."""
        code = args.get('code', '')
        timeout = min(int(args.get('timeout', 60)), 300)
        if not code.strip():
            return "[ERROR] No code provided."
        import tempfile
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
            tmp.write(code)
            tmp.close()
            proc = await asyncio.create_subprocess_exec(
                'python', tmp.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"[Timeout] Python script exceeded {timeout}s and was killed."
            out = stdout.decode('utf-8', errors='ignore').strip()
            err = stderr.decode('utf-8', errors='ignore').strip()
            result = ""
            if out:
                result += f"STDOUT:\n{out}\n"
            if err:
                result += f"STDERR:\n{err}\n"
            if proc.returncode != 0:
                result += f"Exit code: {proc.returncode}"
            return result or "Script completed with no output."
        except Exception as e:
            return f"[ERROR] execute_python: {e}"
        finally:
            if tmp:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

    async def tool_wait(self, args):
        """Pause execution."""
        seconds = min(float(args.get('seconds', 1)), 300)
        await asyncio.sleep(seconds)
        return f"Waited {seconds:.1f} seconds."

    async def tool_send_telegram(self, args):
        """Send a proactive Telegram message."""
        message = args.get('message', '')
        chat_id = args.get('chat_id', '') or str(self.core.config.get('telegram', {}).get('admin_chat_id', ''))
        image_path = args.get('image_path', '')
        if not chat_id:
            return "[ERROR] No chat_id provided and no admin_chat_id in config."
        if not message:
            return "[ERROR] No message provided."
        try:
            tg = getattr(self.core, 'telegram', None)
            if not tg:
                return "[ERROR] Telegram bridge not available."
            if image_path and os.path.exists(image_path):
                await tg.send_photo(int(chat_id), image_path, caption=message)
                return f"Sent photo + message to Telegram chat {chat_id}."
            else:
                await tg.send_message(int(chat_id), message)
                return f"Sent message to Telegram chat {chat_id}."
        except Exception as e:
            return f"[ERROR] send_telegram: {e}"

    async def tool_read_pdf(self, args):
        """Extract text from a PDF file."""
        path = args.get('path', '')
        pages_arg = args.get('pages', 'all')
        if not path or not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        try:
            try:
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    total = len(pdf.pages)
                    page_range = self._parse_page_range(pages_arg, total)
                    texts = []
                    for i in page_range:
                        page = pdf.pages[i]
                        text = page.extract_text()
                        if text:
                            texts.append(f"--- Page {i+1} ---\n{text}")
                    return "\n\n".join(texts) if texts else "[INFO] No text content found in PDF."
            except ImportError:
                pass
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(path)
                total = len(reader.pages)
                page_range = self._parse_page_range(pages_arg, total)
                texts = []
                for i in page_range:
                    text = reader.pages[i].extract_text()
                    if text:
                        texts.append(f"--- Page {i+1} ---\n{text}")
                return "\n\n".join(texts) if texts else "[INFO] No text content found in PDF."
            except ImportError:
                return "[ERROR] Install pdfplumber or PyPDF2: pip install pdfplumber"
        except Exception as e:
            return f"[ERROR] read_pdf: {e}"

    def _parse_page_range(self, spec, total):
        """Parse page range like '1-5', '3', 'all'."""
        if not spec or spec.lower() == 'all':
            return range(total)
        if '-' in spec:
            parts = spec.split('-')
            start = max(0, int(parts[0]) - 1)
            end = min(total, int(parts[1]))
            return range(start, end)
        return [int(spec) - 1]

    async def tool_read_csv(self, args):
        """Read a CSV file and return as JSON rows."""
        import csv as _csv
        path = args.get('path', '')
        limit = int(args.get('limit', 200))
        delimiter = args.get('delimiter', ',')
        if not path or not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                reader = _csv.DictReader(f, delimiter=delimiter)
                rows = []
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    rows.append(dict(row))
            return json.dumps({"total_rows": len(rows), "columns": list(rows[0].keys()) if rows else [], "rows": rows}, indent=2)
        except Exception as e:
            return f"[ERROR] read_csv: {e}"

    async def tool_write_csv(self, args):
        """Write rows to a CSV file."""
        import csv as _csv
        path = args.get('path', '')
        rows = args.get('rows', [])
        append = args.get('append', False)
        if not path:
            return "[ERROR] No path provided."
        if not rows:
            return "[ERROR] No rows provided."
        try:
            mode = 'a' if append else 'w'
            file_exists = os.path.exists(path) and append
            with open(path, mode, newline='', encoding='utf-8') as f:
                writer = _csv.DictWriter(f, fieldnames=rows[0].keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerows(rows)
            return f"Wrote {len(rows)} rows to {path}."
        except Exception as e:
            return f"[ERROR] write_csv: {e}"

    async def tool_read_excel(self, args):
        """Read an Excel (.xlsx) file."""
        path = args.get('path', '')
        sheet = args.get('sheet', None)
        limit = int(args.get('limit', 100))
        if not path or not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return "[INFO] Empty spreadsheet."
            headers = [str(h) if h else f"col_{i}" for i, h in enumerate(rows[0])]
            data = []
            for row in rows[1:limit+1]:
                data.append({headers[i]: (str(v) if v is not None else '') for i, v in enumerate(row)})
            wb.close()
            return json.dumps({"sheets": wb.sheetnames if hasattr(wb, 'sheetnames') else [], "columns": headers, "rows": data, "total_rows": len(data)}, indent=2)
        except ImportError:
            return "[ERROR] Install openpyxl: pip install openpyxl"
        except Exception as e:
            return f"[ERROR] read_excel: {e}"

    async def tool_regex_search(self, args):
        """Search files with regex."""
        import fnmatch as _fn
        pattern = args.get('pattern', '')
        search_path = args.get('path', '.')
        file_pattern = args.get('file_pattern', '*')
        limit = int(args.get('limit', 50))
        if not pattern:
            return "[ERROR] No pattern provided."
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"[ERROR] Invalid regex: {e}"
        results = []
        try:
            if os.path.isfile(search_path):
                files = [search_path]
            else:
                files = []
                for root, dirs, fnames in os.walk(search_path):
                    for fn in fnames:
                        if _fn.fnmatch(fn, file_pattern):
                            files.append(os.path.join(root, fn))
                    if len(files) > 5000:
                        break
            for fpath in files:
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_no, line in enumerate(f, 1):
                            if compiled.search(line):
                                results.append(f"{fpath}:{line_no}: {line.rstrip()[:200]}")
                                if len(results) >= limit:
                                    return f"Found {len(results)} matches (limit reached):\n" + "\n".join(results)
                except (PermissionError, IsADirectoryError):
                    continue
            return f"Found {len(results)} matches:\n" + "\n".join(results) if results else "No matches found."
        except Exception as e:
            return f"[ERROR] regex_search: {e}"

    async def tool_image_resize(self, args):
        """Resize an image."""
        path = args.get('path', '')
        width = args.get('width')
        height = args.get('height')
        output = args.get('output_path', '')
        if not path or not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        try:
            from PIL import Image
            img = Image.open(path)
            orig_w, orig_h = img.size
            new_w = int(width) if width else orig_w
            new_h = int(height) if height else orig_h
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            out_path = output or os.path.splitext(path)[0] + f"_{new_w}x{new_h}" + os.path.splitext(path)[1]
            resized.save(out_path)
            return f"Resized {orig_w}x{orig_h} → {new_w}x{new_h}. Saved to: {out_path}"
        except ImportError:
            return "[ERROR] Pillow not installed. Run: pip install Pillow"
        except Exception as e:
            return f"[ERROR] image_resize: {e}"

    async def tool_image_convert(self, args):
        """Convert image format."""
        path = args.get('path', '')
        fmt = args.get('format', 'png').lower()
        output = args.get('output_path', '')
        quality = int(args.get('quality', 85))
        if not path or not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        try:
            from PIL import Image
            img = Image.open(path)
            if fmt in ('jpeg', 'jpg') and img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            out_path = output or os.path.splitext(path)[0] + '.' + ('jpg' if fmt == 'jpeg' else fmt)
            save_kwargs = {}
            if fmt in ('jpeg', 'jpg', 'webp'):
                save_kwargs['quality'] = quality
            img.save(out_path, **save_kwargs)
            return f"Converted to {fmt.upper()}. Saved to: {out_path}"
        except ImportError:
            return "[ERROR] Pillow not installed. Run: pip install Pillow"
        except Exception as e:
            return f"[ERROR] image_convert: {e}"

    async def _git_exec(self, cmd_args, cwd=None):
        """Helper to run a git command."""
        cwd = cwd or self.core.config.get('paths', {}).get('workspace', '.')
        proc = await asyncio.create_subprocess_exec(
            'git', *cmd_args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode('utf-8', errors='ignore').strip()
        err = stderr.decode('utf-8', errors='ignore').strip()
        if proc.returncode != 0 and err:
            return f"[git error] {err}"
        return out or err or "(no output)"

    async def tool_git_status(self, args):
        path = args.get('path')
        return await self._git_exec(['status', '--short'], cwd=path)

    async def tool_git_diff(self, args):
        path = args.get('path')
        cmd = ['diff', '--stat']
        if args.get('staged'):
            cmd.append('--cached')
        return await self._git_exec(cmd, cwd=path)

    async def tool_git_log(self, args):
        path = args.get('path')
        count = str(int(args.get('count', 10)))
        return await self._git_exec(['log', f'--oneline', f'-{count}'], cwd=path)

    async def tool_git_commit(self, args):
        path = args.get('path')
        message = args.get('message', 'Auto-commit by Galactic AI')
        files = args.get('files', [])
        cwd = path or self.core.config.get('paths', {}).get('workspace', '.')
        if files:
            for f in files:
                await self._git_exec(['add', f], cwd=cwd)
        else:
            await self._git_exec(['add', '-A'], cwd=cwd)
        return await self._git_exec(['commit', '-m', message], cwd=cwd)

    async def tool_spawn_subagent(self, args):
        """Spawn a background sub-agent."""
        task = args.get('task', '')
        agent_type = args.get('agent_type', 'researcher')
        if not task:
            return "[ERROR] No task provided."
        plugin = None
        for p in self.core.plugins:
            if 'SubAgent' in p.__class__.__name__:
                plugin = p
                break
        if not plugin:
            return "[ERROR] SubAgentPlugin not loaded."
        try:
            session_id = await plugin.spawn(task, agent_id=agent_type)
            return f"Sub-agent spawned. Session ID: {session_id}. Use check_subagent to get results."
        except Exception as e:
            return f"[ERROR] spawn_subagent: {e}"

    async def tool_check_subagent(self, args):
        """Check sub-agent status."""
        session_id = args.get('session_id', '')
        if not session_id:
            return "[ERROR] No session_id provided."
        plugin = None
        for p in self.core.plugins:
            if 'SubAgent' in p.__class__.__name__:
                plugin = p
                break
        if not plugin:
            return "[ERROR] SubAgentPlugin not loaded."
        session = plugin.active_sessions.get(session_id)
        if not session:
            return f"[ERROR] Session {session_id} not found."
        result = {
            "id": session.id,
            "agent": session.agent_id,
            "task": session.task[:100],
            "status": session.status,
            "result": (session.result or "")[:2000] if session.status == "completed" else None,
        }
        return json.dumps(result, indent=2)
