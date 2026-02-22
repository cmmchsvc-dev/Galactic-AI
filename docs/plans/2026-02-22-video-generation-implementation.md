# Video Generation + Scroll Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add text-to-video and image-to-video generation via Google Veo, with multi-provider architecture for future Runway/Kling/Luma support, plus fix scroll behavior in Chat/Logs/Thinking tabs.

**Architecture:** Two new gateway tools (`generate_video`, `generate_video_from_image`) using the existing `google-genai` SDK. Provider abstraction allows swapping backends via config. Control Deck gets `appendBotVideo()` for inline playback and `/api/video/` serving endpoint. Scroll fix changes `prepend()`/`insertBefore()` + `scrollTop=0` to `append()` + `scrollTop=scrollHeight`.

**Tech Stack:** Python 3, google-genai SDK (already installed), aiohttp, httpx, HTML5 `<video>`, JavaScript

---

## Task 1: Scroll Behavior Fix — Chat Tab

**Files:**
- Modify: `web_deck.py` — lines around 1657, 1723, 1737, 1772 (scrollTop=0), line 1726 (appendBotImage insertBefore), tab switch at lines 2940-2960

**Step 1: Fix chat message insertion order**

In `web_deck.py`, the chat currently uses `insertBefore()` to place messages relative to the stream bubble, and `scrollTop = 0` to show newest. Change all `scrollTop = 0` in chat context to `scrollTop = scrollHeight`:

Find every instance of:
```javascript
if (autoScroll) log.scrollTop = 0;
// and
if (autoScroll) document.getElementById('chat-log').scrollTop = 0;
```

Replace with:
```javascript
if (autoScroll) log.scrollTop = log.scrollHeight;
// and
if (autoScroll) { const _cl = document.getElementById('chat-log'); _cl.scrollTop = _cl.scrollHeight; }
```

**Step 2: Fix appendBotImage scroll**

In `appendBotImage()` (line ~1737), change:
```javascript
if (autoScroll) log.scrollTop = 0;
```
to:
```javascript
if (autoScroll) log.scrollTop = log.scrollHeight;
```

**Step 3: Fix tab switch — Chat**

In `switchTab()` (line ~2945), change:
```javascript
if (name === 'chat') {
    requestAnimationFrame(() => {
      const el = document.getElementById('chat-log');
      if (el) el.scrollTop = 0;
    });
  }
```
to:
```javascript
if (name === 'chat') {
    requestAnimationFrame(() => {
      const el = document.getElementById('chat-log');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
```

**Step 4: Add smart auto-scroll pause**

Add a scroll listener for chat-log that detects when the user has scrolled up manually. Add this JavaScript near the autoScroll variable initialization:

```javascript
// Smart auto-scroll: pause when user scrolls up, resume at bottom
document.getElementById('chat-log').addEventListener('scroll', function() {
  const el = this;
  const atBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 60;
  autoScroll = atBottom;
});
```

**Step 5: Verify and commit**

Run Galactic AI, open Control Deck, send a message. Confirm:
- New messages appear at bottom
- Page auto-scrolls to show them
- Scrolling up pauses auto-scroll
- Switching to another tab and back scrolls to bottom

```bash
git add web_deck.py
git commit -m "fix: chat tab scroll — new messages at bottom, smart auto-scroll"
```

---

## Task 2: Scroll Behavior Fix — Logs Tab

**Files:**
- Modify: `web_deck.py` — line ~2899 (prepend), line ~2900 (scrollTop=0), tab switch ~2950

**Step 1: Change log entry insertion from prepend to append**

Find (line ~2899):
```javascript
el.prepend(div);
```
Replace with:
```javascript
el.append(div);
```

**Step 2: Fix logs scrollTop**

Find (line ~2900):
```javascript
if (autoScroll) el.scrollTop = 0;
```
Replace with:
```javascript
if (autoScroll) el.scrollTop = el.scrollHeight;
```

**Step 3: Fix tab switch — Logs**

In `switchTab()`, change:
```javascript
if (name === 'logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('logs-scroll');
      if (el) el.scrollTop = 0;
    });
  }
```
to:
```javascript
if (name === 'logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('logs-scroll');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
```

