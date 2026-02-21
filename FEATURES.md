# Galactic AI — Feature Reference

Complete feature reference for Galactic AI Automation Suite **v0.9.0**.

---

## Core Architecture

### AsyncIO Runtime
The entire system runs on Python's `asyncio` event loop. Every subsystem — LLM gateway, web server, Telegram bridge, Discord bridge, WhatsApp bridge, Gmail bridge, plugin engine, Ollama manager, task scheduler — is fully non-blocking. Nothing stalls the core.

### ReAct Agentic Loop
The AI operates in a **Think → Act → Observe → Answer** loop. It chains multiple tool calls in sequence, observes results, reasons about what to do next, and keeps going until the task is complete. Each tool call has a 60-second timeout — no single operation can block the loop indefinitely.

### Per-Tool Timeout
Every tool execution is wrapped in a 60-second `asyncio.wait_for` timeout. If a tool hangs (e.g. a browser operation on a slow page), it is cancelled with a descriptive error message and the AI continues to the next step. This prevents the 330-second "typing forever" issue seen when browser tools stalled.

### Graceful Lifecycle Management
- Single **Ctrl+C** triggers a clean shutdown of all subsystems
- Signal handlers for SIGINT and SIGTERM on all platforms
- All background tasks cancelled and awaited with a 5-second timeout
- Browser closes with a 3-second timeout
- `os._exit(0)` force-exit fallback for edge cases that refuse to terminate
- Relay message queue uses a 2-second poll timeout so it wakes up to check the shutdown flag

---

## True Persistent Memory

### How It Works
Galactic AI uses a three-layer memory architecture:

**Layer 1: Identity Files (always injected into every prompt)**
- `IDENTITY.md` — AI name, role, vibe
- `SOUL.md` — core values and personality style
- `USER.md` — information about the user
- `MEMORY.md` — things the AI has learned across sessions

All four are read from disk on startup and included in every system prompt. Zero extra API calls. Cost is proportional only to the size of the files.

**Layer 2: MEMORY.md Auto-Writing (grows over time)**
When the AI calls `memory_imprint`, it:
1. Writes to `memory_aura.json` (searchable store)
2. Appends a timestamped entry to `MEMORY.md` on disk
3. Hot-reloads the personality so the very next message sees the new memory

The result: the AI builds its own persistent knowledge file automatically. You can edit it in the Memory tab of the Control Deck.

**Layer 3: memory_aura.json (searchable knowledge base)**
A local JSON index for storing arbitrary facts, documents, and imprinted knowledge. Searchable via the `memory_search` tool using keyword matching. Survives restarts.

### Token Efficiency
MEMORY.md is loaded once at startup. There is no per-message search, no embedding API call, no vector DB overhead. You only pay for what's actually in the file.

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

### Multi-Key NVIDIA Routing
NVIDIA hosts models from many vendors. Galactic AI routes to the correct API key based on the model selected. Configure separate keys for DeepSeek, Qwen, GLM, Kimi, StepFun, and FLUX models.

### Smart Model Routing
Enable `smart_routing: true` in config to auto-select the best model for each task type (coding, reasoning, creative, vision, quick queries).

### Auto-Fallback
If the primary provider fails, the system falls back to a secondary provider automatically. Recovery is automatic after a configurable cooldown period.

### Streaming Responses
Token-by-token streaming from all providers, broadcast to the web UI via WebSocket in real-time.

---

## Ollama Local Model Support

### Auto-Discovery
All models installed in Ollama are detected automatically. Pull a model with `ollama pull` and it appears in the UI within 60 seconds. No manual config.

### Health Monitoring
Background health checks track when Ollama goes online or offline. The web UI shows real-time Ollama health status.

### Context Window Awareness
The actual context window size is queried from Ollama for every model. Conversation history is trimmed accordingly.

### Tool Calling for Local Models
Ollama models get enhanced system prompts with full parameter schemas for all 92+ tools, plus few-shot examples for reliable JSON tool call generation. Temperature tuned to 0.3 for consistent structured output.

---

## 92+ Built-In Tools

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

### Memory (2 tools)
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

## Voice I/O (Telegram)

### Speech-to-Text (Whisper)
Incoming Telegram voice messages are transcribed automatically using:
1. **OpenAI Whisper API** (if configured) — `whisper-1` model, ~$0.006/min
2. **Groq Whisper** (free fallback) — `whisper-large-v3`, fast and free

### Text-to-Speech
The AI can generate spoken audio using:
1. **ElevenLabs** — premium voices (requires API key)
2. **OpenAI TTS** — high quality (requires API key)
3. **edge-tts** — FREE Microsoft neural voices (Guy, Aria, and many others)
4. **gTTS** — free Google TTS fallback, always works

### Voice In → Voice Out
When a user sends a voice message via Telegram, the AI automatically:
1. Transcribes the audio with Whisper
2. Generates a text response
3. Converts the response to speech
4. Sends the audio back as a voice message

---

## Web Control Deck

### Tabs
- **Chat** — Full conversational interface with tool output; timestamps on every message; chat history persists across page refreshes (`logs/chat_history.jsonl`)
- **Thinking** — Real-time agent trace viewer; watch the ReAct loop think and act step by step; persists across page refreshes via `/api/traces` backend buffer (last 500 entries)
- **Status** — Live telemetry: provider, model, token usage, uptime, plugin states, version badge
- **Models** — Browse and switch all available models, ordered best-to-worst with tier emoji indicators
- **Tools** — Browse all 92+ tools with descriptions and parameter info
- **Plugins** — Enable/disable plugins with toggle switches
- **Memory** — Read and edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md in-browser; auto-creates missing files with starter templates
- **Ollama** — Health status, discovered models, context window sizes
- **Logs** — Real-time system log stream with tool call highlighting (cyan), tool result lines (indented/italic), 500-line restore

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
| `/status` | System telemetry (provider, model, uptime, tokens) |
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
| `system.version` | Current version string |

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

**v0.9.0** — Galactic AI Automation Suite
