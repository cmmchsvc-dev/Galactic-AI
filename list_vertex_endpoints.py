import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_vertex_endpoints():
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
    
    # Try multiple regions for endpoints
    regions = ["us-central1", "us-east4", "europe-west1"]
    
    print(f"--- Listing Vertex Endpoints ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/endpoints"
            print(f"Checking {loc}...")
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    endpoints = data.get('endpoints', [])
                    print(f"   Found {len(endpoints)} endpoints in {loc}.")
                    for e in endpoints:
                        print(f"      - {e.get('name')} | {e.get('displayName')}")
                else:
                    print(f"   Status: {response.status_code}")
            except Exception as e:
                print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_vertex_endpoints())
