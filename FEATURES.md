# Galactic AI — Feature Reference

Complete feature reference for Galactic AI Automation Suite **v1.1.4**.

---

## Core Architecture

### AsyncIO Runtime
The entire system runs on Python's `asyncio` event loop. Every subsystem — LLM gateway, web server, Telegram bridge, Discord bridge, WhatsApp bridge, Gmail bridge, plugin engine, Ollama manager, task scheduler — is fully non-blocking. Nothing stalls the core.

### Strategic Planning Phase
Before diving into the execution loop for complex queries, the gateway initiates a pre-planning phase. It utilizes a highly capable LLM (like Gemini via the `gemini_code` tool) to break down the task into concrete steps, stores this plan in long-term memory, and guides the ReAct loop step-by-step.

### ReAct Agentic Loop
The AI operates in a **Think → Act → Observe → Answer** loop. It chains multiple tool calls in sequence, observes results, reasons about what to do next, and keeps going until the task is complete. Each tool call has a configurable timeout (default 60 seconds) — no single operation can block the loop indefinitely. The entire ReAct loop is capped by a speak() wall-clock timeout (default 600 seconds).

### Per-Tool Timeout
Every tool execution is wrapped in a configurable `asyncio.wait_for` timeout (defaults: shell 120s, Python 60s, image generation 180s). If a tool hangs (e.g. a browser operation on a slow page), it is cancelled with a descriptive error message and the AI continues to the next step. Configure per-tool timeouts in `config.yaml` under `tool_timeouts`.

### Graceful Lifecycle Management
- Single **Ctrl+C** triggers a clean shutdown of all subsystems
- Signal handlers for SIGINT and SIGTERM on all platforms
- All background tasks cancelled and awaited with a 5-second timeout
- Browser closes with a 3-second timeout
- Bulletproof 8-second hard-exit timer prevents infinite hang on shutdown
- Proper shutdown event chain across all subsystems
- `os._exit(0)` force-exit fallback for edge cases that refuse to terminate
- Relay message queue uses a 2-second poll timeout so it wakes up to check the shutdown flag

---

---

## Skills Ecosystem

### GalacticSkill Base Class
Every capability in Galactic AI is a `GalacticSkill` subclass. Skills declare structured metadata and register their tools dynamically via `get_tools()`. This replaces the hardcoded plugin list and moves tool definitions out of the gateway.

**Metadata fields:** `skill_name`, `version`, `author`, `description`, `category`, `icon`, `is_core`

**Lifecycle hooks:** `on_load()`, `on_unload()`, `run()` (background loop)

### Core Skills
Six built-in skills ship with Galactic AI:

| Skill | Tools | Description |
|-------|-------|-------------|
| ShellSkill | 1 | PowerShell/bash command execution |
| DesktopSkill | 8 | Mouse, keyboard, screenshot via pyautogui |
| ChromeBridgeSkill | 27 | Real Chrome browser control via WebSocket extension |
| SocialMediaSkill | 6 | Twitter/X and Reddit integration |
| SubAgentSkill | 2 | Spawn and monitor parallel AI subagents |
| BrowserProSkill | 55 | Full Playwright browser automation |

### AI Self-Authoring
Byte can create new skills at runtime using three meta-tools:

- **`create_skill(name, code, description)`** — Validates Python via AST, writes to `skills/community/<name>.py`, dynamically imports and loads the skill, registers all its tools immediately. No restart required.
- **`list_skills()`** — Returns all loaded skills with full metadata and tool lists.
- **`remove_skill(name)`** — Safely unloads a community skill and deletes its file.

Community skills persist across restarts via `skills/registry.json`.

### Skills Tab
The Control Deck's Skills tab displays all loaded skills as rich cards with: icon, display name, CORE/COMMUNITY badge, version, author, description, and a tool count preview. Toggle skills on/off without restarting.

## True Persistent Memory

### How It Works
Galactic AI uses a three-layer memory architecture:

**Layer 1: Identity Files (always injected into every prompt)**
- `IDENTITY.md` — AI name, role, vibe
- `SOUL.md` — core values and personality style
- `USER.md` — information about the user
- `MEMORY.md` — things the AI has learned across sessions
- `VAULT.md` — private credentials and personal data for automation tasks

All five are read from disk on startup and included in every system prompt. Zero extra API calls. Cost is proportional only to the size of the files.

**Layer 2: MEMORY.md Auto-Writing (grows over time)**
When the AI calls `memory_imprint`, it:
1. Writes to `memory_aura.json` (searchable store)
2. Appends a timestamped entry to `MEMORY.md` on disk
3. Hot-reloads the personality so the very next message sees the new memory

The result: the AI builds its own persistent knowledge file automatically. You can edit it in the Memory tab of the Control Deck.

**Layer 3: memory_aura.json (searchable knowledge base)**
A local JSON index for storing arbitrary facts, documents, and imprinted knowledge. Searchable via the `memory_search` tool using keyword matching. Survives restarts.

