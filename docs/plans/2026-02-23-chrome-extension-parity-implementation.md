# Chrome Extension Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring the Galactic Browser Chrome extension to full feature parity with Claude in Chrome — fixing 2 broken behaviors and adding 11 new capabilities.

**Architecture:** The Chrome extension communicates via WebSocket to `ChromeBridgeSkill` in Python. JavaScript changes go in `content.js` (DOM interaction) and `background.js` (Chrome API commands). Python changes go in `skills/core/chrome_bridge.py` (tool definitions + handlers). The gateway's `speak()` loop receives all tool results as plain text strings — image results need a special detection pass added to make screenshots visual.

**Tech Stack:** JavaScript (MV3 Chrome extension), Python 3.11, asyncio, Pillow (GIF assembly), Chrome Debugger Protocol

---

## Task 1: Fix contenteditable typing in content.js

**Files:**
- Modify: `chrome-extension/content.js` — `performType()` function (around line 200)

### Step 1: Find the contenteditable branch in performType()

Open `content.js` and locate `performType`. Find the block:
```javascript
} else if (el.contentEditable === 'true') {
    el.textContent = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
}
```

### Step 2: Replace with execCommand-based typing

Replace that entire `else if` block with:

```javascript
} else if (el.contentEditable === 'true') {
    el.focus();
    // Select all existing content if clearing
    if (clear !== false) {
        document.execCommand('selectAll', false, null);
        document.execCommand('delete', false, null);
    }
    // insertText fires the full keydown/keypress/keyup event chain
    // that modern SPAs (X.com, Notion, Reddit) require
    const inserted = document.execCommand('insertText', false, text);
    if (!inserted) {
        // execCommand fallback: dispatch keyboard events character by character
        for (const char of text) {
            ['keydown', 'keypress', 'keyup'].forEach(evtType => {
                el.dispatchEvent(new KeyboardEvent(evtType, {
                    key: char, char: char, charCode: char.charCodeAt(0),
                    keyCode: char.charCodeAt(0), which: char.charCodeAt(0),
                    bubbles: true, cancelable: true
                }));
            });
            el.textContent += char;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
}
```

### Step 3: Verify by testing in X.com

1. Load the extension, open x.com/compose/post
2. Have Byte type something using `chrome_type` with the compose box selector `[data-testid="tweetTextarea_0"]`
3. Text should appear in the compose box

### Step 4: Commit

```bash
git add chrome-extension/content.js
git commit -m "fix(chrome-ext): fix contenteditable typing to fire proper keyboard events"
```

---

## Task 2: Fix chrome_screenshot to save file + enable LLM vision

**Files:**
- Modify: `skills/core/chrome_bridge.py` — `_tool_chrome_screenshot()` (around line 197)
- Modify: `gateway_v2.py` — `speak()` loop tool result handling (line 2512)

### Context

The current handler returns a text string discarding the image data. Two improvements:
1. Save the JPEG to disk so the LLM can reference it (consistent with Playwright)
2. Add gateway vision support so Byte can see screenshots natively in the ReAct loop

### Step 1: Fix the screenshot handler to save the image

In `chrome_bridge.py`, replace `_tool_chrome_screenshot`:

```python
async def _tool_chrome_screenshot(self, args):
    if not self.ws_connection:
        return "[ERROR] Chrome extension not connected. Install the Galactic Browser extension and click Connect."
    result = await self.screenshot()
    if result.get('status') == 'success':
        img_data = result.get('image_b64', '')
        if not img_data:
            return "[ERROR] Chrome screenshot: no image data returned"

        # Save to images/browser/ directory (consistent with Playwright screenshot)
        try:
            import base64
            from pathlib import Path
            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = Path(images_dir) / 'browser'
            img_subdir.mkdir(parents=True, exist_ok=True)

            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = str(img_subdir / f'chrome_{ts}.jpg')

            raw = base64.b64decode(img_data)
            with open(path, 'wb') as f:
                f.write(raw)

            # Return special dict that gateway will render as vision message
            return {"__image_b64__": img_data, "path": path, "media_type": "image/jpeg",
                    "text": f"[CHROME] Screenshot saved: {path}"}
        except Exception as e:
            return f"[CHROME] Screenshot captured ({len(img_data)} chars base64) — save failed: {e}"
    return f"[ERROR] Chrome screenshot: {result.get('error') or result.get('message') or 'unknown error'}"
```

### Step 2: Add vision result detection in gateway_v2.py speak() loop

In `gateway_v2.py`, find line ~2512:
```python
messages.append({"role": "assistant", "content": response_text})
messages.append({"role": "user", "content": f"Tool Output: {result}"})
```

