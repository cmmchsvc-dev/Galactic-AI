# Skills Ecosystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evolve the plugin system into a unified Skills framework with self-registering tools and AI self-authoring.

**Architecture:** Skills replace plugins via a new `GalacticSkill` base class with `get_tools()` for dynamic tool registration. Core skills live in `skills/core/`, community/AI-authored skills in `skills/community/`. Both systems run side-by-side during migration — each plugin is migrated individually with its own commit.

**Tech Stack:** Python 3.10+, asyncio, importlib (dynamic imports), JSON (registry), aiohttp (web endpoints)

**Design Doc:** `docs/plans/2026-02-23-skills-ecosystem-design.md`

**Note:** This codebase has no test framework. Verification is done by restarting the server and confirming tools work via the Control Deck or Telegram. Each task ends with a commit; each phase ends with a server restart + smoke test.

---

## Phase 0: Foundation (additive only, zero risk)

### Task 1: Create skills/base.py — GalacticSkill base class

**Files:**
- Create: `skills/base.py`

**Step 1: Create the file**

```python
# skills/base.py
"""
GalacticSkill — Base class for all Galactic AI skills.

All skills (core and community) inherit from this class.
Skills self-register their tools via get_tools(), replacing
the hardcoded tool definitions in gateway_v2.py.
"""


class GalacticSkill:
    """Base class for all Galactic AI skills (core and community)."""

    # ── Metadata (override in subclass) ──────────────────────────────
    skill_name  = "unnamed_skill"
    version     = "0.1.0"
    author      = "unknown"
    description = "No description provided."
    category    = "general"          # browser, social, system, desktop, data, general
    icon        = "\u2699\ufe0f"
    is_core     = False              # Set by loader — True for skills/core/

    def __init__(self, core):
        self.core = core
        self.enabled = True

    def get_tools(self) -> dict:
        """Return tool definitions this skill provides.

        Format matches existing gateway tool dict:
        {
            "tool_name": {
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                },
                "fn": self.some_async_method
            }
        }
        """
        return {}

    async def run(self):
        """Optional background loop. Called once at startup as an asyncio task."""
        pass

    async def on_load(self):
        """Called after skill is instantiated. Use for async init."""
        pass

    async def on_unload(self):
        """Called before skill is disabled/removed. Cleanup here."""
        pass
```

**Step 2: Commit**

```bash
git add skills/base.py
git commit -m "feat(skills): add GalacticSkill base class"
```

---

### Task 2: Create directory structure and registry

**Files:**
- Create: `skills/__init__.py`
- Create: `skills/core/__init__.py`
- Create: `skills/community/__init__.py`
- Create: `skills/registry.json`

**Step 1: Create package markers**

`skills/__init__.py`:
```python
# Galactic AI Skills Framework
```

`skills/core/__init__.py`:
```python
# Core skills — ship with Galactic AI
```

`skills/community/__init__.py`:
```python
# Community & AI-authored skills
```

**Step 2: Create empty registry**

`skills/registry.json`:
```json
{
  "installed": []
}
```

**Step 3: Commit**

```bash
git add skills/__init__.py skills/core/__init__.py skills/community/__init__.py skills/registry.json
git commit -m "feat(skills): create directory structure and registry"
```

---

### Task 3: Add skill loader to galactic_core_v2.py

**Files:**
- Modify: `galactic_core_v2.py:49-53` (add `self.skills = []`)
- Modify: `galactic_core_v2.py:124-189` (add `load_skills()` and helpers after `setup_systems()`)
- Modify: `galactic_core_v2.py:505-507` (start skill background loops)

**Step 1: Add `self.skills` to `__init__`**

In `galactic_core_v2.py`, line 53, after `self.plugins = []`:

```python
        self.plugins = []
        self.skills = []
```

**Step 2: Add loader methods**

After the `setup_systems()` method (after line 189), add:

```python
    def _load_skill(self, module_path, class_name, is_core=False):
        """Import and instantiate a single skill. Appends to self.skills on success."""
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            skill = cls(self)
            skill.is_core = is_core
            self.skills.append(skill)
            return skill
        except ModuleNotFoundError:
            # Synchronous log fallback during startup (event loop may not be running)
            print(f"[Skill] {class_name} not found — skipping")
            return None
        except Exception as e:
            print(f"[Skill] {class_name} failed to load: {e}")
            return None

    def _read_registry(self):
        """Read skills/registry.json."""
        import json as _json
        registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills', 'registry.json')
        try:
            with open(registry_path, 'r') as f:
                return _json.load(f)
        except (FileNotFoundError, ValueError):
            return {"installed": []}

    def _write_registry(self, data):
        """Write skills/registry.json."""
        import json as _json
        registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills', 'registry.json')
        with open(registry_path, 'w') as f:
            _json.dump(data, f, indent=2)

    async def load_skills(self):
        """Discover and load all skills (core + community)."""
        self.skills = []

        # Phase 0: No core skills yet — they're still loaded as plugins.
        # As each plugin is migrated, add it to CORE_SKILLS and remove from _BUILTIN_PLUGINS.
        CORE_SKILLS = [
            # ('skills.core.shell_executor', 'ShellSkill'),  # Phase 1
            # ('skills.core.desktop_tool',   'DesktopSkill'), # Phase 2
            # ...
        ]
        for module_path, class_name in CORE_SKILLS:
            self._load_skill(module_path, class_name, is_core=True)

        # Community skills from registry.json
        registry = self._read_registry()
        for entry in registry.get('installed', []):
            module = f"skills.community.{entry['module']}"
            self._load_skill(module, entry['class'], is_core=False)

        # Register all skill-provided tools into gateway
        if self.skills:
            self.gateway.register_skill_tools(self.skills)
            await self.log(f"Skills loaded: {', '.join(s.skill_name for s in self.skills)}", priority=2)
```

**Step 3: Call load_skills() in setup_systems()**

At the end of `setup_systems()`, after line 189 (`await self.log(f"Systems initialized..."`):

```python
        # Load Skills (new system — runs alongside plugins during migration)
        await self.load_skills()
```

**Step 4: Start skill background loops**

In `main_loop()`, after line 507 (`asyncio.create_task(plugin.run())`), add:

```python
        # Start Skills
        for skill in self.skills:
            asyncio.create_task(skill.run())
```

**Step 5: Commit**

```bash
git add galactic_core_v2.py
git commit -m "feat(skills): add skill loader to galactic_core_v2.py"
```

---

### Task 4: Add register_skill_tools() and meta-tools to gateway_v2.py

**Files:**
- Modify: `gateway_v2.py` (add `register_skill_tools()` method, add `create_skill`/`list_skills`/`remove_skill` tool defs and handlers)

**Step 1: Add `register_skill_tools()` method**

Add after `register_tools()` method (after the closing brace of `self.tools = {...}`):

```python
    def register_skill_tools(self, skills):
        """Merge tools from all loaded skills into self.tools.
        Called by GalacticCore.load_skills() after all skills are instantiated.
        """
        count = 0
        for skill in skills:
            if not skill.enabled:
                continue
            skill_tools = skill.get_tools()
            for tool_name, tool_def in skill_tools.items():
                if tool_name in self.tools:
                    # Core/existing tools take priority — log conflict and skip
                    asyncio.get_event_loop().call_soon(
                        lambda n=tool_name, s=skill.skill_name:
                            print(f"[Skills] Tool conflict: {n} already registered, skipping from {s}")
                    )
                    continue
                self.tools[tool_name] = tool_def
                count += 1
        if count:
            asyncio.get_event_loop().call_soon(
                lambda c=count: print(f"[Skills] Registered {c} tools from skills")
            )
```

**Step 2: Add meta-tool definitions to `register_tools()`**

Inside the `self.tools = { ... }` dict in `register_tools()`, add these three tool definitions (anywhere — bottom is fine):

