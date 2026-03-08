import os
import re
import json
import asyncio
import importlib
from skills.base import GalacticSkill

class ForgeSkill(GalacticSkill):
    """
    Galactic Forge: The Autonomous Skill Synthesis Engine.
    Allows Galactic AI to expand its own capabilities by writing and 
    installing its own skills.
    """
    
    skill_name   = "forge"
    display_name = "Galactic Forge"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Synthesizes and hot-loads new capabilities autonomously."
    category     = "system"
    icon         = "🔥"

    def __init__(self, core):
        super().__init__(core)
        self.community_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'community')
        os.makedirs(self.community_path, exist_ok=True)

    def get_tools(self):
        return {
            "synthesize_skill": {
                "description": "Autonomously create a new permanent skill/tool to solve a capability gap.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "Snake_case name for the new skill (e.g. 'stock_analyzer')"},
                        "goal": {"type": "string", "description": "Detailed description of what the skill/tools should do."},
                        "class_name": {"type": "string", "description": "CamelCase class name (e.g. 'StockSkill')"}
                    },
                    "required": ["skill_name", "goal", "class_name"]
                },
                "fn": self._tool_synthesize_skill
            },
            "patch_file": {
                "description": "Autonomously apply a code fix or enhancement to an existing file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file to patch."},
                        "explanation": {"type": "string", "description": "What is being fixed/changed."},
                        "target_code": {"type": "string", "description": "The exact block of code to replace."},
                        "replacement_code": {"type": "string", "description": "The new code block to insert."}
                    },
                    "required": ["file_path", "explanation", "target_code", "replacement_code"]
                },
                "fn": self._tool_patch_file
            }
        }

    async def _tool_synthesize_skill(self, args):
        skill_name = args.get("skill_name")
        goal = args.get("goal")
        class_name = args.get("class_name")
        
        await self.core.log(f"🔥 [Forge] Synthesizing new skill: {skill_name}...", priority=2)
        
        # 1. Generate Code using the Primary LLM
        prompt = f"""
Create a new Python file for a Galactic AI Skill. 
The skill should be named '{skill_name}' and have a class '{class_name}'.
Goal: {goal}

Requirements:
1. Inherit from 'skills.base.GalacticSkill'.
2. Implement 'get_tools()' returning one or more useful tools.
3. Use 'await self.core.log(msg, priority=3)' for logging inside tools.
4. If you need external libraries, assume they are available or use standard ones.
5. Return ONLY the complete Python code file content. No markdown, no commentary.

Structure template:
from skills.base import GalacticSkill
import os

class {class_name}(GalacticSkill):
    skill_name = "{skill_name}"
    display_name = "{skill_name.replace('_', ' ').title()}"
    description = "{goal[:100]}"
    icon = "\u2699\ufe0f"
    
    def get_tools(self):
        return {{
            "tool_name": {{
                "description": "...",
                "parameters": {{ ... }},
                "fn": self._some_method
            }}
        }}
    
    async def _some_method(self, args):
        ...
"""
        try:
            code = await self.core.gateway.speak_isolated(prompt, context="You are the Galactic Forge Code Generator.")
            # Sanitize output (remove markdown fences if any)
            code = re.sub(r'^```python\n?', '', code, flags=re.MULTILINE)
            code = re.sub(r'\n?```$', '', code, flags=re.MULTILINE)
            
            # 2. Basic Verification (Syntax Check)
            try:
                compile(code, skill_name, 'exec')
            except Exception as e:
                await self.core.log(f"❌ [Forge] Synthesis failed syntax check: {e}", priority=1)
                return f"[ERROR] Synthesized code has syntax errors: {e}"

            # 3. Save to community folder
            file_path = os.path.join(self.community_path, f"{skill_name}.py")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 4. Update registry.json
            registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry.json')
            registry = {"installed": []}
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
            
            # Check if already in registry
            exists = False
            for entry in registry["installed"]:
                if entry["module"] == skill_name:
                    exists = True
                    break
            
            if not exists:
                registry["installed"].append({
                    "module": skill_name,
                    "class": class_name
                })
                with open(registry_path, 'w') as f:
                    json.dump(registry, f, indent=2)

            # 5. Hot-Reload Skills
            await self.core.log(f"✅ [Forge] Skill '{skill_name}' saved. Hot-loading...", priority=2)
            await self.core.load_skills()
            
            return f"Success! Skill '{skill_name}' has been synthesized, verified, and hot-loaded. You can now use its tools."

        except Exception as e:
            await self.core.log(f"❌ [Forge] Error during synthesis: {e}", priority=1)
            return f"[ERROR] Forge failed: {str(e)}"

    async def _tool_patch_file(self, args):
        file_path = args.get("file_path")
        explanation = args.get("explanation")
        target = args.get("target_code")
        replacement = args.get("replacement_code")

        if not os.path.exists(file_path):
            return f"[ERROR] File not found: {file_path}"

        await self.core.log(f"🛠 [Forge] Patching {os.path.basename(file_path)}: {explanation}", priority=2)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if target not in content:
                # Handle potential whitespace mismatches or small variations?
                # For now, strict match is safer for autonomous patching.
                return f"[ERROR] Target code block not found in {file_path}. Patch aborted."

            new_content = content.replace(target, replacement)

            # Verification: Basic syntax check if it's a .py file
            if file_path.endswith('.py'):
                try:
                    compile(new_content, file_path, 'exec')
                except Exception as e:
                    await self.core.log(f"❌ [Forge] Patch failed syntax check for {file_path}: {e}", priority=1)
                    return f"[ERROR] Patch results in syntax error: {e}"

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            await self.core.log(f"✅ [Forge] Patch applied to {file_path}.", priority=2)
            return f"Success! Patch applied to {os.path.basename(file_path)}."

        except Exception as e:
            await self.core.log(f"❌ [Forge] Patching failed: {e}", priority=1)
            return f"[ERROR] Patch failed: {str(e)}"

    async def synthesize_skill_patch(self, file_path, error_context):
        """Used by ForgeSentinel to autonomously generate and apply a fix."""
        await self.core.log(f"🔥 [Forge] Synthesizing autonomous patch for {os.path.basename(file_path)}...", priority=2)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                current_code = f.read()
            
            prompt = f"""
I need an autonomous code patch for the following file: {file_path}
The system reported this error:
{error_context}

Original Code Snippet (Offending area):
{current_code[:5000]} 

Task: Identify the bug and provide a patch in JSON format:
{{
  "explanation": "Brief description of the fix",
  "target_code": "The exact block of code to remove",
  "replacement_code": "The new code block to insert"
}}
Return ONLY the JSON. No conversation.
"""
            response = await self.core.gateway.speak_isolated(prompt, context="You are the Galactic Forge Repair Specialist.")
            patch_data = json.loads(re.search(r'\{.*\}', response, re.DOTALL).group())
            
            # Apply the patch using the existing tool logic
            result = await self._tool_patch_file({
                "file_path": file_path,
                "explanation": patch_data["explanation"],
                "target_code": patch_data["target_code"],
                "replacement_code": patch_data["replacement_code"]
            })
            
            if "Success" in result:
                await self.core.log(f"✅ [Forge] Autonomous repair successful: {patch_data['explanation']}", priority=2)
                # If it's a core file, Sentinel might trigger a reboot elsewhere
            else:
                await self.core.log(f"❌ [Forge] Autonomous repair failed: {result}", priority=1)

        except Exception as e:
            await self.core.log(f"❌ [Forge] Autonomous synthesis failed: {e}", priority=1)

    async def run(self):
        await self.core.log("Galactic Forge is hot and ready. High-tier synthesis enabled.", priority=3)
