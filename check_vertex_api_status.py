import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def check_api_enabled():
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
    
    url = f"https://serviceusage.googleapis.com/v1/projects/{project}/services/aiplatform.googleapis.com"
    
    print(f"Checking API status: {url}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            state = data.get('state')
            print(f"API State: {state}")
            if state == "ENABLED":
                print("Vertex AI API is ENABLED.")
            else:
                print("Vertex AI API is DISABLED.")
        else:
            print("FAILURE!")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(check_api_enabled())
