import os

def patch_gateway_gemini_suffix():
    target_file = r"c:\Users\Chesley\Galactic AI\gateway_v3.py"
    with open(target_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    patched = False
    while i < len(lines):
        line = lines[i]
        
        # Look for the Google model URL construction
        if 'if publisher == "google":' in line and i + 1 < len(lines) and 'url = f"https://{loc}-aiplatform' in lines[i+1]:
            new_lines.append(line)
            # Insert suffix stripping logic
            new_lines.append('                        # Strip -vertex suffix from internal model IDs for Google\n')
            new_lines.append('                        mid_clean = mid.replace("-vertex", "")\n')
            # Modify the next line to use mid_clean instead of mid
            old_url_line = lines[i+1]
            new_url_line = old_url_line.replace('{mid}', '{mid_clean}')
            new_lines.append(new_url_line)
            i += 2
            patched = True
            continue
            
        new_lines.append(line)
        i += 1

    if patched:
        with open(target_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print("Gemini Suffix Patch applied to gateway_v3.py")
    else:
        print("Could not find Google model URL construction to patch.")

if __name__ == "__main__":
    patch_gateway_gemini_suffix()