Replace with:

```python
messages.append({"role": "assistant", "content": response_text})

# Vision-capable tool result (screenshot with image data)
if isinstance(result, dict) and "__image_b64__" in result:
    img_b64 = result["__image_b64__"]
    media_type = result.get("media_type", "image/jpeg")
    caption = result.get("text", "[CHROME] Screenshot captured")
    # Build multimodal user message so the LLM can see the screenshot
    img_content = [
        {"type": "text", "text": f"Tool Output: {caption}"},
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{img_b64}"}}
    ]
    messages.append({"role": "user", "content": img_content})
else:
    messages.append({"role": "user", "content": f"Tool Output: {result}"})
```

### Step 3: Verify

1. Ask Byte: "Take a screenshot of the current Chrome tab and describe what you see"
2. Byte should call `chrome_screenshot`, see the image visually, and describe the page content (not just say "screenshot captured")
3. Check that the JPG file was created in `images/browser/`

### Step 4: Commit

```bash
git add skills/core/chrome_bridge.py gateway_v2.py
git commit -m "feat(chrome-bridge): screenshot saves file + gateway vision support for image tool results"
```

---

## Task 3: Add chrome_zoom (region screenshot)

**Files:**
- Modify: `chrome-extension/background.js` — add `zoom` command handler
- Modify: `skills/core/chrome_bridge.py` — add `chrome_zoom` tool + handler + convenience method

### Step 1: Add zoom command in background.js

Find the command router in `background.js` (the big `if/else if` chain or switch). Add after the `screenshot` handler:

```javascript
} else if (command === 'zoom') {
    const { tab_id, region } = args;
    const targetTab = tab_id ? { id: tab_id } : activeTab;
    if (!targetTab) { sendResult(id, { status: 'error', error: 'No active tab' }); return; }

    // Take full screenshot first
    chrome.tabs.captureVisibleTab(null, { format: 'jpeg', quality: 85 }, (fullDataUrl) => {
        if (chrome.runtime.lastError) {
            sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
            return;
        }
        // Crop to region using OffscreenCanvas
        (async () => {
            try {
                const [x0, y0, x1, y1] = region;
                const width = x1 - x0;
                const height = y1 - y0;

                const resp = await fetch(fullDataUrl);
                const blob = await resp.blob();
                const bitmap = await createImageBitmap(blob);

                const canvas = new OffscreenCanvas(width, height);
                const ctx = canvas.getContext('2d');
                ctx.drawImage(bitmap, x0, y0, width, height, 0, 0, width, height);

                const croppedBlob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
                const reader = new FileReader();
                reader.onloadend = () => {
                    const b64 = reader.result.split(',')[1];
                    sendResult(id, { status: 'success', image_b64: b64, region, width, height });
                };
                reader.readAsDataURL(croppedBlob);
            } catch (err) {
                sendResult(id, { status: 'error', error: err.message });
            }
        })();
    });
```

### Step 2: Add chrome_zoom tool in chrome_bridge.py

In `get_tools()`, add after `chrome_hover`:

```python
"chrome_zoom": {
    "description": "Capture a cropped region of the Chrome browser for close inspection of small elements. Returns a JPEG of just that region.",
    "parameters": {"type": "object", "properties": {
        "region": {"type": "array", "description": "Bounding box [x0, y0, x1, y1] in pixels from top-left of viewport"},
    }, "required": ["region"]},
    "fn": self._tool_chrome_zoom
},
```

Add the handler and convenience method:

```python
async def _tool_chrome_zoom(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    region = args.get('region')
    if not region or len(region) != 4:
        return "[ERROR] chrome_zoom: region must be [x0, y0, x1, y1]"
    result = await self.zoom(region=region)
    if result.get('status') == 'success':
        img_data = result.get('image_b64', '')
        if not img_data:
            return "[ERROR] Chrome zoom: no image data"
        try:
            import base64
            from pathlib import Path
            from datetime import datetime
            images_dir = self.core.config.get('paths', {}).get('images', './images')
            img_subdir = Path(images_dir) / 'browser'
            img_subdir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = str(img_subdir / f'chrome_zoom_{ts}.jpg')
            with open(path, 'wb') as f:
                f.write(base64.b64decode(img_data))
            return {"__image_b64__": img_data, "path": path, "media_type": "image/jpeg",
                    "text": f"[CHROME] Zoomed region {region} saved: {path}"}
        except Exception as e:
            return f"[CHROME] Zoom captured — save failed: {e}"
    return f"[ERROR] Chrome zoom: {result.get('error') or 'unknown'}"

async def zoom(self, region: list, tab_id=None):
    return await self.send_command("zoom", {"region": region, "tab_id": tab_id})
```

