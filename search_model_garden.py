import os
from google.cloud import aiplatform
from google.oauth2 import service_account

def search_model_garden():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"

    print(f"--- Searching Model Garden for 'minimax' ---")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        aiplatform.init(project=project, location=location, credentials=credentials)
        
        # This is a bit internal, but let's try to list 'publisher' models via the ModelServiceClient
        from google.cloud import aiplatform_v1
        client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
        client = aiplatform_v1.ModelServiceClient(credentials=credentials, client_options=client_options)
        
        # The correct way to find if a model exists in Model Garden is via listing publisher models
        # But we previously saw 404. Let's try listing all publishers.
        
        # Actually, let's try to just 'predict' with a variety of potential IDs one last time in a loop
        # But let's check 'europe-west4' and 'us-east4' specifically.
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    search_model_garden()
