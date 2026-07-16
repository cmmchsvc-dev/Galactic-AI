"""Skill loading: parse markdown files with YAML frontmatter into SkillDef objects."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict
import os

@dataclass
class SkillDef:
    name: str
    description: str
    triggers: List[str]
    tools: List[str]
    prompt: str
    file_path: str
    arguments: List[str] = field(default_factory=list)
    source: str = "user"


def _get_skill_paths() -> List[Path]:
    paths = []
    
    # 1. Project level (.galactic/skills)
    proj_skills = Path.cwd() / ".galactic" / "skills"
    if proj_skills.exists():
        paths.append(proj_skills)
        
    # 2. User level (~/.galactic/skills)
    user_skills = Path.home() / ".galactic" / "skills"
    if user_skills.exists():
        paths.append(user_skills)
        
    return paths

def _parse_list_field(value: str) -> List[str]:
    """Parse YAML-like list: ``[a, b, c]`` or ``"a, b, c"``."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip('"').strip("'") for item in value.split(",") if item.strip()]

def _parse_skill_file(path: Path, source: str = "user") -> Optional[SkillDef]:
    """Parse a markdown file with ``---`` frontmatter into a SkillDef."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter_raw = parts[1].strip()
    prompt = parts[2].strip()

    fields: Dict[str, str] = {}
    for line in frontmatter_raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip().lower()] = val.strip()

    name = fields.get("name", "")
    if not name:
        return None

    tools_raw = fields.get("allowed-tools", fields.get("tools", ""))
    tools = _parse_list_field(tools_raw) if tools_raw else []

    triggers_raw = fields.get("triggers", "")
    triggers = _parse_list_field(triggers_raw) if triggers_raw else [f"/{name}"]

    arguments_raw = fields.get("arguments", "")
    arguments = _parse_list_field(arguments_raw) if arguments_raw else []

    return SkillDef(
        name=name,
        description=fields.get("description", ""),
        triggers=triggers,
        tools=tools,
        prompt=prompt,
        file_path=str(path),
        arguments=arguments,
        source=source,
    )

def load_skills() -> List[SkillDef]:
    """Return skills from disk, deduplicated (project > user)."""
    seen: Dict[str, SkillDef] = {}

    skill_paths = _get_skill_paths()
    # Reverse to process user first, then project (so project overrides user)
    for i, skill_dir in enumerate(reversed(skill_paths)):
        src = "user" if i == 0 else "project"
        if not skill_dir.is_dir():
            continue
        for md_file in sorted(skill_dir.glob("*.md")):
            skill = _parse_skill_file(md_file, source=src)
            if skill:
                seen[skill.name] = skill

    return list(seen.values())

def find_skill(query: str) -> Optional[SkillDef]:
    """Find a skill whose trigger matches the first word (or whole string) of query."""
    query = query.strip()
    if not query:
        return None

    first_word = query.split()[0]
    for skill in load_skills():
        for trigger in skill.triggers:
            if first_word == trigger:
                return skill
            if trigger.startswith(first_word + " "):
                return skill
    return None

def substitute_arguments(prompt: str, args: str, arg_names: List[str]) -> str:
    """Replace $ARGUMENTS (whole args string) and $ARG_NAME placeholders."""
    result = prompt.replace("$ARGUMENTS", args)

    arg_values = args.split()
    for i, arg_name in enumerate(arg_names):
        placeholder = f"${arg_name.upper()}"
        value = arg_values[i] if i < len(arg_values) else ""
        result = result.replace(placeholder, value)

    return result