### Step 3: Verify

Ask Byte: "Zoom in on the top-left 200x200 pixels of my Chrome tab and describe what you see."
Expected: Byte calls `chrome_zoom` with `[0, 0, 200, 200]`, gets an image, describes the content.

### Step 4: Commit

```bash
git add chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_zoom for region screenshot inspection"
```

---

## Task 4: Add chrome_drag (left_click_drag)

**Files:**
- Modify: `chrome-extension/content.js` — add `performDrag()` function
- Modify: `chrome-extension/background.js` — add `drag` command handler
- Modify: `skills/core/chrome_bridge.py` — add `chrome_drag` tool

### Step 1: Add performDrag in content.js

Add after `performHover`:

```javascript
function performDrag(startX, startY, endX, endY) {
    const startEl = document.elementFromPoint(startX, startY);
    if (!startEl) return { success: false, error: 'No element at start coordinates' };

    // Helper to dispatch a mouse event
    function mouseEvt(type, x, y, target) {
        target.dispatchEvent(new MouseEvent(type, {
            clientX: x, clientY: y, screenX: x, screenY: y,
            bubbles: true, cancelable: true, view: window,
            buttons: type === 'mouseup' ? 0 : 1, button: 0
        }));
    }

    mouseEvt('mousedown', startX, startY, startEl);

    // Move in steps to simulate real drag
    const steps = 10;
    for (let i = 1; i <= steps; i++) {
        const x = startX + (endX - startX) * i / steps;
        const y = startY + (endY - startY) * i / steps;
        const el = document.elementFromPoint(x, y) || startEl;
        mouseEvt('mousemove', x, y, el);
    }

    const endEl = document.elementFromPoint(endX, endY) || startEl;
    mouseEvt('mouseup', endX, endY, endEl);
    mouseEvt('click', endX, endY, endEl);

    return { success: true };
}
```

### Step 2: Add drag command handler in background.js

Wire it to call `performDrag` via scripting.executeScript:

```javascript
} else if (command === 'drag') {
    const { start_x, start_y, end_x, end_y, tab_id } = args;
    const targetTab = tab_id ? { id: tab_id } : activeTab;
    if (!targetTab) { sendResult(id, { status: 'error', error: 'No active tab' }); return; }

    chrome.scripting.executeScript({
        target: { tabId: targetTab.id },
        func: (sx, sy, ex, ey) => {
            if (typeof performDrag === 'function') {
                return performDrag(sx, sy, ex, ey);
            }
            return { success: false, error: 'Content script not ready' };
        },
        args: [start_x, start_y, end_x, end_y]
    }, (results) => {
        if (chrome.runtime.lastError) {
            sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
        } else {
            const r = results?.[0]?.result || {};
            sendResult(id, r.success ? { status: 'success' } : { status: 'error', error: r.error });
        }
    });
```

### Step 3: Add chrome_drag tool in chrome_bridge.py

```python
"chrome_drag": {
    "description": "Drag from one coordinate to another for drag-and-drop, sliders, and reordering.",
    "parameters": {"type": "object", "properties": {
        "start_x": {"type": "number"}, "start_y": {"type": "number"},
        "end_x": {"type": "number"}, "end_y": {"type": "number"},
    }, "required": ["start_x", "start_y", "end_x", "end_y"]},
    "fn": self._tool_chrome_drag
},
```

```python
async def _tool_chrome_drag(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    result = await self.send_command("drag", {
        "start_x": args.get('start_x'), "start_y": args.get('start_y'),
        "end_x": args.get('end_x'), "end_y": args.get('end_y'),
    })
    if result.get('status') == 'success':
        return f"[CHROME] Dragged from ({args.get('start_x')},{args.get('start_y')}) to ({args.get('end_x')},{args.get('end_y')})"
    return f"[ERROR] Chrome drag: {result.get('error') or 'unknown'}"
```

### Step 4: Verify

Ask Byte: "Drag from coordinate 100,100 to 300,300 in my Chrome tab."
Expected: No error, `[CHROME] Dragged from (100,100) to (300,300)`

### Step 5: Commit

```bash
git add chrome-extension/content.js chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_drag for click-drag interactions"
```

---

## Task 5: Add chrome_right_click and chrome_triple_click

