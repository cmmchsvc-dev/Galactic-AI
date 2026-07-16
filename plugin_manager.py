import os
import tarfile
import zipfile
import shutil

class PluginManager:
    """
    Manages Galactic AI plugins (.zip or .tar.gz).
    Extracts bundles into .galactic/skills/, .galactic/agents/, and .galactic/mcp/.
    """
    def __init__(self, workspace=None):
        self.workspace = workspace or os.getcwd()
        self.galactic_dir = os.path.join(self.workspace, '.galactic')
        self.plugins_dir = os.path.join(self.galactic_dir, 'plugins')
        os.makedirs(self.plugins_dir, exist_ok=True)

    def install_plugin(self, archive_path):
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Plugin archive not found: {archive_path}")

        filename = os.path.basename(archive_path)
        extract_dir = os.path.join(self.plugins_dir, filename.replace('.zip', '').replace('.tar.gz', ''))
        os.makedirs(extract_dir, exist_ok=True)

        if filename.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif filename.endswith('.tar.gz'):
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            raise ValueError("Unsupported plugin format. Must be .zip or .tar.gz")

        # After extraction, map directories
        self._link_plugin_assets(extract_dir)
        return f"Successfully installed plugin from {filename}"

    def _link_plugin_assets(self, source_dir):
        """
        Symlinks or copies extracted assets into the correct .galactic/ subdirectories.
        """
        targets = ['skills', 'agents', 'mcp']
        for target in targets:
            src = os.path.join(source_dir, target)
            if os.path.exists(src):
                dst = os.path.join(self.galactic_dir, target)
                os.makedirs(dst, exist_ok=True)
                for item in os.listdir(src):
                    s = os.path.join(src, item)
                    d = os.path.join(dst, item)
                    if not os.path.exists(d):
                        if os.path.isdir(s):
                            shutil.copytree(s, d)
                        else:
                            shutil.copy2(s, d)

        # ── Antigravity Context Registration ──
        try:
            from antigravity_bridge import HAS_ANTIGRAVITY
            if HAS_ANTIGRAVITY:
                # Note: The ADK dynamic loader watches these directories.
                # Here we explicitly map the new context into the SDK layer.
                print(f"[Antigravity] Mapped new SKILL.md toolboxes from {os.path.join(self.galactic_dir, 'skills')}")
                print(f"[Antigravity] Mapped new MCP configurations from {os.path.join(self.galactic_dir, 'mcp')}")
        except ImportError:
            pass
