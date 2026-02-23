# Changelog — Galactic AI

All notable changes to Galactic AI are documented here.

---

## v1.1.3 — Chrome Extension Parity (2026-02-23)

### Bug Fixes
- **contenteditable typing**: `performType()` in content.js now uses `document.execCommand('insertText')` for proper SPA support (X.com, Notion, Reddit compose work correctly)
- **screenshot visibility**: `chrome_screenshot` now saves JPEG to disk and returns an actual image to the LLM (not a text description)

### New Tools (11 added, 16 → 27 total)
- `chrome_zoom` — region screenshot for close inspection of UI elements
- `chrome_drag` — click-drag interactions (sliders, reordering)
- `chrome_right_click` — JS context menu trigger
- `chrome_triple_click` — triple-click to select all text
- `chrome_upload` — file upload via Chrome Debugger `DOM.setFileInputFiles`
- `chrome_resize` — viewport resize with mobile/tablet/desktop presets
- `chrome_get_network_body` — fetch full response body for a network request by ID
- `chrome_wait` — wait N seconds between browser actions
- `chrome_gif_start` / `chrome_gif_stop` / `chrome_gif_export` — GIF recorder with Pillow assembly
- `chrome_read_network` now includes `request_id` in each entry

---

## [v1.1.2] — 2026-02-23

### Added
- **⚡ Skills Ecosystem** — Complete architectural evolution of the plugin system. New `GalacticSkill` base class with structured metadata (`skill_name`, `version`, `author`, `description`, `category`, `icon`, `is_core`) and `get_tools()` dynamic tool registration. All capabilities now live in self-contained skill classes instead of the gateway monolith
- **⚡ 6 Core Skills Migrated** — ShellSkill (1 tool), DesktopSkill (8 tools), ChromeBridgeSkill (16 tools), SocialMediaSkill (6 tools), SubAgentSkill (2 tools), BrowserProSkill (55 tools). 88 tool definitions extracted from `gateway_v2.py` into `skills/core/`
- **⚡ AI Self-Authoring** — Byte can write, validate, and load new community skills at runtime. Three new meta-tools: `create_skill` (AST-validated, instantly live), `list_skills` (rich metadata), `remove_skill` (safe unload + file delete). Skills saved to `skills/community/` and tracked in `registry.json`
- **⚡ Community Skill Discovery** — `skills/community/` directory auto-loaded from disk on startup. `registry.json` manifest tracks AI-authored and user-installed community skills
- **⚡ Skills Tab in Control Deck** — Replaces Plugins tab with rich skill cards: icon, display name, CORE/COMMUNITY badge, version, author, description, and tool count preview

---

## [v1.1.1] — 2026-02-23

### Added
- **🌐 Galactic Browser (Chrome Extension)** — Full Chrome extension with popup authentication, side panel chat with streaming responses, and real-time browser interaction via WebSocket bridge. 10 new browser tools: `chrome_navigate`, `chrome_read_page`, `chrome_screenshot`, `chrome_click`, `chrome_find`, `chrome_execute_js`, `chrome_tabs_list`, `chrome_form_input`, `chrome_get_page_text`, `chrome_scroll_to`. Content script provides accessibility tree snapshots, element finding, form interaction, and JavaScript execution in the user's real Chrome browser
- **📱 Social Media Plugin** — Twitter/X integration via Tweepy (post tweets, reply, search mentions, get timeline) and Reddit integration via PRAW (submit posts, comment, search subreddits, read inbox). 8 new tools: `twitter_post`, `twitter_reply`, `twitter_search`, `twitter_mentions`, `reddit_post`, `reddit_comment`, `reddit_search`, `reddit_inbox`
- **💰 Actual Cost Tracking** — CostTracker now supports `actual_cost` from OpenRouter's generation API, overriding local estimates for precise spend tracking
- **📖 TOOLS.md Integration** — Personality system now reads TOOLS.md for tool usage guidance, injected into every system prompt

