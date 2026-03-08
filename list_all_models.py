import os
from google.cloud import aiplatform_v1
from google.oauth2 import service_account

def list_all_models():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"

    credentials = service_account.Credentials.from_service_account_file(creds_path)
    client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
    client = aiplatform_v1.ModelServiceClient(credentials=credentials, client_options=client_options)

    parent = f"projects/{project}/locations/{location}"
    
    print(f"--- Listing All Models in {location} ---")
    try:
        response = client.list_models(parent=parent)
        for model in response:
            print(f"Model Display Name: {model.display_name}")
            print(f"Model Name (Path): {model.name}")
            print("-" * 20)
    except Exception as e:
        print(f"Error listing models: {e}")

    # Also try listing from the 'publishers' endpoint via raw request if SDK doesn't show them
    # Because foundation models aren't always in 'list_models'

if __name__ == "__main__":
    list_all_models()