**Files:**
- Modify: `chrome-extension/content.js` — extend `performClick` to support `click_count` and `right_click`
- Modify: `chrome-extension/background.js` — add `right_click` and `triple_click` command handlers
- Modify: `skills/core/chrome_bridge.py` — add both tools

### Step 1: Extend click dispatch in content.js

Add `performRightClick` function:

```javascript
function performRightClick(el, x, y) {
    const rect = el.getBoundingClientRect();
    const cx = x !== undefined ? x : rect.left + rect.width / 2;
    const cy = y !== undefined ? y : rect.top + rect.height / 2;
    el.dispatchEvent(new MouseEvent('mousedown', { clientX: cx, clientY: cy, button: 2, buttons: 2, bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup',   { clientX: cx, clientY: cy, button: 2, buttons: 0, bubbles: true }));
    el.dispatchEvent(new MouseEvent('contextmenu', { clientX: cx, clientY: cy, button: 2, bubbles: true, cancelable: true }));
    return { success: true };
}
```

Add `performTripleClick`:

```javascript
function performTripleClick(el) {
    for (let i = 1; i <= 3; i++) {
        el.dispatchEvent(new MouseEvent('click', { detail: i, bubbles: true, cancelable: true }));
    }
    // Also select all text in the element
    if (el.select) el.select();
    return { success: true };
}
```

### Step 2: Add command handlers in background.js

Add `right_click` and `triple_click` to the command router, following the same pattern as the existing `click` handler but calling `performRightClick` / `performTripleClick`.

### Step 3: Add tools in chrome_bridge.py

```python
"chrome_right_click": {
    "description": "Right-click to open a context menu at a ref, selector, or coordinates.",
    "parameters": {"type": "object", "properties": {
        "ref": {"type": "string"}, "selector": {"type": "string"},
        "x": {"type": "number"}, "y": {"type": "number"},
    }},
    "fn": self._tool_chrome_right_click
},
"chrome_triple_click": {
    "description": "Triple-click to select all text in an input or contenteditable element.",
    "parameters": {"type": "object", "properties": {
        "ref": {"type": "string"}, "selector": {"type": "string"},
        "x": {"type": "number"}, "y": {"type": "number"},
    }},
    "fn": self._tool_chrome_triple_click
},
```

Handlers follow the same pattern as `_tool_chrome_click` — send `"right_click"` or `"triple_click"` command with ref/selector/x/y args.

### Step 4: Verify

Ask Byte: "Right-click on the body of my current Chrome tab." Context menu should appear.

### Step 5: Commit

```bash
git add chrome-extension/content.js chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_right_click and chrome_triple_click"
```

---

## Task 6: Add chrome_upload (file upload via debugger)

**Files:**
- Modify: `chrome-extension/background.js` — add `upload_file` command using Chrome debugger
- Modify: `skills/core/chrome_bridge.py` — add `chrome_upload` tool

### Key insight

`DOM.setFileInputFiles` in the Chrome DevTools Protocol allows setting files on `<input type="file">` elements programmatically. The debugger must be attached to the tab (already done in this extension for console/network monitoring).

### Step 1: Add upload_file command in background.js

```javascript
} else if (command === 'upload_file') {
    const { ref, selector, file_path, tab_id } = args;
    const targetTab = tab_id ? { id: tab_id } : activeTab;
    if (!targetTab) { sendResult(id, { status: 'error', error: 'No active tab' }); return; }

    // Ensure debugger is attached
    const debuggee = { tabId: targetTab.id };

    const doUpload = () => {
        // First, get the DOM node ID for the selector/ref
        chrome.debugger.sendCommand(debuggee, 'DOM.getDocument', {}, (doc) => {
            chrome.debugger.sendCommand(debuggee, 'DOM.querySelector',
                { nodeId: doc.root.nodeId, selector: selector || `[data-galactic-ref="${ref}"]` },
                (result) => {
                    if (!result || !result.nodeId) {
                        sendResult(id, { status: 'error', error: 'Element not found' });
                        return;
                    }
                    chrome.debugger.sendCommand(debuggee, 'DOM.setFileInputFiles', {
                        files: [file_path],
                        nodeId: result.nodeId
                    }, () => {
                        if (chrome.runtime.lastError) {
                            sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
                        } else {
                            sendResult(id, { status: 'success', file_path });
                        }
                    });
                }
            );
        });
    };

    // Attach debugger if not already attached
    chrome.debugger.attach(debuggee, '1.3', () => {
        if (chrome.runtime.lastError && !chrome.runtime.lastError.message.includes('already attached')) {
            sendResult(id, { status: 'error', error: `Debugger attach failed: ${chrome.runtime.lastError.message}` });
            return;
        }
        doUpload();
    });
```

