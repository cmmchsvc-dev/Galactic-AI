# Galactic AI — Feature Reference

Complete feature reference for Galactic AI Automation Suite **v0.7.1**.

---

## Core Architecture

### AsyncIO Runtime
The entire system runs on Python's `asyncio` event loop. Every subsystem — LLM gateway, web server, Telegram bridge, plugin engine, Ollama manager, task scheduler — is fully non-blocking. Nothing stalls the core.

### ReAct Agentic Loop
The AI operates in a **Think → Act → Observe → Answer** loop. It chains multiple tool calls in sequence, observes results, reasons about what to do next, and keeps going until the task is complete. This is the same architecture used by frontier AI agents.

### Graceful Lifecycle Management
- Single **Ctrl+C** triggers a clean shutdown of all subsystems
- Signal handlers for SIGINT and SIGTERM on all platforms
- All background tasks cancelled and awaited cleanly
- No orphaned processes or socket errors on exit

---

## True Persistent Memory

### How It Works
Galactic AI uses a three-layer memory architecture:

**Layer 1: Identity Files (always injected into every prompt)**
- `IDENTITY.md` — AI name, role, vibe
- `SOUL.md` — core values and personality style
- `USER.md` — information about the user
- `MEMORY.md` — things the AI has learned across sessions *(new in v0.7.1)*

All four are read from disk on startup and included in every system prompt. Zero extra API calls. Cost is proportional only to the size of the files.

**Layer 2: MEMORY.md Auto-Writing (grows over time)**
When the AI calls `memory_imprint`, it:
1. Writes to `memory_aura.json` (existing behavior)
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
| **Cohere** | API key | Yes |
| **NVIDIA AI** | API key(s) | Yes |
| **Together AI** | API key | Yes |
| **Perplexity** | API key | No |
| **Fireworks AI** | API key | Yes |
| **DeepSeek** | API key | Yes |
| **OpenRouter** | API key | Yes (unified) |
| **Ollama (Local)** | None | Free forever |

### Multi-Key NVIDIA Routing
NVIDIA hosts models from many vendors. Galactic AI routes to the correct API key based on the model selected. Configure up to 5 separate NVIDIA keys.

### Smart Model Routing
Enable `smart_routing: true` in config to auto-select the best model for each task type (coding, reasoning, creative, vision, quick queries).

### Auto-Fallback
If the primary provider fails, the system falls back to a secondary provider automatically. Recovery is automatic after a cooldown period.

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
Ollama models get enhanced system prompts with full parameter schemas for all 72 tools, plus few-shot examples for reliable JSON tool call generation. Temperature tuned to 0.3 for consistent structured output.

---

## 72+ Built-In Tools

### File System (3 tools)
| Tool | Description |
|---|---|
| `read_file` | Read the contents of any file |
| `write_file` | Write or create a file |
| `edit_file` | Make targeted edits (find/replace) |

### Shell & Process (6 tools)
| Tool | Description |
|---|---|
| `exec_shell` | Execute any shell command |
| `process_start` | Start a long-running background process |
| `process_status` | Check status of running processes |
| `process_kill` | Terminate a process |
| `schedule_task` | Schedule a recurring or one-shot task |
| `list_tasks` | View all scheduled tasks |

### Web & Search (2 tools)
| Tool | Description |
|---|---|
| `web_search` | Search DuckDuckGo (no API key needed) |
| `web_fetch` | Fetch and parse any URL |

### Vision (1 tool)
| Tool | Description |
|---|---|
| `analyze_image` | Analyze images using Gemini Vision, Ollama multimodal, or other providers |

### Memory (2 tools)
| Tool | Description |
|---|---|
| `memory_search` | Keyword search across persistent memory |
| `memory_imprint` | Store new information — writes to memory_aura.json AND MEMORY.md |

### Audio (1 tool)
| Tool | Description |
|---|---|
| `text_to_speech` | Convert text to speech via ElevenLabs, OpenAI TTS, or free gTTS |

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

## Voice I/O (Telegram)

### Speech-to-Text (Whisper)
Incoming Telegram voice messages are transcribed automatically using:
1. **OpenAI Whisper API** (if configured) — `whisper-1` model, ~$0.006/min
2. **Groq Whisper** (free fallback) — `whisper-large-v3`, fast and free

### Text-to-Speech
The AI can generate spoken audio using:
1. **ElevenLabs** — premium voices (requires API key)
2. **OpenAI TTS** — high quality (requires API key)
3. **gTTS** — free fallback, always works

### Voice In → Voice Out
When a user sends a voice message via Telegram, the AI automatically:
1. Transcribes the audio with Whisper
2. Generates a text response
3. Converts the response to speech (Byte male voice)
4. Sends the audio back as a voice message

