import asyncio
import time
import json
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("GalacticScheduler")

CRON_FILE = os.path.join(os.path.dirname(__file__), "logs", "cron_tasks.json")

class GalacticScheduler:
    def __init__(self, core):
        self.core = core
        self.tasks = []
        self.cron_tasks = []
        self.running = False
        self._load_cron_tasks()

    # ── Persistent cron storage ──────────────────────────────────────

    def _load_cron_tasks(self):
        """Load persisted cron tasks from disk."""
        if os.path.exists(CRON_FILE):
            try:
                with open(CRON_FILE, 'r') as f:
                    saved = json.load(f)
                for entry in saved:
                    self.cron_tasks.append({
                        "name": entry["name"],
                        "cron_expr": entry["cron_expr"],
                        "action": entry["action"],  # stored as string (AI prompt)
                        "last_run": 0,
                    })
                logger.info(f"Loaded {len(saved)} cron tasks from {CRON_FILE}")
            except Exception as e:
                logger.error(f"Failed to load cron tasks: {e}")

    def _save_cron_tasks(self):
        """Persist cron tasks to disk."""
        os.makedirs(os.path.dirname(CRON_FILE), exist_ok=True)
        saveable = []
        for t in self.cron_tasks:
            saveable.append({
                "name": t["name"],
                "cron_expr": t["cron_expr"],
                "action": t["action"] if isinstance(t["action"], str) else "(callable)",
            })
        try:
            with open(CRON_FILE, 'w') as f:
                json.dump(saveable, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cron tasks: {e}")

    # ── Original interval-based API (backward-compatible) ────────────

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

    # ── Cron-style API ───────────────────────────────────────────────

    async def add_cron(self, name, cron_expr, action, persist=True):
        """Schedule a cron-style task.

        Args:
            name: Task name
            cron_expr: Cron expression (e.g., "0 9 * * *" = daily at 9am)
            action: Either a string (processed as AI prompt) or a callable
            persist: If True, save to disk so it survives restarts
        """
        # Remove any existing task with the same name
        self.cron_tasks = [t for t in self.cron_tasks if t["name"] != name]

        self.cron_tasks.append({
            "name": name,
            "cron_expr": cron_expr,
            "action": action,
            "last_run": 0,
        })

        if persist and isinstance(action, str):
            self._save_cron_tasks()

        await self.core.log(f"Scheduled Cron: {name} ({cron_expr})", priority=2)

    def _cron_matches(self, cron_expr, dt):
        """Check if a datetime matches a cron expression.
        Supports: minute hour day-of-month month day-of-week
        Each field can be: * (any), N (exact), */N (every N), N-M (range)
        """
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return False

        values = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday() % 7]  # 0=Sun
        # Also support 7 as Sunday for convenience
        for i, (field, value) in enumerate(zip(fields, values)):
            if not self._cron_field_matches(field, value, i):
                return False
        return True

    def _cron_field_matches(self, field, value, field_index):
        """Check if a single cron field matches a value."""
        if field == '*':
            return True

        for part in field.split(','):
            # Handle step: */N or N-M/S
            step = 1
            if '/' in part:
                part, step_str = part.split('/', 1)
                try:
                    step = int(step_str)
                except ValueError:
                    return False

            # Handle range: N-M
            if '-' in part and part != '*':
                try:
                    low, high = part.split('-', 1)
                    low, high = int(low), int(high)
                    if step > 1:
                        if value in range(low, high + 1, step):
                            return True
                    else:
                        if low <= value <= high:
                            return True
                except ValueError:
                    return False
            elif part == '*':
                # */N — step over full range
                ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
                low, high = ranges[field_index]
                if (value - low) % step == 0:
                    return True
            else:
                try:
                    if int(part) == value:
                        return True
                except ValueError:
                    return False
        return False

    # ── Main loop ────────────────────────────────────────────────────

    async def run(self):
        """Main scheduler loop."""
        self.running = True
        logger.info("Scheduler started.")
        while self.running:
            now = time.time()
            to_remove = []

            # ── Interval-based tasks ──
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

            # ── Cron-based tasks ──
            dt_now = datetime.now()
            for ctask in self.cron_tasks:
                if self._cron_matches(ctask["cron_expr"], dt_now):
                    # Only fire once per matching minute
                    minute_key = dt_now.strftime("%Y%m%d%H%M")
                    if ctask.get("_last_minute_key") == minute_key:
                        continue
                    ctask["_last_minute_key"] = minute_key
                    ctask["last_run"] = now

                    try:
                        logger.info(f"Running cron task: {ctask['name']}")
                        action = ctask["action"]
                        if isinstance(action, str):
                            # AI prompt — process through gateway
                            resp = await asyncio.wait_for(
                                self.core.gateway.speak(action, chat_id=f"cron:{ctask['name']}"),
                                timeout=120.0
                            )
                            await self.core.relay.emit(2, "cron_executed", {
                                "name": ctask["name"],
                                "prompt": action[:200],
                                "response": (resp or "")[:200],
                            })
                        elif callable(action):
                            if asyncio.iscoroutinefunction(action):
                                await action()
                            else:
                                action()
                    except asyncio.TimeoutError:
                        logger.error(f"Cron task {ctask['name']} timed out")
                        await self.core.log(f"Cron task timed out: {ctask['name']}", priority=1)
                    except Exception as e:
                        logger.error(f"Cron task {ctask['name']} failed: {e}")
                        await self.core.log(f"Cron task failed: {ctask['name']} - {e}", priority=1)

            await asyncio.sleep(1)

    async def stop(self):
        self.running = False

    # ── Gateway tool definitions ─────────────────────────────────────

    def get_tool_definitions(self):
        return {
            "schedule_task": {
                "description": "Schedule a recurring AI task using cron syntax. Examples: '0 9 * * *' = daily at 9am, '*/30 * * * *' = every 30 minutes, '0 0 * * 1' = every Monday at midnight.",
                "parameters": {
                    "name": {"type": "string", "description": "Task name"},
                    "cron": {"type": "string", "description": "Cron expression (minute hour day month weekday)"},
                    "prompt": {"type": "string", "description": "AI prompt to execute on schedule"},
                },
                "fn": self._tool_schedule_task
            },
            "list_scheduled_tasks": {
                "description": "List all scheduled and cron tasks.",
                "parameters": {},
                "fn": self._tool_list_tasks
            },
            "remove_scheduled_task": {
                "description": "Remove a scheduled task by name.",
                "parameters": {
                    "name": {"type": "string", "description": "Task name to remove"}
                },
                "fn": self._tool_remove_task
            }
        }

    async def _tool_schedule_task(self, name, cron, prompt, **kw):
        """Gateway tool: schedule a cron task."""
        await self.add_cron(name, cron, prompt, persist=True)
        return f"Scheduled cron task '{name}' with expression '{cron}'."

    async def _tool_list_tasks(self, **kw):
        """Gateway tool: list all tasks."""
        lines = []
        for t in self.tasks:
            kind = "recurring" if t["interval"] > 0 else "one-shot"
            lines.append(f"[{kind}] {t['name']} — every {t['interval']}s")
        for t in self.cron_tasks:
            action_desc = t["action"][:80] if isinstance(t["action"], str) else "(callable)"
            lines.append(f"[cron] {t['name']} — {t['cron_expr']} — {action_desc}")
        if not lines:
            return "No scheduled tasks."
        return "\n".join(lines)

    async def _tool_remove_task(self, name, **kw):
        """Gateway tool: remove a task by name."""
        # Try interval tasks
        for t in list(self.tasks):
            if t["name"] == name:
                self.tasks.remove(t)
                return f"Removed interval task '{name}'."
        # Try cron tasks
        before = len(self.cron_tasks)
        self.cron_tasks = [t for t in self.cron_tasks if t["name"] != name]
        if len(self.cron_tasks) < before:
            self._save_cron_tasks()
            return f"Removed cron task '{name}'."
        return f"No task found with name '{name}'."
