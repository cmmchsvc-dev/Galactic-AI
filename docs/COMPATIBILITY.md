# Galactic AI — Cross-Platform Compatibility Guide

This document outlines feature parity and setup requirements for Galactic AI across Windows, macOS, and Linux.

---

## 📊 Feature Comparison Matrix

| Feature                                  | Windows | macOS | Linux (X11) | Linux (Wayland)|
| :--------------------------------------- | :-----: | :---: | :---------: | :-------------:|
| **Core AI Engine** (Local/Cloud)         | ✅      | ✅   | ✅          | ✅            | 
| **Web Browser Automation** (Playwright)  | ✅      | ✅   | ✅          | ✅            |
| **Desktop Screenshots**                  | ✅      | ✅¹  | ✅²         | ⚠️³           |
| **Mouse/Keyboard Control**               | ✅      | ✅¹  | ✅²         | ⚠️³           |
| **Window Management**                    | ✅      | ❌   | ✅²         | ❌            |
| **Clipboard Read/Write**                 | ✅      | ✅   | ✅²         | ⚠️            |
| **Desktop Notifications**                | ✅      | ✅   | ✅²         | ✅²           |
| **Voice / TTS Playback**                 | ✅      | ✅   | ✅          | ✅            | 

**Legend:**
- ✅ Full Support
- ❌ Not Supported
- ⚠️ Experimental / Limited
- ¹ Requires Accessibility & Screen Recording permissions
- ² Requires system packages: `xclip`, `wmctrl`, `notify-send`
- ³ X11 session recommended for stability

---

## 🍎 macOS Setup (Specifics)

### 1. Permissions (CRITICAL)
For **Desktop Tools** (screenshots, mouse, keyboard) to work, you must grant permissions to your terminal (e.g., Terminal.app, iTerm2) or Python executable:
1. Open **System Settings**
2. Go to **Privacy & Security** > **Accessibility** (Add and enable your terminal)
3. Go to **Privacy & Security** > **Screen Recording** (Add and enable your terminal)

### 2. Limitations
- **Window Management**: Common tools (`window_list`, `window_focus`) are currently **Windows-only**. Desktop interaction on Mac relies on visual search and coordinate clicking.

---

## 🐧 Linux Setup (Specifics)

### 1. Install System Dependencies
Linux requires utilities not included in Python's `pip`. Run the command for your distribution:

**Ubuntu / Debian / Mint:**
```bash
sudo apt update && sudo apt install xclip wmctrl libnotify-bin
```

**Fedora / RHEL / CentOS:**
```bash
sudo dnf install xclip wmctrl libnotify
```

**Arch Linux:**
```bash
sudo pacman -S xclip wmctrl libnotify
```

### 2. Wayland vs. X11
Global desktop automation (`pyautogui`) perform best on **X11**.
- **Issue**: Wayland's security blocks remote input/capture in many cases.
- **Solution**: If tools fail, switch to an "Ubuntu on Xorg" (X11) session at the login screen.

---

## 🛠️ Diagnostic Tool
Verify your environment instantly by running:
```bash
python scripts/diagnostic.py
```
