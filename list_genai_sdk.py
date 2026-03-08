import os
from google import genai
from google.oauth2 import service_account

def list_genai_models():
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    print(f"--- Listing Models via Google GenAI SDK ---")
    
    try:
        # The genai SDK can take a service account.
        # But for the simplest test, we can use the API key if we had one.
        # Since we have the JSON, let's use it to get a token or use the SDK's SA support if it has it.
        # Actually, the genai SDK for standard Gemini usually uses API keys, 
        # but let's see if we can list models available to this project.
        
        client = genai.Client(vertex=False, credentials=creds_path)
        
        for model in client.models.list():
            print(f"Name: {model.name} | Display: {model.display_name}")
            if "minimax" in model.name.lower() or "minimax" in model.display_name.lower():
                print(f"   [FOUND] {model.name}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_genai_models()
