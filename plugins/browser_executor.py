import asyncio
from playwright.async_api import async_playwright

class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True
    async def run(self):
        pass

class BrowserPlugin(GalacticPlugin):
    """The 'Eyes' of Galactic AI: Direct Playwright automation."""
    def __init__(self, core):
        super().__init__(core)
        self.name = "BrowserExecutor"
        self.browser = None
        self.playwright = None
        self.context = None
        self.started = False

    async def start(self):
        if self.started:
            return
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.started = True
            await self.core.log("Galactic Optics Online (Chromium Launched).", priority=2)
        except Exception as e:
            await self.core.log(f"Browser launch failed: {e}", priority=1)
            raise

    async def open_url(self, url):
        """Open a URL in a new page."""
        if not self.started:
            await self.start()
        
        try:
            pages = self.context.pages
            page = pages[0] if pages else await self.context.new_page()
            
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await self.core.log(f"Navigated to: {url}", priority=2)
            return page
        except Exception as e:
            await self.core.log(f"Navigation error: {e}", priority=1)
            raise

    async def search_and_click(self, text):
        """High-level automation: Search on YouTube."""
        if not self.started:
            return "Browser not started. Open a URL first."
        
        try:
            pages = self.context.pages
            if not pages:
                return "No page open."
            page = pages[0]
            
            if "youtube.com" in page.url:
                search_input = await page.wait_for_selector('input[name="search_query"]', timeout=5000)
                await search_input.fill(text)
                await page.keyboard.press('Enter')
                await self.core.log(f"YouTube Search: {text}", priority=2)
                return f"Searched YouTube for {text}"
            else:
                return f"Not on YouTube. Current URL: {page.url}"
        except Exception as e:
            await self.core.log(f"Search error: {e}", priority=1)
            return f"Search failed: {e}"

    async def take_screenshot(self, path="screenshot.png"):
        """Capture the current state of the optics."""
        if not self.started:
            return "Browser not started."
        
        try:
            if not self.context or not self.context.pages:
                return "No page open."
            
            page = self.context.pages[0]
            await page.screenshot(path=path, full_page=True)
            await self.core.log(f"Optics Snapshot captured: {path}", priority=2)
            return path
        except Exception as e:
            await self.core.log(f"Screenshot error: {e}", priority=1)
            return f"Screenshot failed: {e}"

    async def close(self):
        if self.browser:
            await self.browser.close()
            await self.playwright.stop()

    async def run(self):
        await self.core.log("Browser Executor (Optics) Ready.", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
