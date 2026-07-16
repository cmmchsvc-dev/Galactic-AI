"""
Galactic AI -- SubAgent Manager Skill v2.0
Multi-agent task orchestration (Hive Mind) with:
  - Live WebSocket broadcast (subagent_update / subagent_done events)
  - Agent Chains: sequential pipelines with {prev_result} passing
  - list_subagents / cancel_subagent tools
"""

import asyncio
import json
import uuid
import os
import sqlite3
from datetime import datetime

from skills.base import GalacticSkill
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class AgentDefinition:
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    tools: list = field(default_factory=list)
    source: str = "built-in"

_BUILTIN_AGENTS = {
    "general-purpose": AgentDefinition(
        name="general-purpose",
        description="General-purpose agent for researching complex questions, searching code, and executing tasks.",
        system_prompt="",
        source="built-in",
    ),
    "coder": AgentDefinition(
        name="coder",
        description="Specialized coding agent for writing, reading, and modifying code.",
        system_prompt=(
            "You are a specialized coding assistant. Focus on:\n"
            "- Writing clean, idiomatic code\n"
            "- Reading and understanding existing code before modifying\n"
            "- Making minimal targeted changes\n"
            "- Never adding unnecessary features, comments, or error handling\n"
        ),
        source="built-in",
    ),
    "reviewer": AgentDefinition(
        name="reviewer",
        description="Code review agent analyzing quality, security, and correctness.",
        system_prompt=(
            "You are a code reviewer. Analyze code for:\n"
            "- Correctness and logic errors\n"
            "- Security vulnerabilities (injection, XSS, auth bypass, etc.)\n"
            "- Performance issues\n"
            "- Code quality and maintainability\n"
            "Be concise and specific. Categorize findings as: Critical | Warning | Suggestion.\n"
        ),
        source="built-in",
    ),
    "researcher": AgentDefinition(
        name="researcher",
        description="Research agent for exploring codebases and answering questions.",
        system_prompt=(
            "You are a research assistant focused on understanding codebases.\n"
            "- Read and analyze code thoroughly before answering\n"
            "- Provide factual, evidence-based answers\n"
            "- Cite specific file paths and line numbers\n"
            "- Be concise and focused\n"
        ),
        source="built-in",
    ),
    "tester": AgentDefinition(
        name="tester",
        description="Testing agent that writes and runs tests.",
        system_prompt=(
            "You are a testing specialist. Your job:\n"
            "- Write comprehensive tests for the given code\n"
            "- Run existing tests and diagnose failures\n"
            "- Focus on edge cases and error conditions\n"
            "- Keep tests simple, readable, and fast\n"
        ),
        source="built-in",
    ),
}

def _parse_agent_md(path: Path, source: str = "user") -> AgentDefinition:
    content = path.read_text(encoding="utf-8")
    name = path.stem
    description = ""
    model = ""
    tools = []
    system_prompt_body = content

    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            system_prompt_body = content[end + 3:].strip()
            fm = {}
            for line in fm_text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip().lower()] = v.strip()
            description = fm.get("description", "")
            model = fm.get("model", "")
            raw_tools = fm.get("tools", "")
            if raw_tools:
                s = raw_tools.strip("[]")
                tools = [t.strip().strip('"').strip("'") for t in s.split(",") if t.strip()]

    return AgentDefinition(
        name=name,
        description=description,
        system_prompt=system_prompt_body,
        model=model,
        tools=tools,
        source=source,
    )



# ── Session & Chain data classes ─────────────────────────────────────────────

class SubAgentSession:
    def __init__(self, agent_id, task, model, chain_id=None, chain_step=None, isolation=""):
        self.id          = "s-" + str(uuid.uuid4())[:8]
        self.agent_id    = agent_id
        self.task        = task
        self.model       = model
        self.status      = "pending"    # pending | running | completed | failed | cancelled
        self.result      = None
        self.start_time  = datetime.now()
        self.end_time    = None
        self.log_lines   = []           # last N lines of agent output
        self.progress    = ""           # short human-readable status line
        self.task_ref    = None         # asyncio.Task — prevents GC + enables cancel
        self.chain_id    = chain_id     # None if standalone
        self.chain_step  = chain_step   # 0-based index within the chain
        self.progress_percent = 0       # 0-100
        self.isolation   = isolation
        self.worktree_path = None
        self.worktree_branch = None

    @property
    def elapsed(self):
        end = self.end_time or datetime.now()
        secs = int((end - self.start_time).total_seconds())
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def to_dict(self):
        return {
            "id":             self.id,           # internal
            "session_id":     self.id,           # frontend expected name
            "agent":          self.agent_id,
            "task":           self.task[:120],
            "status":         self.status,
            "elapsed":        self.elapsed,
            "progress":       self.progress,
            "start_time":     self.start_time.timestamp(), # for JS sorting
            "log_lines":      self.log_lines[-SubAgentSkill.MAX_LOG_LINES:], # full tail
            "log_tail":       self.log_lines[-3:], 
            "result_snippet": (self.result or "")[:300] if self.status in ("completed", "failed") else None,
            "chain_id":       self.chain_id,
            "chain_step":     self.chain_step,
            "progress_percent": self.progress_percent,
            "isolation":      self.isolation,
            "worktree_path":  self.worktree_path,
            "worktree_branch": self.worktree_branch,
        }


class AgentChain:
    """A sequential pipeline of SubAgentSession instances."""
    def __init__(self, steps):
        """steps: list of dicts {agent_id, task_template}"""
        self.id      = str(uuid.uuid4())[:8]
        self.steps   = steps          # original step definitions
        self.sessions = []            # SubAgentSession list (filled as chain runs)
        self.current  = 0
        self.status   = "pending"
        self.progress_percent = 0
        self.log_lines = []           # Compat with _broadcast_update
        self.progress  = ""           # Compat with _broadcast_update



# ── Skill ────────────────────────────────────────────────────────────────────