```python
            "create_skill": {
                "description": "Create a new Galactic AI skill. Writes a .py file to skills/community/ and loads it immediately. "
                               "The skill must subclass GalacticSkill and implement get_tools(). "
                               "Use list_skills first to check what already exists.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":        {"type": "string", "description": "Skill name in snake_case (e.g. 'weather_lookup'). Used as filename."},
                        "code":        {"type": "string", "description": "Full Python source code. Must import from skills.base and subclass GalacticSkill."},
                        "description": {"type": "string", "description": "One-line description of what this skill does."}
                    },
                    "required": ["name", "code", "description"]
                },
                "fn": self.tool_create_skill
            },
            "list_skills": {
                "description": "List all loaded skills with their metadata and tools. Shows both core and community skills.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "fn": self.tool_list_skills
            },
            "remove_skill": {
                "description": "Remove a community skill by name. Core skills cannot be removed. "
                               "Unloads the skill and deletes its file from skills/community/.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The skill_name to remove (e.g. 'weather_lookup')."}
                    },
                    "required": ["name"]
                },
                "fn": self.tool_remove_skill
            },
```

**Step 3: Add meta-tool handler functions**

Add these handler methods to the `GalacticGateway` class (near the other tool handlers):

```python
    async def tool_list_skills(self, args):
        """List all loaded skills and their tools."""
        lines = []
        for skill in self.core.skills:
            tool_names = list(skill.get_tools().keys())
            core_tag = " [core]" if skill.is_core else " [community]"
            enabled_tag = "" if skill.enabled else " (DISABLED)"
            lines.append(
                f"{skill.icon} {skill.skill_name} v{skill.version}{core_tag}{enabled_tag}\n"
                f"   {skill.description}\n"
                f"   Tools: {', '.join(tool_names) if tool_names else '(none)'}"
            )
        if not lines:
            return "No skills loaded. Core skills are still running as legacy plugins during migration."
        return "\n\n".join(lines)

    async def tool_create_skill(self, args):
        """Create a new community skill at runtime."""
        import importlib
        import ast

        name = args.get('name', '').strip()
        code = args.get('code', '')
        desc = args.get('description', '')

        if not name or not code:
            return "[ERROR] Both 'name' and 'code' are required."

        # Validate name is snake_case
        if not all(c.isalnum() or c == '_' for c in name) or name[0].isdigit():
            return "[ERROR] Skill name must be snake_case (letters, digits, underscores; cannot start with digit)."

        # Validate code contains GalacticSkill subclass
        if 'GalacticSkill' not in code:
            return "[ERROR] Code must contain a class that inherits from GalacticSkill."
        if 'get_tools' not in code:
            return "[ERROR] Skill class must implement get_tools()."

        # Find the skill class name via AST parsing
        skill_class_name = None
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_name = ''
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name == 'GalacticSkill':
                            skill_class_name = node.name
                            break
                if skill_class_name:
                    break
        except SyntaxError as e:
            return f"[ERROR] Syntax error in skill code: {e}"

        if not skill_class_name:
            return "[ERROR] Could not find a class inheriting from GalacticSkill in the provided code."

        # Check for duplicate skill names
        for existing in self.core.skills:
            if existing.skill_name == name:
                return f"[ERROR] Skill '{name}' already exists. Use remove_skill first to replace it."

        # Write to community/
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(self.core.config_path)), 'skills', 'community')
        os.makedirs(skills_dir, exist_ok=True)
        skill_path = os.path.join(skills_dir, f'{name}.py')

        try:
            with open(skill_path, 'w', encoding='utf-8') as f:
                f.write(code)
        except Exception as e:
            return f"[ERROR] Failed to write skill file: {e}"

        # Dynamic import
        try:
            # Invalidate any cached version
            module_name = f'skills.community.{name}'
            if module_name in sys.modules:
                del sys.modules[module_name]

            mod = importlib.import_module(module_name)
            cls = getattr(mod, skill_class_name)
            skill = cls(self.core)
            skill.is_core = False

            # Call on_load lifecycle hook
            await skill.on_load()

            # Register skill
            self.core.skills.append(skill)

            # Register its tools
            new_tools = skill.get_tools()
            for tool_name, tool_def in new_tools.items():
                if tool_name in self.tools:
                    await self.core.log(f"[Skills] Tool conflict: {tool_name} — skipping", priority=2)
                    continue
                self.tools[tool_name] = tool_def

            # Start background loop if defined
            asyncio.create_task(skill.run())

            # Update registry
            from datetime import datetime as _dt
            registry = self.core._read_registry()
            registry['installed'].append({
                'module': name,
                'class': skill_class_name,
                'file': f'{name}.py',
                'installed_at': _dt.now().isoformat(),
                'source': 'ai_authored',
                'description': desc
            })
            self.core._write_registry(registry)

            tool_names = list(new_tools.keys())
            return (
                f"[OK] Skill '{name}' created and loaded.\n"
                f"  Class: {skill_class_name}\n"
                f"  Tools: {', '.join(tool_names) if tool_names else '(none)'}\n"
                f"  File: {skill_path}"
            )

        except Exception as e:
            # Cleanup on failure
            try:
                os.remove(skill_path)
            except OSError:
                pass
            return f"[ERROR] Failed to load skill: {e}"

    async def tool_remove_skill(self, args):
        """Remove a community skill by name."""
        name = args.get('name', '').strip()
        if not name:
            return "[ERROR] 'name' is required."

        # Find the skill
        target = None
        for skill in self.core.skills:
            if skill.skill_name == name:
                target = skill
                break

        if not target:
            return f"[ERROR] Skill '{name}' not found."

        if target.is_core:
            return f"[ERROR] '{name}' is a core skill and cannot be removed."

        # Call on_unload lifecycle hook
        try:
            await target.on_unload()
        except Exception:
            pass

        # Remove tools from gateway
        tool_names = list(target.get_tools().keys())
        for tn in tool_names:
            self.tools.pop(tn, None)

        # Remove from skills list
        self.core.skills.remove(target)

        # Delete file
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(self.core.config_path)), 'skills', 'community')
        skill_path = os.path.join(skills_dir, f'{name}.py')
        try:
            os.remove(skill_path)
        except OSError:
            pass

        # Update registry
        registry = self.core._read_registry()
        registry['installed'] = [e for e in registry['installed'] if e.get('module') != name]
        self.core._write_registry(registry)

        return f"[OK] Skill '{name}' removed. Tools unregistered: {', '.join(tool_names)}"
```