### Fixed
- **🔧 System-wide [No response] Fix** — Root cause: cloud models (Gemini via OpenRouter) return tool calls via native `tool_calls` streaming field, but the streaming code only read `delta.content` → empty response. Added native `tool_calls` capture in all 3 LLM call paths (streaming, non-streaming messages, non-streaming legacy). Streaming fix accumulates incremental arguments across multiple chunks
- **📨 Telegram Reliability Overhaul** — Fixed `send_message` silently swallowing ALL errors (`except: pass`); added Markdown parse failure detection with automatic plain text fallback; added message splitting for Telegram's 4096-character limit; fixed `UnboundLocalError` crash on `CancelledError` (response variable not initialized); added `[No response]` guard in all 4 handler methods (`process_and_respond`, `_handle_document`, `_handle_photo`, `_handle_audio`); added `CancelledError` handling across all handlers
- **🔑 WebSocket Auth Bypass for Localhost** — `handle_stream()` in web_deck.py now bypasses token validation for localhost connections (`127.0.0.1`, `::1`), matching the auth middleware's localhost bypass. Fixes Chrome extension side panel red status dot
- **💬 Side Panel HTTP Fallback** — sidepanel.js now reads HTTP response body from `/api/chat` as fallback when WebSocket `/stream` doesn't deliver chunks, ensuring responses always appear

---

## [v1.1.0] — 2026-02-22

### Added
- **🌐 OpenRouter Model Expansion (6 → 26)** — 26 curated models across 3 tiers: Frontier (Gemini 3.1 Pro, Claude Opus 4.6, GPT-5.2, Grok 4.1 Fast, DeepSeek V3.2, Qwen 3.5 Plus, GPT-5.2 Codex), Strong (12 models including Claude Sonnet 4.6, GPT-5.1, Kimi K2.5, GLM-5), Fast (7 models including Mistral Large, Devstral, MiniMax M2.5, Sonar Pro Search, Nemotron Nano 30B). All models added to Control Deck Models page and Telegram model menus
- **💰 Token Cost Dashboard** — Real-time cost tracking in the Status tab with 6 summary cards (Session, Today, This Week, This Month, Last Request, Avg/Message), multi-currency support (USD, EUR, GBP, CAD, AUD, JPY, INR, BRL, KRW), persistent JSONL logging (`logs/cost_log.jsonl`), real token extraction from all providers (Google, Anthropic, OpenAI-compatible, Ollama), MODEL_PRICING for 33 models, free provider detection (NVIDIA, Cerebras, Groq, HuggingFace, Ollama show FREE), 90-day auto-prune
- **📊 CostTracker Backend** — New `CostTracker` class in `gateway_v2.py` with append-only JSONL storage, session/daily/weekly/monthly aggregation, per-model breakdowns, `/api/cost-stats` endpoint
- **💱 Multi-Currency Support** — 9 currencies with static exchange rates, currency selector saved to localStorage, all costs stored in USD with client-side conversion

### Fixed
- **📈 Chart.js Removal** — Removed Chart.js CDN dependency that caused Chrome STATUS_BREAKPOINT crashes and infinite resize loops in the Status tab. Cost dashboard now uses lightweight summary cards only

---

## [v1.0.9] — 2026-02-22

### Added
- **🎬 Video Generation (Google Veo)** — Text-to-video and image-to-video via Google Veo API. Two new tools: `generate_video` (text prompt → MP4) and `generate_video_from_image` (still image → animated MP4). Supports 4s/6s/8s duration, 720p/1080p/4K resolution, 16:9 and 9:16 aspect ratios, negative prompts. Async polling with status updates during generation
- **🎥 Inline Video Player** — Generated videos appear inline in the Control Deck chat as HTML5 `<video>` elements with controls, autoplay, muted loop, and a download link. New `/api/video/{filename}` serving endpoint
- **📦 New NVIDIA Models** — Added Nemotron Super 49B (`nvidia/llama-3.3-nemotron-super-49b-v1.5`), Nemotron Nano 9B v2 (`nvidia/nvidia-nemotron-nano-9b-v2`), and Phi-3 Medium (`microsoft/phi-3-medium-4k-instruct`) to the Models page with model cards
- **🧠 NVIDIA Thinking Model Params** — Added per-model reasoning parameters for DeepSeek V3.2 and Nemotron Nano 9B v2 to the `_NVIDIA_THINKING_MODELS` configuration
- **🎬 Multi-Provider Video Config** — New `video:` config section with Google Veo day-one support and scaffolding for Runway Gen-4, Kling, and Luma Dream Machine

