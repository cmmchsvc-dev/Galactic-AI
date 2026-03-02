#!/usr/bin/env python3
"""Galactic AI — Standalone Desktop Launcher

Runs the full Galactic AI backend in a background thread and opens
the Control Deck inside a native window via pywebview.

When packaged with PyInstaller --windowed, sys.stdout/stderr are None.
We redirect everything to a log file so no write ever fails silently.
"""

import sys
import os

# ── Windowed-mode safety: must happen BEFORE any other import ────────────────
# PyInstaller --windowed sets sys.stdout/stderr to None on Windows.
# Any print() or logging call would crash with an AttributeError.
# Redirect to a log file so we can debug packaging issues.

_log_file = None

def _safe_io():
    """Redirect stdout/stderr to a log file when there is no console."""
    global _log_file
    if sys.stdout is None or sys.stderr is None:
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            _log_file = open(os.path.join(log_dir, 'desktop_launcher.log'), 'w', encoding='utf-8')
        except Exception:
            _log_file = open(os.devnull, 'w')
        if sys.stdout is None:
            sys.stdout = _log_file
        if sys.stderr is None:
            sys.stderr = _log_file

_safe_io()

# ── Find config.yaml and set working directory ───────────────────────────────
# The exe may be in dist/, the project root, or anywhere the user puts it.
# We search for config.yaml in multiple locations and use the first match.
_exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
_search_dirs = [
    _exe_dir,                           # Same dir as exe
    os.path.dirname(_exe_dir),          # Parent dir (exe is in dist/)
    os.getcwd(),                        # Current working directory
]

_config_path = None
for d in _search_dirs:
    candidate = os.path.join(d, 'config.yaml')
    if os.path.isfile(candidate):
        _config_path = os.path.abspath(candidate)
        os.chdir(os.path.dirname(_config_path))
        break

if _config_path is None:
    # Last resort: use exe dir (GalacticCore will create a default config)
    os.chdir(_exe_dir)
    _config_path = os.path.join(_exe_dir, 'config.yaml')

print(f"Config: {_config_path}")
print(f"Working directory: {os.getcwd()}")

# Now safe to import everything else
import webview
import threading
import asyncio
import time
import socket
import logging
import traceback

from galactic_core_v2 import GalacticCore

# ── Desktop Launcher Configuration ────────────────────────────────────────────

def run_backend(core):
    """Run the Galactic AI backend in a dedicated asyncio loop."""
    try:
        asyncio.run(core.main_loop())
    except Exception as e:
        print(f"Backend Error: {e}")
        traceback.print_exc()

def main():
    print("--- Galactic AI Desktop Launcher ---")

    # 1. Initialize Core with explicit config path
    core = GalacticCore(config_path=_config_path)

    # 2. Start Backend Thread
    backend_thread = threading.Thread(target=run_backend, args=(core,), daemon=True)
    backend_thread.start()

    # 3. Wait for Web Server
    port = core.config.get('web', {}).get('port', 17789)
    host = core.config.get('web', {}).get('host', '127.0.0.1')
    
    # Auto-login: pass the password_hash as a desktop token so the webview
    # doesn't ask for a password on every launch (pywebview has isolated localStorage)
    pw_hash = core.config.get('web', {}).get('password_hash', '')
    if pw_hash:
        url = f"http://{host}:{port}?dt={pw_hash}"
    else:
        url = f"http://{host}:{port}"

    print(f"Waiting for Control Deck at {url}...")

    max_retries = 30
    ready = False
    for i in range(max_retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not ready:
        print("Error: Backend failed to start within 30 seconds.")
        sys.exit(1)

    print("Backend ready. Launching window...")

    # 4. Launch WebView Window
    window = webview.create_window(
        'Galactic AI - Control Deck',
        url,
        width=1280,
        height=850,
        min_size=(900, 600),
        background_color='#0a0a0c',
        easy_drag=False,          # Required for text selection to work
    )

    def on_loaded():
        """Inject CSS to re-enable text selection — pywebview disables it by default."""
        try:
            window.load_css(
                '* { user-select: text !important; -webkit-user-select: text !important; }'
            )
        except Exception:
            pass

    def on_closed():
        print("Window closed. Shutting down Galactic AI...")
        if hasattr(core, 'shutdown_event') and core.loop:
            core.loop.call_soon_threadsafe(core.shutdown_event.set)
        time.sleep(2)
        print("Goodbye!")
        os._exit(0)

    window.events.loaded += on_loaded
    window.events.closed += on_closed

    # Start the GUI loop (blocking)
    webview.start(debug=False)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Last-resort error capture
        try:
            err_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'crash.log')
            with open(err_path, 'w', encoding='utf-8') as f:
                f.write(f"FATAL: {e}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        sys.exit(1)