### Step 2: Add chrome_upload tool in chrome_bridge.py

```python
"chrome_upload": {
    "description": "Upload a local file to a file input element (<input type='file'>) in Chrome. Use ref or selector to target the input.",
    "parameters": {"type": "object", "properties": {
        "file_path": {"type": "string", "description": "Absolute path to the local file to upload"},
        "ref": {"type": "string", "description": "Element ref ID from chrome_read_page"},
        "selector": {"type": "string", "description": "CSS selector for the file input"},
    }, "required": ["file_path"]},
    "fn": self._tool_chrome_upload
},
```

```python
async def _tool_chrome_upload(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    import os
    file_path = args.get('file_path', '')
    if not os.path.exists(file_path):
        return f"[ERROR] File not found: {file_path}"
    result = await self.send_command("upload_file", {
        "file_path": file_path,
        "ref": args.get('ref'),
        "selector": args.get('selector'),
    })
    if result.get('status') == 'success':
        return f"[CHROME] File uploaded: {file_path}"
    return f"[ERROR] Chrome upload: {result.get('error') or 'unknown'}"
```

### Step 3: Verify

1. Navigate to a page with a file input (e.g., a Google Form or any site with file upload)
2. Ask Byte: "Upload the file `C:/some/file.jpg` to the file input on this page"
3. The file input should show the file selected

### Step 4: Commit

```bash
git add chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_upload for file input via debugger DOM.setFileInputFiles"
```

---

## Task 7: Add chrome_resize (viewport resize)

**Files:**
- Modify: `chrome-extension/background.js` — add `resize_window` command
- Modify: `skills/core/chrome_bridge.py` — add `chrome_resize` tool

### Step 1: Add resize_window command in background.js

```javascript
} else if (command === 'resize_window') {
    const { width, height, preset, tab_id } = args;
    const targetTab = tab_id ? { id: tab_id } : activeTab;
    if (!targetTab) { sendResult(id, { status: 'error', error: 'No active tab' }); return; }

    const presets = { mobile: [375, 812], tablet: [768, 1024], desktop: [1280, 800] };
    const [w, h] = preset ? (presets[preset] || [1280, 800]) : [width || 1280, height || 800];

    const debuggee = { tabId: targetTab.id };
    chrome.debugger.attach(debuggee, '1.3', () => {
        if (chrome.runtime.lastError && !chrome.runtime.lastError.message.includes('already attached')) {
            sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
            return;
        }
        chrome.debugger.sendCommand(debuggee, 'Emulation.setDeviceMetricsOverride', {
            width: w, height: h, deviceScaleFactor: 1, mobile: preset === 'mobile'
        }, () => {
            if (chrome.runtime.lastError) {
                sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
            } else {
                sendResult(id, { status: 'success', width: w, height: h, preset: preset || 'custom' });
            }
        });
    });
```

### Step 2: Add chrome_resize tool in chrome_bridge.py

```python
"chrome_resize": {
    "description": "Resize the Chrome browser viewport. Use preset 'mobile' (375×812), 'tablet' (768×1024), or 'desktop' (1280×800), or provide custom width/height.",
    "parameters": {"type": "object", "properties": {
        "preset": {"type": "string", "description": "mobile | tablet | desktop"},
        "width": {"type": "number"}, "height": {"type": "number"},
    }},
    "fn": self._tool_chrome_resize
},
```

```python
async def _tool_chrome_resize(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    result = await self.send_command("resize_window", {
        "preset": args.get('preset'),
        "width": args.get('width'),
        "height": args.get('height'),
    })
    if result.get('status') == 'success':
        w, h, p = result.get('width'), result.get('height'), result.get('preset', 'custom')
        return f"[CHROME] Viewport resized to {w}×{h} ({p})"
    return f"[ERROR] Chrome resize: {result.get('error') or 'unknown'}"
```

### Step 3: Verify

Ask Byte: "Resize my Chrome viewport to mobile size." Take a screenshot — page should be narrow (375px wide).

### Step 4: Commit

```bash
git add chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_resize for viewport resize via Emulation.setDeviceMetricsOverride"
```

---

## Task 8: Add chrome_get_network_body + update chrome_read_network

**Files:**
- Modify: `chrome-extension/background.js` — add `get_network_body` command, update network capture to store request_id
- Modify: `skills/core/chrome_bridge.py` — add `chrome_get_network_body`, update network handler output

### Step 1: Update network request capture in background.js

Find where network requests are stored (the array filled by `Network.requestWillBeSent`). Ensure each entry stores the debugger `requestId`:

```javascript
// In the Network.requestWillBeSent listener:
networkRequests.push({
    requestId: params.requestId,  // ← Add this if not already present
    url: params.request.url,
    method: params.request.method,
    status: null,
    // ...
});
```

### Step 2: Add get_network_body command in background.js

```javascript
} else if (command === 'get_network_body') {
    const { request_id, tab_id } = args;
    const targetTab = tab_id ? { id: tab_id } : activeTab;
    if (!targetTab) { sendResult(id, { status: 'error', error: 'No active tab' }); return; }

    const debuggee = { tabId: targetTab.id };
    chrome.debugger.attach(debuggee, '1.3', () => {
        if (chrome.runtime.lastError && !chrome.runtime.lastError.message.includes('already attached')) {
            sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
            return;
        }
        chrome.debugger.sendCommand(debuggee, 'Network.getResponseBody',
            { requestId: request_id },
            (result) => {
                if (chrome.runtime.lastError) {
                    sendResult(id, { status: 'error', error: chrome.runtime.lastError.message });
                } else {
                    sendResult(id, { status: 'success', body: result.body, base64_encoded: result.base64Encoded });
                }
            }
        );
    });
```

### Step 3: Update chrome_read_network output to include request_id

In `_tool_chrome_read_network` in `chrome_bridge.py`, add `request_id` to each line output:

```python
for r in requests_list[:50]:
    rid = r.get('request_id') or r.get('requestId', '?')
    lines.append(f"  [{rid}] {r.get('method', '?')} {r.get('status', '?')} {r.get('url', '')[:100]}")
```

### Step 4: Add chrome_get_network_body tool

```python
"chrome_get_network_body": {
    "description": "Fetch the response body for a specific network request by its ID. Get request IDs from chrome_read_network output.",
    "parameters": {"type": "object", "properties": {
        "request_id": {"type": "string", "description": "Request ID from chrome_read_network output"},
    }, "required": ["request_id"]},
    "fn": self._tool_chrome_get_network_body
},
```

```python
async def _tool_chrome_get_network_body(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    result = await self.send_command("get_network_body", {"request_id": args.get('request_id')})
    if result.get('status') == 'success':
        body = result.get('body', '')
        encoded = result.get('base64_encoded', False)
        if encoded:
            return f"[CHROME] Response body (base64, {len(body)} chars): {body[:2000]}"
        return f"[CHROME] Response body ({len(body)} chars):\n{body[:5000]}"
    return f"[ERROR] Chrome get_network_body: {result.get('error') or 'unknown'}"
```

### Step 5: Verify

1. Navigate to any page that makes API calls
2. Call `chrome_read_network` — confirm request_ids appear in the output
3. Call `chrome_get_network_body` with one of those IDs — confirm body is returned

### Step 6: Commit

```bash
git add chrome-extension/background.js skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_get_network_body + request_id in network output"
```

---

## Task 9: Add chrome_wait

**Files:**
- Modify: `skills/core/chrome_bridge.py` — add `chrome_wait` tool (Python-side only)

### Step 1: Add tool and handler

In `get_tools()`:

```python
"chrome_wait": {
    "description": "Wait for N seconds between browser actions. Use after navigation or clicks to let pages load or animations settle.",
    "parameters": {"type": "object", "properties": {
        "seconds": {"type": "number", "description": "Number of seconds to wait (max 30)"},
    }, "required": ["seconds"]},
    "fn": self._tool_chrome_wait
},
```

Handler:

```python
async def _tool_chrome_wait(self, args):
    seconds = min(float(args.get('seconds', 1)), 30)
    await asyncio.sleep(seconds)
    return f"[CHROME] Waited {seconds}s"
```

### Step 2: Commit

```bash
git add skills/core/chrome_bridge.py
git commit -m "feat(chrome-bridge): add chrome_wait for explicit waits between actions"
```

---

## Task 10: Add GIF Recorder (chrome_gif_start, chrome_gif_stop, chrome_gif_export)

**Files:**
- Modify: `skills/core/chrome_bridge.py` — add GIF state + 3 tools + export logic
- Check: `requirements.txt` — ensure `Pillow` is listed

### Step 1: Check requirements.txt for Pillow

```bash
grep -i pillow "F:/Galactic AI Public Release/requirements.txt"
```

If not present, add `Pillow>=10.0.0` to `requirements.txt`.

### Step 2: Add GIF state to ChromeBridgeSkill.__init__

```python
# GIF recorder state
self._gif_recording: bool = False
self._gif_frames: list = []        # list of base64 JPEG strings
self._gif_fps: float = 2.0
self._gif_task = None              # asyncio Task for polling loop
```

