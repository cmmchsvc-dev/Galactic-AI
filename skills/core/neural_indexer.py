import os
import sys
import time
import asyncio
import hashlib
from skills.base import GalacticSkill

class NeuralIndexer(GalacticSkill):
    """
    Cutting Edge: Background Semantic Code Indexing.
    Uses the Ampere (RTX 3080) to vector-index the entire workspace.
    """
    
    skill_name   = "neural_indexer"
    display_name = "Neural Workspace Indexer"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Autonomously vector-indexes the codebase for near-instant semantic lookup."
    category     = "system"
    icon         = "🧠"

    def __init__(self, core):
        super().__init__(core)
        self.indexed_files = {} # path -> md5
        self.progress = 0 # 0-100 percentage
        self.is_scanning = False
        self._mtime_snapshot = {} # path -> mtime, for cheap change detection

    def _get_workspace_mtimes(self, workspace):
        """Quick pass to collect mtimes of all tracked files."""
        snapshot = {}
        skip_dirs = {'.git', '__pycache__', 'venv', 'node_modules', 'chroma_data', 'releases'}
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
            for file in files:
                if file.endswith(('.py', '.js', '.md', '.txt', '.yaml', '.json')):
                    path = os.path.join(root, file)
                    try:
                        snapshot[path] = os.path.getmtime(path)
                    except OSError:
                        pass
        return snapshot

    def _has_changes(self, workspace):
        """Returns True if any tracked file was added, removed, or modified."""
        current = self._get_workspace_mtimes(workspace)
        if set(current.keys()) != set(self._mtime_snapshot.keys()):
            return True
        for path, mtime in current.items():
            if self._mtime_snapshot.get(path) != mtime:
                return True
        return False

    async def run(self):
        await self.core.log("🧠 Neural Indexer initialized — change-detection mode active.", priority=3)
        workspace = self.core.config.get('system', {}).get('workspace_root', os.getcwd())

        # Run an initial index on startup
        try:
            self.is_scanning = True
            await self.scan_and_index()
            self.is_scanning = False
            self.progress = 100
            self._mtime_snapshot = self._get_workspace_mtimes(workspace)
        except Exception as e:
            self.is_scanning = False
            await self.core.log(f"⚠️ Indexer startup failed: {e}", priority=1)

        while True:
            try:
                await asyncio.sleep(30)  # Poll every 30 seconds (cheap mtime check only)
                if not self._has_changes(workspace):
                    continue  # Nothing changed — go back to sleep immediately

                # Changes detected — run a targeted scan
                self.is_scanning = True
                await self.scan_and_index()
                self.is_scanning = False
                self.progress = 100
                self._mtime_snapshot = self._get_workspace_mtimes(workspace)
            except Exception as e:
                self.is_scanning = False
                await self.core.log(f"⚠️ Indexer failed: {e}", priority=1)
                await asyncio.sleep(60)


    async def _count_files(self, workspace):
        """Pre-scan to get total file count for progress bar."""
        total = 0
        for root, dirs, files in os.walk(workspace):
            if any(p in root for p in ['.git', '__pycache__', 'venv', 'node_modules', 'chroma_data']):
                continue
            for file in files:
                if file.endswith(('.py', '.js', '.md', '.txt', '.yaml', '.json')):
                    total += 1
        return total

    async def scan_and_index(self):
        workspace = self.core.config.get('system', {}).get('workspace_root', os.getcwd())
        
        # 1. Pre-scan for progress bar
        total_files = await self._count_files(workspace)
        if total_files == 0:
            self.progress = 100
            return

        processed_files = 0
        new_files = 0
        
        for root, dirs, files in os.walk(workspace):
            # Ignore hidden and build dirs
            if any(p in root for p in ['.git', '__pycache__', 'venv', 'node_modules', 'chroma_data']):
                continue
                
            for file in files:
                if not file.endswith(('.py', '.js', '.md', '.txt', '.yaml', '.json')):
                    continue

                processed_files += 1
                self.progress = int((processed_files / total_files) * 100)
                
                if new_files > 0 or processed_files % 10 == 0:
                    status_msg = f"🧠 Neural Indexer: {self.progress}% ({processed_files}/{total_files} files) | Synced: {new_files}"
                    await self.core.update_status(status_msg)
                    
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    content_hash = hashlib.md5(content.encode()).hexdigest()
                    if self.indexed_files.get(path) == content_hash:
                        continue
                        
                    # Semantic Imprint (Silent)
                    await self.core.memory.save_memory(
                        content=f"FILE: {file}\nPATH: {path}\nCONTENT:\n{content[:2000]}",
                        category="codebase_index",
                        metadata={"path": path, "type": "code"},
                        silent=True
                    )
                    self.indexed_files[path] = content_hash
                    new_files += 1
                    
                    if new_files % 10 == 0:
                        await asyncio.sleep(0.01) # Faster yield
                        
                except Exception:
                    continue
        
        if new_files > 0:
            # Final line break and summary log
            sys.stdout.write('\n')
            await self.core.log(f"🧠 Neural Indexer: Synchronized {new_files} files with Semantic Memory.", priority=3)
        self.progress = 100
