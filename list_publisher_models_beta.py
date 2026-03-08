import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_publisher_models_beta():
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
    
    regions = ["us-central1", "us-east4", "europe-west1"]
    
    print(f"--- Listing Publisher Models (v1beta1) ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            # Note: publisherModels listing often doesn't need project ID, but we try both
            urls = [
                f"https://{loc}-aiplatform.googleapis.com/v1beta1/locations/{loc}/publisherModels",
                f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{loc}/publisherModels"
            ]
            for url in urls:
                print(f"Checking {url}...")
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get('publisherModels', [])
                        print(f"Found {len(models)} foundation models in {loc}.")
                        for m in models:
                            disp = m.get('displayName', '')
                            name = m.get('name', '')
                            if "minimax" in disp.lower() or "minimax" in name.lower():
                                print(f"   [FOUND] {disp} | {name}")
                        if models: return # Stop if we found models
                    else:
                        print(f"   Status {response.status_code}")
                except Exception as e:
                    print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_publisher_models_beta())
