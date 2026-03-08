import os
from google.cloud import aiplatform
from google.oauth2 import service_account

def list_foundation_models():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1" # Many models are registered here even if global

    print(f"--- Listing Foundation Models via SDK ({location}) ---")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        aiplatform.init(project=project, location=location, credentials=credentials)
        
        # We can't directly list 'foundation' models easily without the 'ModelServiceClient'
        from google.cloud import aiplatform_v1
        
        client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
        client = aiplatform_v1.ModelServiceClient(credentials=credentials, client_options=client_options)
        
        # This lists models in the project. For foundation models, we often check the 'publishers' collection.
        # But let's try a broad test.
        print(f"Checking models in {location}...")
        parent = f"projects/{project}/locations/{location}"
        response = client.list_models(parent=parent)
        
        found = False
        for model in response:
            found = True
            print(f"Model: {model.display_name} | ID: {model.name}")
            
        if not found:
            print("No models found in this projects/location.")

        # Let's try listing publishers for research
        print("\n--- Checking Publishers ---")
        # The SDK doesn't have a direct 'list_publishers' that is easy to call, 
        # but we can try to access the Model Garden models.
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_foundation_models()
