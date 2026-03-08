import os

file_path = r'c:\Users\Chesley\Galactic AI\gateway_v3.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Correct locations_to_try
old_locations = 'locations_to_try = [location, "global", "us-central1", "us-east5", "europe-west1"]'
new_locations = 'locations_to_try = [location, "global", "us-central1", "us-east4", "europe-west1", "europe-west4"]'

# Fix 2: Implement model variants and correct base_url
old_block = '''                # Build URL based on publisher requirements
                if publisher == "google":
                    url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/google/models/{model_id}:{stream_type}"
                else:
                    # Partner Models and Anthropic logic
                    base_url = f"https://global-aiplatform.googleapis.com" if loc == "global" else f"https://{loc}-aiplatform.googleapis.com"
                    url = f"{base_url}/v1/projects/{project}/locations/{loc}/publishers/{publisher}/models/{model_id}:{stream_type}"'''

new_block = '''                # Model variants: Some partners (MiniMax) on Vertex req -maas suffix
                model_variants = [model_id]
                if publisher not in ("google", "anthropic") and not model_id.endswith("-maas"):
                    model_variants.append(f"{model_id}-maas")

                for mid in model_variants:
                    # Build URL based on publisher requirements
                    if publisher == "google":
                        url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/google/models/{mid}:{stream_type}"
                    else:
                        # Partner Models and Anthropic logic
                        # FIX: global-aiplatform is invalid; use aiplatform.googleapis.com
                        base_url = f"https://aiplatform.googleapis.com" if loc == "global" else f"https://{loc}-aiplatform.googleapis.com"
                        url = f"{base_url}/v1/projects/{project}/locations/{loc}/publishers/{publisher}/models/{mid}:{stream_type}"'''

# Perform replacements
if old_locations in content:
    content = content.replace(old_locations, new_locations)
    print("Updated locations_to_try")
else:
    print("Could not find old_locations")

if old_block in content:
    # Need to be careful with indentation in the new block
    # The old_block starts with 16 spaces
    content = content.replace(old_block, new_block)
    print("Updated URL and variant logic")
else:
    # Try a more flexible match if exact match fails
    print("Could not find old_block exact match")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