**Step 4: Add smart auto-scroll for logs**

Add scroll listener for logs-scroll (similar to chat):

```javascript
document.getElementById('logs-scroll').addEventListener('scroll', function() {
  const atBottom = (this.scrollHeight - this.scrollTop - this.clientHeight) < 60;
  // Use a separate flag for logs auto-scroll
  this._autoScroll = atBottom;
});
```

Update the log append code to check `el._autoScroll !== false` instead of the global `autoScroll`.

**Step 5: Commit**

```bash
git add web_deck.py
git commit -m "fix: logs tab scroll — new entries at bottom, smart auto-scroll"
```

---

## Task 3: Scroll Behavior Fix — Thinking Tab

**Files:**
- Modify: `web_deck.py` — lines ~3023, 3041, 3054, 3074 (prepend), lines ~3025, 3061, 3142 (scrollTop=0), tab switch ~2955

**Step 1: Change thinking entry insertion from prepend to append**

Find all `prepend()` calls in the thinking tab rendering code (lines ~3023, 3041, 3054, 3074) and replace with `append()`.

**Step 2: Fix thinking scrollTop**

Find all instances of:
```javascript
if (traceAutoScroll) scroll.scrollTop = 0;
```
Replace with:
```javascript
if (traceAutoScroll) scroll.scrollTop = scroll.scrollHeight;
```

**Step 3: Fix tab switch — Thinking**

In `switchTab()`, change:
```javascript
if (name === 'thinking') {
    requestAnimationFrame(() => {
      const el = document.getElementById('thinking-scroll');
      if (el) el.scrollTop = 0;
    });
  }
```
to:
```javascript
if (name === 'thinking') {
    requestAnimationFrame(() => {
      const el = document.getElementById('thinking-scroll');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
```

**Step 4: Add smart auto-scroll for thinking**

```javascript
document.getElementById('thinking-scroll').addEventListener('scroll', function() {
  const atBottom = (this.scrollHeight - this.scrollTop - this.clientHeight) < 60;
  traceAutoScroll = atBottom;
});
```

**Step 5: Commit**

```bash
git add web_deck.py
git commit -m "fix: thinking tab scroll — new entries at bottom, smart auto-scroll"
```

---

## Task 4: Video Config + Storage Setup

**Files:**
- Modify: `config.yaml` (template) — add `video:` section and `tool_timeouts` entries
- Modify: `gateway_v2.py` — read video config in `__init__`

**Step 1: Add video config to template config.yaml**

Add after the `tool_timeouts` section:

```yaml
video:
  provider: google
  google:
    model: veo-3.1
    use_vertex: false
    default_duration: 8
    default_resolution: 1080p
    default_aspect_ratio: '16:9'
  runway:
    apiKey: ''
    model: gen4
  kling:
    apiKey: ''
  luma:
    apiKey: ''
```

Add to `tool_timeouts`:
```yaml
  generate_video: 300
  generate_video_from_image: 300
```

**Step 2: Add video config to running installation config.yaml**

Same additions to `F:\Galactic AI\config.yaml`.

**Step 3: Commit**

```bash
git add config.yaml
git commit -m "feat: add video generation config section"
```

---

## Task 5: Google Veo Provider — Text-to-Video

**Files:**
- Modify: `gateway_v2.py` — add `tool_generate_video()` function and tool registration

**Step 1: Register the tool**

Add to the `self.tools` dict (after `generate_image_imagen`):

```python
"generate_video": {
    "description": "Generate a short video clip using Google Veo AI. Returns the path to the saved MP4 file. Supports text-to-video generation with configurable duration, resolution, and aspect ratio.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt":          {"type": "string",  "description": "Scene description for the video"},
            "duration":        {"type": "integer", "description": "Video duration in seconds: 4, 6, or 8 (default: 8)"},
            "aspect_ratio":    {"type": "string",  "description": "Aspect ratio: 16:9 or 9:16 (default: 16:9)"},
            "resolution":      {"type": "string",  "description": "Resolution: 720p, 1080p, or 4k (default: 1080p)"},
            "negative_prompt": {"type": "string",  "description": "Things to avoid in the video (optional)"},
        },
        "required": ["prompt"]
    },
    "fn": self.tool_generate_video
},
```

