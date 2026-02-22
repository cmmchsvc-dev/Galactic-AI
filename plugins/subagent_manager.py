import asyncio
import os
import json
import uuid
from datetime import datetime

class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True
    async def run(self):
        pass

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

class SubAgentPlugin(GalacticPlugin):
    """The Hive Mind: Spawns and manages isolated sub-agent runs."""

    SESSION_TTL_SECONDS = 3600      # Clean up completed/failed sessions after 1 hour
    SESSION_STUCK_TTL = 14400       # Clean up stuck running/pending sessions after 4 hours

    def __init__(self, core):
        super().__init__(core)
        self.name = "SubAgentManager"
        self.active_sessions = {}

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

        # Async execution — store task ref to prevent GC and enable error logging
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