**Step 4: Commit**

```bash
git add gateway_v2.py
git commit -m "feat(skills): add register_skill_tools() and meta-tools (create/list/remove)"
```

---

### Task 5: Verify Phase 0 — restart and smoke test

**Step 1: Sync to dev install**

```bash
cp skills/base.py skills/__init__.py skills/registry.json "F:/Galactic AI/skills/"
cp skills/core/__init__.py "F:/Galactic AI/skills/core/"
cp skills/community/__init__.py "F:/Galactic AI/skills/community/"
cp galactic_core_v2.py gateway_v2.py "F:/Galactic AI/"
```

**Step 2: Restart the server**

Kill the running process and restart:
```bash
cd "F:/Galactic AI" && PYTHONUTF8=1 python galactic_core_v2.py
```

**Step 3: Verify via API**

```bash
curl http://127.0.0.1:17789/api/status
curl http://127.0.0.1:17789/api/tools | python -m json.tool | grep create_skill
curl http://127.0.0.1:17789/api/tools | python -m json.tool | grep list_skills
curl http://127.0.0.1:17789/api/tools | python -m json.tool | grep remove_skill
```

Expected: Server starts, all 3 new meta-tools appear in the tools list, all existing plugins still work.

**Step 4: Test list_skills via chat**

Send a message: "list all skills" — Byte should use the `list_skills` tool and report that no skills are loaded yet (core skills still running as plugins).

---

## Phase 1: Migrate ShellPlugin (1 tool)

### Task 6: Create skills/core/shell_executor.py

**Files:**
- Create: `skills/core/shell_executor.py`

**Step 1: Write the skill file**

Copy the existing `plugins/shell_executor.py` logic, change base class to `GalacticSkill`, add metadata, add `get_tools()`:

```python
# skills/core/shell_executor.py
"""Shell command execution skill for Galactic AI."""
import asyncio
from skills.base import GalacticSkill


class ShellSkill(GalacticSkill):
    """The 'Hands' of Galactic AI: Executes local shell commands."""

    skill_name  = "shell_executor"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Execute local shell commands (PowerShell)."
    category    = "system"
    icon        = "\U0001f4bb"

    def get_tools(self):
        return {
            "exec_shell": {
                "description": "Execute a shell command (PowerShell).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute."}
                    },
                    "required": ["command"]
                },
                "fn": self._tool_exec_shell
            }
        }

    async def _tool_exec_shell(self, args):
        """Tool handler — wraps execute() with gateway-compatible interface."""
        command = args.get('command', '')
        if not command:
            return "[ERROR] No command provided."
        result = await self.execute(command)
        return result

    async def execute(self, command, timeout=120):
        """Execute a shell command and return the output."""
        try:
            await self.core.log(f"DEBUG EXEC START: {command[:50]}...", priority=1)
            process = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await self.core.log(f"SHELL TIMEOUT: {command[:50]}... killed after {timeout}s", priority=1)
                return f"[Timeout] Command exceeded {timeout}s and was killed."

            output = stdout.decode('utf-8', errors='ignore').strip()
            error = stderr.decode('utf-8', errors='ignore').strip()

            if error:
                await self.core.log(f"SHELL ERROR: {error}", priority=1)
                return f"Error: {error}"

            await self.core.log(f"Shell Success!", priority=2)
            return output
        except Exception as e:
            await self.core.log(f"SHELL EXCEPTION: {str(e)}", priority=1)
            return f"Exception: {str(e)}"

    async def run(self):
        await self.core.log("Shell Executor Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
```

**Step 2: Activate in galactic_core_v2.py**

In `load_skills()`, uncomment the ShellSkill entry in CORE_SKILLS:

```python
        CORE_SKILLS = [
            ('skills.core.shell_executor', 'ShellSkill'),
            # ('skills.core.desktop_tool',   'DesktopSkill'), # Phase 2
        ]
```

**Step 3: Remove ShellPlugin from _BUILTIN_PLUGINS**

In `setup_systems()`, remove the shell_executor line from `_BUILTIN_PLUGINS`:

```python
        _BUILTIN_PLUGINS = [
            # ('plugins.shell_executor',      'ShellPlugin'),  # Migrated to skills/core/
            ('plugins.browser_executor_pro','BrowserExecutorPro'),
            ('plugins.subagent_manager',    'SubAgentPlugin'),
            ('plugins.desktop_tool',        'DesktopTool'),
            ('plugins.chrome_bridge',       'ChromeBridge'),
            ('plugins.social_media',        'SocialMediaPlugin'),
        ]
```

**Step 4: Remove exec_shell from gateway register_tools()**

In `gateway_v2.py`, remove the `exec_shell` tool definition (lines 369-379) from the `self.tools` dict in `register_tools()`. Also remove the `tool_exec_shell` handler method (lines 1945-1956).

**Step 5: Commit**

```bash
git add skills/core/shell_executor.py galactic_core_v2.py gateway_v2.py
git commit -m "feat(skills): migrate ShellPlugin -> ShellSkill (Phase 1)"
```

---

### Task 7: Verify Phase 1

**Step 1: Sync and restart**

```bash
cp skills/core/shell_executor.py "F:/Galactic AI/skills/core/"
cp galactic_core_v2.py gateway_v2.py "F:/Galactic AI/"
```

Restart server. Check logs for `"Skills loaded: shell_executor"`.

**Step 2: Verify exec_shell still works**

Send via chat: "Run: echo hello from skill" — should execute via the new ShellSkill.

---

## Phase 2: Migrate DesktopTool (8 tools)

### Task 8: Create skills/core/desktop_tool.py

**Files:**
- Create: `skills/core/desktop_tool.py`

**Step 1: Write the skill file**

Copy the existing `plugins/desktop_tool.py` implementation. Change base class to `GalacticSkill`, add metadata, add `get_tools()` returning all 8 desktop tools. Each tool's `fn` points to a handler method on the skill class itself.

The tool definitions to move from gateway (lines 1144-1244):
- `desktop_screenshot` (line 1144) -> handler at line 2667
- `desktop_click` (line 1155) -> handler at line 2704
- `desktop_type` (line 1169) -> handler at line 2718
- `desktop_move` (line 1181) -> handler at line 2731
- `desktop_scroll` (line 1194) -> handler at line 2744
- `desktop_hotkey` (line 1207) -> handler at line 2758
- `desktop_drag` (line 1218) -> handler at line 2770
- `desktop_locate` (line 1233) -> handler at line 2785

