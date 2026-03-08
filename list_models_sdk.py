
import asyncio
import os
from google import genai

async def list_models_sdk():
    project = "gen-lang-client-0901634078"
    location = "us-central1"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location
    )
    
    print(f"Listing models for project {project} in {location}...")
    try:
        # The list_models method in GenAI SDK
        for model in client.models.list():
            print(f" - {model.name}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_models_sdk())
