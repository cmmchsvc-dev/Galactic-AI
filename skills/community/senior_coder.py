import os
import re
import json
import asyncio
from skills.base import GalacticSkill

class SeniorCoder(GalacticSkill):
    """
    Senior Coder: Interactive & Autonomous Coding Agent.
    Implements a 'Propose -> Review -> Apply' loop for complex coding tasks.
    Supports autonomous mode for high-speed execution.
    """
    
    skill_name   = "senior_coder"
    display_name = "Senior Coder"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Senior-tier coding engine with interactive plan/apply stages."
    category     = "development"
    icon         = "💻"

    def __init__(self, core):
        super().__init__(core)
        self.staging_area = {
            "plan": "",
            "patches": [], # list of {file_path, explanation, target, replacement}
            "status": "idle"
        }

    def get_tools(self):
        return {
            "propose_changes": {
                "description": "Analyze a coding task and propose a multi-file plan with specific code patches. Stages changes for review.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "The coding task or bug fix requested."},
                        "files": {"type": "array", "items": {"type": "string"}, "description": "Optional list of relevant files to analyze."},
                        "autonomous": {"type": "boolean", "description": "If true, applies changes immediately after proposing (Dangerous!).", "default": False}
                    },
                    "required": ["task"]
                },
                "fn": self._tool_propose_changes
            },
            "view_staged_changes": {
                "description": "View the currently staged plan and code patches.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_view_staged
            },
            "apply_staged_changes": {
                "description": "Apply all currently staged code patches to the filesystem.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_apply_staged
            },
            "discard_staged_changes": {
                "description": "Clear the staging area and discard any proposed plan/patches.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_discard_staged
            },
            "run_and_verify": {
                "description": "Execute a verification command (tests, script run) and analyze the output to confirm the task is done.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run for verification."},
                        "cwd": {"type": "string", "description": "Optional working directory."}
                    },
                    "required": ["command"]
                },
                "fn": self._tool_run_and_verify
            }
        }

    async def _tool_propose_changes(self, args):
        task = args.get("task")
        files = args.get("files", [])
        autonomous = args.get("autonomous", False)
        
        await self.core.log(f"🧠 [SeniorCoder] Analyzing task: {task[:60]}...", priority=2)
        
        # 1. Gather context
        file_contexts = []
        for f in files:
            abs_path = os.path.abspath(f)
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as handle:
                        content = handle.read()
                        file_contexts.append(f"FILE: {f}\nCONTENT:\n{content[:8000]}") # Truncate for safety
                except Exception as e:
                    await self.core.log(f"⚠️ Could not read {f}: {e}", priority=3)

        context_str = "\n\n".join(file_contexts)
        
        prompt = f"""
You are the Senior Coder for Galactic AI. 
TASK: {task}

RELEVANT CODE:
{context_str}

Respond ONLY with a JSON object containing the proposed plan and patches.
Each patch must target a specific code block. Use EXACT strings for 'target_code'.

SCHEMA:
{{
  "plan": "Brief multi-step explanation of the solution",
  "patches": [
    {{
      "file_path": "absolute or relative path",
      "explanation": "Why this change is needed",
      "target_code": "The exact block of code to replace",
      "replacement_code": "The new code block"
    }}
  ]
}}
"""
        try:
            response = await self.core.gateway.speak_isolated(prompt, context="You are the Senior Coder Engine.")
            
            # Extract JSON
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if not match:
                return f"[ERROR] Model failed to produce valid JSON. Raw output: {response[:200]}"
            
            data = json.loads(match.group())
            self.staging_area["plan"] = data.get("plan", "No plan provided.")
            self.staging_area["patches"] = data.get("patches", [])
            self.staging_area["status"] = "staged"
            
            msg = f"✅ **Plan Proposed & Staged**\n\n**Plan:**\n{self.staging_area['plan']}\n\n"
            msg += f"**Changes:** {len(self.staging_area['patches'])} patches staged.\n"
            msg += "Use `view_staged_changes` to see details or `apply_staged_changes` to commit."
            
            if autonomous:
                await self.core.log("🚀 Autonomous Mode Active: Applying changes immediately...", priority=2)
                apply_res = await self._tool_apply_staged({})
                return f"{msg}\n\n--- AUTO-APPLY RESULT ---\n{apply_res}"
                
            return msg

        except Exception as e:
            await self.core.log(f"❌ [SeniorCoder] Proposal failed: {e}", priority=1)
            return f"[ERROR] {str(e)}"

    async def _tool_view_staged(self, args):
        if self.staging_area["status"] == "idle":
            return "Staging area is empty."
        
        view = f"### 📝 Staged Plan\n{self.staging_area['plan']}\n\n"
        view += "### 🛠 Staged Patches\n"
        for i, patch in enumerate(self.staging_area["patches"]):
            view += f"\n**Patch {i+1}: {patch['file_path']}**\n"
            view += f"*Explanation:* {patch['explanation']}\n"
            view += f"```diff\n- {patch['target_code'][:200]}\n+ {patch['replacement_code'][:200]}\n```\n"
            
        return view

    async def _tool_apply_staged(self, args):
        if self.staging_area["status"] == "idle" or not self.staging_area["patches"]:
            return "Nothing to apply."
        
        results = []
        for patch in self.staging_area["patches"]:
            file_path = patch.get("file_path")
            target = patch.get("target_code")
            replacement = patch.get("replacement_code")
            
            if not os.path.exists(file_path):
                results.append(f"❌ {file_path}: File not found.")
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if target not in content:
                    results.append(f"❌ {file_path}: Target block not found. (Possible drift)")
                    continue
                
                new_content = content.replace(target, replacement)
                
                # Syntax Check for Python
                if file_path.endswith('.py'):
                    try:
                        compile(new_content, file_path, 'exec')
                    except Exception as e:
                        results.append(f"❌ {file_path}: Syntax error in replacement: {e}")
                        continue
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                results.append(f"✅ patched {file_path}")
                await self.core.log(f"🛠 Applied patch to {file_path}", priority=2)
                
            except Exception as e:
                results.append(f"💥 {file_path}: {e}")

        # Clear stage
        self.staging_area = {"plan": "", "patches": [], "status": "idle"}
        return "### 🚀 Apply Results\n" + "\n".join(results)

    async def _tool_discard_staged(self, args):
        self.staging_area = {"plan": "", "patches": [], "status": "idle"}
        return "Staging area cleared."

    async def _tool_run_and_verify(self, args):
        command = args.get("command")
        cwd = args.get("cwd")
        
        await self.core.log(f"🧪 [SeniorCoder] Verifying with: {command}", priority=2)
        
        # We reuse the shell_executor's execute method if available
        shell = next((s for s in self.core.plugins if getattr(s, 'skill_name', '') == 'shell_executor'), None)
        if not shell:
            return "[ERROR] shell_executor skill not found. Cannot verify."
            
        output = await shell.execute(command, cwd=cwd)
        
        # Analysis Nudge
        analysis_prompt = f"""
VERIFICATION OUTPUT for `{command}`:
{output}

Analyze the output. If the task is successful, state 'TASK_COMPLETE'. 
If there are errors, describe them and plan the next fix.
"""
        return analysis_prompt

    async def run(self):
        await self.core.log("SeniorCoder Skill Online. Interaction Gated.", priority=3)
