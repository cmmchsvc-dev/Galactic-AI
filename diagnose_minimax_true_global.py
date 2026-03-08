import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_true_global():
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
    
    # Host is just aiplatform, location is global
    url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/minimax/models/minimax-m2:rawPredict"
    
    payload = {
        "model": "minimax-m2",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    print(f"--- Diagnosing True Global MiniMax ---")
    print(f"Testing URL: {url}...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                print("   SUCCESS!!!")
                print(response.json())
                return
            else:
                print(f"   Error: {response.text[:200]}")
        except Exception as e:
            print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_true_global())
