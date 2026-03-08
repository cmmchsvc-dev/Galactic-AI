import os
import hashlib
from collections import defaultdict

def get_hash(file_path):
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None

def find_duplicates(start_path):
    files_by_size = defaultdict(list)
    
    # Walk directories, ignoring permission errors
    for root, dirs, files in os.walk(start_path, topdown=True):
        # Prevent climbing into too many deep dirs or system spots
        if 'AppData' in root or '.git' in root or 'node_modules' in root:
            continue
            
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                # Basic size filter: ignore teeny files
                stat = os.stat(filepath)
                if stat.st_size < 1024 * 50: # Only look at files > 50KB to speed this up
                    continue
                files_by_size[stat.st_size].append(filepath)
            except Exception:
                continue

    # Hash shared sizes
    duplicates = []
    for size, paths in files_by_size.items():
        if len(paths) > 1:
            size_hashes = defaultdict(list)
            for path in paths:
                sha = get_hash(path)
                if sha:
                    size_hashes[sha].append(path)
            
            for sha, matched_paths in size_hashes.items():
                if len(matched_paths) > 1:
                    duplicates.append({'size': size, 'files': matched_paths})
    return duplicates

# Focus on user dir, not EVERYTHING
results = find_duplicates(r'C:\Users\Chesley')

with open('duplicate_report.txt', 'w', encoding='utf-8') as f:
    for d in results:
        f.write(f"Size: {d['size']}\n")
        for path in d['files']:
            f.write(f"  {path}\n")
        f.write("\n")

print(f"Done. Found {len(results)} groups.")