### Fixed
- **💬 Chat/Logs/Thinking Scroll** — All three tabs now use conventional bottom-up chat ordering (newest content at bottom, like Facebook Messenger). Root cause: stream-bubble was the first child and `insertBefore(sb.nextSibling)` placed new messages at the top. Fixed by moving stream-bubble to be the last child and inserting before it. Also fixed log trim (now removes oldest, not newest) and filterLogs (removed reverse)
- **🔧 NVIDIA Streaming Hang** — Some NVIDIA models (Qwen 3.5 397B) accept streaming requests but never send SSE data. Added `_NVIDIA_NO_STREAM` set to force non-streaming, plus automatic streaming-to-non-streaming fallback for all NVIDIA models
- **⏳ NVIDIA Cold-Start Retry** — Large NVIDIA models return HTTP 504 after ~5 minutes when cold-loading onto GPUs. Added auto-retry (up to 2 attempts) on 502/503/504 with 10s delay and "⏳ NVIDIA model loading" status messages
- **📡 NVIDIA Granular Timeouts** — Changed from single 300s timeout to 30s connect + 600s read for large NVIDIA models that take several minutes to respond
- **🔗 HuggingFace URL Migration** — Updated from deprecated `api-inference.huggingface.co/v1` to `router.huggingface.co/v1` across gateway, web deck, and config
- **📄 Non-Streaming JSON Parsing** — Hardened non-streaming response path with HTTP status check before parsing and safe handling of empty response bodies
- **⚡ Bulletproof Shutdown** — Added 8-second hard-exit timer that prevents infinite hang on shutdown; proper shutdown_event chain across all subsystems

---

## [v1.0.8] — 2026-02-22

### Fixed
- **🔧 Model Persistence — Definitive Fix** — Complete architectural overhaul of config save system. Root cause: `_save_config()` was a destructive full-file overwrite. Fix: safe read-modify-write pattern, defensive model-key writeback on every save, unified config paths via `self.core.config_path`, consolidated triple-save for toggle settings, startup diagnostics with `[config]`/`[DEFAULT]` source tags
- **🎨 Imagen 4 Safety Filter** — Fixed `400 INVALID_ARGUMENT` by changing `safety_filter_level` from `BLOCK_ONLY_HIGH` to `BLOCK_LOW_AND_ABOVE`
- **🖼️ Inline Image Display** — Added diagnostic logging to image delivery pipeline, fixed `_rawText` accumulation bug between messages
- **💾 Config Save Path Fixes** — `handle_save_key()`, `handle_setup()`, `handle_login()`, and `model_manager._save_config()` all now use safe read-modify-write pattern with defensive model writeback

---

## [v1.0.7] — 2026-02-21

### Added
- **🔽 Shutdown/Restart Buttons** — Control Deck now has shutdown and restart buttons for easy server management
- **🎨 Imagen 4 SDK Migration** — Migrated from legacy Gemini image API to the new `google-genai` SDK for Imagen 4 generation

### Fixed
- **📜 Scroll Ordering** — Initial scroll ordering implementation (newest-first, later corrected in v1.0.9 to conventional bottom-up)
- **🎨 SD3.5 NVIDIA Fix** — Stable Diffusion 3.5 image generation restored on NVIDIA NIM
- **🤖 SubAgent Overhaul** — Reworked SubAgentManager for reliability and proper task tracking

---

## [v1.0.6] — 2026-02-21