class SubAgentSkill(GalacticSkill):
    """The Hive Mind: spawns and manages isolated sub-agent tasks and chains."""

    skill_name  = "subagent_manager"
    version     = "1.6.9"
    author      = "Galactic AI"
    description = "Multi-agent task orchestration with live monitoring and chains."
    category    = "system"
    icon        = "\U0001f916"
    name        = "SubAgentManager"   # legacy compat

    SESSION_TTL_SECONDS = 3600   # clean up completed/failed after 1 h
    SESSION_STUCK_TTL   = 14400  # clean up stuck after 4 h
    MAX_LOG_LINES       = 20     # per session

    def __init__(self, core):
        super().__init__(core)
        self.active_sessions: dict[str, SubAgentSession] = {}
        self.active_chains:   dict[str, AgentChain]     = {}
        
        # SQLite Persistence
        self.db_dir = self.core.config.get('paths', {}).get('db', './db')
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, 'subagents.db')
        self._init_db()
        self._load_sessions()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    task TEXT,
                    model TEXT,
                    status TEXT,
                    result TEXT,
                    start_time REAL,
                    end_time REAL,
                    chain_id TEXT,
                    chain_step INTEGER,
                    progress_percent INTEGER,
                    progress TEXT
                )
            ''')
            conn.commit()

    def _save_session(self, session: SubAgentSession):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (
                    id, agent_id, task, model, status, result, start_time, end_time,
                    chain_id, chain_step, progress_percent, progress
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.id, session.agent_id, session.task, session.model,
                session.status, session.result, session.start_time.timestamp(),
                session.end_time.timestamp() if session.end_time else None,
                session.chain_id, session.chain_step, session.progress_percent, session.progress
            ))
            conn.commit()

    def _load_sessions(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT * FROM sessions')
            for row in cursor.fetchall():
                sid = row[0]
                session = SubAgentSession(row[1], row[2], row[3], chain_id=row[8], chain_step=row[9])
                session.id = sid
                session.status = row[4]
                if session.status in ('running', 'pending'):
                    session.status = 'failed' # Mark orphaned sessions as failed
                    session.result = "[FATAL ERROR] System crashed or restarted while agent was running."
                session.result = row[5]
                session.start_time = datetime.fromtimestamp(row[6]) if row[6] else datetime.now()
                session.end_time = datetime.fromtimestamp(row[7]) if row[7] else None
                session.progress_percent = row[10] or 0
                session.progress = row[11] or ""
                self.active_sessions[sid] = session

    def load_agent_definitions(self) -> dict[str, AgentDefinition]:
        defs = dict(_BUILTIN_AGENTS)

        # 1. User level (~/.galactic/agents/*.md)
        user_dir = Path.home() / ".galactic" / "agents"
        if user_dir.is_dir():
            for p in sorted(user_dir.glob("*.md")):
                try:
                    d = _parse_agent_md(p, source="user")
                    defs[d.name] = d
                except Exception:
                    pass

        # 2. Project level (.galactic/agents/*.md)
        proj_dir = Path.cwd() / ".galactic" / "agents"
        if proj_dir.is_dir():
            for p in sorted(proj_dir.glob("*.md")):
                try:
                    d = _parse_agent_md(p, source="project")
                    defs[d.name] = d
                except Exception:
                    pass

        return defs

    # ── Tool definitions ─────────────────────────────────────────────────────

    def get_tools(self):
        # Dynamically inject whitelisted models into the tool description
        allowed = self.core.config.get("subagents", {}).get("allowed_online_models", [])
        allow_online = self.core.config.get("subagents", {}).get("allow_online_models", False)

        models_desc = "Fuzzy names like 'Qwen3' or 'Ollama/Qwen' are supported."
        if allow_online and allowed:
            allowed_str = f" Currently whitelisted online models you can use: {', '.join(allowed)}."
        else:
            allowed_str = " (Only local Ollama models are currently authorized by the user)."

        agent_roles = list(self.load_agent_definitions().keys())
        roles_desc = f"Agent role: {', '.join(agent_roles)} (default: researcher)"

        return {
            "spawn_subagent": {
                "description": (
                    "Spawn an isolated sub-agent to handle a task in the background. "
                    "This is FULLY ASYNCHRONOUS; the main agent (you) remains free for conversation "
                    "immediately after spawning. Use this to delegate work while you continue chatting. "
                    "Returns a session ID."
                ),
                "parameters": {"type": "object", "properties": {
                    "task":       {"type": "string", "description": "A High-Quality Technical Blueprint. Include: 1. Absolute file paths (MUST), 2. Detailed logic steps, 3. Defensive Context (explicitly warn about common pitfalls like Canvas state leaks or syntax validation), 4. Mandatory Self-Verification turn where the sub-agent reads the file back."},
                    "agent_type": {"type": "string", "description": roles_desc},
                    "model":      {"type": "string", "description": f"Specific model ID. Fuzzy names like 'Qwen3' or 'Ollama/Qwen' are supported.{allowed_str}"},
                    "wait":       {"type": "boolean", "description": "Block and wait for the agent to finish before returning (default: true)."},
                    "isolation":  {"type": "string", "enum": ["worktree", ""], "description": "Use 'worktree' to create a temporary git worktree/branch so the agent's modifications don't conflict with your active workspace."}
                }, "required": ["task"]},
                "fn": self._tool_spawn_subagent,
            },
            "check_subagent": {
                "description": "Check the status and result of a previously spawned sub-agent.",
                "parameters": {"type": "object", "properties": {
                    "session_id": {"type": "string", "description": "Session ID from spawn_subagent"},
                }, "required": ["session_id"]},
                "fn": self._tool_check_subagent,
            },
            "list_subagents": {
                "description": "List all active and recent sub-agent sessions.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_list_subagents,
            },
            "cancel_subagent": {
                "description": "Cancel a running sub-agent task.",
                "parameters": {"type": "object", "properties": {
                    "session_id": {"type": "string", "description": "Session ID to cancel"},
                }, "required": ["session_id"]},
                "fn": self._tool_cancel_subagent,
            },
            "spawn_chain": {
                "description": (
                    "Spawn a sequential chain of sub-agents to perform a complex, multi-step workflow in the background. "
                    "Each step can use {prev_result} to access the previous step's output. "
                    "The main agent remains free immediately after spawning. "
                    "Example steps: [{\"agent_type\": \"researcher\", \"task\": \"Research X\"}, "
                    "{\"agent_type\": \"coder\", \"task\": \"Implement based on: {prev_result}\"}]"
                ),
                "parameters": {"type": "object", "properties": {
                    "steps": {
                        "type": "array",
                        "description": f"List of {{agent_type, task, model}} dicts. EACH task MUST be a clear technical plan. For model: {allowed_str}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_type": {"type": "string", "description": roles_desc},
                                "task": {"type": "string", "description": "The explicit and clear instruction for this agent to perform. DO NOT omit this."},
                                "model": {"type": "string", "description": f"Optional model override: {allowed_str}"}
                            },
                            "required": ["task"]
                        },
                    },
                    "chain_name": {"type": "string", "description": "Optional name for this chain"},
                }, "required": ["steps"]},
                "fn": self._tool_spawn_chain,
            },
            "spawn_team": {
                "description": (
                    "Spawn a concurrent team of sub-agents to tackle a project in parallel. "
                    "Unlike chains, all agents in a team start simultaneously and can communicate with each other "
                    "using the message_teammate tool."
                ),
                "parameters": {"type": "object", "properties": {
                    "team_name": {"type": "string", "description": "Name for the team"},
                    "members": {
                        "type": "array",
                        "description": f"List of dicts: {{agent_type, task, model}}. Each member runs concurrently. For model: {allowed_str}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_type": {"type": "string", "description": roles_desc},
                                "task": {"type": "string", "description": "The explicit and clear instruction for this agent to perform. DO NOT omit this."},
                                "model": {"type": "string", "description": f"Optional model override: {allowed_str}"},
                                "isolation": {"type": "string", "enum": ["worktree", ""], "description": "Use 'worktree' to create a temporary git branch/worktree for this teammate."}
                            },
                            "required": ["task"]
                        }
                    },
                    "wait": {"type": "boolean", "description": "Block and wait for the team to finish before returning (default: true)."}
                }, "required": ["team_name", "members"]},
                "fn": self._tool_spawn_team,
            },
            "message_team": {
                "description": "Broadcast a message to all members of your current agent team. Only use if you are part of a team.",
                "parameters": {"type": "object", "properties": {
                    "team_id": {"type": "string", "description": "The ID of your team"},
                    "message": {"type": "string", "description": "The message to broadcast"}
                }, "required": ["team_id", "message"]},
                "fn": self._tool_message_team,
            },
            "wait_for_subagents": {
                "description": "Block and wait for specific subagent sessions, a chain, or a team to finish. Returns when all specified agents are no longer running. Use this when the user explicitly asks you to monitor or wait for the swarm to finish.",
                "parameters": {"type": "object", "properties": {
                    "session_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of session IDs to wait for."},
                    "chain_id": {"type": "string", "description": "Optional team or chain ID to wait for."}
                }},
                "fn": self._tool_wait_for_subagents,
            },
            "auto_swarm_delegate": {
                "description": (
                    "Autonomously orchestrate a complex task by generating and spawning a multi-agent Swarm Chain. "
                    "Use this whenever the user asks you to 'use the swarm' or perform a complex coding/research task. "
                    "The tool will automatically discover the optimal local Ollama models and build the chain logic."
                ),
                "parameters": {"type": "object", "properties": {
                    "task": {"type": "string", "description": "The overall objective to accomplish."},
                    "allow_online_models": {"type": "boolean", "description": "If true, non-Ollama models can be selected. Defaults to false."}
                }, "required": ["task"]},
                "fn": self._tool_auto_swarm_delegate,
            },
        }

    # ── Tool handlers ────────────────────────────────────────────────────────

    async def _tool_spawn_subagent(self, args):
        task       = args.get("task", "")
        agent_type = args.get("agent_type", "researcher")
        model      = args.get("model")
        wait       = args.get("wait", True)
        isolation  = args.get("isolation", "")
        if not task:
            return "[ERROR] No task provided."
        try:
            session_id = await self.spawn(task, agent_id=agent_type, model=model, isolation=isolation)
            
            if wait:
                import asyncio
                await self._chat_notify(f"🤖 Subagent spawned ({session_id}). Waiting for completion...")
                while True:
                    session = self.active_sessions.get(session_id)
                    if not session or session.status not in ("pending", "running"):
                        break
                    await asyncio.sleep(2)
                
                final_session = self.active_sessions.get(session_id)
                if final_session and final_session.result:
                    return f"[Agent: {final_session.agent_id} ({session_id})]\n\n{final_session.result}"
                return f"[Agent: {agent_type} ({session_id})]\n\nTask finished with no output or error."
            
            return (
                f"Sub-agent spawned. Session ID: `{session_id}`. "
                "CRITICAL: This agent will handle the task independently in the background. Your responsibility for this "
                "specific sub-task is now COMPLETE. DO NOT attempt to perform the sub-task yourself "
                "or confirm its success in this turn. Move to the next step in your plan or inform the user delegation is complete."
            )
        except Exception as e:
            return f"[ERROR] spawn_subagent: {e}"

    async def _tool_check_subagent(self, args):
        session_id = args.get("session_id", "")
        session    = self.active_sessions.get(session_id)
        if not session:
            return f"[ERROR] Session `{session_id}` not found."
        return json.dumps(session.to_dict(), indent=2)

    async def _tool_list_subagents(self, args):
        if not self.active_sessions:
            return "No sub-agent sessions found."
        sessions = [s.to_dict() for s in sorted(
            self.active_sessions.values(), key=lambda s: s.start_time, reverse=True
        )]
        return json.dumps(sessions, indent=2)

    async def _tool_cancel_subagent(self, args):
        session_id = args.get("session_id", "")
        session    = self.active_sessions.get(session_id)
        if not session:
            return f"[ERROR] Session `{session_id}` not found."
        if session.task_ref and not session.task_ref.done():
            session.task_ref.cancel()
        session.status   = "cancelled"
        session.end_time = datetime.now()
        await self._broadcast_done(session)
        return f"Sub-agent `{session_id}` cancelled."

    async def _tool_spawn_chain(self, args):
        steps      = args.get("steps", [])
        chain_name = args.get("chain_name", "chain")
        import json
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                return "[ERROR] 'steps' is a string but not valid JSON."
        if not steps:
            return "[ERROR] No steps provided."
        try:
            chain_id = await self.spawn_chain(steps, name=chain_name)
            return (
                f"Agent Chain launched. Chain ID: `{chain_id}`. "
                "CRITICAL: This chain will handle the multi-step workflow independently. Your responsibility "
                "for these tasks is now COMPLETE. DO NOT attempt to perform the steps yourself. "
                "Inform the user that the chain has been dispatched."
            )
        except Exception as e:
            return f"[ERROR] spawn_chain: {e}"

    async def _tool_spawn_team(self, args):
        team_name = args.get("team_name", "Team")
        members = args.get("members", [])
        wait = args.get("wait", True)
        import json
        if isinstance(members, str):
            try:
                members = json.loads(members)
            except json.JSONDecodeError:
                return "[ERROR] 'members' is a string but not valid JSON."
        if not members:
            return "[ERROR] No team members provided."
            
        team_id = "t-" + str(uuid.uuid4())[:8]
        try:
            spawned_ids = []
            for i, member in enumerate(members):
                agent_type = member.get("agent_type", "researcher")
                model = member.get("model")
                task = member.get("task", "")
                # Inject team awareness into the task
                task_with_context = f"[TEAM CONTEXT: You are part of Team '{team_name}' (ID: {team_id}). You can communicate with your team using the message_team tool.]\n\nYour Task:\n{task}"
                sid = await self.spawn(task_with_context, agent_id=agent_type, model=model, chain_id=team_id, isolation=member.get("isolation", ""))
                spawned_ids.append(sid)
                
                # Stagger spawns to respect Google AI Studio's 15 RPM free-tier rate limit
                if i < len(members) - 1:
                    import asyncio
                    await asyncio.sleep(4.5)
                
            if wait:
                import asyncio
                await self._chat_notify(f"🤝 Team '{team_name}' ({len(members)} agents) launched. Waiting for completion...")
                while True:
                    all_done = True
                    for sid in spawned_ids:
                        session = self.active_sessions.get(sid)
                        if session and session.status in ("pending", "running"):
                            all_done = False
                            break
                    if all_done:
                        break
                    await asyncio.sleep(2)
                    
                # Concatenate all results
                combined = f"Team '{team_name}' ({team_id}) Execution Results:\n{'='*40}\n"
                for sid in spawned_ids:
                    s = self.active_sessions.get(sid)
                    if s:
                        res = s.result if s.result else "(no output)"
                        combined += f"\n[Agent: {s.agent_id} ({sid})]\n{res}\n{'-'*40}\n"
                return combined
                
            return f"Agent Team '{team_name}' ({team_id}) launched with {len(members)} concurrent members in the background."
        except Exception as e:
            return f"[ERROR] spawn_team: {e}"

    async def _tool_message_team(self, args):
        team_id = args.get("team_id")
        message = args.get("message")
        
        # Broadcast message to all active sessions that share this team_id (chain_id field)
        notified = 0
        for session in self.active_sessions.values():
            if session.chain_id == team_id and session.status in ("pending", "running"):
                # Ideally, we would inject this into their memory/context dynamically
                # For now, we log it to their output and if they use tool polling, they see it
                session.log_lines.append(f"[TEAM MESSAGE] {message}")
                notified += 1
                
        return f"Message broadcasted to {notified} active team members."

    async def _tool_wait_for_subagents(self, args):
        session_ids = args.get("session_ids", [])
        chain_id = args.get("chain_id")
        
        if not session_ids and not chain_id:
            return "[ERROR] Must provide either session_ids or chain_id to wait for."
            
        target_sessions = []
        if chain_id:
            for sid, s in self.active_sessions.items():
                if s.chain_id == chain_id:
                    target_sessions.append(s)
                    
        for sid in session_ids:
            if sid in self.active_sessions and self.active_sessions[sid] not in target_sessions:
                target_sessions.append(self.active_sessions[sid])
                
        if not target_sessions:
            return "[ERROR] No active sessions found matching those IDs."
            
        await self._chat_notify("dY  **Standby Mode:** Waiting for subagents to complete...")
        
        import asyncio
        while True:
            all_done = True
            for s in target_sessions:
                if s.status in ("pending", "running"):
                    all_done = False
                    break
            if all_done:
                break
            await asyncio.sleep(2)
            
        return "All specified subagents have completed their tasks."

    async def _tool_auto_swarm_delegate(self, args):
        task = args.get("task", "")
        config_allow_online = self.core.config.get("subagents", {}).get("allow_online_models", False)
        allow_online_models = args.get("allow_online_models", False) or config_allow_online
        if not task:
            return "[ERROR] No task provided."

        model_mgr = getattr(self.core, "model_manager", None)
        if not model_mgr:
            return "[ERROR] ModelManager not found, cannot discover models."
        
        all_models = model_mgr.get_all_models()
        allowed_online = self.core.config.get("subagents", {}).get("allowed_online_models", [])
        
        available_models = []
        for m in all_models:
            mid = m["id"]
            mid_lower = mid.lower()
            
            # If it's an Ollama model, we always allow it
            if mid_lower.startswith("ollama/"):
                available_models.append(mid)
            else:
                # If it's an online model, check if we allow online models AT ALL,
                # and then check if it's explicitly in the whitelist.
                if allow_online_models and mid in allowed_online:
                    available_models.append(mid)

        if not available_models:
            return "[ERROR] No models available to construct the Swarm."

        models_list_str = "\n".join(f"- {m}" for m in available_models)
        
        prompt = (
            f"You are the Swarm Architect (Fugu Orchestrator). Your job is to design a multi-agent chain to accomplish the following task:\n\n"
            f"<TASK>\n{task}\n</TASK>\n\n"
            f"Available Models:\n{models_list_str}\n\n"
            "INSTRUCTIONS:\n"
            "1. Break the task down into a sequential chain of sub-agent steps.\n"
            "2. Each step must specify an 'agent_type' (e.g., researcher, coder, reviewer), a 'model' from the Available Models list, and a 'task' string.\n"
            "3. KEEP THE 'task' STRINGS CONCISE (under 3 sentences). Do NOT write the code or massive details in the task string. The sub-agents are smart enough to figure it out.\n"
            "4. The 'task' string for steps after the first should use '{prev_result}' to ingest the previous step's output.\n"
            "5. Choose heavy models (e.g. 27b, 30b, 70b) or online coder models for complex reasoning/coding, and lighter models (e.g. 8b) for basic parsing or initial web research.\n"
            "6. OUTPUT YOUR ENTIRE RESPONSE AS A VALID JSON ARRAY of step objects. DO NOT output markdown blocks or any other text.\n"
            "Example format:\n"
            '[\n  {"agent_type": "researcher", "model": "ollama/llama3:8b", "task": "Search X"},\n  {"agent_type": "coder", "model": "openai/gpt-4o", "task": "Implement {prev_result}"}\n]'
        )
        
        await self._chat_notify(f"🧠 **Auto-Swarm Orchestrator** analyzing task and dynamically building chain...")
        
        try:
            result = await self.core.gateway.speak_isolated(
                prompt,
                context="You are a JSON-only API.",
                skip_planning=True
            )
            
            # Strip think tags for reasoning models
            import re
            clean_json = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
            
            # Try to extract a JSON block from markdown if present
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', clean_json, re.DOTALL)
            if json_match:
                clean_json = json_match.group(1).strip()
            else:
                # Robust extraction: find the first '[' and last ']'
                start = clean_json.find('[')
                end = clean_json.rfind(']')
                if start != -1 and end != -1 and end >= start:
                    clean_json = clean_json[start:end+1]
                else:
                    # In case it got cut off, attempt to add closing brackets
                    if start != -1:
                        clean_json = clean_json[start:] + '}]'
            
            try:
                steps = json.loads(clean_json)
            except json.JSONDecodeError:
                # If it still fails, usually due to token limits or malformed output
                return f"[ERROR] Failed to parse Swarm Architect JSON. The task may be too complex, or the output was cut off. Please simplify the task.\nRaw output: {result}"
            if not isinstance(steps, list):
                raise ValueError("JSON result is not a list")
                
            chain_id = await self.spawn_chain(steps, name="Auto-Swarm Pipeline")
            return f"Auto-Swarm successfully orchestrated! Chain ID: `{chain_id}` with {len(steps)} steps. The background process is running asynchronously."
            
        except Exception as e:
            return f"[ERROR] Failed to orchestrate auto-swarm chain: {e}\nRaw output was: {result if 'result' in locals() else 'None'}"

    # ── Core implementation ──────────────────────────────────────────────────

    def _infer_provider_for_model(self, bare_model: str) -> str | None:
        """
        Given a bare model name (no provider/ prefix), infer the correct provider.
        1. Registry lookup: scan models.yaml entries to find which provider owns this model.
        2. Pattern matching: known model-name prefixes → provider mapping.
        3. Fallback: return the main gateway's current provider.
        """
        bare_lower = bare_model.lower().strip()

        # 1. Registry lookup — check get_all_models() for an exact match
        model_mgr = getattr(self.core, "model_manager", None)
        if model_mgr and hasattr(model_mgr, "get_all_models"):
            for m in model_mgr.get_all_models():
                mid = m["id"].lower()
                # get_all_models returns "provider/model" format
                if "/" in mid:
                    prov, mod = mid.split("/", 1)
                    if mod == bare_lower:
                        return prov

        # 2. Pattern matching — known model name families
        _PATTERN_MAP = {
            "gemini":    "google",
            "gemma":     "google",
            "claude":    "anthropic",
            "gpt":       "openai",
            "o1":        "openai",
            "o3":        "openai",
            "o4":        "openai",
            "codex":     "openai",
            "grok":      "xai",
            "mistral":   "mistral",
            "codestral": "mistral",
            "devstral":  "mistral",
            "deepseek":  "deepseek",
            "llama":     "groq",
            "qwen":      "ollama",
        }
        for prefix, provider in _PATTERN_MAP.items():
            if bare_lower.startswith(prefix):
                return provider

        # 3. Fallback to main agent's provider
        gw = getattr(self.core, "gateway", None)
        if gw:
            return getattr(gw.llm, "provider", None) or getattr(gw, "provider", None)

        return None

    async def spawn(self, task, agent_id="researcher", model=None,
                    chain_id=None, chain_step=None, isolation="") -> str:
        """Spawn a new sub-agent task. Returns session ID."""
        source = "explicit_request"
        
        # 1. Handle explicit overrides or empty values
        if not model or str(model).lower() in ("null", "auto-resolve", "default"):
            # A) First check the dedicated Sub-Agent default model configured by the user
            configured_default = self.core.config.get("subagents", {}).get("default_model")
            if configured_default:
                model = configured_default
                source = "config_default"
            else:
                # B) Fallback to the main agent's model if no subagent default is set
                gateway_model = getattr(self.core.gateway.llm, "model", None)
                if gateway_model:
                    model = gateway_model
                    source = "inherit_main_agent_fallback"
                else:
                    model_mgr = getattr(self.core, "model_manager", None)
                    if model_mgr:
                        model = model_mgr.get_current_model().get("model", "gemini-2.5-flash")
                        source = "model_manager_fallback"
                    else:
                        model = self.core.config.get("gateway", {}).get("model", "gemini-2.5-flash")
                        source = "gateway_config_fallback"
        
        # 2. Handle explicit "same as main agent" instruction
        elif str(model).lower() in ("same", "same as main agent"):
            gateway_model = getattr(self.core.gateway.llm, "model", None)
            if gateway_model:
                model = gateway_model
                source = "inherit_main_agent_explicit"
            else:
                model_mgr = getattr(self.core, "model_manager", None)
                if model_mgr:
                    model = model_mgr.get_current_model().get("model", "gemini-2.5-flash")
                    source = "model_manager_explicit"
                else:
                    model = self.core.config.get("gateway", {}).get("model", "gemini-2.5-flash")
                    source = "gateway_config_explicit"

        # ── Smart Model Resolution ──
        model_mgr = getattr(self.core, "model_manager", None)
        if model_mgr and hasattr(model_mgr, "resolve_model_id"):
            resolved = model_mgr.resolve_model_id(model)
            if resolved != model:
                model = resolved
                source += " (resolved)"

        # ── Authorize Explicit Model Requests ──
        if source.startswith("explicit_request"):
            config_allow_online = self.core.config.get("subagents", {}).get("allow_online_models", False)
            allowed_online = self.core.config.get("subagents", {}).get("allowed_online_models", [])
            
            is_allowed = False
            model_lower = model.lower()
            
            # Extract provider natively, or fallback to inference
            provider = model_lower.split("/")[0] if "/" in model_lower else self._infer_provider_for_model(model)
            
            # Local models are always allowed
            if provider == "ollama":
                is_allowed = True
            elif config_allow_online and model in allowed_online:
                is_allowed = True
                
            if not is_allowed:
                # Override the unauthorized explicit model with the default configured model
                original_req = model
                configured_default = self.core.config.get("subagents", {}).get("default_model")
                
                if configured_default:
                    model = configured_default
                else:
                    gateway_model = getattr(self.core.gateway.llm, "model", None) if hasattr(self.core, 'gateway') and hasattr(self.core.gateway, 'llm') else None
                    if gateway_model:
                        model = gateway_model
                    else:
                        model = "ollama/qwen2.5-coder:14b" # Safe fallback
                
                source = f"unauthorized_override ({original_req} -> {model})"

        session = SubAgentSession(agent_id, task, model, chain_id=chain_id, chain_step=chain_step, isolation=isolation)
        self.active_sessions[session.id] = session
        self._save_session(session)

        await self.core.log(f"SubAgent Spawned [{session.id}]: {agent_id} (Model: {model} [Source: {source}]) → {task[:60]}...", priority=2)
        await self._broadcast_update(session, f"Agent spawned — starting task...")
        await self._chat_notify(f"🤖 Sub-agent spawned: **{agent_id}** · Model: `{model}` · Session: `{session.id}`")

        task_obj = asyncio.create_task(self._run_agent(session))
        session.task_ref = task_obj

        def _on_done(t, sid=session.id):
            if not t.cancelled() and t.exception():
                print(f"[SubAgent] {sid} raised: {t.exception()}")

        task_obj.add_done_callback(_on_done)
        return session.id

    async def spawn_chain(self, steps: list, name="chain") -> str:
        """Spawn a sequential chain. Returns chain ID."""
        chain = AgentChain(steps)
        self.active_chains[chain.id] = chain
        await self.core.log(f"Agent Chain [{chain.id}] started: {len(steps)} steps", priority=2)
        await self._chat_notify(f"⛓️ Chain launched **[{chain.id}]** · {len(steps)} step(s) queued")
        asyncio.create_task(self._run_chain(chain))
        return chain.id

    async def _run_chain(self, chain: AgentChain):
        """Drive sequential chain execution."""
        chain.status   = "running"
        prev_result    = ""
        for i, step in enumerate(chain.steps):
            agent_type     = step.get("agent_type", "researcher")
            step_model     = step.get("model")
            task_template  = step.get("task", "")
            task           = task_template.replace("{prev_result}", prev_result)
            chain.current  = i
            chain.progress_percent = int(((i + 0.1) / len(chain.steps)) * 100)
            await self._chat_notify(f"⛓️ Chain **[{chain.id}]** running step {i+1} of {len(chain.steps)}")

            session_id = await self.spawn(
                task, agent_id=agent_type, model=step_model,
                chain_id=chain.id, chain_step=i
            )
            session = self.active_sessions[session_id]
            chain.sessions.append(session)

            # Wait for this step to finish before proceeding
            while session.status in ("pending", "running"):
                await asyncio.sleep(1)

            if session.status == "cancelled":
                chain.status = "cancelled"
                await self.core.log(f"Chain [{chain.id}] cancelled at step {i+1}", priority=2)
                await self._chat_notify(f"⛓️ Chain **[{chain.id}]** cancelled at step {i+1}/{len(chain.steps)}")
                return

            if session.status == "failed":
                chain.status = "failed"
                await self.core.log(f"Chain [{chain.id}] failed at step {i+1}: {session.result}", priority=1)
                await self._chat_notify(f"❌ Chain **[{chain.id}]** failed at step {i+1}/{len(chain.steps)}: {(session.result or '')[:100]}")
                return

            prev_result = session.result or ""
            chain.progress_percent = int(((i + 1) / len(chain.steps)) * 100)
            if i < len(chain.steps) - 1:
                await self._chat_notify(f"⛓️ Chain **[{chain.id}]** step {i+1}/{len(chain.steps)} done → passing result to next agent...")

        chain.status = "completed"
        await self.core.log(f"Chain [{chain.id}] completed all {len(chain.steps)} steps.", priority=2)
        await self._chat_notify(f"⛓️ Chain **[{chain.id}]** complete! All {len(chain.steps)} steps finished.")

    async def _setup_worktree(self, session: SubAgentSession):
        workspace = os.path.abspath(self.core.config.get('paths', {}).get('workspace', '.'))
        branch_name = f"worktree-branch-{session.id}"
        worktree_path = os.path.join(workspace, f".worktree-{session.id}")
        
        await self.core.log(f"🌿 Setting up isolated git worktree at {worktree_path}...", priority=2)
        try:
            # Add git worktree
            proc = await asyncio.create_subprocess_exec(
                "git", "worktree", "add", "-b", branch_name, worktree_path,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode('utf-8', errors='replace').strip()
                raise Exception(f"git worktree add failed: {err_msg}")
                
            session.worktree_path = worktree_path
            session.worktree_branch = branch_name
            self._save_session(session)
            await self.core.log(f"🌿 Git worktree setup complete for session {session.id}.", priority=2)
        except Exception as e:
            await self.core.log(f"❌ Failed to set up git worktree: {e}", priority=1)
            raise

    async def _teardown_worktree(self, session: SubAgentSession):
        if not session.worktree_path:
            return
            
        workspace = os.path.abspath(self.core.config.get('paths', {}).get('workspace', '.'))
        await self.core.log(f"🧹 Tearing down isolated git worktree at {session.worktree_path}...", priority=2)
        try:
            # git worktree remove --force <path>
            proc = await asyncio.create_subprocess_exec(
                "git", "worktree", "remove", "--force", session.worktree_path,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            
            # git branch -D <branch>
            if session.worktree_branch:
                proc_branch = await asyncio.create_subprocess_exec(
                    "git", "branch", "-D", session.worktree_branch,
                    cwd=workspace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc_branch.communicate()
                
            session.worktree_path = None
            session.worktree_branch = None
            self._save_session(session)
            await self.core.log(f"🧹 Git worktree teardown complete for session {session.id}.", priority=2)
        except Exception as e:
            await self.core.log(f"⚠️ Failed to teardown git worktree: {e}", priority=1)

    async def _run_agent(self, session: SubAgentSession):
        """Run the sub-agent's brain loop."""
        session.status = "running"
        self._save_session(session)

        # Setup worktree if isolation is requested
        if session.isolation == "worktree":
            try:
                await self._setup_worktree(session)
            except Exception as e:
                session.status = "failed"
                session.result = f"[FATAL ERROR] Setup isolation failed: {e}"
                session.end_time = datetime.now()
                self._save_session(session)
                await self._broadcast_done(session)
                return

        try:
            # ── Dynamic Environment Context for Sub-Agents ──
            desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
            if not os.path.exists(desktop):
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            
            env_context = (
                "\n[USER_ENVIRONMENT_CONTEXT]\n"
                f"- CURRENT_USER: {os.getlogin() if hasattr(os, 'getlogin') else 'User'}\n"
                f"- DESKTOP_PATH: {desktop}\n"
                "- ABSOLUTE_PATH_REQUIRED: ALWAYS use absolute paths for tool arguments (e.g., write_file).\n"
                f"- PROJECT_ROOT: {session.worktree_path or os.getcwd()}\n"
            )

            # Custom agent definition / role system prompt loading
            defs = self.load_agent_definitions()
            agent_def = defs.get(session.agent_id)
            
            role_prompt = ""
            if agent_def and agent_def.system_prompt:
                role_prompt = f"\nROLE INSTRUCTIONS ({session.agent_id}):\n{agent_def.system_prompt.strip()}\n"

            # If the agent type specifies a default model and session model is default/empty
            if agent_def and agent_def.model and (not session.model or str(session.model).lower() in ("null", "auto-resolve", "default")):
                session.model = agent_def.model

            context = (
                f"You are a Galactic Sub-Agent ({session.agent_id}). "
                "CRITICAL: You have been provided with a DETAILED BLUEPRINT by the High-Level Orchestrator. "
                "Your job is to execute the provided instructions EXACTLY. Do not deviate, do not hallucinate "
                "new requirements, and do not skip steps unless specifically directed. "
                "Provide a thorough result once complete.\n"
                f"{env_context}\n"
                f"{role_prompt}\n"
                "--- ZERO HALLUCINATION & VERIFICATION POLICY ---\n"
                "- If you are writing code, you MUST use the `read_file` tool AFTER `write_file` to verify syntax and logic.\n"
                "- MANDATORY: Before declaring victory, you MUST perform a 'Verification Turn' where you re-read your output and confirm it is error-free.\n"
                "- If you do NOT see a 'Tool Result (...)' message after your action, your action did NOT happen. You MUST retry or use a different tool.\n"
                "- If this model does not support native tools, use raw JSON blocks: {\"tool\": \"name\", \"args\": {...}}\n"
                "- In your final answer, you MUST explicitly state: 'Verification performed on [filename]. Syntax and logic checked.'\n"
                "- If you find an error during your self-check, FIX IT IMMEDIATELY before notifying the user.\n\n"
                f"--- DETAILED BLUEPRINT ---\n{session.task}"
            )
            session.progress = "Thinking..."
            await self._broadcast_update(session, f"Thinking (Model: {session.model or 'Default'})...")

            # ── Parse the session model into provider + model for speak_isolated ──
            override_provider = None
            override_model    = None
            if session.model:
                raw = session.model
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) >= 2:
                        override_provider = parts[0]
                        override_model    = "/".join(parts[1:])
                else:
                    override_model = raw
                    override_provider = self._infer_provider_for_model(raw)

            result = await self.core.gateway.speak_isolated(
                session.task,
                context=context,
                session_id=session.id,
                override_provider=override_provider,
                override_model=override_model,
                use_lock=False,
                skip_planning=True
            )

            session.result   = result
            session.status   = "completed"
            session.progress_percent = 100
            session.end_time = datetime.now()
            session.progress = "Done"
            self._save_session(session)

            await self.core.log(f"SubAgent [{session.id}] Complete.", priority=2)
            await self._broadcast_done(session)
            await self._chat_notify(f"✅ Sub-agent done **[{session.id}]** · {session.agent_id} · completed in {session.elapsed}")

            # Telegram notification
            if hasattr(self.core, "telegram"):
                chat_id = self.core.config.get("telegram", {}).get("admin_chat_id")
                if chat_id:
                    snippet = (result or "")[:200]
                    await self.core.telegram.send_message(
                        chat_id,
                        f"🤖 Sub-Agent [{session.id}] Finished!\n\nTask: {session.task[:80]}\n\nResult: {snippet}..."
                    )

        except asyncio.CancelledError:
            session.status   = "cancelled"
            session.progress = "Aborted: User Cancelled"
            session.end_time = datetime.now()
            self._save_session(session)
            await self._broadcast_done(session)
            await self._chat_notify(f"🚫 Sub-agent cancelled **[{session.id}]**")
            await self.core.log(f"SubAgent [{session.id}] Cancelled.", priority=2)

        except Exception as e:
            error_msg = f"Crash: {str(e)[:200]}"
            session.status   = "failed"
            session.progress_percent = 100
            session.progress = error_msg
            session.result   = f"[FATAL ERROR] {str(e)}"
            session.end_time = datetime.now()
            self._save_session(session)
            await self.core.log(f"SubAgent [{session.id}] Failed: {error_msg}", priority=1)
            await self._broadcast_done(session)
            await self._chat_notify(f"❌ Sub-agent failed **[{session.id}]** · {error_msg[:120]}")

            if hasattr(self.core, "telegram"):
                chat_id = self.core.config.get("telegram", {}).get("admin_chat_id")
                if chat_id:
                    await self.core.telegram.send_message(
                        chat_id,
                        f"❌ Sub-Agent [{session.id}] Failed!\n\nTask: {session.task[:80]}\n\n{error_msg}"
                    )
        finally:
            if session.isolation == "worktree":
                await self._teardown_worktree(session)

    # ── WebSocket broadcast helpers ──────────────────────────────────────────

    async def _chat_notify(self, msg: str):
        """Send a brief system notice to the chat log for agent lifecycle events."""
        # Notify web UI
        web_deck = getattr(self.core, "web_deck", None)
        if web_deck and hasattr(web_deck, "_broadcast"):
            await web_deck._broadcast({
                "type":    "system_notice",
                "message": msg,
            })
        
        # Notify CLI (progress overlay)
        if hasattr(self.core, "relay") and hasattr(self.core.relay, "emit"):
            await self.core.relay.emit(3, 'progress', {'status': msg})

    async def _broadcast_update(self, session: SubAgentSession, line: str):
        """Emit a subagent_update event to all connected WebSocket clients."""
        session.log_lines.append(line)
        if len(session.log_lines) > self.MAX_LOG_LINES:
            session.log_lines = session.log_lines[-self.MAX_LOG_LINES:]
        session.progress = line[:80]

        web_deck = getattr(self.core, "web_deck", None)
        if web_deck and hasattr(web_deck, "_broadcast"):
            await web_deck._broadcast({
                "type":       "subagent_update",
                "session_id": session.id,
                "agent":      session.agent_id,
                "status":     session.status,
                "elapsed":    session.elapsed,
                "progress":   session.progress,
                "progress_percent": session.progress_percent,
                "log_line":   line,
                "chain_id":   session.chain_id,
                "chain_step": session.chain_step,
            })

    async def _broadcast_done(self, session: SubAgentSession):
        """Emit a subagent_done event."""
        web_deck = getattr(self.core, "web_deck", None)
        if web_deck and hasattr(web_deck, "_broadcast"):
            await web_deck._broadcast({
                "type":           "subagent_done",
                "session_id":     session.id,
                "agent":          session.agent_id,
                "status":         session.status,
                "elapsed":        session.elapsed,
                "result_snippet": (session.result or "")[:400],
                "chain_id":       session.chain_id,
                "chain_step":     session.chain_step,
            })

    # ── Public API for web_deck ──────────────────────────────────────────────

    def get_all_sessions(self) -> list:
        return [s.to_dict() for s in sorted(
            self.active_sessions.values(), key=lambda s: s.start_time, reverse=True
        )]

    def cancel_session(self, session_id: str) -> bool:
        session = self.active_sessions.get(session_id)
        if not session:
            return False
        if session.task_ref and not session.task_ref.done():
            session.task_ref.cancel()
        session.status   = "cancelled"
        session.end_time = datetime.now()
        self._save_session(session)
        asyncio.create_task(self._broadcast_done(session))
        return True

    def clear_completed_sessions(self):
        to_delete = []
        for sid, session in self.active_sessions.items():
            if session.status in ('completed', 'failed', 'cancelled'):
                to_delete.append(sid)
        for sid in to_delete:
            del self.active_sessions[sid]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('DELETE FROM sessions WHERE id = ?', [(sid,) for sid in to_delete])
            conn.commit()
    # ── Background cleanup loop ──────────────────────────────────────────────

    async def run(self):
        await self.core.log("SubAgent Hive Mind Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(30)
            now     = datetime.now()
            expired = [
                sid for sid, s in self.active_sessions.items()
                if (s.status in ("completed", "failed", "cancelled")
                    and (now - s.start_time).total_seconds() > self.SESSION_TTL_SECONDS)
                or (s.status in ("running", "pending")
                    and (now - s.start_time).total_seconds() > self.SESSION_STUCK_TTL)
            ]
            for sid in expired:
                del self.active_sessions[sid]
                # Also delete from SQLite
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute('DELETE FROM sessions WHERE id = ?', (sid,))
                        conn.commit()
                except Exception:
                    pass
            if expired:
                await self.core.log(
                    f"SubAgent cleanup: removed {len(expired)} expired session(s)", priority=3
                )
