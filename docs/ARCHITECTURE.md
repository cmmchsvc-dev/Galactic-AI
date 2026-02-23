# Galactic AI — Architecture Reference

**v1.1.0** — System design, component breakdown, and data flows.

---

## Overview

Galactic AI is a Python asyncio automation platform. The entire system runs on a single non-blocking event loop. Every component — LLM gateway, web server, Telegram bridge, scheduler, plugin engine — is fully async. Nothing stalls the core.

```
┌─────────────────────────────────────────────────────────────────┐
│                        GalacticCore                             │
│   (galactic_core_v2.py — orchestrator + config + logger)        │
└──────────┬──────────────┬────────────────┬──────────────────────┘
           │              │                │
    ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
    │  GalacticRelay │ │ModelManager│ │OllamaManager│
    │  (WebSocket)   │ │(fallback)  │ │(discovery)  │
    └──────┬──────┘ └─────┬──────┘ └──────┬──────┘
           │              │                │
    ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
    │GalacticGateway│ │GalacticWebDeck│ │TelegramBridge│
    │(LLM + ReAct) │ │(UI + API)    │ │(Bot + Voice)│
    └─────────────┘ └─────────────┘ └─────────────┘
```

---

## Primary Components

### 1. GalacticCore (`galactic_core_v2.py`)

The central orchestrator. Owns:
- `config.yaml` loading and hot-reload
- Plugin discovery and lifecycle (`setup_systems()`)
- Workspace memory imprint on startup (`imprint_workspace()`)
- Priority message relay (`GalacticRelay`)
- Background task registry: relay loop, Telegram listen, web server, scheduler, Ollama discovery, model recovery checks, GitHub update checker
- Structured logging to `logs/system_log.txt` (plain text) + daily JSON component logs

**Startup sequence:**
1. Load `config.yaml`
2. `setup_systems()` — initialize all subsystems in order
3. `imprint_workspace()` — load USER.md, IDENTITY.md, SOUL.md, MEMORY.md, TOOLS.md, VAULT.md into memory
4. Start socket server on `system.port` (default 9999)
5. Launch all background tasks as asyncio Tasks
6. Wait for Ctrl+C → graceful shutdown

---

### 2. GalacticRelay (Message Bus)

A `asyncio.PriorityQueue`-based broadcast system. Every subsystem emits events through the relay; connected web clients receive them over WebSocket.

**Event types:**
| Event | Description |
|-------|-------------|
| `log` | System log line |
| `chat` | Chat message (user or AI) |
| `thinking` | ReAct loop trace entry |
| `status` | System status update |
| `model_fallback` | Provider fallback occurred |
| `update_available` | New GitHub release detected |
| `ollama_status` | Ollama health change |
| `stream_chunk` | Streaming token from LLM |

Priority levels: 1 (critical) → 2 (important) → 3 (normal/verbose)

---

### 3. GalacticGateway (`gateway_v2.py`)

The LLM routing layer and ReAct agent engine.

**Routing logic:**
1. Check `ModelManager` for current primary provider/model
2. Build system prompt via `GalacticPersonality.get_system_prompt()`
3. Send to provider API (aiohttp/httpx)
4. Stream tokens back via relay
5. Parse tool calls from response JSON
6. Execute tools (with per-tool `asyncio.wait_for` timeout)
7. Loop (Think → Act → Observe) up to `models.max_turns` times
8. Return final answer

**Tool execution:**
- 100+ tools registered in the gateway (including image and video generation)
- Each tool wrapped in `asyncio.wait_for(timeout=tool_timeout)`
- Tool timeouts configurable per tool-type in `config.yaml` under `tool_timeouts`
- Entire ReAct loop capped by `models.speak_timeout` (default 600s)
- Video generation tools use async polling (10s intervals) for long-running Veo operations

---

### 4. ModelManager (`model_manager.py`)

Manages the provider/model selection and fallback chain.

**Features:**
- Primary + fallback provider/model configuration
- Per-error-type cooldowns (RATE_LIMIT, SERVER_ERROR, TIMEOUT, AUTH_ERROR, QUOTA_EXHAUSTED)
- `auto_fallback_enabled` toggle (configurable from Settings tab)
- Automatic recovery — periodic health checks restore cooldown-expired providers
- `set_primary(provider, model)` and `set_fallback(provider, model)` persist to `config.yaml`
- Smart routing (optional): auto-selects model by task type when enabled

---

### 5. GalacticPersonality (`personality.py`)

Builds the system prompt injected into every LLM call.