**Layer 4: ChromaDB Vector Memory (Semantic Search)**
Provided by the `memory_manager` community skill. This layer uses ChromaDB to store text and metadata as embeddings, allowing the AI to perform true semantic searches over its past experiences, research, and generated plans. This provides a massive, queryable long-term context that goes beyond simple keyword matching.

### Token Efficiency
MEMORY.md is loaded once at startup. There is no per-message search, no embedding API call, no vector DB overhead. You only pay for what's actually in the file.

---

### Restart Resilience (Conversation Recall)
Two community skills reduce "amnesia" after restarts without running heavy retrieval on every message:

- **Auto-Recall Injection** — `skills/community/conversation_auto_recall.py`
  - Runtime-patches `GalacticGateway.speak()`.
  - Triggers when the user asks remember/earlier/last time questions.
  - Tool: `conversation_auto_recall_status`

- **Boot Recall Banner** — `skills/community/boot_recall_banner.py`
  - Prints the last N hot-buffer messages at boot and writes: `logs/conversations/boot_recall_banner.txt`
  - Config: `conversation.boot_recall_messages: 10`
  - Tool: `boot_recall_show`

---


## 14 AI Providers

Switch between providers at any time from the web UI or Telegram.

| Provider | Auth | Free Tier |
|---|---|---|
| **Google Gemini** | API key | Yes (generous) |
| **Anthropic Claude** | API key | No |
| **OpenAI** | API key | No |
| **xAI Grok** | API key | No |
| **Groq** | API key | Yes (fast) |
| **Mistral** | API key | Yes |
| **NVIDIA AI** | API key(s) | Yes |
| **DeepSeek** | API key | Yes |
| **Cerebras** | API key | Yes |
| **OpenRouter** | API key | Yes (unified) |
| **HuggingFace** | API key | Yes |
| **Together AI** | API key | Yes |
| **Perplexity** | API key | No |
| **Ollama (Local)** | None | Free forever |

### OpenRouter Curated Models (26)
26 hand-picked models across 3 performance tiers available via OpenRouter: **Frontier** (7) — Gemini 3.1 Pro, Claude Opus 4.6, GPT-5.2, GPT-5.2 Codex, Grok 4.1 Fast, DeepSeek V3.2, Qwen 3.5 Plus. **Strong** (12) — Gemini 3 Pro/Flash, Claude Sonnet 4.6, Claude Opus 4.5, GPT-5.2 Pro, GPT-5.1, GPT-5.1 Codex, Qwen 3.5 397B, Qwen 3 Coder Next, Kimi K2.5, DeepSeek V3.2 Speciale, GLM-5. **Fast** (7) — Mistral Large, Devstral, MiniMax M2.5, Sonar Pro Search, Nemotron Nano 30B, Step 3.5 Flash, GPT-5.2 Chat.

### Multi-Key NVIDIA Routing
NVIDIA hosts models from many vendors. Galactic AI routes to the correct API key based on the model selected. Configure separate keys for DeepSeek, Qwen, GLM, Kimi, StepFun, and FLUX models.

### Smart Model Routing
Enable `smart_routing: true` in config to auto-select the best model for each task type (coding, reasoning, creative, vision, quick queries).

### Auto-Fallback & Resilient Fallback Chain
If the primary provider fails, the system falls back to a secondary provider automatically with error-type-specific cooldowns (rate limit: 60s, server error: 30s, timeout: 10s, auth error: 24h, quota exhausted: 1h). Recovery is automatic — the system periodically retests failed providers and restores them when healthy. Toggle auto-fallback on/off from the Settings tab in the Control Deck.

### Streaming Responses
Token-by-token streaming from all providers, broadcast to the web UI via WebSocket in real-time.

### Token Cost Tracking
Real-time cost monitoring with persistent logging. Every API call records model, provider, input/output token counts, and calculated USD cost to `logs/cost_log.jsonl`. The CostTracker provides session, daily, weekly, and monthly aggregation with per-model breakdowns. 33 models have exact pricing; unknown models use a conservative fallback rate. Free providers (NVIDIA, Cerebras, Groq, HuggingFace, Ollama) are tracked for usage but excluded from spend totals. Costs auto-prune after 90 days.

### NVIDIA Provider Hardening
- **Broken SSE workaround** — models with non-functional streaming endpoints (e.g., Qwen 3.5 397B) are automatically routed to non-streaming mode
- **Cold-start retry** — large models that return HTTP 502/503/504 during cold-start are automatically retried up to 2 times with status logging
- **Streaming fallback** — if NVIDIA streaming returns empty data, the system automatically retries with non-streaming
- **Granular timeouts** — 30s connect, 600s read for large NVIDIA models
- **Thinking model params** — per-model extra body parameters for reasoning models (DeepSeek V3.2, Nemotron Nano 9B v2, Qwen 3.5, GLM5, Kimi K2.5)

---

## Ollama Local Model Support

### Auto-Discovery
All models installed in Ollama are detected automatically. Pull a model with `ollama pull` and it appears in the UI within 60 seconds. No manual config.

