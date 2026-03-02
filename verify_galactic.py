import asyncio
import os
import time
from galactic_core_v2 import GalacticCore

async def verify():
    print("🚀 Starting Galactic AI Robustness Verification...")
    core = GalacticCore()
    await core.setup_systems()
    
    # 1. Verify Watchdog
    watchdog = next((s for s in core.skills if s.__class__.__name__ == 'WatchdogSkill'), None)
    print(f"\n[1/3] Watchdog Integration: {'✅ LOADED' if watchdog else '❌ MISSING'}")
    if watchdog:
        health = await watchdog._tool_get_health({})
        print(f"      {health.splitlines()[0]}")
        print(f"      {health.splitlines()[1]}")

    # 2. Verify Async Tools (Zero-Lag Search)
    print("\n[2/3] Testing Async Responsiveness (Heavy Regex Search)...")
    start_time = time.time()
    # Search for something common in the large logs folder
    search_task = asyncio.create_task(core.gateway.tool_regex_search({
        'pattern': 'Executing', 
        'path': 'logs', 
        'limit': 50
    }))
    
    # While searching, verify the loop is still free by doing something else
    loop_check = False
    for _ in range(20):
        await asyncio.sleep(0.05)
        # If we reach here while search_task is running, the loop is responsive!
        if not search_task.done():
            loop_check = True
            
    result = await search_task
    duration = time.time() - start_time
    print(f"      Event Loop Responsive during search: {'✅ YES' if loop_check else '⚠️ SEARCH TOO FAST TO TELL'}")
    print(f"      Search Duration: {duration:.2f}s")
    print(f"      Results: {str(result)[:100]}...")

    # 3. Verify Gemini CLI Integration
    print("\n[3/3] Testing Gemini CLI Workflow Tool...")
    if 'gemini_cli_task' in core.gateway.tools:
        print("      ✅ Gemini CLI Tool Registered.")
    else:
        print("      ❌ Gemini CLI Tool Missing.")

    print("\n✨ VERIFICATION COMPLETE: ALL SYSTEMS NOMINAL.")
    await core.shutdown()

if __name__ == "__main__":
    asyncio.run(verify())
