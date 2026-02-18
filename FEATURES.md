# Galactic AI — Features

Complete feature reference for Galactic AI Automation Suite v0.6.0-Alpha.

---

## Core Architecture

### AsyncIO Runtime
The entire system runs on Python's `asyncio` event loop. Every subsystem — LLM gateway, web server, Telegram bridge, plugin engine, Ollama manager, task scheduler — is fully non-blocking. Nothing stalls the core.

### ReAct Agentic Loop
The AI operates in a **Think > Act > Observe > Answer** loop. It can chain multiple tool calls in sequence, observe the results, reason about what to do next, and keep going until the task is complete. This is the same architecture used by frontier AI agents.

### Graceful Lifecycle Management
- Single **Ctrl+C** triggers a clean shutdown of all subsystems
- Signal handlers for SIGINT and SIGTERM on all platforms
- All background tasks are cancelled and awaited
- No orphaned processes or socket errors on exit

---

## AI Providers

Galactic AI supports five LLM providers out of the box. Switch between them at any time from the web UI or Telegram.

| Provider | Auth | Models |
|----------|------|--------|
| **Google Gemini** | API key | gemini-2.5-flash, gemini-2.5-pro, gemini-3-pro-preview |
| **Anthropic Claude** | API key | claude-sonnet-4-5, claude-opus-4-6 |
| **xAI Grok** | API key | grok-4, grok-3 |
| **NVIDIA AI** | API key(s) | deepseek-v3.2, qwen3-coder-480b, glm5, llama-3.3-70b, kimi, stepfun |
| **Ollama (Local)** | None | Any model you pull — qwen3, llama3.3, deepseek-coder-v2, phi4, mistral, etc. |

### Multi-Key NVIDIA Routing
NVIDIA hosts models from many vendors. Galactic AI automatically routes to the correct API key based on the model you select (DeepSeek key for DeepSeek models, Qwen key for Qwen models, etc.). Configure up to 5 separate NVIDIA keys.

### Anthropic Native API
Full native Anthropic Messages API support with proper `x-api-key` authentication, `anthropic-version` headers, separate system prompts, and multi-turn role alternation.

### Smart Model Routing
Enable `smart_routing: true` in config to let the system automatically pick the best model for each task type (coding, reasoning, creative, vision, quick queries).

### Auto-Fallback
If the primary provider fails, Galactic AI automatically falls back to a configurable secondary provider (default: Ollama local). Recovery happens automatically after a cooldown period.

---

## Ollama Local Model Support

### Auto-Discovery
Galactic AI automatically detects all models installed in Ollama. No manual configuration needed — pull a model with `ollama pull` and it appears in the UI within 60 seconds.

### Health Monitoring
Background health checks ensure the system knows instantly when Ollama goes online or offline. The web UI shows real-time Ollama health status.

### Context Window Awareness
For every discovered model, the system queries the actual context window size from Ollama and adjusts conversation history trimming accordingly.

### Tool Calling for Local Models
Ollama models get enhanced system prompts with full parameter schemas for all 72 tools, plus few-shot examples for reliable JSON tool call generation. Temperature is tuned to 0.3 for consistent structured output.

### Streaming Responses
Token-by-token streaming from Ollama models, broadcast in real-time to the web UI via WebSocket.

---

## 72 Built-In Tools

### File System (3 tools)
| Tool | Description |
|------|-------------|
| `read_file` | Read the contents of any file |
| `write_file` | Write or create a file |
| `edit_file` | Make targeted edits to existing files (find/replace) |

### Shell & Process (5 tools)
| Tool | Description |
|------|-------------|
| `exec_shell` | Execute any shell command |
| `process_start` | Start a long-running background process |
| `process_status` | Check status of running processes |
| `process_kill` | Terminate a process |
| `schedule_task` | Schedule a recurring or one-shot task |
| `list_tasks` | View all scheduled tasks |

### Web & Search (2 tools)
| Tool | Description |
|------|-------------|
| `web_search` | Search DuckDuckGo (no API key needed) |
| `web_fetch` | Fetch and parse any URL |

### Vision (1 tool)
| Tool | Description |
|------|-------------|
| `analyze_image` | Analyze images using Gemini Vision, Ollama multimodal, or other providers |

### Memory (2 tools)
| Tool | Description |
|------|-------------|
| `memory_search` | Semantic search across persistent memory |
| `memory_imprint` | Store new information in persistent memory |

### Audio (1 tool)
| Tool | Description |
|------|-------------|
| `text_to_speech` | Convert text to spoken audio |

### Browser Automation (56 tools)

