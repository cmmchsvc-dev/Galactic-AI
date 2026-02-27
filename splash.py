# Galactic AI - Pulse Engine Boot Screen
# Atomic Age / Raygun Gothic Aesthetic

import yaml, os

def _get_version():
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        return cfg.get('system', {}).get('version', '?')
    except Exception:
        return '?'

def get_splash():
    ver = _get_version()
    return f"""
    ************************************************************
    *                                                          *
    *    GA L A C T I C   AI   -   A U T O M A T I O N         *
    *                                                          *
    *          [ P U L S E   E N G I N E : O N ]               *
    *                                                          *
    *    > SYSTEM: v{ver}                                      *
    *    > CO-PILOT: BYTE                                      *
    *    > STATUS: ALL SYSTEMS NOMINAL                         *
    *                                                          *
    *    "The infinite universe, one byte at a time."          *
    *                                                          *
    ************************************************************
    """

if __name__ == "__main__":
    print(get_splash())