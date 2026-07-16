# F:\Galactic AI\galactic_memory.py
# GALACTIC MEMORY CORE: Hybrid Episodic + Semantic Storage
# Surpasses OpenClaw by giving the AI a true "hippocampus" for long-term learning.

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import sqlite3
import json
import asyncio
import os
from datetime import datetime
from pathlib import Path
import hashlib


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

        # 2. Init Semantic Memory (ChromaDB)
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        self.collection = self.chroma_client.get_or_create_collection(
            name="galactic_memory", # Changed collection name
            metadata={"hnsw:space": "cosine"} # Retained metadata
        )

        # 1. Init episodic memory (SQLite)
        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False) # Changed self.conn to self.db_conn, added check_same_thread
        self._init_db() # Changed _init_sql to _init_db

        # Thread safety lock
        self._lock = asyncio.Lock()
        
        # 3. Init Embedding Model (Lazy load)
        self._model = None

    async def imprint(self, content, metadata=None):
        """Compatibility wrapper for 'imprint' (calls save_memory)."""
        category = (metadata or {}).get("category", "general")
        # Changed to async call
        return await self.save_memory(content, category=category, metadata=metadata)

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

    async def recall(self, query, limit=5, **kwargs):
        """Compatibility wrapper for 'recall' (calls query_memory).

        By default EXCLUDES codebase_index chunks — the Neural Indexer writes
        1000+ code fragments into this collection, and without the filter they
        dominate conversational recall (the "semantic memories" injected per
        message end up being code instead of facts about the user).
        """
        # Supports both 'limit' and legacy 'top_k' parameters
        n_results = kwargs.get('top_k', limit)
        exclude = kwargs.get('exclude_categories', ('codebase_index',))
        return await self.query_memory(
            query, n_results=n_results,
            category=kwargs.get('category'),
            exclude_categories=exclude,
        )

    @property
    def model(self):
        if self._model is None:
            # Look for GPUOffloader skill to handle hardware routing
            device = "cpu"
            if self.core:
                offloader = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'gpu_offloader'), None)
                if offloader:
                    device = offloader.get_device("embeddings")

            print(f"🧠 Loading embedding model to {device} (approx 10s)...")
            self._model = SentenceTransformer(EMBEDDING_MODEL, device=device)
            print(f"✅ Model loaded on {device}.")
        return self._model

    def _init_db(self): # Renamed from _init_sql
        c = self.db_conn.cursor() # Changed self.conn to self.db_conn
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
        # V2.0: track which rows have been folded into a synthesized belief
        try:
            c.execute("ALTER TABLE episodic_memories ADD COLUMN synthesized INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        self.db_conn.commit() # Changed self.conn to self.db_conn

    async def save_memory(self, content: str, category: str = "general", metadata: dict = None, silent: bool = False):
        """Save a memory with both semantic (vector) and episodic (sql) storage."""
        async with self._lock:
            try:
                timestamp = datetime.now().isoformat()
                
                # Generate Vector Embedding (semantic)
                # Offload CPU-bound encode to thread pool to avoid blocking event loop
                loop = asyncio.get_running_loop()
                embedding = await loop.run_in_executor(
                    None, lambda: self.model.encode([content], show_progress_bar=False)[0].tolist()
                )
                # Generate stable vector ID
                if metadata and 'path' in metadata and 'chunk_index' in metadata:
                    # Stable ID for codebase chunks
                    vector_id = hashlib.md5(f"{metadata['path']}_{metadata['chunk_index']}".encode()).hexdigest()
                else:
                    # Fallback to content hash (no timestamp, allows deduplication)
                    vector_id = hashlib.md5(content.encode()).hexdigest()
                
                # 1. Save to Chroma (Semantic Search)
                self.collection.upsert(
                    ids=[vector_id],
                    embeddings=[embedding],
                    documents=[content],
                    metadatas=[{"category": category, "timestamp": timestamp}]
                )
                
                # 2. Save to SQLite (Episodic - Exact Record)
                # ... inserting logic ...
                meta_json = json.dumps(metadata) if metadata else "{}"
                cursor = self.db_conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO episodic_memories (timestamp, category, content, metadata_json, vector_id) VALUES (?, ?, ?, ?, ?)",
                    (timestamp, category, content, meta_json, vector_id)
                )
                self.db_conn.commit()
                
                if self.core and not silent:
                    p = 6 if category == "codebase_index" else 5
                    await self.core.log(f"✅ Memory Saved [{category}]: '{content[:60]}...'", priority=p)
                return vector_id
            except Exception as e:
                if self.core:
                    await self.core.log(f"❌ save_memory failed: {e}", priority=1)
                raise

    async def save_memories_bulk(self, memories: list[dict], silent: bool = False):
        """Save a batch of memories efficiently using single encoding and upsert."""
        if not memories:
            return []
            
        async with self._lock:
            try:
                timestamp = datetime.now().isoformat()
                contents = [m['content'] for m in memories]
                
                # Generate Vector Embeddings (bulk semantic)
                loop = asyncio.get_running_loop()
                embeddings = await loop.run_in_executor(
                    None, lambda: self.model.encode(contents, show_progress_bar=False).tolist()
                )
                
                categories = [m.get('category', 'general') for m in memories]
                metadatas = [m.get('metadata', {}) for m in memories]
                
                vector_ids = []
                for c, m in zip(contents, metadatas):
                    if m and 'path' in m and 'chunk_index' in m:
                        vector_ids.append(hashlib.md5(f"{m['path']}_{m['chunk_index']}".encode()).hexdigest())
                    else:
                        vector_ids.append(hashlib.md5(c.encode()).hexdigest())
                
                # 1. Save to Chroma (bulk upsert)
                chroma_metadatas = [{"category": cat, "timestamp": timestamp} for cat in categories]
                # Merge original metadata if provided
                for c_meta, m_meta in zip(chroma_metadatas, metadatas):
                    if m_meta:
                        # Convert dicts or lists in metadata to strings, as Chroma only accepts str/int/float/bool
                        safe_meta = {k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in m_meta.items()}
                        c_meta.update(safe_meta)
                        
                self.collection.upsert(
                    ids=vector_ids,
                    embeddings=embeddings,
                    documents=contents,
                    metadatas=chroma_metadatas
                )
                
                # 2. Save to SQLite (bulk insert)
                cursor = self.db_conn.cursor()
                rows = []
                for cat, content, meta, v_id in zip(categories, contents, metadatas, vector_ids):
                    meta_json = json.dumps(meta) if meta else "{}"
                    rows.append((timestamp, cat, content, meta_json, v_id))
                    
                cursor.executemany(
                    "INSERT OR IGNORE INTO episodic_memories (timestamp, category, content, metadata_json, vector_id) VALUES (?, ?, ?, ?, ?)",
                    rows
                )
                self.db_conn.commit()
                
                if self.core and not silent:
                    await self.core.log(f"✅ Bulk Memories Saved: {len(memories)} chunks", priority=5)
                return vector_ids
            except Exception as e:
                if self.core:
                    await self.core.log(f"❌ save_memories_bulk failed: {e}", priority=1)
                raise

    async def query_memory(self, query: str, n_results: int = 5, category: str = None,
                           exclude_categories=None):
        """Query memory by meaning (semantic), with optional category filter.

        category           — restrict to ONE category (wins over exclude).
        exclude_categories — iterable of categories to filter OUT (Chroma $nin).
        """
        async with self._lock:
            # SentenceTransformer encode is cpu-bound, but we run in thread to avoid blocking loop
            # For now, keeping it simple as this is a local small model
            # Offload CPU-bound encode to thread pool to avoid blocking event loop
            loop = asyncio.get_running_loop()
            query_embedding = await loop.run_in_executor(
                None, lambda: self.model.encode([query], show_progress_bar=False)[0].tolist()
            )

            # Build Filter
            where_filter = None
            if category:
                where_filter = {"category": category}
            elif exclude_categories:
                where_filter = {"category": {"$nin": list(exclude_categories)}}
                
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

    async def get_all_memories(self, limit: int = 10):
        """Get the most recent episodic memories."""
        async with self._lock:
            c = self.db_conn.cursor()
            c.execute("SELECT timestamp, category, content FROM episodic_memories ORDER BY id DESC LIMIT ?", (limit,))
            return c.fetchall()

    async def list_memories(self, limit: int = 50, category: str = None,
                            exclude_categories=('codebase_index',)):
        """List recent memories with their vector_id (needed for deletion).
        Excludes bulky code-index chunks by default. Returns list of dicts."""
        async with self._lock:
            c = self.db_conn.cursor()
            sql = "SELECT id, timestamp, category, content, vector_id FROM episodic_memories"
            params = []
            where = []
            if category:
                where.append("category = ?")
                params.append(category)
            elif exclude_categories:
                where.append("category NOT IN (%s)" % ",".join("?" * len(exclude_categories)))
                params.extend(exclude_categories)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(int(limit))
            c.execute(sql, params)
            rows = c.fetchall()
        return [
            {"id": r[0], "timestamp": r[1], "category": r[2],
             "content": r[3], "vector_id": r[4]}
            for r in rows
        ]

    async def category_counts(self):
        """Return {category: count} across all stored memories."""
        async with self._lock:
            c = self.db_conn.cursor()
            c.execute("SELECT category, COUNT(*) FROM episodic_memories GROUP BY category ORDER BY COUNT(*) DESC")
            return {row[0] or 'uncategorized': row[1] for row in c.fetchall()}

    async def delete_memory(self, vector_id: str):
        """Delete a single memory from both the vector store and SQLite."""
        if not vector_id:
            return False
        async with self._lock:
            try:
                self.collection.delete(ids=[vector_id])
            except Exception:
                pass  # may already be gone from Chroma
            c = self.db_conn.cursor()
            c.execute("DELETE FROM episodic_memories WHERE vector_id = ?", (vector_id,))
            deleted = c.rowcount
            self.db_conn.commit()
        return deleted > 0

    # ── V2.0: Continuous Memory Synthesis Daemon ─────────────────────

    SYNTH_CATEGORIES = ('general', 'auto_compacted_memory', 'conversation', 'manual')

    def ensure_synthesis_daemon(self, interval=900):
        """Lazily start the background synthesis/pruning loop (idempotent)."""
        t = getattr(self, '_synth_task', None)
        if t is not None and not t.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._synth_task = loop.create_task(self._synthesis_daemon(interval))

    async def _synthesis_daemon(self, interval):
        await asyncio.sleep(120)  # let boot settle before the first cycle
        while True:
            try:
                stats = await self.synthesize_and_prune()
                if self.core and stats and (stats['pruned'] or stats['synthesized']):
                    await self.core.log(
                        f"🧬 Memory Synthesis: {stats['synthesized']} beliefs distilled, "
                        f"{stats['pruned']} duplicate vectors pruned.", priority=2)
            except Exception as e:
                if self.core:
                    await self.core.log(f"[Memory] Synthesis cycle failed: {e}", priority=2)
            await asyncio.sleep(interval)

    async def synthesize_and_prune(self, min_cluster=5, prune_distance=0.05, max_prune_checks=40):
        """One maintenance cycle: prune near-duplicate vectors, then distill
        unsynthesized raw memories into a compact 'synthesized_belief'."""
        stats = {'pruned': 0, 'synthesized': 0}

        # ── Phase 1: near-duplicate vector pruning ──
        async with self._lock:
            c = self.db_conn.cursor()
            c.execute(
                "SELECT id, content, vector_id FROM episodic_memories "
                "WHERE category != 'codebase_index' ORDER BY id DESC LIMIT ?",
                (max_prune_checks,))
            recent = c.fetchall()

        for row_id, content, vector_id in recent:
            if not content or not vector_id:
                continue
            try:
                # Exclude code chunks so cross-category matches can't trigger
                # deletion of (or by) codebase_index entries.
                hits = await self.query_memory(content, n_results=3,
                                               exclude_categories=('codebase_index',))  # locks internally
            except Exception:
                continue
            for h in hits:
                if h['id'] == vector_id:
                    continue
                if (h.get('distance') or 1.0) < prune_distance:
                    async with self._lock:
                        c = self.db_conn.cursor()
                        c.execute("SELECT id FROM episodic_memories WHERE vector_id = ?", (h['id'],))
                        other = c.fetchone()
                        # Keep the newer record, delete the older duplicate
                        if other and other[0] < row_id:
                            try:
                                self.collection.delete(ids=[h['id']])
                                c.execute("DELETE FROM episodic_memories WHERE vector_id = ?", (h['id'],))
                                self.db_conn.commit()
                                stats['pruned'] += 1
                            except Exception:
                                pass

        # ── Phase 2: distill raw memories into a synthesized belief ──
        async with self._lock:
            c = self.db_conn.cursor()
            placeholders = ",".join("?" for _ in self.SYNTH_CATEGORIES)
            c.execute(
                f"SELECT id, content FROM episodic_memories "
                f"WHERE synthesized = 0 AND category IN ({placeholders}) "
                f"ORDER BY id DESC LIMIT 40",
                self.SYNTH_CATEGORIES)
            raw_rows = c.fetchall()

        if len(raw_rows) < min_cluster:
            return stats

        gw = getattr(self.core, 'gateway', None) if self.core else None
        if not gw:
            return stats

        digest = "\n".join(f"- {str(content)[:500]}" for _, content in raw_rows)
        prompt = (
            "You are a long-term memory consolidation process. Distill the raw memory fragments below "
            "into AT MOST 8 durable, high-value belief statements (user facts/preferences, project facts, "
            "hard lessons learned). Drop ephemeral details. One belief per line, no numbering.\n\n"
            f"RAW FRAGMENTS:\n{digest}"
        )
        # This daemon runs in its own asyncio task, so this contextvar-backed
        # provider/model override is isolated and cannot leak into live sessions.
        orig_p, orig_m = gw.llm.provider, gw.llm.model
        try:
            fast_model = (self.core.config.get('models', {}).get('summarizer_model')
                          or self.core.config.get('models', {}).get('planner_fallback_model'))
            fast_prov = (self.core.config.get('models', {}).get('summarizer_provider')
                         or self.core.config.get('models', {}).get('planner_fallback_provider'))
            if fast_model:
                known = {"openrouter", "ollama", "nvidia", "groq", "mistral", "anthropic", "google", "openai"}
                if "/" in fast_model and fast_model.split("/", 1)[0].lower() in known:
                    gw.llm.provider, gw.llm.model = fast_model.split("/", 1)
                else:
                    gw.llm.provider = fast_prov or orig_p
                    gw.llm.model = fast_model
            beliefs = await gw._call_llm_resilient([{"role": "user", "content": prompt}])
        finally:
            gw.llm.provider, gw.llm.model = orig_p, orig_m

        beliefs = str(beliefs).strip()
        if not beliefs or "[ERROR]" in beliefs:
            return stats

        await self.save_memory(  # locks internally
            f"Synthesized beliefs (distilled from {len(raw_rows)} memories):\n{beliefs}",
            category="synthesized_belief",
            metadata={"source_count": len(raw_rows)},
            silent=True,
        )
        async with self._lock:
            c = self.db_conn.cursor()
            c.executemany("UPDATE episodic_memories SET synthesized = 1 WHERE id = ?",
                          [(rid,) for rid, _ in raw_rows])
            self.db_conn.commit()
        stats['synthesized'] = 1
        return stats

    def close(self):
        self.db_conn.close()