The skill file structure:
```python
from skills.base import GalacticSkill
# ... existing imports from plugins/desktop_tool.py ...

class DesktopSkill(GalacticSkill):
    skill_name  = "desktop_tool"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "OS-level mouse, keyboard, and screenshot control via pyautogui."
    category    = "desktop"
    icon        = "\U0001f5a5\ufe0f"

    def get_tools(self):
        return {
            "desktop_screenshot": { ... "fn": self._tool_screenshot },
            "desktop_click":      { ... "fn": self._tool_click },
            "desktop_type":       { ... "fn": self._tool_type },
            "desktop_move":       { ... "fn": self._tool_move },
            "desktop_scroll":     { ... "fn": self._tool_scroll },
            "desktop_hotkey":     { ... "fn": self._tool_hotkey },
            "desktop_drag":       { ... "fn": self._tool_drag },
            "desktop_locate":     { ... "fn": self._tool_locate },
        }

    # Tool handlers (moved from gateway_v2.py lines 2667-2802)
    async def _tool_screenshot(self, args): ...
    async def _tool_click(self, args): ...
    # ... etc, each wrapping self.screenshot(), self.click(), etc.

    # Existing methods (copied from plugins/desktop_tool.py)
    async def screenshot(self, region=None, save_path=None): ...
    async def click(self, x, y, button='left', clicks=1): ...
    # ... etc unchanged
```

**Important:** The tool handlers currently reference `self.core` for image path config — this still works since `GalacticSkill.__init__` sets `self.core`.

**Step 2: Activate in galactic_core_v2.py**

Uncomment `DesktopSkill` in CORE_SKILLS. Remove `DesktopTool` from `_BUILTIN_PLUGINS`.

**Step 3: Remove from gateway_v2.py**

- Remove 8 tool defs from `register_tools()` (lines 1144-1244)
- Remove `_get_desktop_plugin()` helper (lines 2663-2665)
- Remove 8 handler methods (lines 2667-2802)

**Step 4: Commit**

```bash
git add skills/core/desktop_tool.py galactic_core_v2.py gateway_v2.py
git commit -m "feat(skills): migrate DesktopTool -> DesktopSkill (Phase 2, 8 tools)"
```

---

## Phase 3: Migrate ChromeBridge, SocialMedia, SubAgent

### Task 9: Create skills/core/chrome_bridge.py (16 tools)

**Files:**
- Create: `skills/core/chrome_bridge.py`

**Pattern:** Same as Tasks 6 and 8. Copy `plugins/chrome_bridge.py`, change base to `GalacticSkill`, add metadata and `get_tools()` returning 16 chrome_* tools. Move the 16 handler methods from gateway (lines 2812-3020) into the skill class.

Tool definitions to move from gateway (lines 1731-1854):
`chrome_screenshot`, `chrome_navigate`, `chrome_read_page`, `chrome_find`, `chrome_click`, `chrome_type`, `chrome_scroll`, `chrome_form_input`, `chrome_execute_js`, `chrome_get_text`, `chrome_tabs_list`, `chrome_tabs_create`, `chrome_key_press`, `chrome_read_console`, `chrome_read_network`, `chrome_hover`

Remove from gateway: `_get_chrome_bridge()` (line 2806), 16 tool defs, 16 handlers.

```python
class ChromeBridgeSkill(GalacticSkill):
    skill_name  = "chrome_bridge"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Chrome extension WebSocket bridge for real browser control."
    category    = "browser"
    icon        = "\U0001f310"
    # ... existing ChromeBridge implementation + get_tools()
```

**Commit:**
```bash
git commit -m "feat(skills): migrate ChromeBridge -> ChromeBridgeSkill (Phase 3, 16 tools)"
```

---

### Task 10: Create skills/core/social_media.py (6 tools)

**Files:**
- Create: `skills/core/social_media.py`

Tool definitions to move from gateway (lines 1857-1905):
`post_tweet`, `read_mentions`, `read_dms`, `post_reddit`, `read_reddit_inbox`, `reply_reddit`