### Health Monitoring
Background health checks track when Ollama goes online or offline. The web UI shows real-time Ollama health status.

### Context Window Awareness
The actual context window size is queried from Ollama for every model. Conversation history is trimmed accordingly.

### Tool Calling for Local Models
Ollama models get enhanced system prompts with full parameter schemas for all 110+ tools, plus few-shot examples for reliable JSON tool call generation. Temperature tuned to 0.3 for consistent structured output.

---

## VAULT — Personal Data for Automation

`VAULT.md` is a private credentials file loaded into every system prompt. It enables the AI to log into services, fill forms, and automate tasks using your personal information.

### How It Works
1. Copy `VAULT-example.md` to `VAULT.md`
2. Add your credentials (email, API tokens, personal info, payment details)
3. The `personality.py` loader reads VAULT.md and injects it with instructions to never share or expose the contents
4. The AI can reference these values when performing automation tasks

### Security
- Gitignored — never committed to the repository
- Protected by the auto-updater — `update.ps1` / `update.sh` never overwrite VAULT.md
- Editable in the Memory tab of the Control Deck
- The AI receives explicit instructions to use VAULT data for automation only and never expose it

---

## GitHub Auto-Update Checker

Galactic AI automatically checks GitHub for new releases on startup (after a 15-second boot delay) and then every 6 hours.

### How It Works
1. Queries `https://api.github.com/repos/cmmchsvc-dev/Galactic-AI/releases/latest`
2. Compares the latest release tag against the current `system.version` in config.yaml
3. If a newer version exists, broadcasts an `update_available` event via the WebSocket relay
4. The Control Deck shows a persistent dismissible banner and a 30-second toast notification
5. Instructions to run `./update.ps1` or `./update.sh` are included in the notification

### Configuration
```yaml
system:
  update_check_interval: 21600  # 6 hours in seconds (0 = disabled)
```

---

## 110+ Built-In Tools

### File System (7 tools)
| Tool | Description |
|---|---|
| `read_file` | Read the contents of any file |
| `write_file` | Write or create a file |
| `edit_file` | Make targeted edits (find/replace) |
| `list_dir` | Rich directory listing with sizes, dates, and type info |
| `find_files` | Recursive glob file finder |
| `hash_file` | SHA256/MD5/SHA1 checksum of any file |
| `diff_files` | Unified diff between two files or a file and text |

### Shell & Process (6 tools)
| Tool | Description |
|---|---|
| `exec_shell` | Execute any shell command |
| `process_start` | Start a long-running background process |
| `process_status` | Check status of running processes |
| `process_kill` | Terminate a process |
| `schedule_task` | Schedule a recurring or one-shot task |
| `list_tasks` | View all scheduled tasks |

### Archives (2 tools)
| Tool | Description |
|---|---|
| `zip_create` | Create ZIP archives from files or directories |
| `zip_extract` | Extract ZIP archives |

### Web & Search (2 tools)
| Tool | Description |
|---|---|
| `web_search` | Search DuckDuckGo (no API key needed) |
| `web_fetch` | Fetch and parse any URL |

### HTTP (1 tool)
| Tool | Description |
|---|---|
| `http_request` | Raw HTTP GET/POST/PUT/DELETE/PATCH to any URL with custom headers |

### Vision (2 tools)
| Tool | Description |
|---|---|
| `analyze_image` | Analyze images using Gemini Vision, Ollama multimodal, or other providers |
| `image_info` | Get image dimensions and format without AI analysis |

### Image Generation (6 tools)
| Tool | Description |
|---|---|
| `generate_image` | Generate an image with the currently selected image model |
| `generate_image_flux` | Generate with FLUX.1 Schnell via NVIDIA NIM |
| `generate_image_flux_dev` | Generate with FLUX.1 Dev via NVIDIA NIM |
| `generate_image_sd35` | Generate with Stable Diffusion 3.5 Large via NVIDIA NIM |
| `generate_image_gemini` | Generate with Google Imagen 4 via Gemini API |
| `generate_image_gemini_ultra` | Generate with Google Imagen 4 Ultra via Gemini API |

### Video Generation (2 tools)
| Tool | Description |
|---|---|
| `generate_video` | Generate a video clip from a text prompt using Google Veo (4s/6s/8s, up to 4K) |
| `generate_video_from_image` | Animate a still image into a video clip using Google Veo |

### Memory (4 tools)
| Tool | Description |
|---|---|
| `memory_search` | Keyword search across persistent memory |
| `memory_imprint` | Store new information — writes to memory_aura.json AND MEMORY.md |

### Audio (1 tool)
| Tool | Description |
|---|---|
| `text_to_speech` | Convert text to speech via ElevenLabs, OpenAI TTS, edge-tts, or free gTTS |

### Clipboard (2 tools)
| Tool | Description |
|---|---|
| `clipboard_get` | Read OS clipboard (Windows/macOS/Linux) |
| `clipboard_set` | Write text to clipboard |

