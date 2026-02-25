from skills.base import GalacticSkill
import asyncio
import os
import re
import tempfile

# Try to import the new SDK
try:
    from google import genai
    from google.genai import types
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

class GeminiCoder(GalacticSkill):
    """
    A dedicated coding specialist skill powered by Google's Gemini models.
    Uses the new google-genai SDK.
    """
    skill_name  = "gemini_coder"
    version     = "1.1.0"
    author      = "Chesley"
    description = "Senior Coding Engine powered by Google Gemini (google-genai SDK) with self-healing execution."
    category    = "data"
    icon        = "\U0001f916"

    def get_tools(self):
        return {
            'gemini_code': {
                'description': 'Use Google Gemini to generate code, scripts, or debug complex logic. Use this when you need a "Senior Dev" opinion.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'prompt': {
                            'type': 'string', 
                            'description': 'Detailed description of the code or solution needed.'
                        },
                        'model': {
                            'type': 'string',
                            'description': 'Model to use (default: gemini-3-pro-preview). Options: gemini-3-flash-preview, gemini-3-pro-preview, gemini-2.5-pro',
                            'default': 'gemini-3-pro-preview'
                        }
                    },
                    'required': ['prompt']
                },
                'fn': self.gemini_code
            },
            'test_driven_coder': {
                'description': 'Writes a Python script, executes it, and if it fails, autonomously loops with the LLM to fix the errors until it runs successfully.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'task': {
                            'type': 'string', 
                            'description': 'The programming task to execute and verify.'
                        },
                        'max_retries': {
                            'type': 'integer',
                            'description': 'Maximum number of fix attempts (default 3).'
                        }
                    },
                    'required': ['task']
                },
                'fn': self.test_driven_coder
            }
        }

    async def gemini_code(self, args):
        if not HAS_SDK:
            return "[Error] google-genai library not found. Run: pip install google-genai"

        prompt = args.get('prompt', '')
        model_name = args.get('model', 'gemini-3-pro-preview')

        api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey') or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "[Error] Google API key not found."

        def _generate():
            client = genai.Client(api_key=api_key)
            sys_instruct = "You are a specialized Python coding engine. Output clean, runnable code. Minimize explanation."
            response = client.models.generate_content(
                model=model_name,
                contents=f"System: {sys_instruct}\n\nTask: {prompt}"
            )
            return response.text

        try:
            result = await asyncio.to_thread(_generate)
            return f"### Gemini {model_name} Output:\n{result}"
        except Exception as e:
            return f"[Gemini Error]: {str(e)}"

    async def test_driven_coder(self, args):
        if not HAS_SDK:
            return "[Error] google-genai library not found."
            
        task = args.get('task', '')
        max_retries = args.get('max_retries', 3)
        model_name = 'gemini-3-pro-preview'
        
        api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey') or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "[Error] Google API key not found."
            
        client = genai.Client(api_key=api_key)
        
        def _extract_code(text):
            match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
            return match.group(1).strip() if match else text.strip()

        async def _run_code(code_str):
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
            tmp.write(code_str)
            tmp.close()
            try:
                proc = await asyncio.create_subprocess_exec(
                    'python', tmp.name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                out = stdout.decode('utf-8', errors='ignore').strip()
                err = stderr.decode('utf-8', errors='ignore').strip()
                return proc.returncode, out, err
            finally:
                try:
                    os.unlink(tmp.name)
                except:
                    pass

        await self.core.log(f"[TDD] Starting task: {task[:50]}...")
        
        # Initial Generation
        prompt = f"Write a Python script for this task: {task}. Output ONLY the raw python code in a markdown block."
        
        def _call_gemini(p):
            return client.models.generate_content(model=model_name, contents=p).text
            
        try:
            response_text = await asyncio.to_thread(_call_gemini, prompt)
            current_code = _extract_code(response_text)
        except Exception as e:
            return f"[TDD Error] Failed initial generation: {e}"

        # Execution Loop
        for attempt in range(max_retries + 1):
            await self.core.log(f"[TDD] Running code (Attempt {attempt+1}/{max_retries+1})...")
            
            try:
                code, out, err = await _run_code(current_code)
            except asyncio.TimeoutError:
                err = "Execution timed out after 30 seconds."
                code = 1
                out = ""

            if code == 0 and not err:
                await self.core.log("[TDD] Success!")
                return f"✅ **Test-Driven Execution Successful!**\n\n**Output:**\n```\n{out}\n```\n\n**Final Code:**\n```python\n{current_code}\n```"
                
            if attempt == max_retries:
                return f"❌ **TDD Failed after {max_retries} retries.**\n\n**Last Error:**\n```\n{err}\n```\n\n**Last Code Attempt:**\n```python\n{current_code}\n```"

            # Healing phase
            await self.core.log(f"[TDD] Script failed with error. Requesting fix from Gemini...", priority=1)
            fix_prompt = (
                f"I ran your Python script but it threw an error.\n\n"
                f"THE CODE:\n```python\n{current_code}\n```\n\n"
                f"THE ERROR:\n```\n{err}\n```\n\n"
                f"Fix the code to resolve this error. Output ONLY the fixed raw python code in a markdown block."
            )
            
            try:
                response_text = await asyncio.to_thread(_call_gemini, fix_prompt)
                current_code = _extract_code(response_text)
            except Exception as e:
                return f"[TDD Error] Failed to generate fix: {e}"

        return "Unknown state."
