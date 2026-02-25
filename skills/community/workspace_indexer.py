"""
Galactic AI -- Workspace Indexer Skill
Continuously indexes the workspace/ directory into ChromaDB for semantic search.
"""

import asyncio
import os
import glob
import hashlib
from datetime import datetime
from skills.base import GalacticSkill

try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

class WorkspaceIndexerSkill(GalacticSkill):
    """
    Monitors the workspace folder and builds a searchable semantic index of your codebase.
    """
    skill_name  = "workspace_indexer"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Automatically indexes files in workspace/ for fast semantic search (RAG)."
    category    = "system"
    icon        = "\U0001f5c2"

    def __init__(self, core):
        super().__init__(core)
        self.client = None
        self.collection = None
        self.embed_fn = None
        self._file_hashes = {} # Track modified files

    async def on_load(self):
        if not CHROMA_AVAILABLE:
            await self.core.log("[Workspace Indexer] ChromaDB not found.", priority=1)
            return

        def _init_chroma():
            try:
                chroma_path = self.core.config.get('paths', {}).get('chroma_data', 'chroma_data')
                self.client = chromadb.PersistentClient(path=chroma_path)
                self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
                self.collection = self.client.get_or_create_collection(
                    name="workspace_code",
                    embedding_function=self.embed_fn
                )
                return "[Workspace Indexer] Chroma collection 'workspace_code' initialized."
            except Exception as e:
                return f"[Workspace Indexer] Error initializing: {e}"

        init_message = await asyncio.to_thread(_init_chroma)
        await self.core.log(init_message, priority=2)

    def get_tools(self):
        if not CHROMA_AVAILABLE:
            return {}
        return {
            "search_workspace": {
                "description": "Semantic search through all files in the workspace/ folder. Use this to quickly find relevant code snippets, functions, or documentation without reading entire files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The concept, function, or bug you are looking for."},
                        "n_results": {"type": "integer", "description": "Number of snippets to return (default: 5)."}
                    },
                    "required": ["query"]
                },
                "fn": self.search_workspace
            }
        }

    async def search_workspace(self, args):
        if not self.collection:
            return "[ERROR] Index collection is not available."

        query = args.get('query')
        n_results = args.get('n_results', 5)

        def _query():
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=n_results
                )
                
                if not results or not results.get('documents') or not results['documents'][0]:
                    return "No relevant code snippets found in workspace."

                output = [f"### Workspace Search Results for: '{query}'
"]
                for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                    file_path = meta.get('file', 'Unknown File')
                    output.append(f"**File:** `{file_path}`
```
{doc}
```
---")
                return "
".join(output)
            except Exception as e:
                return f"[ERROR] Failed to search workspace: {e}"

        return await asyncio.to_thread(_query)

    async def run(self):
        """Background loop to monitor and index files."""
        if not CHROMA_AVAILABLE:
            return
            
        workspace_dir = self.core.config.get('paths', {}).get('workspace', 'workspace')
        if not os.path.exists(workspace_dir):
            return

        extensions = ('.py', '.js', '.ts', '.html', '.css', '.md', '.txt', '.json', '.yaml', '.yml', '.ps1', '.sh')
        
        while self.enabled:
            def _index_files():
                try:
                    updated_count = 0
                    for root, _, files in os.walk(workspace_dir):
                        for file in files:
                            if not file.endswith(extensions):
                                continue
                                
                            path = os.path.join(root, file)
                            
                            # Get file modification time
                            try:
                                mtime = os.path.getmtime(path)
                            except:
                                continue
                                
                            # Check if we need to process this file
                            if path in self._file_hashes and self._file_hashes[path] == mtime:
                                continue
                                
                            # Process file
                            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                
                            if not content.strip():
                                continue
                                
                            # Simple chunking (e.g., split by paragraphs or double newlines)
                            chunks = [c.strip() for c in content.split('

') if len(c.strip()) > 50]
                            
                            # If no natural breaks, chunk by length
                            if not chunks:
                                chunk_size = 1000
                                chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
                                
                            docs = []
                            metadatas = []
                            ids = []
                            
                            for i, chunk in enumerate(chunks):
                                doc_id = hashlib.md5(f"{path}_{i}_{mtime}".encode()).hexdigest()
                                docs.append(chunk)
                                metadatas.append({"file": os.path.relpath(path, workspace_dir), "chunk": str(i)})
                                ids.append(doc_id)
                                
                            if docs:
                                # Remove old chunks for this file
                                try:
                                    self.collection.delete(where={"file": os.path.relpath(path, workspace_dir)})
                                except:
                                    pass
                                    
                                # Add new chunks
                                self.collection.add(
                                    documents=docs,
                                    metadatas=metadatas,
                                    ids=ids
                                )
                                
                            self._file_hashes[path] = mtime
                            updated_count += 1
                            
                    if updated_count > 0:
                        return f"[Workspace Indexer] Re-indexed {updated_count} files."
                except Exception as e:
                    return f"[Workspace Indexer Error] {e}"
                return None

            result = await asyncio.to_thread(_index_files)
            if result:
                await self.core.log(result, priority=2)
                
            await asyncio.sleep(60) # Scan every 60 seconds
