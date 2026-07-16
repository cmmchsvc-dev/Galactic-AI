"""
Purge stale codebase_index chunks from semantic memory.
======================================================

The Neural Indexer only ever walks the CURRENT workspace root, but the vector
store still holds code chunks written by older installs of this project (e.g.
an old F:\\Galactic AI drive, or a copy that once lived on the Desktop). Those
chunks are frozen at whatever the code looked like back then, so `search_codebase`
can surface outdated implementations as if they were live.

This removes every codebase_index chunk whose path is NOT under the current
workspace root, from both ChromaDB and SQLite. Nothing else is touched:
personal/general/conversation memories are never considered, and current-repo
code chunks are kept (and are re-indexed automatically anyway).

Usage (run with Galactic AI STOPPED):
    python scripts/purge_stale_index.py            # dry run - just report
    python scripts/purge_stale_index.py --apply    # actually delete
"""

import argparse
import collections
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='perform the deletion (default: dry run)')
    ap.add_argument('--root', default=None, help='workspace root to keep (default: repo root)')
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    keep_root = os.path.abspath(args.root or repo_root).lower()

    import config_loader
    cfg = config_loader.load_config()
    logs_dir = cfg.get('paths', {}).get('logs', './logs')
    db_path = os.path.join(logs_dir, 'galactic_memory.db')
    if not os.path.exists(db_path):
        print(f"No memory DB at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT vector_id, metadata_json FROM episodic_memories WHERE category='codebase_index'")
    rows = c.fetchall()

    stale, kept = [], 0
    roots = collections.Counter()
    for vector_id, mj in rows:
        try:
            path = (json.loads(mj) or {}).get('path', '')
        except Exception:
            path = ''
        if path and path.lower().startswith(keep_root):
            kept += 1
        else:
            stale.append(vector_id)
            parts = path.split(os.sep)
            roots[os.sep.join(parts[:4]) or '(no path)'] += 1

    print(f"Keep root : {keep_root}")
    print(f"Total code chunks : {len(rows):,}")
    print(f"  current repo    : {kept:,}  (kept)")
    print(f"  stale/foreign   : {len(stale):,}  (purge candidates)\n")
    for r, n in roots.most_common(10):
        print(f"    {n:>7,}  {r}")

    if not stale:
        print("\nNothing to purge.")
        return 0

    if not args.apply:
        print("\nDRY RUN - nothing deleted. Re-run with --apply to purge.")
        return 0

    # Delete from Chroma first, then SQLite.
    print("\nPurging...")
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.join(logs_dir, 'chroma_data'))
        coll = client.get_or_create_collection(name="galactic_memory",
                                               metadata={"hnsw:space": "cosine"})
        for i in range(0, len(stale), 500):
            coll.delete(ids=stale[i:i + 500])
        print(f"  Chroma: removed {len(stale):,} vectors")
    except Exception as e:
        print(f"  Chroma delete failed: {e}")
        print("  Aborting so SQLite stays consistent with the vector store.")
        return 1

    for i in range(0, len(stale), 500):
        batch = stale[i:i + 500]
        c.execute("DELETE FROM episodic_memories WHERE vector_id IN (%s)"
                  % ",".join("?" * len(batch)), batch)
    conn.commit()
    print(f"  SQLite: removed {len(stale):,} rows")
    conn.close()
    print("\nDone. search_codebase now only sees the current repo.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