### Step 3: Add gif_start tool and handler

```python
"chrome_gif_start": {
    "description": "Start recording a GIF of the Chrome browser. Takes screenshots at the specified FPS.",
    "parameters": {"type": "object", "properties": {
        "fps": {"type": "number", "description": "Frames per second (default: 2, max: 5)"},
    }},
    "fn": self._tool_chrome_gif_start
},
```

```python
async def _tool_chrome_gif_start(self, args):
    if not self.ws_connection: return "[ERROR] Chrome extension not connected."
    if self._gif_recording:
        return "[CHROME] GIF recording already in progress. Call chrome_gif_stop first."

    self._gif_frames.clear()
    self._gif_fps = min(float(args.get('fps', 2)), 5)
    self._gif_recording = True

    async def _poll():
        interval = 1.0 / self._gif_fps
        while self._gif_recording:
            try:
                result = await self.screenshot()
                if result.get('status') == 'success' and result.get('image_b64'):
                    self._gif_frames.append(result['image_b64'])
            except Exception:
                pass
            await asyncio.sleep(interval)

    self._gif_task = asyncio.create_task(_poll())
    return f"[CHROME] GIF recording started at {self._gif_fps}fps"
```

### Step 4: Add gif_stop tool and handler

```python
"chrome_gif_stop": {
    "description": "Stop the GIF recording. Frames are kept in memory until chrome_gif_export is called.",
    "parameters": {"type": "object", "properties": {}},
    "fn": self._tool_chrome_gif_stop
},
```

```python
async def _tool_chrome_gif_stop(self, args):
    if not self._gif_recording:
        return "[CHROME] No GIF recording in progress."
    self._gif_recording = False
    if self._gif_task:
        self._gif_task.cancel()
        try:
            await self._gif_task
        except asyncio.CancelledError:
            pass
        self._gif_task = None
    return f"[CHROME] GIF recording stopped. {len(self._gif_frames)} frames captured."
```

### Step 5: Add gif_export tool and handler

```python
"chrome_gif_export": {
    "description": "Export the recorded GIF frames to an animated GIF file. Returns the file path.",
    "parameters": {"type": "object", "properties": {
        "quality": {"type": "number", "description": "GIF quality 1-30 (lower=better, default: 10)"},
        "show_progress_bar": {"type": "boolean", "description": "Add progress bar overlay (default: true)"},
    }},
    "fn": self._tool_chrome_gif_export
},
```

```python
async def _tool_chrome_gif_export(self, args):
    if not self._gif_frames:
        return "[ERROR] No GIF frames to export. Call chrome_gif_start and chrome_gif_stop first."

    try:
        import base64
        import io
        from pathlib import Path
        from datetime import datetime
        from PIL import Image, ImageDraw

        quality = max(1, min(int(args.get('quality', 10)), 30))
        show_bar = args.get('show_progress_bar', True)

        frames = []
        total = len(self._gif_frames)

        for i, b64 in enumerate(self._gif_frames):
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw)).convert('RGBA')

            if show_bar:
                draw = ImageDraw.Draw(img)
                bar_height = 4
                bar_width = int(img.width * (i + 1) / total)
                draw.rectangle([0, img.height - bar_height, bar_width, img.height],
                               fill=(255, 140, 0, 255))  # orange progress bar

            frames.append(img.convert('P', palette=Image.ADAPTIVE, colors=256 // quality))

        # Save GIF
        recordings_dir = Path('logs') / 'recordings'
        recordings_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = str(recordings_dir / f'chrome_{ts}.gif')

        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            optimize=True,
            loop=0,
            duration=int(1000 / self._gif_fps)
        )

        self._gif_frames.clear()
        return f"[CHROME] GIF exported: {path} ({total} frames, {self._gif_fps}fps)"

    except ImportError:
        return "[ERROR] Pillow not installed. Run: pip install Pillow"
    except Exception as e:
        return f"[ERROR] GIF export failed: {e}"
```

### Step 6: Verify

1. Ask Byte: "Start recording a GIF"
2. Ask Byte: "Navigate to google.com"
3. Ask Byte: "Stop recording and export the GIF"
4. Check `logs/recordings/` for the .gif file and open it

### Step 7: Commit

```bash
git add skills/core/chrome_bridge.py requirements.txt
git commit -m "feat(chrome-bridge): add GIF recorder (chrome_gif_start/stop/export) with Pillow assembly"
```

---

## Task 11: Bump version + update docs

