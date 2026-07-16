#!/usr/bin/env python3
"""
   ██████   █████  ██       █████   ██████ ████████ ██  ██████
  ██       ██   ██ ██      ██   ██ ██         ██    ██ ██
  ██   ███ ███████ ██      ███████ ██         ██    ██ ██
  ██    ██ ██   ██ ██      ██   ██ ██         ██    ██ ██
   ██████  ██   ██ ███████ ██   ██  ██████    ██    ██  ██████   A I

Galactic AI — Installer
=======================

Interactive, feature-aware installer. Pick only what you want:

    python install.py                  # guided (recommended)
    python install.py --profile lite   # fast, ~120 MB, chat + Control Deck
    python install.py --profile full   # everything, ~4 GB
    python install.py --add memory     # add a feature to an existing install
    python install.py --repair         # reinstall what's missing
    python install.py --list           # show features and what's installed
    python install.py --dry-run        # show the plan, install nothing

Runs on Windows, macOS, and Linux. Python 3.9+.
"""

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
REQ_DIR = os.path.join(ROOT, 'requirements')
MANIFEST = os.path.join(ROOT, '.install_manifest.json')
MIN_PY = (3, 9)

try:
    from version import VERSION
except Exception:
    VERSION = '2.1.0'


# ── Feature catalogue ────────────────────────────────────────────────────────
# probe = an import name we can check to see if the group is already present.

FEATURES = [
    {
        'key': 'memory', 'name': 'Semantic Memory', 'icon': '🧠', 'size_mb': 2500,
        'size_mb_cpu': 800,
        'probe': ['chromadb', 'sentence_transformers'],
        'what': 'Recall by meaning, not just keywords',
        'why': ('Ask "what did I say about my truck?" and it finds "1966 F100".\n'
                'Also powers search_codebase (semantic search of your own code).\n'
                'Without it you still get persistent KEYWORD memory.'),
        'lite': False,
    },
    {
        'key': 'voice-tts', 'name': 'Voice Output (TTS)', 'icon': '🔊', 'size_mb': 40,
        'probe': ['edge_tts'],
        'what': 'The AI talks back, out loud',
        'why': ('Free Microsoft neural voices — no API key needed.\n'
                'ElevenLabs / Fish Speech voice cloning also supported.'),
        'lite': True,
    },
    {
        'key': 'voice-stt', 'name': 'Voice Input (STT)', 'icon': '🎙️', 'size_mb': 150,
        'probe': ['faster_whisper', 'speech_recognition'],
        'what': 'Talk to it; wake-word listening',
        'why': ('Transcribes LOCALLY — your voice never leaves this machine.\n'
                'Say "Computer" / your wake word to trigger it hands-free.\n'
                'Needs a microphone. Downloads a ~150 MB model on first use.'),
        'lite': False,
    },
    {
        'key': 'browser', 'name': 'Web Browsing', 'icon': '🌐', 'size_mb': 160,
        'probe': ['playwright'],
        'what': 'Autonomous web research & automation',
        'why': ('The AI navigates sites, clicks, types, and scrapes on its own.\n'
                'Includes the Chromium engine download (~150 MB).'),
        'lite': False,
    },
    {
        'key': 'desktop', 'name': 'Computer Control', 'icon': '🖥️', 'size_mb': 120,
        'probe': ['pyautogui'],
        'what': 'Mouse, keyboard, screenshots, windows',
        'why': ('Let the AI see your screen and drive your desktop.\n'
                'Also enables the native desktop app window.'),
        'lite': False,
    },
    {
        'key': 'documents', 'name': 'Document Reading', 'icon': '📄', 'size_mb': 90,
        'probe': ['pdfplumber', 'pandas'],
        'what': 'Read PDFs, Word, Excel, CSV',
        'why': 'Point it at real files and have it analyze or summarize them.',
        'lite': False,
    },
    {
        'key': 'bridges', 'name': 'Discord & Social', 'icon': '💬', 'size_mb': 25,
        'probe': ['discord'],
        'what': 'Chat from Discord; post to X/Reddit',
        'why': ('Telegram and Gmail bridges work on EVERY install (no extra\n'
                'packages). This adds Discord, Twitter/X, and Reddit.'),
        'lite': False,
    },
    {
        'key': 'ocr', 'name': 'Screen OCR', 'icon': '👁️', 'size_mb': 200,
        'probe': ['easyocr'],
        'what': 'Read text out of images/screenshots',
        'why': ('Adds the desktop_ocr tool.\n'
                'Heavy — pulls in torch (free if you picked Semantic Memory).'),
        'lite': False,
    },
    {
        'key': 'vertex', 'name': 'Google Vertex AI', 'icon': '☁️', 'size_mb': 120,
        'probe': ['google.cloud.aiplatform'],
        'what': 'Enterprise GCP endpoints',
        'why': 'Only if you use Vertex service accounts instead of a Gemini API key.',
        'lite': False,
    },
]
FEATURE_BY_KEY = {f['key']: f for f in FEATURES}
LITE_KEYS = [f['key'] for f in FEATURES if f['lite']]
FULL_KEYS = [f['key'] for f in FEATURES if f['key'] != 'vertex']  # vertex is niche


