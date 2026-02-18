# Galactic AI — Automation Suite

**Sovereign. Universal. Fast.**

A powerful, local-first AI automation platform with 72 built-in tools, browser automation, multi-provider LLM support, and a real-time web control deck.

Run fully local with Ollama (no API keys needed), or connect to Google Gemini, Anthropic Claude, xAI Grok, and NVIDIA AI endpoints.

---

## Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **Ollama** (optional, for local models) — [ollama.com/download](https://ollama.com/download)
- **Git** (optional, for cloning) — [git-scm.com](https://git-scm.com/)

---

## Installation

### Step 1 — Clone or Download

```bash
git clone https://github.com/YOUR_USERNAME/galactic-core.git
cd galactic-core
```

Or download and extract the ZIP, then open a terminal in the `galactic-core` folder.

### Step 2 — Install Python Dependencies

Pick the command for your terminal:

**PowerShell (Windows):**
```powershell
pip install aiohttp httpx pyyaml jinja2 beautifulsoup4 playwright cryptography; playwright install chromium
```

**Command Prompt (Windows):**
```cmd
pip install aiohttp httpx pyyaml jinja2 beautifulsoup4 playwright cryptography && playwright install chromium
```

**Bash / Zsh (Linux / macOS):**
```bash
pip3 install aiohttp httpx pyyaml jinja2 beautifulsoup4 playwright cryptography && playwright install chromium
```

> **Note:** If you get a permissions error on Linux/macOS, prefix with `sudo` or use `pip3 install --user`.

### Step 3 — (Optional) Install Ollama for 100% Local AI

If you want to run completely offline with no API keys:

**Windows:**
Download and install from [ollama.com/download](https://ollama.com/download), then:
```powershell
ollama pull qwen3:8b
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen3:8b
```

**macOS:**
```bash
brew install ollama
ollama pull qwen3:8b
```

You can pull any model you want — `qwen3:30b`, `llama3.3:70b`, `deepseek-coder-v2`, `phi4`, etc. Galactic AI auto-discovers all installed Ollama models.

---

## Launch

### PowerShell (Windows) — Recommended
```powershell
.\launch.ps1
```

### Python Direct (Any Terminal)
```bash
python galactic_core_v2.py
```

### Bash (Linux / macOS)
```bash
chmod +x launch.sh
./launch.sh
```

### Shut Down
Press **Ctrl+C** once. Galactic AI will shut down cleanly.

---

## First-Run Setup Wizard

After launching, open your browser to:

```
http://127.0.0.1:17789
```

The **Setup Wizard** appears automatically on first run and walks you through five steps:

1. **Choose Provider** — Select your primary AI provider (Google, Anthropic, xAI, NVIDIA, or Ollama Local)
2. **API Keys** — Enter API keys for the providers you want to use
3. **Telegram** (optional) — Connect a Telegram bot for mobile access
4. **Security** — Set a passphrase to protect the web UI
5. **Review & Save** — Confirm your settings and launch

> If you chose **Ollama Local** as your provider, no API keys are needed. Just make sure Ollama is running (`ollama serve`).

### Manual Configuration

All settings are stored in `config.yaml`. You can edit it directly instead of using the wizard:

```yaml
# Set your primary provider and model
gateway:
  provider: google          # google | anthropic | xai | nvidia | ollama
  model: gemini-2.5-flash

# Add your API keys
providers:
  google:
    apiKey: "YOUR_KEY_HERE"
  anthropic:
    apiKey: "YOUR_KEY_HERE"
  xai:
    apiKey: "YOUR_KEY_HERE"
  nvidia:
    keys:
      deepseek: "YOUR_KEY_HERE"
      qwen: "YOUR_KEY_HERE"
  ollama:
    baseUrl: http://127.0.0.1:11434/v1   # No key needed

# Set a web UI password (SHA-256 hash)
web:
  password_hash: ""   # Generate: python -c "import hashlib; print(hashlib.sha256(b'yourpassword').hexdigest())"
```

To generate a password hash from the command line:

**PowerShell:**
```powershell
python -c "import hashlib; print(hashlib.sha256(b'yourpassword'.replace(b'yourpassword', input('Password: ').encode())).hexdigest())"
```

**Bash:**
```bash
python3 -c "import hashlib; p=input('Password: '); print(hashlib.sha256(p.encode()).hexdigest())"
```

---

## API Keys (Free Tiers Available)

| Provider | Models | Get Key |
|----------|--------|---------|
| Google Gemini | gemini-2.5-flash, gemini-2.5-pro, gemini-3-pro | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Anthropic Claude | claude-sonnet-4-5, claude-opus-4-6 | [console.anthropic.com/keys](https://console.anthropic.com/keys) |
| xAI Grok | grok-4, grok-3 | [console.x.ai](https://console.x.ai) |
| NVIDIA AI | deepseek-v3.2, qwen3-coder-480b, glm5, llama-3.3-70b | [build.nvidia.com](https://build.nvidia.com) |
| Ollama (Local) | qwen3, llama3.3, deepseek-coder-v2, phi4, mistral | [ollama.com](https://ollama.com) — **No key needed** |

---

## Web Control Deck

Once running, the control deck is at **http://127.0.0.1:17789** and includes:

- **Chat** — Talk to your AI with full tool-calling support
- **Status** — Live provider, model, token usage, and uptime telemetry
- **Tools** — Browse and invoke any of the 72 built-in tools
- **Plugins** — Enable/disable plugins with one click
- **Memory Editor** — Read and edit the AI's persistent memory files
- **Ollama Hub** — See all local models, health status, context window sizes
- **Logs** — Real-time system log stream
- **Model Switcher** — Switch between providers and models on the fly

---

## Telegram Bot (Optional)

Control Galactic AI from your phone:

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot
2. Copy the bot token into `config.yaml` under `telegram.bot_token`
3. Get your chat ID from [@userinfobot](https://t.me/userinfobot) and set `telegram.admin_chat_id`
4. Restart Galactic AI

**Telegram Commands:**
| Command | Description |
|---------|-------------|
| `/status` | System telemetry |
| `/model` | Switch AI model |
| `/models` | Configure primary/fallback models |
| `/browser` | Launch browser automation |
| `/screenshot` | Take a browser screenshot |
| `/cli` | Execute a shell command |
| `/compact` | Compact conversation context |
| `/leads` | View lead pipeline |
| `/help` | Interactive menu |

Or just send a normal message to chat with the AI.

---

## File Structure

```
galactic-core/
├── galactic_core_v2.py       # Main entry point
├── gateway_v2.py             # LLM routing + 72-tool ReAct loop
├── web_deck.py               # Web Control Deck (http://127.0.0.1:17789)
├── model_manager.py          # Multi-provider model management
├── ollama_manager.py         # Ollama auto-discovery + health monitoring
├── telegram_bridge.py        # Telegram bot integration
├── memory_module_v2.py       # Persistent memory system
├── scheduler.py              # Task scheduling engine
├── personality.py            # AI personality configuration
├── splash.py                 # Boot screen
├── config.yaml               # All configuration (auto-generated on first run)
├── launch.ps1                # Windows PowerShell launcher
├── launch.sh                 # Linux/macOS launcher
└── plugins/
    ├── browser_executor_pro.py   # Playwright browser automation (72 actions)
    ├── shell_executor.py         # Shell command execution
    ├── subagent_manager.py       # Multi-agent orchestration
    └── ping.py                   # Connectivity monitoring
```

---

## Security Notes

- Web UI runs on **localhost only** (`127.0.0.1`) by default — not exposed to the internet
- Set a passphrase in the setup wizard to protect the control deck
- API keys are stored locally in `config.yaml` — **never commit this file**
- `.gitignore` already excludes `config.yaml`, `logs/`, `workspace/`, and other sensitive paths
- Ollama runs 100% on your machine — no data leaves your computer

---

## Troubleshooting

**"No module named 'aiohttp'"**
Run the install command from Step 2 above.

**"playwright._impl._errors.Error: Executable doesn't exist"**
Run `playwright install chromium` to download the browser engine.

**Ollama models not showing up?**
Make sure Ollama is running (`ollama serve` or launch the Ollama app). Galactic AI polls for models automatically.

**Web UI won't load?**
Check that port 17789 is not in use by another application. You can change it in `config.yaml` under `web.port`.

**Ctrl+C not working?**
A single Ctrl+C triggers graceful shutdown. Wait a moment for all systems to close cleanly.

---

## License

MIT License — see LICENSE file.