**Files loaded (in order):**
1. `IDENTITY.md` — AI name, role, vibe
2. `SOUL.md` — personality and values
3. `USER.md` — user preferences and context
4. `MEMORY.md` — persistent learned memories
5. `VAULT.md` — private credentials for automation (marked "never share or expose")

**Modes:** `byte` (default) | `custom` | `generic` | `files`

---

### 6. GalacticWebDeck (`web_deck.py`)

The web Control Deck served on `web.port` (default 17789). Single-file aiohttp server with inline HTML/CSS/JS.

**Tabs:**
| Tab | Description |
|-----|-------------|
| Chat | Full conversational UI with tool output, voice input mic button, timestamps, chat history |
| Thinking | Real-time ReAct trace viewer |
| Status | 30+ telemetry fields across 6 sections |
| Models | Browse/switch 100+ models; per-model overrides |
| Tools | Tool browser with descriptions and parameters |
| Plugins | Enable/disable plugins |
| Memory | In-browser editor for all .md files including VAULT.md |
| ⚙️ Settings | Model dropdowns, auto-fallback toggle, voice selector, system tuning |
| Ollama | Health status, discovered models, context windows |
| Logs | Real-time log stream |

**WebSocket relay:** Persistent connection receives all relay events. Handles `log`, `chat`, `thinking`, `status`, `model_fallback`, `update_available`, `stream_chunk`, `ollama_status`.

**REST API endpoints (key):**
```
GET  /api/status           — full system telemetry
POST /api/chat             — send a message
POST /api/settings/models  — update primary/fallback model
POST /api/settings/voice   — update TTS voice
POST /api/settings/system  — update system settings
GET  /api/traces           — last 500 ReAct trace entries
GET  /api/video/{filename} — serve generated video files
GET  /api/memory/files     — list workspace .md files
GET  /api/memory/file      — read a .md file
POST /api/memory/file      — write a .md file
GET  /api/tools            — list all registered tools
POST /api/model/set        — switch model
```

---

### 7. Messaging Bridges

Each bridge runs as a separate asyncio task.

| Bridge | File | Transport |
|--------|------|-----------|
| Telegram | `telegram_bridge.py` | Long polling; voice I/O via Whisper + TTS |
| Discord | `discord_bridge.py` | discord.py bot |
| WhatsApp | `whatsapp_bridge.py` | Meta Cloud API webhooks |
| Gmail | `gmail_bridge.py` | IMAP polling |

All bridges emit chat messages through `GalacticGateway.speak()` and relay responses back to their platform.

---

### 8. OllamaManager (`ollama_manager.py`)

- Health checks Ollama every 60 seconds
- Auto-discovers all pulled models on startup and periodically
- Queries context window sizes per model
- Provides context-trim support to keep conversations within window limits

---

### 9. GalacticScheduler (`scheduler.py`)

APScheduler-backed task scheduler.
- Cron-style recurring tasks
- One-shot delayed tasks
- Tasks survive restarts if configured in `config.yaml` under `shell_tasks`

---

### 10. Plugin System

Plugins extend the gateway with additional capabilities. Each plugin is an asyncio-compatible class with a `run()` coroutine.

**Built-in plugins:**
| Plugin | File | Description |
|--------|------|-------------|
| BrowserExecutorPro | `plugins/browser_executor_pro.py` | 56 Playwright browser actions |
| ShellExecutor | `plugins/shell_executor.py` | Shell command execution with timeout |
| SubAgentManager | `plugins/subagent_manager.py` | Multi-agent parallel task orchestration |
| DesktopTool | `plugins/desktop_tool.py` | OS-level mouse/keyboard/screenshot (pyautogui) |
| Ping | `plugins/ping.py` | Connectivity monitoring |

Custom plugins: drop any `.py` file with a `run()` coroutine in `plugins/` — it's auto-discovered on startup.

---

### 11. Remote Access (`remote_access.py`)

Security module for remote connections. Activated when `web.remote_access: true` in config.yaml.

**Components:**
- **JWT Authentication** — HMAC-SHA256 tokens with 24-hour expiry, auto-generated 64-char hex secret
- **Auth Middleware** — aiohttp middleware that validates JWT on all `/api/*` routes; `127.0.0.1`/`::1` bypass auth so the PC is never locked out
- **Plain HTTP on LAN** — server binds to `0.0.0.0` with no TLS in remote mode; avoids `ERR_EMPTY_RESPONSE` caused by self-signed certs
- **Auto Firewall Rule** — on Windows with `remote_access: true`, `galactic_core_v2.py` calls `New-NetFirewallRule` via PowerShell on startup to open TCP 17789 (private networks only)
- **Rate Limiter** — per-IP sliding window (60 req/min API, 5 req/min login)
- **CORS Middleware** — configurable `allowed_origins` whitelist