**Step 2: Implement tool_generate_video()**

Add after `tool_generate_image_imagen()`:

```python
async def tool_generate_video(self, args):
    """Generate a video using Google Veo via the google-genai SDK."""
    import time as _time
    prompt = args.get('prompt', '')
    if not prompt:
        return "[ERROR] generate_video requires a 'prompt' argument."

    video_cfg = self.core.config.get('video', {}).get('google', {})
    duration = str(args.get('duration', video_cfg.get('default_duration', 8)))
    aspect_ratio = args.get('aspect_ratio', video_cfg.get('default_aspect_ratio', '16:9'))
    resolution = args.get('resolution', video_cfg.get('default_resolution', '1080p'))
    negative_prompt = args.get('negative_prompt', '')
    model_name = video_cfg.get('model', 'veo-3.1')

    # Map short model names to full IDs
    model_map = {
        'veo-2': 'veo-2-generate-preview',
        'veo-3': 'veo-3.0-generate-preview',
        'veo-3.1': 'veo-3.1-generate-preview',
    }
    model_id = model_map.get(model_name, model_name)

    google_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey', '')
    if not google_key:
        return "[ERROR] No google.apiKey found in config.yaml"

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=google_key)

        await self.core.log(f"🎬 Generating video with {model_id}...", priority=2)

        # Build config
        gen_config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration_seconds=duration,
        )
        if negative_prompt:
            gen_config.negative_prompt = negative_prompt

        # Start async generation
        operation = client.models.generate_videos(
            model=model_id,
            prompt=prompt,
            config=gen_config,
        )

        # Poll for completion
        poll_count = 0
        while not operation.done:
            poll_count += 1
            if poll_count % 6 == 0:  # Log every 60s
                await self.core.log(
                    f"🎬 Video still generating... ({poll_count * 10}s elapsed)",
                    priority=3
                )
            await asyncio.sleep(10)
            operation = client.operations.get(operation)

        if not operation.response or not operation.response.generated_videos:
            return "[ERROR] Video generation returned no results."

        # Download and save
        video = operation.response.generated_videos[0]
        client.files.download(file=video.video)

        images_dir = self.core.config.get('paths', {}).get('images', './images')
        vid_subdir = os.path.join(images_dir, 'video')
        os.makedirs(vid_subdir, exist_ok=True)
        fname = f"veo_{int(_time.time())}.mp4"
        path = os.path.join(vid_subdir, fname)
        video.video.save(path)

        # Signal delivery
        self.last_video_file = path
        return (
            f"✅ Video generated: {path}\n"
            f"Model: {model_id}\n"
            f"Duration: {duration}s | Resolution: {resolution} | Aspect: {aspect_ratio}\n"
            f"Prompt: {prompt}"
        )
    except Exception as e:
        return f"[ERROR] generate_video: {e}"
```

**Step 3: Commit**

```bash
git add gateway_v2.py
git commit -m "feat: add generate_video tool — Google Veo text-to-video"
```

---

## Task 6: Google Veo Provider — Image-to-Video

**Files:**
- Modify: `gateway_v2.py` — add `tool_generate_video_from_image()` and tool registration

**Step 1: Register the tool**

Add to `self.tools` dict:

```python
"generate_video_from_image": {
    "description": "Animate a still image into a short video clip using Google Veo. Takes an image (from Imagen, FLUX, or SD3.5) and turns it into motion video. Returns path to saved MP4.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt":       {"type": "string",  "description": "Description of the motion/animation to apply"},
            "image_path":   {"type": "string",  "description": "Path to the source image file"},
            "duration":     {"type": "integer", "description": "Video duration in seconds: 4, 6, or 8 (default: 8)"},
            "aspect_ratio": {"type": "string",  "description": "Aspect ratio: 16:9 or 9:16 (default: 16:9)"},
        },
        "required": ["prompt", "image_path"]
    },
    "fn": self.tool_generate_video_from_image
},
```

**Step 2: Implement tool_generate_video_from_image()**

