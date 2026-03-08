import os

def patch_gateway_maas_final():
    target_file = r"c:\Users\Chesley\Galactic AI\gateway_v3.py"
    with open(target_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for the URL build logic inside the cascade loop
        if 'if publisher == "google":' in line and i + 1 < len(lines) and 'url = f"https://{loc}-aiplatform' in lines[i+1]:
            new_lines.append(line)
            new_lines.append(lines[i+1])
            i += 2
            
            # Now handle the else (partner models and anthropic)
            if 'else:' in lines[i]:
                new_lines.append(lines[i])
                i += 1
                # Skip the old partner logic up to the try: block
                while i < len(lines) and 'try:' not in lines[i]:
                    i += 1
                
                # Insert our generalized Partner URL logic (MaaS OpenAI endpoint)
                new_lines.append('\n')
                new_lines.append('                        # Partner Models (MiniMax, GLM) route to OpenAI-compatible MaaS endpoint in global\n')
                new_lines.append('                        if loc == "global" and (publisher in ("minimax", "minimax-ai", "minimaxai") or "glm" in mid.lower()):\n')
                new_lines.append('                            # Generalized mapping for partner model billing IDs\n')
                new_lines.append('                            if "minimax-m2" in mid.lower():\n')
                new_lines.append('                                mid_effective = "minimaxai/minimax-m2-maas"\n')
                new_lines.append('                            elif "glm-5" in mid.lower():\n')
                new_lines.append('                                mid_effective = "zai-org/glm-5-maas"\n')
                new_lines.append('                            else:\n')
                new_lines.append('                                mid_effective = mid\n')
                new_lines.append('                            \n')
                new_lines.append('                            url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi/chat/completions"\n')
                new_lines.append('                            payload["model"] = mid_effective\n')
                new_lines.append('                        else:\n')
                new_lines.append('                            # Standard Publisher/Model path\n')
                new_lines.append('                            base_url = f"https://aiplatform.googleapis.com" if loc == "global" else f"https://{loc}-aiplatform.googleapis.com"\n')
                new_lines.append('                            url = f"{base_url}/v1/projects/{project}/locations/{loc}/publishers/{publisher}/models/{mid}:{stream_type}"\n')
                continue
        
        new_lines.append(line)
        i += 1

    with open(target_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print("Generalized Patch (MiniMax/GLM) applied to gateway_v3.py")

if __name__ == "__main__":
    patch_gateway_maas_final()
