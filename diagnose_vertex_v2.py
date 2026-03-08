
import asyncio
import httpx
import json
import os
from google.oauth2 import service_account
import google.auth.transport.requests

async def diagnose():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    # Common Vertex locations for Anthropic
    locations = ["us-central1", "us-east5", "europe-west1", "us-east4", "asia-southeast1"]
    models_to_test = ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-3-5-sonnet-v2@20241022", "claude-3-5-sonnet@20240620"]

    print(f"🚀 Starting Vertex Deep Diagnostic for Project: {project}")
    
    try:
        creds = service_account.Credentials.from_service_account_file(creds_path)
        scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/cloud-platform'])
        auth_req = google.auth.transport.requests.Request()
        scoped_creds.refresh(auth_req)
        token = scoped_creds.token
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Check API Enablement
            print("\n🔍 Checking AI Platform API state...")
            usage_url = f"https://serviceusage.googleapis.com/v1/projects/{project}/services/aiplatform.googleapis.com"
            usage_res = await client.get(usage_url, headers=headers)
            usage_data = usage_res.json()
            api_state = usage_data.get('state', 'UNKNOWN')
            print(f"   State: {api_state}")

            # 2. List Models (if possible)
            print("\n🔍 Listing available Anthropic models (us-central1)...")
            list_url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/publishers/anthropic/models"
            list_res = await client.get(list_url, headers=headers)
            if list_res.status_code == 200:
                models = list_res.json().get('models', [])
                for m in models:
                    print(f"   ✅ Found Model: {m.get('name')}")
            else:
                print(f"   ⚠️ Could not list models (Status {list_res.status_code}): {list_res.text[:200]}")

            # 3. Connectivity Scan
            print("\n🔍 Scanning regional availability...")
            for model_id in models_to_test:
                print(f"\n   Testing Model: {model_id}")
                for loc in locations:
                    url = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/anthropic/models/{model_id}:rawPredict"
                    # Small payload just to test connectivity
                    payload = {
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 10
                    }
                    try:
                        res = await client.post(url, headers=headers, json=payload)
                        if res.status_code == 200:
                            print(f"      ✨ {loc:15} -> 200 OK")
                        else:
                            print(f"      📍 {loc:15} -> {res.status_code}")
                    except Exception as e:
                        print(f"      ❌ {loc:15} -> Error: {str(e)}")

    except Exception as e:
        print(f"🔥 Diagnostic Fatal Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(diagnose())
