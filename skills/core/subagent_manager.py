"""
Galactic AI -- SubAgent Manager Skill (Phase 3 migration)
Multi-agent task orchestration (Hive Mind).
"""

import asyncio
import json
import uuid
from datetime import datetime

from skills.base import GalacticSkill


class SubAgentSession:
    def __init__(self, agent_id, task, model):
        self.id = str(uuid.uuid4())[:8]
        self.agent_id = agent_id
        self.task = task
        self.model = model
        self.status = "pending"
        self.result = None
        self.start_time = datetime.now()
        self.task_ref = None  # asyncio.Task reference (prevents GC + allows cancellation)


class SubAgentSkill(GalacticSkill):
    """The Hive Mind: Spawns and manages isolated sub-agent runs."""

    skill_name  = "subagent_manager"
    version     = "1.1.2"
    author      = "Galactic AI"
    description = "Multi-agent task orchestration (Hive Mind)."
    category    = "system"
    icon        = "\U0001f916"

    # Legacy name for web_deck compat
    name = "SubAgentManager"

    SESSION_TTL_SECONDS = 3600      # Clean up completed/failed sessions after 1 hour
    SESSION_STUCK_TTL = 14400       # Clean up stuck running/pending sessions after 4 hours

    def __init__(self, core):
        super().__init__(core)
        self.active_sessions = {}

    # ── GalacticSkill: tool definitions ──────────────────────────────────

    def get_tools(self):
        return {
            "spawn_subagent": {
                "description": "Spawn an isolated sub-agent to handle a task in the background. Returns a session ID to check later.",
                "parameters": {"type": "object", "properties": {
                    "task": {"type": "string", "description": "Task description for the sub-agent"},
                    "agent_type": {"type": "string", "description": "Agent role: researcher, coder, analyst (default: researcher)"},
                }, "required": ["task"]},
                "fn": self._tool_spawn_subagent
            },
            "check_subagent": {
                "description": "Check the status and result of a previously spawned sub-agent.",
                "parameters": {"type": "object", "properties": {
                    "session_id": {"type": "string", "description": "Session ID from spawn_subagent"},
                }, "required": ["session_id"]},
                "fn": self._tool_check_subagent
            },
        }

    # ── Tool handlers ────────────────────────────────────────────────────

    async def _tool_spawn_subagent(self, args):
        """Spawn a background sub-agent."""
        task = args.get('task', '')
        agent_type = args.get('agent_type', 'researcher')
        if not task:
            return "[ERROR] No task provided."
        try:
            session_id = await self.spawn(task, agent_id=agent_type)
            return f"Sub-agent spawned. Session ID: {session_id}. Use check_subagent to get results."
        except Exception as e:
            return f"[ERROR] spawn_subagent: {e}"

    async def _tool_check_subagent(self, args):
        """Check sub-agent status."""
        session_id = args.get('session_id', '')
        if not session_id:
            return "[ERROR] No session_id provided."
        session = self.active_sessions.get(session_id)
        if not session:
            return f"[ERROR] Session {session_id} not found."
        result = {
            "id": session.id,
            "agent": session.agent_id,
            "task": session.task[:100],
            "status": session.status,
            "result": (session.result or "")[:2000] if session.status == "completed" else None,
        }
        return json.dumps(result, indent=2)

    # ── Implementation (copied verbatim from plugins/subagent_manager.py) ─

    async def spawn(self, task, agent_id="researcher", model=None):
        """Spawn a new sub-agent task."""
        if not model:
            model_mgr = getattr(self.core, 'model_manager', None)
            if model_mgr:
                model = model_mgr.get_current_model()['model']
            else:
                model = self.core.config.get('gateway', {}).get('model', 'gemini-2.5-flash')

        session = SubAgentSession(agent_id, task, model)
        self.active_sessions[session.id] = session

        await self.core.log(f"SubAgent Spawned [{session.id}]: {agent_id} -> {task[:30]}...", priority=2)

        # Async execution -- store task ref to prevent GC and enable error logging
        task_obj = asyncio.create_task(self._run_agent(session))
        session.task_ref = task_obj

        def _on_done(t, sid=session.id):
            """Log unhandled exceptions from the sub-agent task."""
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                print(f"[SubAgent] Task {sid} raised unhandled exception: {exc}")

        task_obj.add_done_callback(_on_done)
        return session.id

    async def _run_agent(self, session):
        """Internal runner for the sub-agent brain."""
        session.status = "running"
        try:
            # Sub-agents use the Gateway with isolated state via speak_isolated()
            context = f"You are a Galactic Sub-Agent ({session.agent_id}). Focus ONLY on this task: {session.task}"

            result = await self.core.gateway.speak_isolated(session.task, context=context)

            session.result = result
            session.status = "completed"

            await self.core.log(f"SubAgent [{session.id}] Task Complete.", priority=2)

            if hasattr(self.core, 'telegram'):
                chat_id = self.core.config.get('telegram', {}).get('admin_chat_id')
                if chat_id:
                    await self.core.telegram.send_message(chat_id, f"Sub-Agent [{session.id}] Finished!\n\nTask: {session.task[:50]}...\n\nResult: {result[:200]}...")

        except Exception as e:
            session.status = "failed"
            session.result = str(e)
            await self.core.log(f"SubAgent [{session.id}] Failed: {e}", priority=1)

    async def run(self):
        """Background loop -- session cleanup."""
        await self.core.log("SubAgent Hive Mind Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(30)
            # Clean up completed/failed sessions older than TTL
            now = datetime.now()
            expired = [
                sid for sid, session in self.active_sessions.items()
                if (session.status in ("completed", "failed")
                    and (now - session.start_time).total_seconds() > self.SESSION_TTL_SECONDS)
                or (session.status in ("running", "pending")
                    and (now - session.start_time).total_seconds() > self.SESSION_STUCK_TTL)
            ]
            for sid in expired:
                del self.active_sessions[sid]
            if expired:
                await self.core.log(
                    f"SubAgent cleanup: removed {len(expired)} expired session(s)",
                    priority=3
                )
