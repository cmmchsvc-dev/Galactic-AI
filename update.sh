#!/usr/bin/env bash
# Galactic AI - Linux / macOS Auto-Updater
# Pulls the latest release directly from GitHub — no manual download needed.
#
# Usage (run from your Galactic AI installation folder):
#   chmod +x update.sh && ./update.sh
#
# Pin to a specific version:
#   ./update.sh v0.7.1
#
# What is PRESERVED (never touched):
#   config.yaml         — all your API keys, passwords, Telegram settings
#   logs/               — chat history, memory cache, TTS files
#   workspace/          — your workspace files
#   watch/              — your watch folder
#   memory/             — your memory folder
#   MEMORY.md, USER.md, IDENTITY.md, SOUL.md, TOOLS.md, VAULT.md
#
# What is UPDATED (safe to overwrite):
#   All .py source files, plugins, launch scripts, requirements.txt, docs

set -e

GITHUB_REPO="cmmchsvc-dev/Galactic-AI"
GITHUB_API="https://api.github.com/repos/$GITHUB_REPO/releases"
VERSION="${1:-latest}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "============================================"
echo "  GALACTIC AI - Auto-Updater"
echo "  Pulls latest release from GitHub"
echo "============================================"
echo ""

# ── Step 1: Verify we're in a Galactic AI folder ─────────────────────────────
echo "[1/6] Verifying installation..."
if [ ! -f "$INSTALL_DIR/galactic_core_v2.py" ]; then
    echo "  ERROR: galactic_core_v2.py not found."
    echo "  Run this script from your Galactic AI installation folder."
    exit 1
fi
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    echo "  ERROR: config.yaml not found. Use install.sh for fresh installs."
    exit 1
fi

CURRENT_VERSION=$(grep 'version:' "$INSTALL_DIR/config.yaml" | head -1 | sed 's/.*version: *//' | tr -d ' \r')
echo "  Installed version : v${CURRENT_VERSION}"

# ── Step 2: Fetch latest release info from GitHub ─────────────────────────────
echo "[2/6] Checking GitHub for updates..."

# Prefer curl, fall back to wget
if command -v curl &>/dev/null; then
    FETCH_JSON() { curl -fsSL -H "User-Agent: GalacticAI-Updater" "$1"; }
    FETCH_FILE() { curl -fsSL -H "User-Agent: GalacticAI-Updater" -o "$2" "$1"; }
elif command -v wget &>/dev/null; then
    FETCH_JSON() { wget -qO- --header="User-Agent: GalacticAI-Updater" "$1"; }
    FETCH_FILE() { wget -qO "$2" --header="User-Agent: GalacticAI-Updater" "$1"; }
else
    echo "  ERROR: curl or wget is required. Install one and try again."
    exit 1
fi

if [ "$VERSION" = "latest" ]; then
    RELEASE_JSON=$(FETCH_JSON "$GITHUB_API/latest")
else
    RELEASE_JSON=$(FETCH_JSON "$GITHUB_API/tags/$VERSION")
fi

if [ -z "$RELEASE_JSON" ]; then
    echo "  ERROR: Could not reach GitHub API. Check your internet connection."
    exit 1
fi

