import asyncio
import httpx
import json
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def deep_diagnose():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    # Common 2026 Model IDs
    models = ["gemini-3.1-flash", "gemini-3.1-pro", "gemini-3.0-flash"]
    regions = ["us-central1", "us-east5", "europe-west9"] # Try a few diverse ones
    
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
    
    result_log = []
    
    for loc in regions:
        for model in models:
            url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/google/models/{model}:generateContent"
            payload = {"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}
            
            print(f"Testing {model} in {loc}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    log_entry = {
                        "model": model,
                        "location": loc,
                        "status": response.status_code,
                        "body": response.text[:500]
                    }
                    result_log.append(log_entry)
                    print(f"  Result: {response.status_code}")
                    if response.status_code == 200:
                        print(f"  !!! SUCCESS FOUND !!!")
                except Exception as e:
                    print(f"  Error: {str(e)}")

    print("\n--- FINAL DIAGNOSTIC REPORT ---")
    print(json.dumps(result_log, indent=2))

if __name__ == "__main__":
    asyncio.run(deep_diagnose())
