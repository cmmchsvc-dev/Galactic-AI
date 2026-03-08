import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def diagnose_minimax_vertex():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    # Regions to test
    regions = ["global", "us-central1", "europe-west1", "europe-west4", "us-east4"]
    # Publisher variations
    publishers = ["minimax", "minimax-ai"]
    # Model ID variations
    model_ids = ["minimax-m2", "minimax-m2-turbo"]
    
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
    
    print(f"--- Diagnosing MiniMax M2 on Vertex for Project {project} ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for loc in regions:
            for pub in publishers:
                for mid in model_ids:
                    base_url = "https://global-aiplatform.googleapis.com" if loc == "global" else f"https://{loc}-aiplatform.googleapis.com"
                    url = f"{base_url}/v1/projects/{project}/locations/{loc}/publishers/{pub}/models/{mid}:rawPredict"
                    
                    payload = {
                        "model": mid,
                        "messages": [{"role": "user", "content": "hi"}]
                    }
                    
                    try:
                        response = await client.post(url, headers=headers, json=payload)
                        print(f"Region: {loc:15} | Pub: {pub:10} | ID: {mid:15} | Status: {response.status_code}")
                        if response.status_code == 200:
                            print("SUCCESS!!!")
                            return
                        elif response.status_code != 404:
                            print(f"   Error: {response.text[:100]}")
                    except Exception as e:
                        print(f"   Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_minimax_vertex())
