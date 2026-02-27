"""Desktop automation skill for Galactic AI."""
import asyncio
import base64
import io
import os
import time

try:
    import pyautogui
    pyautogui.FAILSAFE = True      # emergency abort: mouse to (0,0)
    pyautogui.PAUSE = 0.1          # small delay between actions
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

# Max width for vision-analysis resize (keeps base64 payload manageable)
VISION_MAX_WIDTH = 1280

from skills.base import GalacticSkill


class DesktopSkill(GalacticSkill):
    """OS-level desktop control: screenshots, mouse, keyboard."""

    skill_name  = "desktop_tool"
    version     = "1.1.1"
    author      = "Galactic AI"
    description = "OS-level mouse, keyboard, and screenshot control via pyautogui."
    category    = "desktop"
    icon        = "\U0001f5a5\ufe0f"

    def get_tools(self):
        return {
            "desktop_screenshot": {
                "description": "Capture the entire desktop screen (not just browser). Automatically analyzes the screenshot with vision so you can 'see' and describe what is on screen. Use this to observe the desktop before clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "Optional region as 'x,y,width,height' (e.g. '0,0,1920,1080'). Omit for full screen."},
                        "save_path": {"type": "string", "description": "Optional file path to save PNG."}
                    }
                },
                "fn": self._tool_desktop_screenshot
            },
            "desktop_click": {
                "description": "Click the mouse at desktop pixel coordinates (x, y). Use after desktop_screenshot to interact with any UI element on screen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X pixel coordinate from left edge"},
                        "y": {"type": "number", "description": "Y pixel coordinate from top edge"},
                        "button": {"type": "string", "description": "Mouse button: left, right, or middle (default: left)"},
                        "clicks": {"type": "integer", "description": "Number of clicks — 1=single, 2=double (default: 1)"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self._tool_desktop_click
            },
            "desktop_type": {
                "description": "Type text at the current cursor/focus position on the desktop. Click a text field first with desktop_click.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type"},
                        "interval": {"type": "number", "description": "Seconds between keystrokes (default: 0.05)"}
                    },
                    "required": ["text"]
                },
                "fn": self._tool_desktop_type
            },
            "desktop_move": {
                "description": "Move the mouse cursor to desktop coordinates without clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "duration": {"type": "number", "description": "Move duration in seconds (default: 0.2)"}
                    },
                    "required": ["x", "y"]
                },
                "fn": self._tool_desktop_move
            },
            "desktop_scroll": {
                "description": "Scroll the mouse wheel. Positive = up, negative = down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "clicks": {"type": "integer", "description": "Scroll amount (positive=up, negative=down)"},
                        "x": {"type": "number", "description": "Optional X to scroll at"},
                        "y": {"type": "number", "description": "Optional Y to scroll at"}
                    },
                    "required": ["clicks"]
                },
                "fn": self._tool_desktop_scroll
            },
            "desktop_hotkey": {
                "description": "Press a keyboard shortcut (e.g. 'ctrl,c' for Ctrl+C, 'alt,tab' for Alt+Tab, 'win,r' for Run dialog).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {"type": "string", "description": "Comma-separated keys, e.g. 'ctrl,c' or 'alt,tab' or 'win,d'"}
                    },
                    "required": ["keys"]
                },
                "fn": self._tool_desktop_hotkey
            },
            "desktop_drag": {
                "description": "Click and drag from one desktop coordinate to another.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_x": {"type": "number", "description": "Start X"},
                        "from_y": {"type": "number", "description": "Start Y"},
                        "to_x": {"type": "number", "description": "End X"},
                        "to_y": {"type": "number", "description": "End Y"},
                        "duration": {"type": "number", "description": "Drag duration in seconds (default: 0.5)"}
                    },
                    "required": ["from_x", "from_y", "to_x", "to_y"]
                },
                "fn": self._tool_desktop_drag
            },
            "desktop_locate": {
                "description": "Find an image template on the desktop screen (template matching). Returns the coordinates where found.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_path": {"type": "string", "description": "Path to PNG image to search for on screen"},
                        "confidence": {"type": "number", "description": "Match confidence 0.0-1.0 (default: 0.8)"}
                    },
                    "required": ["image_path"]
                },
                "fn": self._tool_desktop_locate
            },
        }

    # ── Tool handlers ─────────────────────────────────────────────────────────

    async def _tool_desktop_screenshot(self, args):
        """Capture full desktop screen and analyze with vision."""
        try:
            region_str = args.get('region')
            region = None
            if region_str:
                parts = [int(v.strip()) for v in region_str.split(',')]
                if len(parts) == 4:
                    region = tuple(parts)
            save_path = args.get('save_path')
            result = await self.screenshot(region=region, save_path=save_path)
            if result['status'] != 'success':
                return f"[ERROR] Desktop screenshot failed: {result.get('message')}"

            # Automatically analyze with vision so the LLM can "see" the screen
            try:
                vision_result = await self.core.gateway._analyze_image_b64(
                    result['b64'], 'image/png',
                    'Describe what is visible on this desktop screenshot in detail. '
                    'Identify all windows, applications, buttons, text, icons, taskbar items, '
                    'and any other UI elements. Note the approximate pixel coordinates of key '
                    'elements so they can be clicked with desktop_click.'
                )
            except Exception as ve:
                vision_result = f"[Vision analysis failed: {ve}] Screenshot saved at {result['path']} — use analyze_image tool with that path to retry."
            return (
                f"[DESKTOP] Screenshot: {result['path']} "
                f"(full {result['width']}x{result['height']} px, "
                f"vision at {result.get('vision_width', result['width'])}x{result.get('vision_height', result['height'])} px)\n\n"
                f"Vision Analysis:\n{vision_result}"
            )
        except Exception as e:
            return f"[ERROR] Desktop screenshot: {e}"

    async def _tool_desktop_click(self, args):
        """Click at desktop coordinates."""
        x = args.get('x')
        y = args.get('y')
        button = args.get('button', 'left')
        clicks = int(args.get('clicks', 1))
        result = await self.click(x, y, button=button, clicks=clicks)
        if result['status'] == 'success':
            return f"[DESKTOP] Clicked ({x}, {y}) with {button} button x{clicks}"
        return f"[ERROR] Desktop click: {result.get('message')}"

    async def _tool_desktop_type(self, args):
        """Type text at current cursor position."""
        text = args.get('text', '')
        interval = float(args.get('interval', 0.05))
        result = await self.type_text(text, interval=interval)
        if result['status'] == 'success':
            preview = text[:80] + ('...' if len(text) > 80 else '')
            return f"[DESKTOP] Typed: {preview}"
        return f"[ERROR] Desktop type: {result.get('message')}"

    async def _tool_desktop_move(self, args):
        """Move mouse to coordinates."""
        x = args.get('x')
        y = args.get('y')
        duration = float(args.get('duration', 0.2))
        result = await self.move(x, y, duration=duration)
        if result['status'] == 'success':
            return f"[DESKTOP] Moved mouse to ({x}, {y})"
        return f"[ERROR] Desktop move: {result.get('message')}"

    async def _tool_desktop_scroll(self, args):
        """Scroll mouse wheel."""
        clicks = int(args.get('clicks', 3))
        x = args.get('x')
        y = args.get('y')
        result = await self.scroll(clicks, x=x, y=y)
        if result['status'] == 'success':
            direction = "up" if clicks > 0 else "down"
            return f"[DESKTOP] Scrolled {direction} {abs(clicks)} clicks"
        return f"[ERROR] Desktop scroll: {result.get('message')}"

    async def _tool_desktop_hotkey(self, args):
        """Press a keyboard shortcut."""
        keys_str = args.get('keys', '')
        keys = [k.strip() for k in keys_str.split(',')]
        result = await self.hotkey(*keys)
        if result['status'] == 'success':
            return f"[DESKTOP] Pressed hotkey: {'+'.join(keys)}"
        return f"[ERROR] Desktop hotkey: {result.get('message')}"

    async def _tool_desktop_drag(self, args):
        """Drag from one coordinate to another."""
        from_x = args.get('from_x')
        from_y = args.get('from_y')
        to_x = args.get('to_x')
        to_y = args.get('to_y')
        duration = float(args.get('duration', 0.5))
        result = await self.drag(from_x, from_y, to_x, to_y, duration=duration)
        if result['status'] == 'success':
            return f"[DESKTOP] Dragged ({from_x},{from_y}) -> ({to_x},{to_y})"
        return f"[ERROR] Desktop drag: {result.get('message')}"

    async def _tool_desktop_locate(self, args):
        """Find an image on screen via template matching."""
        # Accept both 'image_path' and 'template' (common alias LLMs use)
        image_path = args.get('image_path') or args.get('template', '')
        confidence = float(args.get('confidence', 0.8))
        result = await self.locate_on_screen(image_path, confidence=confidence)
        if result['status'] == 'success':
            return (
                f"[DESKTOP] Found at ({result['x']},{result['y']}) "
                f"size {result['width']}x{result['height']}. "
                f"Center: ({result['center_x']},{result['center_y']})"
            )
        elif result['status'] == 'not_found':
            return f"[DESKTOP] Image not found on screen: {image_path}"
        return f"[ERROR] Desktop locate: {result.get('message')}"

    # ── Copied from plugins/desktop_tool.py ──────────────────────────────────

    def _check(self):
        if not PYAUTOGUI_AVAILABLE:
            raise RuntimeError(
                "pyautogui not installed. Run: pip install pyautogui"
            )

    # ── Screenshots ──────────────────────────────────────────────────────────

    async def screenshot(self, region=None, save_path=None):
        """
        Capture the full desktop (or a region).
        region: (x, y, width, height) tuple or None for full screen.
        Returns: {'status': 'success', 'path': str, 'b64': str, 'width': int, 'height': int}
        The base64 image is resized to max VISION_MAX_WIDTH px wide before encoding
        so vision API payloads stay manageable.
        """
        self._check()
        try:
            loop = asyncio.get_event_loop()
            if region:
                img = await loop.run_in_executor(
                    None, lambda: pyautogui.screenshot(region=region)
                )
            else:
                img = await loop.run_in_executor(None, pyautogui.screenshot)

            if save_path:
                path = save_path
            else:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                img_subdir = os.path.join(images_dir, 'desktop')
                os.makedirs(img_subdir, exist_ok=True)
                path = os.path.join(img_subdir, f"desktop_{int(time.time())}.png")

            # Save full-resolution copy to disk
            await loop.run_in_executor(None, img.save, path)

            # Resize for vision API (avoid huge base64 payloads)
            vision_img = img
            if img.width > VISION_MAX_WIDTH:
                ratio = VISION_MAX_WIDTH / img.width
                new_h = int(img.height * ratio)
                vision_img = await loop.run_in_executor(
                    None, lambda: img.resize((VISION_MAX_WIDTH, new_h))
                )

            buf = io.BytesIO()
            vision_img.save(buf, format='PNG', optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            return {
                'status': 'success',
                'path': path,
                'b64': b64,
                'width': img.width,
                'height': img.height,
                'vision_width': vision_img.width,
                'vision_height': vision_img.height,
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    # ── Mouse ────────────────────────────────────────────────────────────────

    async def click(self, x, y, button='left', clicks=1):
        """Click at desktop coordinates."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: pyautogui.click(x, y, button=button, clicks=clicks)
            )
            return {'status': 'success', 'x': x, 'y': y, 'button': button, 'clicks': clicks}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def move(self, x, y, duration=0.2):
        """Move mouse to desktop coordinates."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: pyautogui.moveTo(x, y, duration=duration)
            )
            return {'status': 'success', 'x': x, 'y': y}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def scroll(self, clicks, x=None, y=None):
        """Scroll the mouse wheel. Positive = up, negative = down."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            if x is not None and y is not None:
                await loop.run_in_executor(
                    None, lambda: pyautogui.scroll(clicks, x=x, y=y)
                )
            else:
                await loop.run_in_executor(
                    None, lambda: pyautogui.scroll(clicks)
                )
            return {'status': 'success', 'clicks': clicks}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def drag(self, from_x, from_y, to_x, to_y, duration=0.5):
        """Click and drag from one coordinate to another."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            def _drag():
                pyautogui.moveTo(from_x, from_y)
                pyautogui.drag(to_x - from_x, to_y - from_y, duration=duration)
            await loop.run_in_executor(None, _drag)
            return {'status': 'success', 'from': (from_x, from_y), 'to': (to_x, to_y)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    # ── Keyboard ─────────────────────────────────────────────────────────────

    async def type_text(self, text, interval=0.05):
        """
        Type text at the current cursor/focus position.
        Uses clipboard paste for non-ASCII/Unicode text (emojis, special chars).
        Falls back to pyautogui.typewrite for ASCII-only text.
        """
        self._check()
        try:
            loop = asyncio.get_event_loop()
            # Check if text is ASCII-safe
            is_ascii = all(ord(c) < 128 for c in text)

            if is_ascii:
                await loop.run_in_executor(
                    None, lambda: pyautogui.typewrite(text, interval=interval)
                )
            elif PYPERCLIP_AVAILABLE:
                # Use clipboard for Unicode support
                def _paste_text():
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                await loop.run_in_executor(None, _paste_text)
            else:
                # Fallback: type ASCII chars, skip non-ASCII
                ascii_text = text.encode('ascii', errors='ignore').decode('ascii')
                await loop.run_in_executor(
                    None, lambda: pyautogui.typewrite(ascii_text, interval=interval)
                )
                return {'status': 'partial', 'typed': ascii_text, 'note': 'Non-ASCII chars skipped (install pyperclip for full Unicode support)'}

            return {'status': 'success', 'typed': text[:80]}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def hotkey(self, *keys):
        """Press a keyboard shortcut (e.g. 'ctrl', 'c' -> Ctrl+C)."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: pyautogui.hotkey(*keys))
            return {'status': 'success', 'keys': list(keys)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def press(self, key):
        """Press a single key (enter, tab, escape, etc.)."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: pyautogui.press(key))
            return {'status': 'success', 'key': key}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    # ── Locate on screen ─────────────────────────────────────────────────────

    async def locate_on_screen(self, image_path, confidence=0.8):
        """
        Find an image on the desktop screen (template matching).
        Requires opencv-python: pip install opencv-python
        """
        self._check()
        try:
            # Check OpenCV availability
            try:
                import cv2  # noqa: F401
            except ImportError:
                return {
                    'status': 'error',
                    'message': 'OpenCV not installed. Run: pip install opencv-python'
                }

            if not os.path.exists(image_path):
                return {
                    'status': 'error',
                    'message': f'Template image not found: {image_path}'
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: pyautogui.locateOnScreen(image_path, confidence=confidence)
            )
            if result:
                return {
                    'status': 'success',
                    'x': result.left, 'y': result.top,
                    'width': result.width, 'height': result.height,
                    'center_x': result.left + result.width // 2,
                    'center_y': result.top + result.height // 2,
                }
            return {
                'status': 'not_found',
                'message': f'Template not found on screen (confidence={confidence}). Try lowering confidence or use desktop_screenshot + vision instead.'
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def get_screen_size(self):
        """Return current screen resolution."""
        self._check()
        w, h = pyautogui.size()
        return {'width': w, 'height': h}

    async def get_mouse_position(self):
        """Return current mouse (x, y)."""
        self._check()
        x, y = pyautogui.position()
        return {'x': x, 'y': y}

    async def run(self):
        pass  # No background loop needed
