import os
from google import genai
from google.oauth2 import service_account

def list_models():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"
    
    # Auth
    credentials = service_account.Credentials.from_service_account_file(creds_path)
    
    client = genai.Client(
        vertex=True,
        project=project,
        location=location,
        credentials=credentials
    )
    
    print(f"Listing models for project {project} in {location}...")
    try:
        # Modern SDK model listing
        models = client.models.list()
        print("Available Models:")
        for m in models:
            # Model object contains name (full path) and model_id (just the ID)
            print(f" - ID: {m.name} | Display: {m.display_name if hasattr(m, 'display_name') else 'N/A'}")
    except Exception as e:
        print(f"Error listing models: {str(e)}")

if __name__ == "__main__":
    list_models()
