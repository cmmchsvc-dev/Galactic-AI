"""
Galactic AI -- Computer Use Skill
Vision-based GUI automation using Gemini.
"""

import asyncio
import os
import tempfile
import json
from skills.base import GalacticSkill

try:
    import pyautogui
    # Failsafe and pause for safety
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.5
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    from google import genai
    from google.genai import types
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

class ComputerUseSkill(GalacticSkill):
    """
    Allows the AI to look at the screen and find coordinates for elements based on natural language descriptions.
    """
    skill_name  = "computer_use"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Vision-based GUI automation: find and click elements on screen using Gemini."
    category    = "system"
    icon        = "\U0001f441"

    def get_tools(self):
        if not PYAUTOGUI_AVAILABLE or not HAS_SDK:
            return {}
            
        return {
            'computer_vision_click': {
                'description': 'Look at the screen, find a specific UI element based on a description, and interact with it. Move the mouse to a specific visual element.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'target_description': {
                            'type': 'string', 
                            'description': 'A detailed description of what to interact with (e.g. "The blue Submit button in the bottom right", "The file named report.pdf").'
                        },
                        'action': {
                            'type': 'string',
                            'description': 'What to do: click, double_click, right_click, or hover',
                            'default': 'click'
                        }
                    },
                    'required': ['target_description']
                },
                'fn': self.computer_vision_click
            }
        }

    async def computer_vision_click(self, args):
        target = args.get('target_description', '')
        action = args.get('action', 'click')
        
        api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
        if not api_key:
            api_key = os.environ.get("GOOGLE_API_KEY")
            
        if not api_key:
            return "[Error] Google API key required in config (providers.google.apiKey) for Computer Use vision model."

        def _execute():
            # Take screenshot
            screenshot = pyautogui.screenshot()
            
            # Save to temporary file
            temp_path = os.path.join(tempfile.gettempdir(), "vision_capture.jpg")
            screenshot.save(temp_path, format="JPEG", quality=80)
            
            client = genai.Client(api_key=api_key)
            
            sys_instruct = (
                "You are an expert GUI automation assistant. Your job is to locate a specific UI element on the provided screen capture. "
                "The screen dimensions are width=" + str(screenshot.width) + ", height=" + str(screenshot.height) + ". "
                "Return ONLY a raw JSON object containing the center x and y coordinates of the requested element. "
                "Format: {"x": 500, "y": 300}. If you cannot find it, return {"error": "not found"}. Do not use markdown."
            )
            
            try:
                with open(temp_path, "rb") as f:
                    img_bytes = f.read()
                    
                image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                
                response = client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=[
                        types.Content(parts=[
                            types.Part.from_text(text=f"System: {sys_instruct}

Task: Find this element: {target}"),
                            image_part
                        ])
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.0
                    )
                )
                
                # Cleanup temp file
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
                # Parse response
                text = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text)
                
                if "error" in data:
                    return f"[Computer Use] Element not found on screen: {target}"
                    
                x = int(data['x'])
                y = int(data['y'])
                
                if action == 'click':
                    pyautogui.click(x, y)
                    return f"[Computer Use] Clicked '{target}' at ({x}, {y})"
                elif action == 'double_click':
                    pyautogui.doubleClick(x, y)
                    return f"[Computer Use] Double-clicked '{target}' at ({x}, {y})"
                elif action == 'right_click':
                    pyautogui.rightClick(x, y)
                    return f"[Computer Use] Right-clicked '{target}' at ({x}, {y})"
                else:
                    pyautogui.moveTo(x, y)
                    return f"[Computer Use] Hovered over '{target}' at ({x}, {y})"
                    
            except Exception as e:
                try:
                    os.remove(temp_path)
                except:
                    pass
                return f"[Computer Use Error] Failed to parse vision response. {str(e)}"

        try:
            return await asyncio.to_thread(_execute)
        except Exception as e:
            return f"[Computer Use Error]: {str(e)}"
