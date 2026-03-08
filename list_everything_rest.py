import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_everything_rest():
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
    
    # Try the most general list endpoint
    loc = "us-central1"
    url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/models"
    
    print(f"--- Listing EVERYTHING via REST at {loc} ---")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                models = data.get('models', [])
                print(f"Found {len(models)} models.")
                for m in models:
                    print(f"   - {m.get('displayName')} | {m.get('name')}")
            else:
                print(f"Error: {response.text[:500]}")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(list_everything_rest())
