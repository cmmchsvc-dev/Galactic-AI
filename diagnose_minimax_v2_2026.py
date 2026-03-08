import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_v2_2026():
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
    
    # Variants to try
    configs = [
        {"ver": "v1beta1", "loc": "global", "type": "rawPredict"},
        {"ver": "v1beta1", "loc": "us-central1", "type": "predict"},
        {"ver": "v1", "loc": "global", "type": "predict"},
        {"ver": "v1", "loc": "us-central1", "type": "predict"},
    ]
    
    print(f"--- Diagnosing MiniMax M2 (v1beta1 / predict) ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for cfg in configs:
            ver = cfg['ver']
            loc = cfg['loc']
            ctype = cfg['type']
            
            base_url = "https://global-aiplatform.googleapis.com" if loc == "global" else f"https://{loc}-aiplatform.googleapis.com"
            url = f"{base_url}/{ver}/projects/{project}/locations/{loc}/publishers/minimax/models/minimax-m2:{ctype}"
            
            payload = {
                "instances": [{"role": "user", "content": "hi"}] if ctype == "predict" else None,
                "messages": [{"role": "user", "content": "hi"}] if ctype == "rawPredict" else None
            }
            if ctype == "predict":
                 payload["parameters"] = {}
            
            print(f"Test: {ver} | {loc:15} | {ctype:10} ...")
            try:
                response = await client.post(url, headers=headers, json=payload)
                print(f"   Status: {response.status_code}")
                if response.status_code == 200:
                    print("   SUCCESS!!!")
                    return
                elif response.status_code != 404:
                    print(f"   Error: {response.text[:100]}")
            except Exception as e:
                print(f"   Failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_v2_2026())
