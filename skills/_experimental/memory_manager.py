import re
import json
from dataclasses import dataclass
from pathlib import Path
from skills.base import GalacticSkill

USER_MEMORY_DIR = Path.home() / ".galactic" / "memory"
INDEX_FILENAME = "MEMORY.md"

def get_project_memory_dir() -> Path:
    return Path.cwd() / ".galactic" / "memory"

def get_memory_dir(scope: str = "user") -> Path:
    if scope == "project":
        return get_project_memory_dir()
    return USER_MEMORY_DIR

@dataclass
class MemoryEntry:
    name: str
    description: str
    type: str
    content: str
    file_path: str = ""
    created: str = ""
    scope: str = "user"

def _slugify(name: str) -> str:
    s = name.lower().strip().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s[:60]

def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, parts[2].strip()

def _format_entry_md(entry: MemoryEntry) -> str:
    return (
        f"---\n"
        f"name: {entry.name}\n"
        f"description: {entry.description}\n"
        f"type: {entry.type}\n"
        f"created: {entry.created}\n"
        f"---\n"
        f"{entry.content}\n"
    )

def save_memory(entry: MemoryEntry, scope: str = "user") -> None:
    mem_dir = get_memory_dir(scope)
    mem_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(entry.name)
    fp = mem_dir / f"{slug}.md"
    fp.write_text(_format_entry_md(entry), encoding="utf-8")
    entry.file_path = str(fp)
    entry.scope = scope
    _rewrite_index(scope)

def delete_memory(name: str, scope: str = "user") -> None:
    mem_dir = get_memory_dir(scope)
    slug = _slugify(name)
    fp = mem_dir / f"{slug}.md"
    if fp.exists():
        fp.unlink()
    _rewrite_index(scope)

def load_entries(scope: str = "user") -> list[MemoryEntry]:
    mem_dir = get_memory_dir(scope)
    if not mem_dir.exists():
        return []
    entries = []
    for fp in sorted(mem_dir.glob("*.md")):
        if fp.name == INDEX_FILENAME:
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        meta, body = parse_frontmatter(text)
        entries.append(MemoryEntry(
            name=meta.get("name", fp.stem),
            description=meta.get("description", ""),
            type=meta.get("type", "user"),
            content=body,
            file_path=str(fp),
            created=meta.get("created", ""),
            scope=scope,
        ))
    return entries

def load_index(scope: str = "all") -> list[MemoryEntry]:
    if scope == "all":
        return load_entries("user") + load_entries("project")
    return load_entries(scope)

def search_memory(query: str, scope: str = "all") -> list[MemoryEntry]:
    q = query.lower()
    results = []
    for entry in load_index(scope):
        haystack = f"{entry.name} {entry.description} {entry.content}".lower()
        if q in haystack:
            results.append(entry)
    return results

def _rewrite_index(scope: str) -> None:
    mem_dir = get_memory_dir(scope)
    if not mem_dir.exists():
        return
    index_path = mem_dir / INDEX_FILENAME
    entries = load_entries(scope)
    lines = [
        f"- [{e.name}]({Path(e.file_path).name}) — {e.description} (Scope: {scope})"
        for e in entries
    ]
    index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

def get_index_content(scope: str = "user") -> str:
    if scope == "all":
        user_content = get_index_content("user")
        project_content = get_index_content("project")
        merged = []
        if user_content:
            merged.append(user_content)
        if project_content:
            merged.append(project_content)
        return "\n".join(merged).strip()

    mem_dir = get_memory_dir(scope)
    index_path = mem_dir / INDEX_FILENAME
    if not index_path.exists():
        return ""
    return index_path.read_text(encoding="utf-8").strip()



class MemorySkill(GalacticSkill):
    skill_name = "memory_manager"
    display_name = "Dual-Scope Memory"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "Explicit memory tools for saving and recalling persistent facts across sessions."
    category = "general"
    icon = "🧠"

    def get_tools(self) -> dict:
        return {
            "MemorySave": {
                "description": "Save or update a memory entry. Scopes can be 'user' (global) or 'project' (local).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short unique name for the memory (max 60 chars)"},
                        "description": {"type": "string", "description": "1-sentence summary of the memory"},
                        "content": {"type": "string", "description": "The full detailed content to remember"},
                        "scope": {"type": "string", "enum": ["user", "project"], "description": "Where to store this memory"}
                    },
                    "required": ["name", "description", "content"]
                },
                "fn": self._tool_memory_save
            },
            "MemoryDelete": {
                "description": "Delete a memory entry by name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the memory to delete"},
                        "scope": {"type": "string", "enum": ["user", "project"], "description": "Scope of the memory"}
                    },
                    "required": ["name", "scope"]
                },
                "fn": self._tool_memory_delete
            },
            "MemorySearch": {
                "description": "Search across all memory entries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keyword to search for"},
                        "scope": {"type": "string", "enum": ["user", "project", "all"], "description": "Scope to search"}
                    },
                    "required": ["query"]
                },
                "fn": self._tool_memory_search
            },
            "MemoryList": {
                "description": "List all memory entries in the index.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["user", "project", "all"], "description": "Scope to list"}
                    },
                    "required": []
                },
                "fn": self._tool_memory_list
            }
        }

    async def _tool_memory_save(self, name: str, description: str, content: str, scope: str = "user") -> str:
        from datetime import datetime
        entry = MemoryEntry(
            name=name,
            description=description,
            type="user",
            content=content,
            created=datetime.now().strftime("%Y-%m-%d"),
            scope=scope
        )
        save_memory(entry, scope)
        return f"Successfully saved memory '{name}' to {scope} scope."

    async def _tool_memory_delete(self, name: str, scope: str) -> str:
        delete_memory(name, scope)
        return f"Successfully deleted memory '{name}' from {scope} scope."

    async def _tool_memory_search(self, query: str, scope: str = "all") -> str:
        results = search_memory(query, scope)
        if not results:
            return f"No memories found matching '{query}' in {scope} scope."
        output = [f"Found {len(results)} matches for '{query}':"]
        for r in results:
            output.append(f"\n--- {r.name} ({r.scope}) ---\nDescription: {r.description}\n{r.content}")
        return "\n".join(output)

    async def _tool_memory_list(self, scope: str = "all") -> str:
        results = load_index(scope)
        if not results:
            return f"No memories found in {scope} scope."
        output = [f"Memories in {scope} scope:"]
        for r in results:
            output.append(f"- {r.name} ({r.scope}): {r.description}")
        return "\n".join(output)
