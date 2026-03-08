import sys
import importlib.util
import re
from pathlib import Path

def get_missing_deps(requirements_path):
    """
    Scans a requirements.txt and returns a list of packages that cannot be imported.
    """
    req_file = Path(requirements_path)
    if not req_file.exists():
        return []

    # Map requirement name to import name if they differ
    import_map = {
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
    }

    missing = []
    
    with open(req_file, 'r', encoding='utf-8') as f:
        for line in f:
            # Split by # to remove comments and strip
            req_spec = line.split('#')[0].strip()
            if not req_spec:
                continue
            
            # Extract package name (remove version constraints and extras)
            # e.g., "torch>=2.2.0" -> "torch"
            # e.g., "qrcode[pil]>=8.0" -> "qrcode[pil]"
            match = re.match(r'^([a-zA-Z0-9\[\]\._-]+)', req_spec)
            if not match:
                continue
                
            req_name = match.group(1).lower()
            import_name = import_map.get(req_name, req_name.replace('-', '_'))
            
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
