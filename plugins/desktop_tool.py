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

            await loop.run_in_executor(None, img.save, path)

            # Also return base64 for direct vision analysis
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            return {
                'status': 'success',
                'path': path,
                'b64': b64,
                'width': img.width,
                'height': img.height,
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
            await loop.run_in_executor(None, lambda: (
                pyautogui.moveTo(from_x, from_y),
                pyautogui.drag(to_x - from_x, to_y - from_y, duration=duration)
            ))
            return {'status': 'success', 'from': (from_x, from_y), 'to': (to_x, to_y)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    # ── Keyboard ─────────────────────────────────────────────────────────────

    async def type_text(self, text, interval=0.05):
        """Type text at the current cursor/focus position."""
        self._check()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: pyautogui.typewrite(text, interval=interval)
            )
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
        """Find an image on the desktop screen (template matching)."""
        self._check()
        try:
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
            return {'status': 'not_found'}
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
