#!/usr/bin/env bash
# Galactic AI - Linux / macOS Installer
# Run: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "============================================"
echo "  GALACTIC AI - Automation Suite Installer"
echo "  v1.4.8"
echo "============================================"
# Determine OS
OS_TYPE=$(uname -s | tr '[:upper:]' '[:lower:]')

# [Step 0/5] Install System Prerequisites
echo "[0/5] Checking System Prerequisites..."
if [[ "$OS_TYPE" == "linux" ]]; then
    if command -v apt-get &>/dev/null; then
        echo "  Detected Debian/Ubuntu (apt). Installing dependencies..."
        sudo apt-get update -y && sudo apt-get install -y xclip wmctrl libnotify-bin
    elif command -v dnf &>/dev/null; then
        echo "  Detected Fedora/RHEL (dnf). Installing dependencies..."
        sudo dnf install -y xclip wmctrl libnotify
    elif command -v pacman &>/dev/null; then
        echo "  Detected Arch Linux (pacman). Installing dependencies..."
        sudo pacman -S --noconfirm xclip wmctrl libnotify
    else
        echo "  WARNING: Unknown package manager. Please manually install: xclip, wmctrl, libnotify"
    fi
elif [[ "$OS_TYPE" == "darwin" ]]; then
    echo "  Detected macOS."
    if command -v brew &>/dev/null; then
        echo "  Homebrew found. Ensuring wmctrl is installed..."
        brew install wmctrl || echo "  (Optional) wmctrl install failed. Window management may be limited."
    else
        echo "  Homebrew not found. Skipping optional system tools."
    fi
fi
echo "  System prerequisites handled."
echo ""

# Check Python
echo "[1/5] Checking Python..."
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "  ERROR: Python not found. Install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi
echo "  Found: $($PYTHON --version)"

# Upgrade pip
echo "[2/5] Upgrading pip..."
$PYTHON -m pip install --upgrade pip --quiet
echo "  pip upgraded."

# Install pip dependencies from requirements.txt
echo "[3/5] Installing Python dependencies (this may take a few minutes)..."
$PYTHON -m pip install -r requirements.txt
echo "  Dependencies installed."

# Install Playwright browser
echo "[4/5] Installing Chromium browser engine..."
$PYTHON -m playwright install chromium || echo "  WARNING: Playwright browser install failed. Browser tools will not work."
echo "  Chromium installed."

# Create workspace directories
echo "[5/5] Creating workspace directories..."
mkdir -p logs workspace watch memory
echo "  Directories created."

# Platform-specific dependency checks
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo ""
    echo "--- Linux System Dependency Check ---"
    MISSING=()
    command -v xclip >/dev/null 2>&1 || MISSING+=("xclip")
    command -v wmctrl >/dev/null 2>&1 || MISSING+=("wmctrl")
    command -v notify-send >/dev/null 2>&1 || MISSING+=("libnotify-bin")

    if [ ${#MISSING[@]} -ne 0 ]; then
        echo "  WARNING: Missing system tools for desktop automation: ${MISSING[*]}"
        echo "  Run: sudo apt update && sudo apt install xclip wmctrl libnotify-bin"
    else
        echo "  All system dependencies found."
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo ""
    echo "--- macOS System Note ---"
    echo "  NOTE: Desktop screenshots/control require 'Accessibility' and"
    echo "  'Screen Recording' permissions in System Settings for your terminal."
fi

# Make launch script executable
chmod +x launch.sh 2>/dev/null || true
chmod +x scripts/diagnostic.py 2>/dev/null || true

echo ""
echo "============================================"
echo "  Installation complete!"
echo "  Run 'python3 scripts/diagnostic.py' to verify setup."
echo "============================================"
echo ""
echo "  To start Galactic AI:"
echo "    ./launch.sh"
echo ""
echo "  Then open your browser to:"
echo "    http://127.0.0.1:17789"
echo ""
echo "  The setup wizard will guide you through configuring"
echo "  API keys for 14+ AI providers."
echo ""
echo "  (Optional) For local AI with no API keys:"
echo "    1. Install Ollama: https://ollama.com/download"
echo "    2. ollama pull qwen3:8b"
echo ""
