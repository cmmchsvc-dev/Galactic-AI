# Galactic AI — Automation Suite

**Sovereign. Universal. Fast.**

A powerful, local-first AI automation platform with 147 built-in tools, an extensible Skills ecosystem, true persistent memory, voice I/O, video generation, Chrome browser extension, social media tools, 14 AI providers, multi-platform messaging bridges, and a real-time web Control Deck. **v1.1.4**

Run fully local with Ollama (no API keys, no cloud, no tracking), or connect to any of 14 cloud providers. Your data stays yours.

---

## What Makes Galactic AI Different

### Strategic Planning for Complex Tasks (Big Brain / Builder Architecture)
Instead of diving blindly into a problem, Galactic AI thinks ahead. For complex multi-step requests, the system automatically isolates a high-powered "Planner" model (like Gemini 3.1 Pro or Claude 3.5 Sonnet) in its own ReAct loop. This Planner autonomously scans your codebase, reads files, and investigates the environment *before* generating a step-by-step implementation plan. 

Once the plan is generated and stored in long-term memory, your standard, affordable "Builder" model (like Grok 4.1 Fast or Qwen) wakes up to execute the tools and write the code based on the Planner's blueprint. This gives you top-tier intelligence with highly efficient execution.

You can trigger this explicitly anytime by starting your prompt with `/plan`.

### True Persistent Memory — Without Burning Tokens
Most AI tools forget everything the moment you close the tab. Galactic AI doesn't.

When the AI learns something important, it writes it to **MEMORY.md** on disk. The next time it starts up, it reads that file and immediately knows everything it learned in past sessions — no searches, no extra API calls, just the file loaded once into the system prompt. As the AI learns more, the memory file grows. You can edit it directly in the Control Deck.

Additionally, Galactic AI includes a `memory_manager` community skill powered by **ChromaDB**. This provides true, queryable long-term vector memory, allowing the AI to semantic-search its entire history to find the most relevant context before answering a question.

### Self-Healing Code Execution (Test-Driven Development)
Galactic AI now writes robust code that *actually works*. With the `test_driven_coder` tool (part of the Gemini Coder skill), the AI can write a Python script, execute it in a sandboxed environment, automatically catch any errors (tracebacks), and then autonomously iterate with Gemini to fix the code until it runs successfully. This means the AI delivers working code solutions, not just drafts.

### Workspace Context Awareness (RAG for Local Codebase)
Beyond recalling chat history, Galactic AI now has a living memory of your local codebase. A background process continuously watches your `workspace/` folder, chunking and embedding code files into ChromaDB. The AI can use the `search_workspace` tool to instantly find relevant code snippets, function definitions, or documentation semantically, making it an expert on your project's internals without manual file searches.

## Quick Start

### Windows
```powershell
# Extract the ZIP, open PowerShell in the folder, then:
.\install.ps1    # Installs all dependencies
.\launch.ps1     # Starts Galactic AI
```

### macOS / Linux
```bash
chmod +x install.sh launch.sh
./install.sh     # Installs all dependencies
./launch.sh      # Starts Galactic AI
```

Then open **http://127.0.0.1:17789** — the Setup Wizard walks you through configuration.

Press **Ctrl+C** once to shut down cleanly.

---

## Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **Ollama** (optional, for local models) — [ollama.com/download](https://ollama.com/download)

---

## Installation (Manual)

If you prefer to install dependencies manually instead of using the install scripts:

**Windows (PowerShell):**
```powershell
pip install -r requirements.txt
playwright install chromium
```

**Linux / macOS:**
```bash
pip3 install -r requirements.txt
playwright install chromium
```

---

## Setup Wizard

After launching, open **http://127.0.0.1:17789**. The Setup Wizard appears automatically on first run:

| Step | What You Configure |
|---|---|
| 1 | **Primary Provider** — your main AI (Google, Anthropic, OpenAI, Groq, Ollama, etc.) |
| 2 | **Additional API Keys + TTS** — extra providers and ElevenLabs voice |
| 3 | **Telegram** — optional Telegram bot for mobile access and voice I/O |
| 4 | **Messaging Bridges** — Discord, WhatsApp, Gmail (all optional) |
| 5 | **Security** — passphrase to protect the web UI |
| 6 | **Personality** — choose Byte, Custom, or Generic Assistant |
| 7 | **OpenClaw Migration** — import your existing memory/identity files |
| 8 | **Review & Launch** — confirm everything and start |

> **Zero-key mode:** Choose Ollama as your provider in Step 1 and skip all API key steps. Pull a model with `ollama pull qwen3:8b` and you're running 100% locally.

---

## AI Providers

| Provider | Top Models | Free Tier |
|---|---|---|
| **Google Gemini** | gemini-2.5-pro, gemini-3.1-pro-preview, gemini-2.5-flash | Yes |
| **Anthropic Claude** | claude-opus-4-6, claude-sonnet-4-5 | No |
| **OpenAI** | gpt-4o, o3, o1 | No |
| **xAI Grok** | grok-4, grok-3 | No |
| **Groq** | llama-3.3-70b, deepseek-r1, gemma-2-9b — blazing fast | Yes |
| **Mistral** | mistral-large-3, codestral | Yes |
| **NVIDIA AI** | qwen3-coder-480b, deepseek-v3.2, kimi-k2.5, llama-3.1-405b | Yes |
| **DeepSeek** | deepseek-chat, deepseek-reasoner | Yes |
| **Cerebras** | llama-3.3-70b — ultra fast inference | Yes |
| **OpenRouter** | Any model via unified API | Yes |
| **HuggingFace** | 1000s of open models | Yes |
| **Together AI** | 100+ open models | Yes |
| **Perplexity** | sonar-pro, sonar | No |
| **Ollama (Local)** | Any model you pull — qwen3, llama3.3, phi4, mistral, deepseek-coder | **No key needed** |

---

## Web Control Deck

The Control Deck at **http://127.0.0.1:17789** gives you full control:

| Tab | What's There |
|---|---|
| **Chat** | Talk to your AI with full tool support; inline image and video players; 🎤 voice input mic button; timestamps on every message; chat history survives page refreshes |
| **Thinking** | Real-time agent trace — watch the ReAct loop think and act step by step; persists across page refreshes |
| **Status** | Live provider, model, token usage, uptime, fallback chain, and plugin telemetry |
| **Models** | Browse and switch all 100+ models, ordered best-to-worst with tier indicators |
| **Tools** | Browse all 100+ built-in tools with descriptions and parameters |
| **Plugins** | Enable/disable plugins with one click |
| **Memory** | Edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md, VAULT.md directly in-browser |
| **⚙️ Settings** | Primary/fallback model dropdowns, auto-fallback toggle, voice selector, system tuning |
| **Ollama** | Health status, discovered models, context window sizes |
| **Logs** | Real-time log stream with tool call highlighting and 500-line history |

---

## Persistent Memory System

Galactic AI has three layers of memory, all persistent across restarts:

### 1. Identity Files (always in every prompt)
- **IDENTITY.md** — who the AI is (name, role, vibe)
- **SOUL.md** — core values and personality
- **USER.md** — who you are, your preferences, context
- **MEMORY.md** — things the AI has learned over time
- **VAULT.md** — private credentials and personal data for automation (see [VAULT section](#vault--personal-data-for-automation) below)

All five files are loaded from disk on startup and injected into every system prompt. The AI always knows who it is and who you are.

### 2. MEMORY.md (grows automatically)
When you tell the AI to remember something, or when it decides something is worth keeping, it appends a timestamped entry to `MEMORY.md`. This file is then available in **every future conversation** automatically. You can also edit it directly in the Memory tab.

### 3. memory_aura.json (searchable knowledge base)
Facts, documents, and imprinted knowledge stored in a local JSON index. The AI can search this store at any time using the `memory_search` tool.

---

### 4. Restart Resilience — Conversation Recall
Two lightweight, local-first mechanisms make restarts less amnesiac without running heavy retrieval on every message:

- **Auto-Recall Injection** — `skills/community/conversation_auto_recall.py`
  - Runtime-patches `GalacticGateway.speak()`.
  - When the user asks *remember/last time/earlier/what did I say* type questions, it scans `logs/conversations/` (hot buffer + recent session archives) and injects a compact **Conversation Recall (auto)** block into context.
  - Tool: `conversation_auto_recall_status`

- **Boot Recall Banner** — `skills/community/boot_recall_banner.py`
  - On startup, prints the last N hot-buffer messages and writes: `logs/conversations/boot_recall_banner.txt`
  - Config:
    ```yaml
    conversation:
      boot_recall_messages: 10
    ```
  - Tool: `boot_recall_show`

---


## VAULT — Personal Data for Automation

**VAULT.md** is a private credentials file that the AI loads into every prompt. It lets the agent log into services, fill forms, and automate tasks on your behalf without you having to re-type credentials every time.

### Setup

1. Copy the included template: `cp VAULT-example.md VAULT.md`
2. Edit `VAULT.md` with your real credentials
3. Restart Galactic AI — the AI now has access to your credentials in every conversation

### What Goes in VAULT.md

```markdown
## Login Credentials
- **Email:** your-email@example.com
- **GitHub Username:** your-username
- **GitHub Token:** ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

## Personal Info
- **Full Name:** Your Name
- **Phone:** +1-555-555-5555
- **Address:** 123 Main St, City, State, ZIP

## Payment
- **PayPal Email:** your-paypal@example.com

## Custom Fields
- **Company Name:** Your Company
- **Project Name:** Your Project
```

### Security

- **VAULT.md is gitignored** — it is never committed to the public repository
- **Protected by the updater** — `update.ps1` and `update.sh` never overwrite VAULT.md
- The AI is instructed to **never share or expose** VAULT.md contents
- Editable directly in the **Memory tab** of the Control Deck
- Store only what you need for automation — keep truly sensitive data (bank passwords, SSNs) out of any file

---

## Telegram Bot (Optional)

Control Galactic AI from your phone with full voice support:

1. Message [@BotFather](https://t.me/BotFather) — create a new bot — copy the token
2. Enter the token in the Setup Wizard
3. Get your chat ID from [@userinfobot](https://t.me/userinfobot) and enter it too
4. Restart Galactic AI

**Commands:**
| Command | What it does |
|---|---|
| `/status` | Live system telemetry (lite) |
| `/status full` | Live system telemetry (full) (`--full` / `-f` also supported) |
| `/model` | Switch AI model or select image generation model |
| `/models` | Configure primary and fallback models |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Take a browser screenshot |
| `/cli` | Run a shell command |
| `/compact` | Compact conversation context |
| `/help` | Interactive menu |

The `/model` menu includes an **Image Models** section to switch between Imagen 4 Ultra, Imagen 4, FLUX.1 Dev, Imagen 4 Fast, and FLUX.1 Schnell.

Or just send any message — text or voice — and the AI responds. Voice messages are transcribed automatically and replied to with voice.

---

## Messaging Bridges (Optional)

### Discord
Full bot integration — AI responds in channels, handles slash commands, shows typing indicators.

1. Create a bot at [discord.com/developers](https://discord.com/developers/applications)
2. Add the bot token to `config.yaml` under `discord.bot_token`
3. Set allowed channels and admin user ID
4. Restart Galactic AI

### WhatsApp
Uses the official Meta Cloud API. Requires a Meta Business account and phone number.

Set `whatsapp.phone_number_id`, `whatsapp.access_token`, and `whatsapp.verify_token` in `config.yaml`.

### Gmail
Monitors your inbox via IMAP. AI can read, respond to, and summarize emails.

Set `gmail.email` and `gmail.app_password` in `config.yaml`. Requires a Gmail App Password (not your login password).

---

## Chrome Extension — Galactic Browser

Control your real Chrome browser through Galactic AI with the included Chrome extension:

1. Open `chrome://extensions` in Chrome
2. Enable "Developer mode" (top right)
3. Click "Load unpacked" → select the `chrome-extension/` folder
4. Click the Galactic AI icon in the toolbar → enter your passphrase → Connect

**Features:**
| Feature | Description |
|---|---|
| **Browser Control** | Navigate, click, type, scroll — the AI controls your actual Chrome tabs |
| **Page Reading** | Accessibility tree snapshots for understanding any page |
| **Side Panel Chat** | Chat with Byte in a Chrome side panel with streaming responses |
| **Tab Management** | List, switch, and interact with all open tabs |
| **Form Filling** | AI can fill forms, click buttons, and interact with page elements |
| **JavaScript Execution** | Run arbitrary JavaScript in the page context |

27 browser tools: `chrome_navigate`, `chrome_read_page`, `chrome_screenshot`, `chrome_zoom`, `chrome_click`, `chrome_find`, `chrome_execute_js`, `chrome_tabs_list`, `chrome_form_input`, `chrome_get_page_text`, `chrome_scroll_to`, `chrome_drag`, `chrome_right_click`, `chrome_triple_click`, `chrome_upload`, `chrome_resize`, `chrome_read_network`, `chrome_get_network_body`, `chrome_wait`, `chrome_gif_start`, `chrome_gif_stop`, `chrome_gif_export`.

---

## Social Media (Optional)

Post, search, and manage social media accounts directly through the AI:

### Twitter/X
Set `social_media.twitter` keys in `config.yaml` (consumer_key, consumer_secret, access_token, access_token_secret).

**Tools:** `twitter_post`, `twitter_reply`, `twitter_search`, `twitter_mentions`

### Reddit
Set `social_media.reddit` keys in `config.yaml` (client_id, client_secret, username, password).

**Tools:** `reddit_post`, `reddit_comment`, `reddit_search`, `reddit_inbox`

---

## Image Generation

Generate images directly in chat or from Telegram:

| Model | Provider | Quality |
|---|---|---|
| Imagen 4 Ultra | Google | Highest quality |
| Imagen 4 | Google | High quality, fast |
| Imagen 4 Fast | Google | Fastest |
| FLUX.1 Dev | NVIDIA / Black Forest Labs | Excellent detail |
| FLUX.1 Schnell | NVIDIA / Black Forest Labs | Very fast |
| Stable Diffusion 3.5 Large | NVIDIA / Stability AI | Versatile |

In Telegram: `/model` → Image Models to select your preferred generation backend.

---

## Video Generation

Generate AI video clips directly in chat using Google Veo:

| Mode | Description |
|---|---|
| **Text-to-Video** | Describe a scene and Veo generates a video clip (4s, 6s, or 8s) |
| **Image-to-Video** | Animate a still image (from Imagen, FLUX, or SD3.5) into motion video |

Videos play inline in the Control Deck chat with an HTML5 player (controls, autoplay, loop) and a download link. Configurable resolution (720p, 1080p, 4K), aspect ratio (16:9, 9:16), and negative prompts.

Multi-provider architecture — Google Veo is the day-one provider, with Runway Gen-4, Kling, and Luma Dream Machine planned.

---

## Personality

Choose how your AI presents itself:

- **Byte** (default) — a techno-hippie AI familiar. Chill, resourceful, opinionated, curious about stars and code.
- **Custom** — set your own name, soul, and user context in the Setup Wizard or `config.yaml`.
- **Generic** — neutral, professional, no personality flavor.
- **Files** — automatically activated when you import your own IDENTITY.md, SOUL.md, and USER.md from OpenClaw or elsewhere.

```yaml
# config.yaml
personality:
  mode: byte          # byte | custom | generic | files
  name: Byte
  soul: ""            # only used when mode=custom
  user_context: ""    # only used when mode=custom
```

---

## Updating

One command — pulls the latest release directly from GitHub, no manual download needed:

```powershell
# Windows (run from your Galactic AI folder)
.\update.ps1

# Linux / macOS
./update.sh
```

Pin to a specific version if needed:
```powershell
.\update.ps1 -Version v0.9.0   # Windows
./update.sh v0.9.0              # Linux / macOS
```

The updater will:
- Check GitHub for the latest release and skip if you're already up to date
- Back up your `config.yaml` to `logs/backups/` before touching anything
- Update all source files while **never touching** your config, API keys, memory files, or chat history
- Run `pip install --upgrade` to keep dependencies current

---

## Remote Access

Enable secure remote connections to Galactic AI from any device:

```yaml
# config.yaml
web:
  remote_access: true    # Binds to 0.0.0.0 instead of localhost
```

When enabled, Galactic AI:
- Binds to `0.0.0.0` (all network interfaces) on plain HTTP
- Requires JWT authentication on all API endpoints
- Rate-limits API calls (60/min) and login attempts (5/min)
- Automatically adds a Windows Firewall inbound rule for port 17789 (private networks)
- Local connections from `127.0.0.1`/`::1` always bypass auth so the PC is never locked out
- Logs a startup warning that remote access is active

| Layer | Protection |
|---|---|
| Transport | Plain HTTP on LAN (no TLS — avoids ERR_EMPTY_RESPONSE from self-signed certs) |
| Auth | JWT tokens (HMAC-SHA256, 24h expiry) on all `/api/*` endpoints |
| Localhost | `127.0.0.1` and `::1` bypass auth — PC browser always has access |
| Brute Force | Rate limiting (5 login attempts/min per IP) |
| CORS | Configurable allowed origins |
| WebSocket | JWT token validation via query parameter |

---

## File Structure

```
Galactic-AI/
├── galactic_core_v2.py       # Main entry point + orchestrator
├── gateway_v2.py             # LLM routing + 110-tool ReAct loop
├── web_deck.py               # Web Control Deck (http://127.0.0.1:17789)
├── remote_access.py          # JWT auth, TLS, rate limiting, CORS middleware
├── telegram_bridge.py        # Telegram bot + voice I/O + image model selector
├── chrome-extension/            # Galactic Browser Chrome extension
│   ├── manifest.json            # Extension manifest (MV3)
│   ├── background.js            # Service worker + WebSocket bridge
│   ├── content.js               # Page interaction (accessibility, clicks, forms)
│   ├── popup.html/js            # Auth popup
│   ├── sidepanel.html/js/css    # Side panel chat interface
│   └── icons/                   # Extension icons
├── discord_bridge.py         # Discord bot bridge
├── whatsapp_bridge.py        # WhatsApp Cloud API bridge
├── gmail_bridge.py           # Gmail IMAP bridge
├── personality.py            # AI personality + MEMORY.md + VAULT.md loader
├── memory_module_v2.py       # Persistent memory (memory_aura.json)
├── model_manager.py          # 14-provider model management
├── ollama_manager.py         # Ollama auto-discovery + health monitoring
├── scheduler.py              # Cron-style task scheduler (APScheduler)
├── nvidia_gateway.py         # NVIDIA NIM image generation gateway
├── splash.py                 # Startup splash screen
├── VAULT-example.md          # Template for private credentials (copy to VAULT.md)
├── config.yaml               # All configuration (generated by setup wizard)
├── install.ps1 / install.sh  # One-command installers
├── launch.ps1 / launch.sh    # Launchers
├── update.ps1 / update.sh    # Safe updaters (never touch your data)
└── plugins/
    ├── browser_executor_pro.py   # Playwright browser automation (56 actions)
    ├── shell_executor.py         # Shell command execution
    ├── subagent_manager.py       # Multi-agent orchestration
    ├── chrome_bridge.py          # Chrome extension WebSocket bridge (27 tools)
    ├── social_media.py           # Twitter/X + Reddit integration (8 tools)
    ├── desktop_tool.py           # OS-level mouse/keyboard/screenshot automation
    └── ping.py                   # Connectivity monitoring
```

---

## Security

- Web UI runs on **localhost only** by default (`127.0.0.1`) — not exposed to the internet
- Optional **remote access mode** with JWT authentication, rate limiting, and auto-firewall rule (Windows)
- Protected by a passphrase set in the setup wizard (stored as SHA-256 hash, plaintext never saved)
- API keys live in `config.yaml` on your machine — **never committed to git** (excluded by `.gitignore`)
- `VAULT.md` (personal credentials) is gitignored and protected by the updater
- Ollama runs 100% on your machine — zero data leaves your computer in local mode
- Per-tool timeout (configurable, default 60s) prevents any single operation from hanging the system
- speak() wall-clock timeout (default 600s) caps the entire ReAct loop duration
- Automatic GitHub update notifications keep you on the latest version

---

## Troubleshooting

**"No module named 'aiohttp'"**
Run `pip install -r requirements.txt` (or `pip3` on Linux/macOS).

**"playwright._impl._errors.Error: Executable doesn't exist"**
Run `playwright install chromium`.

**Ollama models not showing up?**
Make sure Ollama is running: `ollama serve` or launch the Ollama app. Galactic AI polls for models every 60 seconds.

**Web UI won't load?**
Check that port 17789 is free. Change it in `config.yaml` under `web.port`.

**Voice messages not being transcribed?**
You need an OpenAI or Groq API key configured in the setup wizard for speech-to-text.

**Memory tab is empty?**
Click into the Memory tab — it auto-creates the .md files with starter templates on first visit.

**Telegram /model menu shows empty provider?**
Make sure the provider's API key is set in `config.yaml`. Providers with empty keys are still listed but will fail when selected.

**AI response taking too long in Telegram?**
Individual tools time out after 60 seconds. The overall response limit is 180 seconds. If a tool hangs, it will be skipped with an error message and the AI will try another approach.

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

## License

MIT License — see LICENSE file.

---

## Version History

| Version | Highlights |
|---|---|
| **v1.1.4** | 🛰️ Telegram UX update — `/status` lite/full (`/status`, `/status full`, `--full`, `-f`); `/help` + command menu updated • 🧠 Restart resilience: conversation auto-recall injection + boot recall banner |
| **v1.1.3** | 🔧 Chrome extension parity — 11 new tools (16 → 27 total): `chrome_zoom`, `chrome_drag`, `chrome_right_click`, `chrome_triple_click`, `chrome_upload`, `chrome_resize`, `chrome_get_network_body`, `chrome_wait`, `chrome_gif_start/stop/export`; contenteditable fix (X.com, Notion, Reddit); screenshot now returns real image to LLM |
| **v1.1.1** | 🌐 Chrome extension (Galactic Browser) with 10 browser tools, side panel chat, real-time page interaction; 📱 Social media plugin (Twitter/X + Reddit, 8 tools); 🔧 System-wide [No response] fix (native tool_calls capture); 📨 Telegram reliability overhaul (Markdown fallback, message splitting, CancelledError fix) |
| **v1.1.0** | 💰 Token cost dashboard (6 summary cards, 9 currencies, persistent JSONL tracking, real token extraction); OpenRouter expansion (6 → 26 curated models across Frontier/Strong/Fast tiers); Chart.js removal for stability |
| **v1.0.9** | 🎬 Video generation via Google Veo (text-to-video + image-to-video), inline HTML5 player; NVIDIA provider hardening (streaming fixes, cold-start retry, broken SSE workaround); new models (Nemotron Super 49B, Nano 9B, Phi-3 Medium, DeepSeek V3.2); HuggingFace URL migration; conventional bottom-up chat scroll; bulletproof shutdown |
| **v1.0.8** | 🔧 Model persistence definitive fix — safe read-modify-write config saves, defensive model-key writeback; Imagen 4 safety filter fix; inline image display diagnostics |
| **v1.0.7** | 🔄 Newest-first scroll, shutdown/restart buttons, Imagen 4 SDK migration to google-genai, SD3.5 NVIDIA fix, SubAgent overhaul |
| **v1.0.6** | 🧠 VAULT/personality fix — workspace path now resolves correctly after install migration; smart routing no longer misclassifies file uploads as coding tasks; Telegram timeout respects global speak_timeout ceiling |
| **v1.0.5** | 🔌 Agent loop resilience — circuit breaker (3 consecutive failures stops tool spam), progressive backpressure (50%/80% turn-budget nudges), tool repetition guard, model lock during active tasks, smart routing auto-restore |
| **v1.0.4** | 🔧 Model persistence fix — selected primary model now survives restarts (both the Models tab quick-switch and the Settings tab now persist to config.yaml) |
| **v1.0.3** | 🎤 Voice input mic button in Control Deck chat bar, 🔥 auto-Windows Firewall rule on remote_access startup, plain HTTP LAN mode (no TLS — fixes ERR_EMPTY_RESPONSE), em dash updater fix |
| **v1.0.2** | Localhost bypass for remote auth (PC never locked out), QR code compatibility fix, Test Voice button now plays audio, desktop shortcut icon added |
| **v1.0.1** | Config auto-migration for missing sections, updater `-Force` flag, missing release ZIP assets fixed |
| **v1.0.0** | 🌐 Remote Access mode, 🔑 JWT authentication, 🛡️ rate limiting, 🔒 CORS, 🎙️ voice API (TTS/STT), settings model save bug fix |
| **v0.9.2** | Resilient model fallback chain with cooldowns, 16 new tools (archives, HTTP, env vars, window management, system info, QR codes, text transforms), expanded Status screen with 30+ fields, per-tool configurable timeouts, speak() wall-clock timeout, shell command timeout |
| **v0.9.0** | Discord/WhatsApp/Gmail bridges, Imagen 4, Telegram image model selector, Thinking tab persistence, chat timestamps, per-tool timeout, graceful shutdown fix, all providers in Telegram model menu |
| **v0.8.1** | Typing indicator heartbeat fix, fast Ctrl+C shutdown, duplicate message guard |
| **v0.8.0** | 17 new tools — clipboard, notifications, window management, HTTP requests, QR codes, system info, text transforms, SD3.5 image gen, FLUX auto-generate |
| **v0.7.9** | Image delivery to Telegram & Control Deck, FLUX auto-generate, dual FLUX API keys |
| **v0.7.8** | 9 new NVIDIA models, FLUX image gen tool, thinking models, file attachment fix |
| **v0.7.7** | Enhanced browser automation — accessibility-driven interactions, network interception |
| **v0.7.6** | Desktop automation plugin (pyautogui), template matching, clipboard tools |
| **v0.7.5** | Sub-agent orchestration, parallel task execution, multi-agent workflows |
| **v0.7.4** | Browser session save/restore, geolocation spoofing, proxy support, media emulation |
| **v0.7.3** | Browser tracing, iframe support, storage tools, advanced browser control |
| **v0.7.2** | NVIDIA single-key setup, quick-pick model chips, custom model field, Ollama 10-min timeout |
| **v0.7.1** | Persistent memory, voice I/O, chat persistence, personality config, one-command auto-updater |
| **v0.7.0** | 14 AI providers, Gemini dupe fix, TTS config, OpenClaw migration step, expanded installer |
| **v0.6.0-Alpha** | Initial public release — 72 tools, 5 providers, Telegram bot, web control deck |
