import os
import platform
"""Shell command execution skill for Galactic AI."""
import asyncio
from skills.base import GalacticSkill


class ShellSkill(GalacticSkill):
    """The 'Hands' of Galactic AI: Executes local shell commands."""

    skill_name  = "shell_executor"
    version     = "1.1.2"
    author      = "Galactic AI"
    description = "Execute local shell commands (PowerShell)."
    category    = "system"
    icon        = "\U0001f4bb"

    def get_tools(self):
        return {
            "exec_shell": {
                "description": "Execute a shell command (PowerShell on Windows, Bash on Linux). Supports working directory and custom timeout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string",  "description": "Command to execute."},
                        "cwd":     {"type": "string",  "description": "Optional working directory."},
                        "timeout": {"type": "integer", "description": "Optional timeout in seconds (default: 120)."}
                    },
                    "required": ["command"]
                },
                "fn": self._tool_exec_shell
            }
        }

    async def _tool_exec_shell(self, args):
        """Tool handler for exec_shell with enhanced robustness."""
        command = args.get('command')
        if not command:
            return "[ERROR] No command provided."
        
        cwd = args.get('cwd') or os.getcwd()
        timeout = int(args.get('timeout', 120))
        
        return await self.execute(command, cwd=cwd, timeout=timeout)

    # ── Enhanced execute() ───────────────────────────────────────────────────
    async def execute(self, command, cwd=None, timeout=120):
        """Execute a shell command and return the combined output and exit code."""
        try:
            cwd = cwd or os.getcwd()
            await self.core.log(f"🛠️ Executing: {command[:100]}", priority=3)

            # Use powershell.exe on Windows for better compatibility
            if os.name == 'nt':
                executable = "powershell.exe"
                shell_args = ["-NoProfile", "-Command", command]
            else:
                executable = "/bin/bash"
                shell_args = ["-c", command]

            process = await asyncio.create_subprocess_exec(
                executable,
                *shell_args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                exit_code = process.returncode
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                await self.core.log(f"⏱ Tool timeout: {command[:50]}... killed after {timeout}s", priority=1)
                return f"[Timeout] Command exceeded {timeout}s and was killed.\nCommand: {command}"

            # Combine output for a complete picture
            out = stdout.decode('utf-8', errors='replace').strip()
            err = stderr.decode('utf-8', errors='replace').strip()

            # Truncate to prevent context window explosion and massive TTFT hangs
            if len(out) > 8000: out = out[:4000] + "\n...[STDOUT TRUNCATED]...\n" + out[-4000:]
            if len(err) > 8000: err = err[:4000] + "\n...[STDERR TRUNCATED]...\n" + err[-4000:]

            result = []
            if out:
                result.append(out)
            if err:
                result.append(f"--- STDERR ---\n{err}")
            
            if exit_code != 0:
                result.append(f"--- EXIT CODE: {exit_code} ---")
            
            final_output = "\n".join(result)
            if not final_output:
                return f"[OK] Command completed with no output (Exit code: {exit_code})"
            
            await self.core.log(f"Shell Success!", priority=2)
            return final_output

        except Exception as e:
            await self.core.log(f"SHELL EXCEPTION: {str(e)}", priority=1)
            return f"[ERROR] Shell execution failed: {str(e)}"

    async def run(self):
        await self.core.log("Shell Executor (Hands) Active.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
