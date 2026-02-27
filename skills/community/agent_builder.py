from skills.base import GalacticSkill

class AgentBuilderSkill(GalacticSkill):
    skill_name  = "agent_builder"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Generate Claude-style subagent markdown specs with strong trigger descriptions and frontmatter."
    category    = "development"
    icon        = "🧩"

    def get_tools(self):
        return {
            'generate_agent_spec': {
                'description': 'Generate a markdown subagent specification with YAML frontmatter and trigger examples.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string', 'description': 'Agent name (lowercase-hyphen format).'},
                        'purpose': {'type': 'string', 'description': 'What the agent does.'},
                        'tools': {'type': 'string', 'description': 'Comma-separated tool names, e.g. read_file,edit_file,list_dir'}
                    },
                    'required': ['name', 'purpose']
                },
                'fn': self.generate_agent_spec
            }
        }

    async def generate_agent_spec(self, args):
        name = args.get('name', '').strip()
        purpose = args.get('purpose', '').strip()
        tools_csv = args.get('tools', 'read_file,list_dir')

        if not name or not purpose:
            return "[Error] 'name' and 'purpose' are required."

        tools = [t.strip() for t in tools_csv.split(',') if t.strip()]
        tools_yaml = '[' + ', '.join([f'"{t}"' for t in tools]) + ']'

        content = f"""---
name: {name}
description: Use this agent when tasks involve {purpose}. Examples:

<example>
Context: A user asks for help related to {purpose}.
user: \"Please handle {purpose}.\"
assistant: \"I'll use the {name} agent to handle this efficiently.\"
<commentary>
This request matches the agent's specialty and should be delegated.
</commentary>
</example>

model: inherit
color: blue
tools: {tools_yaml}
---

You are the **{name}** agent.

Your responsibilities:
1. Analyze the request scope.
2. Execute only relevant tasks for: {purpose}.
3. Return concise, actionable output.

Output format:
- Summary
- Steps taken
- Result
- Follow-up suggestions
"""
        return content