import os

FILE_PATH = r"F:\Galactic AI\gateway_v2.py"

def wipe_broken_lines():
    if not os.path.exists(FILE_PATH):
        print("❌ File not found.")
        return

    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    # We are going to look for the specific broken line text
    target_text = 'if provider == "ollama" and "```json" in str(body):'
    
    found = False
    for line in lines:
        # Skip the broken if statement and any 'pass' or comments we added
        if target_text in line or "# --- CLEAN GALACTIC FIX" in line or "# --- RECOVERED OLLAMA FIX" in line:
            found = True
            print(f"🗑️ Found and removed broken line: {line.strip()}")
            continue
        
        # Also skip any line that is just 'pass' right after that area
        if found and line.strip() == "pass":
            continue
            
        new_lines.append(line)

    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    if found:
        print("✅ Broken code wiped. The file should now be syntactically correct.")
    else:
        print("❓ Could not find the broken line. You might need to open the file in VS Code and go to line 3533 manually.")

if __name__ == "__main__":
    wipe_broken_lines()