# ── Terminal styling ─────────────────────────────────────────────────────────

class C:
    on = True
    @staticmethod
    def _w(code, s):
        return f"\033[{code}m{s}\033[0m" if C.on else s
    @staticmethod
    def cyan(s):   return C._w('96', s)
    @staticmethod
    def mag(s):    return C._w('95', s)
    @staticmethod
    def green(s):  return C._w('92', s)
    @staticmethod
    def yellow(s): return C._w('93', s)
    @staticmethod
    def red(s):    return C._w('91', s)
    @staticmethod
    def dim(s):    return C._w('90', s)
    @staticmethod
    def bold(s):   return C._w('1', s)


def _enable_ansi():
    """Windows 10+ needs VT processing turned on for colour."""
    if os.name != 'nt':
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
        return True
    except Exception:
        return False


def banner():
    print()
    print(C.cyan("  ╔═══════════════════════════════════════════════════════════════╗"))
    print(C.cyan("  ║") + C.bold(C.mag("   ⬡  G A L A C T I C   A I   —   I N S T A L L E R           ")) + C.cyan("║"))
    print(C.cyan("  ║") + C.dim(f"      Local-first AI automation suite  ·  v{VERSION}".ljust(63)) + C.cyan("║"))
    print(C.cyan("  ╚═══════════════════════════════════════════════════════════════╝"))
    print()


def hr(label=''):
    line = '─' * 65
    if label:
        print(C.dim(f"  ── {label} " + '─' * max(0, 60 - len(label))))
    else:
        print(C.dim('  ' + line))


def fmt_size(mb):
    return f"{mb/1000:.1f} GB" if mb >= 1000 else f"{mb} MB"


# ── Environment probing ──────────────────────────────────────────────────────

def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def feature_installed(feat):
    return all(has_module(p) for p in feat['probe'])


def detect_gpu():
    """(has_nvidia, description). Used to pick CUDA vs CPU torch."""
    if shutil.which('nvidia-smi'):
        try:
            out = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return True, out.stdout.strip().splitlines()[0].strip()
        except Exception:
            pass
    return False, 'no NVIDIA GPU detected'


def detect_ollama():
    """(installed, n_models)."""
    if not shutil.which('ollama'):
        return False, 0
    try:
        out = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            lines = [l for l in out.stdout.strip().splitlines()[1:] if l.strip()]
            return True, len(lines)
    except Exception:
        pass
    return True, 0


# ── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest():
    try:
        with open(MANIFEST, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_manifest(keys, gpu_mode):
    try:
        with open(MANIFEST, 'w', encoding='utf-8') as f:
            json.dump({
                'version': VERSION,
                'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'features': sorted(set(keys)),
                'torch': gpu_mode,
                'python': sys.version.split()[0],
                'platform': platform.platform(),
            }, f, indent=2)
    except Exception:
        pass


# ── Interactive UI ───────────────────────────────────────────────────────────

def ask(prompt, default=''):
    try:
        return input(prompt).strip() or default
    except (EOFError, KeyboardInterrupt):
        print('\n' + C.yellow('  Cancelled.'))
        sys.exit(130)


def choose_profile():
    hr('CHOOSE YOUR INSTALL')
    print()
    lite_mb = sum(FEATURE_BY_KEY[k]['size_mb'] for k in LITE_KEYS) + 120
    full_mb = sum(f['size_mb'] for f in FEATURES if f['key'] in FULL_KEYS) + 120
    print(f"  {C.bold('1)')} {C.green('LITE')}      {C.dim('~' + fmt_size(lite_mb) + '  ·  ~2 min')}")
    print(C.dim("     Chat + Control Deck + all 14 AI providers + voice output."))
    print(C.dim("     Keyword memory. No heavy ML. Great on a laptop."))
    print()
    print(f"  {C.bold('2)')} {C.cyan('FULL')}      {C.dim('~' + fmt_size(full_mb) + '  ·  10-20 min')}")
    print(C.dim("     Everything: semantic memory, voice in/out, browsing,"))
    print(C.dim("     computer control, documents, Discord, OCR."))
    print()
    print(f"  {C.bold('3)')} {C.mag('CUSTOM')}    {C.dim('pick feature by feature')}")
    print()
    while True:
        c = ask(f"  Choose {C.dim('[1/2/3]')} (default 1): ", '1')
        if c in ('1', 'lite'):   return 'lite', list(LITE_KEYS)
        if c in ('2', 'full'):   return 'full', list(FULL_KEYS)
        if c in ('3', 'custom'): return 'custom', None
        print(C.red("  Please enter 1, 2, or 3."))


def choose_custom(preselected=None):
    """Checkbox-style picker. Toggle by number, Enter to confirm."""
    sel = set(preselected or LITE_KEYS)
    while True:
        print()
        hr('CUSTOM — toggle features by number, ENTER when done')
        print()
        print(C.dim("     CORE (always installed): chat, Control Deck, 14 providers,"))
        print(C.dim("     scheduler, Telegram + Gmail bridges, keyword memory."))
        print()
        for i, f in enumerate(FEATURES, 1):
            on = f['key'] in sel
            box = C.green('[✓]') if on else C.dim('[ ]')
            already = C.dim(' (already installed)') if feature_installed(f) else ''
            name = f"{f['icon']}  {f['name']}"
            print(f"   {box} {C.bold(str(i))}. {name}{already}")
            print(f"       {C.dim(f['what'])}  {C.dim('·')}  {C.dim('~' + fmt_size(f['size_mb']))}")
        total = sum(FEATURE_BY_KEY[k]['size_mb'] for k in sel) + 120
        print()
        print(f"   {C.bold('Selected:')} {len(sel)} feature(s)   {C.bold('Est. download:')} {C.cyan('~' + fmt_size(total))}")
        print(C.dim("   Commands: <number> toggle · 'a' all · 'n' none · '?<number>' details · ENTER done"))
        raw = ask("   > ")
        if not raw:
            return sorted(sel)
        if raw.lower() == 'a':
            sel = set(f['key'] for f in FEATURES); continue
        if raw.lower() == 'n':
            sel = set(); continue
        if raw.startswith('?'):
            try:
                f = FEATURES[int(raw[1:]) - 1]
                print()
                print(f"   {f['icon']}  {C.bold(f['name'])}  {C.dim('~' + fmt_size(f['size_mb']))}")
                for line in f['why'].split('\n'):
                    print(f"      {line}")
                ask(C.dim("      (enter to go back) "))
            except (ValueError, IndexError):
                print(C.red("   Unknown feature number."))
            continue
        for tok in raw.replace(',', ' ').split():
            try:
                k = FEATURES[int(tok) - 1]['key']
                sel.discard(k) if k in sel else sel.add(k)
            except (ValueError, IndexError):
                print(C.red(f"   Ignoring '{tok}'"))


# ── Install steps ────────────────────────────────────────────────────────────

def pip_install(args, dry_run=False, label=''):
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check'] + args
    if dry_run:
        print(C.dim(f"      DRY RUN: {' '.join(cmd)}"))
        return True
    try:
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(C.red(f"      ✗ pip failed for {label or ' '.join(args)}"))
            return False
        return True
    except Exception as e:
        print(C.red(f"      ✗ {e}"))
        return False


def install_torch(use_cuda, dry_run=False):
    """torch is the single biggest download; CPU-only saves ~2 GB."""
    if has_module('torch'):
        print(C.green("      ✓ torch already installed"))
        return True
    if use_cuda:
        print(C.dim("      Installing torch with CUDA support (large)…"))
        return pip_install(['torch'], dry_run, 'torch (cuda)')
    print(C.dim("      Installing CPU-only torch (saves ~2 GB)…"))
    return pip_install(['torch', '--index-url', 'https://download.pytorch.org/whl/cpu'],
                       dry_run, 'torch (cpu)')


def run_install(keys, use_cuda, dry_run=False):
    ok, failed = [], []

    hr('INSTALLING')
    print()
    print(C.bold("  [1] Core") + C.dim("  — chat, Control Deck, providers, scheduler"))
    if pip_install(['-r', os.path.join(REQ_DIR, 'core.txt')], dry_run, 'core'):
        print(C.green("      ✓ core installed"))
    else:
        print(C.red("      ✗ CORE FAILED — Galactic AI will not run. Check your connection."))
        return [], ['core']

    step = 2
    for key in keys:
        f = FEATURE_BY_KEY[key]
        print()
        print(C.bold(f"  [{step}] {f['icon']} {f['name']}") + C.dim(f"  — {f['what']}"))
        step += 1

        if key == 'memory' and not install_torch(use_cuda, dry_run):
            failed.append(key); print(C.red("      ✗ torch failed")); continue

        req = os.path.join(REQ_DIR, f"{key}.txt")
        if not os.path.exists(req):
            print(C.red(f"      ✗ missing {req}")); failed.append(key); continue
        if not pip_install(['-r', req], dry_run, key):
            failed.append(key); continue

        # Post-install extras
        if key == 'browser' and not dry_run:
            print(C.dim("      Downloading Chromium engine…"))
            try:
                subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'])
            except Exception as e:
                print(C.yellow(f"      ⚠ Chromium download failed ({e}). Run later: playwright install chromium"))

        print(C.green(f"      ✓ {f['name']} installed"))
        ok.append(key)

    return ok, failed


def make_dirs():
    for d in ('logs', 'workspace', 'watch', 'logs/sessions'):
        try:
            os.makedirs(os.path.join(ROOT, d), exist_ok=True)
        except Exception:
            pass


def bootstrap_config():
    """Create the gitignored config.local.yaml overlay (never contains secrets
    from the repo — the user adds their own keys in the setup wizard)."""
    local = os.path.join(ROOT, 'config.local.yaml')
    if os.path.exists(local):
        print(C.green("      ✓ config.local.yaml already present (left untouched)"))
        return
    try:
        with open(local, 'w', encoding='utf-8') as f:
            f.write(
                "# Galactic AI — YOUR local settings and secrets.\n"
                "# This file is gitignored and overrides config.yaml (the tracked template).\n"
                "# Add API keys here, or use the Setup Wizard in the Control Deck.\n\n"
                "system:\n"
                f"  version: {VERSION}\n\n"
                "# providers:\n"
                "#   openrouter:\n"
                "#     apiKey: sk-or-v1-...\n\n"
                "# costs:\n"
                "#   daily_budget: 5.00      # advisory spend alerts (0 = off)\n"
                "#   monthly_budget: 50.00\n"
            )
        print(C.green("      ✓ created config.local.yaml (your private settings file)"))
    except Exception as e:
        print(C.yellow(f"      ⚠ could not create config.local.yaml: {e}"))


def verify(keys):
    hr('VERIFYING')
    print()
    all_ok = True
    core_mods = [('aiohttp', 'web server'), ('yaml', 'config'), ('openai', 'provider SDK')]
    for mod, what in core_mods:
        good = has_module(mod)
        all_ok &= good
        print(f"   {C.green('✓') if good else C.red('✗')} core: {mod} {C.dim('(' + what + ')')}")
    for key in keys:
        f = FEATURE_BY_KEY[key]
        good = feature_installed(f)
        all_ok &= good
        print(f"   {C.green('✓') if good else C.red('✗')} {f['icon']} {f['name']}")
    return all_ok


def next_steps(keys, ollama_installed, ollama_models):
    print()
    hr('READY')
    print()
    print(C.bold("  Start Galactic AI:"))
    print(C.cyan("      python galactic_core_v2.py"))
    print()
    print(C.bold("  Then open the Control Deck:"))
    print(C.cyan("      http://127.0.0.1:17789"))
    print()
    print(C.dim("  First run walks you through API keys in the Setup Wizard."))
    print(C.dim("  Press Ctrl+K in the deck for the command palette."))
    print()
    if not ollama_installed:
        print(C.bold("  💡 Want it 100% free & offline?"))
        print(C.dim("      1. Install Ollama:  https://ollama.com/download"))
        print(C.dim("      2. ollama pull qwen3:8b"))
        print(C.dim("      No API keys, no cloud, nothing leaves your machine."))
    elif ollama_models == 0:
        print(C.bold("  💡 Ollama is installed but has no models yet:"))
        print(C.dim("      ollama pull qwen3:8b"))
    else:
        print(C.green(f"  ✓ Ollama ready with {ollama_models} model(s) — you can run fully offline."))
    if 'memory' not in keys:
        print()
        print(C.dim("  Note: running with KEYWORD memory. For semantic recall:"))
        print(C.dim("      python install.py --add memory"))
    print()


def cmd_list():
    banner()
    man = load_manifest()
    hr('FEATURES')
    print()
    print(C.dim("   CORE is always installed: chat, Control Deck, 14 providers,"))
    print(C.dim("   scheduler, Telegram + Gmail bridges, keyword memory."))
    print()
    for f in FEATURES:
        inst = feature_installed(f)
        mark = C.green('✓ installed') if inst else C.dim('· not installed')
        print(f"   {f['icon']}  {C.bold(f['name']):<28} {mark}")
        print(f"       {C.dim(f['key'] + '  ·  ~' + fmt_size(f['size_mb']) + '  ·  ' + f['what'])}")
    if man:
        print()
        print(C.dim(f"   Last install: v{man.get('version')} on {man.get('installed_at')} "
                    f"(torch: {man.get('torch', 'n/a')})"))
    print()
    print(C.dim("   Add one:  python install.py --add <key>"))
    print()


def main():
    p = argparse.ArgumentParser(add_help=True, description='Galactic AI installer')
    p.add_argument('--profile', choices=['lite', 'full', 'custom'], help='non-interactive profile')
    p.add_argument('--add', metavar='FEATURE', nargs='+', help='add feature(s) to an existing install')
    p.add_argument('--repair', action='store_true', help='reinstall anything missing')
    p.add_argument('--list', action='store_true', help='list features and status')
    p.add_argument('--dry-run', action='store_true', help='show the plan without installing')
    p.add_argument('--yes', '-y', action='store_true', help='no prompts (use with --profile)')
    p.add_argument('--cpu', action='store_true', help='force CPU-only torch')
    p.add_argument('--no-color', action='store_true')
    args = p.parse_args()

    C.on = _enable_ansi() and not args.no_color and sys.stdout.isatty()

    if sys.version_info < MIN_PY:
        print(f"Galactic AI needs Python {MIN_PY[0]}.{MIN_PY[1]}+ — you have {sys.version.split()[0]}")
        sys.exit(1)

    if args.list:
        cmd_list(); return

    banner()

    # ── Environment report ──
    hr('ENVIRONMENT')
    print()
    print(f"   {C.green('✓')} Python {sys.version.split()[0]}  {C.dim('(' + platform.system() + ' ' + platform.machine() + ')')}")
    has_gpu, gpu_name = detect_gpu()
    print(f"   {C.green('✓') if has_gpu else C.dim('·')} GPU: {gpu_name}")
    ollama_installed, ollama_models = detect_ollama()
    print(f"   {C.green('✓') if ollama_installed else C.dim('·')} Ollama: "
          + (f"installed, {ollama_models} model(s)" if ollama_installed else 'not installed (optional)'))
    existing = [f['key'] for f in FEATURES if feature_installed(f)]
    if existing:
        print(f"   {C.cyan('↻')} Existing install detected: {', '.join(existing)}")
    print()

    use_cuda = has_gpu and not args.cpu

    # ── Decide what to install ──
    if args.add:
        unknown = [k for k in args.add if k not in FEATURE_BY_KEY]
        if unknown:
            print(C.red(f"  Unknown feature(s): {', '.join(unknown)}"))
            print(C.dim(f"  Available: {', '.join(FEATURE_BY_KEY)}"))
            sys.exit(1)
        keys, profile = list(args.add), 'add'
    elif args.repair:
        keys = [k for k in (load_manifest().get('features') or existing or LITE_KEYS)
                if not feature_installed(FEATURE_BY_KEY[k])]
        profile = 'repair'
        if not keys:
            print(C.green("  Nothing to repair — every recorded feature is present."))
            print(C.dim("  (Reinstall core anyway with: python install.py --profile lite)"))
            return
        print(C.yellow(f"  Repairing: {', '.join(keys)}"))
    elif args.profile == 'lite':
        keys, profile = list(LITE_KEYS), 'lite'
    elif args.profile == 'full':
        keys, profile = list(FULL_KEYS), 'full'
    elif args.profile == 'custom':
        keys, profile = choose_custom(existing or LITE_KEYS), 'custom'
    else:
        profile, keys = choose_profile()
        if keys is None:
            keys = choose_custom(existing or LITE_KEYS)

    # ── Plan + confirm ──
    est = sum(FEATURE_BY_KEY[k]['size_mb'] for k in keys) + (120 if profile != 'add' else 0)
    if 'memory' in keys and not use_cuda:
        est -= (FEATURE_BY_KEY['memory']['size_mb'] - FEATURE_BY_KEY['memory']['size_mb_cpu'])
    print()
    hr('PLAN')
    print()
    print(f"   Profile        : {C.bold(profile.upper())}")
    print(f"   Features       : {', '.join(keys) if keys else C.dim('core only')}")
    print(f"   torch build    : {'CUDA (GPU)' if use_cuda and 'memory' in keys else ('CPU-only' if 'memory' in keys else C.dim('n/a'))}")
    print(f"   Est. download  : {C.cyan('~' + fmt_size(est))}")
    print(f"   Install to     : {C.dim(ROOT)}")
    print()
    if not args.yes and not args.dry_run:
        if ask(f"   Proceed? {C.dim('[Y/n]')} ", 'y').lower() not in ('y', 'yes', ''):
            print(C.yellow("   Cancelled — nothing was installed."))
            return

    print()
    t0 = time.time()
    ok, failed = run_install(keys, use_cuda, args.dry_run)

    if args.dry_run:
        print()
        print(C.yellow("   DRY RUN — nothing was installed."))
        return

    print()
    print(C.bold("  [*] Workspace & config"))
    make_dirs()
    print(C.green("      ✓ created logs/, workspace/, watch/"))
    bootstrap_config()

    print()
    healthy = verify(ok if profile == 'add' else keys)

    mins = (time.time() - t0) / 60
    print()
    if failed:
        print(C.yellow(f"  ⚠ Finished in {mins:.1f} min with {len(failed)} failed feature(s): {', '.join(failed)}"))
        print(C.dim("     Retry just those:  python install.py --add " + ' '.join(failed)))
    elif healthy:
        print(C.green(f"  ✓ Installation complete in {mins:.1f} min — everything verified."))
    else:
        print(C.yellow(f"  ⚠ Installed in {mins:.1f} min, but verification found gaps. Try: python install.py --repair"))

    merged = sorted(set((load_manifest().get('features') or []) + ok)) if profile == 'add' else sorted(set(ok))
    save_manifest(merged, 'cuda' if use_cuda else 'cpu')
    next_steps(merged, ollama_installed, ollama_models)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n' + C.yellow('  Cancelled.'))
        sys.exit(130)