Remove from gateway: `_get_social_media_plugin()` (line 2809), 6 tool defs, 6 handlers (lines 3022-3104).

```python
class SocialMediaSkill(GalacticSkill):
    skill_name  = "social_media"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Twitter/X and Reddit integration."
    category    = "social"
    icon        = "\U0001f4f1"
    # ... existing SocialMediaPlugin implementation + get_tools()
```

**Commit:**
```bash
git commit -m "feat(skills): migrate SocialMediaPlugin -> SocialMediaSkill (Phase 3, 6 tools)"
```

---

### Task 11: Create skills/core/subagent_manager.py (2 tools)

**Files:**
- Create: `skills/core/subagent_manager.py`

Tool definitions to move from gateway (lines 1714-1728):
`spawn_subagent`, `check_subagent`

Remove from gateway: 2 tool defs, 2 handlers (lines 6743-6780).

```python
class SubAgentSkill(GalacticSkill):
    skill_name  = "subagent_manager"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Multi-agent task orchestration (Hive Mind)."
    category    = "system"
    icon        = "\U0001f916"
    # ... existing SubAgentPlugin implementation + get_tools()
```

**Commit:**
```bash
git commit -m "feat(skills): migrate SubAgentPlugin -> SubAgentSkill (Phase 3, 2 tools)"
```

---

### Task 12: Verify Phase 3

Sync all files, restart server. Verify:
- Chrome bridge still connects and chrome_* tools work
- `list_skills` shows 4 skills loaded (shell, desktop, chrome_bridge, social_media, subagent)
- All existing functionality still works

---

## Phase 4: Migrate BrowserExecutorPro (55 tools)

### Task 13: Create skills/core/browser_pro.py

**Files:**
- Create: `skills/core/browser_pro.py`

This is the largest migration — 55 tool definitions and 55 handler methods. The pattern is identical to previous migrations.

Tool definitions to move from gateway (lines 423-1143):
`browser_search`, `browser_click`, `browser_type`, `browser_snapshot`, `browser_click_by_ref`, `browser_type_by_ref`, `browser_fill_form`, `browser_extract`, `browser_wait`, `browser_execute_js`, `browser_upload`, `browser_scroll`, `browser_new_tab`, `browser_press`, `browser_hover`, `browser_hover_by_ref`, `browser_scroll_into_view`, `browser_scroll_into_view_by_ref`, `browser_drag`, `browser_drag_by_ref`, `browser_select`, `browser_select_by_ref`, `browser_download`, `browser_download_by_ref`, `browser_dialog`, `browser_highlight`, `browser_highlight_by_ref`, `browser_resize`, `browser_console_logs`, `browser_page_errors`, `browser_network_requests`, `browser_pdf`, `browser_get_local_storage`, `browser_set_local_storage`, `browser_clear_local_storage`, `browser_get_session_storage`, `browser_set_session_storage`, `browser_clear_session_storage`, `browser_set_offline`, `browser_set_headers`, `browser_set_geolocation`, `browser_clear_geolocation`, `browser_emulate_media`, `browser_set_locale`, `browser_response_body`, `browser_click_coords`, `browser_get_frames`, `browser_frame_action`, `browser_trace_start`, `browser_trace_stop`, `browser_intercept`, `browser_clear_intercept`, `browser_save_session`, `browser_load_session`, `browser_set_proxy`

Handlers to move from gateway: lines 2080-2660 (and lines 2556-2660 for the newer tools).

```python
class BrowserProSkill(GalacticSkill):
    skill_name  = "browser_pro"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Full Playwright browser automation (55 tools)."
    category    = "browser"
    icon        = "\U0001f310"
    # ... existing BrowserExecutorPro implementation + get_tools()
```

**Special consideration:** `galactic_core_v2.py` line 185-187 caches the browser plugin as `self.browser`. Update this to also check `self.skills`:

```python
        # After load_skills():
        browser_skill = next((s for s in self.skills if s.skill_name == 'browser_pro'), None)
        if browser_skill:
            self.browser = browser_skill
```

Remove from gateway: `_get_browser_plugin()` (line 2553-2554), 55 tool defs, 55 handlers.

**Commit:**
```bash
git commit -m "feat(skills): migrate BrowserExecutorPro -> BrowserProSkill (Phase 4, 55 tools)"
```

