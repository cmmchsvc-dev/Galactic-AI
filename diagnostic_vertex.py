
import os
import yaml
import asyncio
import google.auth
from google.cloud import aiplatform
from google.oauth2 import service_account

def test_vertex_auth():
    config_path = r"c:\Users\Chesley\Galactic AI\config.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    v_cfg = config.get('providers', {}).get('google_vertex', {})
    project = v_cfg.get('project_id')
    location = v_cfg.get('location', 'us-central1')
    creds_path = v_cfg.get('credentials_path')
    
    print(f"Project: {project}")
    print(f"Location: {location}")
    print(f"Credentials Path: {creds_path}")
    
    if not project or not creds_path:
        print("❌ Missing project_id or credentials_path in config.yaml")
        return

    if not os.path.exists(creds_path):
        print(f"❌ Credentials file not found: {creds_path}")
        return

    try:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        aiplatform.init(project=project, location=location, credentials=credentials)
        print("✅ Vertex AI initialized successfully.")
        
        print("Listing models in us-central1...")
        models = aiplatform.Model.list()
        if not models:
            print("  No models found.")
        for m in models:
            print(f"  - Model ID: {m.name}, Display Name: {m.display_name}")
            
    except Exception as e:
        print(f"❌ Vertex AI initialization failed: {str(e)}")

if __name__ == "__main__":
    test_vertex_auth()