### Fixed
- **🧠 VAULT / Personality not loading** — `config.yaml` → `paths.workspace` was still pointing to the old OpenClaw workspace directory after install migration. The personality system (`personality.py`) reads VAULT.md, IDENTITY.md, USER.md, SOUL.md, and MEMORY.md from the workspace path. With the stale path, the AI had no access to the user's vault (credentials, personal data) and responded with "I don't have access to your personal credentials." Fixed by updating the workspace path to the current install directory
- **🎯 Smart routing misclassification of file uploads** — When a user sends a document via Telegram (e.g., CHANGELOG.md, README.md), the entire file content was fed into `classify_task()` for smart routing. Any .md file describing code changes would contain keywords like "script", "function", "implement", triggering a "coding" classification and routing to the Qwen Coder 480B model — even when the user wanted help with marketing or social media. `classify_task()` now strips attached file content and code blocks before classification, so routing is based on the user's actual message/caption, not file contents
- **⏱ Telegram timeout killing active tasks early** — Telegram bridge had its own `timeout_seconds: 180` that wrapped `speak()` in a separate `asyncio.wait_for()`. The global `speak_timeout` is 600s, but Telegram's 180s limit killed the task before the gateway finished. `_get_speak_timeout()` now uses `max(global_timeout, telegram_timeout)` so the Telegram bridge never cuts off a task that the gateway is still allowed to work on

---

## [v1.0.5] — 2026-02-21

### Added
- **🔌 Agent Loop Circuit Breaker** — After 3 consecutive tool failures (errors or timeouts), the AI is forced to stop calling tools and explain the situation to the user instead of spiraling through all 50 turns
- **⚠️ Progressive Backpressure** — At 50% and 80% of the tool-turn budget, the AI receives nudge messages telling it to wrap up and deliver results, preventing runaway automation sessions
- **🔄 Tool Repetition Guard** — If the same tool is called 4+ times in a 6-call window without progress, the AI is instructed to change strategy or explain the problem
- **🔒 Model Lock During Active Tasks** — Switching models via the Control Deck while the AI is mid-task now queues the switch instead of disrupting the active conversation (applied automatically after the task completes)
- **🎯 Smart Routing Restoration** — When smart routing temporarily switches to a specialized model (e.g., Qwen Coder for coding tasks), the original model is now automatically restored after the request completes

### Fixed
- **Agent timeout spiral** — Complex tasks (like script creation) could burn through all 50 tool turns without converging, hitting the 600s wall-clock timeout. The new anti-spin guardrails (circuit breaker, backpressure, repetition guard) prevent this pattern
- **Smart routing model leak** — `auto_route()` switched the model but never restored it, so the specialized model stuck around for subsequent unrelated requests

---

## [v1.0.4] — 2026-02-21

### Fixed
- **🔧 Model persistence across restarts** — Selected primary model now survives restarts. Two bugs were causing the model to revert to Gemini 2.5 Flash on every startup:
  1. `/api/switch_model` (used by the Models tab quick-switch) updated the live session only — it never wrote the selection to `config.yaml`. It now calls `ModelManager._save_config()` so the choice is immediately persisted.
  2. `GalacticGateway.__init__` read `config.gateway.model` which was only written by the Settings tab path, not the Models tab path. It now reads `config.models.primary_model` first (the canonical value written by `ModelManager`), falling back to `config.gateway.model`, so startup always loads the correct last-used model regardless of which UI element made the switch.

---

## [v1.0.3] — 2026-02-21

### Added
- **🎤 Voice Input Button** — Microphone button in the Control Deck chat bar. Click to record, sends audio to Whisper (OpenAI/Groq) for transcription, inserts text into the chat input automatically
- **🔥 Auto Windows Firewall Rule** — On startup with `remote_access: true`, Galactic AI automatically adds a Windows Firewall inbound rule allowing TCP traffic on the Control Deck port (private networks only)
- **"CONTROL DECK" label** in the top bar next to the model status badge

### Fixed
- **Remote access HTTP mode** — Server now binds to `0.0.0.0` on plain HTTP instead of HTTPS with self-signed TLS. Self-signed certs caused `ERR_EMPTY_RESPONSE`. JWT authentication still protects all remote API endpoints
- **Updater em dash encoding** — Fixed `update.ps1` parse error caused by em dash character corruption in some environments

---

## [v1.0.2] — 2026-02-21

### Added
- **Localhost bypass for remote auth** — Local connections from `127.0.0.1`/`::1` bypass JWT auth so the PC is never locked out of the Control Deck when `remote_access: true`
- **"CONTROL DECK" label** in top bar (first introduced here, improved in v1.0.3)

