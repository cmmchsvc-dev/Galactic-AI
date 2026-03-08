import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def brute_force_minimax():
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
    
    regions = ["us-central1", "us-east4", "europe-west4", "global", "asia-northeast1", "us-west1", "europe-west1"]
    publishers = ["minimax", "minimax-ai", "google", "minimax-cloud"]
    mids = ["minimax-m2", "minimax-m2-maas", "minimax-m2.1-maas", "minimax-m2.1"]
    vers = ["v1", "v1beta1"]
    
    print(f"--- BRUTE FORCE MINIMAX ---")
    log_file = r"C:\Users\Chesley\Galactic AI\brute_force_log.txt"
    
    with open(log_file, "w", encoding="utf-8") as f_log:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for loc in regions:
                host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
                for pub in publishers:
                    for mid in mids:
                        for ver in vers:
                            url = f"https://{host}/{ver}/projects/{project}/locations/{loc}/publishers/{pub}/models/{mid}:rawPredict"
                            try:
                                response = await client.post(url, headers=headers, json={"model": mid, "messages": []})
                                msg = f"[{response.status_code}] | {url}\n"
                                f_log.write(msg)
                                if response.status_code == 200:
                                    print(f"!!! FOUND !!! {url}")
                                    return
                                elif response.status_code != 404:
                                    print(f"[{response.status_code}] {url}")
                            except Exception:
                                pass

if __name__ == "__main__":
    asyncio.run(brute_force_minimax())
