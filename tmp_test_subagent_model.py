import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from galactic_core_v2 import GalacticCore
from gateway_v3 import GalacticGateway

async def test():
    core = GalacticCore()
    # Need to mimic a basic setup without full boot loop for a simple test
    from gateway_v3 import GalacticGateway
    from galactic_memory import GalacticMemory
    core.memory = GalacticMemory()
    gateway = GalacticGateway(core)
    core.gateway = gateway
    
    # Initialize tools list explicitly for test
    gateway.register_tools()
    
    # Load just the subagent skill to get spawn_subagent tool
    from skills.core.subagent_manager import SubAgentSkill
    subagent_skill = SubAgentSkill(core)
    core.skills = [subagent_skill]
    gateway.register_skill_tools([subagent_skill])

    print("Testing spawn_subagent with a custom model...")
    args = {
        "task": "Echo the word 'hello' and stop immediately.",
        "model": "ollama/llama3"
    }
    
    # 1. Spawn sub-agent
    res = await gateway.tools["spawn_subagent"]["fn"](args)
    print("Spawn Response:", res)
    
    # Extract session ID using regex or simple split
    import re
    m = re.search(r'`([^`]+)`', res)
    if not m:
        print("Failed to parse session ID.")
        return
        
    session_id = m.group(1)
    
    # Give it some time to start and run
    print("Waiting for subagent to finish...")
    await asyncio.sleep(5)
    
    # 2. Check sub-agent
    check_args = {"session_id": session_id}
    status = await gateway.tools["check_subagent"]["fn"](check_args)
    print("Subagent Status:", status)

if __name__ == "__main__":
    asyncio.run(test())