### Fixed
- **QR code compatibility** — QR pairing code now uses standard black-on-white colors with higher error correction (`ERROR_CORRECT_H`)
- **Test Voice button now plays audio** — Previously only generated the MP3 server-side without streaming it back. Now uses `/api/tts` to stream audio bytes to the browser and plays them directly
- **Desktop shortcut icon** — `galactic_ai_flux_v4.ico` added to the repository (was missing, referenced by `create_shortcut.ps1`)

---

## [v1.0.1] — 2026-02-21

### Added
- **Config auto-migration** — On startup, `load_config()` detects missing config sections from newer versions and adds them with safe defaults. Affected sections: `gmail`, `discord`, `whatsapp`, `webhooks`, `web`, `elevenlabs`, `models`, `tool_timeouts`, `aliases`. Existing values are never overwritten
- **Updater `-Force` flag** — `.\update.ps1 -Force` and `./update.sh --force` re-download even when the installed version matches the latest release

### Fixed
- Missing release ZIP assets — Added `windows.zip`, `macos.zip`, `linux.tar.gz`, `universal.zip`, and `SHA256SUMS.txt`

---

## [v1.0.0] — 2026-02-21

### Added
- **🌐 Remote Access Mode** — Access Galactic AI from anywhere
  - Enable with `remote_access: true` in config.yaml
  - Auto-generated self-signed TLS certificates (HTTPS)
  - Binds to `0.0.0.0` for LAN/internet access
  - Startup warning when remote access is active
- **🔑 JWT Authentication** — Enterprise-grade auth for remote connections
  - HMAC-SHA256 signed tokens with 24-hour expiry
  - Auto-generated 64-character hex secret stored in config.yaml
  - Auth middleware on all `/api/*` endpoints
  - WebSocket authentication via query parameter
  - Backward-compatible with existing password hash for local mode
- **🛡️ Rate Limiting** — Brute-force protection
  - 60 requests/minute per IP for API endpoints
  - 5 login attempts/minute per IP
  - Returns 429 with `Retry-After` header
- **🔒 CORS Middleware** — Cross-origin protection with configurable allowed origins
- **🎙️ Voice API Endpoints**:
  - `POST /api/tts` — text-to-speech via existing ElevenLabs/edge-tts/gTTS pipeline, returns MP3
  - `POST /api/stt` — speech-to-text via OpenAI Whisper with Groq Whisper fallback, accepts multipart audio
- **`remote_access.py`** — New security module centralizing JWT, rate limiting, CORS, and auth middleware

### Fixed
- **Settings model save bug** — Changing primary/fallback models in the Settings tab now takes effect immediately
  - `switch_to_primary()` no longer short-circuits when already in primary mode
  - `_save_config()` now syncs gateway provider/model in config.yaml for persistence across restarts

### Changed
- Version bumped from v0.9.3 to v1.0.0 across all files
- `web_deck.py` login endpoint returns JWT tokens when remote access is enabled
- `web_deck.py` JavaScript uses `authFetch()` wrapper for JWT auth headers on all API calls
- `web_deck.py` WebSocket uses `wss://` protocol when on HTTPS
- `galactic_core_v2.py` auto-generates JWT secret on first remote-mode startup
- Website `index.html` updated with remote access section

---

## [v0.9.3] — 2026-02-21

### Added
- **⚙️ Settings Tab** — New Control Deck tab with three sections:
  - *Model Configuration* — Primary and fallback provider+model dropdowns (populated from all 100+ models), auto-fallback toggle, smart routing toggle, streaming toggle
  - *Voice* — TTS voice dropdown with all 7 voices + Test Voice button
  - *System* — GitHub update check interval, speak() timeout, max ReAct turns
  - All settings saved immediately to `config.yaml` via new API endpoints
- **🔐 VAULT.md** — Private credentials file for automation tasks
  - `VAULT-example.md` template included in repository
  - Loaded by `personality.py` into every system prompt with "never share or expose" instruction
  - Gitignored and protected by both `update.ps1` and `update.sh`
  - Editable in the Memory tab of the Control Deck
