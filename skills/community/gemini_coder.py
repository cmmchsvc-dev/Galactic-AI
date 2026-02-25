from skills.base import GalacticSkill
import asyncio
import os

# Try to import the new SDK
try:
    from google import genai
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

class GeminiCoder(GalacticSkill):
    """
    A dedicated coding specialist skill powered by Google's Gemini models.
    Uses the new google-genai SDK.
    """
    skill_name  = "gemini_coder"
    version     = "1.0.0"
    author      = "Chesley"
    description = "Senior Coding Engine powered by Google Gemini (google-genai SDK)."
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
            }
        }

    async def gemini_code(self, args):
        if not HAS_SDK:
            return "[Error] google-genai library not found. Run: pip install google-genai"

        prompt = args.get('prompt', '')
        model_name = args.get('model', 'gemini-3-pro-preview')

        # 1. Try to find the API key in Galactic AI config
        api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
        
        # 2. Fallback to Environment Variable
        if not api_key:
            api_key = os.environ.get("GOOGLE_API_KEY")

        if not api_key:
            return "[Error] Google API key not found in config.yaml (providers.google.apiKey) or GOOGLE_API_KEY env var."

        # Define the blocking call to run in a thread
        def _generate():
            client = genai.Client(api_key=api_key)
            # Add a specific system instruction for coding
            sys_instruct = "You are a specialized Python coding engine. Output clean, runnable code. Minimize explanation."
            
            response = client.models.generate_content(
                model=model_name,
                contents=f"{sys_instruct}\n\nTask: {prompt}"
            )
            return response.text

        try:
            # Run in a separate thread to keep Galactic AI snappy
            result = await asyncio.to_thread(_generate)
            return f"### Gemini {model_name} Output:\n{result}"
        except Exception as e:
            return f"[Gemini Error]: {str(e)}"
