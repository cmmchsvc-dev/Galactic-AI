"""
Galactic AI — Lite Memory (no-ML fallback)
==========================================

Stands in for `galactic_memory.GalacticMemory` when the heavy semantic stack
(torch + chromadb + sentence-transformers, ~2.5 GB) isn't installed — i.e. a
Lite install.

This is NOT a stub: memories are really stored, in a JSONL file, and recalled
by keyword scoring instead of vector similarity. You keep persistent memory
and the whole app boots and runs; you just trade semantic search ("what did I
say about my truck?" matching "F100 carburetor") for literal word overlap.

Installing the `memory` feature later swaps the real engine back in:
    python install.py --add memory

Implements the same surface the rest of the app calls: save_memory,
save_memories_bulk, query_memory, recall, imprint, imprint_file,
get_all_memories, list_memories, category_counts, delete_memory, close,
ensure_synthesis_daemon, plus the `index` and `db_conn` attributes.
"""

import hashlib
import json
import os
import re
from datetime import datetime

_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were', 'be',
    'been', 'to', 'of', 'in', 'on', 'at', 'for', 'with', 'my', 'me', 'i',
    'you', 'it', 'that', 'this', 'what', 'how', 'do', 'does', 'did', 'about',
    'where', 'when', 'who', 'why', 'which', 'am', 'has', 'have', 'had', 'his',
    'her', 'their', 'our', 'your', 'they', 'we', 'he', 'she', 'from', 'by',
    'as', 'if', 'so', 'not', 'no', 'yes', 'can', 'will', 'would', 'tell',
}


def _stem(w):
    """Very light suffix stripping so 'lives'/'living'/'lived' all match 'live'.
    Not linguistically rigorous - just enough to make keyword recall useful."""
    for suf in ('ing', 'ed', 'es', 's'):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _tokens(text):
    return {_stem(w) for w in re.findall(r'[a-z0-9]{2,}', str(text).lower())
            if w not in _STOPWORDS}


