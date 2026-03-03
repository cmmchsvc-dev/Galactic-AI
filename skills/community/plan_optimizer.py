import os
import json
from skills.base import GalacticSkill

class PlanOptimizerSkill(GalacticSkill):
    """
    Workspace Oracle: Enhances the system's ability to plan by providing an intelligent
    'optimize_plan' tool that previews tool chains and estimates execution costs
    before committing to a long-running subagent loop.
    """
    skill_name  = "plan_optimizer"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Workspace Oracle: Simulates tool chains and previews costs/steps before execution."
    category    = "intelligence"
    icon        = "🧠"

    def get_tools(self):
        return {
            'optimize_plan': {
                'description': 'Simulates a tool chain for a given task and returns a structured preview of the optimal steps, required tools, and estimated cost (low/medium/high) before execution.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {
                            'type': 'string', 
                            'description': 'The task or problem to analyze and optimize a plan for.'
                        }
                    },
                    'required': ['query']
                },
                'fn': self.optimize_plan
            }
        }

    async def optimize_plan(self, args):
        query = args.get('query', '').lower()
        if not query:
            return "[Error] Must provide a query to optimize."
            
        await self.core.log(f"🧠 Oracle analyzing plan for: {query[:50]}...", priority=2)
        
        # Simple heuristic-based simulation engine for the prototype
        steps = []
        tools_needed = set()
        cost_estimate = "low"
        
        # Heuristics based on keywords
        if "project_state" in query or "state" in query:
            steps.append("Read PROJECT_STATE.md to gather current project focus.")
            tools_needed.add("read_file")
            
        if "error" in query or "bug" in query or "crash" in query:
            steps.append("Search workspace for error logs or related tracebacks.")
            steps.append("Read the failing file.")
            steps.append("Formulate a patch and write changes.")
            tools_needed.update(["search_workspace", "read_file", "edit_file"])
            cost_estimate = "high"
            
        if "skill" in query or "feature" in query:
            steps.append("Review existing skills registry to prevent duplication.")
            steps.append("Scaffold new python file using write_file.")
            steps.append("Load skill via create_skill or manual reboot.")
            tools_needed.update(["list_dir", "write_file", "create_skill"])
            cost_estimate = "medium"
            
        if not steps:
            steps.append("Perform initial directory listing to understand context.")
            steps.append("Search for relevant files.")
            steps.append("Read target files and execute modifications.")
            tools_needed.update(["list_dir", "search_workspace", "read_file"])
            cost_estimate = "medium"
            
        plan_output = {
            "query": query,
            "steps": steps,
            "tools": list(tools_needed),
            "cost_estimate": cost_estimate,
            "total_steps": len(steps),
            "recommendation": "Review the steps and proceed if the cost aligns with your expectations."
        }
        
        return json.dumps(plan_output, indent=2)