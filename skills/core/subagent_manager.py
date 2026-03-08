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
from datetime import datetime

from skills.base import GalacticSkill


# ── Session & Chain data classes ─────────────────────────────────────────────

class SubAgentSession:
    def __init__(self, agent_id, task, model, chain_id=None, chain_step=None):
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
    version     = "1.6.3"
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
                "description": (
                    "Spawn an isolated sub-agent to handle a task in the background. "
                    "This is FULLY ASYNCHRONOUS; the main agent (you) remains free for conversation "
                    "immediately after spawning. Use this to delegate work while you continue chatting. "
                    "Returns a session ID."
                ),
                "parameters": {"type": "object", "properties": {
                    "task":       {"type": "string", "description": "A High-Quality Technical Blueprint. Include: 1. Absolute file paths (MUST), 2. Detailed logic steps, 3. Defensive Context (explicitly warn about common pitfalls like Canvas state leaks or syntax validation), 4. Mandatory Self-Verification turn where the sub-agent reads the file back."},
                    "agent_type": {"type": "string", "description": "Agent role: researcher, coder, analyst, reviewer (default: researcher)"},
                    "model":      {"type": "string", "description": "Specific model ID. Fuzzy names like 'Qwen3' or 'Ollama/Qwen' are supported and will be auto-resolved to the full system ID."},
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
                        "description": "List of {agent_type, task, model} dicts. EACH task MUST be a clear technical plan.",
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
        model      = args.get("model")
        if not task:
            return "[ERROR] No task provided."
        try:
            session_id = await self.spawn(task, agent_id=agent_type, model=model)
            return (
                f"Sub-agent spawned. Session ID: `{session_id}`. "
                "CRITICAL: This agent will handle the task independently. Your responsibility for this "
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

    # ── Core implementation ──────────────────────────────────────────────────

    async def spawn(self, task, agent_id="researcher", model=None,
                    chain_id=None, chain_step=None) -> str:
        """Spawn a new sub-agent task. Returns session ID."""
        if not model:
            # 1. config.yaml subagents.default_model
            model = self.core.config.get("subagents", {}).get("default_model")
        
        if not model:
            # 2. active model from ModelManager
            model_mgr = getattr(self.core, "model_manager", None)
            if model_mgr:
                model = model_mgr.get_current_model().get("model", "gemini-2.5-flash")
            else:
                model = self.core.config.get("gateway", {}).get("model", "gemini-2.5-flash")

        # ── Smart Model Resolution ──
        model_mgr = getattr(self.core, "model_manager", None)
        if model_mgr and hasattr(model_mgr, "resolve_model_id"):
            resolved = model_mgr.resolve_model_id(model)
            if resolved != model:
                model = resolved

        session = SubAgentSession(agent_id, task, model, chain_id=chain_id, chain_step=chain_step)
        self.active_sessions[session.id] = session

        await self.core.log(f"SubAgent Spawned [{session.id}]: {agent_id} (Model: {model}) → {task[:60]}...", priority=2)
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
            if i < len(chain.steps) - 1:
                await self._chat_notify(f"⛓️ Chain **[{chain.id}]** step {i+1}/{len(chain.steps)} done → passing result to next agent...")

        chain.status = "completed"
        await self.core.log(f"Chain [{chain.id}] completed all {len(chain.steps)} steps.", priority=2)
        await self._chat_notify(f"⛓️ Chain **[{chain.id}]** complete! All {len(chain.steps)} steps finished.")

    async def _run_agent(self, session: SubAgentSession):
        """Run the sub-agent's brain loop."""
        session.status = "running"
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
                f"- PROJECT_ROOT: {os.getcwd()}\n"
            )

            context = (
                f"You are a Galactic Sub-Agent ({session.agent_id}). "
                "CRITICAL: You have been provided with a DETAILED BLUEPRINT by the High-Level Orchestrator. "
                "Your job is to execute the provided instructions EXACTLY. Do not deviate, do not hallucinate "
                "new requirements, and do not skip steps unless specifically directed. "
                "Provide a thorough result once complete.\n"
                f"{env_context}\n"
                "--- ZERO HALLUCINATION & VERIFICATION POLICY ---\n"
                "- If you are writing code, you MUST use the `read_file` tool AFTER `write_file` to verify syntax and logic.\n"
                "- MANDATORY: Before declaring victory, you MUST perform a 'Verification Turn' where you re-read your output and confirm it is error-free.\n"
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
                # Handle "provider/model" format (e.g. "ollama/qwen3.5:27b",
                # "openrouter/anthropic/claude-3-5-sonnet", or bare "gemini-2.5-flash")
                if "/" in raw:
                    parts = raw.split("/")
                    if len(parts) >= 2:
                        override_provider = parts[0]
                        override_model    = "/".join(parts[1:])
                else:
                    # Bare model ID: try to infer provider from ModelManager
                    model_mgr = getattr(self.core, "model_manager", None)
                    if model_mgr and hasattr(model_mgr, "_infer_provider"):
                        override_provider = model_mgr._infer_provider(raw)
                    override_model = raw

            result = await self.core.gateway.speak_isolated(
                session.task,
                context=context,
                session_id=session.id,
                override_provider=override_provider,
                override_model=override_model,
                skip_planning=True # Optimization: Caller provides the plan/task
            )

            session.result   = result
            session.status   = "completed"
            session.end_time = datetime.now()
            session.progress = "Done"

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
            await self._broadcast_done(session)
            await self._chat_notify(f"🚫 Sub-agent cancelled **[{session.id}]**")
            await self.core.log(f"SubAgent [{session.id}] Cancelled.", priority=2)

        except Exception as e:
            # We assume gateway_v3 emitted a session_abort trace before re-raising.
            error_msg = f"Crash: {str(e)[:200]}"
            session.status   = "failed"
            session.progress = error_msg
            session.result   = f"[FATAL ERROR] {str(e)}"
            session.end_time = datetime.now()
            await self.core.log(f"SubAgent [{session.id}] Failed: {error_msg}", priority=1)
            await self._broadcast_done(session)
            await self._chat_notify(f"❌ Sub-agent failed **[{session.id}]** · {error_msg[:120]}")

            # Telegram notification for failure
            if hasattr(self.core, "telegram"):
                chat_id = self.core.config.get("telegram", {}).get("admin_chat_id")
                if chat_id:
                    await self.core.telegram.send_message(
                        chat_id,
                        f"❌ Sub-Agent [{session.id}] Failed!\n\nTask: {session.task[:80]}\n\n{error_msg}"
                    )

    # ── WebSocket broadcast helpers ──────────────────────────────────────────

    async def _chat_notify(self, msg: str):
        """Send a brief system notice to the chat log for agent lifecycle events."""
        web_deck = getattr(self.core, "web_deck", None)
        if web_deck and hasattr(web_deck, "_broadcast"):
            await web_deck._broadcast({
                "type":    "system_notice",
                "message": msg,
            })

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
