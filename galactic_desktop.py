import os
import sys
import time
import subprocess
import urllib.request
import urllib.parse
import webview
import yaml

PORT = 17789
URL = f"http://127.0.0.1:{PORT}"
SERVER_PROCESS = None

def get_desktop_token():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # Live values are in the gitignored overlay; config.yaml is the template.
        for name in ("config.local.yaml", "config.yaml"):
            config_path = os.path.join(base_dir, name)
            if not os.path.exists(config_path):
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            hash_val = cfg.get("web", {}).get("password_hash", "")
            if hash_val:
                return f"?dt={urllib.parse.quote(hash_val)}"
    except Exception:
        pass
    return ""


def is_server_running():
    try:
        response = urllib.request.urlopen(f"{URL}/api/status", timeout=1)
        return response.getcode() == 200
    except Exception:
        return False

def start_server():
    global SERVER_PROCESS
    if is_server_running():
        print("[Desktop] Galactic AI is already running.")
        return False
        
    print("[Desktop] Starting Galactic AI background core...")
    # Get the path to launcher_desktop.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    launcher_path = os.path.join(base_dir, "launcher_desktop.py")
    
    # Run silently, discarding stdout/stderr to avoid popping up a console if run via pythonw
    SERVER_PROCESS = subprocess.Popen(
        [sys.executable, launcher_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    
    # Wait for the server to spin up
    max_retries = 30
    for i in range(max_retries):
        if is_server_running():
            print("[Desktop] Server is up!")
            return True
        time.sleep(0.5)
        
    print("[Desktop] Warning: Server did not respond in time, launching UI anyway.")
    return True

def on_closed():
    global SERVER_PROCESS
    if SERVER_PROCESS:
        print("[Desktop] Shutting down background core...")
        SERVER_PROCESS.terminate()
        try:
            SERVER_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            SERVER_PROCESS.kill()
        print("[Desktop] Shutdown complete.")

if __name__ == '__main__':
    # Try to start the server if it's not already running
    spawned_server = start_server()
    
    # Create the native desktop window
    # We use a sleek dark theme window, loading the local URL
    window = webview.create_window(
        title="Galactic AI",
        url=f"{URL}{get_desktop_token()}",
        width=1280,
        height=800,
        min_size=(800, 600),
        background_color="#0d1117" # Dark background matching Web Deck
    )
    
    # Attach the close event
    window.events.closed += on_closed
    
    # Start the desktop app loop
    webview.start(private_mode=False, gui='edgechromium')
