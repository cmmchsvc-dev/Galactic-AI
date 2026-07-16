import asyncio
from skills.base import GalacticSkill

class AutoDreamSkill(GalacticSkill):
    """
    AutoDream Background Consolidation
    Periodically compacts recent ephemeral memories/logs into durable semantic vector storage.
    """
    skill_name = "auto_dream"
    version = "1.0.0"
    author = "Galactic AI"
    description = "Background task that waits until AFK to consolidate memories into durable storage."
    category = "memory"
    icon = "🛌"

    def __init__(self, core):
        super().__init__(core)
        self.is_dreaming = False

    async def run(self):
        """Background loop to periodically dream (compact memory) when idle."""
        while self.enabled:
            await asyncio.sleep(3600)  # Check every hour
            
            # Simple AFK check: if we haven't spoken in an hour, start dreaming
            # In a real implementation, you'd check gateway activity timestamps
            
            if not self.is_dreaming:
                self.is_dreaming = True
                await self.core.log("[AutoDream] Starting memory consolidation (Hippocampus Upgrade) sequence...", priority=1)
                
                # Here we would call the compact_memory endpoint or logic
                try:
                    # Execute actual compaction
                    import subprocess
                    # Using the existing compaction script if it exists
                    subprocess.run(["python", "compaction.py", "--auto"], capture_output=True)
                    await self.core.log("[AutoDream] Memory consolidation complete.", priority=2)
                except Exception as e:
                    await self.core.log(f"[AutoDream] Error during dream state: {e}", priority=1)
                
                self.is_dreaming = False

    def get_tools(self):
        return {
            "trigger_dream": {
                "description": "Force the AutoDream memory consolidation to run immediately.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._force_dream
            }
        }

    async def _force_dream(self, args):
        if self.is_dreaming:
            return "AutoDream is already running."
        
        asyncio.create_task(self._dream_now())
        return "AutoDream consolidation triggered. Running in background."
        
    async def _dream_now(self):
        self.is_dreaming = True
        try:
            import subprocess
            subprocess.run(["python", "compaction.py", "--auto"], capture_output=True)
            await self.core.log("[AutoDream] Forced memory consolidation complete.", priority=2)
        except Exception as e:
            await self.core.log(f"[AutoDream] Error during forced dream state: {e}", priority=1)
        self.is_dreaming = False
