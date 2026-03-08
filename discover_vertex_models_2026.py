import asyncio
import httpx
import json
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def discover_models():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"
    
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
    
    # Discovery URL for foundation models
    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models"
    
    print(f"Discovering models at: {url}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                models = data.get('models', [])
                print(f"Found {len(models)} models.")
                for m in models:
                    # Model name is usually 'projects/{P}/locations/{L}/publishers/google/models/{ID}'
                    full_name = m.get('name', '')
                    model_id = full_name.split('/')[-1]
                    print(f" - {model_id} ({m.get('displayName', 'N/A')})")
            else:
                print(f"Error Body: {response.text}")
        except Exception as e:
            print(f"Request failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(discover_models())
