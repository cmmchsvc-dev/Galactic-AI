import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def search_mg_catalog():
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
    
    # We'll search in us-central1 (default for Model Garden searches)
    loc = "us-central1"
    url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/locations/{loc}/publisherModels:search"
    
    payload = {
        "filter": "minimax"
    }
    
    print(f"--- Searching Model Garden Catalog ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Note: search is usually a GET or POST depending on version, 
            # but v1beta1 uses POST for search requests usually.
            # Actually, the endpoint is often projects/.../locations/.../publisherModels:search
            full_url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{loc}/publisherModels:search"
            
            response = await client.post(full_url, headers=headers, json=payload)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                models = data.get('publisherModels', [])
                print(f"Found {len(models)} matching models.")
                for m in models:
                    print(f"   Name: {m.get('name')}")
                    print(f"   Display: {m.get('displayName')}")
                    print(f"   Supported Methods: {m.get('supportedActions')}")
                    print("-" * 20)
            else:
                print(f"Error: {response.text[:500]}")
                
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(search_mg_catalog())