### Notifications (1 tool)
| Tool | Description |
|---|---|
| `notify` | Desktop toast/balloon notifications (Windows/macOS/Linux) |

### Window Management (3 tools)
| Tool | Description |
|---|---|
| `window_list` | List all open application windows |
| `window_focus` | Bring any window to the foreground |
| `window_resize` | Move and resize any application window |

### System (4 tools)
| Tool | Description |
|---|---|
| `system_info` | CPU, RAM, disk, uptime, process count |
| `kill_process_by_name` | Kill processes by name |
| `env_get` | Read environment variables |
| `env_set` | Write environment variables |

### Utilities (3 tools)
| Tool | Description |
|---|---|
| `qr_generate` | Generate QR code images |
| `color_pick` | Sample pixel color at screen coordinates |
| `text_transform` | 15 text operations: case convert, base64, URL encode/decode, regex, JSON format, CSV→JSON, word count, and more |

### Desktop Automation (via DesktopTool plugin)
| Tool | Description |
|---|---|
| `desktop_screenshot` | Full-screen screenshot |
| `desktop_click` | Click at screen coordinates |
| `desktop_type` | Type text at current cursor position |
| `desktop_key` | Press keyboard shortcuts |
| `desktop_move` | Move mouse to coordinates |
| `desktop_scroll` | Scroll at coordinates |
| `desktop_locate` | Find an image on screen using template matching |
| `desktop_drag` | Drag from one coordinate to another |

### Browser Automation (56 tools)

Powered by Playwright. Supports **Chromium**, **Firefox**, and **WebKit** engines.

**Navigation & Pages**
| Tool | Description |
|---|---|
| `open_browser` | Navigate to a URL |
| `browser_search` | Search Google |
| `browser_new_tab` | Open a new tab |
| `screenshot` | Take a full-page screenshot |
| `browser_snapshot` | Get accessibility tree of the page |
| `browser_pdf` | Save page as PDF |

**Interaction — By Selector**
| Tool | Description |
|---|---|
| `browser_click` | Click an element by CSS selector |
| `browser_type` | Type text into an element |
| `browser_fill_form` | Fill multiple form fields at once |
| `browser_select` | Select a dropdown option |
| `browser_hover` | Hover over an element |
| `browser_scroll_into_view` | Scroll element into viewport |
| `browser_drag` | Drag and drop |
| `browser_highlight` | Highlight an element |
| `browser_download` | Download a file by clicking a selector |
| `browser_upload` | Upload a file to an input element |

**Interaction — By Accessibility Ref**
| Tool | Description |
|---|---|
| `browser_click_by_ref` | Click element by accessibility ref ID |
| `browser_type_by_ref` | Type into element by ref ID |
| `browser_select_by_ref` | Select dropdown by ref ID |
| `browser_hover_by_ref` | Hover by ref ID |
| `browser_scroll_into_view_by_ref` | Scroll into view by ref ID |
| `browser_drag_by_ref` | Drag and drop by ref ID |
| `browser_highlight_by_ref` | Highlight by ref ID |
| `browser_download_by_ref` | Download by ref ID |

**Interaction — By Coordinates**
| Tool | Description |
|---|---|
| `browser_click_coords` | Click at exact x,y coordinates |
| `browser_scroll` | Scroll the page (up, down, left, right) |
| `browser_press` | Press keyboard keys |
| `browser_resize` | Resize the browser window |

**Data Extraction**
| Tool | Description |
|---|---|
| `browser_extract` | Extract structured data from the page |
| `browser_execute_js` | Run arbitrary JavaScript |
| `browser_console_logs` | Read browser console output |
| `browser_page_errors` | Get JavaScript errors |
| `browser_network_requests` | Inspect network traffic |
| `browser_response_body` | Get the response body of a network request |

**Storage**
| Tool | Description |
|---|---|
| `browser_get_local_storage` | Read localStorage values |
| `browser_set_local_storage` | Write localStorage values |
| `browser_clear_local_storage` | Clear all localStorage |
| `browser_get_session_storage` | Read sessionStorage values |
| `browser_set_session_storage` | Write sessionStorage values |
| `browser_clear_session_storage` | Clear all sessionStorage |

**Advanced Browser Control**
| Tool | Description |
|---|---|
| `browser_wait` | Wait for elements, navigation, or timeouts |
| `browser_dialog` | Handle browser dialogs (alert, confirm, prompt) |
| `browser_set_offline` | Simulate offline/online network conditions |
| `browser_set_headers` | Set custom HTTP headers |
| `browser_set_geolocation` | Spoof GPS coordinates |
| `browser_clear_geolocation` | Clear geolocation override |
| `browser_emulate_media` | Emulate media features (dark mode, print) |
| `browser_set_locale` | Change browser locale |
| `browser_set_proxy` | Route traffic through a proxy |

**Frames**
| Tool | Description |
|---|---|
| `browser_get_frames` | List all iframes on the page |
| `browser_frame_action` | Execute actions inside a specific iframe |

