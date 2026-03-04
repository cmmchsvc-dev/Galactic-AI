#!/usr/bin/env python3
"""
Galactic AI - Environment Diagnostic Tool
Verifies system dependencies and platform-specific capabilities.
"""
import sys
import os
import platform
import subprocess
import shutil

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_result(label, success, message=""):
    status = f"{Colors.GREEN}[PASS]{Colors.END}" if success else f"{Colors.RED}[FAIL]{Colors.END}"
    if not success and "SKIP" in message:
        status = f"{Colors.YELLOW}[SKIP]{Colors.END}"
    print(f"  {status} {label:<25} {message}")

def check_bin(name):
    return shutil.which(name) is not None

def main():
    os_name = platform.system()
    print(f"\n{Colors.HEADER}{Colors.BOLD}=== GALACTIC AI DIAGNOSTIC ==={Colors.END}")
    print(f"OS: {os_name} ({platform.release()})")
    print(f"Python: {sys.version.split()[0]}")
    print("-" * 40)

    # 1. Check Python Dependencies
    print(f"\n{Colors.BLUE}Checking Python packages...{Colors.END}")
    packages = [
        "playwright", "pyautogui", "pygetwindow", "pyperclip", 
        "cv2", "PIL", "openai", "anthropic", "google.genai"
    ]
    for pkg in packages:
        try:
            __import__(pkg.replace('google.genai', 'google.genai')) # Simplified check
            print_result(pkg, True)
        except ImportError:
            print_result(pkg, False, f"pip install {pkg}")

    # 2. Platform Specifics
    print(f"\n{Colors.BLUE}Checking System Binaries...{Colors.END}")
    
    if os_name == "Windows":
        print_result("PowerShell", check_bin("powershell"))
    
    elif os_name == "Darwin": # macOS
        print_result("pbcopy/pbpaste", check_bin("pbcopy"))
        print_result("osascript", check_bin("osascript"))
        print(f"\n{Colors.YELLOW}NOTE: macOS requires Accessibility & Screen Recording permissions.{Colors.END}")
        print(f"See: docs/COMPATIBILITY.md")

    elif os_name == "Linux":
        xclip = check_bin("xclip")
        wmctrl = check_bin("wmctrl")
        notify = check_bin("notify-send")
        
        print_result("xclip (Clipboard)", xclip, "" if xclip else "Missing (sudo apt install xclip)")
        print_result("wmctrl (Windows)", wmctrl, "" if wmctrl else "Missing (sudo apt install wmctrl)")
        print_result("notify-send", notify, "" if notify else "Missing (sudo apt install libnotify-bin)")
        
        wayland = os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'
        if wayland:
            print(f"\n{Colors.RED}WARNING: Wayland detected.{Colors.END}")
            print("Desktop automation (clicking/typing) may fail. X11 is recommended.")
    
    # 3. Playwright check
    print(f"\n{Colors.BLUE}Checking Browser Engine...{Colors.END}")
    pw_path = os.path.expanduser("~/.cache/ms-playwright") # Typical path
    has_browsers = os.path.exists(pw_path)
    print_result("Playwright Browsers", has_browsers, "" if has_browsers else "Run: playwright install chromium")

    print(f"\n{Colors.CYAN}Review docs/COMPATIBILITY.md for full details.{Colors.END}")
    print(f"{Colors.HEADER}=============================={Colors.END}\n")

if __name__ == "__main__":
    main()
