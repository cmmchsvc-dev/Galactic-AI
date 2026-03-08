import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_all_publisher_models():
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
    
    # Common publishers on Vertex
    publishers = ["google", "anthropic", "mistral", "meta", "minimax", "zhipu-ai", "minimax-ai", "minimax-m2"]
    loc = "us-central1"
    
    print(f"--- Listing Models for Common Publishers in {loc} ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for pub in publishers:
            url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{loc}/publishers/{pub}/models"
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    models = data.get('models', [])
                    print(f"[{pub}] Found {len(models)} models.")
                    for m in models:
                        print(f"   - {m.get('name')}")
                elif response.status_code != 404:
                    print(f"[{pub}] {response.status_code}")
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(list_all_publisher_models())
