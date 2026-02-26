import os
import sys
import shutil
import zipfile
import tarfile
import re
import yaml
import argparse
import glob
import hashlib
from datetime import datetime

# Configure paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_BASE_DIR = os.path.join(ROOT_DIR, "releases")
BUILD_DIR = os.path.join(RELEASE_BASE_DIR, "build")

# Files and directories to explicitly INCLUDE in the release
INCLUDE_LIST = [
    "docs",
    "chrome-extension",
    "skills",
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
    "web_deck.py",
    "telegram_bridge.py",
    "discord_bridge.py",
    "gmail_bridge.py",
    "whatsapp_bridge.py",
    "flusher.py",
    "hot_memory_buffer.py",
    "imprint_engine.py",
    "remote_access.py",
    "ollama_manager.py",
    "nvidia_gateway.py",
    "scheduler.py",
    "splash.py",
    "autopatch.py",
    "fix_ollama.py"
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

def generate_release_notes(version, release_target_dir):
    """Extract latest release notes from CHANGELOG.md."""
    changelog_path = os.path.join(ROOT_DIR, "CHANGELOG.md")
    if not os.path.exists(changelog_path):
        return
    
    print("Generating RELEASE_NOTES.md...")
    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        notes_lines = []
        found_version = False
        
        for line in lines:
            if f"## v{version}" in line:
                found_version = True
                notes_lines.append(line)
                continue
            
            if found_version:
                if line.startswith("## v"):
                    break
                notes_lines.append(line)
            
        if notes_lines:
            notes = "".join(notes_lines).strip()
            # Remove trailing horizontal rules
            notes = re.sub(r'\n---\s*$', '', notes)
        else:
            notes = f"Release notes for v{version} not found in CHANGELOG.md"
            
        with open(os.path.join(release_target_dir, "RELEASE_NOTES.md"), 'w', encoding='utf-8') as f:
            f.write(f"# Galactic AI v{version} Release Notes\n\n{notes}")
    except Exception as e:
        print(f"  Error generating release notes: {e}")

def get_file_sha256(filepath):
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def build_packages(version, release_target_dir):
    """Build zip and tar.gz packages for different platforms."""
    packages = []
    
    # Base filenames
    zip_base = f"Galactic-AI-v{version}"
    
    # 1. Universal Zip
    zip_path = os.path.join(release_target_dir, f"{zip_base}.zip")
    print(f"Creating universal archive: {os.path.basename(zip_path)}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(BUILD_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, BUILD_DIR)
                zipf.write(file_path, arcname)
    packages.append(zip_path)
    
    # 2. Windows Zip (Copy of universal)
    win_zip = os.path.join(release_target_dir, f"{zip_base}-windows.zip")
    shutil.copy2(zip_path, win_zip)
    packages.append(win_zip)
    
    # 3. macOS Zip (Copy of universal)
    mac_zip = os.path.join(release_target_dir, f"{zip_base}-macos.zip")
    shutil.copy2(zip_path, mac_zip)
    packages.append(mac_zip)
    
    # 4. Linux Tarball
    linux_tar = os.path.join(release_target_dir, f"{zip_base}-linux.tar.gz")
    print(f"Creating linux tarball: {os.path.basename(linux_tar)}...")
    with tarfile.open(linux_tar, "w:gz") as tar:
        tar.add(BUILD_DIR, arcname="")
    packages.append(linux_tar)
    
    # Generate SHA256SUMS.txt
    print("Generating SHA256SUMS.txt...")
    sums_path = os.path.join(release_target_dir, "SHA256SUMS.txt")
    with open(sums_path, 'w', encoding='utf-8') as f:
        for pkg in packages:
            fname = os.path.basename(pkg)
            sha = get_file_sha256(pkg)
            f.write(f"{sha}  {fname}\n")
    
    print(f"All packages built in: {release_target_dir}")

def main():
    parser = argparse.ArgumentParser(description="Build Galactic AI release")
    parser.add_argument('--set-version', type=str, help='New version number (e.g. 1.1.6)')
    args = parser.parse_args()

    print(f"--- Galactic AI Release Builder ---")
    
    if args.set_version:
        sync_versions(args.set_version)
        
    version = get_version()
    release_target_dir = os.path.join(RELEASE_BASE_DIR, f"v{version}")
    os.makedirs(release_target_dir, exist_ok=True)
    
    clean_build_dir()
    copy_files()
    scrub_config()
    create_workspace_templates()
    
    build_packages(version, release_target_dir)
    generate_release_notes(version, release_target_dir)
    
    # Cleanup build dir
    shutil.rmtree(BUILD_DIR)
    print("Done!")

if __name__ == "__main__":
    main()
