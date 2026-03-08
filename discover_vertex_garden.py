import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_vertex_models_discovery():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    # Try common regions
    regions = ["us-central1", "us-east4", "us-west1", "europe-west1", "asia-northeast1"]
    
    # Auth
    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    auth_req = Request()
    credentials.refresh(auth_req)
    access_token = credentials.token
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    
    print(f"--- Discovering Vertex Models for {project} ---")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Foundation Models listing is limited, but we can try the Model Garden endpoints
        for loc in regions:
            print(f"\nChecking region: {loc}...")
            # Try listing models via the standard Resource Manager / AI Platform list
            url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/models"
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    models = data.get('models', [])
                    print(f"Found {len(models)} models.")
                    for m in models:
                        print(f" - {m.get('displayName')} (ID: {m.get('name')})")
                else:
                    print(f"Status {response.status_code} for {url}")
            except Exception as e:
                print(f"Error checking {loc}: {e}")

        # 2. Try the "publishers" list if supported
        print("\n--- Checking Publishers ---")
        loc = "us-central1"
        url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers"
        try:
            response = await client.get(url, headers=headers)
            print(f"Publishers List Status: {response.status_code}")
            if response.status_code == 200:
                print(response.json())
        except: pass

if __name__ == "__main__":
    asyncio.run(list_vertex_models_discovery())
