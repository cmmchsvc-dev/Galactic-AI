# Galactic AI - Telegram Queue Flusher
import httpx
import asyncio
import yaml

async def flush():
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        
        token = config['telegram']['bot_token']
        url = f"https://api.telegram.org/bot{token}"
        client = httpx.AsyncClient(timeout=30.0)
        
        print("Contacting Telegram to flush stuck queue...")
        
        # Get the latest update ID
        resp = await client.get(f"{url}/getUpdates", params={"limit": 1})
        data = resp.json()
        
        if data.get("ok") and data.get("result"):
            last_id = data["result"][0]["update_id"]
            # Clear all old messages by sending an offset of -1 (latest)
            # and then making one more call to advance the cursor.
            await client.get(f"{url}/getUpdates", params={"offset": last_id + 1})
            print(f"SUCCESS: Queue Flushed! Skipped to ID: {last_id}")
        else:
            print("INFO: Queue already clean.")
        
        await client.aclose()
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    asyncio.run(flush())
