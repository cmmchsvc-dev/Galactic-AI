# F:\Galactic AI\galactic_orchestrator_v2.py
# GALACTIC SUB-AGENT ORCHESTRATOR (V2)
# - Loads orchestrator_config.json
# - Supports --daemon mode for Windows Scheduled Task
# - Auto-start agents configured with auto_start: true

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

try:
    from galactic_memory import GalacticMemory
except ImportError:
    print("ERROR: galactic_memory.py not found. Run from F:/Galactic AI where galactic_memory.py exists.")
    sys.exit(1)

BASE_DIR = Path(r"F:\Galactic AI")
CONFIG_FILE = BASE_DIR / "orchestrator_config.json"
AGENT_LOG_DIR = BASE_DIR / "logs" / "agents"

DEFAULT_AGENTS: Dict[str, dict] = {
    "newegg_watchdog": {
        "script": "newegg_5080_watch.py",
        "args": [],
        "auto_start": False,
        "restart_on_crash": True,
        "description": "Monitors Newegg (default)"
    },
    "f100_voice_logger": {
        "script": "f100_voice_logger.py",
        "args": [],
        "auto_start": False,
        "restart_on_crash": True,
        "description": "Watches for voice notes (placeholder)"
    },
    "github_monitor": {
        "script": "github_monitor.py",
        "args": [],
        "auto_start": False,
        "restart_on_crash": True,
        "description": "Checks GitHub (placeholder)"
    },
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class ProcHandles:
    stdout_f: Optional[object] = None
    stderr_f: Optional[object] = None


class AgentProcess:
    def __init__(self, name: str, config: dict, memory: GalacticMemory):
        self.name = name
        self.config = config
        self.memory = memory
        self.process: Optional[subprocess.Popen] = None
        self.start_time: Optional[datetime] = None
        self.status: str = "STOPPED"
        self.restart_count: int = 0
        self._handles = ProcHandles()

    def _open_logs(self) -> ProcHandles:
        AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_path = AGENT_LOG_DIR / f"{self.name}.out.log"
        err_path = AGENT_LOG_DIR / f"{self.name}.err.log"
        stdout_f = open(out_path, "a", encoding="utf-8", errors="replace")
        stderr_f = open(err_path, "a", encoding="utf-8", errors="replace")
        stdout_f.write(f"\n[{_now()}] --- START ---\n")
        stderr_f.write(f"\n[{_now()}] --- START ---\n")
        stdout_f.flush()
        stderr_f.flush()
        return ProcHandles(stdout_f=stdout_f, stderr_f=stderr_f)

    def _close_logs(self):
        for f in [self._handles.stdout_f, self._handles.stderr_f]:
            try:
                if f:
                    f.write(f"[{_now()}] --- STOP ---\n")
                    f.flush()
                    f.close()
            except Exception:
                pass
        self._handles = ProcHandles()

    def start(self) -> str:
        if self.process and self.process.poll() is None:
            return f"WARN: Agent {self.name} is already running."

        script_path = BASE_DIR / self.config.get("script", "")
        if not script_path.exists():
            self.status = "MISSING"
            return f"ERROR: Script not found: {script_path}"

        # record to memory
        try:
            self.memory.save_memory(f"Starting agent: {self.name}", category="orchestrator")
        except Exception:
            pass

        cmd = [sys.executable, str(script_path)] + list(self.config.get("args", []))

        try:
            self._close_logs()
            self._handles = self._open_logs()

            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

            self.process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=self._handles.stdout_f,
                stderr=self._handles.stderr_f,
                creationflags=creation_flags,
            )
            self.status = "RUNNING"
            self.start_time = datetime.now()
            try:
                self.memory.save_memory(f"Agent {self.name} started (PID: {self.process.pid})", category="orchestrator")
            except Exception:
                pass
            return f"OK: Agent {self.name} started (PID: {self.process.pid})"
        except Exception as e:
            self.status = "CRASHED"
            self._close_logs()
            return f"ERROR: Failed to start {self.name}: {e}"

    def stop(self) -> str:
        if not self.process or self.process.poll() is not None:
            self.status = "STOPPED"
            self._close_logs()
            return f"INFO: Agent {self.name} is not running."

        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

            self.status = "STOPPED"
            try:
                self.memory.save_memory(f"Agent {self.name} stopped", category="orchestrator")
            except Exception:
                pass
            self._close_logs()
            return f"OK: Agent {self.name} stopped."
        except Exception as e:
            return f"ERROR: Error stopping {self.name}: {e}"

    def check_health(self):
        if self.status in ("STOPPED", "MISSING"):
            return "OK"

        if self.process and self.process.poll() is not None:
            exit_code = self.process.poll()
            self.status = "CRASHED"
            try:
                self.memory.save_memory(
                    f"Agent {self.name} crashed (Exit Code: {exit_code})",
                    category="orchestrator",
                )
            except Exception:
                pass
            self._close_logs()

            if self.config.get("restart_on_crash", False):
                if self.restart_count < 3:
                    self.restart_count += 1
                    return "RESTART"
                return "DISABLED"

            return "CRASHED"

        return "OK"