**Session Management**
| Tool | Description |
|---|---|
| `browser_save_session` | Save cookies and storage state to a file |
| `browser_load_session` | Restore a saved session |

**Tracing & Debugging**
| Tool | Description |
|---|---|
| `browser_trace_start` | Start recording a Playwright trace |
| `browser_trace_stop` | Stop recording and save trace file |

**Network Interception**
| Tool | Description |
|---|---|
| `browser_intercept` | Intercept and modify network requests |
| `browser_clear_intercept` | Remove all network intercepts |

---

### Chrome Browser Tools (27 tools — via Galactic Browser extension)

Control the user's real Chrome browser through the Galactic Browser extension. Requires the Chrome extension to be loaded and connected.

| Tool | Description |
|---|---|
| `chrome_navigate` | Navigate the user's Chrome browser to a URL, or use 'back'/'forward' for history |
| `chrome_read_page` | Get accessibility tree snapshot of the current page (roles, names, ref IDs) |
| `chrome_screenshot` | Take a JPEG screenshot of the active tab |
| `chrome_zoom` | Region screenshot for close inspection of UI elements |
| `chrome_click` | Click an element by CSS selector or accessibility ref ID |
| `chrome_find` | Find elements using natural language queries (e.g., "login button", "search bar") |
| `chrome_execute_js` | Execute JavaScript in the page context |
| `chrome_tabs_list` | List all open Chrome tabs with titles and URLs |
| `chrome_form_input` | Fill form elements (inputs, selects, checkboxes) by ref ID |
| `chrome_get_page_text` | Extract raw text content from the page, prioritizing article content |
| `chrome_scroll_to` | Scroll an element into view by ref ID |
| `chrome_drag` | Click-drag interactions (sliders, reordering) |
| `chrome_right_click` | JS context menu trigger |
| `chrome_triple_click` | Triple-click to select all text in an element |
| `chrome_upload` | File upload via Chrome Debugger `DOM.setFileInputFiles` |
| `chrome_resize` | Viewport resize with mobile/tablet/desktop presets |
| `chrome_read_network` | List network requests with URL, method, status, and request_id per entry |
| `chrome_get_network_body` | Fetch full response body for a network request by request_id |
| `chrome_wait` | Wait N seconds between browser actions |
| `chrome_gif_start` | Start recording browser actions as an animated GIF |
| `chrome_gif_stop` | Stop GIF recording |
| `chrome_gif_export` | Export and assemble the recorded GIF using Pillow |

### Social Media (8 tools — via SocialMediaPlugin)

Post, search, and manage Twitter/X and Reddit directly through the AI.

**Twitter/X (via Tweepy)**
| Tool | Description |
|---|---|
| `twitter_post` | Post a tweet to your timeline |
| `twitter_reply` | Reply to a specific tweet by ID |
| `twitter_search` | Search Twitter for recent tweets matching a query |
| `twitter_mentions` | Get recent mentions and notifications |

**Reddit (via PRAW)**
| Tool | Description |
|---|---|
| `reddit_post` | Submit a post to a subreddit (text or link) |
| `reddit_comment` | Reply to a Reddit post or comment |
| `reddit_search` | Search a subreddit for posts matching a query |
| `reddit_inbox` | Read your Reddit inbox (unread messages and comment replies) |

---

## Image Generation

Galactic AI supports six image generation backends. The active image model is set per-session and persists across messages.

| Model | Tool | Speed | Quality |
|---|---|---|---|
| Imagen 4 Ultra | `generate_image_gemini_ultra` | Slow | Best |
| Imagen 4 | `generate_image_gemini` | Medium | High |
| FLUX.1 Dev | `generate_image_flux_dev` | Medium | Excellent detail |
| Imagen 4 Fast | `generate_image_gemini` (fast) | Fast | Good |
| FLUX.1 Schnell | `generate_image_flux` | Fastest | Good |
| SD 3.5 Large | `generate_image_sd35` | Medium | Versatile |

**FLUX Auto-Generate:** When FLUX is set as the active model, typing any prompt automatically generates an image.

**Telegram Image Model Selector:** Use `/model` → Image Models to pick your preferred generation backend directly from Telegram. The preference is stored for the session.

---

## Video Generation

Generate AI video clips directly from the chat interface using Google Veo.

### Text-to-Video
Describe a scene and Veo generates a short video clip. Configurable duration (4s, 6s, 8s), resolution (720p, 1080p, 4K), aspect ratio (16:9, 9:16), and negative prompts.

### Image-to-Video
Animate any still image (from Imagen, FLUX, SD3.5, or any file) into motion video. The AI generates the image first, then animates it — a complete creative pipeline.

### Inline Playback
Videos appear inline in the Control Deck chat as HTML5 `<video>` elements with controls, autoplay, muted loop, and a download link for saving the MP4 locally.

### Multi-Provider Architecture
Google Veo is the day-one provider. The `video:` config section supports Runway Gen-4, Kling, and Luma Dream Machine as future backends.

