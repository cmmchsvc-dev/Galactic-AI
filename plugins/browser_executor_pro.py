"""
GALACTIC BROWSER EXECUTOR PRO - Full Playwright Automation Suite
Capabilities: Form filling, clicking, scraping, multi-tab, JavaScript execution, file uploads
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Page state tracking (OpenClaw parity)
pageStates = {}

def ensurePageState(page):
    """Ensure page has state tracking for console/errors/requests/responses (OpenClaw+ parity)."""
    if page not in pageStates:
        state = {
            "console": [],
            "errors": [],
            "requests": [],
            "responses": {}   # url -> {status, headers, body, timestamp}
        }
        pageStates[page] = state

        # Console log capture — .type and .text are properties in Playwright Python, not methods
        page.on("console", lambda msg: state["console"].append({
            "type": msg.type if isinstance(msg.type, str) else str(msg.type),
            "text": msg.text if isinstance(msg.text, str) else str(msg.text),
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # JS error capture
        page.on("pageerror", lambda err: state["errors"].append({
            "message": str(err),
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # Request capture (metadata only)
        page.on("request", lambda req: state["requests"].append({
            "method": req.method,
            "url": req.url,
            "timestamp": str(asyncio.get_event_loop().time())
        }))

        # Response body capture (async — best-effort)
        async def _capture_response(resp):
            try:
                body_bytes = await resp.body()
                state["responses"][resp.url] = {
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": body_bytes.decode('utf-8', errors='replace')[:100_000],
                    "timestamp": str(asyncio.get_event_loop().time())
                }
            except Exception:
                pass  # binary / closed responses are silently skipped

        page.on("response", lambda resp: asyncio.create_task(_capture_response(resp)))

    return pageStates[page]

class GalacticPlugin:
    def __init__(self, core):
        self.core = core
        self.name = "BasePlugin"
        self.enabled = True
    async def run(self):
        pass

class BrowserExecutorPro(GalacticPlugin):
    """Full-power browser automation via Playwright."""
    
    def __init__(self, core):
        super().__init__(core)
        self.name = "BrowserExecutorPro"
        self.browser = None
        self.playwright = None
        self.context = None
        self.pages = {}  # Track multiple pages by ID
        self.active_page_id = None
        self.started = False
        self.default_timeout = 30000  # 30 seconds
        self.refs = {}  # Store ref mappings: {page_id: {ref: selector}}

    async def start(self):
        """Launch browser with stealth mode. Engine and headless mode are config-driven."""
        if self.started:
            return {"status": "already_running"}

        try:
            self.playwright = await async_playwright().start()

            # Read browser engine from config (chromium | firefox | webkit)
            engine_name = self.core.config.get('browser', {}).get('engine', 'chromium')
            browser_engine = getattr(self.playwright, engine_name, self.playwright.chromium)
            headless = self.core.config.get('browser', {}).get('headless', False)

            # Launch with realistic browser args (anti-detection)
            self.browser = await browser_engine.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--no-sandbox'
                ]
            )
            
            # Context with realistic viewport
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            # Create initial page
            page = await self.context.new_page()
            page_id = "page_1"
            self.pages[page_id] = page
            self.active_page_id = page_id
            
            # Enable state tracking (OpenClaw parity)
            ensurePageState(page)
            
            self.started = True
            await self.core.log("Galactic Browser PRO: Online (Anti-Detection Mode)", priority=2)
            return {"status": "started", "page_id": page_id}
            
        except Exception as e:
            await self.core.log(f"Browser launch failed: {e}", priority=1)
            return {"status": "error", "message": str(e)}

    def _get_page(self, page_id=None):
        """Get page by ID or return active page."""
        if page_id and page_id in self.pages:
            return self.pages[page_id]
        elif self.active_page_id and self.active_page_id in self.pages:
            return self.pages[self.active_page_id]
        else:
            return None

    async def navigate(self, url, page_id=None, wait_for="domcontentloaded"):
        """Navigate to URL with smart waiting."""
        if not self.started:
            await self.start()
        
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.goto(url, timeout=self.default_timeout, wait_until=wait_for)
            await self.core.log(f"Navigated: {url}", priority=2)
            return {"status": "success", "url": url, "page_id": page_id or self.active_page_id}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click(self, selector, page_id=None, wait=True):
        """Click element by CSS selector, XPath, or text."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            # Smart selector handling
            if wait:
                await page.wait_for_selector(selector, timeout=self.default_timeout)
            
            await page.click(selector)
            await self.core.log(f"Clicked: {selector}", priority=2)
            return {"status": "success", "selector": selector}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def type_text(self, selector, text, page_id=None, clear=True, press_enter=False):
        """Type text into input field."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.wait_for_selector(selector, timeout=self.default_timeout)
            
            if clear:
                await page.fill(selector, "")  # Clear first
            
            await page.fill(selector, text)
            
            if press_enter:
                await page.press(selector, "Enter")
            
            await self.core.log(f"Typed into {selector}: {text[:50]}...", priority=2)
            return {"status": "success", "selector": selector, "text_length": len(text)}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def fill_form(self, fields, page_id=None, submit_selector=None):
        """Fill multiple form fields at once.
        
        Args:
            fields: List of dicts with 'selector' and 'value' keys
            submit_selector: Optional submit button selector
        
        Example:
            fields = [
                {"selector": "#email", "value": "test@example.com"},
                {"selector": "#password", "value": "secret123"},
                {"selector": "#age", "value": "25"}
            ]
        """
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            filled = []
            for field in fields:
                selector = field.get('selector')
                value = field.get('value')
                field_type = field.get('type', 'text')  # text, checkbox, radio, select
                
                await page.wait_for_selector(selector, timeout=self.default_timeout)
                
                if field_type == 'checkbox':
                    if value:
                        await page.check(selector)
                    else:
                        await page.uncheck(selector)
                elif field_type == 'select':
                    await page.select_option(selector, value)
                else:
                    await page.fill(selector, str(value))
                
                filled.append(selector)
                await self.core.log(f"Filled: {selector}", priority=2)
            
            if submit_selector:
                await page.click(submit_selector)
                await self.core.log(f"Submitted form via: {submit_selector}", priority=2)
            
            return {"status": "success", "filled_count": len(filled), "submitted": bool(submit_selector)}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def extract_data(self, config, page_id=None):
        """Extract structured data from page.
        
        Args:
            config: Dict with extraction rules
            
        Example:
            config = {
                "title": {"selector": "h1", "attr": "text"},
                "price": {"selector": ".price", "attr": "text"},
                "image": {"selector": "img.product", "attr": "src"},
                "table": {"selector": "table.data", "attr": "table"}
            }
        """
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            extracted = {}
            
            for key, rule in config.items():
                selector = rule['selector']
                attr = rule.get('attr', 'text')
                multiple = rule.get('multiple', False)
                
                if multiple:
                    # Extract from multiple elements
                    elements = await page.query_selector_all(selector)
                    values = []
                    for el in elements:
                        if attr == 'text':
                            values.append(await el.inner_text())
                        elif attr == 'html':
                            values.append(await el.inner_html())
                        else:
                            values.append(await el.get_attribute(attr))
                    extracted[key] = values
                else:
                    # Single element
                    element = await page.query_selector(selector)
                    if element:
                        if attr == 'text':
                            extracted[key] = await element.inner_text()
                        elif attr == 'html':
                            extracted[key] = await element.inner_html()
                        elif attr == 'table':
                            # Extract table as 2D array
                            rows = await element.query_selector_all('tr')
                            table_data = []
                            for row in rows:
                                cells = await row.query_selector_all('td, th')
                                row_data = [await cell.inner_text() for cell in cells]
                                table_data.append(row_data)
                            extracted[key] = table_data
                        else:
                            extracted[key] = await element.get_attribute(attr)
            
            await self.core.log(f"Extracted {len(extracted)} data points", priority=2)
            return {"status": "success", "data": extracted}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def execute_js(self, script, page_id=None):
        """Execute JavaScript in page context."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            result = await page.evaluate(script)
            await self.core.log(f"Executed JS: {script[:100]}...", priority=2)
            return {"status": "success", "result": result}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def wait_for(self, selector=None, text=None, timeout=30000, page_id=None):
        """Wait for element or text to appear."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            if selector:
                await page.wait_for_selector(selector, timeout=timeout)
                await self.core.log(f"Waited for: {selector}", priority=2)
            elif text:
                await page.wait_for_function(
                    f'document.body.innerText.includes("{text}")',
                    timeout=timeout
                )
                await self.core.log(f"Waited for text: {text}", priority=2)
            
            return {"status": "success"}
            
        except PlaywrightTimeout:
            return {"status": "timeout", "message": f"Timeout waiting for {selector or text}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll(self, direction="down", amount=None, page_id=None):
        """Scroll page up/down."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            if direction == "down":
                if amount:
                    await page.evaluate(f"window.scrollBy(0, {amount})")
                else:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                if amount:
                    await page.evaluate(f"window.scrollBy(0, -{amount})")
                else:
                    await page.evaluate("window.scrollTo(0, 0)")
            
            await self.core.log(f"Scrolled {direction}", priority=2)
            return {"status": "success", "direction": direction}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot(self, path=None, full_page=True, page_id=None):
        """Capture screenshot."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            if not path:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                img_subdir = Path(images_dir) / 'browser'
                img_subdir.mkdir(parents=True, exist_ok=True)
                path = str(img_subdir / 'screenshot.png')

            await page.screenshot(path=path, full_page=full_page)
            await self.core.log(f"Screenshot: {path}", priority=2)
            return {"status": "success", "path": path}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def snapshot(self, format="ai", interactive=False, compact=False, depth=6, max_chars=50000, page_id=None):
        """Take accessibility snapshot of page for automation refs.
        
        Args:
            format: "ai" (numeric refs) or "aria" (accessibility tree)
            interactive: If True, return flat list of interactive elements only
            compact: If True, minimize output size
            depth: Max tree depth for aria snapshots
            max_chars: Maximum characters in output
            page_id: Target page ID
            
        Returns:
            Snapshot text with element refs for automation
        """
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            # Use Playwright's built-in accessibility snapshot
            # This mimics OpenClaw's approach
            if format == "aria" or interactive:
                # Get accessibility tree
                snapshot = await page.accessibility.snapshot(interesting_only=interactive)
                
                def flatten_tree(node, indent=0, ref_counter=[0]):
                    """Convert accessibility tree to text with refs."""
                    lines = []
                    if node:
                        ref = ref_counter[0]
                        ref_counter[0] += 1
                        
                        role = node.get('role', 'unknown')
                        name = node.get('name', '')
                        
                        if compact and not interactive:
                            # Skip generic containers in compact mode
                            if role in ['generic', 'group'] and not name:
                                for child in node.get('children', []):
                                    lines.extend(flatten_tree(child, indent, ref_counter))
                                return lines
                        
                        line = f"[ref=e{ref}] {role}"
                        if name:
                            line += f" \"{name}\""
                        
                        if interactive:
                            # For interactive mode, show actionable elements
                            if role in ['button', 'link', 'textbox', 'combobox', 'listbox', 'menuitem', 'checkbox', 'radio']:
                                lines.append(line)
                        else:
                            lines.append("  " * indent + line)
                        
                        for child in node.get('children', []):
                            if indent < depth:
                                lines.extend(flatten_tree(child, indent + 1, ref_counter))
                    
                    return lines
                
                if snapshot:
                    lines = flatten_tree(snapshot)
                    snapshot_text = "\n".join(lines[:1000])  # Limit output
                else:
                    snapshot_text = "No accessibility data available"
                    
            else:
                # AI format with numeric refs - store ref mappings for actions
                # Generate snapshot with refs that can be used for actions
                snapshot_data = await page.evaluate("""() => {
                    const elements = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="menuitem"], [role="checkbox"], [role="radio"], [tabindex]');
                    let output = [];
                    let mappings = [];
                    let ref = 0;
                    
                    elements.forEach(el => {
                        if (el.offsetParent !== null) {  // Only visible elements
                            ref++;
                            const tag = el.tagName.toLowerCase();
                            const id = el.id ? '#' + el.id : '';
                            const classes = el.className ? '.' + el.className.split(' ').filter(c => c).join('.') : '';
                            const text = el.innerText ? el.innerText.substring(0, 50).replace(/\\n/g, ' ') : '';
                            const role = el.getAttribute('role') || '';
                            const ariaLabel = el.getAttribute('aria-label') || '';
                            
                            let line = `[ref=${ref}] <${tag}${id}${classes}>`;
                            if (ariaLabel) line += ` aria-label="${ariaLabel}"`;
                            if (role) line += ` role="${role}"`;
                            if (text) line += ` "${text}"`;
                            
                            output.push(line);
                            
                            // Store mapping: ref -> CSS selector
                            const selector = tag + id + classes;
                            mappings.push({ref: ref, selector: selector});
                        }
                    });
                    
                    return {output: output.join('\\n'), mappings: mappings};
                }""")
                
                snapshot_text = snapshot_data['output']
                
                # Store ref mappings for this page
                actual_page_id = page_id or self.active_page_id
                if actual_page_id:
                    ref_map = {}
                    for mapping in snapshot_data['mappings']:
                        ref_map[mapping['ref']] = mapping['selector']
                    self.refs[actual_page_id] = ref_map
            
            # Truncate if needed
            if len(snapshot_text) > max_chars:
                snapshot_text = snapshot_text[:max_chars] + "\n... (truncated)"
            
            await self.core.log(f"Snapshot captured ({format} format)", priority=2)
            return {"status": "success", "snapshot": snapshot_text, "format": format}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def upload_file(self, selector, file_path, page_id=None):
        """Upload file to input element."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.wait_for_selector(selector, timeout=self.default_timeout)
            await page.set_input_files(selector, file_path)
            
            await self.core.log(f"Uploaded: {file_path} to {selector}", priority=2)
            return {"status": "success", "file": file_path}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click_by_ref(self, ref, page_id=None):
        """Click element using ref from snapshot (OpenClaw-style).
        
        Args:
            ref: Numeric ref from snapshot (e.g., 1 for [ref=1])
            page_id: Target page ID
            
        Returns:
            Action result
        """
        try:
            actual_page_id = page_id or self.active_page_id
            
            # Get ref mapping for this page
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            result = await self.click(selector, page_id=page_id)
            return result
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def type_by_ref(self, ref, text, page_id=None, clear=True, press_enter=False):
        """Type text using ref from snapshot (OpenClaw-style).
        
        Args:
            ref: Numeric ref from snapshot
            text: Text to type
            page_id: Target page ID
            clear: Clear field before typing
            press_enter: Press Enter after typing
            
        Returns:
            Action result
        """
        try:
            actual_page_id = page_id or self.active_page_id
            
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            result = await self.type_text(selector, text, page_id=page_id, clear=clear, press_enter=press_enter)
            return result
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def new_tab(self, url=None):
        """Create new tab/page."""
        try:
            page = await self.context.new_page()
            page_id = f"page_{len(self.pages) + 1}"
            self.pages[page_id] = page
            
            # Enable state tracking (OpenClaw parity)
            ensurePageState(page)
            
            if url:
                await page.goto(url, timeout=self.default_timeout)
            
            await self.core.log(f"New tab: {page_id}", priority=2)
            return {"status": "success", "page_id": page_id, "url": url}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def switch_tab(self, page_id):
        """Switch active tab."""
        if page_id in self.pages:
            self.active_page_id = page_id
            await self.core.log(f"Switched to: {page_id}", priority=2)
            return {"status": "success", "page_id": page_id}
        else:
            return {"status": "error", "message": f"Page {page_id} not found"}

    async def get_cookies(self, page_id=None):
        """Get all cookies."""
        try:
            cookies = await self.context.cookies()
            return {"status": "success", "cookies": cookies}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_cookies(self, cookies):
        """Set cookies."""
        try:
            await self.context.add_cookies(cookies)
            return {"status": "success", "count": len(cookies)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def press(self, key, page_id=None):
        """Press a keyboard key (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.keyboard.press(key)
            await self.core.log(f"Pressed key: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def hover(self, selector, page_id=None):
        """Hover over element (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.hover(selector)
            await self.core.log(f"Hovered: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def hover_by_ref(self, ref, page_id=None):
        """Hover using ref from snapshot (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            return await self.hover(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll_into_view(self, selector, page_id=None):
        """Scroll element into view (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.locator(selector).scroll_into_view_if_needed()
            await self.core.log(f"Scrolled into view: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def scroll_into_view_by_ref(self, ref, page_id=None):
        """Scroll into view using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            return await self.scroll_into_view(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def drag(self, from_selector, to_selector, page_id=None):
        """Drag and drop (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.drag_and_drop(from_selector, to_selector)
            await self.core.log(f"Dragged {from_selector} to {to_selector}", priority=2)
            return {"status": "success", "from": from_selector, "to": to_selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def drag_by_ref(self, from_ref, to_ref, page_id=None):
        """Drag and drop using refs (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs:
                return {"status": "error", "message": "No refs found. Take a snapshot first."}
            
            if from_ref not in self.refs[actual_page_id] or to_ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Refs not found. Take a snapshot first."}
            
            from_selector = self.refs[actual_page_id][from_ref]
            to_selector = self.refs[actual_page_id][to_ref]
            return await self.drag(from_selector, to_selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def select_option(self, selector, values, page_id=None):
        """Select dropdown option(s) (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            if isinstance(values, str):
                values = [values]
            
            await page.select_option(selector, values)
            await self.core.log(f"Selected {values} in {selector}", priority=2)
            return {"status": "success", "selector": selector, "values": values}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def select_option_by_ref(self, ref, values, page_id=None):
        """Select dropdown using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            return await self.select_option(selector, values, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def download(self, selector, filename, page_id=None):
        """Download file from link (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            async with page.expect_download() as download_info:
                await page.click(selector)
            download = await download_info.value
            
            images_dir = self.core.config.get('paths', {}).get('images', './images')
            dl_dir = Path(images_dir) / 'downloads'
            dl_dir.mkdir(parents=True, exist_ok=True)
            download_path = dl_dir / filename
            await download.save_as(download_path)
            await self.core.log(f"Downloaded: {download_path}", priority=2)
            return {"status": "success", "path": str(download_path)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def download_by_ref(self, ref, filename, page_id=None):
        """Download using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            return await self.download(selector, filename, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def dialog(self, action="accept", text=None, page_id=None):
        """Handle dialog (arming call - OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            def handle_dialog(dialog):
                if action == "accept":
                    asyncio.create_task(dialog.accept(text if text else ""))
                else:
                    asyncio.create_task(dialog.dismiss())
            
            page.once("dialog", handle_dialog)
            await self.core.log(f"Dialog armed: {action}", priority=2)
            return {"status": "success", "action": action}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def highlight(self, selector, page_id=None):
        """Highlight element for debugging (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.evaluate(f"""
                const el = document.querySelector('{selector}');
                if (el) {{
                    el.style.outline = '3px solid red';
                    el.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                }}
            """)
            await self.core.log(f"Highlighted: {selector}", priority=2)
            return {"status": "success", "selector": selector}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def highlight_by_ref(self, ref, page_id=None):
        """Highlight using ref (OpenClaw parity)."""
        try:
            actual_page_id = page_id or self.active_page_id
            if actual_page_id not in self.refs or ref not in self.refs[actual_page_id]:
                return {"status": "error", "message": f"Ref {ref} not found. Take a snapshot first."}
            
            selector = self.refs[actual_page_id][ref]
            return await self.highlight(selector, page_id=page_id)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def resize_viewport(self, width, height, page_id=None):
        """Resize viewport (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.set_viewport_size({"width": width, "height": height})
            await self.core.log(f"Resized viewport: {width}x{height}", priority=2)
            return {"status": "success", "width": width, "height": height}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_console_logs(self, level=None, page_id=None):
        """Get console logs (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            state = ensurePageState(page) if hasattr(self, 'ensurePageState') else pageStates.get(page, {"console": []})
            logs = state.get("console", [])
            
            if level:
                logs = [log for log in logs if log.get("type") == level]
            
            return {"status": "success", "logs": logs, "count": len(logs)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_page_errors(self, page_id=None):
        """Get page errors (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            state = pageStates.get(page, {"errors": []})
            errors = state.get("errors", [])
            
            return {"status": "success", "errors": errors, "count": len(errors)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_network_requests(self, filter_pattern=None, page_id=None):
        """Get network requests (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            state = pageStates.get(page, {"requests": []})
            requests = state.get("requests", [])
            
            if filter_pattern:
                requests = [r for r in requests if filter_pattern in r.get("url", "")]
            
            return {"status": "success", "requests": requests, "count": len(requests)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def generate_pdf(self, path=None, page_id=None):
        """Generate PDF (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            if not path:
                images_dir = self.core.config.get('paths', {}).get('images', './images')
                br_dir = Path(images_dir) / 'browser'
                br_dir.mkdir(parents=True, exist_ok=True)
                path = str(br_dir / 'page.pdf')

            await page.pdf(path=path)
            await self.core.log(f"PDF generated: {path}", priority=2)
            return {"status": "success", "path": path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_local_storage(self, page_id=None):
        """Get localStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            storage = await page.evaluate("() => Object.assign({}, window.localStorage)")
            return {"status": "success", "storage": storage}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_local_storage(self, key, value, page_id=None):
        """Set localStorage item (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.evaluate(f"() => window.localStorage.setItem('{key}', '{value}')")
            await self.core.log(f"Set localStorage: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_local_storage(self, page_id=None):
        """Clear localStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.evaluate("() => window.localStorage.clear()")
            await self.core.log("Cleared localStorage", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_session_storage(self, page_id=None):
        """Get sessionStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            storage = await page.evaluate("() => Object.assign({}, window.sessionStorage)")
            return {"status": "success", "storage": storage}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_session_storage(self, key, value, page_id=None):
        """Set sessionStorage item (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.evaluate(f"() => window.sessionStorage.setItem('{key}', '{value}')")
            await self.core.log(f"Set sessionStorage: {key}", priority=2)
            return {"status": "success", "key": key}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_session_storage(self, page_id=None):
        """Clear sessionStorage (OpenClaw parity)."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            
            await page.evaluate("() => window.sessionStorage.clear()")
            await self.core.log("Cleared sessionStorage", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_offline(self, offline=True):
        """Set offline mode (OpenClaw parity)."""
        try:
            await self.context.set_offline(offline)
            await self.core.log(f"Offline mode: {offline}", priority=2)
            return {"status": "success", "offline": offline}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_extra_http_headers(self, headers):
        """Set extra HTTP headers (OpenClaw parity)."""
        try:
            await self.context.set_extra_http_headers(headers)
            await self.core.log(f"Set {len(headers)} HTTP headers", priority=2)
            return {"status": "success", "count": len(headers)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_geolocation(self, latitude, longitude, accuracy=None):
        """Set geolocation (OpenClaw parity)."""
        try:
            geo = {"latitude": latitude, "longitude": longitude}
            if accuracy:
                geo["accuracy"] = accuracy
            
            await self.context.set_geolocation(geo)
            await self.core.log(f"Set geolocation: {latitude}, {longitude}", priority=2)
            return {"status": "success", "latitude": latitude, "longitude": longitude}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_geolocation(self):
        """Clear geolocation (OpenClaw parity)."""
        try:
            await self.context.clear_permissions()
            await self.core.log("Cleared geolocation", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_timezone(self, timezone_id):
        """Set browser timezone by recreating the context (OpenClaw parity - real implementation)."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}

            # Playwright requires timezone to be set at context creation time
            # Close the old context and recreate with the desired timezone
            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass

            self.context = await self.browser.new_context(
                timezone_id=timezone_id,
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)

            await self.core.log(f"Timezone set to: {timezone_id} (context recreated)", priority=2)
            return {"status": "success", "timezone": timezone_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def emulate_media(self, color_scheme=None, reduced_motion=None):
        """Emulate media features (OpenClaw parity)."""
        try:
            features = []
            if color_scheme:
                features.append({"name": "prefers-color-scheme", "value": color_scheme})
            if reduced_motion:
                features.append({"name": "prefers-reduced-motion", "value": reduced_motion})
            
            await self.context.emulate_media(color_scheme=color_scheme, reduced_motion=reduced_motion)
            await self.core.log(f"Emulated media: {color_scheme}", priority=2)
            return {"status": "success", "features": features}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ═══════════════════════════════════════════════════════════════════
    # NEW TOOLS — Beyond OpenClaw parity
    # ═══════════════════════════════════════════════════════════════════

    async def set_locale(self, locale):
        """Set browser locale by recreating the context (e.g. 'en-US', 'fr-FR', 'ja-JP')."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}
            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass
            self.context = await self.browser.new_context(
                locale=locale,
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)
            await self.core.log(f"Locale set to: {locale} (context recreated)", priority=2)
            return {"status": "success", "locale": locale}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_response_body(self, url_pattern=None, page_id=None):
        """Get captured HTTP response bodies. Optionally filter by URL substring."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            state = pageStates.get(page, {"responses": {}})
            responses = state.get("responses", {})
            if url_pattern:
                responses = {k: v for k, v in responses.items() if url_pattern in k}
            return {"status": "success", "responses": responses, "count": len(responses)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def click_coords(self, x, y, button="left", page_id=None):
        """Click at exact pixel coordinates. Useful for canvas elements or when selectors fail."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            await page.mouse.click(float(x), float(y), button=button)
            await self.core.log(f"Clicked coords ({x}, {y}) [{button}]", priority=2)
            return {"status": "success", "x": x, "y": y, "button": button}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_frames(self, page_id=None):
        """List all frames (including iframes) on the current page."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            frames = []
            for i, frame in enumerate(page.frames):
                frames.append({"index": i, "name": frame.name, "url": frame.url})
            return {"status": "success", "frames": frames, "count": len(frames)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def frame_action(self, frame_index, action, selector=None, text=None, page_id=None):
        """Perform an action inside an iframe. action: click | type | snapshot | evaluate."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            frames = page.frames
            if frame_index >= len(frames):
                return {"status": "error", "message": f"Frame {frame_index} out of range (have {len(frames)})"}
            frame = frames[frame_index]

            if action == "click":
                await frame.click(selector)
                return {"status": "success", "action": "click", "selector": selector}
            elif action == "type":
                await frame.fill(selector, text or "")
                return {"status": "success", "action": "type", "selector": selector}
            elif action == "snapshot":
                content = await frame.content()
                return {"status": "success", "action": "snapshot", "content": content[:10000]}
            elif action == "evaluate":
                result = await frame.evaluate(text or "")
                return {"status": "success", "action": "evaluate", "result": str(result)}
            else:
                return {"status": "error", "message": f"Unknown action: {action}. Use: click, type, snapshot, evaluate"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def trace_start(self, screenshots=True, snapshots=True, sources=False):
        """Start Playwright tracing (saves screenshots+snapshots for debugging)."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context — start browser first"}
            await self.context.tracing.start(
                screenshots=screenshots,
                snapshots=snapshots,
                sources=sources
            )
            await self.core.log("Playwright tracing started", priority=2)
            return {"status": "success", "screenshots": screenshots, "snapshots": snapshots}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def trace_stop(self, output_path=None, page_id=None):
        """Stop Playwright tracing and save the trace zip file."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context"}
            if not output_path:
                from pathlib import Path
                output_path = str(Path(self.core.config['paths']['logs']) / 'trace.zip')
            await self.context.tracing.stop(path=output_path)
            await self.core.log(f"Trace saved: {output_path}", priority=2)
            return {"status": "success", "path": output_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_intercept(self, rules, page_id=None):
        """
        Intercept network requests. rules = list of dicts:
          {"pattern": "ads.js", "action": "block"}
          {"pattern": "/api/data", "action": "mock", "body": '{"ok":true}', "status": 200}
        """
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}

            self._intercept_rules = rules  # store on instance

            async def handle_route(route, request):
                for rule in self._intercept_rules:
                    if rule.get('pattern', '') in request.url:
                        if rule.get('action') == 'block':
                            await route.abort()
                            return
                        elif rule.get('action') == 'mock':
                            await route.fulfill(
                                status=rule.get('status', 200),
                                content_type=rule.get('content_type', 'application/json'),
                                body=rule.get('body', '{}')
                            )
                            return
                await route.continue_()

            await page.route("**/*", handle_route)
            await self.core.log(f"Network intercept armed: {len(rules)} rule(s)", priority=2)
            return {"status": "success", "rules_count": len(rules)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def clear_intercept(self, page_id=None):
        """Remove all network interception rules."""
        try:
            page = self._get_page(page_id)
            if not page:
                return {"status": "error", "message": "No page available"}
            self._intercept_rules = []
            await page.unroute("**/*")
            await self.core.log("Network intercept cleared", priority=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def save_session(self, session_name="default"):
        """Save browser cookies & localStorage as a named session for reuse."""
        try:
            if not self.context:
                return {"status": "error", "message": "No browser context"}
            from pathlib import Path
            session_path = str(Path(self.core.config['paths']['logs']) / f'session_{session_name}.json')
            await self.context.storage_state(path=session_path)
            await self.core.log(f"Session saved: {session_name} → {session_path}", priority=2)
            return {"status": "success", "session": session_name, "path": session_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def load_session(self, session_name="default"):
        """Load a previously saved browser session (cookies + localStorage)."""
        try:
            if not self.browser:
                return {"status": "error", "message": "Browser not started"}
            from pathlib import Path
            session_path = Path(self.core.config['paths']['logs']) / f'session_{session_name}.json'
            if not session_path.exists():
                return {"status": "error", "message": f"No saved session named '{session_name}'"}

            old_page_id = self.active_page_id or "page_1"
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass

            self.context = await self.browser.new_context(
                storage_state=str(session_path),
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {old_page_id: page}
            self.active_page_id = old_page_id
            ensurePageState(page)
            await self.core.log(f"Session loaded: {session_name}", priority=2)
            return {"status": "success", "session": session_name}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def restart_with_proxy(self, server, username=None, password=None):
        """Restart the browser with a proxy server (e.g. 'http://proxy:8080')."""
        try:
            if not self.playwright:
                return {"status": "error", "message": "Playwright not started — open browser first"}

            proxy_config = {"server": server}
            if username:
                proxy_config["username"] = username
                proxy_config["password"] = password or ""

            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass

            engine_name = self.core.config.get('browser', {}).get('engine', 'chromium')
            browser_engine = getattr(self.playwright, engine_name, self.playwright.chromium)
            headless = self.core.config.get('browser', {}).get('headless', False)

            self.browser = await browser_engine.launch(
                headless=headless,
                proxy=proxy_config,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await self.context.new_page()
            self.pages = {"page_1": page}
            self.active_page_id = "page_1"
            ensurePageState(page)
            await self.core.log(f"Browser restarted with proxy: {server}", priority=2)
            return {"status": "success", "proxy": server}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def close(self):
        """Shutdown browser."""
        if self.browser:
            await self.browser.close()
            await self.playwright.stop()
            self.started = False
            await self.core.log("Browser closed", priority=2)

    async def run(self):
        """Plugin main loop."""
        await self.core.log("Browser Executor PRO: Ready for automation", priority=2)
        while self.enabled:
            await asyncio.sleep(10)