# --- Automated Test Suite ---
async def run_self_test():
    print("\n[RUNNING GALACTIC MEMORY SELF-TEST...]")
    mem = GalacticMemory()
    
    # Test 1: Save Episodic Memory (F100 Context)
    print("\n1. Saving F100 Memory...")
    await mem.save_memory(
        "Installed the Holley Sniper EFI on the 352FE today. It's running rich at idle and smells like raw gas. Need to tune the IAC curve.",
        category="f100_truck"
    )
    
    # Test 2: Save Episodic Memory (AI Dev Context)
    print("2. Saving AI Dev Memory...")
    await mem.save_memory(
        "Refactored telegram_bridge_fixed.py to use async waits. The old sleep loops were causing timeouts.",
        category="ai_development"
    )

    # Test 3: Semantic Query (The Magic Part)
    print("\n3. Testing Semantic Search...")
    print("   Query: 'Why does my truck smell like gas?'")
    
    results = await mem.query_memory("Why does my truck smell like gas?", n_results=2)
    
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
    results_cat = await mem.query_memory("Refactored telegram", n_results=2, category="ai_development")
    if results_cat and "telegram" in results_cat[0]['content'].lower():
        print("   [SUCCESS] Category filtering works.")
    else:
        print("   [WARNING] Category filtering returned unexpected results.")

    mem.close()
    print("\n[SELF-TEST COMPLETE] Galactic Memory Core is online.")

if __name__ == "__main__":
    # If run directly, execute the self-test
    asyncio.run(run_self_test())
