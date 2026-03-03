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
from datetime import datetime

from skills.base import GalacticSkill


# ── Session & Chain data classes ─────────────────────────────────────────────

class SubAgentSession:
    def __init__(self, agent_id, task, model, chain_id=None, chain_step=None):
        self.id          = str(uuid.uuid4())[:8]
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

    @property
    def elapsed(self):
        end = self.end_time or datetime.now()
        secs = int((end - self.start_time).total_seconds())
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def to_dict(self):
        return {
            "id":         self.id,
            "agent":      self.agent_id,
            "task":       self.task[:120],
            "status":     self.status,
            "elapsed":    self.elapsed,
            "progress":   self.progress,
            "log_tail":   self.log_lines[-3:],
            "result_snippet": (self.result or "")[:300] if self.status in ("completed", "failed") else None,
            "chain_id":   self.chain_id,
            "chain_step": self.chain_step,
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


# ── Skill ────────────────────────────────────────────────────────────────────

class SubAgentSkill(GalacticSkill):
    """The Hive Mind: spawns and manages isolated sub-agent tasks and chains."""

    skill_name  = "subagent_manager"
    version     = "2.0.0"
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

    # ── Tool definitions ─────────────────────────────────────────────────────

    def get_tools(self):
        return {
            "spawn_subagent": {
                "description": "Spawn an isolated sub-agent to handle a task in the background. Returns a session ID.",
                "parameters": {"type": "object", "properties": {
                    "task":       {"type": "string", "description": "Task description for the sub-agent"},
                    "agent_type": {"type": "string", "description": "Agent role: researcher, coder, analyst, reviewer (default: researcher)"},
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
                    "Spawn a sequential chain of sub-agents where each step can use "
                    "{prev_result} to access the previous step's output. "
                    "Example steps: [{\"agent_type\": \"researcher\", \"task\": \"Research X\"}, "
                    "{\"agent_type\": \"coder\", \"task\": \"Implement based on: {prev_result}\"}]"
                ),
                "parameters": {"type": "object", "properties": {
                    "steps": {
                        "type": "array",
                        "description": "List of {agent_type, task} dicts",
                        "items": {"type": "object"},
                    },
                    "chain_name": {"type": "string", "description": "Optional name for this chain"},
                }, "required": ["steps"]},
                "fn": self._tool_spawn_chain,
            },
        }

    # ── Tool handlers ────────────────────────────────────────────────────────

    async def _tool_spawn_subagent(self, args):
        task       = args.get("task", "")
        agent_type = args.get("agent_type", "researcher")
        if not task:
            return "[ERROR] No task provided."
        try:
            session_id = await self.spawn(task, agent_id=agent_type)
            return f"Sub-agent spawned. Session ID: `{session_id}`. Use check_subagent or the Hive Mind panel to monitor."
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
        if not steps:
            return "[ERROR] No steps provided."
        try:
            chain_id = await self.spawn_chain(steps, name=chain_name)
            return f"Agent chain `{chain_id}` launched with {len(steps)} steps. Monitor in the Hive Mind panel."
        except Exception as e:
            return f"[ERROR] spawn_chain: {e}"

    # ── Core implementation ──────────────────────────────────────────────────

    async def spawn(self, task, agent_id="researcher", model=None,
                    chain_id=None, chain_step=None) -> str:
        """Spawn a new sub-agent task. Returns session ID."""
        if not model:
            model_mgr = getattr(self.core, "model_manager", None)
            if model_mgr:
                model = model_mgr.get_current_model().get("model", "gemini-2.5-flash")
            else:
                model = self.core.config.get("gateway", {}).get("model", "gemini-2.5-flash")

        session = SubAgentSession(agent_id, task, model, chain_id=chain_id, chain_step=chain_step)
        self.active_sessions[session.id] = session

        await self.core.log(f"SubAgent Spawned [{session.id}]: {agent_id} → {task[:60]}...", priority=2)
        await self._broadcast_update(session, f"Agent spawned — starting task...")

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
        # Start the first step
        asyncio.create_task(self._run_chain(chain))
        return chain.id

    async def _run_chain(self, chain: AgentChain):
        """Drive sequential chain execution."""
        chain.status   = "running"
        prev_result    = ""
        for i, step in enumerate(chain.steps):
            agent_type     = step.get("agent_type", "researcher")
            task_template  = step.get("task", "")
            task           = task_template.replace("{prev_result}", prev_result)
            chain.current  = i

            session_id = await self.spawn(
                task, agent_id=agent_type,
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
                return

            if session.status == "failed":
                chain.status = "failed"
                await self.core.log(f"Chain [{chain.id}] failed at step {i+1}: {session.result}", priority=1)
                return

            prev_result = session.result or ""

        chain.status = "completed"
        await self.core.log(f"Chain [{chain.id}] completed all {len(chain.steps)} steps.", priority=2)

    async def _run_agent(self, session: SubAgentSession):
        """Run the sub-agent's brain loop."""
        session.status = "running"
        try:
            context = (
                f"You are a Galactic Sub-Agent ({session.agent_id}). "
                f"Focus ONLY on this task and return a thorough result:\n\n{session.task}"
            )
            session.progress = "Thinking..."
            await self._broadcast_update(session, "Starting task execution...")

            result = await self.core.gateway.speak_isolated(session.task, context=context)

            session.result   = result
            session.status   = "completed"
            session.end_time = datetime.now()
            session.progress = "Done"

            await self.core.log(f"SubAgent [{session.id}] Complete.", priority=2)
            await self._broadcast_done(session)

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
            session.end_time = datetime.now()
            await self._broadcast_done(session)

        except Exception as e:
            session.status   = "failed"
            session.result   = str(e)
            session.end_time = datetime.now()
            await self.core.log(f"SubAgent [{session.id}] Failed: {e}", priority=1)
            await self._broadcast_done(session)

    # ── WebSocket broadcast helpers ──────────────────────────────────────────

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
        asyncio.create_task(self._broadcast_done(session))
        return True

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
            if expired:
                await self.core.log(
                    f"SubAgent cleanup: removed {len(expired)} expired session(s)", priority=3
                )
