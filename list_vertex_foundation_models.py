import asyncio
import httpx
import os
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_vertex_models():
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
    
    # List models from publisher 'google'
    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models"
    
    print(f"Listing models from: {url}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            print(f"Found {len(models)} models.")
            for m in models[:20]:
                print(f" - {m.get('name')}")
        else:
            print("FAILURE!")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(list_vertex_models())
