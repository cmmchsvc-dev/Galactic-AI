import os
import hashlib
from collections import defaultdict
import csv

def get_hash(file_path):
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def find_duplicates():
    # Only scan relevant user drives to avoid system permission hell
    drives = ['C:\\Users\\Chesley'] 
    
    files_by_size = defaultdict(list)
    results = []

    # First pass: collect by size
    for drive in drives:
        for root, _, files in os.walk(drive):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    size = os.path.getsize(filepath)
                    files_by_size[size].append(filepath)
                except:
                    continue

    # Second pass: hash only files with shared sizes
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
                    duplicates.append({
                        'size': size,
                        'hash': sha,
                        'files': matched_paths
                    })
    return duplicates

dupes = find_duplicates()
with open('duplicate_report.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['Size', 'FilePaths'])
    for d in dupes:
        writer.writerow([d['size'], ' | '.join(d['files'])])

print(f"Report generated: duplicate_report.csv with {len(dupes)} groups of duplicates.")
