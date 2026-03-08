import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_global_loc():
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
    
    # Try global location on different regional endpoints
    hosts = [
        "us-central1-aiplatform.googleapis.com",
        "us-east4-aiplatform.googleapis.com",
        "europe-west1-aiplatform.googleapis.com",
        "aiplatform.googleapis.com"
    ]
    
    payload = {
        "model": "minimax-m2",
        "messages": [{"role": "user", "content": "hi"}]
    }
    
    print(f"--- Diagnosing Global Location for MiniMax M2 ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for host in hosts:
            for ver in ["v1", "v1beta1"]:
                url = f"https://{host}/{ver}/projects/{project}/locations/global/publishers/minimax/models/minimax-m2:rawPredict"
                print(f"Testing Host: {host} | Ver: {ver}...")
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    print(f"   Status: {response.status_code}")
                    if response.status_code == 200:
                        print("   SUCCESS!!!")
                        return
                except Exception as e:
                    print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_global_loc())
