import sys
import os

# Add root dir to path
ROOT_DIR = os.getcwd()
sys.path.append(ROOT_DIR)

try:
    from galactic_core_v2 import GalacticCore
    import asyncio

    async def audit():
        core = GalacticCore()
        # setup_systems initializes gateway and calls load_skills
        await core.setup_systems()
        
        all_tools = []
        tool_map = {}
        
        for skill in core.skills:
            skill_tools = []
            if hasattr(skill, 'get_tools'):
                skill_tools = skill.get_tools()
            
            if isinstance(skill_tools, dict):
                tool_names = list(skill_tools.keys())
            else:
                tool_names = []
                for t in skill_tools:
                    if isinstance(t, dict):
                        tool_names.append(t.get('name', 'unnamed'))
                    else:
                        tool_names.append(getattr(t, 'name', 'unnamed'))
            
            tool_map[skill.skill_name] = tool_names
            all_tools.extend(tool_names)
            
        print(f"TOTAL_TOOLS: {len(all_tools)}")
        import json
        print(json.dumps(tool_map, indent=2))

    asyncio.run(audit())
except Exception as e:
    import traceback
    traceback.print_exc()
