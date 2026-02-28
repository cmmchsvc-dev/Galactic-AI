import os
import asyncio
from skills.base import GalacticSkill

class GeminiCLIBridge(GalacticSkill):
    """
    Integrates the Node.js @google/gemini-cli-core tool into Galactic AI.
    Allows Galactic AI to delegate highly complex coding tasks natively to the Gemini CLI.
    """
    skill_name  = "gemini_cli_bridge"
    version     = "1.0.0"
    author      = "Chesley"
    description = "Delegates tasks to the native Node.js Gemini CLI with YOLO mode for deep codebase interventions."
    category    = "development"
    icon        = "🤖"

    def get_tools(self):
        return {
            'invoke_gemini_cli': {
                'description': 'Hand off an extremely complex coding or codebase investigation task to the native Gemini CLI. It has powerful abilities to explore, read, and write files autonomously. Only use this when you cannot solve the problem yourself.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'prompt': {
                            'type': 'string', 
                            'description': 'Detailed instructions for the Gemini CLI to execute.'
                        },
                        'working_directory': {
                            'type': 'string',
                            'description': 'The directory path where Gemini CLI should operate (defaults to the current workspace).'
                        }
                    },
                    'required': ['prompt']
                },
                'fn': self.invoke_gemini_cli
            }
        }

    async def invoke_gemini_cli(self, args):
        prompt = args.get('prompt', '')
        working_dir = args.get('working_directory', '.')
        if working_dir == '.':
            working_dir = self.core.config.get('system', {}).get('workspace_dir', os.getcwd())
            
        google_api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
        if not google_api_key:
            return "[Error] Google API key not found in config.yaml under providers.google.apiKey"

        await self.core.log(f"🚀 Invoking native Gemini CLI: {prompt[:50]}...", priority=2)
        
        env = os.environ.copy()
        env['GOOGLE_API_KEY'] = google_api_key
        
        # Build the command. 
        # --yolo automatically approves file edits.
        # --prompt runs it in non-interactive mode.
        cmd = [
            "gemini.cmd" if os.name == "nt" else "gemini", 
            "--yolo", 
            "--prompt", 
            prompt
        ]
        
        try:
            # We use an asyncio timeout because the CLI can sometimes hang or take a very long time
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0) # 5 min timeout
            except asyncio.TimeoutError:
                process.kill()
                return "[Error] Gemini CLI invocation timed out after 5 minutes."
            
            out_str = stdout.decode('utf-8', errors='replace').strip()
            err_str = stderr.decode('utf-8', errors='replace').strip()
            
            # Clean out the Punycode deprecation warnings which clutter the output
            clean_out = "\\n".join([line for line in out_str.split("\\n") if "punycode" not in line.lower() and "trace-deprecation" not in line.lower()])
            clean_err = "\\n".join([line for line in err_str.split("\\n") if "punycode" not in line.lower() and "trace-deprecation" not in line.lower()])
            
            result = f"### Gemini CLI Output (Exit Code: {process.returncode})\\n"
            if clean_out.strip():
                result += f"STDOUT:\\n{clean_out.strip()}\\n"
            if clean_err.strip():
                result += f"STDERR:\\n{clean_err.strip()}\\n"
                
            return result
            
        except Exception as e:
            return f"[Error] Failed to invoke Gemini CLI: {str(e)}"
