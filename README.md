# Galactic AI — Automation Suite

**Sovereign. Universal. Fast.**

A powerful, local-first AI automation platform with 92+ built-in tools, true persistent memory, voice I/O, browser automation, 14 AI providers, multi-platform messaging bridges, and a real-time web Control Deck.

Run fully local with Ollama (no API keys, no cloud, no tracking), or connect to any of 14 cloud providers. Your data stays yours.

---

## What Makes Galactic AI Different

### True Persistent Memory — Without Burning Tokens
Most AI tools forget everything the moment you close the tab. Galactic AI doesn't.

When the AI learns something important, it writes it to **MEMORY.md** on disk. The next time it starts up, it reads that file and immediately knows everything it learned in past sessions — no searches, no extra API calls, just the file loaded once into the system prompt. As the AI learns more, the memory file grows. You can edit it directly in the Control Deck.

This is fundamentally different from session memory or expensive vector search on every message.

### 14 AI Providers, One Interface
Switch between Google Gemini, Claude, GPT, Grok, Groq, Mistral, DeepSeek, NVIDIA, and more — or run completely offline with Ollama. Change providers mid-conversation. Set automatic fallback so the AI never goes down.

### 92+ Tools, Real Agent Behavior
The AI doesn't just answer questions — it acts. It browses the web, reads and writes files, runs shell commands, controls a full Chromium browser, generates images, manages schedules, sends messages across platforms, and more. It chains tool calls in a ReAct loop until the task is done.

### Voice I/O + Multi-Platform Messaging
Send a voice message to your Telegram bot — the AI transcribes it with Whisper, thinks, responds with a voice message back. Or message from Discord, WhatsApp, or Gmail. Control everything from wherever you are.

---

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
| **Chat** | Talk to your AI with full tool support; timestamps on every message; chat history survives page refreshes |
| **Thinking** | Real-time agent trace — watch the ReAct loop think and act step by step; persists across page refreshes |
| **Status** | Live provider, model, token usage, uptime, and plugin telemetry |
| **Models** | Browse and switch all 92+ models, ordered best-to-worst with tier indicators |
| **Tools** | Browse all 92+ built-in tools with descriptions and parameters |
| **Plugins** | Enable/disable plugins with one click |
| **Memory** | Edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md directly in-browser |
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

All four files are loaded from disk on startup and injected into every system prompt. The AI always knows who it is and who you are.

### 2. MEMORY.md (grows automatically)
When you tell the AI to remember something, or when it decides something is worth keeping, it appends a timestamped entry to `MEMORY.md`. This file is then available in **every future conversation** automatically. You can also edit it directly in the Memory tab.

### 3. memory_aura.json (searchable knowledge base)
Facts, documents, and imprinted knowledge stored in a local JSON index. The AI can search this store at any time using the `memory_search` tool.

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
| `/status` | Live system telemetry |
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

## File Structure

```
Galactic-AI/
├── galactic_core_v2.py       # Main entry point + orchestrator
├── gateway_v2.py             # LLM routing + 92-tool ReAct loop
├── web_deck.py               # Web Control Deck (http://127.0.0.1:17789)
├── telegram_bridge.py        # Telegram bot + voice I/O + image model selector
├── discord_bridge.py         # Discord bot bridge
├── whatsapp_bridge.py        # WhatsApp Cloud API bridge
├── gmail_bridge.py           # Gmail IMAP bridge
├── personality.py            # AI personality + MEMORY.md loader
├── memory_module_v2.py       # Persistent memory (memory_aura.json)
├── model_manager.py          # 14-provider model management
├── ollama_manager.py         # Ollama auto-discovery + health monitoring
├── scheduler.py              # Cron-style task scheduler (APScheduler)
├── nvidia_gateway.py         # NVIDIA NIM image generation gateway
├── splash.py                 # Startup splash screen
├── config.yaml               # All configuration (generated by setup wizard)
├── install.ps1 / install.sh  # One-command installers
├── launch.ps1 / launch.sh    # Launchers
├── update.ps1 / update.sh    # Safe updaters (never touch your data)
└── plugins/
    ├── browser_executor_pro.py   # Playwright browser automation (56 actions)
    ├── shell_executor.py         # Shell command execution
    ├── subagent_manager.py       # Multi-agent orchestration
    ├── desktop_tool.py           # OS-level mouse/keyboard/screenshot automation
    └── ping.py                   # Connectivity monitoring
```

---

## Security

- Web UI runs on **localhost only** (`127.0.0.1`) — not exposed to the internet
- Protected by a passphrase set in the setup wizard (stored as SHA-256 hash, plaintext never saved)
- API keys live in `config.yaml` on your machine — **never committed to git** (excluded by `.gitignore`)
- Ollama runs 100% on your machine — zero data leaves your computer in local mode
- Per-tool timeout (60s) prevents any single operation from hanging the system

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
