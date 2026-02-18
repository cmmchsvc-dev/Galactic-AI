# Galactic AI: Local Memory Ingestion & In-Memory Index
import asyncio
import os
import json
from datetime import datetime

class GalacticMemory:
    """The Rust-Powered Brain: Local Vector Store simulation."""
    def __init__(self, config_or_core):
        if hasattr(config_or_core, 'config'):
            self.core = config_or_core
            self.config = config_or_core.config
        else:
            self.core = None
            self.config = config_or_core
            
        self.memory_path = os.path.join(self.config['paths']['logs'], 'memory_aura.json')
        self.index = self.load_index()

    def load_index(self):
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"memories": [], "last_sync": None}

    async def imprint(self, content, metadata=None):
        """Add a memory to the local index."""
        memory_entry = {
            "id": len(self.index["memories"]),
            "timestamp": datetime.now().isoformat(),
            "content": content,
            "metadata": metadata or {}
        }
        self.index["memories"].append(memory_entry)
        self.index["last_sync"] = datetime.now().isoformat()
        
        # Save to disk
        with open(self.memory_path, 'w') as f:
            json.dump(self.index, f, indent=2)
            
        if self.core:
            await self.core.log(f"Memory Imprinted: {metadata.get('source', 'unknown')}", priority=3)

    async def recall(self, query):
        """Keyword-based local recall."""
        results = [m for m in self.index["memories"] if query.lower() in m["content"].lower()]
        return results[:5]

    async def imprint_file(self, file_path):
        """Imprint an entire file into memory."""
        if not os.path.exists(file_path):
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                await self.imprint(content, {"source": os.path.basename(file_path), "path": file_path})
        except Exception as e:
            if self.core:
                await self.core.log(f"Imprint failed for {file_path}: {e}")