### Models
| Model | API ID | Features |
|---|---|---|
| Veo 3.1 (default) | `veo-3.1-generate-preview` | Latest, highest quality |
| Veo 3 | `veo-3.0-generate-preview` | High quality |
| Veo 2 | `veo-2-generate-preview` | Stable, fast |

### Configuration
```yaml
video:
  provider: google
  google:
    model: veo-3.1
    default_duration: 8
    default_resolution: 1080p
    default_aspect_ratio: '16:9'
tool_timeouts:
  generate_video: 300
  generate_video_from_image: 300
```

---

## Voice I/O (Telegram)

### Speech-to-Text (Whisper)
Incoming Telegram voice messages are transcribed automatically using:
1. **OpenAI Whisper API** (if configured) — `whisper-1` model, ~$0.006/min
2. **Groq Whisper** (free fallback) — `whisper-large-v3`, fast and free

### Text-to-Speech
The AI can generate spoken audio using:
1. **ElevenLabs** — premium voices: Nova, Byte (requires API key)
2. **OpenAI TTS** — high quality (requires API key)
3. **edge-tts** — FREE Microsoft neural voices: Guy (default), Aria, Jenny, Davis
4. **gTTS** — free Google TTS fallback, always works

Switch voices from the **Quick Tools** sidebar dropdown or the **⚙️ Settings** tab. Changes take effect immediately and persist to config.yaml.

### Voice In → Voice Out
When a user sends a voice message via Telegram, the AI automatically:
1. Transcribes the audio with Whisper
2. Generates a text response
3. Converts the response to speech
4. Sends the audio back as a voice message

### Telegram Message Reliability
- **Markdown fallback**: If Telegram rejects a message due to invalid Markdown formatting, the bridge automatically retries as plain text
- **Message splitting**: Responses longer than 4096 characters are split at paragraph/line/word boundaries
- **CancelledError handling**: All 4 handler methods (`process_and_respond`, `_handle_document`, `_handle_photo`, `_handle_audio`) properly handle task cancellation without crashing
- **Empty response guard**: `[No response]` or empty responses are replaced with user-friendly messages instead of being sent literally
- **Error logging**: All Telegram API errors are logged instead of silently swallowed

---

## Chrome Extension — Galactic Browser

### Architecture
The Galactic Browser extension connects to Galactic AI via a persistent WebSocket on `/ws/chrome_bridge`. The background service worker manages the connection lifecycle (auto-reconnect on disconnect, heartbeat every 30s). The content script runs in the page context and provides accessibility tree snapshots, element interaction, form filling, and JavaScript execution.

### Side Panel Chat
A Chrome side panel provides a chat interface that connects to both the `/api/chat` HTTP endpoint and the `/stream` WebSocket for streaming responses. If WebSocket streaming fails, the side panel falls back to reading the HTTP response body.

### Authentication
The popup authenticates using a SHA-256 hash of the user's passphrase, matching the web Control Deck's auth system. Localhost connections bypass token validation for seamless local usage.

### Tool Capabilities
- **Page reading**: Full accessibility tree with roles, names, values, and ref IDs for programmatic interaction
- **Element finding**: Natural language element search (e.g., "login button", "search bar")
- **Form interaction**: Fill inputs, select dropdowns, check checkboxes by ref ID
- **Navigation**: URL navigation, back/forward history, tab listing
- **Screenshots**: JPEG capture of the active tab
- **JavaScript**: Execute arbitrary code in the page context

---

## Web Control Deck

### Tabs
- **Chat** — Full conversational interface with tool output; inline image and video players; 🎤 voice input mic button (click to record, transcribed via Whisper, inserted into chat); timestamps on every message; conventional bottom-up scroll (newest at bottom); chat history persists across page refreshes (`logs/chat_history.jsonl`)
- **Thinking** — Real-time agent trace viewer; watch the ReAct loop think and act step by step; persists across page refreshes via `/api/traces` backend buffer (last 500 entries)
- **Status** — Live telemetry: provider, model, token usage, uptime, fallback chain status, plugin states, version badge; 30+ data fields across 6 sections; **Cost Dashboard** with 6 summary cards (Session Cost, Today, This Week, This Month, Last Request, Avg/Message), multi-currency selector (9 currencies), free model detection, persistent cost logging
- **Models** — Browse and switch all available models, ordered best-to-worst with tier emoji indicators; per-model override dropdowns
- **Tools** — Browse all 110+ tools with descriptions and parameter info
- **Plugins** — Enable/disable plugins with toggle switches
- **Memory** — Read and edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md, VAULT.md in-browser; auto-creates missing files with starter templates
- **⚙️ Settings** — Primary/fallback model dropdowns, auto-fallback/smart-routing/streaming toggles, TTS voice selector, update check interval, speak timeout, max ReAct turns — all saved to config.yaml
- **Ollama** — Health status, discovered models, context window sizes
- **Logs** — Real-time system log stream with tool call highlighting (cyan), tool result lines (indented/italic), chronological order (newest at bottom), 500-line restore

### Real-Time Updates
Persistent WebSocket connection for live status, chat, Ollama health, logs, and streaming responses. No manual refresh needed.

