import asyncio
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

async def discover_minimax_publisher():
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
    
    # Try many potential publisher names
    publishers = ["minimax", "minimax-ai", "minimax_ai", "minimax-inc", "minimax-china", "minimax-intl", "minimax-official"]
    
    print(f"--- Discovering MiniMax Publisher Name ---")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for pub in publishers:
            # We'll try the v1beta1 endpoint which previously 200ed for 'minimax'
            url = f"https://us-central1-aiplatform.googleapis.com/v1beta1/publishers/{pub}/models"
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        print(f"[MATCH!] Publisher: {pub} | JSON: {data}")
                        return
                    else:
                        print(f"[EMPTY 200] Publisher: {pub}")
            except Exception as e:
                pass

if __name__ == "__main__":
    asyncio.run(discover_minimax_publisher())
