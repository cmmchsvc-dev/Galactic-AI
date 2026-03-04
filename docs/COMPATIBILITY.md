# Galactic AI — Cross-Platform Compatibility Guide

This document outlines the feature parity and setup requirements for Galactic AI across Windows, macOS, and Linux.

## 📊 Feature Comparison

| Feature | Windows | macOS | Linux (X11) | Linux (Wayland) |
| :--- | :---: | :---: | :---: | :---: |
| **Core AI Engine** (Local/Cloud) | ✅ | ✅ | ✅ | ✅ |
| **Web Browser Automation** (Playwright) | ✅ | ✅ | ✅ | ✅ |
| **Desktop Screenshots** | ✅ | ✅¹ | ✅² | ⚠️³ |
| **Mouse/Keyboard Control** | ✅ | ✅¹ | ✅² | ⚠️³ |
| **Window Management** | ✅ | ❌ | ✅² | ❌ |
| **Clipboard Read/Write** | ✅ | ✅ | ✅² | ⚠️ |
| **Desktop Notifications** | ✅ | ✅ | ✅² | ✅² |
| **Voice / TTS Playback** | ✅ | ✅ | ✅ | ✅ |

---

## 🍎 macOS Setup (Specifics)

### 1. Permissions (CRITICAL)
For **Desktop Tools** (screenshots, mouse, keyboard) to work, you must grant permissions to your terminal (e.g., Terminal.app, iTerm2) or Python executable:
- **System Settings** > **Privacy & Security** > **Accessibility**
- **System Settings** > **Privacy & Security** > **Screen Recording**

### 2. Limitations
- **Window Management**: `window_list`, `window_focus`, and `window_resize` are currently **Windows-only**. Desktop automation on Mac relies primarily on coordinate-based clicking and visual recognition.

---

## 🐧 Linux Setup (Specifics)

### 1. System Dependencies
Linux requires several system-level utilities that aren't included in Python's `pip`. Run the following to enable full desktop support:

**Ubuntu / Debian / Mint:**
```bash
sudo apt update
sudo apt install xclip wmctrl libnotify-bin
```

**Fedora:**
```bash
sudo dnf install xclip wmctrl libnotify
```

### 2. Wayland vs. X11
Galactic AI's desktop automation (`pyautogui`) currently performs best on **X11**.
- **Wayland Support**: Most desktop tools (clicking/typing) will fail on Wayland due to security restrictions. If you are on a modern distro (like Ubuntu 22.04+), you may need to switch to an "Ubuntu on Xorg" session at the login screen.

---

## 🛠️ Diagnostic Tool
You can verify your environment at any time by running:
```bash
python scripts/diagnostic.py
```

---
¹ Requires Accessibility & Screen Recording permissions.  
² Requires `xclip`, `wmctrl`, and `notify-send`.  
³ Limited support on Wayland; X11 session recommended.