### Chat Persistence
Chat messages are logged to `logs/chat_history.jsonl` and reloaded on page load. Refreshing the browser does not wipe your conversation. Each message shows an HH:MM:SS timestamp.

### Thinking Tab Persistence
Agent trace entries are buffered in memory on the backend (last 500 entries, `/api/traces` endpoint). On page load, `loadTraceHistory()` fetches and replays them so the Thinking tab is never empty after a refresh.

### Tab Memory
The active tab is saved to `localStorage` on every switch. After a page refresh, the same tab is automatically restored.

### Login Security
Protected by a passphrase set during setup. Stored as a SHA-256 hash — the plaintext is never saved.

### Log Enhancements
- Tool call lines highlighted in **cyan**
- Tool result lines shown indented and italic
- Up to 500 lines restored from server log history on page load

---

## Messaging Bridges

### Telegram
Full-featured bot with voice I/O, image delivery, inline keyboards, and admin-only access control.

**Commands:**
| Command | Description |
|---|---|
| `/status` | System telemetry (lite) |
| `/status full` | System telemetry (full) (`--full` / `-f` also supported) |
| `/model` | Switch AI model or select image generation backend |
| `/models` | Configure primary and fallback models |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Take a screenshot of the current browser page |
| `/cli` | Execute a shell command |
| `/compact` | Compact conversation context |
| `/help` | Interactive help menu |

The `/model` menu includes all 14 providers (each with their model list) plus an **Image Models** section for switching image generation backends.

### Discord
Full bot integration — responds in allowed channels, shows typing indicators, handles commands.

Config keys: `discord.bot_token`, `discord.allowed_channels`, `discord.admin_user_id`, `discord.timeout_seconds`

### WhatsApp
Webhook-based integration via the Meta Cloud API. Receives and responds to WhatsApp messages.

Config keys: `whatsapp.phone_number_id`, `whatsapp.access_token`, `whatsapp.verify_token`, `whatsapp.webhook_secret`

### Gmail
IMAP-based inbox monitoring. AI reads new emails, can auto-respond, and sends Telegram notifications on new mail.

Config keys: `gmail.email`, `gmail.app_password`, `gmail.check_interval`, `gmail.notify_telegram`

---

## Task Scheduler

Powered by APScheduler. Tasks survive restarts if configured in `config.yaml`.

- Cron-style recurring tasks with configurable intervals
- One-shot delayed tasks
- Tasks can invoke any tool or run arbitrary shell commands
- Manage from the AI chat using `schedule_task` and `list_tasks`

---

## Personality System

### 4 Modes
| Mode | Description |
|---|---|
| `byte` | Techno-hippie AI familiar (default) — tries .md files first, falls back to Byte defaults |
| `custom` | User-defined name, soul, and context from config.yaml |
| `generic` | Neutral, professional, no personality flavor |
| `files` | Reads entirely from workspace .md files (set automatically after OpenClaw migration) |

### What Gets Injected Into Every Prompt
1. IDENTITY.md (name, role, vibe)
2. SOUL.md (personality and values)
3. USER.md (user context)
4. MEMORY.md (persistent learned memories)
5. VAULT.md (private credentials and personal data — marked as "never share or expose")

### Hot Reload
`personality.reload_memory()` re-reads MEMORY.md from disk mid-session. Called automatically after every `memory_imprint`. The very next message sees the updated memory.

---

## Plugin System

### Built-In Plugins
| Plugin | Description |
|---|---|
| **BrowserExecutorPro** | Playwright-powered browser automation — 56 actions, Chromium/Firefox/WebKit |
| **ShellExecutor** | System shell command execution |
| **SubAgentManager** | Spawn and manage multiple parallel AI agents |
| **DesktopTool** | OS-level mouse/keyboard/screenshot automation via pyautogui |
| **Ping** | Connectivity monitoring |

### Custom Plugins
Drop a Python file in the `plugins/` folder. Any class with a `run()` coroutine method is automatically picked up on startup.

---

## Update System

`update.ps1` (Windows) and `update.sh` (Linux/macOS) safely update code while preserving:
- `config.yaml` — backed up to `logs/backups/` before any changes
- `logs/` — chat history, memory cache, TTS files
- `workspace/` — workspace files
- `memory/` — memory folder
- `watch/` — watch folder
- `VAULT.md` — private credentials and personal data

Galactic AI also checks GitHub for new releases automatically (every 6 hours by default) and shows a notification banner in the Control Deck when an update is available.

---

## Remote Access

Enable secure remote connections to Galactic AI from any device on your LAN or the internet.

### Setup
Set `web.remote_access: true` in `config.yaml`. On next startup, Galactic AI:
- Binds to `0.0.0.0` (all network interfaces) on plain HTTP
- Requires JWT authentication on all `/api/*` endpoints
- Automatically adds a Windows Firewall inbound rule for port 17789 (private networks only)
- Local connections from `127.0.0.1`/`::1` bypass auth — PC browser always has access
- Logs a startup warning that remote access is active

