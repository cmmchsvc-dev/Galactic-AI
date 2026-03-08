import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def brute_force_vertex():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    location = "us-central1"
    
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
    
    # More varied IDs for March 2026
    ids = [
        "gemini-3.1-flash", "gemini-3.1-pro", "gemini-3.1-pro-preview", 
        "gemini-3.0-pro", "gemini-3.0-flash", "gemini-3-pro", "gemini-3-flash",
        "gemini-1.5-pro", "gemini-1.5-flash" # legacy check
    ]
    
    for model_id in ids:
        url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model_id}:generateContent"
        payload = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
        
        print(f"Testing {model_id}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    print(f"SUCCESS with {model_id}!")
                    return
                else:
                    print(f"  {response.status_code}: {response.text[:100]}")
            except Exception as e:
                print(f"  Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(brute_force_vertex())
