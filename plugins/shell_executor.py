import asyncio
import subprocess
import os
import traceback

class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True
    async def run(self):
        pass

class ShellPlugin(GalacticPlugin):
    """The 'Hands' of Galactic AI: Executes local shell commands."""
    def __init__(self, core):
        super().__init__(core)
        self.name = "ShellExecutor"

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
