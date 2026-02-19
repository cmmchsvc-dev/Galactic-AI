#!/bin/bash
# Galactic AI - Chromebook Installation Script
# Requires: Linux (Crostini) enabled on Chromebook

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         Galactic AI v0.6.0 - Chromebook Setup            ║"
echo "╚═══════════════════════════════════════════════════════════╝"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install with: sudo apt install python3 python3-pip"
    exit 1
fi

echo "✓ Python found: $(python3 --version)"

# Create virtual environment (recommended)
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
echo "🌐 Installing Playwright browsers..."
playwright install chromium

# Check config
if [ ! -f "config.yaml" ]; then
    echo "⚠️  config.yaml not found. Copy from example or create new."
    if [ -f "config.example.yaml" ]; then
        cp config.example.yaml config.yaml
        echo "✓ Created config.yaml from example"
    fi
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                  Installation Complete!                   ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "To run Galactic AI:"
echo "  source venv/bin/activate"
echo "  python galactic_core_v2.py"
echo ""
echo "Control Deck: http://127.0.0.1:17789"
echo ""