### Security Layers

| Layer | Mechanism | Details |
|---|---|---|
| Transport | Plain HTTP on LAN | No TLS — avoids `ERR_EMPTY_RESPONSE` from self-signed certs; JWT protects all endpoints |
| Authentication | JWT (HMAC-SHA256) | 24-hour expiry, signed with auto-generated 64-char hex secret |
| Localhost Bypass | IP check | `127.0.0.1` and `::1` skip auth — PC is never locked out |
| API Protection | Auth middleware | Every `/api/*` route requires valid JWT (except login/setup) |
| Brute Force | Rate limiting | 5 login attempts/min, 60 API calls/min per IP |
| CORS | Whitelist | Configurable `allowed_origins` in config.yaml |
| WebSocket | JWT | Token validation via query parameter |
| Firewall | Auto-rule (Windows) | `New-NetFirewallRule` adds TCP 17789 allow rule on startup |

### Voice API
- `POST /api/tts` — text-to-speech via ElevenLabs/edge-tts/gTTS pipeline, returns MP3 audio
- `POST /api/stt` — speech-to-text via OpenAI Whisper (Groq Whisper fallback), accepts multipart audio upload

---

## Configuration Reference

| Key | Description |
|---|---|
| `gateway.provider` | Primary AI provider |
| `gateway.model` | Active model name |
| `models.auto_fallback` | Enable auto-fallback on provider failure |
| `models.fallback_provider` | Fallback provider |
| `models.fallback_model` | Fallback model name |
| `models.streaming` | Enable response streaming |
| `models.smart_routing` | Auto-select model by task type |
| `models.max_turns` | Max ReAct loop iterations (default: 50) |
| `providers.*.apiKey` | API keys per provider |
| `providers.nvidia.keys.*` | Per-vendor NVIDIA keys |
| `providers.nvidia.fluxDevApiKey` | Separate key for FLUX.1-Dev generation |
| `providers.ollama.baseUrl` | Ollama server URL |
| `browser.engine` | Browser engine: chromium / firefox / webkit |
| `browser.headless` | Headless mode |
| `telegram.bot_token` | Telegram bot token |
| `telegram.admin_chat_id` | Your Telegram user ID |
| `telegram.timeout_seconds` | Max Telegram response wait (default: 180) |
| `discord.bot_token` | Discord bot token |
| `discord.allowed_channels` | List of channel IDs the bot responds in |
| `whatsapp.phone_number_id` | Meta Cloud API phone number ID |
| `whatsapp.access_token` | Meta Cloud API access token |
| `gmail.email` | Gmail address to monitor |
| `gmail.app_password` | Gmail App Password |
| `gmail.check_interval` | Inbox poll interval in seconds |
| `elevenlabs.api_key` | ElevenLabs TTS key |
| `elevenlabs.voice` | TTS voice name |
| `personality.mode` | byte / custom / generic / files |
| `personality.name` | AI name (custom mode) |
| `personality.soul` | Personality description (custom mode) |
| `personality.user_context` | User context (custom mode) |
| `web.port` | Web UI port (default: 17789) |
| `web.password_hash` | SHA-256 password hash (set via setup wizard) |
| `web.remote_access` | Enable remote access mode (default: false) |
| `web.jwt_secret` | Auto-generated JWT signing secret (64-char hex) |
| `web.rate_limit` | API rate limit per IP per minute (default: 60) |
| `web.allowed_origins` | CORS whitelist (empty = same-origin only) |
| `system.version` | Current version string |
| `system.update_check_interval` | GitHub update check interval in seconds (default: 21600 = 6h, 0 = disabled) |
| `models.speak_timeout` | Wall-clock timeout for entire ReAct loop in seconds (default: 600) |
| `tool_timeouts.exec_shell` | Shell command timeout in seconds (default: 120) |
| `tool_timeouts.execute_python` | Python execution timeout in seconds (default: 60) |
| `tool_timeouts.generate_image` | Image generation timeout in seconds (default: 180) |
| `tool_timeouts.generate_video` | Video generation timeout in seconds (default: 300) |
| `video.provider` | Video generation provider (default: google) |
| `video.google.model` | Google Veo model (veo-2, veo-3, veo-3.1) |
| `video.google.default_duration` | Default video duration in seconds (4, 6, or 8) |
| `video.google.default_resolution` | Default resolution (720p, 1080p, 4k) |
| `video.google.default_aspect_ratio` | Default aspect ratio (16:9 or 9:16) |
| `models.fallback_cooldowns.*` | Per-error-type cooldown durations for provider fallback |

---

## Platform Support

| Platform | Status |
|---|---|
| Windows 10/11 | Fully supported |
| Linux (Ubuntu, Debian, Arch, etc.) | Fully supported |
| macOS (Intel & Apple Silicon) | Fully supported |
| WSL2 | Supported |
| Chromebook (Linux mode) | See CHROMEBOOK.md |

---

**v1.1.4** — Galactic AI Automation Suite