---

### Task 14: Verify Phase 4

Sync, restart. Verify:
- `list_skills` shows all 6 skills
- Browser automation works (navigate, screenshot, click)
- All tool counts match

---

## Phase 5: Cleanup

### Task 15: Remove legacy plugin system

**Files:**
- Modify: `galactic_core_v2.py` — remove `_BUILTIN_PLUGINS`, remove old plugin loading loop, remove `self.plugins` (or keep as alias to `self.skills`)
- Modify: `gateway_v2.py` — remove all `_get_*_plugin()` helpers (should be empty by now)
- Modify: `web_deck.py` — update `/api/plugins` endpoint to read from `self.core.skills` instead of `self.core.plugins`, update the Plugins tab label to "Skills"
- Delete: `plugins/shell_executor.py`, `plugins/browser_executor_pro.py`, `plugins/desktop_tool.py`, `plugins/chrome_bridge.py`, `plugins/social_media.py`, `plugins/subagent_manager.py`
- Keep: `plugins/__init__.py`, `plugins/ping.py` (legacy, not hurting anything)

**Important:** Keep `self.plugins` as an alias for backwards compatibility:

```python
        self.skills = []
        self.plugins = self.skills   # Backwards compat alias
```

**Commit:**
```bash
git commit -m "refactor(skills): remove legacy plugin system (Phase 5 cleanup)"
```

---

### Task 16: Update web_deck.py — Skills tab

**Files:**
- Modify: `web_deck.py`

Update the Plugins pane (lines 875-880) to Skills:
- Change sidebar label from "Plugins" to "Skills"
- Change tab button from "Plugins" to "Skills"
- Update `loadPlugins()` JS function to `loadSkills()` — fetch from `/api/plugins` (now returns skills data)
- Show skill metadata: version, author, description, category in the cards
- Show tool count per skill

Update `/api/plugins` handler (line 3828) to return skill data:

```python
async def handle_list_plugins(self, request):
    """GET /api/plugins — list all loaded skills."""
    skills = []
    for s in self.core.skills:
        skills.append({
            'name': s.skill_name,
            'display_name': s.skill_name.replace('_', ' ').title(),
            'enabled': s.enabled,
            'class': s.__class__.__name__,
            'version': s.version,
            'author': s.author,
            'description': s.description,
            'category': s.category,
            'icon': s.icon,
            'is_core': s.is_core,
            'tools': list(s.get_tools().keys()),
        })
    return web.json_response({'plugins': skills})
```

**Commit:**
```bash
git commit -m "feat(skills): update Control Deck to show skills with metadata"
```

---

### Task 17: Final sync, restart, and full verification

**Step 1: Sync all files to dev install and public release**

**Step 2: Restart server**

**Step 3: Verify all skills load**

```bash
curl http://127.0.0.1:17789/api/plugins | python -m json.tool
```

Expected: 6 skills with full metadata (name, version, author, description, tools list).

**Step 4: Verify AI self-authoring**

Send via chat: "Create a skill called 'hello_world' that has a tool called 'say_hello' which returns 'Hello from a custom skill!'"

Byte should use `create_skill` to write the file, and then `say_hello` should be available as a tool.

**Step 5: Verify skill removal**

Send: "Remove the hello_world skill"

Byte should use `remove_skill`. The tool should no longer be available.

**Step 6: Commit final state and push**

```bash
git add -A
git commit -m "feat: Skills ecosystem v1 — unified skills framework with AI self-authoring"
git push
```

---

## Summary

| Phase | Tasks | Tools Migrated | Commits |
|-------|-------|----------------|---------|
| 0 — Foundation | 1-5 | 0 (+ 3 meta-tools) | 3 |
| 1 — Shell | 6-7 | 1 | 1 |
| 2 — Desktop | 8 | 8 | 1 |
| 3 — Chrome/Social/SubAgent | 9-12 | 24 | 3 |
| 4 — Browser Pro | 13-14 | 55 | 1 |
| 5 — Cleanup | 15-17 | 0 | 3 |
| **Total** | **17 tasks** | **88 tools migrated + 3 new** | **12 commits** |
