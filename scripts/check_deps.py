import sys
import importlib.util
import re
from pathlib import Path

IMPORT_MAP = {
    "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn",
    "python-dotenv": "dotenv",
    "google-genai": "google.genai",
    "google-cloud-aiplatform": "google.cloud.aiplatform",
    "google-auth": "google.auth",
    "opencv-python": "cv2",
    "python-docx": "docx",
    "pypdf": "pypdf",
    "qrcode[pil]": "qrcode",
    "discord.py": "discord",
    "pywebview": "webview",
    "pyyaml": "yaml",
    "jinja2": "jinja2",
    "pillow": "PIL",
    "speechrecognition": "speech_recognition",
    "faster-whisper": "faster_whisper",
    "sentence-transformers": "sentence_transformers",
}


def _iter_requirement_lines(requirements_path, _seen=None):
    """Yield real (non-`-r`) requirement spec strings from a requirements
    file, recursively following `-r other_file.txt` includes — our
    requirements.txt is now an aggregator of requirements/*.txt groups, so a
    non-recursive reader would only ever see `-r` lines and never a single
    real package."""
    req_file = Path(requirements_path)
    if _seen is None:
        _seen = set()
    resolved = req_file.resolve()
    if resolved in _seen or not req_file.exists():
        return
    _seen.add(resolved)

    with open(req_file, 'r', encoding='utf-8') as f:
        for line in f:
            spec = line.split('#')[0].strip()
            if not spec:
                continue
            if spec.startswith('-r'):
                # "-r path" or "-rpath"
                ref = spec[2:].strip()
                if ref:
                    yield from _iter_requirement_lines(req_file.parent / ref, _seen)
                continue
            if spec.startswith('-'):
                continue  # other pip flags (--index-url etc.) aren't a package
            yield spec


def get_missing_deps(requirements_path):
    """
    Scans a requirements.txt (following -r includes) and returns a list of
    packages that cannot be imported.
    """
    missing = []
    for req_spec in _iter_requirement_lines(requirements_path):
        # Extract package name (remove version constraints and extras)
        # e.g., "torch>=2.2.0" -> "torch"
        # e.g., "qrcode[pil]>=8.0" -> "qrcode[pil]"
        match = re.match(r'^([a-zA-Z0-9\[\]\._-]+)', req_spec)
        if not match:
            continue

        req_name = match.group(1).lower()
        import_name = IMPORT_MAP.get(req_name, req_name.replace('-', '_'))

        # Special case for bracketed extras like qrcode[pil]
        if '[' in import_name:
            import_name = import_name.split('[')[0]

        try:
            if importlib.util.find_spec(import_name) is None:
                missing.append(req_spec)
        except (ImportError, ValueError):
            missing.append(req_spec)

    return missing

if __name__ == "__main__":
    req_path = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    missing = get_missing_deps(req_path)
    if missing:
        print(" ".join(missing))
    else:
        sys.exit(0)
