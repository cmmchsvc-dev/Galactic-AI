# Changelog — Galactic AI

All notable changes to Galactic AI are documented here.

---

## [v1.0.0] — 2026-02-21

### Added
- **📱 Galactic-AI Mobile** — Native Android companion app (Kotlin + WebView)
  - Full Control Deck access with all 10 tabs (Chat, Tools, Plugins, Models, Browser, Memory, Status, Settings, Logs, Thinking)
  - QR code pairing — scan from PC Settings tab to connect instantly
  - Voice I/O — hands-free speech-to-text (Android SpeechRecognizer) and text-to-speech (server-side + local fallback)
  - Biometric/PIN lock for app access (AndroidX Biometric)
  - TLS certificate pinning with TOFU (Trust On First Use) model
  - AES-256 encrypted credential storage (Android Keystore)
  - Auto-reconnect on network changes with exponential backoff
  - Hardware-accelerated WebView for smooth CRT effects
  - Cyberpunk-themed native connection screen with QR scanner
  - Animated splash screen matching desktop aesthetic
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
- **📷 QR Code Pairing** — `GET /api/qr_pair` endpoint generates pairing QR code encoding host, port, and cert fingerprint
- **🎙️ Voice API Endpoints** for mobile hands-free communication:
  - `POST /api/tts` — text-to-speech via existing ElevenLabs/edge-tts/gTTS pipeline, returns MP3
  - `POST /api/stt` — speech-to-text via OpenAI Whisper with Groq Whisper fallback, accepts multipart audio
- **📱 Mobile Pairing Card** in Settings tab — displays QR code for instant mobile connection
- **`remote_access.py`** — New security module centralizing JWT, TLS, rate limiting, CORS, and auth middleware

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
- Website `index.html` updated with mobile app section and download link

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
