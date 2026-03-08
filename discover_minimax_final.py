import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def discover_minimax_final():
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
    
    regions = ["us-central1", "us-east4", "europe-west1", "global"]
    publishers = ["minimax", "minimax-ai"]
    versions = ["v1", "v1beta1"]
    methods = ["rawPredict", "predict"]
    
    print(f"--- Comprehensive MiniMax Discovery ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
            for pub in publishers:
                for ver in versions:
                    for method in methods:
                        url = f"https://{host}/{ver}/projects/{project}/locations/{loc}/publishers/{pub}/models/minimax-m2:{method}"
                        
                        # Simplified payload for connectivity test
                        payload = {
                            "model": "minimax-m2",
                            "messages": [{"role": "user", "content": "hi"}]
                        }
                        if method == "predict":
                            payload = {"instances": [{"prompt": "hi"}]}
                        
                        try:
                            response = await client.post(url, headers=headers, json=payload)
                            if response.status_code == 200:
                                print(f"SUCCESS! | Loc: {loc:15} | Pub: {pub:10} | Ver: {ver:10} | Method: {method:10}")
                                print(f"   URL: {url}")
                                return
                            elif response.status_code not in (404, 403):
                                print(f"   {response.status_code} | Loc: {loc:15} | Pub: {pub:10} | Ver: {ver:10} | Method: {method:10}")
                        except Exception as e:
                            pass

if __name__ == "__main__":
    asyncio.run(discover_minimax_final())