class NullMemory:
    """Keyword-based persistent memory. Drop-in for GalacticMemory."""

    is_lite = True   # lets diagnostics/UI say "Lite memory" honestly
    db_conn = None   # no SQLite in lite mode; callers must guard on this

    def __init__(self, core=None):
        self.core = core
        logs_dir = './logs'
        try:
            if core is not None and hasattr(core, 'config'):
                logs_dir = core.config.get('paths', {}).get('logs', './logs')
        except Exception:
            pass
        os.makedirs(logs_dir, exist_ok=True)
        self.store_path = os.path.join(logs_dir, 'memory_lite.jsonl')
        self._rows = []
        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self):
        try:
            if os.path.exists(self.store_path):
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            self._rows.append(json.loads(line))
                        except Exception:
                            continue
        except Exception:
            self._rows = []

    def _append(self, row):
        try:
            with open(self.store_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        except Exception:
            pass

    def _rewrite(self):
        try:
            with open(self.store_path, 'w', encoding='utf-8') as f:
                for r in self._rows:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
        except Exception:
            pass

    # ── compatibility attribute (discord_bridge / web_deck read this) ──

    @property
    def index(self):
        return {'memories': [r.get('content', '') for r in self._rows]}

    # ── write API ────────────────────────────────────────────────────

    async def save_memory(self, content, category="general", metadata=None, silent=False):
        content = str(content or '').strip()
        if not content:
            return None
        vector_id = hashlib.md5(content.encode('utf-8')).hexdigest()
        if any(r.get('vector_id') == vector_id for r in self._rows):
            return vector_id  # dedupe, same as the real engine
        row = {
            'vector_id': vector_id,
            'timestamp': datetime.now().isoformat(),
            'category': category or 'general',
            'content': content,
            'metadata': metadata or {},
        }
        self._rows.append(row)
        self._append(row)
        if not silent and self.core is not None:
            try:
                await self.core.log(f"✅ Memory saved [lite/{category}]: '{content[:60]}...'", priority=5)
            except Exception:
                pass
        return vector_id

    async def save_memories_bulk(self, memories, silent=True):
        out = []
        for m in (memories or []):
            out.append(await self.save_memory(
                m.get('content', ''), category=m.get('category', 'general'),
                metadata=m.get('metadata'), silent=silent))
        return out

    async def imprint(self, content, metadata=None):
        category = (metadata or {}).get('category', 'general')
        return await self.save_memory(content, category=category, metadata=metadata)

    async def imprint_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()[:20000]
            return await self.save_memory(
                content, category='file_imprint',
                metadata={'source': os.path.basename(path), 'path': str(path)}, silent=True)
        except Exception:
            return None

    # ── read API ─────────────────────────────────────────────────────

    async def query_memory(self, query, n_results=5, category=None, exclude_categories=None):
        """Keyword-overlap search. Mirrors the real engine's return shape:
        [{id, content, distance, metadata}] with distance in [0,1] (lower=better)."""
        q = _tokens(query)
        if not q:
            return []
        excl = set(exclude_categories or ())
        scored = []
        for r in self._rows:
            cat = r.get('category', 'general')
            if category and cat != category:
                continue
            if not category and cat in excl:
                continue
            overlap = len(q & _tokens(r.get('content', '')))
            if overlap:
                score = overlap / max(1, len(q))
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{
            'id': r.get('vector_id'),
            'content': r.get('content', ''),
            'distance': round(1.0 - s, 4),
            'metadata': dict(r.get('metadata') or {}, category=r.get('category', 'general')),
        } for s, r in scored[:n_results]]

    async def recall(self, query, limit=5, **kwargs):
        n = kwargs.get('top_k', limit)
        exclude = kwargs.get('exclude_categories', ('codebase_index',))
        return await self.query_memory(query, n_results=n,
                                       category=kwargs.get('category'),
                                       exclude_categories=exclude)

    async def get_all_memories(self, limit=10):
        rows = self._rows[-limit:][::-1]
        return [(r.get('timestamp'), r.get('category'), r.get('content')) for r in rows]

    async def list_memories(self, limit=50, category=None, exclude_categories=('codebase_index',)):
        out = []
        for r in reversed(self._rows):
            cat = r.get('category', 'general')
            if category and cat != category:
                continue
            if not category and cat in (exclude_categories or ()):
                continue
            out.append({'id': r.get('vector_id'), 'timestamp': r.get('timestamp'),
                        'category': cat, 'content': r.get('content', ''),
                        'vector_id': r.get('vector_id')})
            if len(out) >= limit:
                break
        return out

    async def category_counts(self):
        counts = {}
        for r in self._rows:
            c = r.get('category') or 'uncategorized'
            counts[c] = counts.get(c, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    async def delete_memory(self, vector_id):
        if not vector_id:
            return False
        before = len(self._rows)
        self._rows = [r for r in self._rows if r.get('vector_id') != vector_id]
        if len(self._rows) == before:
            return False
        self._rewrite()
        return True

    # ── lifecycle no-ops ─────────────────────────────────────────────

    def ensure_synthesis_daemon(self, interval=900):
        return None  # synthesis needs an LLM + vectors; not available in lite mode

    async def close(self):
        return None


def load_memory(core):
    """Return the best available memory engine.

    Prefers the full semantic engine; falls back to keyword memory when the
    ML stack isn't installed (Lite install) so the app still boots and
    remembers things. Returns (instance, is_lite).
    """
    try:
        from galactic_memory import GalacticMemory
    except Exception as e:
        print(f"[Memory] Semantic stack unavailable ({e.__class__.__name__}) - using Lite keyword memory. "
              f"Run 'python install.py --add memory' for semantic recall.")
        return NullMemory(core), True

    try:
        return GalacticMemory(core), False
    except TypeError as e:
        # Older signature during an in-place upgrade
        if "argument" in str(e) or "positional" in str(e):
            mem = GalacticMemory()
            mem.core = core
            return mem, False
        raise
    except Exception as e:
        print(f"[Memory] Semantic engine failed to start ({e}) - falling back to Lite keyword memory.")
        return NullMemory(core), True