- **🗣️ TTS Voice Selector** — Quick Tools sidebar dropdown for instant voice switching (Guy, Aria, Jenny, Davis, Nova, Byte, gTTS)
- **🆕 GitHub Auto-Update Checker** — Background task checks `cmmchsvc-dev/Galactic-AI` releases every 6 hours (configurable, 0 = disabled). Shows dismissible banner + 30-second toast in Control Deck when update available
- **🔽 Model Dropdowns** — PER-MODEL OVERRIDES now uses `<select>` dropdown populated from ALL_MODELS instead of a text input. Custom model text input provided as fallback
- **3 new API endpoints**: `POST /api/settings/models`, `POST /api/settings/voice`, `POST /api/settings/system`
- **`voice` and `update_check_interval`** fields added to `/api/status` response
- **VAULT.md** added to workspace file lists in Memory tab (OpenClaw migration, file list, auto-create defaults)
- **`system.update_check_interval: 21600`** added to `config.yaml`

### Changed
- Settings tab allows switching primary/fallback models without leaving the browser — no more editing `config.yaml` manually
- `personality.py` `get_system_prompt()` now loads VAULT.md as the 5th injected file
- `galactic_core_v2.py` `imprint_workspace()` now includes VAULT.md in the workspace files list
- `update.ps1` and `update.sh` protected file lists updated to include VAULT.md
- `.gitignore` updated to explicitly list VAULT.md
- Website `index.html` updated to v0.9.3 with new features section
- `docs/ARCHITECTURE.md` fully rewritten to reflect v0.9.3 system design
- Tool count updated to 100+ across README, FEATURES, and website

---

## [v0.9.2] — 2026-02-20

### Added
- **Resilient model fallback chain** — Error-type-specific cooldowns (RATE_LIMIT: 60s, SERVER_ERROR: 30s, TIMEOUT: 10s, AUTH_ERROR: 86400s, QUOTA_EXHAUSTED: 3600s)
- **Automatic provider recovery** — Background loop retests failed providers after cooldown expires
- **16 new built-in tools** (108 total):
  - Archives: `zip_create`, `zip_extract`
  - HTTP: `http_request` (raw REST with custom headers)
  - Environment: `env_get`, `env_set`
  - Window management: `window_list`, `window_focus`, `window_resize`
  - System: `system_info`, `kill_process_by_name`
  - Utilities: `qr_generate`, `color_pick`, `text_transform` (15 text operations)
  - Notifications: `notify` (desktop toast/balloon)
  - Clipboard: `clipboard_get`, `clipboard_set`
- **Expanded Status screen** — 30+ telemetry fields across 6 sections (Model, Fallback Chain, Runtime, Memory, Tokens, Plugins)
- **speak() wall-clock timeout** — Entire ReAct loop wrapped in `asyncio.wait_for()`, default 600s, configurable via `models.speak_timeout`
- **Per-tool configurable timeouts** in `config.yaml` under `tool_timeouts` (exec_shell: 120s, execute_python: 60s, generate_image: 180s)
- **Shell command timeout** in ShellExecutor plugin
- **`model_fallback` WebSocket event** — Control Deck shows toast notification when provider falls back
- **Toast notification system** — CSS-animated popups for model fallback events

### Changed
- `config.yaml` expanded with `tool_timeouts`, `speak_timeout`, `fallback_cooldowns` sections
- Status tab HTML redesigned with 6 organized sections

---

## [v0.9.1] — 2026-02-14

### Added
- **Organized image folders** — Generated images saved to date-stamped subdirectories
- **Structured logging system** — Daily JSON component logs alongside plain-text system_log.txt
- **Log rotation** — Files trimmed at 2MB / 5000 lines

### Changed
- Log system backwards-compatible — existing callers unchanged

---

## [v0.9.0] — 2026-02-10

