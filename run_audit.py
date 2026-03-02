import asyncio
import os
from galactic_core_v2 import GalacticCore

async def main():
    print("Initializing Galactic Core...")
    core = GalacticCore()
    await core.setup_systems()
    
    # Check gateway tools
    tools = getattr(core.gateway, 'tools', {})
    if 'gemini_cli_task' in tools:
        print("Starting Gemini CLI task...")
        task_fn = tools['gemini_cli_task']['fn']
        result = await task_fn({
            'task': 'Stability Audit: Identify any remaining blocking I/O calls in gateway_v2.py and skills/core/system_tools.py.'
        })
        print("\n--- RESULT ---\n")
        print(result)
    else:
        print("Error: gemini_cli_task not found.")

if __name__ == "__main__":
    asyncio.run(main())
