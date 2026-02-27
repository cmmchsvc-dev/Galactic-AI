"""Shell command execution skill for Galactic AI."""
import asyncio
from skills.base import GalacticSkill


class ShellSkill(GalacticSkill):
    """The 'Hands' of Galactic AI: Executes local shell commands."""

    skill_name  = "shell_executor"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "Execute local shell commands (PowerShell)."
    category    = "system"
    icon        = "\U0001f4bb"

    def get_tools(self):
        return {
            "exec_shell": {
                "description": "Execute a shell command (PowerShell).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute."}
                    },
                    "required": ["command"]
                },
                "fn": self._tool_exec_shell
            }
        }

    async def _tool_exec_shell(self, args):
        """Tool handler wrapping execute() with gateway-compatible interface."""
        command = args.get('command', '')
        if not command:
            return "[ERROR] No command provided."
        return await self.execute(command)

    # ── Copied from plugins/shell_executor.py ────────────────────────────────
    async def execute(self, command, timeout=120):
        """Execute a shell command and return the output."""
        try:
            await self.core.log(f"DEBUG EXEC START: {command[:50]}...", priority=1)

            # Use absolute path to powershell and simple execution
            process = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await self.core.log(f"SHELL TIMEOUT: {command[:50]}... killed after {timeout}s", priority=1)
                return f"[Timeout] Command exceeded {timeout}s and was killed."

            output = stdout.decode('utf-8', errors='ignore').strip()
            error = stderr.decode('utf-8', errors='ignore').strip()

            if error:
                await self.core.log(f"SHELL ERROR: {error}", priority=1)
                return f"Error: {error}"

            await self.core.log(f"Shell Success!", priority=2)
            return output
        except Exception as e:
            await self.core.log(f"SHELL EXCEPTION: {str(e)}", priority=1)
            return f"Exception: {str(e)}"

    async def run(self):
        await self.core.log("Shell Executor (Hands) Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
