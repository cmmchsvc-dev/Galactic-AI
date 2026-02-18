import asyncio
import time
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("GalacticScheduler")

class GalacticScheduler:
    def __init__(self, core):
        self.core = core
        self.tasks = []
        self.running = False

    async def add_task(self, name, interval_seconds, func, *args, **kwargs):
        """Schedule a recurring task."""
        task = {
            "name": name,
            "interval": interval_seconds,
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "next_run": time.time() + interval_seconds,
            "last_run": 0
        }
        self.tasks.append(task)
        await self.core.log(f"Scheduled Task: {name} (Every {interval_seconds}s)", priority=2)

    async def add_one_shot(self, name, delay_seconds, func, *args, **kwargs):
        """Schedule a one-time task."""
        task = {
            "name": name,
            "interval": 0, # 0 means one-shot
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "next_run": time.time() + delay_seconds,
            "last_run": 0
        }
        self.tasks.append(task)
        await self.core.log(f"Scheduled One-Shot: {name} (In {delay_seconds}s)", priority=2)

    async def run(self):
        """Main scheduler loop."""
        self.running = True
        logger.info("Scheduler started.")
        while self.running:
            now = time.time()
            to_remove = []
            
            for task in self.tasks:
                if now >= task["next_run"]:
                    try:
                        logger.info(f"Running task: {task['name']}")
                        if asyncio.iscoroutinefunction(task["func"]):
                            await task["func"](*task["args"], **task["kwargs"])
                        else:
                            task["func"](*task["args"], **task["kwargs"])
                        
                        task["last_run"] = now
                        
                        if task["interval"] > 0:
                            task["next_run"] = now + task["interval"]
                        else:
                            to_remove.append(task)
                            
                    except Exception as e:
                        logger.error(f"Task {task['name']} failed: {e}")
                        await self.core.log(f"Task Failed: {task['name']} - {e}", priority=1)
            
            for task in to_remove:
                self.tasks.remove(task)
                
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
