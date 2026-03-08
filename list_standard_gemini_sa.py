import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def list_models_standard_api():
    project = "gen-lang-client-0901634078"
    creds_path = r"C:\Users\Chesley\Downloads\gen-lang-client-0901634078-9963164bc0db.json"
    
    # Auth for standard Google AI (Gemini) API
    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=['https://www.googleapis.com/auth/generative-language']
    )
    auth_req = Request()
    credentials.refresh(auth_req)
    access_token = credentials.token
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    
    # List models from standard API
    url = f"https://generativelanguage.googleapis.com/v1beta/models"
    
    print(f"Listing models from standard Gemini API: {url}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                print("SUCCESS!")
                data = response.json()
                for m in data.get('models', []):
                    print(f" - {m.get('name')} ({m.get('displayName')})")
            else:
                print(f"Error Body: {response.text}")
        except Exception as e:
            print(f"Request failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(list_models_standard_api())
