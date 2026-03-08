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

    async def run(self):
        await self.core.log("🧠 Neural Indexer initialized. Stealth Mode active.", priority=3)
        while True:
            try:
                self.is_scanning = True
                await self.scan_and_index()
                self.is_scanning = False
                self.progress = 100
                await asyncio.sleep(300) # Scan every 5 mins
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
