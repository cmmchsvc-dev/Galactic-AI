"""
Galactic AI — Config Loader (secrets-safe overlay)
==================================================

config.yaml        — git-tracked TEMPLATE (placeholders only, never written by code)
config.local.yaml  — gitignored OVERLAY holding the real, live configuration
                     (API keys, tokens, tuned settings). All runtime saves land here.

Load order: config.yaml is read first, then config.local.yaml is deep-merged
over it (overlay wins). Every save writes the FULL merged config to the overlay
only, so real values can never leak back into the tracked template.

Standalone scripts (flusher.py, nvidia_gateway.py, galactic_desktop.py, the CLI)
should use load_config() too, or at minimum prefer config.local.yaml when present.
"""

import os
import secrets as _secrets

import yaml

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.yaml')
LOCAL_CONFIG_BASENAME = 'config.local.yaml'
LOCAL_CONFIG_PATH = os.path.join(CONFIG_DIR, LOCAL_CONFIG_BASENAME)


def local_path_for(base_path=None):
    """The overlay path that pairs with a given config.yaml path."""
    if not base_path:
        return LOCAL_CONFIG_PATH
    return os.path.join(os.path.dirname(os.path.abspath(base_path)), LOCAL_CONFIG_BASENAME)


# Keys where the overlay is AUTHORITATIVE — its value REPLACES the base's rather
# than deep-merging. These are user-managed collections (per-model tuning, command
# aliases): deep-merging them means the user can never DELETE an entry that also
# exists in the tracked config.yaml, because the merge keeps re-injecting it every
# load. The deck's save side already treats these as whole-value replacements, so
# load must agree or deletions silently "come back". Only applies when the overlay
# actually contains the key — otherwise the base provides it normally.
_OVERLAY_AUTHORITATIVE = {'model_overrides', 'aliases'}


def deep_merge(base, overlay):
    """Recursively merge overlay into a copy of base. Overlay values win.
    For _OVERLAY_AUTHORITATIVE keys present in the overlay, the overlay value
    replaces the base's outright (so deletions in the overlay actually stick)."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay if overlay is not None else base
    merged = dict(base)
    for key, value in overlay.items():
        if key in _OVERLAY_AUTHORITATIVE:
            merged[key] = value
        elif key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[Config] Failed to read {os.path.basename(path)}: {e}")
    return {}


def load_config(base_path=None):
    """Template + overlay, merged. Returns {} when neither file exists."""
    base_path = os.path.abspath(base_path) if base_path else CONFIG_PATH
    base = _read_yaml(base_path)
    overlay = _read_yaml(local_path_for(base_path))
    return deep_merge(base, overlay)


def save_config(cfg, base_path=None):
    """Atomically write the FULL config dict to the overlay. Never touches
    the tracked config.yaml."""
    target = local_path_for(base_path)
    try:
        tmp = f"{target}.{_secrets.token_hex(4)}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp, target)
        return True
    except Exception as e:
        print(f"[Config] Failed to save {os.path.basename(target)}: {e}")
        return False
