#!/usr/bin/env bash
# Galactic AI installer bootstrap (Linux / macOS).
#
# Ensures Python 3.9+ exists, then hands off to install.py which does the real
# work (feature picking, Lite/Full/Custom, GPU detection, verification).
# All arguments pass straight through.
#
#   ./install.sh                  # guided install
#   ./install.sh --profile lite   # fast, ~160 MB
#   ./install.sh --profile full   # everything
#   ./install.sh --list           # show features

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CYAN='\033[96m'; GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; OFF='\033[0m'

echo ""
echo -e "  ${CYAN}Galactic AI - preparing installer...${OFF}"
echo ""

# ── Find a suitable Python ───────────────────────────────────────────────────
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo -e "  ${YELLOW}Python 3.9+ not found. Attempting to install...${OFF}"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv
    PY=python3
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip && PY=python3
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python python-pip && PY=python
  elif command -v brew >/dev/null 2>&1; then
    brew install python@3.11 && PY=python3
  fi
fi

if [ -z "$PY" ] || ! command -v "$PY" >/dev/null 2>&1; then
  echo -e "  ${RED}Could not find or install Python 3.9+.${OFF}"
  echo -e "  Install it, then re-run:  ${CYAN}https://www.python.org/downloads/${OFF}"
  exit 1
fi

echo -e "  ${GREEN}$($PY --version) : OK${OFF}"

# Some distros ship Python without pip
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo -e "  ${YELLOW}pip missing - bootstrapping...${OFF}"
  "$PY" -m ensurepip --upgrade 2>/dev/null || {
    echo -e "  ${RED}pip unavailable. Install python3-pip and re-run.${OFF}"; exit 1; }
fi
"$PY" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>/dev/null || true

# Audio playback (pygame/TTS) needs SDL on some minimal Linux images
if [ "$(uname -s)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
  if ! dpkg -s libsdl2-2.0-0 >/dev/null 2>&1; then
    echo -e "  ${YELLOW}Note:${OFF} if voice output fails later, install SDL + audio headers:"
    echo -e "        sudo apt-get install -y libsdl2-2.0-0 portaudio19-dev"
  fi
fi

# ── Hand off to the real installer ───────────────────────────────────────────
cd "$ROOT"
exec "$PY" install.py "$@"
