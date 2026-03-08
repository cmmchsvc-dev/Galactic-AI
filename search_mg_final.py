import os
from google.cloud import aiplatform
from google.oauth2 import service_account

def search_model_garden_minimax():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"

    print(f"--- Searching Model Garden for 'minimax' ---")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        aiplatform.init(project=project, location=location, credentials=credentials)
        
        # We'll use the search method to find models
        # Note: ModelGarden is not always exposed via search_models in older SDKs,
        # but let's try to list 'publisher' models via the ModelServiceClient
        from google.cloud import aiplatform_v1beta1
        client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
        client = aiplatform_v1beta1.ModelServiceClient(credentials=credentials, client_options=client_options)
        
        # Searching publishers
        req = aiplatform_v1beta1.ListPublisherModelsRequest(
            parent=f"projects/{project}/locations/{location}",
            filter='display_name:"minimax"'
        )
        
        results = client.list_publisher_models(request=req)
        found = False
        for model in results:
            print(f"FOUND: {model.display_name} | {model.name}")
            found = True
            
        if not found:
            # Try without filter and manually check
            print("No models found with filter. Listing all and checking...")
            req_all = aiplatform_v1beta1.ListPublisherModelsRequest(
                parent=f"projects/799574214932/locations/{location}" # Use project number
            )
            results_all = client.list_publisher_models(request=req_all)
            for model in results_all:
                if "minimax" in model.display_name.lower():
                    print(f"FOUND (All): {model.display_name} | {model.name}")
                    found = True
        
        if not found:
            print("Still no minimax found in Model Garden.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    search_model_garden_minimax()
