import os
import yaml
import json
import numpy as np

class GalacticMemory:
    """The Persistent Brain: Uses a simple local vector-store logic."""
    def __init__(self, core=None):
        self.core = core
        self.storage_path = "./memory/vector_store.json"
        self.ensure_dirs()
        self.knowledge_base = self.load_kb()

    def ensure_dirs(self):
        if not os.path.exists("./memory"):
            os.makedirs("./memory")

    def load_kb(self):
        if os.path.exists(self.storage_path):
            with open(self.storage_path, "r") as f:
                return json.load(f)
        return []

    def store(self, content, metadata=None):
        """Store a 'memory' with metadata."""
        entry = {
            "content": content,
            "metadata": metadata or {},
            "timestamp": str(os.path.getmtime(self.storage_path)) if os.path.exists(self.storage_path) else str(0)
        }
        self.knowledge_base.append(entry)
        self.save_kb()

    def save_kb(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.knowledge_base, f, indent=2)

    def recall(self, query):
        """Simple keyword-based recall for now (V1). V2 will use actual embeddings."""
        results = [m for m in self.knowledge_base if query.lower() in m["content"].lower()]
        return results[:5]

if __name__ == "__main__":
    mem = GalacticMemory()
    mem.store("F100 Firing Order: 1-5-4-2-6-3-7-8", {"category": "truck_specs"})
    print(f"Recalled: {mem.recall('F100')}")