```python
async def tool_generate_video_from_image(self, args):
    """Animate a still image into video using Google Veo."""
    import time as _time
    from PIL import Image as _PILImage

    prompt = args.get('prompt', '')
    image_path = args.get('image_path', '')
    if not prompt:
        return "[ERROR] generate_video_from_image requires a 'prompt' argument."
    if not image_path or not os.path.exists(image_path):
        return f"[ERROR] Image not found: {image_path}"

    video_cfg = self.core.config.get('video', {}).get('google', {})
    duration = str(args.get('duration', video_cfg.get('default_duration', 8)))
    aspect_ratio = args.get('aspect_ratio', video_cfg.get('default_aspect_ratio', '16:9'))
    model_name = video_cfg.get('model', 'veo-3.1')

    model_map = {
        'veo-2': 'veo-2-generate-preview',
        'veo-3': 'veo-3.0-generate-preview',
        'veo-3.1': 'veo-3.1-generate-preview',
    }
    model_id = model_map.get(model_name, model_name)

    google_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey', '')
    if not google_key:
        return "[ERROR] No google.apiKey found in config.yaml"

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=google_key)

        await self.core.log(f"🎬 Animating image to video with {model_id}...", priority=2)

        # Load image
        img = _PILImage.open(image_path)

        # Start generation with image as first frame
        operation = client.models.generate_videos(
            model=model_id,
            prompt=prompt,
            image=img,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                duration_seconds=duration,
            ),
        )

        # Poll for completion
        poll_count = 0
        while not operation.done:
            poll_count += 1
            if poll_count % 6 == 0:
                await self.core.log(
                    f"🎬 Video still generating... ({poll_count * 10}s elapsed)",
                    priority=3
                )
            await asyncio.sleep(10)
            operation = client.operations.get(operation)

        if not operation.response or not operation.response.generated_videos:
            return "[ERROR] Video generation returned no results."

        video = operation.response.generated_videos[0]
        client.files.download(file=video.video)

        images_dir = self.core.config.get('paths', {}).get('images', './images')
        vid_subdir = os.path.join(images_dir, 'video')
        os.makedirs(vid_subdir, exist_ok=True)
        fname = f"veo_{int(_time.time())}.mp4"
        path = os.path.join(vid_subdir, fname)
        video.video.save(path)

        self.last_video_file = path
        return (
            f"✅ Image animated to video: {path}\n"
            f"Model: {model_id}\n"
            f"Source: {image_path}\n"
            f"Duration: {duration}s | Aspect: {aspect_ratio}\n"
            f"Prompt: {prompt}"
        )
    except Exception as e:
        return f"[ERROR] generate_video_from_image: {e}"
```

**Step 3: Commit**

```bash
git add gateway_v2.py
git commit -m "feat: add generate_video_from_image tool — animate stills with Veo"
```

---

## Task 7: Control Deck — Video Serving Endpoint

**Files:**
- Modify: `web_deck.py` — add `/api/video/` route and handler

**Step 1: Register route**

Find where `/api/image/{filename}` is registered (line ~75) and add:

```python
self.app.router.add_get('/api/video/{filename}', self.handle_serve_video)
```

**Step 2: Implement handler**

Add near `handle_serve_image()`:

```python
async def handle_serve_video(self, request):
    """GET /api/video/{filename} — serve a generated video."""
    filename = request.match_info.get('filename', '')
    filename = os.path.basename(filename)  # security: no path traversal
    images_dir = self.core.config.get('paths', {}).get('images', './images')
    video_dir = os.path.join(images_dir, 'video')
    path = os.path.join(video_dir, filename)
    if not os.path.exists(path):
        return web.Response(status=404, text='Video not found')
    return web.FileResponse(path, headers={
        'Content-Type': 'video/mp4',
        'Cache-Control': 'public, max-age=86400',
    })
```

**Step 3: Add last_video_file tracking in handle_chat()**

Find the `last_image_file` handling block (line ~3439) and add video handling after it:

```python
# Video delivery (same pattern as image delivery)
video_file = getattr(self.core.gateway, 'last_video_file', None)
if video_file and os.path.exists(video_file):
    images_dir = os.path.abspath(
        self.core.config.get('paths', {}).get('images', './images')
    )
    abs_vid = os.path.abspath(video_file)
    fname = os.path.basename(video_file)
    resp_data['video_url'] = f'/api/video/{fname}'
    self.core.gateway.last_video_file = None
    await self.core.log(
        f"[Video Delivery] serving {fname}",
        priority=3
    )
```

**Step 4: Commit**

```bash
git add web_deck.py
git commit -m "feat: add /api/video/ endpoint + video delivery in handle_chat"
```

---

## Task 8: Control Deck — Inline Video Player

**Files:**
- Modify: `web_deck.py` — add `appendBotVideo()` JS function and client-side video handling

**Step 1: Add appendBotVideo() function**

Add after `appendBotImage()`:

```javascript
function appendBotVideo(url) {
  const log = document.getElementById('chat-log');
  const sb = document.getElementById('stream-bubble');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble" style="padding:8px">
    <video src="${url}" controls autoplay muted loop
           style="max-width:100%;max-height:512px;border-radius:8px;display:block"></video>
    <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
      <span style="font-size:0.75em;color:var(--dim)">🎬 Generated video</span>
      <a href="${url}" download style="font-size:0.75em;color:var(--cyan);text-decoration:none">⬇ Download MP4</a>
    </div>
  </div><div class="meta">Byte • ${fmtTime()}</div>`;
  log.insertBefore(div, sb.nextSibling);
  if (autoScroll) log.scrollTop = log.scrollHeight;
}
```

**Step 2: Add video_url handling in chat response**

Find where `image_url` is checked in the chat response handler (the client-side JS that processes the response from `/api/chat`). Add video handling:

```javascript
if (d.video_url) {
  appendBotVideo(d.video_url);
}
```

**Step 3: Commit**

```bash
git add web_deck.py
git commit -m "feat: inline video player in Control Deck chat"
```

---

## Task 9: Deploy + End-to-End Test

**Files:**
- Copy updated files to `F:\Galactic AI\`

**Step 1: Copy files to running installation**

```bash
cp "F:\Galactic AI Public Release\gateway_v2.py" "F:\Galactic AI\gateway_v2.py"
cp "F:\Galactic AI Public Release\web_deck.py" "F:\Galactic AI\web_deck.py"
cp "F:\Galactic AI Public Release\config.yaml" "F:\Galactic AI\config.yaml"
```

Note: Preserve the running installation's API keys — only copy the template config if the user hasn't customized their config yet. Otherwise, manually add the `video:` section and new `tool_timeouts` entries to the running config.

**Step 2: Restart and test scroll behavior**

- Open Control Deck Chat tab — messages should appear at bottom
- Open Logs tab — entries should appear at bottom
- Open Thinking tab — traces should appear at bottom
- Scroll up in any tab — auto-scroll should pause
- Scroll back down — auto-scroll should resume
- Switch tabs — should jump to bottom (newest content)

**Step 3: Test video generation**

In the chat, ask Byte: "Generate a short video of a sunset over the ocean"

Expected:
- Byte calls `generate_video` tool
- Log shows "Generating video with veo-3.1-generate-preview..."
- After 30-120s, video appears inline in chat with player controls
- Download button works
- Video file saved in `./images/video/veo_*.mp4`

**Step 4: Test image-to-video**

Ask Byte: "Generate an image of a mountain landscape, then animate it"

Expected:
- Byte calls `generate_image_imagen` first
- Image appears in chat
- Byte calls `generate_video_from_image` with the image path
- Animated video appears in chat

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: video generation v1.0 — Veo text-to-video + image-to-video + inline player"
```

---

## Future Tasks (Not in This Plan)

- **Vertex AI toggle** — switch `use_vertex: true` for video extension features
- **Runway Gen-4 provider** — requires Runway API key + REST implementation
- **Kling provider** — requires Kling API key + REST implementation
- **Luma provider** — requires Luma API key + REST implementation
- **Video Models page** — add video model cards to Control Deck Models tab
- **Video gallery** — browse generated videos in Control Deck