# Parse tag name and download URL (prefer linux, fall back to universal zip)
LATEST_TAG=$(echo "$RELEASE_JSON" | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*": *"//' | tr -d '"')
LATEST_VERSION=$(echo "$LATEST_TAG" | sed 's/^v//')

echo "  Latest version    : $LATEST_TAG"

if [ "$LATEST_VERSION" = "$CURRENT_VERSION" ]; then
    echo ""
    echo "  You are already on the latest version (v$CURRENT_VERSION)."
    echo "  To force a specific version: ./update.sh v0.7.0"
    echo ""
    exit 0
fi

echo "  Update available  : v$CURRENT_VERSION -> v$LATEST_VERSION"

# Find the best asset URL: prefer linux tar.gz, then linux zip, then universal zip
DOWNLOAD_URL=$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*linux[^"]*"' | head -1 | sed 's/.*": *"//' | tr -d '"')
if [ -z "$DOWNLOAD_URL" ]; then
    DOWNLOAD_URL=$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*\.zip"' | head -1 | sed 's/.*": *"//' | tr -d '"')
fi
if [ -z "$DOWNLOAD_URL" ]; then
    echo "  ERROR: No downloadable asset found in the GitHub release."
    echo "  Visit: https://github.com/$GITHUB_REPO/releases"
    exit 1
fi

ASSET_NAME=$(basename "$DOWNLOAD_URL")
echo "  Downloading       : $ASSET_NAME"

# ── Step 3: Back up config.yaml ───────────────────────────────────────────────
echo "[3/6] Backing up your configuration..."
BACKUP_DIR="$INSTALL_DIR/logs/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
BACKUP_PATH="$BACKUP_DIR/config-backup-$TIMESTAMP.yaml"
cp "$INSTALL_DIR/config.yaml" "$BACKUP_PATH"
echo "  Backed up to: $BACKUP_PATH"

# ── Step 4: Download the archive ──────────────────────────────────────────────
echo "[4/6] Downloading update..."
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

TEMP_ARCHIVE="$TEMP_DIR/galactic-update.$([[ $ASSET_NAME == *.tar.gz ]] && echo tar.gz || echo zip)"
FETCH_FILE "$DOWNLOAD_URL" "$TEMP_ARCHIVE"
echo "  Download complete."

# ── Step 5: Apply update (skip protected files) ───────────────────────────────
echo "[5/6] Applying update..."

PROTECTED="config.yaml logs workspace watch memory MEMORY.md USER.md IDENTITY.md SOUL.md TOOLS.md VAULT.md HEARTBEAT.md"

EXTRACT_DIR="$TEMP_DIR/extracted"
mkdir -p "$EXTRACT_DIR"

if [[ "$TEMP_ARCHIVE" == *.tar.gz ]]; then
    tar -xzf "$TEMP_ARCHIVE" -C "$EXTRACT_DIR"
else
    if command -v unzip &>/dev/null; then
        unzip -q "$TEMP_ARCHIVE" -d "$EXTRACT_DIR"
    else
        python3 -c "import zipfile, sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TEMP_ARCHIVE" "$EXTRACT_DIR"
    fi
fi

# Handle nested folder inside archive (Galactic-AI-vX.X.X/)
INNER_DIR=$(find "$EXTRACT_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)
SOURCE_DIR="${INNER_DIR:-$EXTRACT_DIR}"

COPIED=0
while IFS= read -r -d '' FILE; do
    REL="${FILE#$SOURCE_DIR/}"
    TOP_LEVEL="${REL%%/*}"

    # Skip protected
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
done < <(find "$SOURCE_DIR" -type f -print0)

echo "  Updated $COPIED files."
echo "  Protected (untouched): $PROTECTED"

# Make scripts executable
chmod +x "$INSTALL_DIR/launch.sh" "$INSTALL_DIR/update.sh" 2>/dev/null || true

# ── Step 5b: Patch version in config.yaml ────────────────────────────────────
# config.yaml is protected so your API keys are never touched, but the version
# field must be updated so the splash screen and updater stay in sync.
if sed --version 2>/dev/null | grep -q 'GNU'; then
    # GNU sed (Linux)
    sed -i "s/^\(\s*version:\s*\)[0-9.]*/\1$LATEST_VERSION/" "$INSTALL_DIR/config.yaml"
else
    # BSD sed (macOS)
    sed -i '' "s/^\([[:space:]]*version:[[:space:]]*\)[0-9.]*/\1$LATEST_VERSION/" "$INSTALL_DIR/config.yaml"
fi
echo "  Version stamped    : v$LATEST_VERSION"

# ── Step 6: Update pip dependencies ───────────────────────────────────────────
echo "[6/6] Updating Python dependencies..."
if command -v python3 &>/dev/null; then PYTHON=python3; else PYTHON=python; fi
$PYTHON -m pip install -r "$INSTALL_DIR/requirements.txt" --quiet --upgrade
echo "  Dependencies up to date."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Updated to $LATEST_TAG!"
echo "============================================"
echo ""
echo "  Your config, memory, and chat history are untouched."
echo "  Config backup: $BACKUP_PATH"
echo ""
echo "  Restart Galactic AI to apply:"
echo "    ./launch.sh"
echo ""
