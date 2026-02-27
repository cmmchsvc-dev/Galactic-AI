import os
from skills.base import GalacticSkill

class MdImprover(GalacticSkill):
    skill_name  = "md_improver"
    version     = "1.0.0"
    author      = "Galactic AI (via Planner)"
    description = "Audits a markdown file against quality heuristics."
    category    = "documentation"
    icon        = "📝"

    def get_tools(self):
        return {
            "audit_markdown": {
                "description": "Audit a markdown file against quality heuristics (conciseness, actionability, currency) and generate a report.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "The markdown file to analyze (e.g. PROJECT_STATE.md)."}
                    },
                    "required": ["file_path"]
                },
                "handler": self.audit_markdown
            }
        }

    def audit_markdown(self, file_path: str):
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' not found."
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        word_count = len(content.split())
        lines = len(content.splitlines())
        return (f"Markdown Audit for {file_path}:\nWord Count: {word_count}\nLines: {lines}\n"
                f"\n--- AI Instruction ---\n"
                f"Analyze the content of {file_path} for:\n"
                f"1. Conciseness (is it too wordy?)\n2. Actionability (are the next steps clear?)\n"
                f"3. Currency (does it seem outdated?)\n"
                f"Generate a brief report with specific improvement suggestions.")