**Files:**
- Modify: `skills/core/chrome_bridge.py` — version string
- Modify: `FEATURES.md` — Chrome Browser Tools section
- Modify: `README.md` — Chrome Extension feature table + version history
- Modify: `CHANGELOG.md` — add v1.1.3 entry

### Step 1: Bump version in chrome_bridge.py

```python
version = "1.1.3"
```

### Step 2: Update FEATURES.md Chrome Browser Tools section

Change "Chrome Browser Tools (16 tools)" → "Chrome Browser Tools (27 tools)" and add the new tools to the table.

New entries to add:
| `chrome_zoom` | Capture a cropped region for close inspection of small UI elements |
| `chrome_drag` | Drag from one coordinate to another (drag-and-drop, sliders) |
| `chrome_right_click` | Right-click to open context menus |
| `chrome_triple_click` | Triple-click to select all text in an input |
| `chrome_upload` | Upload a local file to a file input element |
| `chrome_resize` | Resize the viewport (mobile/tablet/desktop presets or custom) |
| `chrome_get_network_body` | Fetch the response body for a captured network request |
| `chrome_wait` | Wait N seconds between browser actions |
| `chrome_type` | *(fixed)* Now works correctly on contenteditable elements (X.com, Notion, Reddit) |
| `chrome_screenshot` | *(fixed)* Now saves file to disk and LLM can see the image |
| `chrome_gif_start` | Start recording browser interactions as frames |
| `chrome_gif_stop` | Stop recording (keeps frames in memory) |
| `chrome_gif_export` | Assemble frames into animated GIF with progress bar overlay |

### Step 3: Update README.md Chrome Extension section

Update the tool list from 10→16→27, add new tool entries, bump version history.

### Step 4: Add CHANGELOG entry

```markdown
## [v1.1.3] — 2026-02-23

### Added
- **🌐 Galactic Browser — Full Claude Parity (27 tools)** — Chrome extension expanded from 16 to 27 tools with full feature parity with Claude in Chrome. New: `chrome_zoom` (region screenshot), `chrome_drag` (click-drag), `chrome_right_click` (context menus), `chrome_triple_click` (select all), `chrome_upload` (file input via debugger `DOM.setFileInputFiles`), `chrome_resize` (viewport resize via `Emulation.setDeviceMetricsOverride`), `chrome_get_network_body` (response body by request ID), `chrome_wait` (explicit wait), `chrome_gif_start`/`chrome_gif_stop`/`chrome_gif_export` (GIF recorder with Pillow assembly and progress bar overlay)

### Fixed
- **🔧 contenteditable typing** — `chrome_type` now fires proper `keydown/keypress/keyup` events on contenteditable elements via `document.execCommand('insertText')`. Previously silently failed on X.com, Notion, Reddit compose, and Google Docs
- **📸 chrome_screenshot now visual** — Screenshots are saved to `images/browser/` and returned as vision-capable image results. The LLM can now see the screenshot content instead of receiving only a text description
- **🌐 Gateway vision support for tool results** — `gateway_v2.py` speak() loop now detects image tool results (`__image_b64__` key) and builds multimodal user messages, enabling any tool to return images the LLM can analyze
```

### Step 5: Commit

```bash
git add skills/core/chrome_bridge.py FEATURES.md README.md CHANGELOG.md
git commit -m "docs: update docs for v1.1.3 chrome extension parity (27 tools)"
```

---

## Summary

| Task | Files | New Tools |
|---|---|---|
| 1. Fix contenteditable | content.js | — |
| 2. Fix screenshot + gateway vision | chrome_bridge.py, gateway_v2.py | — |
| 3. chrome_zoom | background.js, chrome_bridge.py | chrome_zoom |
| 4. chrome_drag | content.js, background.js, chrome_bridge.py | chrome_drag |
| 5. right_click + triple_click | content.js, background.js, chrome_bridge.py | chrome_right_click, chrome_triple_click |
| 6. chrome_upload | background.js, chrome_bridge.py | chrome_upload |
| 7. chrome_resize | background.js, chrome_bridge.py | chrome_resize |
| 8. network body + IDs | background.js, chrome_bridge.py | chrome_get_network_body |
| 9. chrome_wait | chrome_bridge.py | chrome_wait |
| 10. GIF recorder | chrome_bridge.py, requirements.txt | chrome_gif_start, chrome_gif_stop, chrome_gif_export |
| 11. Docs + version bump | chrome_bridge.py, FEATURES, README, CHANGELOG | — |

**Total new tools:** 11 → ChromeBridgeSkill goes from 16 to **27 tools**
