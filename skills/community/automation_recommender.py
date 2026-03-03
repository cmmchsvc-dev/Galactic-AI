import os
from skills.base import GalacticSkill

class AutomationRecommender(GalacticSkill):
    skill_name  = "automation_recommender"
    version     = "1.0.0"
    author      = "Galactic AI (via Planner)"
    description = "Analyzes codebase patterns to recommend custom Galactic AI automations."
    category    = "code_analysis"
    icon        = "🤖"

    def get_tools(self):
        return {
            "recommend_automations": {
                "description": "Analyze codebase patterns to recommend tailored AI automations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory to analyze"}
                    },
                    "required": ["directory"]
                },
                "fn": self.recommend_automations
            }
        }

    def recommend_automations(self, directory: str):
        if not os.path.exists(directory):
            return f"Directory '{directory}' not found."
        sys_info = []
        exts = set()
        file_count = 0
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules')]
            file_count += len(files)
            for f in files:
                if '.' in f: exts.add(f.split('.')[-1])
        sys_info.append(f"Analysis of {directory}: {file_count} files.")
        sys_info.append(f"Extensions: {', '.join(sorted(list(exts))[:20])}")
        sys_info.append("\n--- AI Instruction ---\nBased on the project structure above, please suggest 3 unique Galactic AI skills, sub-agents, or automation hooks that would stream-line the developer's workflow.")
        return "\n".join(sys_info)
