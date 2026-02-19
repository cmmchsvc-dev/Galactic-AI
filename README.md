# Galactic AI — Automation Suite

**Sovereign. Universal. Fast.**

A powerful, local-first AI automation platform with 72+ built-in tools, true persistent memory, voice I/O, browser automation, 14 AI providers, and a real-time web control deck.

Run fully local with Ollama (no API keys, no cloud, no tracking), or connect to any of 14 cloud providers. Your data stays yours.

---

## What Makes Galactic AI Different

### True Persistent Memory — Without Burning Tokens
Most AI tools forget everything the moment you close the tab. Galactic AI doesn't.

When the AI learns something important, it writes it to **MEMORY.md** on disk. The next time it starts up, it reads that file and immediately knows everything it learned in past sessions — no searches, no extra API calls, just the file loaded once into the system prompt. As the AI learns more, the memory file grows. You can edit it directly in the Control Deck.

This is fundamentally different from session memory or expensive vector search on every message.

### 14 AI Providers, One Interface
Switch between Google Gemini, Claude, GPT, Grok, Groq, Mistral, Cohere, DeepSeek, Perplexity, and more — or run completely offline with Ollama. Change providers mid-conversation. Set automatic fallback so the AI never goes down.

### 72+ Tools, Real Agent Behavior
The AI doesn't just answer questions — it acts. It browses the web, reads and writes files, runs shell commands, controls a full Chromium browser, manages schedules, searches memory, converts text to speech, and more. It chains tool calls in a ReAct loop until the task is done.

### Voice I/O via Telegram
Send a voice message to your Telegram bot → the AI transcribes it with Whisper, thinks, responds with a voice message back. Send a text → get text back. Control everything from your phone.

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

## Setup Wizard (7 Steps)

After launching, open **http://127.0.0.1:17789**. The Setup Wizard appears automatically on first run:

| Step | What You Configure |
|---|---|
| 1 | **Primary Provider** — your main AI (Google, Anthropic, OpenAI, Groq, Ollama, etc.) |
| 2 | **Additional API Keys + TTS** — extra providers and ElevenLabs voice |
| 3 | **Telegram** — optional Telegram bot for mobile access |
| 4 | **Security** — passphrase to protect the web UI |
| 5 | **Personality** — choose Byte, Custom, or Generic Assistant |
| 6 | **OpenClaw Migration** — import your existing memory/identity files |
| 7 | **Review & Launch** — confirm everything and start |

> **Zero-key mode:** Choose Ollama as your provider in Step 1 and skip all API key steps. Pull a model with `ollama pull qwen3:8b` and you're running 100% locally.

---

## AI Providers

| Provider | Models | Free Tier |
|---|---|---|
| **Google Gemini** | gemini-2.5-flash, gemini-2.5-pro | Yes |
| **Anthropic Claude** | claude-sonnet-4-5, claude-opus-4-6 | No |
| **OpenAI** | gpt-4o, gpt-4o-mini, o1, o3 | No |
| **xAI Grok** | grok-4, grok-3 | No |
| **Groq** | llama3, mixtral, gemma — blazing fast | Yes |
| **Mistral** | mistral-large, codestral | Yes |
| **Cohere** | command-r-plus | Yes |
| **NVIDIA AI** | deepseek-v3.2, qwen3-coder-480b, llama-3.3-70b | Yes |
| **Together AI** | 100+ open models | Yes |
| **Perplexity** | sonar-pro, sonar | No |
| **Fireworks AI** | firefunction-v2, llama-v3 | Yes |
| **DeepSeek** | deepseek-chat, deepseek-coder | Yes |
| **OpenRouter** | Any model via unified API | Yes |
| **Ollama (Local)** | Any model you pull — qwen3, llama3.3, phi4, mistral, deepseek-coder | **No key needed** |

---

## Web Control Deck

The control deck at **http://127.0.0.1:17789** gives you full control:

