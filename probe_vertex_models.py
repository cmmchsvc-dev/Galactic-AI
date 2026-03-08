
import asyncio
import os
from google import genai
from google.genai import types

async def probe_models():
    project = "gen-lang-client-0901634078"
    location = "us-central1"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location
    )
    
    real_models = [
        "publishers/google/models/gemini-3.1-flash-lite-preview",
        "publishers/google/models/gemini-3.1-pro-preview"
    ]
    
    for model in real_models:
        print(f"Probing {model}...")
        try:
            # list_models or just try to generate a tiny response
            response = client.models.generate_content(
                model=model,
                contents='hi',
                config=types.GenerateContentConfig(max_output_tokens=1)
            )
            print(f"✅ {model}: SUCCESS")
        except Exception as e:
            print(f"❌ {model}: {e}")

if __name__ == "__main__":
    asyncio.run(probe_models())
