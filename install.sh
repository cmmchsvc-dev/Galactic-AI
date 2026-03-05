#!/usr/bin/env bash
# Galactic AI - Linux / macOS Installer
# Run: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "============================================"
echo "  GALACTIC AI - Automation Suite Installer"
echo "  v1.5.1"
echo "============================================"
# Determine OS
OS_TYPE=$(uname -s | tr '[:upper:]' '[:lower:]')

# [Step 0/6] Install System Prerequisites
echo "[0/6] Checking System Prerequisites..."
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
echo "[1/6] Checking Python..."
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "  Python not found. Attempting automatic installation..."
    if [[ "$OS_TYPE" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3 python3-pip python3-venv
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3 python3-pip
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm python python-pip
        else
            echo "  ERROR: Cannot auto-install Python. Install Python 3.10+ manually."
            exit 1
        fi
    elif [[ "$OS_TYPE" == "darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install python3
        else
            echo "  ERROR: Install Homebrew first (https://brew.sh), then re-run this script."
            exit 1
        fi
    fi
    # Re-check after install
    if command -v python3 &>/dev/null; then
        PYTHON=python3
    else
        echo "  ERROR: Python installation failed. Install Python 3.10+ from https://www.python.org/downloads/"
        exit 1
    fi
fi
echo "  Found: $($PYTHON --version)"

# [1.5/6] Ensure pip is available
echo "[2/6] Checking pip..."
if ! $PYTHON -m pip --version &>/dev/null; then
    echo "  pip not found. Installing pip..."
    if [[ "$OS_TYPE" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-pip python3-venv
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3-pip
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm python-pip
        else
            echo "  Trying ensurepip fallback..."
            $PYTHON -m ensurepip --upgrade || {
                echo "  ERROR: Could not install pip. Run: sudo apt install python3-pip"
                exit 1
            }
        fi
    elif [[ "$OS_TYPE" == "darwin" ]]; then
        $PYTHON -m ensurepip --upgrade || {
            echo "  ERROR: Could not install pip."
            exit 1
        }
    fi
    # Verify pip is now available
    if ! $PYTHON -m pip --version &>/dev/null; then
        echo "  ERROR: pip installation failed. Install manually: sudo apt install python3-pip"
        exit 1
    fi
fi
echo "  Found: $($PYTHON -m pip --version)"

# Upgrade pip
echo "[3/6] Upgrading pip..."
$PYTHON -m pip install --upgrade pip --quiet
echo "  pip upgraded."

# Install pip dependencies from requirements.txt
echo "[4/6] Installing Python dependencies (this may take a few minutes)..."
$PYTHON -m pip install -r requirements.txt
echo "  Dependencies installed."

# Install Playwright browser
echo "[5/6] Installing Chromium browser engine..."
$PYTHON -m playwright install chromium || echo "  WARNING: Playwright browser install failed. Browser tools will not work."
echo "  Chromium installed."

# Create workspace directories
echo "[6/6] Creating workspace directories..."
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
