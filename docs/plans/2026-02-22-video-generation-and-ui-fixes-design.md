# Video Generation + Control Deck UI Fixes — Design Document

**Date:** 2026-02-22
**Author:** Chesley + Claude
**Status:** Approved

---

## 1. Overview

Two features for Galactic AI v1.1.0:

1. **Video generation** — text-to-video and image-to-video via multi-provider architecture (Google Veo day-one, with Runway Gen-4, Kling, and Luma Dream Machine planned)
2. **Scroll behavior fix** — Chat, Logs, and Thinking tabs flip to standard bottom-up chat behavior

---

## 2. Video Generation

### 2.1 Architecture

Multi-provider abstraction, same pattern as LLM provider routing:

```
User prompt --> tool_generate_video() --> VideoProvider router
                                            |-- GoogleVeoProvider (Gemini API -- day one)
                                            |-- GoogleVeoVertexProvider (Vertex AI -- upgrade)
                                            |-- RunwayProvider (Gen-4 -- future)
                                            |-- KlingProvider (Kuaishou -- future)
                                            '-- LumaProvider (Dream Machine -- future)
```

### 2.2 Config Structure

New `video:` section in `config.yaml`:

```yaml
video:
  provider: google
  google:
    model: veo-3.1
    use_vertex: false
    default_duration: 8
    default_resolution: 1080p
    default_aspect_ratio: "16:9"
  runway:
    apiKey: ""
    model: gen4
  kling:
    apiKey: ""
  luma:
    apiKey: ""
```

### 2.3 Tool Interface

Two new tools registered in the gateway ReAct tool list:

**`generate_video`** — Text-to-video

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| prompt | string | yes | — | Scene description |
| provider | string | no | config default | google, runway, kling, luma |
| duration | int | no | 8 | Seconds: 4, 6, or 8 |
| aspect_ratio | string | no | 16:9 | 16:9 or 9:16 |
| resolution | string | no | 1080p | 720p, 1080p, 4k |
| negative_prompt | string | no | — | What to exclude |

**`generate_video_from_image`** — Image-to-video

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| prompt | string | yes | — | Motion/animation description |
| image_path | string | yes | — | Path to source image |
| provider | string | no | config default | google, runway, kling, luma |
| duration | int | no | 8 | Seconds: 4, 6, or 8 |

### 2.4 Async Flow

Video generation takes 30-120+ seconds:

1. Tool called -> sends request to provider API
2. Logs "Generating video..." status message visible in chat
3. Polls every 10s for completion (async, non-blocking)
4. On completion -> saves to `./images/video/{provider}_{timestamp}.mp4`
5. Returns path -> Control Deck renders inline video player + download button

### 2.5 Google Veo Implementation (Day One)

Uses existing `google-genai` SDK and Google API key:

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=google_key)

# Text-to-video
operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=prompt,
    config=types.GenerateVideosConfig(
        aspect_ratio="16:9",
        resolution="1080p",
        duration_seconds="8",
        negative_prompt=negative_prompt,
    ),
)

# Poll for completion
while not operation.done:
    await asyncio.sleep(10)
    operation = client.operations.get(operation)

# Save result
video = operation.response.generated_videos[0]
client.files.download(file=video.video)
video.video.save(output_path)
```

Image-to-video uses the same API with an `image=` parameter.

### 2.6 Vertex AI Upgrade Path

When `video.google.use_vertex: true`:
- Uses Vertex AI authentication (service account or ADC)
- Unlocks video extension (chain clips into 60s+ videos)
- Unlocks scene chaining and advanced features
- Same tool interface, different backend path

### 2.7 Future Providers

Runway, Kling, and Luma each have their own REST APIs. The provider abstraction allows adding them without changing the tool interface. Each provider implements:
- `generate_from_text(prompt, config) -> video_path`
- `generate_from_image(prompt, image_path, config) -> video_path`

---

## 3. Control Deck Video UI

### 3.1 Inline Player

When video generation completes, chat renders an HTML5 video player:

- `<video>` tag with `controls`, `autoplay`, `muted`, `loop`
- Metadata line below: duration, resolution, aspect ratio, model name
- Download button: direct link to the MP4 file
- New `appendBotVideo()` JS function (mirrors `appendBotImage()`)

### 3.2 Backend Serving

- Video files served from `/api/video/<filename>` endpoint
- Proper `Content-Type: video/mp4` header
- `last_video_file` tracked alongside `last_image_file` in handle_chat()

### 3.3 File Storage

- Directory: `./images/video/`
- Naming: `{provider}_{timestamp}.mp4` (e.g., `veo_1740268800.mp4`)
- No auto-cleanup (same policy as images)

---

## 4. Scroll Behavior Fix

### 4.1 Affected Tabs

Chat, Logs, Thinking — all three.

### 4.2 Current Behavior (Broken)

New content appears at the top (reverse chronological). Uses `prepend()` or `flex-direction: column-reverse`.

### 4.3 New Behavior (Standard Chat)

- New messages/entries append at the **bottom**
- Auto-scroll to bottom when new content arrives
- On tab open/switch: scroll to bottom (show newest data)
- Smart pause: if user scrolls up manually, auto-scroll pauses
- Auto-scroll resumes when user scrolls back near bottom (within ~50px)

### 4.4 Implementation

- Remove `flex-direction: column-reverse` and `prepend()` patterns
- Use `append()` + `scrollTop = scrollHeight` for new content
- Scroll listener: check if user is near bottom before auto-scrolling
- Tab switch handler: always `scrollTop = scrollHeight`

---

## 5. Error Handling

### 5.1 Video Generation Errors

| Error | Handling |
|-------|----------|
| Provider API error | Log + return `[ERROR] video: {message}` |
| Generation timeout | Configurable `tool_timeouts.generate_video: 300` |
| Polling failure | Retry poll 3x, then return error |
| Quota exhausted | Clear message: "Video quota exceeded for {provider}" |

### 5.2 Image-to-Video Edge Cases

| Case | Handling |
|------|----------|
| Source image doesn't exist | Validate path before API call |
| Unsupported format | Convert to PNG/JPEG before sending |
| Image still generating | Wait for `last_image_file` to be set |

---

## 6. Config Additions

### config.yaml

```yaml
video:
  provider: google
  google:
    model: veo-3.1
    use_vertex: false
    default_duration: 8
    default_resolution: 1080p
    default_aspect_ratio: "16:9"
  runway:
    apiKey: ""
    model: gen4
  kling:
    apiKey: ""
  luma:
    apiKey: ""

tool_timeouts:
  generate_video: 300
  generate_video_from_image: 300
```

---

## 7. Files Modified

| File | Changes |
|------|---------|
| `gateway_v2.py` | Add `tool_generate_video()`, `tool_generate_video_from_image()`, tool registration, provider abstraction |
| `web_deck.py` | Add `appendBotVideo()`, `/api/video/` endpoint, `last_video_file` tracking, scroll behavior fix for Chat/Logs/Thinking |
| `config.yaml` | Add `video:` section, `tool_timeouts.generate_video` |

---

## 8. Implementation Order

1. Scroll behavior fix (quick win, improves daily UX immediately)
2. Video config + storage setup
3. Google Veo provider (text-to-video)
4. Image-to-video support
5. Control Deck video player UI
6. Vertex AI toggle
7. Runway/Kling/Luma providers (future PRs)
