# Galactic AI v1.0.9

## What's New

### Video Generation (Google Veo)
Generate AI video clips directly from the chat interface. Two new tools:

- **`generate_video`** — Describe a scene and Veo generates a video clip
  - Duration: 4s, 6s, or 8s
  - Resolution: 720p, 1080p, or 4K
  - Aspect ratio: 16:9 or 9:16
  - Negative prompts supported
- **`generate_video_from_image`** — Animate a still image into motion video
  - Works with images from Imagen, FLUX, SD3.5, or any file

Videos play inline in the Control Deck chat with an HTML5 player (controls, autoplay, loop) and a download link for saving the MP4.

Multi-provider architecture: Google Veo is the day-one provider, with config scaffolding for Runway Gen-4, Kling, and Luma Dream Machine.

### New NVIDIA Models
- **Nemotron Super 49B** (`nvidia/llama-3.3-nemotron-super-49b-v1.5`) — Large reasoning model
- **Nemotron Nano 9B v2** (`nvidia/nvidia-nemotron-nano-9b-v2`) — Compact thinking model
- **Phi-3 Medium** (`microsoft/phi-3-medium-4k-instruct`) — Microsoft's mid-size model
- **DeepSeek V3.2** — Now with thinking params enabled

All four have model cards in the Control Deck Models page.

---

## What's Fixed

### Chat/Logs/Thinking Scroll Behavior
All three tabs now use conventional bottom-up chat ordering — newest content appears at the bottom, just like Facebook Messenger.

**Root cause:** The stream-bubble (typing indicator) was the first child in the chat container. Every new message used `insertBefore(sb.nextSibling)` which placed it right after the stream-bubble at the top. The fix moves stream-bubble to the last position and inserts messages before it, naturally building chronological order.

Also fixed:
- Log filter was rendering in reverse (newest first)
- Log trim was removing the newest entry instead of the oldest

### NVIDIA Provider Hardening
- **Broken SSE workaround** — Qwen 3.5 397B (and other models with non-functional streaming) are auto-routed to non-streaming via the `_NVIDIA_NO_STREAM` set
- **Cold-start retry** — Large models that return HTTP 502/503/504 during GPU loading are retried up to 2 times with status messages
- **Streaming fallback** — If NVIDIA streaming returns empty, the system automatically retries non-streaming
- **Granular timeouts** — 30s connect + 600s read (was a single 300s timeout)

### HuggingFace URL Migration
Updated from deprecated `api-inference.huggingface.co/v1` to `router.huggingface.co/v1` in the gateway, web deck, and config template.

### Non-Streaming Response Hardening
HTTP status is now checked before JSON parsing, and empty response bodies are handled gracefully instead of throwing `Expecting value: line 1 column 1`.

### Bulletproof Shutdown
Added an 8-second hard-exit timer that guarantees the process terminates even if subsystems hang during shutdown. Proper shutdown_event chain prevents the old infinite-hang edge case.

---

## Updating

```powershell
.\update.ps1      # Windows
./update.sh       # Linux / macOS
```

Pin to this version:
```powershell
.\update.ps1 -Version v1.0.9   # Windows
./update.sh v1.0.9              # Linux / macOS
```

---

## Files Modified

| File | Changes |
|------|---------|
| `gateway_v2.py` | Video generation tools (`tool_generate_video`, `tool_generate_video_from_image`), tool registrations, `_NVIDIA_NO_STREAM` set, `_NVIDIA_THINKING_MODELS` updates, NVIDIA streaming fallback, cold-start retry, granular httpx timeouts, HuggingFace URL, non-streaming JSON hardening |
| `web_deck.py` | `/api/video/` route, `handle_serve_video()`, `appendBotVideo()` JS, video delivery tracking, scroll fix (stream-bubble position, `insertBefore(sb)`, log trim direction, filterLogs order), HuggingFace URL, new model cards (Nemotron Super 49B, Nano 9B, Phi-3 Medium) |
| `config.yaml` | `video:` section, `generate_video`/`generate_video_from_image` timeouts, version bump |
| `galactic_core_v2.py` | Bulletproof shutdown timer, shutdown_event chain |

---

## Previous Releases

- **v1.0.8**: Model persistence definitive fix, Imagen 4 safety filter, inline image diagnostics
- **v1.0.7**: Shutdown/restart buttons, Imagen 4 SDK migration, SD3.5 fix, SubAgent overhaul
- **v1.0.6**: VAULT/personality loading fix, smart routing misclassification, Telegram timeout
- **v1.0.5**: Agent loop resilience, anti-spin guardrails
- **v1.0.4**: Model selection persistence fix (initial attempt)
- **v0.9.3**: Settings tab, VAULT.md, voice selector, auto-update checker

---

**Full documentation:** [README.md](../../README.md) | [FEATURES.md](../../FEATURES.md) | [CHANGELOG.md](../../CHANGELOG.md)

**License:** MIT