### Added
- **Discord bridge** — Full bot integration with slash commands, typing indicators, allowed-channel access control
- **WhatsApp bridge** — Meta Cloud API webhook integration
- **Gmail bridge** — IMAP inbox monitoring with Telegram notifications
- **Imagen 4 / Imagen 4 Ultra** — Google Imagen 4 image generation tools (`generate_image_gemini`, `generate_image_gemini_ultra`)
- **Imagen 4 Fast** — Fast variant via Gemini API
- **Telegram image model selector** — `/model` → Image Models in Telegram to switch between Imagen 4 Ultra, Imagen 4, FLUX.1 Dev, Imagen 4 Fast, FLUX.1 Schnell
- **Thinking tab persistence** — Agent trace buffered in memory (last 500 entries), restored on page load via `/api/traces`
- **Chat timestamps** — HH:MM:SS timestamp on every message
- **All providers in Telegram model menu** — 14 providers × their model lists in `/model` keyboard
- **Image attachment in chat** — Attach images to chat messages for vision analysis

### Fixed
- Graceful shutdown — single Ctrl+C now cleanly closes all subsystems
- Per-tool timeout — 60s `asyncio.wait_for` on every tool call prevents "typing forever"

---

## [v0.8.1] — 2026-01-28

### Fixed
- Typing indicator heartbeat — no longer sends duplicate "typing" events
- Fast Ctrl+C shutdown — no longer hangs waiting for Telegram long-poll to expire
- Duplicate message guard — prevents double-processing of messages on slow connections

---

## [v0.8.0] — 2026-01-20

### Added
- 17 new tools — clipboard, notifications, window management, HTTP requests, QR codes, system info, text transforms, SD3.5 image gen, FLUX auto-generate
- FLUX.1 Schnell and FLUX.1 Dev image generation via NVIDIA NIM
- Stable Diffusion 3.5 Large image generation
- FLUX auto-generate mode — typing any prompt generates an image when FLUX is selected

---

## [v0.7.9] — 2026-01-12

### Added
- Image delivery to Telegram and Control Deck — generated images sent as photos, not file paths
- Dual FLUX API keys — separate keys for FLUX.1 Schnell and FLUX.1 Dev

---

## [v0.7.8] — 2026-01-08

### Added
- 9 new NVIDIA models (Kimi K2.5, GLM5, MiniMax M2, Nemotron variants)
- Thinking model support (models that return `<thinking>` blocks)
- File attachment fix in chat

---

## [v0.7.7] — 2025-12-28

### Added
- Accessibility-driven browser interactions — click/type by accessibility ref ID
- Network request interception and response body capture

---

## [v0.7.6] — 2025-12-20

### Added
- Desktop automation plugin (pyautogui) — click, type, scroll, drag, template matching
- Clipboard tools

---

## [v0.7.5] — 2025-12-14

### Added
- Sub-agent orchestration — spawn parallel AI agents for multi-step workflows
- `SubAgentManager` plugin

---

## [v0.7.4] — 2025-12-08

### Added
- Browser session save/restore — persist cookies and storage state across runs
- Geolocation spoofing, proxy support, media emulation

---

## [v0.7.3] — 2025-12-02

### Added
- Browser tracing (Playwright trace recording)
- Iframe support — execute actions inside nested frames
- Browser storage tools (localStorage, sessionStorage)

---

## [v0.7.2] — 2025-11-25

### Added
- NVIDIA single-key setup — one key works for all NVIDIA-hosted models
- Quick-pick model chips in Control Deck
- Custom model text field for Ollama custom models
- Ollama 10-minute timeout for large local models

---

## [v0.7.1] — 2025-11-18

### Added
- **Persistent memory** — MEMORY.md + memory_aura.json
- **Voice I/O** — Whisper transcription + TTS response via Telegram
- **Chat persistence** — `logs/chat_history.jsonl`, restored on page load
- **Personality config** — byte / custom / generic / files modes
- **One-command auto-updater** — `update.ps1` and `update.sh`

---

## [v0.7.0] — 2025-11-10

### Added
- 14 AI providers (added Cerebras, OpenRouter, HuggingFace, Together AI, Perplexity)
- TTS configuration in Setup Wizard
- OpenClaw migration step — import existing memory/identity files

### Fixed
- Gemini duplicate response bug

---

## [v0.6.0-Alpha] — 2025-10-28

### Initial public release
- 72 built-in tools
- 5 AI providers (Google, Anthropic, OpenAI, Groq, Ollama)
- Telegram bot
- Web Control Deck at localhost:17789
- ReAct agentic loop
- Playwright browser automation
