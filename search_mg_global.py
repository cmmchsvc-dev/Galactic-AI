import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def search_global_mg():
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
    
    # Try global search (no project ID)
    loc = "us-central1"
    url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/locations/{loc}/publisherModels:search"
    
    payload = {
        "filter": "minimax"
    }
    
    print(f"--- Searching Global Model Garden ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                for m in data.get('publisherModels', []):
                    print(f"   {m.get('name')} | {m.get('displayName')}")
            else:
                print(f"Error: {response.text[:500]}")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(search_global_mg())