Powered by Playwright. Supports **Chromium**, **Firefox**, and **WebKit** engines.

**Navigation & Pages**
| Tool | Description |
|------|-------------|
| `open_browser` | Navigate to a URL |
| `browser_search` | Search Google |
| `browser_new_tab` | Open a new tab |
| `screenshot` | Take a full-page screenshot |
| `browser_snapshot` | Get accessibility tree of the page |
| `browser_pdf` | Save page as PDF |

**Interaction — By Selector**
| Tool | Description |
|------|-------------|
| `browser_click` | Click an element by CSS selector |
| `browser_type` | Type text into an element by selector |
| `browser_fill_form` | Fill multiple form fields at once |
| `browser_select` | Select dropdown option by selector |
| `browser_hover` | Hover over an element by selector |
| `browser_scroll_into_view` | Scroll element into viewport by selector |
| `browser_drag` | Drag and drop by selector |
| `browser_highlight` | Highlight element by selector |
| `browser_download` | Download a file by clicking a selector |
| `browser_upload` | Upload a file to an input element |

**Interaction — By Accessibility Ref**
| Tool | Description |
|------|-------------|
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
|------|-------------|
| `browser_click_coords` | Click at exact x,y coordinates |
| `browser_scroll` | Scroll the page (up, down, left, right) |
| `browser_press` | Press keyboard keys |
| `browser_resize` | Resize the browser window |

**Data Extraction**
| Tool | Description |
|------|-------------|
| `browser_extract` | Extract structured data from the page |
| `browser_execute_js` | Run arbitrary JavaScript |
| `browser_console_logs` | Read browser console output |
| `browser_page_errors` | Get JavaScript errors |
| `browser_network_requests` | Inspect network traffic |
| `browser_response_body` | Get the response body of a network request |

**Storage**
| Tool | Description |
|------|-------------|
| `browser_get_local_storage` | Read localStorage values |
| `browser_set_local_storage` | Write localStorage values |
| `browser_clear_local_storage` | Clear all localStorage |
| `browser_get_session_storage` | Read sessionStorage values |
| `browser_set_session_storage` | Write sessionStorage values |
| `browser_clear_session_storage` | Clear all sessionStorage |

**Advanced Browser Control**
| Tool | Description |
|------|-------------|
| `browser_wait` | Wait for elements, navigation, or timeouts |
| `browser_dialog` | Handle browser dialogs (alert, confirm, prompt) |
| `browser_set_offline` | Simulate offline/online network conditions |
| `browser_set_headers` | Set custom HTTP headers |
| `browser_set_geolocation` | Spoof GPS coordinates |
| `browser_clear_geolocation` | Clear geolocation override |
| `browser_emulate_media` | Emulate media features (dark mode, print, etc.) |
| `browser_set_locale` | Change browser locale |
| `browser_set_proxy` | Route traffic through a proxy |

**Frames**
| Tool | Description |
|------|-------------|
| `browser_get_frames` | List all iframes on the page |
| `browser_frame_action` | Execute actions inside a specific iframe |

**Session Management**
| Tool | Description |
|------|-------------|
| `browser_save_session` | Save cookies and storage state to a file |
| `browser_load_session` | Restore a saved session |

**Tracing & Debugging**
| Tool | Description |
|------|-------------|
| `browser_trace_start` | Start recording a Playwright trace |
| `browser_trace_stop` | Stop recording and save trace file |

**Network Interception**
| Tool | Description |
|------|-------------|
| `browser_intercept` | Intercept and modify network requests |
| `browser_clear_intercept` | Remove all network intercepts |

---

## Web Control Deck

The web UI runs at **http://127.0.0.1:17789** and provides a full graphical interface.

### Tabs
- **Chat** — Full conversational interface with the AI, including tool use output
- **Status** — Live telemetry: provider, model, token usage, uptime, plugin states
- **Tools** — Browse all 72 tools with descriptions and parameter info
- **Plugins** — Enable/disable plugins with toggle switches
- **Memory** — Read and edit the AI's persistent memory files (MEMORY.md, IDENTITY.md, SOUL.md, USER.md, TOOLS.md)
- **Ollama** — Health status, discovered models, context window sizes
- **Logs** — Real-time system log stream

### Real-Time Updates
The web UI maintains a persistent WebSocket connection. Status telemetry, chat messages, Ollama health, logs, and streaming responses all update live without page refreshes.

### Login Security
The web UI is protected by a passphrase set during the first-run wizard. Passwords are stored as SHA-256 hashes — the plaintext is never saved.

