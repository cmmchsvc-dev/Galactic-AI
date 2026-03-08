import os
import re
import json
import asyncio
import traceback
from skills.base import GalacticSkill

class ForgeSentinel(GalacticSkill):
    """
    Project Galactic Forge: Sentinel Module.
    Monitors system logs for errors, analyzes root cause, and NOTIFIES the user
    with proposed solutions. Does NOT apply any patches automatically.
    """
    
    skill_name   = "forge_sentinel"
    display_name = "Forge Sentinel (Self-Healing)"
    version      = "1.1.0"
    author       = "Antigravity"
    description  = "Monitors core logs for errors and proposes repair solutions for user approval."
    category     = "system"
    icon         = "🛡️"

    def __init__(self, core):
        super().__init__(core)
        self.log_path = os.path.join(core.config.get('paths', {}).get('logs', './logs'), 'system_log.txt')
        self._last_size = 0
        self._busy = False
        # Track recently notified snippets to avoid spam
        self._last_error_hash = None

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
                await asyncio.sleep(5)  # Watch every 5 seconds
            except Exception as e:
                await self.core.log(f"⚠️ Sentinel watchdog error: {e}", priority=1)
                await asyncio.sleep(10)

    async def check_for_errors(self, current_size):
        if self._busy:
            return
        
        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(self._last_size)
            new_content = f.read()
            
        # Ignore transient or expected errors to prevent notification spam
        if "Traceback" in new_content or "[ERROR]" in new_content:
            if any(x in new_content for x in ("locations_to_try", "404: Publisher Model", "API errors: 3")):
                return
            # Simple hash to avoid duplicate alerts for the same error
            error_hash = hash(new_content[:500])
            if error_hash == self._last_error_hash:
                return
            self._last_error_hash = error_hash
            await self.analyze_and_notify(new_content)

    async def analyze_and_notify(self, error_content):
        """
        Analyze the error log snippet using an isolated LLM call and emit
        a chat notification with the root cause and two or three proposed solutions.
        No files are modified — the user must explicitly request a fix.
        """
        self._busy = True
        try:
            await self.core.log("🚨 Forge Sentinel: Error detected. Analyzing root cause...", priority=2)
            
            prompt = (
                "You are Galactic AI's Forge Sentinel. An error was detected in the system log.\n\n"
                f"```\n{error_content[:3000]}\n```\n\n"
                "Your job is to:\n"
                "1. Identify the root cause in 1-2 sentences.\n"
                "2. Identify the likely file and line number that needs fixing.\n"
                "3. Propose 2-3 specific solution options the user can choose from.\n"
                "Format your response as a short, clear notification message the user will see in chat. "
                "Do NOT apply any fix. Do NOT write code. Just describe what went wrong and what the options are."
            )

            analysis = await self.core.gateway.speak_isolated(
                prompt,
                context="You are the Galactic Forge Sentinel. Analyze errors and propose solutions clearly and concisely."
            )

            # Deliver the analysis as a visible chat message
            await self.core.gateway.speak(
                f"🛡️ **Forge Sentinel Alert**\n\n{analysis.strip()}\n\n"
                f"_To apply a fix, tell me which option to use and I will make the change for your review._"
            )
            await self.core.log("🛡️ Sentinel: Notified user. Awaiting instruction.", priority=2)

        except Exception as e:
            await self.core.log(f"⚠️ Sentinel analysis failed: {e}", priority=1)
        finally:
            self._busy = False
