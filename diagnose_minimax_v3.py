import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_v3():
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
    
    # Test cases: focus on us-central1 since it gave 400 (not 404)
    loc = "us-central1"
    tests = [
        {"ver": "v1beta1", "type": "rawPredict", "payload": {"messages": [{"role": "user", "content": "hi"}]}},
        {"ver": "v1", "type": "rawPredict", "payload": {"messages": [{"role": "user", "content": "hi"}]}},
        {"ver": "v1", "type": "predict", "payload": {"instances": [{"prompt": "hi"}]}},
        {"ver": "v1", "type": "predict", "payload": {"instances": [{"role": "user", "content": "hi"}]}},
        {"ver": "v1", "type": "predict", "payload": {"instances": [{"content": "hi"}]}},
    ]
    
    print(f"--- Diagnosing MiniMax M2 (Refined Payloads) ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for t in tests:
            ver = t['ver']
            ctype = t['type']
            payload = t['payload']
            
            url = f"https://{loc}-aiplatform.googleapis.com/{ver}/projects/{project}/locations/{loc}/publishers/minimax/models/minimax-m2:{ctype}"
            
            print(f"Test: {ver} | {ctype:10} | {str(payload)[:30]}...")
            try:
                response = await client.post(url, headers=headers, json=payload)
                print(f"   Status: {response.status_code}")
                if response.status_code == 200:
                    print("   SUCCESS!!!")
                    print(response.json())
                    return
                else:
                    print(f"   Error: {response.text[:150]}")
            except Exception as e:
                print(f"   Failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_v3())
