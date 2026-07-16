import os
import re
from skills.base import GalacticSkill

class MarkdownSkills(GalacticSkill):
    """
    Dynamically loads SKILL.md files from .galactic/skills/ and makes them available as tools.
    """
    skill_name = "markdown_skills"
    display_name = "Markdown Skills Plugin"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "Parses .galactic/skills/<name>/SKILL.md files and registers them as tools."
    category = "system"
    icon = "📚"

    def __init__(self):
        super().__init__()
        self._dynamic_tools = {}
        self._load_skills()

    def _load_skills(self):
        workspace = os.getcwd() # Typically Galactic AI root or user workspace
        skills_dir = os.path.join(workspace, '.galactic', 'skills')
        
        if not os.path.exists(skills_dir):
            return

        for entry in os.scandir(skills_dir):
            if entry.is_dir():
                skill_file = os.path.join(entry.path, 'SKILL.md')
                if os.path.exists(skill_file):
                    self._parse_skill(entry.name, skill_file)

    def _parse_skill(self, skill_name, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            description_match = re.search(r'##\s*Description\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
            desc = description_match.group(1).strip() if description_match else f"Dynamically loaded skill: {skill_name}"

            prompt_match = re.search(r'##\s*Prompt\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
            prompt = prompt_match.group(1).strip() if prompt_match else ""

            # Register dynamic function closure
            async def dynamic_tool_impl(args):
                return f"[Markdown Skill: {skill_name}]\nSystem Prompt: {prompt}\nProvided Args: {args}"

            self._dynamic_tools[f"skill_{skill_name}"] = {
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "The input to pass to the skill"}
                    }
                },
                "fn": dynamic_tool_impl
            }
        except Exception:
            pass

    def get_tools(self):
        # We also provide a tool to refresh skills
        tools = {
            "refresh_markdown_skills": {
                "description": "Reloads SKILL.md files from .galactic/skills/",
                "parameters": {"type": "object", "properties": {}},
                "fn": self.tool_refresh
            }
        }
        tools.update(self._dynamic_tools)
        return tools

    async def tool_refresh(self, args):
        self._dynamic_tools.clear()
        self._load_skills()
        return f"Reloaded {len(self._dynamic_tools)} markdown skills."
