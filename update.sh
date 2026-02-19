#!/usr/bin/env bash
# Galactic AI - Linux / macOS Updater
# Updates code files while preserving your config, keys, memory, and chat history.
# Run from your Galactic AI installation folder: chmod +x update.sh && ./update.sh
#
# What is PRESERVED (never touched):
#   config.yaml         — all your API keys, passwords, Telegram settings
#   logs/               — chat history, memory cache, TTS files
#   workspace/          — your workspace files
#   watch/              — your watch folder
#   memory/             — your memory folder
#   ../*.md             — MEMORY.md, USER.md, IDENTITY.md, SOUL.md, TOOLS.md (one level up)
#
# What is UPDATED (safe to overwrite):
#   All .py source files, plugins, launch scripts, requirements.txt, docs

set -e

ZIP_PATH="${1:-}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "============================================"
echo "  GALACTIC AI - Updater"
echo "  Safely updates code, preserves your data"
echo "============================================"
echo ""

# ── Step 1: Verify we're in a Galactic AI folder ─────────────────────────────
echo "[1/5] Verifying installation..."
if [ ! -f "$INSTALL_DIR/galactic_core_v2.py" ]; then
    echo "  ERROR: galactic_core_v2.py not found."
    echo "  Run this script from your Galactic AI installation folder."
    exit 1
fi
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    echo "  ERROR: config.yaml not found. Is this a fresh install?"
    echo "  Use install.sh for fresh installs, not the updater."
    exit 1
fi

CURRENT_VERSION=$(grep 'version:' "$INSTALL_DIR/config.yaml" | head -1 | sed 's/.*version: *//' | tr -d ' ')
echo "  Found Galactic AI v${CURRENT_VERSION} at: $INSTALL_DIR"

# ── Step 2: Locate the update ZIP ─────────────────────────────────────────────
echo "[2/5] Locating update package..."

if [ -z "$ZIP_PATH" ]; then
    # Search common locations
    ZIP_PATH=$(find "$INSTALL_DIR" "$INSTALL_DIR/.." "$HOME/Downloads" "$HOME/Desktop" \
        -maxdepth 1 -name "Galactic-AI-v*.zip" 2>/dev/null | sort | tail -1)
fi

if [ -z "$ZIP_PATH" ] || [ ! -f "$ZIP_PATH" ]; then
    echo "  No update ZIP found automatically."
    echo "  Download the latest release ZIP and run:"
    echo "    ./update.sh /path/to/Galactic-AI-v0.7.1-linux.tar.gz"
    echo "  Or place the ZIP in your Downloads folder and run ./update.sh again."
    exit 0
fi

echo "  Using: $(basename "$ZIP_PATH")"

# ── Step 3: Back up config.yaml ───────────────────────────────────────────────
echo "[3/5] Backing up your configuration..."
BACKUP_DIR="$INSTALL_DIR/logs/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
BACKUP_PATH="$BACKUP_DIR/config-backup-$TIMESTAMP.yaml"
cp "$INSTALL_DIR/config.yaml" "$BACKUP_PATH"
echo "  config.yaml backed up to: $BACKUP_PATH"

# ── Step 4: Extract update (skipping protected files) ────────────────────────
echo "[4/5] Applying update..."

# Protected paths — never overwrite
PROTECTED="config.yaml logs workspace watch memory"

TEMP_DIR=$(mktemp -d)
trap "rm -rf '$TEMP_DIR'" EXIT

# Handle both .zip and .tar.gz
if [[ "$ZIP_PATH" == *.tar.gz ]]; then
    tar -xzf "$ZIP_PATH" -C "$TEMP_DIR"
else
    unzip -q "$ZIP_PATH" -d "$TEMP_DIR"
fi

# Find the inner folder (Galactic-AI-vX.X.X/)
INNER_DIR=$(find "$TEMP_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)
if [ -z "$INNER_DIR" ]; then
    echo "  ERROR: Could not find folder inside archive."
    exit 1
fi

COPIED=0
while IFS= read -r -d '' FILE; do
    REL="${FILE#$INNER_DIR/}"
    TOP_LEVEL="${REL%%/*}"

    # Skip protected files/folders
    SKIP=0
    for P in $PROTECTED; do
        if [ "$TOP_LEVEL" = "$P" ] || [ "$REL" = "$P" ]; then
            SKIP=1
            break
        fi
    done
    [ "$SKIP" -eq 1 ] && continue

    DEST="$INSTALL_DIR/$REL"
    mkdir -p "$(dirname "$DEST")"
    cp "$FILE" "$DEST"
    COPIED=$((COPIED + 1))
done < <(find "$INNER_DIR" -type f -print0)

echo "  Updated $COPIED files."
echo "  Skipped protected: $PROTECTED"

# ── Step 5: Update pip dependencies ───────────────────────────────────────────
echo "[5/5] Updating Python dependencies..."
if command -v python3 &>/dev/null; then PYTHON=python3; else PYTHON=python; fi
$PYTHON -m pip install -r "$INSTALL_DIR/requirements.txt" --quiet --upgrade
echo "  Dependencies up to date."

# Make scripts executable
chmod +x "$INSTALL_DIR/launch.sh" "$INSTALL_DIR/update.sh" 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Update complete!"
echo "============================================"
echo ""
echo "  Your config, memory, and chat history are untouched."
echo "  Config backup saved to: $BACKUP_PATH"
echo ""
echo "  Restart Galactic AI to apply the update:"
echo "    ./launch.sh"
echo ""
