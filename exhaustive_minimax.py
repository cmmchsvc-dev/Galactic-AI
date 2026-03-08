import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def exhaustive_minimax_discovery():
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
    
    regions = ["us-central1", "us-east4", "global"]
    publishers = ["minimax", "minimax-ai", "google"]
    mids = ["minimax-m2", "minimax-m2-maas", "minimax-m2.1", "minimax-m2.1-maas"]
    vers = ["v1", "v1beta1"]
    methods = ["rawPredict", "predict"]
    
    print(f"--- Exhaustive MiniMax Discovery (Logging to file) ---")
    log_file = r"C:\Users\Chesley\Galactic AI\exhaustive_log_v2.txt"
    
    with open(log_file, "w", encoding="utf-8") as f_log:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for loc in regions:
                host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
                for pub in publishers:
                    for mid in mids:
                        for ver in vers:
                            for meth in methods:
                                url = f"https://{host}/{ver}/projects/{project}/locations/{loc}/publishers/{pub}/models/{mid}:{meth}"
                                
                                # Payload
                                if meth == "predict":
                                    payload = {"instances": [{"prompt": "hi"}], "parameters": {}}
                                else:
                                    payload = {
                                        "model": mid,
                                        "messages": [{"role": "user", "content": "hi"}]
                                    }
                                    
                                try:
                                    response = await client.post(url, headers=headers, json=payload)
                                    msg = f"[{response.status_code}] | {url}\n"
                                    print(msg.strip())
                                    f_log.write(msg)
                                    if response.status_code == 200:
                                        print(f"!!! SUCCESS !!! at {url}")
                                        f_log.write(f"   SUCCESS! Response: {response.text}\n")
                                        return
                                except Exception as e:
                                    pass

if __name__ == "__main__":
    asyncio.run(exhaustive_minimax_discovery())
