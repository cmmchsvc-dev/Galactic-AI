# Design: Galactic Browser — Claude Parity (v1.1.3)

**Date:** 2026-02-23
**Status:** Approved

---

## Goal

Bring the Galactic Browser Chrome extension to full feature parity with Claude in Chrome, fixing two broken behaviors and adding 11 new capabilities. After this work, Byte using the real Chrome extension will have the same interaction surface as Claude operating in its own browser.

---

## Files

| File | Changes |
|---|---|
| `chrome-extension/content.js` | Fix `performType()` for contenteditable elements |
| `chrome-extension/background.js` | Fix screenshot return; add 8 new commands + GIF polling |
| `skills/core/chrome_bridge.py` | Fix screenshot handler to return image; add 11 new Python tools |

---

## Section 1: Bug Fixes

### Fix 1 — Screenshot returns visual image to LLM

**Current behavior:** `_tool_chrome_screenshot` returns a text string (`"[CHROME] Screenshot captured (N bytes base64)"`). The LLM receives a description of the screenshot, not the image itself. Visual automation is blind.

**Fix:** Look at how `browser_pro.py` returns screenshots to the LLM (via the gateway's tool result handling). Mirror that pattern in `_tool_chrome_screenshot`. The base64 JPEG from the extension should be returned as an image result, not a text string. The gateway needs to see a response that it will render as an image in the Control Deck and pass visually to the LLM.

**Implementation:** Check how `browser_pro.py`'s `screenshot` tool result is structured, then have `_tool_chrome_screenshot` return the same shape. Likely involves returning a dict with a `type: image` or `image_b64` key that the gateway recognizes.

---

### Fix 2 — contenteditable typing fires real keyboard events

**Current behavior:** `performType()` in `content.js` sets `el.textContent = text` and fires only an `input` event. Modern SPAs (X.com, Notion, Reddit compose, Google Docs) listen for `keydown`/`keypress`/`keyup` events and ignore programmatic `textContent` assignments.

**Fix:** Replace the contenteditable path in `performType()`:

```javascript
// OLD (broken):
el.textContent = text;
el.dispatchEvent(new Event('input', { bubbles: true }));

// NEW (fires full event chain):
el.focus();
if (clear) {
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
}
document.execCommand('insertText', false, text);
// Fallback if execCommand unavailable:
// dispatch KeyboardEvent for each char with keydown/keypress/keyup
```

`document.execCommand('insertText')` triggers the complete event chain that X.com, Reddit, and similar apps require. Fallback: character-by-character `KeyboardEvent` dispatch.

---

## Section 2: New Tools

### 2.1 `chrome_zoom` — Region Screenshot

**Purpose:** Capture a cropped region of the screen for close inspection of small UI elements (icons, buttons, form fields). Equivalent to Claude's `computer: zoom` action.

**Extension command:** `zoom` with args `{region: [x0, y0, x1, y1]}`

**Implementation:** Take a full screenshot, then crop using `OffscreenCanvas` (available in MV3 service workers). Return the cropped JPEG as base64.

**Python tool:**
```python
"chrome_zoom": {
    "description": "Take a screenshot of a specific region for close inspection. region=[x0,y0,x1,y1] in pixels.",
    "parameters": {"region": {"type": "array", "description": "Bounding box [x0, y0, x1, y1]"}},
    "required": ["region"]
}
```

---

### 2.2 `chrome_drag` — Click-Drag

**Purpose:** Drag from one coordinate to another for drag-and-drop interactions, sliders, and reordering. Equivalent to Claude's `computer: left_click_drag`.

**Extension command:** `drag` with args `{start_x, start_y, end_x, end_y}`

**Implementation:** Inject into content script via `chrome.scripting.executeScript`. Dispatch `mousedown` at start, series of `mousemove` events, then `mouseup` at end.

**Python tool:**
```python
"chrome_drag": {
    "description": "Drag from one coordinate to another for drag-and-drop interactions.",
    "parameters": {"start_x", "start_y", "end_x", "end_y" (all number, required)}
}
```

---

### 2.3 `chrome_right_click` — Context Menu

**Purpose:** Right-click at a ref, selector, or coordinate to trigger context menus. Equivalent to Claude's `computer: right_click`.

**Extension command:** `right_click` with args `{ref, selector, x, y}`

**Implementation:** Dispatch `contextmenu` event at the target element via content script.

---

### 2.4 `chrome_upload` — File Upload

**Purpose:** Upload a local file to a `<input type="file">` element. Equivalent to Claude's `upload_image`.

**Extension command:** `upload_file` with args `{ref, selector, file_path}`

**Implementation:** Use Chrome debugger protocol `DOM.setFileInputFiles` command — this is the only way to programmatically set files on a file input in Chrome (the debugger API bypasses the security restriction). Requires the debugger to be attached to the tab (already done for console/network monitoring).

**Python tool:**
```python
"chrome_upload": {
    "description": "Upload a local file to a file input element. Use ref or selector to target the input.",
    "parameters": {"ref", "selector", "file_path" (required)}
}
```

---

### 2.5 `chrome_resize` — Viewport Resize

**Purpose:** Resize the browser viewport to test responsive layouts. Equivalent to Claude's `resize_window`.

**Extension command:** `resize_window` with args `{width, height, preset}`

**Presets:** `mobile` (375×812), `tablet` (768×1024), `desktop` (1280×800)

**Implementation:** Use Chrome debugger protocol `Emulation.setDeviceMetricsOverride`.

**Python tool:**
```python
"chrome_resize": {
    "description": "Resize the Chrome viewport. Presets: mobile (375×812), tablet (768×1024), desktop (1280×800).",
    "parameters": {"preset": "mobile|tablet|desktop", "width": number, "height": number}
}
```

---

### 2.6 `chrome_get_network_body` — Network Response Body

**Purpose:** Fetch the full response body for a captured network request by ID. Completes the two-step network inspection flow (list → inspect body). Equivalent to Claude's `preview_network` with requestId.

**Extension command:** `get_network_body` with args `{request_id}`

**Implementation:** Use Chrome debugger `Network.getResponseBody`. The `request_id` comes from the existing `chrome_read_network` output (update that tool to include IDs in its output).

Also update `chrome_read_network` to include `request_id` in each entry.

---

### 2.7 `chrome_triple_click` — Select All Text

**Purpose:** Triple-click to select all text in an input, textarea, or contenteditable. Useful before replacing content.

**Extension command:** `triple_click` with args `{ref, selector, x, y}`

**Implementation:** Dispatch three rapid click events at the target. content.js already has click logic; extend to support `click_count: 3`.

---

### 2.8 `chrome_wait` — Explicit Wait

**Purpose:** Wait N seconds between browser actions. Useful for page load settling, animations completing, or rate limiting.

**Implementation:** Python-side only — `asyncio.sleep(seconds)`. No extension command needed.

**Python tool:**
```python
"chrome_wait": {
    "description": "Wait for N seconds. Use to let pages load or animations settle.",
    "parameters": {"seconds": {"type": "number", "required": True}}
}
```

---

## Section 3: GIF Recorder

**Tools:** `chrome_gif_start`, `chrome_gif_stop`, `chrome_gif_export`

**Architecture:** Screenshot polling + Python-side GIF assembly.

The extension side takes screenshots at a configurable interval. The Python bridge collects frames in memory. On export, Pillow assembles the frames into an animated GIF with optional overlays.

### `chrome_gif_start`
- Starts screenshot polling at `fps` (default: 2) frames per second
- Stores frames in `self._gif_frames: list[bytes]` in `ChromeBridgeSkill`
- Background asyncio loop calls `screenshot()` and appends base64 frames
- Returns `{"status": "recording", "fps": 2}`

### `chrome_gif_stop`
- Sets `self._gif_recording = False` to stop the polling loop
- Keeps frames in memory
- Returns `{"status": "stopped", "frame_count": N}`

### `chrome_gif_export`
- Assembles frames using Pillow: `PIL.Image` + `PIL.ImageDraw`
- Optional overlays: click indicators (orange circles), action labels (black text), progress bar (orange bottom strip)
- Saves to `logs/recordings/<timestamp>.gif`
- Returns the file path (and optionally base64 for inline display)

**Dependency:** `Pillow` — check `requirements.txt`. If not present, add it (already used by the image generation pipeline).

**Quality setting:** default GIF quality = 10 (1=best, higher=smaller file). Configurable via `quality` parameter.

---

## Tool Count Summary

| Category | Before | After |
|---|---|---|
| Core interaction (fixed) | 16 | 16 (fixed) |
| New tools added | — | +11 |
| **Total** | **16** | **27** |

New tools: `chrome_zoom`, `chrome_drag`, `chrome_right_click`, `chrome_upload`, `chrome_resize`, `chrome_get_network_body`, `chrome_triple_click`, `chrome_wait`, `chrome_gif_start`, `chrome_gif_stop`, `chrome_gif_export`

---

## Version Bump

`ChromeBridgeSkill.version`: `"1.1.2"` → `"1.1.3"`

Update `FEATURES.md`, `README.md`, and `CHANGELOG.md` to reflect the new tool count and capabilities.

---

## Verification Checklist

- [ ] `chrome_type` works on X.com compose box (contenteditable fix)
- [ ] `chrome_screenshot` returns a visual image in the LLM response (not a text description)
- [ ] `chrome_zoom` returns a cropped region screenshot
- [ ] `chrome_drag` can drag a slider or reorder a list
- [ ] `chrome_right_click` opens a context menu
- [ ] `chrome_upload` sets a file on a `<input type="file">`
- [ ] `chrome_resize` changes the viewport to mobile/tablet/desktop
- [ ] `chrome_get_network_body` returns response body by request ID
- [ ] `chrome_gif_start` / `chrome_gif_stop` / `chrome_gif_export` produces a valid animated GIF
- [ ] All 27 tools listed in `chrome_bridge.py` `get_tools()`
- [ ] Version string updated to 1.1.3
