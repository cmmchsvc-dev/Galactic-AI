import os
import sys
import shutil
import zipfile
import re
import yaml
import argparse
import glob
from datetime import datetime

# Configure paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join(ROOT_DIR, "releases")
BUILD_DIR = os.path.join(RELEASE_DIR, "build")

# Files and directories to explicitly INCLUDE in the release
INCLUDE_LIST = [
    "docs",
    "chrome-extension",
    "skills",
    "plugins",
    "CHANGELOG.md",
    "config.yaml",  # We will scrub this later
    "FEATURES.md",
    "index.html",
    "install.ps1",
    "install.sh",
    "install-chromebook.sh",
    "launch.ps1",
    "launch.sh",
    "LICENSE",
    "privacy.html",
    "README.md",
    "remove_galactic_autostart.ps1",
    "terms.html",
    "update.ps1",
    "update.sh",
    "galactic_core_v2.py",
    "gateway_v2.py",
    "memory_module_v2.py",
    "model_manager.py",
    "personality.py",
    "personality.yaml",
    "requirements.txt",
    "subagent_worker.py",
    "web_deck.py",
    "telegram_bridge.py",
    "discord_bridge.py",
    "gmail_bridge.py",
    "whatsapp_bridge.py",
    "flusher.py"
]

def sync_versions(new_version):
    """Sync the given version across all necessary files in the source tree."""
    new_version_clean = new_version.lstrip('v')
    
    # Get current version from config.yaml to use as the search target
    current_version = None
    config_path = os.path.join(ROOT_DIR, "config.yaml")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if 'system' in config and 'version' in config['system']:
                current_version = str(config['system']['version']).lstrip('v')
    except Exception as e:
        print(f"Warning: Could not read current version from config.yaml: {e}")
        return

    if not current_version:
        print("Warning: Current version not found in config.yaml. Cannot safely sync.")
        return
        
    print(f"Syncing version tags from {current_version} to {new_version_clean} across source files...")

    targets = [
        "config.yaml",
        "index.html",
        "README.md",
        "FEATURES.md",
        "PROJECT_STATE.md"
    ]
    
    # Add all skill files
    skill_files = glob.glob(os.path.join(ROOT_DIR, "skills", "**", "*.py"), recursive=True)
    targets.extend([os.path.relpath(p, ROOT_DIR) for p in skill_files])
    
    for target in targets:
        filepath = os.path.join(ROOT_DIR, target)
        if not os.path.exists(filepath):
            continue
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Replace vX.X.X first to avoid double replacement if we did X.X.X first
        new_content = content.replace(f"v{current_version}", f"v{new_version_clean}")
        # Then replace X.X.X
        new_content = new_content.replace(current_version, new_version_clean)
        
        if content != new_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"  Updated: {target}")

def clean_build_dir():
    """Remove the build directory if it exists."""
    if os.path.exists(BUILD_DIR):
        print(f"Cleaning build directory: {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

def copy_files():
    """Copy files to the build directory."""
    print("Copying files to build directory...")
    for item in INCLUDE_LIST:
        src = os.path.join(ROOT_DIR, item)
        dst = os.path.join(BUILD_DIR, item)
        if not os.path.exists(src):
            print(f"  Warning: Expected file/folder missing: {item}")
            continue
        
        if os.path.isdir(src):
            # Exclude __pycache__ during copy
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(src, dst)
    
    # Create empty directories required for runtime
    for empty_dir in ['logs', 'images', 'chroma_data', 'workspace']:
        os.makedirs(os.path.join(BUILD_DIR, empty_dir), exist_ok=True)

def scrub_config():
    """Scrub sensitive API keys and tokens from the copied config.yaml."""
    config_path = os.path.join(BUILD_DIR, "config.yaml")
    if not os.path.exists(config_path):
        return

    print("Scrubbing API keys from config.yaml...")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Recursive function to clear sensitive keys
        def _scrub_dict(d):
            sensitive_keywords = ['apikey', 'api_key', 'token', 'secret', 'hash', 'password', 'consumer_key', 'admin_chat_id', 'admin_user_id', 'client_id', 'phone_number_id']
            for k, v in d.items():
                if isinstance(v, dict):
                    # Hardcoded clear for NVIDIA model-specific keys
                    if k == 'keys' and isinstance(v, dict):
                        for model_key in v:
                            v[model_key] = ""
                    else:
                        _scrub_dict(v)
                elif any(kw in k.lower() for kw in sensitive_keywords):
                    d[k] = ""

        _scrub_dict(config)

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
    except Exception as e:
        print(f"  Error scrubbing config.yaml: {e}")

def create_workspace_templates():
    """Create template files for the workspace so users have empty starting points."""
    print("Creating safe workspace templates...")
    workspace_dir = os.path.join(BUILD_DIR, "workspace")
    
    templates = {
        "MEMORY.md": "## Galactic AI Memory\n\nThis file is managed by the AI. It will automatically store long-term facts here.\n",
        "IDENTITY.md": "## AI Identity\n\nName: Byte\nRole: Universal Automation Engine\n",
        "SOUL.md": "## Core Values\n\nBe helpful, clear, and action-oriented.\n",
        "USER.md": "## User Preferences\n\nAdd your preferences here.\n",
        "VAULT-example.md": "## Personal Info\n\n- **Email:** your.email@example.com\n\n## Credentials\n\n- **GitHub Token:** ghp_xxxxxxxxxxxxxxxxxxxx\n\n*(Rename this file to VAULT.md to use it)*\n"
    }
    
    # Also copy the tools reference to the workspace
    tools_src = os.path.join(ROOT_DIR, "TOOLS.md")
    tools_dst = os.path.join(workspace_dir, "TOOLS.md")
    if os.path.exists(tools_src):
        shutil.copy2(tools_src, tools_dst)

    for filename, content in templates.items():
        with open(os.path.join(workspace_dir, filename), 'w', encoding='utf-8') as f:
            f.write(content)

def get_version():
    """Extract version from config.yaml or fallback to date."""
    try:
        config_path = os.path.join(ROOT_DIR, "config.yaml")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if 'system' in config and 'version' in config['system']:
                return str(config['system']['version']).lstrip('v')
    except Exception as e:
        pass
    return datetime.now().strftime("%Y%m%d")

def build_zip(version):
    """Zip the build directory."""
    zip_filename = f"Galactic_AI_v{version}.zip"
    zip_path = os.path.join(RELEASE_DIR, zip_filename)
    
    print(f"Creating release archive: {zip_filename}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(BUILD_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                # Ensure the files are at the root of the zip
                arcname = os.path.relpath(file_path, BUILD_DIR)
                zipf.write(file_path, arcname)
    
    print(f"Release built successfully at: {zip_path}")
    return zip_path

def main():
    parser = argparse.ArgumentParser(description="Build Galactic AI release")
    parser.add_argument('--set-version', type=str, help='New version number (e.g. 1.1.6)')
    args = parser.parse_args()

    print(f"--- Galactic AI Release Builder ---")
    os.makedirs(RELEASE_DIR, exist_ok=True)
    
    if args.set_version:
        sync_versions(args.set_version)
        
    clean_build_dir()
    copy_files()
    scrub_config()
    create_workspace_templates()
    
    version = get_version()
    zip_path = build_zip(version)
    
    # Cleanup build dir
    shutil.rmtree(BUILD_DIR)
    print("Done!")

if __name__ == "__main__":
    main()
