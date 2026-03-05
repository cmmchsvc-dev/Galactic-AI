# F:\Galactic AI\galactic_memory.py
# GALACTIC MEMORY CORE: Hybrid Episodic + Semantic Storage
# Surpasses OpenClaw by giving the AI a true "hippocampus" for long-term learning.

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import sqlite3
import json
from datetime import datetime
from pathlib import Path
import hashlib
import os

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "galactic_memory.db"
CHROMA_PATH = BASE_DIR / "chroma_data"
EMBEDDING_MODEL = "all-MiniLM-L6-v2" # Fast, local, lightweight (approx 80MB)

class GalacticMemory:
    def __init__(self, core=None):
        self.core = core
        # 1. Init SQLite (Episodic - Exact Records)
        # Use config paths if available
        if core and hasattr(core, 'config'):
            logs_dir = core.config.get('paths', {}).get('logs', './logs')
            self.db_path = Path(logs_dir).resolve() / "galactic_memory.db"
            self.chroma_path = Path(logs_dir).resolve() / "chroma_data"
        else:
            self.db_path = DB_PATH
            self.chroma_path = CHROMA_PATH

        self.conn = sqlite3.connect(str(self.db_path))
        self._init_sql()
        
        # 2. Init ChromaDB (Semantic - Meaning & Context)
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        self.collection = self.client.get_or_create_collection(
            name="galactic_context",
            metadata={"hnsw:space": "cosine"}
        )
        
        # 3. Init Embedding Model (Lazy load)
        self._model = None

    async def imprint(self, content, metadata=None):
        """Compatibility wrapper for 'imprint' (calls save_memory)."""
        category = (metadata or {}).get("category", "general")
        return self.save_memory(content, category=category, metadata=metadata)

    async def imprint_file(self, file_path):
        """Imprint an entire file into memory."""
        p = Path(file_path)
        if not p.exists():
            return
        try:
            content = p.read_text(encoding='utf-8', errors='ignore')
            await self.imprint(content, {"source": p.name, "path": str(p), "category": "file_imprint"})
        except Exception as e:
            if self.core:
                await self.core.log(f"Imprint failed for {file_path}: {e}")

    async def recall(self, query, top_k=5):
        """Compatibility wrapper for 'recall' (calls query_memory)."""
        return self.query_memory(query, n_results=top_k)

    @property
    def model(self):
        if self._model is None:
            print("🧠 Loading embedding model (first time only, approx 10s)...")
            self._model = SentenceTransformer(EMBEDDING_MODEL)
            print("✅ Model loaded.")
        return self._model

    def _init_sql(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS episodic_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                category TEXT,
                content TEXT,
                metadata_json TEXT,
                vector_id TEXT UNIQUE
            )
        """)
        self.conn.commit()

    def save_memory(self, content: str, category: str = "general", metadata: dict = None):
        """Save a memory with both semantic (vector) and episodic (sql) storage."""
        timestamp = datetime.now().isoformat()
        
        # Generate Vector Embedding
        embedding = self.model.encode([content])[0].tolist()
        vector_id = hashlib.md5(f"{timestamp}{content}".encode()).hexdigest()
        
        # 1. Save to Chroma (Semantic Search)
        self.collection.upsert(
            ids=[vector_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"category": category, "timestamp": timestamp}]
        )
        
        # 2. Save to SQLite (Exact Record Keeping)
        meta_json = json.dumps(metadata) if metadata else "{}"
        c = self.conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO episodic_memories (timestamp, category, content, metadata_json, vector_id) VALUES (?, ?, ?, ?, ?)",
            (timestamp, category, content, meta_json, vector_id)
        )
        self.conn.commit()
        
        print(f"✅ Memory Saved [{category}]: '{content[:60]}...'")
        return vector_id

    def query_memory(self, query: str, n_results: int = 5, category: str = None):
        """Query memory by meaning (semantic), with optional category filter."""
        query_embedding = self.model.encode([query])[0].tolist()
        
        # Build Filter
        where_filter = None
        if category:
            where_filter = {"category": category}
            
        # Chroma Search (Cosine Similarity)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter
        )
        
        # Format Output
        memories = []
        if results['ids'] and results['ids'][0]:
            for i, id in enumerate(results['ids'][0]):
                memories.append({
                    "id": id,
                    "content": results['documents'][0][i],
                    "distance": results['distances'][0][i], # Lower is better match
                    "metadata": results['metadatas'][0][i]
                })
        
        return memories

    def get_all_memories(self, limit: int = 10):
        """Get the most recent episodic memories."""
        c = self.conn.cursor()
        c.execute("SELECT timestamp, category, content FROM episodic_memories ORDER BY id DESC LIMIT ?", (limit,))
        return c.fetchall()

    def close(self):
        self.conn.close()

# --- Automated Test Suite ---
def run_self_test():
    print("\n[RUNNING GALACTIC MEMORY SELF-TEST...]")
    mem = GalacticMemory()
    
    # Test 1: Save Episodic Memory (F100 Context)
    print("\n1. Saving F100 Memory...")
    mem.save_memory(
        "Installed the Holley Sniper EFI on the 352FE today. It's running rich at idle and smells like raw gas. Need to tune the IAC curve.",
        category="f100_truck"
    )
    
    # Test 2: Save Episodic Memory (AI Dev Context)
    print("2. Saving AI Dev Memory...")
    mem.save_memory(
        "Refactored telegram_bridge_fixed.py to use async waits. The old sleep loops were causing timeouts.",
        category="ai_development"
    )

    # Test 3: Semantic Query (The Magic Part)
    print("\n3. Testing Semantic Search...")
    print("   Query: 'Why does my truck smell like gas?'")
    
    results = mem.query_memory("Why does my truck smell like gas?", n_results=2)
    
    if results:
        print(f"   [SUCCESS] Found {len(results)} relevant memories.")
        for r in results:
            print(f"      - [{r['metadata']['category']}] (Score: {r['distance']:.4f})")
            print(f"        '{r['content']}'")
        
        # Verify it found the F100 one
        if any("Holley" in r['content'] or "EFI" in r['content'] for r in results):
            print("\n[SEMANTIC MATCH CONFIRMED] The AI understood the connection between 'smell like gas' and 'running rich/EFI'.")
        else:
            print("\n[WARNING] Found results, but missed the specific F100 context.")
    else:
        print("   [FAILED] No memories found.")

    # Test 4: Category Filter
    print("\n4. Testing Category Filter...")
    print("   Query: 'Refactored telegram', Category: 'ai_development'")
    results_cat = mem.query_memory("Refactored telegram", n_results=2, category="ai_development")
    if results_cat and "telegram" in results_cat[0]['content'].lower():
        print("   [SUCCESS] Category filtering works.")
    else:
        print("   [WARNING] Category filtering returned unexpected results.")

    mem.close()
    print("\n[SELF-TEST COMPLETE] Galactic Memory Core is online.")

if __name__ == "__main__":
    # If run directly, execute the self-test
    run_self_test()