When a user sends a text message, the AI responds with text only.

---

## Web Control Deck

### Tabs
- **Chat** — Full conversational interface with tool output; chat history persists across page refreshes (stored in `logs/chat_history.jsonl`)
- **Status** — Live telemetry: provider, model, token usage, uptime, plugin states, version badge
- **Tools** — Browse all 72+ tools with descriptions and parameter info
- **Plugins** — Enable/disable plugins with toggle switches
- **Memory** — Read and edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md in-browser; auto-creates missing files with starter templates
- **Ollama** — Health status, discovered models, context window sizes
- **Logs** — Real-time system log stream

### Real-Time Updates
Persistent WebSocket connection for live status, chat, Ollama health, logs, and streaming responses.

### Chat Persistence
Chat messages are logged to `logs/chat_history.jsonl` and reloaded on page load. Refreshing the browser does not wipe your conversation.

### Login Security
Protected by a passphrase set during setup. Stored as a SHA-256 hash — the plaintext is never saved.

### Model Switching
Switch provider and model from the UI at any time. Takes effect on the next message.

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
4. MEMORY.md (persistent learned memories) ← new in v0.7.1

### Hot Reload
`personality.reload_memory()` re-reads MEMORY.md from disk mid-session. Called automatically after every `memory_imprint`. The very next message sees the updated memory.

---

## Telegram Bot

### Commands
| Command | Description |
|---|---|
| `/status` | System telemetry (provider, model, uptime, tokens) |
| `/model` | Switch to a different AI model |
| `/models` | Configure primary and fallback models |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Take a screenshot of the current browser page |
| `/cli` | Execute a shell command |
| `/compact` | Compact conversation context |
| `/help` | Interactive help menu |

### Natural Language Chat
Send any message (text or voice) without a `/` command and the AI responds with full tool access.

### Web UI Integration
Telegram messages appear in the web UI chat log in real-time.

---

## Setup Wizard (7 Steps)

| Step | Content |
|---|---|
| 1 | Primary Provider |
| 2 | Additional API Keys + TTS Voice |
| 3 | Telegram Bot |
| 4 | Security (password) |
| 5 | Personality (Byte / Custom / Generic) |
| 6 | OpenClaw Migration (import .md files) |
| 7 | Review & Launch |

---

## Update System

`update.ps1` (Windows) and `update.sh` (Linux/macOS) safely update code while preserving:
- `config.yaml` — backed up before any changes
- `logs/` — chat history, memory cache, TTS files
- `workspace/` — workspace files
- `memory/` — memory folder
- `watch/` — watch folder

---

## Plugin System

### Built-In Plugins
| Plugin | Description |
|---|---|
| **BrowserExecutorPro** | Playwright-powered browser automation (Chromium/Firefox/WebKit) |
| **ShellExecutor** | System shell command execution |
| **SubAgentManager** | Spawn and manage multiple parallel AI agents |
| **Ping** | Connectivity monitoring |

### Custom Plugins
Drop a Python file in the `plugins/` folder. Any class with a `run()` coroutine method is automatically picked up.

---

## Task Scheduler

- Cron-style recurring tasks with configurable intervals
- One-shot delayed tasks
- Tasks can invoke any tool or run arbitrary shell commands
- View and manage from the AI chat or web UI

---

## Configuration Reference

| Key | Description |
|---|---|
| `gateway.provider` | Primary AI provider |
| `gateway.model` | Active model name |
| `models.auto_fallback` | Enable auto-fallback on provider failure |
| `models.fallback_provider` | Fallback provider |
| `models.streaming` | Enable response streaming |
| `models.smart_routing` | Auto-select model by task type |
| `providers.*.apiKey` | API keys per provider |
| `providers.nvidia.keys.*` | Per-vendor NVIDIA keys |
| `providers.ollama.baseUrl` | Ollama server URL |
| `browser.engine` | Browser engine: chromium / firefox / webkit |
| `browser.headless` | Headless mode |
| `telegram.bot_token` | Telegram bot token |
| `telegram.admin_chat_id` | Your Telegram user ID |
| `elevenlabs.api_key` | ElevenLabs TTS key |
| `elevenlabs.voice` | TTS voice: nova / byte / gtts |
| `personality.mode` | byte / custom / generic / files |
| `personality.name` | AI name (custom mode) |
| `personality.soul` | Personality description (custom mode) |
| `personality.user_context` | User context (custom mode) |
| `web.port` | Web UI port (default: 17789) |
| `web.password_hash` | SHA-256 password hash |
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

**v0.7.1** — Galactic AI Automation Suite
