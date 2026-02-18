#!/usr/bin/env bash
# Galactic AI - Linux / macOS Installer
# Run: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "============================================"
echo "  GALACTIC AI - Automation Suite Installer"
echo "  v0.6.0-Alpha"
echo "============================================"
echo ""

# Check Python
echo "[1/4] Checking Python..."
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "  ERROR: Python not found. Install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi
echo "  Found: $($PYTHON --version)"

# Install pip dependencies
echo "[2/4] Installing Python dependencies..."
$PYTHON -m pip install aiohttp httpx pyyaml jinja2 beautifulsoup4 playwright
echo "  Dependencies installed."

# Install Playwright browser
echo "[3/4] Installing Chromium browser engine..."
$PYTHON -m playwright install chromium || echo "  WARNING: Playwright browser install failed. Browser tools will not work."
echo "  Chromium installed."

# Create workspace directories
echo "[4/4] Creating workspace directories..."
mkdir -p logs workspace watch memory
echo "  Directories created."

# Make launch script executable
chmod +x launch.sh 2>/dev/null || true

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "  To start Galactic AI:"
echo "    ./launch.sh"
echo ""
echo "  Then open your browser to:"
echo "    http://127.0.0.1:17789"
echo ""
echo "  (Optional) For local AI with no API keys:"
echo "    1. Install Ollama: https://ollama.com/download"
echo "    2. ollama pull qwen3:8b"
echo ""
