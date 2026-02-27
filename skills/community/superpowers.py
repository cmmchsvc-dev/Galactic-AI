import os
import glob
from skills.base import GalacticSkill

class SuperpowersSkill(GalacticSkill):
    """
    Integrates Jesse Vincent's Superpowers agent workflow system.
    Dynamically loads and provides access to .md skill files as agent instructions.
    """
    skill_name  = "superpowers"
    version     = "4.3.1"
    author      = "Jesse Vincent (Ported to Galactic AI)"
    description = "Provides the Superpowers cognitive workflows (TDD, brainstorming, etc) for your agent to follow."
    category    = "workflow"
    icon        = "🦸"

    def get_tools(self):
        return {
            'list_superpowers': {
                'description': 'Lists all available Superpowers (cognitive workflows) you can invoke.',
                'parameters': {
                    'type': 'object',
                    'properties': {}
                },
                'fn': self.list_superpowers
            },
            'invoke_superpower': {
                'description': 'Loads the exact instructions for a specific superpower workflow (e.g. test-driven-development, brainstorming). You MUST read and follow the returned instructions strictly.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'skill_name': {
                            'type': 'string',
                            'description': 'The name of the superpower skill to invoke (e.g., brainstorming).'
                        }
                    },
                    'required': ['skill_name']
                },
                'fn': self.invoke_superpower
            }
        }

    def _get_skills_dir(self):
        # We assume the user has the powers directory cached locally from Claude
        return r"C:\Users\Chesley\.claude\plugins\cache\claude-plugins-official\superpowers\4.3.1\skills"

    async def list_superpowers(self, args):
        skills_dir = self._get_skills_dir()
        if not os.path.exists(skills_dir):
            return "[Error] Superpowers directory not found."
            
        skills = []
        for d in os.listdir(skills_dir):
            if os.path.isdir(os.path.join(skills_dir, d)):
                skills.append(d)
                
        return "Available Superpowers:\\n" + "\\n".join(f"- {s}" for s in sorted(skills)) + "\\n\\nUse invoke_superpower to read the instructions for one of these workflows."

    async def invoke_superpower(self, args):
        skill_name = args.get('skill_name')
        if not skill_name:
            return "[Error] Must provide a skill_name."
            
        skill_file = os.path.join(self._get_skills_dir(), skill_name, 'SKILL.md')
        
        if not os.path.exists(skill_file):
            return f"[Error] Superpower '{skill_name}' not found."
            
        try:
            with open(skill_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return f"### INSTRUCTIONS FOR {skill_name.upper()} ###\\n\\n{content}\\n\\n### END INSTRUCTIONS ###\\nYou must now adopt this workflow immediately for the current task."
        except Exception as e:
            return f"[Error] Failed to read superpower file: {e}"
