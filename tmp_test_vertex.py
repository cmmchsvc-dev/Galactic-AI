
import asyncio
import httpx
from google.oauth2 import service_account
import google.auth.transport.requests

async def test():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    loc = "us-central1"
    # Trial a set of known models
    models = ["claude-3-5-haiku@v1", "claude-3-5-sonnet@v2", "claude-3-5-sonnet@20240620", "claude-3-opus@20240229"]
    
    creds = service_account.Credentials.from_service_account_file(creds_path)
    scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/cloud-platform'])
    auth_req = google.auth.transport.requests.Request()
    scoped_creds.refresh(auth_req)
    token = scoped_creds.token
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for model_id in models:
            url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/anthropic/models/{model_id}:rawPredict"
            payload = {
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10,
                "anthropic_version": "vertex-2023-10-16"
            }
            try:
                res = await client.post(url, headers=headers, json=payload)
                print(f"Model: {model_id} -> Status: {res.status_code}")
                if res.status_code != 200:
                    print(f"  Error: {res.text[:200]}")
            except Exception as e:
                print(f"Model: {model_id} -> Exception: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test())