**Voice API endpoints:**
```
POST /api/tts         — text-to-speech (returns MP3 audio)
POST /api/stt         — speech-to-text (accepts multipart audio)
```

---

## Data Flows

### Chat Message (Web UI → AI → Web UI)

```
User types in Chat tab
  → POST /api/chat
    → GalacticGateway.speak(message)
      → GalacticPersonality.get_system_prompt()
        → Reads IDENTITY.md, SOUL.md, USER.md, MEMORY.md, VAULT.md
      → LLM API (provider)
        → stream_chunk events → WebSocket → Chat tab
      → Tool calls parsed
        → asyncio.wait_for(tool_fn(), timeout=tool_timeout)
        → thinking events → WebSocket → Thinking tab
      → Loop until final answer
    → chat event → relay → WebSocket → Chat tab
```

### VAULT.md for Automation

```
User creates VAULT.md with credentials
  → On startup: GalacticPersonality reads VAULT.md
    → Injected as "VAULT (private — use for automation, never expose)"
      into every system prompt
  → AI uses credentials when filling forms, logging in, automating tasks
  → VAULT.md never committed (gitignored), never overwritten by updater
```

### Video Generation (Veo)

```
User asks "generate a video of a sunset"
  → GalacticGateway.speak() → ReAct loop
    → Tool call: generate_video(prompt="a sunset over the ocean")
      → google-genai SDK → client.models.generate_videos()
        → Returns async operation
      → Poll operation every 10s until done
        → Log "🎬 Video still generating..." every 60s
      → Download video → save to images/video/veo_{timestamp}.mp4
      → Set self.last_video_file = path
    → Final answer returned to web_deck
  → handle_chat() checks last_video_file
    → Adds video_url: /api/video/{filename} to response
  → Browser JS: appendBotVideo(url)
    → Inline <video> player with controls + download link
```

### GitHub Update Checker

```
On startup (15s delay) and every update_check_interval seconds:
  → GalacticCore._update_check_loop()
    → GET api.github.com/repos/cmmchsvc-dev/Galactic-AI/releases/latest
    → Compare latest tag to config.system.version
    → If newer: relay.emit("update_available", {current, latest, url})
      → WebSocket → Control Deck: toast + persistent banner
```

---

## Configuration (`config.yaml`)

Key sections:

```yaml
gateway:          # Active provider + model
models:           # Fallback chain, timeouts, auto-fallback toggle
providers:        # API keys per provider
tool_timeouts:    # Per-tool timeout overrides (including video: 300s)
video:            # Video generation (provider, model, duration, resolution)
elevenlabs:       # TTS voice selection
personality:      # Mode + custom fields
system:           # Version, port, update_check_interval
paths:            # logs, images, plugins, workspace
telegram:         # Bot token + admin chat ID
web:              # Host, port, password hash, remote_access, jwt_secret
```

`config.yaml` is read on startup and persisted by `_save_config()` whenever settings change via the API.

---

## File Structure

```
Galactic-AI/
├── galactic_core_v2.py     # Orchestrator, relay, update checker
├── gateway_v2.py           # LLM routing, ReAct loop, 100+ tools
├── web_deck.py             # Control Deck (aiohttp + inline HTML/JS)
├── remote_access.py        # JWT auth, TLS, rate limiting, CORS
├── personality.py          # System prompt builder (loads all .md files)
├── model_manager.py        # Provider fallback chain
├── memory_module_v2.py     # memory_aura.json store
├── ollama_manager.py       # Ollama health + discovery
├── scheduler.py            # APScheduler task runner
├── nvidia_gateway.py       # NVIDIA NIM image generation
├── telegram_bridge.py      # Telegram bot + voice I/O
├── discord_bridge.py       # Discord bot
├── whatsapp_bridge.py      # WhatsApp Cloud API
├── gmail_bridge.py         # Gmail IMAP
├── VAULT-example.md        # Template for private credentials
├── config.yaml             # All configuration
└── plugins/
    ├── browser_executor_pro.py   # Playwright (56 actions)
    ├── shell_executor.py         # Shell execution
    ├── subagent_manager.py       # Multi-agent
    └── desktop_tool.py           # Desktop automation
```

**Workspace files (gitignored, never overwritten by updater):**
- `MEMORY.md` — persistent learned memories
- `IDENTITY.md` — AI identity
- `SOUL.md` — AI personality
- `USER.md` — user profile
- `TOOLS.md` — tool notes
- `VAULT.md` — private credentials for automation