### Model Switching
Switch between any provider and model from the web UI at any time. The change takes effect immediately for the next message.

---

## Telegram Bot

Control Galactic AI remotely from your phone via Telegram.

### Commands
| Command | Description |
|---------|-------------|
| `/status` | System telemetry (provider, model, uptime, tokens) |
| `/model` | Switch to a different AI model |
| `/models` | Configure primary and fallback models |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Take a screenshot of the current browser page |
| `/cli` | Execute a shell command and get the output |
| `/compact` | Compact conversation context to free memory |
| `/leads` | View the lead pipeline (if Sniper plugin is active) |
| `/help` | Interactive help menu |

### Natural Language Chat
Send any message without a `/` command and the AI responds naturally, with full access to all 72 tools.

### Web UI Integration
Telegram messages appear in the web UI chat log in real-time. You see both sides of the conversation from either interface.

---

## Plugin System

Plugins are Python classes that extend core functionality. Enable or disable them at runtime from the web UI.

### Built-In Plugins
| Plugin | Description |
|--------|-------------|
| **BrowserExecutorPro** | Playwright-powered browser automation (Chromium/Firefox/WebKit) |
| **ShellExecutor** | System shell command execution |
| **SubAgentManager** | Spawn and manage multiple parallel AI agents |
| **Ping** | Connectivity monitoring |

### Custom Plugins
Drop a Python file in the `plugins/` folder. Any class with a `run()` coroutine method is automatically picked up as a plugin.

---

## Memory System

### Persistent Files
The AI reads and writes `.md` files in the workspace directory:
- **MEMORY.md** — Long-term knowledge and conversation history
- **IDENTITY.md** — AI personality and behavioral directives
- **SOUL.md** — Core values and interaction style
- **USER.md** — Information about the user
- **TOOLS.md** — Tool usage notes and preferences

### Semantic Memory Imprinting
The AI automatically imprints important information into memory for later recall. Memory is searchable via the `memory_search` tool.

### Workspace Imprint on Boot
On startup, all personality files are loaded into the AI's active context so it remembers who it is and who you are.

---

## Task Scheduler

Schedule recurring or one-shot tasks that the AI executes automatically:
- Cron-style recurring tasks with configurable intervals
- One-shot delayed tasks
- Tasks can invoke any tool or run arbitrary shell commands
- View and manage all scheduled tasks from the AI or web UI

---

## Model Aliases

Define shorthand aliases in `config.yaml` for quick model switching:

```yaml
aliases:
  gemini-flash: google/gemini-2.5-flash
  claude-sonnet: anthropic/claude-sonnet-4-5
  grok: xai/grok-4
  deepseek: nvidia/deepseek-ai/deepseek-v3.2
  qwen: ollama/qwen3:8b
```

Use the alias name anywhere you'd use a full model path.

---

## Configuration Reference

All settings live in `config.yaml`:

| Section | Key | Description |
|---------|-----|-------------|
| `gateway.provider` | Primary AI provider | `google`, `anthropic`, `xai`, `nvidia`, `ollama` |
| `gateway.model` | Active model name | e.g. `gemini-2.5-flash` |
| `models.auto_fallback` | Enable auto-fallback | `true` / `false` |
| `models.fallback_provider` | Fallback provider | e.g. `ollama` |
| `models.fallback_model` | Fallback model | e.g. `qwen3:8b` |
| `models.streaming` | Enable response streaming | `true` / `false` |
| `models.smart_routing` | Auto-select model by task type | `true` / `false` |
| `providers.*.apiKey` | API keys per provider | String |
| `providers.nvidia.keys.*` | Per-vendor NVIDIA keys | String |
| `providers.ollama.baseUrl` | Ollama server URL | Default: `http://127.0.0.1:11434/v1` |
| `browser.engine` | Browser engine | `chromium`, `firefox`, `webkit` |
| `browser.headless` | Headless mode | `true` / `false` |
| `telegram.bot_token` | Telegram bot token | From @BotFather |
| `telegram.admin_chat_id` | Your Telegram user ID | From @userinfobot |
| `web.port` | Web UI port | Default: `17789` |
| `web.password_hash` | SHA-256 password hash | Generated via setup wizard |
| `system.port` | Internal socket port | Default: `9999` |

---

## Platform Support

| Platform | Status |
|----------|--------|
| Windows 10/11 | Fully supported |
| Linux (Ubuntu, Debian, Arch, etc.) | Fully supported |
| macOS (Intel & Apple Silicon) | Fully supported |
| WSL2 | Supported |

---

## Version

**v0.6.0-Alpha** — Galactic AI Automation Suite
