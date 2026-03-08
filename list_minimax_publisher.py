import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_publisher_specific_models():
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
    
    regions = ["us-central1", "global"]
    publishers = ["minimax", "minimax-ai", "google"]
    
    print(f"--- Listing Models for Publishers ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
            for pub in publishers:
                url = f"https://{host}/v1beta1/locations/{loc}/publishers/{pub}/models"
                print(f"Checking {pub} in {loc} ({url})...")
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get('models', [])
                        print(f"Found {len(models)} models for {pub} in {loc}.")
                        for m in models:
                            print(f"   - {m.get('name')}")
                    else:
                        print(f"   Status {response.status_code}")
                except Exception as e:
                    print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_publisher_specific_models())
