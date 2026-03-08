import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def discover_minimax_path():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
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
    
    # Try common regions to list models
    regions = ["us-central1", "global", "europe-west1"]
    
    print(f"--- Searching for 'minimax' in Foundation Models ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            # Note: The endpoint for listing foundation models can be different.
            # We'll try listing models in the project/location
            url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/models"
            if loc == "global":
                url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/global/models"
            
            print(f"Checking region {loc}...")
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    models = data.get('models', [])
                    for m in models:
                        name = m.get('name', '')
                        display = m.get('displayName', '')
                        if "minimax" in name.lower() or "minimax" in display.lower():
                            print(f"   [FOUND] {display} | Path: {name}")
                else:
                    print(f"   Status {response.status_code}")
            except Exception as e:
                print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(discover_minimax_path())
