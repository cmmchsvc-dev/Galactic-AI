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
        self.progress = 0 # 0-100 percentage
        self.is_scanning = False
        self._mtime_snapshot = {} # path -> mtime, for cheap change detection
        
        # Load cache
        self.db_dir = self.core.config.get('paths', {}).get('db', './db') if self.core and hasattr(self.core, 'config') else './db'
        os.makedirs(self.db_dir, exist_ok=True)
        self.cache_path = os.path.join(self.db_dir, 'neural_indexer_cache.json')
        
        self.indexed_files = {} # path -> md5
        if os.path.exists(self.cache_path):
            try:
                import json
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    self.indexed_files = json.load(f)
            except Exception as e:
                print(f"Failed to load indexer cache: {e}")

    def _save_cache(self):
        try:
            import json
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.indexed_files, f)
        except Exception as e:
            print(f"Failed to save indexer cache: {e}")

    # Directories that hold RUNTIME OUTPUT rather than source. Watching these
    # made the indexer trigger itself in a loop: a scan writes
    # db/neural_indexer_cache.json, whose mtime change is then detected as
    # "files changed", which starts the next scan — forever, every 30s, always
    # re-embedding the same handful of files. logs/ is the same story
    # (system_log.txt, conversations/hot_buffer.json, checkpoint.json are all
    # rewritten continuously while Galactic runs).
    _RUNTIME_DIRS = {
        '.git', '__pycache__', 'venv', '.venv', 'env', 'node_modules',
        'chroma_data', 'chroma_data.bak', 'releases', 'dist', 'build',
        'logs', 'db', 'tmp', 'scratch', 'messages', 'images', '_archive',
        '.pytest_cache', 'tts_models', 'fish-speech',
    }
    # ...and single files under the workspace root that churn constantly.
    _RUNTIME_FILES = {'system_log.txt', 'neural_indexer_cache.json',
                      'hot_buffer.json', 'current_session.json',
                      'gemini_error.txt', 'checkpoint.json'}

    _SOURCE_EXTS = ('.py', '.js', '.md', '.txt', '.yaml', '.json')

    def _walk_source_files(self, workspace):
        """Yield indexable source paths, skipping runtime output.

        ONE definition of what's indexable, used by change-detection, the
        progress pre-count and the scan itself. They used to disagree: change
        detection pruned a handful of dirs, while the scan tested
        `any(p in root for p in [...])` — a substring match that never excluded
        logs/ or db/ at all, so the scan re-read Galactic's own output even when
        the mtime pass had ignored it.
        """
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs
                       if d.lower() not in self._RUNTIME_DIRS and not d.startswith('.')]
            for file in files:
                if file.lower() in self._RUNTIME_FILES:
                    continue
                if file.endswith(self._SOURCE_EXTS):
                    yield os.path.join(root, file)

    def _get_workspace_mtimes(self, workspace):
        """Quick pass to collect mtimes of all tracked files."""
        snapshot = {}
        for path in self._walk_source_files(workspace):
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
        return sum(1 for _ in self._walk_source_files(workspace))

    async def scan_and_index(self):
        workspace = self.core.config.get('system', {}).get('workspace_root', os.getcwd())
        
        # 1. Pre-scan for progress bar
        total_files = await self._count_files(workspace)
        if total_files == 0:
            self.progress = 100
            return

        processed_files = 0
        new_files = 0
        global_batch = []
        
        for path in self._walk_source_files(workspace):
            file = os.path.basename(path)

            processed_files += 1
            self.progress = int((processed_files / total_files) * 100)

            if new_files > 0 or processed_files % 10 == 0:
                status_msg = f"🧠 Neural Indexer: {self.progress}% ({processed_files}/{total_files} files) | Synced: {new_files}"
                await self.core.update_status(status_msg)

            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                        
                content_hash = hashlib.md5(content.encode()).hexdigest()
                if self.indexed_files.get(path) == content_hash:
                    continue
                        
                # Semantic Imprint (Silent) with Global Batching
                if len(content) > 100000:
                    content = content[:100000]
                        
                chunks = [c.strip() for c in content.split('\n\n') if len(c.strip()) > 50]
                if not chunks:
                    chunk_size = 1500
                    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
                    
                for i, chunk in enumerate(chunks):
                    global_batch.append({
                        "content": f"FILE: {file} (Part {i+1}/{len(chunks)})\nPATH: {path}\nCONTENT:\n{chunk}",
                        "category": "codebase_index",
                        "metadata": {"path": path, "type": "code", "chunk_index": i}
                    })
                        
                self.indexed_files[path] = content_hash
                new_files += 1
                    
                if len(global_batch) >= 100:
                    if hasattr(self.core.memory, 'save_memories_bulk'):
                        await self.core.memory.save_memories_bulk(global_batch, silent=True)
                    else:
                        for mem in global_batch:
                            await self.core.memory.save_memory(
                                content=mem['content'], category=mem['category'], metadata=mem['metadata'], silent=True
                            )
                    global_batch.clear()
                    await asyncio.sleep(0.01) # Yield to event loop
                        
            except Exception:
                continue
                    
        if global_batch:
            if hasattr(self.core.memory, 'save_memories_bulk'):
                await self.core.memory.save_memories_bulk(global_batch, silent=True)
            else:
                for mem in global_batch:
                    await self.core.memory.save_memory(
                        content=mem['content'], category=mem['category'], metadata=mem['metadata'], silent=True
                    )
            global_batch.clear()
        
        if new_files > 0:
            self._save_cache()
            # Final line break and summary log
            sys.stdout.write('\n')
            await self.core.log(f"🧠 Neural Indexer: Synchronized {new_files} files with Semantic Memory.", priority=3)
        self.progress = 100
