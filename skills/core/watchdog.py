"""
Watchdog Skill for Galactic AI.
Monitors system health and breaks deadlocks or hangs.
"""
import asyncio
import time
import os
from skills.base import GalacticSkill

class WatchdogSkill(GalacticSkill):
    """
    The 'Guardian' of Galactic AI.
    Periodically checks if the system is unresponsive during long tasks.
    """
    
    def __init__(self, core):
        super().__init__(core)
        self.skill_name  = "watchdog"
        self.description = "Monitors system health, detects hung tasks, and auto-recovers deadlocked ReAct loops."
        self.category    = "system"
        self.icon        = "🐕"
        self.check_interval = 30  # seconds
        self.hang_threshold = 3600 # seconds (60 mins)
        self._last_heartbeat = time.time()
        self._monitor_task = None
        self._consecutive_hangs = 0

    def get_tools(self):
        return {
            "get_system_health": {
                "description": "Check the health and status of Galactic AI's internal monitors.",
                "parameters": {"type": "object", "properties": {}},
                "fn": self._tool_get_health
            }
        }

    async def _tool_get_health(self, args):
        uptime = time.time() - self._last_heartbeat
        status = "Healthy" if uptime < self.hang_threshold else "Stalled"
        return f"System Status: {status}\nUptime since last heartbeat: {int(uptime)}s\nConsecutive hangs recovered: {self._consecutive_hangs}"

    def heartbeat(self):
        """Called by Gateway or Core to indicate activity."""
        self._last_heartbeat = time.time()

    async def _monitor_loop(self):
        """Background loop to check for hangs."""
        await asyncio.sleep(10) # Initial cooldown
        while self.enabled:
            try:
                now = time.time()
                idle_time = now - self._last_heartbeat
                
                # Check if we are currently 'speaking' (running a ReAct loop)
                gateway = getattr(self.core, 'gateway', None)
                is_busy = getattr(gateway, '_speaking', False) if gateway else False
                
                if is_busy and idle_time > self.hang_threshold:
                    await self.core.log(f"🚨 WATCHDOG: System appears hung! Idle for {int(idle_time)}s while busy.", priority=1)
                    
                    # Intervention logic:
                    # 1. Try to cancel active tasks in the gateway
                    if gateway and hasattr(gateway, '_active_tasks'):
                        for task in list(gateway._active_tasks):
                            if not task.done():
                                await self.core.log(f"Watchdog: Cancelling hung task: {task.get_name()}", priority=2)
                                task.cancel()
                                self._consecutive_hangs += 1
                    
                    # 2. Reset the speaking flag to allow new requests
                    if gateway:
                        gateway._speaking = False
                    
                    # 3. Reset heartbeat to prevent immediate re-trigger
                    self.heartbeat()
                
                elif not is_busy:
                    # System is idle, just update heartbeat to now to show we are monitoring
                    self.heartbeat()
                    
            except Exception as e:
                await self.core.log(f"Watchdog loop error: {e}", priority=1)
                
            await asyncio.sleep(self.check_interval)

    async def run(self):
        await self.core.log("Watchdog Guardian Active.", priority=2)
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        try:
            while self.enabled:
                await asyncio.sleep(1)
        finally:
            if self._monitor_task:
                self._monitor_task.cancel()
