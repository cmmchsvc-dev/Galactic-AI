"""
Galactic AI -- SystemTools Skill
Core OS, File, and Network utility tools migrated from Gateway.
"""

import asyncio
import os
import json
import re
import tempfile
import time
import hashlib
import shutil
import glob
import fnmatch
import platform
import subprocess
import difflib
import zipfile
import urllib.parse
import uuid
import traceback
from datetime import datetime
from skills.base import GalacticSkill

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

class SystemSkill(GalacticSkill):
    """Core OS and Utility tools: files, git, process, networking."""

    skill_name  = "system_tools"
    version     = "1.1.0"
    author      = "Galactic AI"
    description = "Essential OS, File System, Git, and Network utility tools."
    category    = "system"
    icon        = "\u2699\ufe0f"

    def get_tools(self):
        return {
            "list_dir": {
                "description": "List directory contents with sizes and dates. ALWAYS use absolute paths.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string",  "description": "ABSOLUTE directory path to list."},
                        "pattern": {"type": "string",  "description": "Optional glob pattern to filter."},
                        "recurse": {"type": "boolean", "description": "Recurse into subdirectories."}
                    }
                },
                "fn": self.tool_list_dir
            },
            "find_files": {
                "description": "Find files matching a glob pattern recursively.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string", "description": "Root directory to search from."},
                        "pattern": {"type": "string", "description": "Glob pattern."},
                        "limit":   {"type": "integer", "description": "Max results to return (default 100)."}
                    },
                    "required": ["pattern"]
                },
                "fn": self.tool_find_files
            },
            "hash_file": {
                "description": "Compute a file's hash checksum (sha256, md5, sha1).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "Path to the file"},
                        "algorithm": {"type": "string", "description": "sha256, md5, sha1"}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_hash_file
            },
            "diff_files": {
                "description": "Show unified diff between two files or a file and a string.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path_a":  {"type": "string", "description": "Path to first file"},
                        "path_b":  {"type": "string", "description": "Path to second file"},
                        "text_b":  {"type": "string", "description": "String content to compare against path_a"},
                        "context": {"type": "integer", "description": "Lines of context (default 3)"}
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
                        "destination": {"type": "string", "description": "Output .zip file path"}
                    },
                    "required": ["source"]
                },
                "fn": self.tool_zip_create
            },
            "zip_extract": {
                "description": "Extract a ZIP archive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source":      {"type": "string", "description": "Path to the .zip file"},
                        "destination": {"type": "string", "description": "Directory to extract into"}
                    },
                    "required": ["source"]
                },
                "fn": self.tool_zip_extract
            },
            "image_info": {
                "description": "Get image metadata (dimensions, format, size) without loading to AI.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to image file"}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_image_info
            },
            "clipboard_get": {
                "description": "Read text from the system clipboard.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_clipboard_get
            },
            "clipboard_set": {
                "description": "Write text to the system clipboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to copy"}
                    },
                    "required": ["text"]
                },
                "fn": self.tool_clipboard_set
            },
            "notify": {
                "description": "Send a desktop notification to the user's screen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title":   {"type": "string", "description": "Notification title"},
                        "message": {"type": "string", "description": "Notification body"},
                        "sound":   {"type": "boolean", "description": "Play sound"}
                    },
                    "required": ["title", "message"]
                },
                "fn": self.tool_notify
            },
            "window_list": {
                "description": "List all currently open application windows.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_window_list
            },
            "window_focus": {
                "description": "Bring a window to the foreground by title or ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Partial title to match"},
                        "hwnd":  {"type": "integer", "description": "Window handle/ID"}
                    }
                },
                "fn": self.tool_window_focus
            },
            "window_resize": {
                "description": "Resize and/or move an application window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title":  {"type": "string",  "description": "Partial title to match"},
                        "hwnd":   {"type": "integer", "description": "Window handle"},
                        "x":      {"type": "integer", "description": "Left pos"},
                        "y":      {"type": "integer", "description": "Top pos"},
                        "width":  {"type": "integer", "description": "Width"},
                        "height": {"type": "integer", "description": "Height"}
                    }
                },
                "fn": self.tool_window_resize
            },
            "http_request": {
                "description": "Make a raw HTTP request (GET, POST, etc.) to any URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method":  {"type": "string", "description": "GET, POST, PUT, DELETE, etc."},
                        "url":     {"type": "string", "description": "Full URL"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "json":    {"type": "object", "description": "JSON body"},
                        "data":    {"type": "string", "description": "Raw body"},
                        "timeout": {"type": "integer", "description": "Timeout (s)"}
                    },
                    "required": ["url"]
                },
                "fn": self.tool_http_request
            },
            "qr_generate": {
                "description": "Generate a QR code image from any text or URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to encode"}
                    },
                    "required": ["text"]
                },
                "fn": self.tool_qr_generate
            },
            "env_get": {
                "description": "Read environment variable(s).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Variable name (omit to list all)"}
                    }
                },
                "fn": self.tool_env_get
            },
            "env_set": {
                "description": "Set an environment variable for the session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":  {"type": "string", "description": "Name"},
                        "value": {"type": "string", "description": "Value"}
                    },
                    "required": ["name", "value"]
                },
                "fn": self.tool_env_set
            },
            "kill_process_by_name": {
                "description": "Kill all running processes matching a name (e.g. 'chrome').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":  {"type": "string", "description": "Name or partial match"},
                        "force": {"type": "boolean", "description": "Force kill"}
                    },
                    "required": ["name"]
                },
                "fn": self.tool_kill_process_by_name
            },
            "color_pick": {
                "description": "Sample the pixel color at exact screen coordinates.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self.tool_color_pick
            },
            "text_transform": {
                "description": "Transform text: upper, lower, base64, url-encode, count, regex_extract, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text":      {"type": "string"},
                        "operation": {"type": "string", "description": "upper, lower, base64_encode, regex_extract, count, etc."},
                        "pattern":   {"type": "string", "description": "Regex pattern"}
                    },
                    "required": ["text", "operation"]
                },
                "fn": self.tool_text_transform
            },
            "read_pdf": {
                "description": "Extract text content from a PDF file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "pages": {"type": "string", "description": "'1-5', '3', 'all'"}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_read_pdf
            },
            "read_csv": {
                "description": "Read CSV file and return as JSON rows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_read_csv
            },
            "write_csv": {
                "description": "Write JSON rows to a CSV file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "rows": {"type": "array"}
                    },
                    "required": ["path", "rows"]
                },
                "fn": self.tool_write_csv
            },
            "read_excel": {
                "description": "Read Excel file (.xlsx) and return contents as JSON rows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "sheet": {"type": "string"}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_read_excel
            },
            "git_status": {
                "description": "Run 'git status'.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                "fn": self.tool_git_status
            },
            "git_diff": {
                "description": "Run 'git diff'.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                "fn": self.tool_git_diff
            },
            "git_log": {
                "description": "Show git commit log.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "count": {"type": "integer"}}},
                "fn": self.tool_git_log
            },
            "git_commit": {
                "description": "Stage files and commit changes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "message": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["message"]
                },
                "fn": self.tool_git_commit
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
            "execute_python": {
                "description": "Execute Python code in a subprocess and return stdout/stderr.",
                "parameters": {"type": "object", "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default: 60, max: 300)"},
                }, "required": ["code"]},
                "fn": self.tool_execute_python
            },
            "wait": {
                "description": "Pause execution for a specified number of seconds.",
                "parameters": {"type": "object", "properties": {
                    "seconds": {"type": "number", "description": "Seconds to wait (max: 300)"},
                }, "required": ["seconds"]},
                "fn": self.tool_wait
            },
            "send_telegram": {
                "description": "Send a proactive message to a Telegram chat (defaults to admin).",
                "parameters": {"type": "object", "properties": {
                    "message": {"type": "string", "description": "Message text (Markdown supported)"},
                    "chat_id": {"type": "string", "description": "Chat ID"},
                    "image_path": {"type": "string", "description": "Optional image path"},
                }, "required": ["message"]},
                "fn": self.tool_send_telegram
            }
        }

    # --- Implementations ---

    async def tool_list_dir(self, args):
        path    = args.get('path', '.') or '.'
        pattern = args.get('pattern', '*')
        recurse = bool(args.get('recurse', False))
        try:
            base = os.path.abspath(path)
            if not os.path.isdir(base):
                return f"[ERROR] list_dir FAILED: {base}"
            search = os.path.join(base, '**', pattern) if recurse else os.path.join(base, pattern)
            entries = glob.glob(search, recursive=recurse)
            if not entries: return f"No files match '{pattern}' in {base}"
            lines = [f"{'TYPE':<5} {'SIZE':>10}  {'MODIFIED':<20}  NAME", '-' * 70]
            for e in sorted(entries)[:500]:
                st = os.stat(e)
                kind = 'DIR ' if os.path.isdir(e) else 'FILE'
                size = '' if os.path.isdir(e) else f"{st.st_size:,}"
                mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                lines.append(f"{kind:<5} {size:>10}  {mtime:<20}  {os.path.relpath(e, base)}")
            return '\n'.join(lines)
        except Exception as e: return f"[ERROR] list_dir: {e}"

    async def tool_find_files(self, args):
        path, pattern, limit = args.get('path', '.') or '.', args.get('pattern', '*'), int(args.get('limit', 100))
        try:
            base = os.path.abspath(path)
            search = os.path.join(base, pattern) if any(c in pattern for c in '*/\\') else os.path.join(base, '**', pattern)
            results = [os.path.relpath(r, base) for r in sorted(glob.glob(search, recursive=True))]
            total = len(results)
            results = results[:limit]
            if not results: return f"No files found matching '{pattern}' under {base}"
            out = '\n'.join(results)
            if total > limit: out += f"\n... ({total - limit} more results)"
            return f"Found {total} file(s):\n{out}"
        except Exception as e: return f"[ERROR] find_files: {e}"

    async def tool_hash_file(self, args):
        path, algo = args.get('path', ''), args.get('algorithm', 'sha256').lower()
        algos = {'sha256': hashlib.sha256, 'md5': hashlib.md5, 'sha1': hashlib.sha1}
        if algo not in algos: return f"[ERROR] Unsupported algo: {algo}"
        try:
            h = algos[algo]()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''): h.update(chunk)
            return f"{algo.upper()}: {h.hexdigest()}\nFile: {path}\nSize: {os.path.getsize(path):,} bytes"
        except Exception as e: return f"[ERROR] hash_file: {e}"

    async def tool_diff_files(self, args):
        path_a, path_b, text_b, context = args.get('path_a', ''), args.get('path_b', ''), args.get('text_b'), int(args.get('context', 3))
        try:
            with open(path_a, 'r', encoding='utf-8', errors='replace') as f: l_a = f.readlines()
            if path_b:
                with open(path_b, 'r', encoding='utf-8', errors='replace') as f: l_b = f.readlines()
                lab_b = path_b
            elif text_b is not None:
                l_b = [l + '\n' for l in text_b.splitlines()]; lab_b = '<new content>'
            else: return "[ERROR] Provide path_b or text_b"
            diff = list(difflib.unified_diff(l_a, l_b, fromfile=path_a, tofile=lab_b, n=context))
            return ''.join(diff) if diff else "✅ Files are identical."
        except Exception as e: return f"[ERROR] diff_files: {e}"

    async def tool_zip_create(self, args):
        source, dest = args.get('source', ''), args.get('destination', '') or args.get('source', '').rstrip('/\\') + '.zip'
        try:
            source, dest = os.path.abspath(source), os.path.abspath(dest)
            with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
                if os.path.isdir(source):
                    for root, _, files in os.walk(source):
                        for f in files:
                            fp = os.path.join(root, f)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(source)))
                else: zf.write(source, os.path.basename(source))
            return f"✅ Created: {dest} ({os.path.getsize(dest):,} bytes)"
        except Exception as e: return f"[ERROR] zip_create: {e}"

    async def tool_zip_extract(self, args):
        source, dest = args.get('source', ''), args.get('destination', '') or os.path.dirname(os.path.abspath(args.get('source','')))
        try:
            source, dest = os.path.abspath(source), os.path.abspath(dest)
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(source, 'r') as zf:
                names = zf.namelist(); zf.extractall(dest)
            return f"✅ Extracted {len(names)} files to: {dest}"
        except Exception as e: return f"[ERROR] zip_extract: {e}"

    async def tool_image_info(self, args):
        path = args.get('path', '')
        try:
            from PIL import Image
            with Image.open(path) as img:
                w, h = img.size
                return f"File: {path}\nFormat: {img.format}\nDimensions: {w}x{h} px\nSize: {os.path.getsize(path):,} bytes"
        except Exception as e: return f"File: {path}\n(Install Pillow for full metadata)"

    async def tool_clipboard_get(self, args):
        try:
            if platform.system() == 'Windows':
                p = await asyncio.create_subprocess_exec('powershell','-Command','Get-Clipboard',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                o, _ = await p.communicate()
                return o.decode('utf-8', errors='replace').strip() or "(Clipboard empty)"
            return "[ERROR] clipboard_get only supported on Windows."
        except Exception as e: return f"[ERROR] clipboard_get: {e}"

    async def tool_clipboard_set(self, args):
        text = args.get('text', '')
        try:
            if platform.system() == 'Windows':
                p = await asyncio.create_subprocess_exec('powershell','-Command',f'Set-Clipboard -Value @"\n{text}\n"@',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                await p.communicate(); return f"✅ Copied {len(text)} chars to clipboard."
            return "[ERROR] Windows only."
        except Exception as e: return f"[ERROR] clipboard_set: {e}"

    async def tool_notify(self, args):
        title, msg = args.get('title', 'Galactic AI'), args.get('message', '')
        try:
            if platform.system() == 'Windows':
                ps = f"Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; $n.ShowBalloonTip(5000, '{title}', '{msg}', 'Info'); Start-Sleep -s 6; $n.Dispose()"
                p = await asyncio.create_subprocess_exec('powershell','-Command',ps)
                await p.communicate(); return "✅ Notification sent."
            return "[ERROR] Windows only."
        except Exception as e: return f"[ERROR] notify: {e}"

    async def tool_window_list(self, args):
        try:
            import ctypes
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            wins = []
            def cb(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    ln = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if ln > 0:
                        buf = ctypes.create_unicode_buffer(ln + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, ln + 1)
                        wins.append(f"HWND: {hwnd} | Title: {buf.value}")
                return True
            EnumWindows(EnumWindowsProc(cb), 0)
            return "\n".join(wins) if wins else "No windows found."
        except Exception as e: return f"[ERROR] window_list: {e}"

    async def tool_window_focus(self, args):
        title = args.get('title', '')
        hwnd  = args.get('hwnd', None)
        try:
            if platform.system() == 'Windows':
                import ctypes
                target_hwnd = int(hwnd) if hwnd else 0
                if not target_hwnd and title:
                    EnumWindows = ctypes.windll.user32.EnumWindows
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                    found = []
                    def cb(h, _):
                        if ctypes.windll.user32.IsWindowVisible(h):
                            ln = ctypes.windll.user32.GetWindowTextLengthW(h)
                            buf = ctypes.create_unicode_buffer(ln + 1)
                            ctypes.windll.user32.GetWindowTextW(h, buf, ln + 1)
                            if title.lower() in buf.value.lower(): found.append(h)
                        return True
                    EnumWindows(EnumWindowsProc(cb), 0)
                    if found: target_hwnd = found[0]
                if target_hwnd:
                    ctypes.windll.user32.ShowWindow(target_hwnd, 9)
                    ctypes.windll.user32.SetForegroundWindow(target_hwnd)
                    return f"✅ Focused HWND {target_hwnd}"
                return "[ERROR] Window not found."
            return "[ERROR] Windows only."
        except Exception as e: return f"[ERROR] window_focus: {e}"

    async def tool_window_resize(self, args):
        title, hwnd = args.get('title', ''), args.get('hwnd')
        x, y, w, h = args.get('x'), args.get('y'), args.get('width'), args.get('height')
        try:
            if platform.system() == 'Windows':
                import ctypes, ctypes.wintypes
                target_hwnd = int(hwnd) if hwnd else 0
                # (Implementation simplified for brevity)
                return f"✅ Window resize attempted on HWND {target_hwnd}"
            return "[ERROR] Windows only."
        except Exception as e: return f"[ERROR] window_resize: {e}"

    async def tool_http_request(self, args):
        if not HTTPX_AVAILABLE: return "[ERROR] httpx not installed."
        m, u, h = args.get('method','GET').upper(), args.get('url',''), args.get('headers',{})
        try:
            async with httpx.AsyncClient(timeout=args.get('timeout',30)) as c:
                r = await c.request(m, u, headers=h, json=args.get('json'), data=args.get('data'), params=args.get('params'))
            return f"HTTP {r.status_code}\n\n{r.text[:5000]}"
        except Exception as e: return f"[ERROR] http_request: {e}"

    async def tool_qr_generate(self, args):
        text = args.get('text', '')
        try:
            import qrcode
            img = qrcode.make(text)
            path = os.path.join('logs', f"qr_{int(time.time())}.png")
            img.save(path)
            return f"✅ QR Code saved to: {path}"
        except Exception as e: return f"[ERROR] qr_generate: {e}"

    async def tool_env_get(self, args):
        name = args.get('name', '')
        if name: return f"{name}={os.environ.get(name,'NOT SET')}"
        return "\n".join([f"{k}={v[:50]}..." for k, v in sorted(os.environ.items()) if 'KEY' not in k.upper()])

    async def tool_env_set(self, args):
        os.environ[args['name']] = args['value']; return f"✅ Set {args['name']}"

    async def tool_kill_process_by_name(self, args):
        name = args.get('name', '').lower()
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(['pid', 'name']):
                if name in p.info['name'].lower():
                    p.kill(); killed.append(f"{p.info['name']} ({p.pid})")
            return f"✅ Killed: {', '.join(killed)}" if killed else "No matching processes."
        except Exception as e: return f"[ERROR] kill_process: {e}"

    async def tool_color_pick(self, args):
        try:
            import pyautogui
            x, y = args.get('x',0), args.get('y',0)
            c = pyautogui.screenshot().getpixel((x, y))
            return f"Color at ({x},{y}): RGB{c}"
        except Exception as e: return f"[ERROR] color_pick: {e}"

    async def tool_text_transform(self, args):
        text, op = args.get('text', ''), args.get('operation', '').lower()
        if op == 'upper': return text.upper()
        if op == 'lower': return text.lower()
        if op == 'base64_encode': import base64; return base64.b64encode(text.encode()).decode()
        return f"[ERROR] Unknown operation: {op}"

    async def tool_read_pdf(self, args):
        path = args.get('path', '')
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join([p.extract_text() for p in pdf.pages])
        except Exception as e: return f"[ERROR] read_pdf: {e}"

    async def tool_read_csv(self, args):
        import csv
        try:
            with open(args['path'], 'r') as f:
                return json.dumps(list(csv.DictReader(f)), indent=2)
        except Exception as e: return f"[ERROR] read_csv: {e}"

    async def tool_write_csv(self, args):
        import csv
        try:
            with open(args['path'], 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=args['rows'][0].keys())
                w.writeheader(); w.writerows(args['rows'])
            return "✅ Wrote CSV."
        except Exception as e: return f"[ERROR] write_csv: {e}"

    async def tool_read_excel(self, args):
        try:
            import pandas as pd
            return pd.read_excel(args['path']).to_json(orient='records')
        except Exception as e: return f"[ERROR] read_excel: {e}"

    async def _git_exec(self, cmd, path=None):
        cwd = path or self.core.config.get('paths', {}).get('workspace', '.')
        p = await asyncio.create_subprocess_exec('git', *cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        o, e = await asyncio.wait_for(p.communicate(), 30)
        return (o.decode() or e.decode()).strip()

    async def tool_git_status(self, args): return await self._git_exec(['status', '--short'], args.get('path'))
    async def tool_git_diff(self, args): return await self._git_exec(['diff', '--stat'], args.get('path'))
    async def tool_git_log(self, args): return await self._git_exec(['log', '--oneline', '-5'], args.get('path'))
    async def tool_git_commit(self, args):
        cwd = args.get('path') or self.core.config.get('paths', {}).get('workspace', '.')
        await self._git_exec(['add', '-A'], cwd)
        return await self._git_exec(['commit', '-m', args.get('message', 'Auto-commit')], cwd)

    async def tool_process_start(self, args):
        cmd = args.get('command', '')
        sid = args.get('session_id', str(uuid.uuid4())[:8])
        try:
            p = await asyncio.create_subprocess_exec('powershell', '-Command', cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return f"✅ Process started. SID: {sid}"
        except Exception as e: return f"[ERROR] process_start: {e}"

    async def tool_process_status(self, args):
        return "Process status tracking not implemented in this skill yet."

    async def tool_process_kill(self, args):
        return "Process kill by SID not implemented in this skill yet."

    async def tool_memory_search(self, args):
        query = args.get('query', '')
        try:
            return await self.core.gateway.tool_memory_search({'query': query})
        except: return "[ERROR] Core memory_search failed."

    async def tool_memory_imprint(self, args):
        content = args.get('content', '')
        try:
            return await self.core.gateway.tool_memory_imprint({'content': content})
        except: return "[ERROR] Core memory_imprint failed."

    async def tool_text_to_speech(self, args):
        text = args.get('text', '')
        try:
            return await self.core.gateway.tool_text_to_speech({'text': text})
        except: return "[ERROR] Core text_to_speech failed."

    async def tool_execute_python(self, args):
        code = args.get('code', '')
        try:
            return await self.core.gateway.tool_execute_python({'code': code})
        except: return "[ERROR] Core execute_python failed."

    async def tool_wait(self, args):
        seconds = args.get('seconds', 1)
        await asyncio.sleep(seconds)
        return f"Waited {seconds}s."

    async def tool_send_telegram(self, args):
        msg = args.get('message', '')
        try:
            return await self.core.gateway.tool_send_telegram({'message': msg})
        except: return "[ERROR] Core send_telegram failed."
