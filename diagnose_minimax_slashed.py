import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_slashed():
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
    
    # Try the 'google' publisher with 'minimax/minimax-m2'
    # And also 'minimax' publisher with 'minimax-m2' but in us-central1
    tests = [
        {"host": "us-central1-aiplatform.googleapis.com", "loc": "us-central1", "pub": "google", "mid": "minimax/minimax-m2"},
        {"host": "us-central1-aiplatform.googleapis.com", "loc": "us-central1", "pub": "minimax", "mid": "minimax-m2"},
        {"host": "us-central1-aiplatform.googleapis.com", "loc": "us-central1", "pub": "minimax-ai", "mid": "minimax-m2"},
    ]
    
    payload = {
        "model": "minimax-m2",
        "messages": [{"role": "user", "content": "hi"}]
    }
    
    print(f"--- Diagnosing Slashed MiniMax Path ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for t in tests:
            url = f"https://{t['host']}/v1/projects/{project}/locations/{t['loc']}/publishers/{t['pub']}/models/{t['mid']}:rawPredict"
            print(f"Testing URL: {url}...")
            try:
                response = await client.post(url, headers=headers, json=payload)
                print(f"   Status: {response.status_code}")
                if response.status_code == 200:
                    print("   SUCCESS!!!")
                    return
                else:
                    print(f"   Error: {response.text[:200]}")
            except Exception as e:
                print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_slashed())
