# Skills Ecosystem Design

**Date:** 2026-02-23
**Status:** Approved
**Scope:** Evolve the plugin system into a unified Skills framework with AI self-authoring

---

## Context

Galactic AI currently has 6 built-in plugins (`ShellPlugin`, `BrowserExecutorPro`, `DesktopTool`, `ChromeBridge`, `SocialMediaPlugin`, `SubAgentPlugin`) loaded via a hardcoded `_BUILTIN_PLUGINS` list in `galactic_core_v2.py`. Tools are registered separately in `gateway_v2.py`'s `register_tools()` method — a 207-tool monolith where tool definitions are disconnected from the plugin code that implements them.

The `GalacticPlugin` base class is minimal (defined inline in `shell_executor.py`) with only `name`, `enabled`, and `run()`. Some plugins don't even inherit from it. There is no metadata, no versioning, no dynamic tool registration, and no way for users or the AI to add new skills at runtime.

## Goals

1. **Unified base class** — `GalacticSkill` with metadata and `get_tools()` for self-registration
2. **Disk-based discovery** — Skills loaded from `skills/core/` and `skills/community/` directories
3. **AI self-authoring** — Byte can write new skills to `skills/community/` at runtime
4. **Optional later: Skills Store UI** — Browse/install community skills from the Control Deck

## Approach: Unified Evolution

Skills ARE plugins. We evolve the existing system rather than creating a parallel one. Existing plugins become "core skills" with the same new interface. The migration is phased — both systems run side-by-side until all plugins are migrated.

---

## 1. GalacticSkill Base Class

**File:** `skills/base.py`

```python
class GalacticSkill:
    """Base class for all Galactic AI skills (core and community)."""

    # ── Metadata (override in subclass) ──
    skill_name    = "unnamed_skill"
    version       = "0.1.0"
    author        = "unknown"
    description   = "No description provided."
    category      = "general"     # browser, social, system, desktop, data, general
    icon          = "\u2699\ufe0f"

    def __init__(self, core):
        self.core = core
        self.enabled = True

    def get_tools(self) -> dict:
        """Return tool definitions this skill provides.

        Format matches existing gateway tool dict:
        {
            "tool_name": {
                "description": "...",
                "parameters": { "type": "object", "properties": {...}, "required": [...] },
                "fn": self.some_async_method
            }
        }
        """
        return {}

    async def run(self):
        """Optional background loop. Called once at startup."""
        pass

    async def on_load(self):
        """Called after skill is instantiated. Use for async init."""
        pass

    async def on_unload(self):
        """Called before skill is disabled/removed. Cleanup here."""
        pass
```

### Changes vs current GalacticPlugin

- **Metadata fields** (`version`, `author`, `description`, `category`, `icon`) used by future Store UI
- **`get_tools()`** lets skills self-declare their tools instead of gateway hardcoding them
- **`on_load()` / `on_unload()`** lifecycle hooks for clean setup/teardown
- Lives in `skills/base.py`, imported everywhere (not redefined per-file)

---

## 2. Directory Structure & Discovery

```
skills/
  base.py                  # GalacticSkill base class
  __init__.py              # Package marker
  core/                    # Ships with Galactic AI
    __init__.py
    shell_executor.py      # Migrated from plugins/shell_executor.py
    browser_pro.py         # Migrated from plugins/browser_executor_pro.py
    chrome_bridge.py       # Migrated from plugins/chrome_bridge.py
    social_media.py        # Migrated from plugins/social_media.py
    desktop_tool.py        # Migrated from plugins/desktop_tool.py
    subagent_manager.py    # Migrated from plugins/subagent_manager.py
  community/               # User-installed & AI-authored
    __init__.py
    (empty initially)
  registry.json            # Manifest of installed community skills
```

### registry.json

Tracks community skills only (core skills are always loaded):

```json
{
  "installed": [
    {
      "module": "weather",
      "class": "WeatherSkill",
      "file": "weather.py",
      "installed_at": "2026-02-23T12:00:00",
      "source": "ai_authored"
    }
  ]
}
```

### Skill Loader (galactic_core_v2.py)

Replaces `_BUILTIN_PLUGINS`:

```python
async def load_skills(self):
    """Discover and load all skills (core + community)."""
    self.skills = []

    # 1. Core skills
    CORE_SKILLS = [
        ('skills.core.shell_executor',   'ShellSkill'),
        ('skills.core.browser_pro',      'BrowserProSkill'),
        ('skills.core.chrome_bridge',    'ChromeBridgeSkill'),
        ('skills.core.social_media',     'SocialMediaSkill'),
        ('skills.core.desktop_tool',     'DesktopSkill'),
        ('skills.core.subagent_manager', 'SubAgentSkill'),
    ]
    for module_path, class_name in CORE_SKILLS:
        self._load_skill(module_path, class_name, is_core=True)

    # 2. Community skills from registry.json
    registry = self._read_registry()
    for entry in registry.get('installed', []):
        module = f"skills.community.{entry['module']}"
        self._load_skill(module, entry['class'], is_core=False)

    # 3. Register all tools from loaded skills into gateway
    self.gateway.register_skill_tools(self.skills)
```

### Gateway Integration (gateway_v2.py)

New method merges skill-declared tools into the tool dict:

