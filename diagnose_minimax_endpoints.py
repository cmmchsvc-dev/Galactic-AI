import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_endpoints():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
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
    
    # Combinations of Hostname and Location segment
    # OpenRouter says "global", which might mean location="global" but endpoint could be us-central1
    tests = [
        {"host": "us-central1-aiplatform.googleapis.com", "loc": "us-central1"},
        {"host": "us-central1-aiplatform.googleapis.com", "loc": "global"},
        {"host": "aiplatform.googleapis.com", "loc": "us-central1"},
        {"host": "aiplatform.googleapis.com", "loc": "global"},
        {"host": "europe-west1-aiplatform.googleapis.com", "loc": "europe-west1"},
        {"host": "europe-west1-aiplatform.googleapis.com", "loc": "global"},
    ]
    
    payload = {
        "model": "minimax-m2",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    print(f"--- Deep Endpoint Discovery for MiniMax M2 ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for t in tests:
            host = t['host']
            loc = t['loc']
            
            # Try v1 and v1beta1
            for ver in ["v1", "v1beta1"]:
                url = f"https://{host}/{ver}/projects/{project}/locations/{loc}/publishers/minimax/models/minimax-m2:rawPredict"
                print(f"Testing URL: {url}...")
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    print(f"   Status: {response.status_code}")
                    if response.status_code == 200:
                        print("   SUCCESS!!!")
                        print(response.json())
                        return
                    elif response.status_code == 400:
                        print(f"   400 Error: {response.text[:200]}")
                    elif response.status_code == 403:
                        print(f"   403 (Permission Denied): {response.text[:200]}")
                except Exception as e:
                    print(f"   Request Error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_endpoints())
