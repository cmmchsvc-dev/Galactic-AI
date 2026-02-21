# Galactic AI Imprint Engine - Initializing Knowledge Ingestion
import os
import json
from memory_module import GalacticMemory

def imprint_workspace():
    """Ingests the user's workspace soul into the local Galactic Memory."""
    mem = GalacticMemory()
    workspace_path = "C:\\Users\\Chesley\\.openclaw\\workspace"
    files_to_imprint = ["MEMORY.md", "USER.md", "IDENTITY.md", "SOUL.md"]
    
    print("=== GALACTIC IMPRINT: Starting Knowledge Ingestion ===")
    
    for filename in files_to_imprint:
        path = os.path.join(workspace_path, filename)
        if os.path.exists(path):
            print(f"Ingesting: {filename}...")
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Store in chunks for better recall
                mem.store(content, {"source": filename, "type": "agent_essence"})
                print(f"Success: {filename} imprinted.")
        else:
            print(f"Skipping: {filename} not found.")
            
    print("=== IMPRINT COMPLETE: Byte's soul is now local. ===")

if __name__ == "__main__":
    imprint_workspace()