| Tab | What's There |
|---|---|
| **Chat** | Talk to your AI with full tool support; chat history survives page refreshes |
| **Status** | Live provider, model, token usage, uptime, and plugin telemetry |
| **Tools** | Browse and understand all 72+ built-in tools |
| **Plugins** | Enable/disable plugins with one click |
| **Memory** | Edit MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md directly in-browser |
| **Ollama** | Health status, discovered models, context window sizes |
| **Logs** | Real-time system log stream |

---

## Persistent Memory System

Galactic AI has three layers of memory, all persistent across restarts:

### 1. Identity Files (always in every prompt)
- **IDENTITY.md** — who the AI is (name, role, vibe)
- **SOUL.md** — core values and personality
- **USER.md** — who you are, your preferences, context
- **MEMORY.md** — things the AI has learned over time ← **new in v0.7.1**

All four files are loaded from disk on startup and injected into every system prompt. The AI always knows who it is and who you are.

### 2. MEMORY.md (grows automatically)
When you tell the AI to remember something, or when it decides something is worth keeping, it appends a timestamped entry to `MEMORY.md`. This file is then available in **every future conversation** automatically. You can also edit it directly in the Memory tab.

### 3. memory_aura.json (searchable knowledge base)
Facts, documents, and imprinted knowledge stored in a local JSON index. The AI can search this store at any time using the `memory_search` tool.

---

## Telegram Bot (Optional)

Control Galactic AI from your phone:

1. Message [@BotFather](https://t.me/BotFather) → create a new bot → copy the token
2. Enter the token in the Setup Wizard (Step 3)
3. Get your chat ID from [@userinfobot](https://t.me/userinfobot) and enter it too
4. Restart Galactic AI

**Commands:**
| Command | What it does |
|---|---|
| `/status` | Live system telemetry |
| `/model` | Switch AI model |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Take a browser screenshot |
| `/cli` | Run a shell command |
| `/compact` | Compact conversation context |
| `/help` | Interactive menu |

Or just send any message — text or voice — and the AI responds. Voice messages are transcribed automatically and replied to with voice.

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

Extract the new release ZIP into your existing folder and run the updater. Your config, API keys, memory files, and chat history are **never touched**.

```powershell
# Windows
.\update.ps1

# Linux / macOS
./update.sh
```

The updater backs up your `config.yaml` before touching anything.

---

## File Structure

```
Galactic-AI/
├── galactic_core_v2.py       # Main entry point
├── gateway_v2.py             # LLM routing + 72-tool ReAct loop
├── web_deck.py               # Web Control Deck (http://127.0.0.1:17789)
├── telegram_bridge.py        # Telegram bot + voice I/O
├── personality.py            # AI personality + MEMORY.md loader
├── memory_module_v2.py       # Persistent memory (memory_aura.json)
├── model_manager.py          # 14-provider model management
├── ollama_manager.py         # Ollama auto-discovery + health monitoring
├── scheduler.py              # Task scheduling engine
├── config.yaml               # All configuration (generated by setup wizard)
├── install.ps1 / install.sh  # One-command installers
├── launch.ps1 / launch.sh    # Launchers
├── update.ps1 / update.sh    # Safe updaters (never touch your data)
└── plugins/
    ├── browser_executor_pro.py   # Playwright browser automation (56 actions)
    ├── shell_executor.py         # Shell command execution
    ├── subagent_manager.py       # Multi-agent orchestration
    └── ping.py                   # Connectivity monitoring
```

---

## Security

- Web UI runs on **localhost only** (`127.0.0.1`) — not exposed to the internet
- Protected by a passphrase set in the setup wizard (stored as SHA-256 hash, plaintext never saved)
- API keys live in `config.yaml` on your machine — **never committed to git** (excluded by `.gitignore`)
- Ollama runs 100% on your machine — zero data leaves your computer in local mode

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
| **v0.7.1** | True persistent memory (MEMORY.md auto-injection), voice I/O (Whisper STT + TTS), chat persistence, 7-step setup wizard with personality config |
| **v0.7.0** | 14 AI providers, Gemini dupe fix, TTS config, OpenClaw migration step, expanded installer |
| **v0.6.0-Alpha** | Initial public release — 72 tools, 5 providers, Telegram bot, web control deck |