class GalacticOrchestratorV2:
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.memory = GalacticMemory()
        self.config_path = config_path
        self.config = self._load_config_merged()
        self.agents: Dict[str, AgentProcess] = {
            name: AgentProcess(name, cfg, self.memory) for name, cfg in self.config.items()
        }
        try:
            self.memory.save_memory("Galactic Orchestrator V2 initialized", category="system")
        except Exception:
            pass

    def _load_config_merged(self) -> Dict[str, dict]:
        cfg = {}
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"ERROR: Failed reading config {self.config_path}: {e}")
                cfg = {}

        # merge defaults, but let file override
        merged = dict(DEFAULT_AGENTS)
        for k, v in cfg.items():
            merged[k] = {**merged.get(k, {}), **v}

        # if config file missing, write defaults to disk
        if not self.config_path.exists():
            try:
                self.config_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            except Exception:
                pass

        return merged

    def auto_start(self):
        for name, agent in self.agents.items():
            if agent.config.get("auto_start", False):
                print(agent.start())

    async def monitor_loop(self):
        while True:
            for name, agent in self.agents.items():
                status = agent.check_health()
                if status == "RESTART":
                    print(agent.start())
                elif status == "DISABLED":
                    print(f"WARN: Agent {name} disabled after repeated crashes")
            await asyncio.sleep(10)

    def list_agents(self) -> str:
        lines = []
        lines.append("\nAGENT STATUS")
        lines.append("-" * 50)
        for name, agent in self.agents.items():
            uptime = ""
            if agent.start_time and agent.status == "RUNNING":
                delta = datetime.now() - agent.start_time
                uptime = f" (Up: {str(delta).split('.')[0]})"
            lines.append(f"- {name}: {agent.status}{uptime}")
            desc = agent.config.get("description", "")
            if desc:
                lines.append(f"    {desc}")
        return "\n".join(lines)

    def handle_command(self, command: str) -> str:
        parts = command.strip().split()
        if not parts:
            return "ERROR: No command."
        action = parts[0].lower()

        if action == "list":
            return self.list_agents()
        if action == "start" and len(parts) >= 2:
            name = parts[1]
            if name not in self.agents:
                return f"ERROR: Unknown agent: {name}"
            return self.agents[name].start()
        if action == "stop" and len(parts) >= 2:
            name = parts[1]
            if name not in self.agents:
                return f"ERROR: Unknown agent: {name}"
            return self.agents[name].stop()
        if action == "restart" and len(parts) >= 2:
            name = parts[1]
            if name not in self.agents:
                return f"ERROR: Unknown agent: {name}"
            self.agents[name].stop()
            self.agents[name].restart_count = 0
            return self.agents[name].start()
        if action == "help":
            return (
                "Commands:\n"
                "  list\n"
                "  start <agent>\n"
                "  stop <agent>\n"
                "  restart <agent>\n"
                "  exit\n"
            )

        return f"ERROR: Unknown command: {action}"

    async def run_cli(self):
        print("Galactic Orchestrator V2 Online")
        print(self.list_agents())
        print("Type 'help' for commands. Type 'exit' to detach.")

        self.auto_start()
        monitor_task = asyncio.create_task(self.monitor_loop())

        while True:
            try:
                cmd = await asyncio.get_event_loop().run_in_executor(None, input, "Galactic> ")
                if cmd.lower().strip() == "exit":
                    break
                print(self.handle_command(cmd))
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nType 'exit' to detach.")

        monitor_task.cancel()
        self.memory.close()

    async def run_daemon(self):
        # no CLI; intended for Scheduled Task
        print("Galactic Orchestrator V2 (daemon) starting")
        self.auto_start()
        try:
            await self.monitor_loop()
        finally:
            self.memory.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run without CLI, for scheduled tasks")
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="Path to orchestrator_config.json")
    args = parser.parse_args()

    orch = GalacticOrchestratorV2(config_path=Path(args.config))

    if args.daemon:
        asyncio.run(orch.run_daemon())
    else:
        asyncio.run(orch.run_cli())


if __name__ == "__main__":
    if os.name == "nt":
        os.system("")
    main()
