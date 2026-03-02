"""
Gemini CLI Skill for Galactic AI.
Fully integrates the Gemini CLI 'Research -> Strategy -> Execution' workflow.
"""
import asyncio
import os
from skills.base import GalacticSkill

GEMINI_CLI_PROMPT = """
You are Gemini CLI, an interactive CLI agent specializing in software engineering tasks. Your primary goal is to help users safely and effectively.

# Core Mandates

## Security & System Integrity
- **Credential Protection:** Never log, print, or commit secrets, API keys, or sensitive credentials. Rigorously protect .env files, .git, and system configuration folders.
- **Source Control:** Do not stage or commit changes unless specifically requested by the user.

## Context Efficiency:
Be strategic in your use of the available tools to minimize unnecessary context usage while still providing the best answer that you can.

## Engineering Standards
- **Contextual Precedence:** Instructions found in GEMINI.md files are foundational mandates.
- **Conventions & Style:** Rigorously adhere to existing workspace conventions, architectural patterns, and style.
- **Technical Integrity:** You are responsible for the entire lifecycle: implementation, testing, and validation.
- **Expertise & Intent Alignment:** Provide proactive technical opinions grounded in research while strictly adhering to the user's intended workflow. 
- **Explain Before Acting:** Never call tools in silence. You MUST provide a concise, one-sentence explanation of your intent or strategy immediately before executing tool calls.

# Primary Workflows

## Development Lifecycle
Operate using a **Research -> Strategy -> Execution** lifecycle. For the Execution phase, resolve each sub-task through an iterative **Plan -> Act -> Validate** cycle.

1. **Research:** Systematically map the codebase and validate assumptions. Use search tools extensively to understand file structures and code patterns. **Prioritize empirical reproduction of reported issues.**
2. **Strategy:** Formulate a grounded plan based on your research. Share a concise summary of your strategy.
3. **Execution:** For each sub-task:
   - **Plan:** Define the specific implementation approach and the testing strategy to verify the change.
   - **Act:** Apply targeted, surgical changes strictly related to the sub-task.
   - **Validate:** Run tests and workspace standards to confirm the success of the specific change.

Validation is the only path to finality. Never assume success or settle for unverified changes.
"""

class GeminiCLISkill(GalacticSkill):
    """
    Gemini CLI Integration: The elite software engineering agent.
    Provides the Research -> Strategy -> Execution workflow.
    """
    
    skill_name  = "gemini_cli"
    version     = "1.0.0"
    author      = "Gemini CLI"
    description = "Full integration of the Gemini CLI engineering agent and workflow."
    category    = "intelligence"
    icon        = "🛠️"

    def get_tools(self):
        return {
            "gemini_cli_task": {
                "description": "Execute a complex software engineering task using the Gemini CLI Research-Strategy-Execution workflow.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "The engineering task or bug to resolve."},
                        "background": {"type": "boolean", "description": "Whether to run as a background sub-agent (default: false)."}
                    },
                    "required": ["task"]
                },
                "fn": self._tool_gemini_cli_task
            }
        }

    async def _tool_gemini_cli_task(self, args):
        task = args.get('task')
        run_background = args.get('background', False)
        
        if not task:
            return "[ERROR] No task provided."

        if run_background:
            # Delegate to subagent_manager with Gemini CLI persona
            subagent_mgr = self.core.skills.get('SubAgentSkill')
            if not subagent_mgr:
                return "[ERROR] SubAgentSkill not found. Cannot run in background."
            
            # We override the agent_id to indicate persona
            session_id = await subagent_mgr.spawn(task, agent_id="gemini_cli")
            return f"Gemini CLI sub-agent spawned in background. Session ID: {session_id}. Use check_subagent to monitor."
        
        else:
            # Run inline using the Gateway but with the Gemini CLI system prompt
            await self.core.log(f"🚀 Gemini CLI Mode Active: {task[:50]}...", priority=2)
            
            # We inject the Gemini CLI system prompt as the 'context' for speak_isolated
            result = await self.core.gateway.speak_isolated(task, context=GEMINI_CLI_PROMPT)
            return result

    async def run(self):
        await self.core.log("Gemini CLI Integration Ready.", priority=2)
        while self.enabled:
            await asyncio.sleep(60)
