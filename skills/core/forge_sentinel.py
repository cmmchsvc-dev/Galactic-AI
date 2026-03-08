import os
import time
import asyncio
import traceback
from skills.base import GalacticSkill

class ForgeSentinel(GalacticSkill):
    """
    Project Galactic Forge: Sentinel Module.
    Proactively monitors system logs and repairs errors via the Forge.
    """
    
    skill_name   = "forge_sentinel"
    display_name = "Forge Sentinel (Self-Healing)"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Monitors core logs for errors and autonomously synthesizes repairs."
    category     = "system"
    icon         = "🛡️"

    def __init__(self, core):
        super().__init__(core)
        self.log_path = os.path.join(core.config.get('paths', {}).get('logs', './logs'), 'system_log.txt')
        self._last_size = 0
        self._busy = False

    async def run(self):
        await self.core.log("🛡️ Forge Sentinel standing guard. Monitoring system_log.txt...", priority=3)
        
        # Initialize mark
        if os.path.exists(self.log_path):
            self._last_size = os.path.getsize(self.log_path)

        while True:
            try:
                if os.path.exists(self.log_path):
                    current_size = os.path.getsize(self.log_path)
                    if current_size > self._last_size:
                        await self.check_for_errors(current_size)
                        self._last_size = current_size
                await asyncio.sleep(5) # Watch every 5 seconds
            except Exception as e:
                await self.core.log(f"⚠️ Sentinel watchdog error: {e}", priority=1)
                await asyncio.sleep(10)

    async def check_for_errors(self, current_size):
        if self._busy: return
        
        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(self._last_size)
            new_content = f.read()
            
        # Ignore certain transient or expected errors to prevent configuration revert loops
        if "Traceback" in new_content or "[ERROR]" in new_content:
            if any(x in new_content for x in ("locations_to_try", "404: Publisher Model", "API errors: 3")):
                return
            await self.process_error(new_content)

    async def process_error(self, content):
        self._busy = True
        try:
            await self.core.log("🚨 Forge Sentinel: Error detected. Analyzing for autonomous repair...", priority=2)
            
            # Use the Forge to synthesize a fix
            forge = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'forge'), None)
            if not forge:
                await self.core.log("⚠️ Sentinel: Forge skill not found. Self-healing aborted.", priority=1)
                return

            # Analyze error with LLM to find offending file/fix
            analysis_prompt = (
                f"I am the Galactic AI Forge Sentinel. I detected the following error in the logs:\n\n"
                f"```\n{content}\n```\n\n"
                f"Identify the file path and the likely fix. Respond ONLY with the absolute path of the file to patch."
            )
            
            target_file = await self.core.gateway.speak_isolated(analysis_prompt)
            target_file = target_file.strip().strip('`').strip()
            
            if os.path.exists(target_file):
                await self.core.log(f"🛠️ Sentinel: Targeting repair for {os.path.basename(target_file)}...", priority=2)
                # In a real scenario, the Forge would generate a patch and apply it.
                # Here we trigger a Forge synthesis request.
                await forge.synthesize_skill_patch(target_file, content)
            else:
                await self.core.log(f"⚠️ Sentinel: Could not identify target file from log snippet.", priority=3)

        except Exception as e:
            await self.core.log(f"⚠️ Sentinel repair loop failed: {e}", priority=1)
        finally:
            self._busy = False
