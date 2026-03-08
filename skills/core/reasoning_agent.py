"""
Galactic AI -- Reasoning Agent Skill v1.0
Specialized sub-agent with advanced reasoning, reflection, and spatial awareness.
Designed to mimic the 'Agentic Soul' demonstrated in Galactic AI v1.6.1.
"""

import asyncio
import json
import uuid
from datetime import datetime
from skills.base import GalacticSkill
from skills.util.monologue_formatter import MonologueFormatter

class ReasoningSubAgentSession:
    def __init__(self, task, model, agent_id="reasoner"):
        self.id = str(uuid.uuid4())[:8]
        self.agent_id = agent_id
        self.task = task
        self.model = model
        self.status = "pending"  # pending | running | completed | failed | cancelled
        self.result = None
        self.start_time = datetime.now()
        self.end_time = None
        self.log_lines = []
        self.progress = ""
        self.task_ref = None

    @property
    def elapsed(self):
        end = self.end_time or datetime.now()
        secs = int((end - self.start_time).total_seconds())
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def to_dict(self):
        return {
            "id": self.id,
            "agent": self.agent_id,
            "task": self.task[:120],
            "status": self.status,
            "elapsed": self.elapsed,
            "progress": self.progress,
            "result_snippet": (self.result or "")[:300] if self.status in ("completed", "failed") else None,
        }

class ReasoningAgentSkill(GalacticSkill):
    """Specialized agent skill providing enhanced reasoning and reflection loops."""

    skill_name = "reasoning_agent"
    version = "1.0.0"
    author = "Galactic AI"
    description = "Advanced reasoning and reflection agent for complex tasks."
    category = "core"
    icon = "🧠"

    def __init__(self, core):
        super().__init__(core)
        self.active_sessions: dict[str, ReasoningSubAgentSession] = {}

    def get_tools(self):
        return {
            "spawn_reasoning_agent": {
                "description": "Spawn a specialized reasoning sub-agent for complex tasks requiring high-level planning and reflection.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Complex task for the reasoning agent"},
                        "model": {"type": "string", "description": "Optional: Model to use (defaults to current model)"}
                    },
                    "required": ["task"]
                },
                "fn": self._tool_spawn_reasoning_agent,
            }
        }

    async def _tool_spawn_reasoning_agent(self, args):
        task = args.get("task")
        model = args.get("model")
        session_id = await self.spawn(task, model=model)
        return f"Reasoning agent spawned. Session ID: `{session_id}`. Monitor output in the Hive Mind or logs."

    async def spawn(self, task, model=None):
        if not model:
            model_mgr = getattr(self.core, "model_manager", None)
            model = model_mgr.get_current_model().get("model", "gemini-2.5-flash") if model_mgr else "gemini-2.5-flash"

        session = ReasoningSubAgentSession(task, model)
        self.active_sessions[session.id] = session
        
        await self.core.log(f"🧠 Reasoning Agent Spawned [{session.id}]: {task[:60]}...", priority=2)
        
        task_obj = asyncio.create_task(self._run_reasoning_loop(session))
        session.task_ref = task_obj
        return session.id

    async def _run_reasoning_loop(self, session):
        """Advanced ReAct loop with explicit Reflection turns."""
        session.status = "running"
        try:
            # The 'Agentic Soul' System Prompt
            system_context = (
                "You are an Elite Galactic Reasoning Agent. Your goal is to execute the following task with extreme precision and reliability.\n\n"
                "TASK:\n"
                f"{session.task}\n\n"
                "REASONING PROTOCOL:\n"
                "For every action, you MUST follow this internal monologue structure:\n"
                "[PLAN]: What you attend to do next.\n"
                "[OBSERVATION]: What you see in the current environment (DOM, logs, file content).\n"
                "[ANALYSIS]: Your interpretation of why things are happening.\n"
                "[REFLECTION]: Critique your own previous steps. Did they work? Why or why not?\n"
                "[DECISION]: Which tool you will call and why.\n\n"
                "CRITICAL: Be proactive and self-correcting. If a tool fails, REFLECT and try a different approach. "
                "You have full authorization to manage accounts, credentials, and complex file operations."
            )

            # Isolated speak call to use the main gateway's ReAct engine but with our specialized context
            # We use speak_isolated to ensure we don't mess with the main conversation state.
            session.progress = "Thinking..."
            result = await self.core.gateway.speak_isolated(
                user_input=session.task,
                context=system_context,
                override_model=session.model,
                use_lock=True
            )

            # Apply monologue formatting to the final result for presentation
            session.result = MonologueFormatter.format_text(result)
            session.status = "completed"
            session.end_time = datetime.now()
            session.progress = "Task Complete"
            
            await self.core.log(f"🧠 Reasoning Agent [{session.id}] Finished.", priority=2)

        except asyncio.CancelledError:
            session.status = "cancelled"
            session.end_time = datetime.now()
        except Exception as e:
            session.status = "failed"
            session.result = str(e)
            session.end_time = datetime.now()
            await self.core.log(f"🧠 Reasoning Agent [{session.id}] Failed: {e}", priority=1)
