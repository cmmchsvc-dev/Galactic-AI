import os
from google.cloud import aiplatform
from google.oauth2 import service_account

def list_foundation_models():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    print(f"--- Listing Foundation Models via SDK ---")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        # We need to use the v1beta1 ModelServiceClient to list publisher models
        from google.cloud import aiplatform_v1beta1
        
        # Try a few common regions
        for location in ["us-central1", "us-east4", "europe-west1"]:
            client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
            client = aiplatform_v1beta1.ModelServiceClient(credentials=credentials, client_options=client_options)
            
            parent = f"projects/{project}/locations/{location}"
            print(f"Checking {location}...")
            
            # Note: listing 'publisherModels' is the way to see foundation models
            # We use the list_publisher_models method
            list_pub_req = aiplatform_v1beta1.ListPublisherModelsRequest(parent=parent)
            
            try:
                page_result = client.list_publisher_models(request=list_pub_req)
                for model in page_result:
                    name = model.name # projects/.../locations/.../publishers/.../models/...
                    display = model.display_name
                    if "minimax" in display.lower() or "minimax" in name.lower():
                        print(f"   [FOUND] {display} | {name}")
            except Exception as inner_e:
                print(f"   Error in {location}: {inner_e}")
                
    except Exception as e:
        print(f"General Error: {e}")

if __name__ == "__main__":
    list_foundation_models()