```python
def register_skill_tools(self, skills):
    """Merge tools from all loaded skills into self.tools."""
    for skill in skills:
        if not skill.enabled:
            continue
        skill_tools = skill.get_tools()
        for tool_name, tool_def in skill_tools.items():
            if tool_name in self.tools:
                self.core.log(
                    f"Tool conflict: {tool_name} already registered, "
                    f"skipping from {skill.skill_name}"
                )
                continue
            self.tools[tool_name] = tool_def
```

---

## 3. AI Self-Authoring

### Meta-tools in gateway

**`create_skill`** — Byte writes a new skill at runtime:

```python
"create_skill": {
    "description": "Create a new Galactic AI skill. Writes a Python file to "
                   "skills/community/ and registers it. Available immediately.",
    "parameters": {
        "type": "object",
        "properties": {
            "name":        {"type": "string", "description": "snake_case skill name"},
            "code":        {"type": "string", "description": "Full Python source"},
            "description": {"type": "string", "description": "What this skill does"}
        },
        "required": ["name", "code", "description"]
    },
    "fn": self.tool_create_skill
}
```

Handler flow:
1. Validate code contains a `GalacticSkill` subclass with `get_tools()`
2. Write to `skills/community/{name}.py`
3. Dynamic import and instantiate
4. Call `on_load()`, append to `self.core.skills`
5. Register new tools via `register_skill_tools()`
6. Update `registry.json`
7. On failure: delete file, return error

**`list_skills`** — inspect what's available:

```python
"list_skills": {
    "description": "List all loaded skills and their tools.",
    "fn": self.tool_list_skills
}
```

**`remove_skill`** — remove a community skill:

```python
"remove_skill": {
    "description": "Remove a community skill by name.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to remove"}
        },
        "required": ["name"]
    },
    "fn": self.tool_remove_skill
}
```

### Safety constraints

- Skills run in the same process (no sandbox in v1 — same trust model as current plugins)
- AI-authored skills write to `community/` only, never `core/`
- Users can review/delete any community skill file
- Failed skills are cleaned up immediately (file deleted on load error)
- `list_skills` lets Byte check existing tools before creating duplicates

---

## 4. Migrated Skill Example

ShellPlugin becomes ShellSkill:

```python
# skills/core/shell_executor.py
from skills.base import GalacticSkill
import asyncio

class ShellSkill(GalacticSkill):
    skill_name   = "shell_executor"
    version      = "1.1.1"
    author       = "Galactic AI"
    description  = "Execute local shell commands (PowerShell)."
    category     = "system"
    icon         = "\U0001f4bb"

    def get_tools(self):
        return {
            "exec_shell": {
                "description": "Execute a shell command (PowerShell).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Command to execute."
                        }
                    },
                    "required": ["command"]
                },
                "fn": self._exec
            }
        }

    async def _exec(self, args):
        command = args.get('command', '')
        return await self.execute(command)

    async def execute(self, command, timeout=120):
        # ... existing implementation unchanged ...

    async def run(self):
        await self.core.log("Shell Executor Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
```

---

## 5. Migration Strategy

Phased approach — both systems run side-by-side during transition:

| Phase | Scope | Risk |
|-------|-------|------|
| **0** | Create `skills/base.py`, `skills/core/`, `skills/community/`, `registry.json`. Loader calls both old plugins and new skills. | Zero (additive only) |
| **1** | Migrate ShellPlugin (1 tool). Remove `exec_shell` from gateway hardcoded tools. | Low |
| **2** | Migrate DesktopTool (doesn't inherit GalacticPlugin today). | Low |
| **3** | Migrate SocialMedia, ChromeBridge, SubAgent. | Medium |
| **4** | Migrate BrowserExecutorPro (54 tools — largest). | Largest but mechanical |
| **5** | Remove old `plugins/` directory, `_BUILTIN_PLUGINS`, all `_get_*_plugin()` helpers. | Cleanup |

Each phase is a single commit. Revert one commit if anything breaks.

---

## 6. Files Changed/Created

| File | Action | Purpose |
|------|--------|---------|
| `skills/base.py` | Create | GalacticSkill base class |
| `skills/__init__.py` | Create | Package marker |
| `skills/core/__init__.py` | Create | Package marker |
| `skills/core/shell_executor.py` | Create | Migrated ShellPlugin |
| `skills/core/browser_pro.py` | Create | Migrated BrowserExecutorPro |
| `skills/core/chrome_bridge.py` | Create | Migrated ChromeBridge |
| `skills/core/social_media.py` | Create | Migrated SocialMediaPlugin |
| `skills/core/desktop_tool.py` | Create | Migrated DesktopTool |
| `skills/core/subagent_manager.py` | Create | Migrated SubAgentPlugin |
| `skills/community/__init__.py` | Create | Package marker |
| `skills/registry.json` | Create | Community skill manifest |
| `galactic_core_v2.py` | Modify | Add `load_skills()`, keep `_BUILTIN_PLUGINS` during migration |
| `gateway_v2.py` | Modify | Add `register_skill_tools()`, `create_skill`, `list_skills`, `remove_skill` |

---

## 7. Future: Skills Store UI (Optional)

When ready, the existing Plugins tab in the Control Deck evolves into a Skills tab with:
- **Installed view** — current toggle cards, plus version/author/description from metadata
- **Store view** — browse/search community skills from a GitHub-hosted registry, one-click install

New API endpoints:
- `GET /api/skills` — replaces `/api/plugins`
- `POST /api/skills/install` — install from registry
- `DELETE /api/skills/{name}` — remove community skill
- `GET /api/skills/store` — fetch available skills from GitHub registry
