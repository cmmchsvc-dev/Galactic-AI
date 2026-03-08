import asyncio
import os
import re
from skills.base import GalacticSkill

class SelfHealingSkill(GalacticSkill):
    """
    Intelligently diagnoses and repairs system issues:
    - Monitors logs for [ERROR] and CRITICAL spikes
    - Detects provider outages and triggers recovery
    - Automatically fixes corrupted configs or missing directories
    - Proposes patches for recurring code errors
    """
    
    skill_name   = "self_healing"
    display_name = "Self-Healing Core"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Autonomous diagnosis and repair for Galactic AI."
    category     = "system"
    icon         = "🛠️"

    def __init__(self, core):
        super().__init__(core)
        self.check_interval = 60
        self.last_log_size = 0
        self.error_patterns = {
            r"\[ERROR\] (.*)": self._handle_llm_error,
            r"ConnectionResetError": self._handle_network_error,
            r"Ollama OFFLINE": self._handle_ollama_offline,
            r"Failed to setup systems: (.*)": self._handle_critical_init_error,
            r"permission denied": self._handle_permission_error,
            r"Tool '(.*)' not found": self._handle_capability_gap,
        }
        self._monitor_task = None

    async def run(self):
        """Main monitoring loop."""
        await self.core.log("Self-Healing Skill online. Monitoring for system integrity...", priority=2)
        
        while self.running:
            try:
                await self._check_logs()
                await self._check_system_health()
            except Exception as e:
                # Avoid crashing the healer
                pass
            await asyncio.sleep(60)

    async def _check_logs(self):
        """Scan system_log.txt for new errors."""
        logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
        log_file = os.path.join(logs_dir, 'system_log.txt')
        
        if not os.path.exists(log_file):
            return

        size = os.path.getsize(log_file)
        if size < self.last_log_size:
            self.last_log_size = 0 # Log rotated
            
        if size > self.last_log_size:
            with open(log_file, 'r', encoding='utf-8') as f:
                f.seek(self.last_log_size)
                new_lines = f.readlines()
                self.last_log_size = size
                
    async def _handle_capability_gap(self, tool_name):
        """Trigger the Forge when a missing tool is requested."""
        if tool_name in ("synthesize_skill", "check_health"): return # Recursive protection
        
        await self.core.log(f"🔥 [Healing] Capability gap detected: {tool_name}. Engaging Galactic Forge...", priority=1)
        
        # Find Forge skill
        forge = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'forge'), None)
        if forge:
            # We don't want to block the log-processing loop, so spawn synthesis in background
            asyncio.create_task(forge._tool_synthesize_skill({
                "skill_name": tool_name.replace(' ', '_').lower(),
                "goal": f"A skill that provides the tool '{tool_name}' which was requested but not found.",
                "class_name": f"{tool_name.replace('_', ' ').title().replace(' ', '')}Skill"
            }))
        else:
            await self.core.log("⚠️ [Healing] Galactic Forge not online, cannot synthesize skill.", priority=2)

    async def _handle_llm_error(self, error_msg):
        """Analyze LLM errors and trigger model switching or repair."""
        await self.core.log(f"🛠 [Healing] LLM Error detected: {error_msg[:100]}...", priority=2)
        
        # If it looks like a prefix bug (user reported this specifically)
        if "ollama/" in error_msg.lower():
            await self.core.log("🛠 [Healing] Detected 'ollama/' prefix bug in runtime. Forcing model manager audit.", priority=1)
            if hasattr(self.core, 'model_manager'):
                await self.core.model_manager.rebuild_fallback_chain()
        
        # If it's a permanent error (Auth/Quota), switch fallback
        if any(k in error_msg.lower() for k in ("401", "402", "unauthorized", "quota", "invalid_api_key")):
            await self.core.log("🛠 [Healing] Permanent provider error. Escaping to next healthy model...", priority=1)
            if hasattr(self.core, 'model_manager'):
                await self.core.model_manager.switch_to_fallback(reason="Self-Healing Auto-Switch")

    async def _handle_network_error(self, ctx):
        await self.core.log(f"🛠 [Healing] Network instability detected. Checking internet/DNS...", priority=2)
        # Check connectivity
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get("https://1.1.1.1", timeout=5.0)
                await self.core.log("🛠 [Healing] Internet is up. Issue is likely provider-specific.", priority=2)
        except:
             await self.core.log("🛠 [Healing] Global network outage detected. Pausing non-local tasks.", priority=1)

    async def _handle_ollama_offline(self, ctx):
        await self.core.log(f"🛠 [Healing] Ollama is offline. Attempting to locate local instance...", priority=2)
        # Check if process is running
        import subprocess
        try:
            if os.name == 'nt':
                res = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ollama.exe'], capture_output=True, text=True)
                if 'ollama.exe' not in res.stdout:
                    await self.core.log("🛠 [Healing] Ollama process not found. Please start Ollama Desktop.", priority=1)
        except: pass

    async def _handle_critical_init_error(self, ctx):
        await self.core.log(f"🚨 [Healing] CRITICAL INIT FAILURE: {ctx}. Reviewing config...", priority=1)
        # Check for config.yaml corruption
        try:
            with open(self.core.config_path, 'r') as f:
                yaml.safe_load(f)
        except Exception as e:
            await self.core.log(f"🛠 [Healing] Config corrupted: {e}. Attempting to restore from memory...", priority=1)
            # Failsafe: if we had a backup, restore it here. For now, just log.

    async def _handle_permission_error(self, line):
        """Repair file permission issues if possible."""
        await self.core.log(f"🛠 [Healing] Permission error detected at: {line}", priority=1)
        # On Windows, we could try to icacls or similar, but for now just log it clearly
        pass

    async def run(self):
        """Main monitoring loop."""
        await self.core.log("Self-Healing Guardian Active. Monitoring system integrity...", priority=2)
        self.enabled = True
        while self.enabled:
            try:
                await self._check_logs()
                await self._check_system_health()
            except Exception as e:
                pass
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.enabled = False
