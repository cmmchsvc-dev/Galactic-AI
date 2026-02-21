"""
Galactic AI — Desktop Automation Tool
OS-level mouse, keyboard, and screenshot control via pyautogui.
Complements browser automation (Playwright) with full desktop access.

Safety: pyautogui.FAILSAFE = True — move mouse to top-left corner to abort.
"""
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


class DesktopTool:
    """OS-level desktop control: screenshots, mouse, keyboard."""

    def __init__(self, core):
        self.core = core
        self.name = "DesktopTool"
        self.enabled = True

    async def run(self):
        """No background loop needed — tools are called on demand."""
        pass

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
                logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
                os.makedirs(logs_dir, exist_ok=True)
                path = os.path.join(logs_dir, f"desktop_{int(time.time())}.png")

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
        """Press a keyboard shortcut (e.g. 'ctrl', 'c' → Ctrl+C)."""
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
