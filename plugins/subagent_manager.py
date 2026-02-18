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

class SubAgentPlugin(GalacticPlugin):
    """The Hive Mind: Spawns and manages isolated sub-agent runs."""
    def __init__(self, core):
        super().__init__(core)
        self.name = "SubAgentManager"
        self.active_sessions = {}

    async def spawn(self, task, agent_id="researcher", model=None):
        """Spawn a new sub-agent task."""
        model = model or self.core.config['gateway']['model']
        session = SubAgentSession(agent_id, task, model)
        self.active_sessions[session.id] = session
        
        await self.core.log(f"SubAgent Spawned [{session.id}]: {agent_id} -> {task[:30]}...", priority=2)
        
        # Async execution of the sub-agent task
        asyncio.create_task(self._run_agent(session))
        return session.id

    async def _run_agent(self, session):
        """Internal runner for the sub-agent brain."""
        session.status = "running"
        try:
            # Sub-agents use the Gateway but with a specific 'Analytic' context
            context = f"You are a Galactic Sub-Agent ({session.agent_id}). Focus ONLY on this task: {session.task}"
            
            # Simulate high-intensity thinking
            result = await self.core.gateway.speak(session.task, context=context)
            
            session.result = result
            session.status = "completed"
            
            # Notify the core/user
            await self.core.log(f"SubAgent [{session.id}] Task Complete.", priority=2)
            
            if hasattr(self.core, 'telegram'):
                chat_id = self.core.config.get('telegram', {}).get('admin_chat_id')
                if chat_id:
                    await self.core.telegram.send_message(chat_id, f"🧠 **Sub-Agent [{session.id}] Finished!**\n\nTask: {session.task[:50]}...\n\nResult: {result[:200]}...")
                    
        except Exception as e:
            session.status = "failed"
            session.result = str(e)
            await self.core.log(f"SubAgent [{session.id}] Failed: {e}", priority=1)

    async def run(self):
        await self.core.log("SubAgent Hive Mind Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
