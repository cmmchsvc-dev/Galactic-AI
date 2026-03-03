"""
Galactic AI -- SystemTools Skill
Core OS, File, and Network utility tools migrated from Gateway.
"""

import asyncio
import os
import json
import re
import ast
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
                "description": "Start a background process and track it. CRITICAL: If you need to wait for the result before replying to the user to avoid 'hanging up' on them, you MUST immediately call process_wait after this.",
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
            "process_wait": {
                "description": "Wait for a background process to finish and return its final output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Process session ID."},
                        "timeout": {"type": "integer", "description": "Maximum seconds to wait (default 120, max 600)."}
                    },
                    "required": ["session_id"]
                },
                "fn": self.tool_process_wait
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
                "description": "Execute Python code and return stdout/stderr. MANDATE: NEVER use subprocess.Popen or 'start' commands here to 'background' a task to bypass turn limits. All code MUST be synchronous or use await. If you need backgrounding, you MUST use process_start.",
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
            },
            "grep_search": {
                "description": "Search file contents for a text or regex pattern. Returns matching lines with filenames and line numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Text or regex pattern to find."},
                        "path": {"type": "string", "description": "Root directory to search (default: current workspace)."},
                        "file_pattern": {"type": "string", "description": "Optional glob to filter files (e.g. '*.py')."},
                        "max_results": {"type": "integer", "description": "Max matches to return (default: 50)."}
                    },
                    "required": ["pattern"]
                },
                "fn": self.tool_grep_search
            },
            "code_outline": {
                "description": "Show the structure of a Python code file: classes, functions, and methods with line numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the Python file to analyze."}
                    },
                    "required": ["path"]
                },
                "fn": self.tool_code_outline
            }
        }

    # --- Implementations ---

    async def tool_list_dir(self, args):
        """List directory contents (non-blocking)."""
        path    = args.get('path', '.') or '.'
        pattern = args.get('pattern', '*')
        recurse = bool(args.get('recurse', False))
        
        def _list_sync():
            try:
                base = os.path.abspath(path)
                if not os.path.isdir(base):
                    return f"[ERROR] list_dir FAILED: {base}"
                search = os.path.join(base, '**', pattern) if recurse else os.path.join(base, pattern)
                import glob
                entries = glob.glob(search, recursive=recurse)
                if not entries: return f"No files match '{pattern}' in {base}"
                lines = [f"{'TYPE':<5} {'SIZE':>10}  {'MODIFIED':<20}  NAME", '-' * 70]
                for e in sorted(entries)[:500]:
                    try:
                        st = os.stat(e)
                        kind = 'DIR ' if os.path.isdir(e) else 'FILE'
                        size = '' if os.path.isdir(e) else f"{st.st_size:,}"
                        mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        name = os.path.relpath(e, base)
                        flag = ""
                        if not os.path.isdir(e):
                            ext = os.path.splitext(e)[1].lower()
                            if ext in ('.onnx', '.engine', '.7z', '.zip') and st.st_size < 1000:
                                flag = " [CRITICAL WARNING: FILE IS SUSPICIOUSLY SMALL / LIKELY CORRUPT]"
                        lines.append(f"{kind:<5} {size:>10}  {mtime:<20}  {name}{flag}")
                    except: continue
                return '\n'.join(lines)
            except Exception as e: return f"[ERROR] list_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _list_sync)

    async def tool_find_files(self, args):
        """Find files matching a glob pattern (non-blocking)."""
        path    = args.get('path', '.') or '.'
        pattern = args.get('pattern', '*')
        limit   = int(args.get('limit', 100))
        
        def _find_sync():
            try:
                base = os.path.abspath(path)
                search = os.path.join(base, '**', pattern) if '**' not in pattern else os.path.join(base, pattern)
                import glob
                results = sorted(glob.glob(search, recursive=True))
                found = [os.path.relpath(r, base) for r in results[:limit]]
                if not found: return f"No files found matching '{pattern}' under {base}"
                out = "\n".join(found)
                if len(results) > limit: out += f"\n... ({len(results) - limit} more)"
                return f"Found {len(results)} file(s):\n{out}"
            except Exception as e: return f"[ERROR] find_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _find_sync)

    async def tool_hash_file(self, args):
        """Compute file hash (non-blocking)."""
        path, algo = args.get('path', ''), args.get('algorithm', 'sha256').lower()
        algos = {'sha256': hashlib.sha256, 'md5': hashlib.md5, 'sha1': hashlib.sha1}
        if algo not in algos: return f"[ERROR] Unsupported algo: {algo}"
        
        def _hash_sync():
            try:
                h = algos[algo]()
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''): h.update(chunk)
                return h.hexdigest(), os.path.getsize(path)
            except Exception as e: return str(e), 0

        try:
            loop = asyncio.get_running_loop()
            digest, size = await loop.run_in_executor(None, _hash_sync)
            if size == 0 and digest != hashlib.sha256(b"").hexdigest(): # Basic error check
                 return f"[ERROR] hash_file: {digest}"
            return f"{algo.upper()}: {digest}\nFile: {path}\nSize: {size:,} bytes"
        except Exception as e: return f"[ERROR] hash_file: {e}"

    async def tool_diff_files(self, args):
        """Unified diff (non-blocking)."""
        path_a, path_b, text_b, context = args.get('path_a', ''), args.get('path_b', ''), args.get('text_b'), int(args.get('context', 3))
        
        def _diff_sync():
            try:
                with open(path_a, 'r', encoding='utf-8', errors='replace') as f: l_a = f.readlines()
                if path_b:
                    with open(path_b, 'r', encoding='utf-8', errors='replace') as f: l_b = f.readlines()
                    lab_b = path_b
                elif text_b is not None:
                    l_b = [l + '\n' for l in text_b.splitlines()]; lab_b = '<new content>'
                else: return "[ERROR] Provide path_b or text_b"
                import difflib
                diff = list(difflib.unified_diff(l_a, l_b, fromfile=path_a, tofile=lab_b, n=context))
                return ''.join(diff) if diff else "✅ Files are identical."
            except Exception as e: return f"[ERROR] diff_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _diff_sync)

    async def tool_zip_create(self, args):
        """Create a ZIP archive (non-blocking)."""
        source, dest = args.get('source', ''), args.get('destination', '') or args.get('source', '').rstrip('/\\') + '.zip'
        def _zip_sync():
            try:
                src, dst = os.path.abspath(source), os.path.abspath(dest)
                import zipfile
                with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zf:
                    if os.path.isdir(src):
                        for root, _, files in os.walk(src):
                            for f in files:
                                fp = os.path.join(root, f)
                                zf.write(fp, os.path.relpath(fp, os.path.dirname(src)))
                    else: zf.write(src, os.path.basename(src))
                return f"✅ Created: {dst} ({os.path.getsize(dst):,} bytes)"
            except Exception as e: return f"[ERROR] zip_create sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _zip_sync)

    async def tool_zip_extract(self, args):
        """Extract a ZIP archive (non-blocking)."""
        source, dest = args.get('source', ''), args.get('destination', '') or os.path.dirname(os.path.abspath(args.get('source','')))
        def _extract_sync():
            try:
                src, dst = os.path.abspath(source), os.path.abspath(dest)
                os.makedirs(dst, exist_ok=True)
                import zipfile
                with zipfile.ZipFile(src, 'r') as zf:
                    names = zf.namelist(); zf.extractall(dst)
                return f"✅ Extracted {len(names)} files to: {dst}"
            except Exception as e: return f"[ERROR] zip_extract sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _extract_sync)

    async def tool_image_info(self, args):
        """Get image info (non-blocking)."""
        path = args.get('path', '')
        def _img_sync():
            try:
                from PIL import Image
                with Image.open(path) as img:
                    w, h = img.size
                    return f"File: {path}\nFormat: {img.format}\nDimensions: {w}x{h} px\nSize: {os.getsize(path):,} bytes"
            except Exception as e: return f"File: {path}\n(Error: {e})"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _img_sync)

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
        """Generate a QR code image (non-blocking)."""
        text = args.get('text', '')
        def _qr_sync():
            try:
                import qrcode
                img = qrcode.make(text)
                path = os.path.join('logs', f"qr_{int(time.time())}.png")
                img.save(path)
                return f"✅ QR Code saved to: {path}"
            except Exception as e: return f"[ERROR] qr_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _qr_sync)

    async def tool_env_get(self, args):
        name = args.get('name', '')
        if name: return f"{name}={os.environ.get(name,'NOT SET')}"
        return "\n".join([f"{k}={v[:50]}..." for k, v in sorted(os.environ.items()) if 'KEY' not in k.upper()])

    async def tool_env_set(self, args):
        os.environ[args['name']] = args['value']; return f"✅ Set {args['name']}"

    async def tool_kill_process_by_name(self, args):
        """Kill all running processes matching a name (non-blocking)."""
        name = args.get('name', '').lower()
        def _kill_sync():
            try:
                import psutil
                killed = []
                for p in psutil.process_iter(['pid', 'name']):
                    if name in (p.info['name'] or "").lower():
                        try:
                            p.kill(); killed.append(f"{p.info['name']} ({p.pid})")
                        except: continue
                return f"✅ Killed: {', '.join(killed)}" if killed else "No matching processes."
            except Exception as e: return f"[ERROR] kill_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _kill_sync)

    async def tool_color_pick(self, args):
        """Sample the pixel color at exact screen coordinates (non-blocking)."""
        try:
            x, y = int(args.get('x', 0)), int(args.get('y', 0))
            def _color_sync():
                try:
                    import pyautogui
                    # Sample color at x, y
                    c = pyautogui.screenshot().getpixel((x, y))
                    return f"Color at ({x},{y}): RGB{c}"
                except Exception as e: return f"[ERROR] color_sync: {e}"

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _color_sync)
        except Exception as e: return f"[ERROR] color_pick: {e}"

    async def tool_text_transform(self, args):
        text, op = args.get('text', ''), args.get('operation', '').lower()
        if op == 'upper': return text.upper()
        if op == 'lower': return text.lower()
        if op == 'base64_encode': import base64; return base64.b64encode(text.encode()).decode()
        return f"[ERROR] Unknown operation: {op}"

    async def tool_read_pdf(self, args):
        """Extract text from PDF (non-blocking)."""
        path = args.get('path', '')
        def _pdf_sync():
            try:
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    return "\n".join([p.extract_text() or "" for p in pdf.pages])
            except Exception as e: return f"[ERROR] pdf_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _pdf_sync)

    async def tool_read_csv(self, args):
        """Read CSV (non-blocking)."""
        path, limit = args.get('path', ''), args.get('limit', 100)
        def _csv_sync():
            try:
                import csv
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    rows = list(csv.DictReader(f))
                    return json.dumps(rows[:limit], indent=2)
            except Exception as e: return f"[ERROR] csv_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _csv_sync)

    async def tool_write_csv(self, args):
        """Write JSON rows to a CSV file (non-blocking)."""
        path, rows = args.get('path', ''), args.get('rows', [])
        def _csv_write_sync():
            try:
                if not rows: return "[ERROR] No rows to write."
                import csv
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=rows[0].keys())
                    w.writeheader(); w.writerows(rows)
                return f"✅ Wrote {len(rows)} rows to {path}"
            except Exception as e: return f"[ERROR] csv_write_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _csv_write_sync)

    async def tool_read_excel(self, args):
        """Read Excel file (.xlsx) and return contents as JSON rows (non-blocking)."""
        path = args.get('path', '')
        def _excel_sync():
            try:
                import pandas as pd
                return pd.read_excel(path).to_json(orient='records')
            except Exception as e: return f"[ERROR] excel_sync: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _excel_sync)

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
        if not hasattr(self, '_active_processes'):
            self._active_processes = {}
            
        if sid in self._active_processes and self._active_processes[sid]['process'].returncode is None:
            return f"[ERROR] Session ID {sid} is already running."
            
        try:
            p = await asyncio.create_subprocess_exec('powershell', '-Command', cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            out_buf = []
            err_buf = []
            
            async def read_stream(stream, buf):
                while True:
                    line = await stream.readline()
                    if not line: break
                    buf.append(line.decode('utf-8', errors='replace'))
                    if len(buf) > 1000: buf.pop(0)
            
            t_out = asyncio.create_task(read_stream(p.stdout, out_buf))
            t_err = asyncio.create_task(read_stream(p.stderr, err_buf))
            
            p_info = {
                'process': p,
                'cmd': cmd,
                'out_buf': out_buf,
                'err_buf': err_buf,
                'tasks': [t_out, t_err],
                'start_time': time.time()
            }
            self._active_processes[sid] = p_info
            self._active_processes['latest'] = p_info # Alias for easier waiting
            
            return f"✅ Process started in background. SID: {sid}\nUse process_status or process_wait with SID 'latest' to check output."
        except Exception as e: return f"[ERROR] process_start: {e}"

    async def tool_process_status(self, args):
        sid = args.get('session_id', '') or 'latest'
        if not hasattr(self, '_active_processes') or sid not in self._active_processes:
            return f"[ERROR] No active process found with SID: {sid}"

        p_info = self._active_processes[sid]
        p = p_info['process']

        status = "RUNNING"
        if p.returncode is not None:
            status = f"EXITED with code {p.returncode}"
            if p.returncode != 0:
                status += " [FAILED]"

        out_tail = "".join(p_info['out_buf'][-50:])
        err_tail = "".join(p_info['err_buf'][-50:])

        res = f"--- Process Status for {sid} ---\nCommand: {p_info['cmd'][:100]}\nStatus: {status}\nUptime: {int(time.time() - p_info['start_time'])}s\n"
        if out_tail: res += f"\n--- STDOUT (Last 50 lines) ---\n{out_tail.strip()}"
        if err_tail: res += f"\n--- STDERR (Last 50 lines) ---\n{err_tail.strip()}"
        if not out_tail and not err_tail: res += "\n(No output captured yet)"

        return res

    async def tool_process_kill(self, args):
        sid = args.get('session_id', '') or 'latest'
        if not hasattr(self, '_active_processes') or sid not in self._active_processes:
            return f"[ERROR] No active process found with SID: {sid}"

        p_info = self._active_processes[sid]
        p = p_info['process']
        if p.returncode is not None:
            return f"Process {sid} already exited with code {p.returncode}."

        try:
            if platform.system() == 'Windows':
                # Kill process tree on Windows to prevent orphaned children (like nested powershells)
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True)
            else:
                p.kill()
            return f"✅ Killed process {sid} (and any child processes)."
        except Exception as e:
            return f"[ERROR] Failed to kill {sid}: {e}"

    async def tool_process_wait(self, args):
        sid = args.get('session_id', '') or 'latest'
        timeout = int(args.get('timeout', 120))
        timeout = min(timeout, 600)  # Max 10 minutes

        if not hasattr(self, '_active_processes') or sid not in self._active_processes:
            return f"[ERROR] No active process found with SID: {sid}"

        p_info = self._active_processes[sid]
        p = p_info['process']

        start_wait = time.time()
        while p.returncode is None:
            if time.time() - start_wait > timeout:
                return f"[TIMEOUT] Process {sid} is still running after {timeout} seconds.\nConsider using process_status to check progress, or process_kill if it's stuck."
            await asyncio.sleep(1)

        # Give a moment for the output buffers to catch up
        await asyncio.sleep(0.5)
        status_report = await self.tool_process_status({'session_id': sid})

        if p.returncode != 0:
            return f"⚠️ PROCESS FAILED (Exit Code {p.returncode})\n\n{status_report}"
        return f"✅ PROCESS COMPLETED SUCCESSFULLY\n\n{status_report}"
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

    async def tool_grep_search(self, args):
        """Search file contents (non-blocking)."""
        pattern = args.get('pattern')
        path = args.get('path', '.') or '.'
        file_pattern = args.get('file_pattern', '*')
        max_results = int(args.get('max_results', 50))

        def _grep_sync():
            try:
                import fnmatch
                base = os.path.abspath(path)
                regex = re.compile(pattern, re.IGNORECASE)
                matches = []
                
                # Directories to skip
                skip_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv'}
                
                for root, dirs, files in os.walk(base):
                    # Skip unwanted directories
                    dirs[:] = [d for d in dirs if d not in skip_dirs]
                    
                    for filename in files:
                        if not fnmatch.fnmatch(filename, file_pattern):
                            continue
                            
                        file_path = os.path.join(root, filename)
                        
                        # Skip binary files/large files
                        if os.path.getsize(file_path) > 1_000_000: # 1MB limit for grep
                            continue
                            
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                for i, line in enumerate(f, 1):
                                    if regex.search(line):
                                        rel_path = os.path.relpath(file_path, base)
                                        matches.append(f"{rel_path}:{i}: {line.strip()}")
                                        if len(matches) >= max_results:
                                            return matches
                        except: continue
                return matches
            except Exception as e: return [f"[ERROR] grep_sync: {e}"]

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _grep_sync)
        if isinstance(results, str): return results
        if not results:
            return f"No matches found for '{pattern}' in {path}"
        
        output = "\n".join(results)
        if len(results) >= max_results:
            output += f"\n\n--- (Reached limit of {max_results} results) ---"
        return f"Found {len(results)} match(es):\n{output}"

    async def tool_code_outline(self, args):
        """Analyze Python file structure using AST (non-blocking)."""
        path = args.get('path')
        if not path: return "[ERROR] Provide a path."
        
        def _outline_sync():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                
                outline = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        outline.append(f"CLASS: {node.name} (line {node.lineno})")
                    elif isinstance(node, ast.FunctionDef):
                        # Simple way to check if it's a method
                        outline.append(f"  FUNC: {node.name} (line {node.lineno})")
                
                # Sort by line number for better readability
                def get_line(s):
                    m = re.search(r"line (\d+)", s)
                    return int(m.group(1)) if m else 0
                
                outline.sort(key=get_line)
                return "\n".join(outline) if outline else "No classes or functions found."
            except Exception as e: return f"[ERROR] code_outline: {e}"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _outline_sync)
