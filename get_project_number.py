import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def get_project_number():
    project_id = "gen-lang-client-0901634078"
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
    
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
    
    print(f"--- Getting Project Number for {project_id} ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"Project Number: {data.get('projectNumber')}")
            else:
                print(f"Error ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_project_number())
