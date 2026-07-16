from skills.base import GalacticSkill
import asyncio
import base64
import os
from io import BytesIO

class ScreenAwarenessSkill(GalacticSkill):
    skill_name = "screen_awareness"
    display_name = "Screen Awareness"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "Grants the AI the ability to see what is currently on the user's screen."
    category = "vision"
    icon = "👁️"

    def __init__(self, core):
        super().__init__(core)

    def get_tools(self):
        return {
            "take_screenshot": {
                "description": "Takes a screenshot of the user's primary monitor and returns the base64 encoded image.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "fn": self._tool_take_screenshot
            }
        }

    async def _tool_take_screenshot(self, args):
        try:
            import pyautogui
            from PIL import Image
            
            # Take screenshot
            screenshot = pyautogui.screenshot()
            
            # Resize image if it's too large to save tokens and processing time
            # Assuming max width 1920 to keep it manageable
            if screenshot.width > 1920:
                ratio = 1920.0 / screenshot.width
                new_size = (1920, int(screenshot.height * ratio))
                screenshot = screenshot.resize(new_size, Image.Resampling.LANCZOS)
                
            # Convert to RGB if necessary
            if screenshot.mode != 'RGB':
                screenshot = screenshot.convert('RGB')
                
            # Save to BytesIO
            buffered = BytesIO()
            screenshot.save(buffered, format="JPEG", quality=85)
            
            # Convert to base64
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            # Save a debug copy to the logs directory
            logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
            os.makedirs(logs_dir, exist_ok=True)
            screenshot.save(os.path.join(logs_dir, 'latest_screenshot.jpg'))
            
            return img_str
            
        except Exception as e:
            return f"[ERROR] Failed to take screenshot: {e}"
