# Galactic AI — User Manual

**v2.1.1 — "The Hybrid Pilot QOL Update"**

This is the practical, task-oriented guide to running Galactic AI day to day: what to click, what to type, and what happens next. For the technical feature reference see [`FEATURES.md`](FEATURES.md); for install/quick-start see [`README.md`](README.md); for the exhaustive tool catalogue see [`TOOLS.md`](TOOLS.md). This manual is the one you keep open in a second tab.

Your AI's default name is **Byte** — a techno-hippie familiar who's chill, resourceful, and opinionated. Everything below refers to "Byte" but applies equally if you've renamed or reskinned your assistant (see [Personality & Personas](#17-personality-personas)).

---

## Table of Contents

1. [What Is Galactic AI](#1-what-is-galactic-ai)
2. [Getting Started](#2-getting-started)
3. [The Web Control Deck — Tab by Tab](#3-the-web-control-deck-tab-by-tab)
4. [Chatting with Byte](#4-chatting-with-byte)
5. [Chat Slash Commands](#5-chat-slash-commands)
6. [Command Palette & Keyboard Shortcuts](#6-command-palette-keyboard-shortcuts)
7. [Models, Providers & Cost](#7-models-providers-cost)
8. [Memory System](#8-memory-system)
9. [Skills & Tools](#9-skills-tools)
10. [Voice](#10-voice)
11. [Creative Generation — Images & Video](#11-creative-generation-images-video)
12. [Sessions, History & Export](#12-sessions-history-export)
13. [Sub-Agents & the Swarm Tab](#13-sub-agents-the-swarm-tab)
14. [Messaging Bridges](#14-messaging-bridges)
15. [Chrome Extension — Galactic Browser](#15-chrome-extension-galactic-browser)
16. [The Galactic CLI](#16-the-galactic-cli)
17. [Personality & Personas](#17-personality-personas)
18. [Security & Remote Access](#18-security-remote-access)
19. [Updating](#19-updating)
20. [Troubleshooting](#20-troubleshooting)
21. [Appendix A — Configuration Quick Reference](#21-appendix-a-configuration-quick-reference)
22. [Appendix B — Where to Learn More](#22-appendix-b-where-to-learn-more)

---

## 1. What Is Galactic AI

Galactic AI is a local-first AI automation platform: a web-based **Control Deck**, a terminal **CLI**, and background bridges (Telegram, Discord, Gmail) all talking to the same brain — `gateway_v3.py`. That brain can drive 24 different cloud AI providers, or run 100% offline through Ollama with zero API keys and zero data leaving your machine.

What makes it more than "a chat window in front of an API":

- **It remembers.** Across restarts, across weeks — see [Memory System](#8-memory-system).
- **It plans before it acts.** Complex or coding requests get a scan-the-codebase-first planning pass — see [Models, Providers & Cost](#7-models-providers-cost).
- **It can escalate on demand.** Run cheap/local by default, one click to re-run an answer on your best cloud model — see [Boost & Retry](#74-boost-retry).
- **It can split brains for coding.** A big cloud model designs the fix, your free local model applies it — see [Hybrid Coding Mode](#75-hybrid-coding-mode).
- **It has hands.** 100+ tools spanning the file system, shell, browser (two different engines), image/video generation, social media, and your real Chrome browser.
- **It's reachable everywhere.** The same assistant answers in the web deck, the CLI, Telegram, Discord, and Gmail.

---

## 2. Getting Started

### 2.1 Install

```powershell
# Windows
.\install.ps1        # guided install — asks what you want, only downloads that
.\launch.ps1          # start Galactic AI
```

```bash
# macOS / Linux
chmod +x install.sh && ./install.sh
./launch.sh
```

The installer offers three profiles — **Lite** (~160 MB, chat + Control Deck + all providers), **Full** (~3.4 GB, everything including semantic memory and voice), or **Custom** (pick features individually). You can always add a feature later:

```bash
python install.py --add memory      # e.g. add semantic memory after the fact
python install.py --list            # see what's installed vs available
python install.py --repair          # reinstall anything missing
```

### 2.2 First Launch — the Setup Wizard

Open **http://127.0.0.1:17789** after launching. On first run the Setup Wizard walks you through, in order: Primary Provider → extra API keys + TTS voice → Telegram (optional) → other messaging bridges (optional) → a login passphrase → personality choice → OpenClaw migration (if you have existing identity files) → review & launch.

**Want zero API keys?** Pick **Ollama** as your provider in step 1, skip every key screen, and run:

```bash
ollama pull qwen3:8b
```

You're now 100% local — nothing leaves your machine.

### 2.3 Logging In

The Control Deck is protected by the passphrase you set in the wizard (stored as a SHA-256 hash — the plaintext is never saved). Enter it once; your session token is kept in the browser's `localStorage` so you won't be asked again until it expires or you clear site data.

### 2.4 Launching Day-to-Day

- **Web Deck:** `.\launch.ps1` / `./launch.sh`, then open the URL (or use the **Desktop app** — `Galactic AI Desktop.bat` / `Launch Galactic Desktop.vbs` — for a native window instead of a browser tab)
- **CLI:** `python galactic_cli.py` (needs the web deck's backend running, since the CLI is a terminal client talking to the same `/api/*` endpoints)
- Shut down cleanly with a single **Ctrl+C** in whichever terminal is running the core.

---

## 3. The Web Control Deck — Tab by Tab

The Deck's left sidebar has 12 tabs. Your active tab is remembered across refreshes.

### 💬 Chat
Your main conversation with Byte. Full tool support, inline images/video, file attachments, voice input, and now (v2.1.1) a hover toolbar and provenance chips on every message — see [Chatting with Byte](#4-chatting-with-byte).

### 🧠 Thinking
A real-time view into the ReAct loop: every tool call, its arguments, and its result, grouped by turn and session. Useful for understanding *why* Byte did something, or for babysitting a long autonomous task. Also hosts the **Resumable Workflows** list — if a long task got interrupted (crash, timeout, manual stop), find the run here and click **▶ Resume** to pick up exactly where it left off instead of starting over. Persists across refreshes (last 500 trace entries).

### 📊 Status
Live telemetry: current provider/model, token usage, uptime, fallback-chain health, plugin states, version. Includes the **Cost Dashboard** — six summary cards (Session, Today, This Week, This Month, Last Request, Avg/Message), a 9-currency selector, and free-model detection so Ollama/Groq/etc. usage doesn't inflate your spend total.

### 🎨 Models
Browse and one-click switch every available model — cloud models ordered best-to-worst with tier badges (👑 flagship, ⚡ fast, etc.), plus every locally-discovered Ollama model. Switching here changes your **primary** model immediately (or queues the switch if Byte is mid-task, so you don't yank the rug out from under an active tool loop).

### 🔧 Tools
A browsable, searchable catalogue of every currently-loaded tool with its description and parameters. The count badge in the sidebar reflects what's actually loaded right now — it changes as you toggle Skills on/off. For the full categorized catalogue see [`TOOLS.md`](TOOLS.md).

### ⚡ Skills
Every loaded skill as a card: icon, name, CORE or COMMUNITY badge, version, author, description, and tool count. Flip the toggle to enable/disable a skill instantly — no restart. See [Skills & Tools](#9-skills-tools).

### 💾 Memory
Two jobs in one tab:
- **Identity file editor** — edit `MEMORY.md`, `IDENTITY.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `VAULT.md` directly in the browser. Missing files are auto-created with starter templates the first time you open the tab.
- **Memory Browser** — search, list, inspect, and delete individual entries from the semantic (ChromaDB) memory store, with per-category stats.

See [Memory System](#8-memory-system).

### ⚙️ Settings
The control room for models, voice, personality, and system tuning. The **Model Configuration** box covers Primary / Fallback / **🚀 Boost** / Planner / Planner Fallback / Summarizer model dropdowns, streaming toggle, thinking-effort level, and the gold **🧬 Hybrid Coding Mode** box (enable checkbox + Architect/Builder model pickers) — see [Models, Providers & Cost](#7-models-providers-cost). Further down: TTS voice picker, personality mode, and system settings (update-check interval, speak timeout, max ReAct turns, autonomous coding toggle).

### 🦙 Ollama
Health status (online/offline, polled continuously), every locally-discovered model, and each one's actual context window size as reported by Ollama itself.

> **Two local backends, one selector.** Galactic AI also supports **LM Studio** as an interchangeable local backend. Start LM Studio's local server (Developer tab → Start Server, default port 1234) and add a `providers.lmstudio` section to your config (`enabled: true`) — or just pick "LM Studio" in the ⚙ Setup wizard, which activates it without a restart. Its models appear in the model picker under a violet 🖥️ group alongside Ollama's orange 🦙 group (embedding-only models are filtered out automatically), the Models tab gets its own LM Studio health row, and LM Studio is selectable in every Settings model dropdown. Switching backends is just picking a different model — no restart. Both are free, local, and need no API key.
>
> **Fastest way to switch:** click the **local-backend pill** in the topbar (it reads e.g. `Ollama: 3 · LM Studio: 2`). A menu drops down showing both backends with health dots and every discovered model — click any model to make it the active primary on the spot; the highlighted chip is what's running now.
>
> **LM Studio VRAM safety (avoid GPU crashes):** unlike Ollama, LM Studio loads a model with a **fixed** context length and (in GPU-strict mode) won't spill to system RAM — asking for a huge context (e.g. 65k on a 27B) can exceed VRAM and hard-crash the GPU driver. Recipe that works: set Context Length to **24–32k**, enable **K/V Cache Quantization** (halves cache VRAM), and watch LM Studio's VRAM estimate before loading. Galactic helps on its side: it clamps every request to the *loaded* window (the Models tab shows it, e.g. `2 models · ctx 32k`), and sends a `ttl` with each request (default 600s, `providers.lmstudio.ttl`) so an idle LM Studio model **auto-unloads and frees its VRAM** instead of fighting Ollama for the GPU.

### 📋 Logs
The raw system log stream in real time — tool calls highlighted in cyan, tool results indented and italic, newest at the bottom, 500 lines of history restored on refresh.

### 🕸️ Swarm
Multi-agent orchestration ("Hive Mind"). See [Sub-Agents & the Swarm Tab](#13-sub-agents-the-swarm-tab).

### ⌨️ CLI Settings
Mirrors and controls the terminal CLI's Auto Mode / Plan Mode / Verbose Mode toggles from the browser, so you can flip them without switching windows.

---

## 4. Chatting with Byte

### 4.1 Sending Messages

Type in the input bar at the bottom of the **Chat** tab and press **Enter** to send (**Shift+Enter** for a newline). The 📎 button attaches files — text/code files are inlined as context, images are sent as vision content so Byte can actually look at them. Drag limit is 20 MB per file.

### 4.2 Message Hover Toolbar *(v2.1.1)*

Hover any message bubble to reveal quick actions:

| Button | On | Does |
|---|---|---|
| 📋 Copy | every message | Copies the raw markdown (not rendered HTML) to your clipboard |
| 🔊 Speak | bot replies | Reads the reply aloud via the unified TTS engine |
| ✏️ Edit | your newest message | Loads that prompt back into the input box so you can tweak and resend |
| ⟳ Retry | the newest bot reply | Rewinds that exchange and re-runs it on the **current** model |
| 🚀 Boost | the newest bot reply | Rewinds that exchange and re-runs it on your **boost** (big-brain cloud) model |

Only the *newest* answer/prompt shows Retry/Boost/Edit — older messages only get Copy (and Speak, for bot replies).

### 4.3 Provenance — Knowing Who Actually Answered

Every reply's meta line shows which model **actually** answered (not just which one you had selected), how long it took, and token counts:

```
Byte • 2:22:16 PM   qwen3:8b   12.4s   ↑1.2K ↓380
```

If the primary model errored mid-request and the system silently failed over, you'll see an amber **⚠ fallback** chip plus a toast — so a suspiciously-different-feeling answer is never a mystery. A boosted reply carries a gold **🚀 boosted** chip and a gold left border; the answer it replaced dims to show it's superseded.

### 4.4 Draft Persistence & Prompt Recall *(v2.1.1)*

- **Drafts survive refreshes.** Half-typed a message and reloaded the page? It's still in the box.
- **ArrowUp/ArrowDown cycles your last 50 sent prompts**, shell-history style — press ArrowUp in an empty (or caret-at-start) input to walk backwards, ArrowDown to come back. Slash commands are excluded from recall.

### 4.5 Barge-In — Steer Byte Mid-Task

While Byte is working, a **Nudge / correct** box appears under the thinking orb. Realize it's heading down the wrong path? Type a course-correction and hit Enter — the current generation is cut short, your steer is folded in as a live instruction, and Byte adjusts *without losing the task*. No more mashing STOP and re-explaining from scratch. It's best-effort: if nothing's running, it just tells you to send a normal message; it never hangs the agent.

### 4.6 Executable Smart Artifacts

Code that Byte emits isn't just static text on the page. Fenced code blocks and Byte's `<galactic_code>` snippets render as **Smart Artifact cards** with a **▶ Run** button (plus Copy). Click Run and the snippet executes for real — Python and shell run server-side in an isolated background process and stream their output back into the card; HTML/CSS/JS run in a sandboxed preview frame. It's a one-click "does this actually work?" without leaving the chat. (Same isolation and timeouts as the `execute_python`/`exec_shell` tools.)

### 4.7 Voice, Files, and Images

The 🎙️ mic button records push-to-talk voice input (transcribed locally via `faster-whisper`), 👂 toggles always-on wake-word listening, and 🔊 toggles **Live Call Mode** (auto-speaks every reply). Attached text/code files are inlined as context; images are sent as vision content so Byte can actually see them. See [Voice](#10-voice) for the full voice picture.

---

## 5. Chat Slash Commands

Typed directly into the chat box (deck, CLI, or via a bridge), these are intercepted before reaching the model:

| Command | What it does |
|---|---|
| `/help` | Lists these commands |
| `/context` | Shows token usage of the active model (used / free / total, as % of the context window) |
| `/compact` | Manually summarizes and archives older history to free up context now (otherwise happens automatically near ~90% usage) |
| `/clear` | Wipes the current conversation and its on-disk history file |
| `/rewind [n]` | Undoes the last *n* messages (default 2) — useful to erase a bad exchange before continuing |
| `/boost [model]` | Rewinds the last exchange and re-runs it on your boost model (or a named model, e.g. `/boost gemini`) |
| `/retry` | Rewinds the last exchange and re-runs it on the current model |
| `/hybrid [on\|off]` | Toggles Hybrid Coding Mode; no argument flips it |
| `switch personality to <name>` | Hot-swaps persona (e.g. "switch personality to homer") — natural language, not a `/command` |

---

## 6. Command Palette & Keyboard Shortcuts

Press **Ctrl+K** (or **⌘K**) anywhere in the deck to open the command palette — a fuzzy-searchable launcher for nearly everything:

- **Go to** any tab
- **Chat actions** — clear, stop, `/context`, `/compact`, `/rewind`, `/help`, **Boost last answer**, **Retry last answer**, **Copy last answer**, **Export chat as Markdown**, **Toggle Hybrid Coding Mode**
- **Voice** — toggle wake-word, Live Call, push-to-talk
- **Session** — save/switch/start sessions
- **Model** — switch to any enabled model directly, across every provider
- **System** — run diagnostics, toggle desktop notifications, refresh status, display settings, re-run setup wizard

Type to filter (subsequence fuzzy match — "gtm" matches "Go to Memory"), **↑/↓** to navigate, **Enter** to run, **Esc** to close.

Other shortcuts:

| Key | Where | Does |
|---|---|---|
| **Enter** | chat input | Send message |
| **Shift+Enter** | chat input | Newline without sending |
| **↑ / ↓** | empty/caret-at-start chat input | Recall previous sent prompts |
| **Escape** | anywhere, task running | Cancels the current agent task (escalating STOP) |
| **Ctrl+K** | anywhere | Open/close the command palette |

---

## 7. Models, Providers & Cost

### 7.1 Switching Models

Three equally-valid ways: the **Models** tab (click any model), the **Ctrl+K palette** (type part of the model name), or Settings → Model Configuration dropdowns. A switch mid-task is queued automatically rather than yanking the model out from under an in-flight tool loop.

### 7.2 The Model Roles

Galactic AI assigns different jobs to different models — you don't have to use the same model for everything:

| Role | Job | Configured in |
|---|---|---|
| **Primary** | Your default chat/answer model | Settings, Models tab, or `models.primary_provider/model` |
| **Fallback** | Takes over automatically if Primary errors repeatedly | Settings or `models.fallback_provider/model` |
| **Planner** | The "Big Brain" that scans your codebase and drafts a plan before complex/coding work | Settings or `models.planner_provider/model` |
| **Planner Fallback** | Backup planner if the primary planner hangs or returns empty | Settings or `models.planner_fallback_*` |
| **Summarizer** | Compacts old conversation history when context fills up | Settings or `models.summarizer_provider/model` |
| **🚀 Boost** | One-shot escalation target for the Boost button/command | Settings or `models.boost_provider/model` |
| **🏛️ Architect** / **🔨 Builder** | Hybrid Coding Mode's two halves — see [full details](#75-hybrid-coding-mode) | Settings or `models.hybrid_coding.*` |

### 7.3 Auto-Fallback & Resilience

If your primary provider throws repeated errors (rate limits, auth failures, timeouts, empty responses), Galactic AI automatically switches to your fallback model, with per-error-type cooldowns (e.g. an auth error backs off for 24h, a rate limit for 60s) so it doesn't hammer a provider that's clearly down. It automatically retries the primary once its recovery window elapses. Toggle this in Settings (**Auto-Fallback**) or `models.auto_fallback` in config.

### 7.4 🚀 Boost & Retry

The everyday money-saver: run your cheap/local Primary model for the bulk of your conversation, and escalate a specific answer to a smarter (and pricier) cloud model only when you actually need it — without ever changing your default.

**To use it:** hover the newest reply → **🚀 Boost** (or type `/boost`, or hit it from Ctrl+K). It rewinds that one exchange, re-runs your question against the boost model, and shows the new answer with a gold "boosted" chip. Your Primary model selection is completely untouched afterward — this is a one-shot override, nothing is written to config.

**Picking a boost target** (checked in this order):
1. Named explicitly: `/boost gemini` (fuzzy-matches your configured models)
2. Pinned in **Settings → Model Configuration → 🚀 Boost Model**, or `models.boost_provider`/`boost_model` in config
3. Auto-picked: the first 👑-flagship-tier model (per `config/models.yaml`'s tier badges) whose provider has an API key configured — falling back further to the first cloud model with a key if nothing is 👑-marked

**⟳ Retry** does the same rewind-and-rerun but stays on whatever model is currently active — good for "that answer was off, try again" without paying for an upgrade.

### 7.5 🧬 Hybrid Coding Mode

The split-brain workflow purpose-built for coding tasks, and the deepest money-saver in the system. The idea: a coding request is really *one* expensive thinking step (design the fix) followed by *many* cheap mechanical steps (read files, write the edit, run tests, fix a typo, run tests again...). Hybrid Coding Mode makes sure only the expensive part touches your cloud bill.

**How it works, in order:**
1. You ask for something that reads as a coding task (build/fix/refactor/implement/update/etc.).
2. The **🏛️ Architect** (your big cloud brain) is engaged automatically. It scans your codebase read-only and produces a blueprint that contains the **exact final code** — complete fenced code blocks, file paths, and precise placement instructions. It does not touch any files itself.
3. The **🔨 Builder** (your cheap/local model) takes over the execution loop with that blueprint pinned in context, and is explicitly instructed to *apply it faithfully, verify it works, and report* — not to redesign or rewrite the Architect's code.
4. The reply's provenance chip shows the Builder as the model that answered; the Thinking tab shows the Architect's planning run separately, so you can always see who did what.

**To turn it on:**
- Settings tab → tick the gold **🧬 Hybrid Coding Mode** box, optionally pick your **Architect** and **Builder** models (Architect defaults to your Planner model, Builder to your local Fallback model if either is left unset), then **Save Model Settings**.
- Or just type `/hybrid on` (or `/hybrid` to flip it) anywhere — deck chat, CLI, or palette.

**When it's off**, coding requests behave exactly as they did before — no change to existing behavior.

**Cost caveat:** with Hybrid Coding on, *every* detected coding request calls the Architect — great for real feature work, wasteful for a one-line typo fix. Flip it off (`/hybrid off`) for trivial edits, or just leave it off by default and reach for 🚀 Boost on individual answers instead.

### 7.6 Cost Dashboard

The **Status** tab tracks every API call's model, provider, token counts, and calculated USD cost to a persistent log. Six summary cards (Session / Today / This Week / This Month / Last Request / Avg per Message), a 9-currency display selector, and automatic exclusion of free-tier usage (Ollama, Groq, Cerebras, HuggingFace, NVIDIA) from spend totals so your dashboard reflects real spend, not noise.

---

## 8. Memory System

Galactic AI remembers you across restarts without burning extra tokens on every message, using four layers:

### 8.1 Identity Files — loaded into every prompt, always

| File | Purpose |
|---|---|
| `IDENTITY.md` | Who the AI is — name, role, vibe |
| `SOUL.md` | Core values and personality style |
| `USER.md` | Who *you* are — preferences, context |
| `MEMORY.md` | Things learned across past sessions |
| `VAULT.md` | Private credentials for automation (see [Credentials for Automation](#83-vaultmd-credentials-for-automation)) |

All five are read from disk at startup and folded into the system prompt. Nothing extra is queried per-message — the cost is proportional only to file size. Edit any of them directly in the **Memory** tab.

### 8.2 MEMORY.md — grows automatically

When you tell Byte to remember something (or it decides something's worth keeping), it appends a timestamped entry to `MEMORY.md`, hot-reloads immediately (the very next message already sees it), and it's now permanent across every future session. You can also hand-edit the file in the Memory tab.

### 8.3 VAULT.md — Credentials for Automation

A private file that lets Byte log into services and fill forms on your behalf, without you re-typing credentials every time.

**Setup:**
```bash
cp VAULT-example.md VAULT.md
# edit VAULT.md with your real credentials
```
Restart Galactic AI and it has access in every conversation.

**What goes in it:** login credentials, personal info (name/phone/address), payment emails, and any custom fields your automations need.

**Security:** `VAULT.md` is gitignored (never committed), the updater (`update.ps1`/`update.sh`) explicitly never overwrites it, and the AI is instructed to never expose its contents in a response. Still — keep genuinely sensitive data (bank passwords, SSNs) out of *any* file the AI reads; VAULT is for automation convenience, not a password manager replacement.

### 8.4 Semantic Memory (ChromaDB) & the Memory Browser

Beyond the flat files, `galactic_memory.py` runs a real vector database (ChromaDB + SQLite) so Byte can semantically search its entire history — "what did I say about my truck?" finds "1966 F100" even without the word "truck" appearing. A background synthesis daemon prunes near-duplicates and distills raw memories into durable belief statements over time.

As of v2.1.0, recall **excludes the codebase index by default** — so semantic search of your *personal* memories isn't drowned out by chunks of your own source code (which has its own separate tool, see [search_codebase](#93-search_codebase)).

**Memory Browser** (Memory tab): search, list, inspect, and delete individual stored memories, with per-category stats — full manual control over what Byte remembers about you.

---

## 9. Skills & Tools

### 9.1 Core Skills

Six built-in skills ship by default: **ShellSkill** (PowerShell/bash), **DesktopSkill** (mouse/keyboard/screenshot), **ChromeBridgeSkill** (your real Chrome via the extension), **SocialMediaSkill** (Twitter/X + Reddit), **SubAgentSkill** (spawn/monitor parallel sub-agents), **BrowserProSkill** (full Playwright automation). Manage all of them — and every community skill — from the **Skills** tab, where each is a toggleable card.

### 9.2 Community Skills — AI Self-Authoring

Byte can write entirely new skills for itself at runtime — no restart required — via `create_skill(name, code, description)`, which validates the Python via AST, writes it to `skills/community/`, and loads it immediately. `list_skills()` shows everything loaded; `remove_skill(name)` unloads one. They persist across restarts via `skills/registry.json`.

At the time of writing, 16 community skills are installed, including:

- **gemini_coder / senior_coder** — Gemini-powered coding engines with plan/apply stages
- **superpowers** — Jesse Vincent's cognitive workflows (test-driven-development, brainstorming, systematic-debugging) — `list_superpowers` / `invoke_superpower`
- **plan_optimizer** ("Workspace Oracle") — simulates a task's tool chain and previews cost/steps *before* execution, to avoid blind runs on large changes
- **gemini_cli_bridge / gemini_cli** — delegates heavy refactors to the official Google Gemini CLI in `--yolo` autonomous mode
- **conversation_auto_recall / conversation_archiver** — restart-resilient conversation memory (hot buffer + archive)
- **vcr_thinkback** — VCR-style file snapshot/undo/restore for risky operations
- **lsp_tooling** — AST-based Python code intelligence (find definitions, extract symbols)
- **magic_docs** — auto-maintains a project architecture map (`.galactic_map.md`)
- **agent_builder** — generates subagent markdown specs with frontmatter
- **automation_recommender** / **md_improver** — self-analysis and doc-quality tools
- **computer_use** — vision-based GUI automation (find/click elements on screen using Gemini vision)

### 9.3 `search_codebase`

Semantic search over *this project's own source code*, scoped strictly to your current workspace (so stale code from an old install elsewhere on disk can't leak into an answer). Use it when you know what code should *do* but not what it's named — "where do we handle the JWT refresh?" — instead of a literal grep.

### 9.4 Tool Categories at a Glance

Well over 100 tools, organized by category (exhaustive list in [`TOOLS.md`](TOOLS.md) and the live **Tools** tab):

| Category | Examples |
|---|---|
| File System | `read_file`, `write_file`, `edit_file`, `list_dir`, `find_files`, `hash_file`, `diff_files` |
| AST-safe Python editing | `list_functions`, `read_function`, `replace_function` — locate & rewrite a function/class by name, syntax-checked before writing |
| Human-in-the-loop | `ask_user` — pause and ask *you* a question mid-task, then resume with your answer |
| Shell & Process | `exec_shell`, `process_start/status/kill`, `schedule_task` |
| Memory & Code Search | `memory_search`, `memory_imprint`, `search_codebase` |
| Vision & Images | `analyze_image`, `generate_image*` (6 backends) |
| Video | `generate_video`, `generate_video_from_image` |
| Web & HTTP | `web_search`, `web_fetch`, `http_request` |
| Desktop Automation | `desktop_screenshot/click/type/key/move/scroll/locate/drag` |
| Browser (Playwright, headless) | 56 tools — navigation, forms, storage, network interception, tracing |
| Chrome (your real browser) | 27 tools — `chrome_navigate/click/read_page/screenshot/...` |
| Social Media | `twitter_post/reply/search/mentions`, `reddit_post/comment/search/inbox` |
| System & Utility | `system_info`, `clipboard_get/set`, `notify`, `window_list/focus/resize`, `qr_generate`, `text_transform` |

**Choosing chrome_\* vs browser_\*:** use **chrome_\*** when Byte needs your *actual logged-in session* or you want to watch it work in your real browser; use **browser_\*** for silent, headless background research that shouldn't disturb what you're doing.

### 9.5 Strategic Planning & the Research → Plan → Implement → Verify Loop

For complex requests, Byte doesn't dive straight into edits. It isolates a Planner model in its own loop to scan the codebase and draft a step-by-step plan first (see [The Model Roles](#72-the-model-roles)); you can force this explicitly by starting a message with `/plan`. The underlying reasoning discipline (`SOUL.md`) is Research → Plan → Implement → Verify: gather facts with `grep_search`/`code_outline`, draft a plan, make precise edits, then verify before declaring done.

### 9.6 Resumable Workflows

Every 5 tool calls (or immediately on failure), Byte checkpoints its full working state — history, active plan, turn count — to `logs/runs/<uuid>/checkpoint.json`. If a long task gets interrupted by a crash or a manual stop, find it in the Thinking tab's **Resumable Workflows** list and click **▶ Resume** to continue exactly where it left off.

### 9.7 Safe-Editing Guarantees ("Zero-Fear Editing")

Letting an AI edit your files is only comfortable if you can trust and undo it. Three mechanisms run automatically behind every file operation:

- **Automatic VCR backups.** *Before* Byte overwrites or edits any file, it silently snapshots the original into `workspace/.galactic_vcr/` — no flag, no asking. If an edit goes wrong, roll it back instantly: `/vcr undo <file>` in the CLI (`/vcr snapshot|list|undo <file>` for the full set). This is separate from, and automatic on top of, the manual VCR command.
- **Byte-level write verification.** After every `write_file`/`edit_file`, Byte immediately reads the file back from disk and reports "✅ WRITE VERIFIED" with the real line and byte counts — structural proof the change actually landed. It cannot hallucinate a successful save; the model only sees success if the bytes are confirmed on disk. (For edits, it also spot-checks that your exact new text is present.)
- **Self-cleaning `tmp/` sandbox.** Scratch scripts, test snippets, and throwaway generations are routed to a dedicated `tmp/` directory instead of your project root, and anything older than 7 days is auto-purged on startup. Byte experiments without leaving clutter behind.

### 9.8 AST-Safe Code Editing

For Python files, Byte has three tools that operate on *code structure* rather than raw text, so edits don't shatter when line numbers shift:

- **`list_functions`** — maps a file's top-level functions/classes and their methods with exact line ranges.
- **`read_function`** — pulls one function/class/method by name (`my_func` or `MyClass.my_method`) — no line-number guessing.
- **`replace_function`** — rewrites a whole function/class located by name. It auto-indents the new code, preserves existing decorators, and — critically — **re-parses the entire file to confirm it's still valid Python before writing anything to disk**. If your replacement would break syntax, nothing is written and Byte gets told why. Every replace also VCR-backs-up the original first.

Together these make whole-function rewrites immune to the line-drift and whitespace hallucinations that make plain find-and-replace risky.

### 9.9 Byte Can Ask You Questions (`ask_user`)

When Byte hits something only you can resolve mid-task — a 2FA code, a missing credential, a genuinely ambiguous instruction, or a subjective design call — it can **pause and ask you** instead of guessing and failing. A modal pops up in the Control Deck ("🤖 Byte needs your input"); type your answer and the agent resumes exactly where it left off. If you're away, it waits (with a timeout) and then either proceeds on its best judgment or tells you it's blocked — it never hangs forever.

### 9.10 The Crucible — Approve Edits Before They Land

For maximum control, turn on **Settings → Model Configuration → ⏸️ Require approval for file edits** (or `models.require_approval` in config). With it on, *every* file write, edit, or `replace_function` **pauses and shows you a colorized diff** in the Control Deck before touching disk:

- **✅ Approve & write** — applies the change (still VCR-backed-up).
- **❌ Reject** — the change is discarded; click again to add feedback that goes straight back to Byte so it can revise its approach.

It's the ultimate "watch every keystroke" mode for when Byte is loose in an important codebase. Default **off** (edits apply immediately, as normal). If you don't respond, the change **times out and is rejected** — never applied behind your back. Toggle it any time; it takes effect on the next edit.

---

## 10. Voice

### 10.1 Speech-to-Text — Local First

Both wake-word listening and push-to-talk transcribe via **`faster-whisper`** running locally (GPU-accelerated when available) — your voice never leaves the machine by default. Cloud Whisper/Google STT is available only as an explicit fallback, not the default path.

### 10.2 Text-to-Speech

A single shared engine (`tts_engine.py`) backs both the always-on voice agent and the on-demand `text_to_speech` tool / message-hover 🔊 Speak button. Pick your voice engine in **Settings** or the **Quick Tools** sidebar dropdown: ElevenLabs (premium, needs a key), Fish Speech (voice clone), edge-tts (free Microsoft neural voices), Piper, Chatterbox, or gTTS (free universal fallback).

### 10.3 Wake Word, Barge-In & Live Call

- **👂 Wake-word listening** — always-on mic; say the wake word to start talking hands-free.
- **Barge-in** — say the wake word again while Byte is mid-sentence and playback stops instantly so you can interrupt. (If you've set up a custom persona/voice-clone — e.g. "Chong" — barge-in works the same regardless of which voice is active.)
- **🔊 Live Call Mode** — every text reply is automatically spoken aloud as soon as it arrives, turning the chat into a real voice conversation.

---

## 11. Creative Generation — Images & Video

### 11.1 Images

Six backends, switchable per-session: Imagen 4 Ultra (best quality, slow), Imagen 4 (high quality, fast), Imagen 4 Fast (fastest Google option), FLUX.1 Dev (excellent detail), FLUX.1 Schnell (fastest overall), and Stable Diffusion 3.5 Large (versatile). Just ask in chat ("generate an image of...") — when FLUX is the active backend, any prompt auto-generates. Images render inline with a click-to-expand full-size view.

### 11.2 Video

Powered by Google Veo. **Text-to-video** describes a scene into a 4/6/8-second clip; **image-to-video** animates any existing still (including one Byte just generated) into motion. Configurable resolution (720p/1080p/4K), aspect ratio (16:9/9:16), and negative prompts. Videos play inline with a standard HTML5 player and a one-click MP4 download.

---

## 12. Sessions, History & Export

### 12.1 Named Sessions

The session bar atop the Chat tab lets you **Save** the current conversation under a name, **switch** between saved sessions via the dropdown, start a **New** blank one, or **delete** one you no longer need. Your active session is remembered across refreshes.

### 12.2 Chat History Persistence

Every message is logged to `logs/chat_history.jsonl` and reloaded automatically on page refresh — closing the tab never loses your conversation.

### 12.3 Export to Markdown *(v2.1.1)*

Click **⬇ Export** in the session bar (or run it from Ctrl+K) to download the current conversation as a clean, role-labeled, timestamped Markdown file — ready to archive, paste into a doc, or share. The CLI equivalent is `/export md` (also supports `json` and `txt`).

### 12.4 Rewind

`/rewind [n]` (default 2) deletes the last *n* messages from history and from the on-disk log — the fast way to erase a wrong turn without wiping the whole conversation.

### 12.5 Context Icebox — Reclaim Tokens Surgically

Click the topbar **CTX** meter (or Ctrl+K → "Context Icebox") to open an itemized view of everything currently filling the model's context window — every message with its role, a preview, and an estimated token cost, with image messages flagged. It's the surgical alternative to `/compact` (which summarizes everything) and `/rewind` (which only trims from the end):

- **🗑 Drop** any single heavy item — a giant pasted log, an old screenshot — to reclaim exactly those tokens while keeping the rest of the conversation intact.
- **🖼 Strip all images** in one click — images keep their text but lose the pixels, usually the single biggest token win.

The CTX meter updates live as you trim. Safe by design: your conversation history holds only clean message text (tool-call machinery lives elsewhere), so dropping an item never corrupts the conversation.

---

## 13. Sub-Agents & the Swarm Tab

Galactic AI can delegate work to parallel sub-agents instead of doing everything serially in the main chat — the "Hive Mind" architecture.

- **Holo-Map Visualizer** — a live node graph of active sub-agents (or a flat list view via **📋 List View**), showing what each one is working on in real time.
- **Build Chain** — manually construct a multi-step agent chain.
- **Auto-Swarm Orchestrator** (toggle) — when enabled, the main AI can autonomously decide to delegate a sub-task to a dynamically spawned swarm rather than asking you first.
- **Allow Online Models in Auto-Swarm** (toggle) — when disabled, auto-spawned swarm agents are restricted to your local Ollama models only, so autonomous delegation can never quietly rack up cloud costs; a whitelist selector further restricts which specific models are eligible.
- **Clear Completed** / **Refresh Swarm** — housekeeping for the active-agent list.
- **🧠 Blackboard** — a live panel of the shared agent memory. Agents don't just hand finished results downstream; they can publish intermediate findings to a shared key/value store *mid-task* (`blackboard_write`) and read or **wait for** each other's keys (`blackboard_read` / `blackboard_wait_for`). Example: a research agent posts a URL the instant it finds one, and a scraper running in parallel — blocked on `blackboard_wait_for('target_url')` — wakes up and proceeds the moment it lands. Every write shows up in this panel in real time, so you can watch agents collaborate.

---

## 14. Messaging Bridges

### 14.1 Telegram

Set up once (BotFather token + your chat ID from `@userinfobot` in the Setup Wizard), then control Galactic AI from your phone with full voice I/O — send a voice message, get one back.

| Command | Does |
|---|---|
| `/status` [`full`] | System telemetry (lite or full) |
| `/model` | Switch AI model, or pick an image-generation backend under its Image Models submenu |
| `/models` | Configure primary and fallback models |
| `/browser` | Open a URL in the browser |
| `/screenshot` | Capture a browser screenshot |
| `/cli` | Run a shell command |
| `/compact` | Compact conversation context |
| `/help` | Interactive command menu |

Or just send any plain message — text or voice — and Byte responds normally.

### 14.2 Discord

Full bot integration with slash commands and typing indicators. Create a bot at discord.com/developers, add the token under `discord.bot_token` in config, set allowed channels + an admin user ID, restart.

### 14.3 WhatsApp

Uses the official Meta Cloud API — needs a Meta Business account. Configure `whatsapp.phone_number_id`, `access_token`, and `verify_token`.

### 14.4 Gmail

Monitors your inbox via IMAP; Byte can read, respond to, and summarize emails. Needs a Gmail **App Password** (not your login password) under `gmail.email`/`gmail.app_password`.

All bridges default to a strict "Default Deny" authorization model — an unconfigured admin ID means the bridge locks itself down rather than accepting anyone.

---

## 15. Chrome Extension — Galactic Browser

Lets Byte drive your *actual* logged-in Chrome, not a fresh headless one.

**Setup:** `chrome://extensions` → enable Developer mode → **Load unpacked** → select the `chrome-extension/` folder → click the toolbar icon → enter your passphrase → Connect.

**What you get:** real browser control (navigate/click/type/scroll), a side-panel chat with streaming responses, full tab management, form-filling, and JavaScript execution — all through a persistent WebSocket connection with auto-reconnect. See [Tool Categories at a Glance](#94-tool-categories-at-a-glance) for when to prefer this over the headless Playwright tools.

---

## 16. The Galactic CLI

`python galactic_cli.py` gives you a terminal-native companion to the same backend — full command history, autocomplete, and rich-formatted output. **Tab-autocomplete:** type `@` to autocomplete local file paths as you write a prompt. All the [chat slash commands](#5-chat-slash-commands) work here too, forwarded straight to the backend. Additional CLI-only commands:

| Command | Does |
|---|---|
| `/help` | Show all commands |
| `/clear` | Clear context and terminal |
| `/compact` | Trigger deep history compaction |
| `/agents` / `/tasks` | List active sub-agents |
| `/desktop` | Launch the web Control Deck UI |
| `/btw <question>` | Ask a side question without polluting main conversation history |
| `/commit` | Auto-generate a commit message from `git diff` and commit |
| `/context` | Token usage & model info |
| `/context viz` | Render a visual ASCII tree-map breakdown of what's filling the context window |
| `/cost` | Session cost & token statistics |
| `/verbose` | Toggle expanded thinking output |
| `/thinking` | Toggle extended thinking mode |
| `/cwd` / `/cd` | Show or change working directory |
| `/memory <query>` | Search long-term memory |
| `/skills` | List available tools & skills |
| `/skill` | List/load/trigger YAML prompt-template skills |
| `/plan [on\|off]` | Toggle Plan Mode — the backend structures responses as step-by-step plans |
| `/auto [prompt]` | Toggle Auto Mode — the agent executes tools continuously until the task's done, optionally starting from `prompt` |
| `/rewind [n]` | Undo the last *n* messages |
| `/boost [model]` / `/retry` / `/hybrid [on\|off]` | See [Models, Providers & Cost](#7-models-providers-cost) |
| `/save` / `/load` | Save/load a session to/from a JSON file |
| `/history [n]` | Show recent conversation history |
| `/config` | View/edit config settings |
| `/status` | Full system status |
| `/worktree` | Manage isolated git worktrees for safe sandboxed changes |
| `/vcr <snapshot\|undo\|list> <file>` | File-level snapshot/undo via the VCR & Thinkback skill |
| `/permissions [allow\|deny] <pattern>` | View or restrict which tools the AI may call |
| `/shutup` / `/quiet` | Stop any currently-playing TTS immediately |
| `/exit` | Quit the CLI |

---

## 17. Personality & Personas

Set in the Setup Wizard or `personality.mode` in config:

- **byte** *(default)* — the techno-hippie familiar: chill, resourceful, curious about stars and code.
- **custom** — your own name/soul/user-context, set in the wizard or config.
- **generic** — neutral, professional, no personality flavor.
- **files** — auto-activated when you import your own `IDENTITY.md`/`SOUL.md`/`USER.md` (e.g. from OpenClaw).

Switch on the fly with natural language in chat: *"switch personality to homer"* (aliases like "homer", "byte", "generic" are recognized directly; anything else is treated as a custom mode name) — no restart needed, takes effect on your very next message.

---

## 18. Security & Remote Access

- The web UI binds to **localhost only** (`127.0.0.1`) by default — nothing is exposed to your network unless you turn on remote access.
- **Remote access** (`web.remote_access: true` in config) binds to `0.0.0.0`, requires JWT auth (HMAC-SHA256, 24h expiry) on every `/api/*` call, rate-limits logins (5/min) and general API calls (60/min), and auto-adds a Windows Firewall inbound rule for the port. Local connections from `127.0.0.1`/`::1` always bypass auth, so the machine itself is never locked out.
- Your passphrase is stored only as a SHA-256 hash.
- All API keys and secrets live in **`config.local.yaml`**, a gitignored overlay — the tracked `config.yaml`/`config.template.yaml` is a sanitized template only. Never hand-edit secrets into the tracked template.
- `VAULT.md` is gitignored and explicitly protected by the updater.
- Ollama-only usage means literally nothing leaves your machine.
- Every tool call has a configurable timeout (default 60s) and the whole ReAct loop is capped by a wall-clock `speak_timeout` (default 600s) — nothing can hang forever.

Found an actual vulnerability? Do **not** open a public GitHub issue — email **chesley@cmmchsvc.net** per [`SECURITY.md`](SECURITY.md).

---

## 19. Updating

```powershell
.\update.ps1              # Windows — latest release
.\update.ps1 -Version v2.1.0   # pin a specific version
```
```bash
./update.sh                # Linux/macOS
./update.sh v2.1.0
```

The updater checks GitHub, backs up your config to `logs/backups/` first, updates source files, and **never touches** your config, API keys, memory files, or chat history. Galactic AI also self-checks for new releases on startup and every 6 hours, showing a dismissible Control Deck banner when one's available.

---

## 20. Troubleshooting

| Symptom | Fix |
|---|---|
| Desktop exe closes immediately | Check `logs/desktop_launcher.log`; ensure `config.yaml` sits next to the exe (or one folder up) |
| Desktop exe always shows Setup Wizard | Delete any stray `config.yaml` inside `dist/` — the exe looks one level up from there |
| `No module named 'aiohttp'` | `pip install -r requirements.txt` |
| Playwright executable missing | `playwright install chromium` |
| Ollama models not appearing | Make sure `ollama serve` is running; discovery polls every 60s |
| Web UI won't load | Check port 17789 is free, or change `web.port` in config |
| Voice messages not transcribing (Telegram) | Configure an OpenAI or Groq key for cloud STT fallback |
| Memory tab looks empty | Just click into it — starter templates are created on first visit |
| Telegram `/model` shows an empty provider | That provider's API key isn't set — it's listed but will fail if selected |
| A Telegram response is slow/times out | Individual tools time out at 60s, overall response cap is 180s — a hung tool is skipped and Byte tries another approach |
| Boost/Hybrid says "no boost model available" | Set `models.boost_provider`/`boost_model` (or an Architect model) in Settings, or add any cloud API key |

Run **🩺 diagnostics** from the Ctrl+K palette (or `GET /api/doctor`) any time for an on-demand health check covering the same tests as boot preflight.

---

## 21. Appendix A — Configuration Quick Reference

Two files matter: the tracked, sanitized **`config.template.yaml`** (safe defaults, no secrets — never hand-edit real keys into this one) and the gitignored **`config.local.yaml`** overlay, which is where every in-app writer (Settings, Models tab, CLI, voice agent) actually saves. `config_loader.py` deep-merges them at load time, overlay winning.

Key sections you'll touch most:

```yaml
models:
  primary_provider: ollama
  primary_model: qwen3:8b
  fallback_provider: google
  fallback_model: gemini-3-flash-preview
  boost_provider: anthropic          # optional — see the Boost & Retry section
  boost_model: claude-opus-4-6
  hybrid_coding:                     # optional — see the Hybrid Coding Mode section
    enabled: false
    architect_provider: anthropic
    architect_model: claude-opus-4-6
    builder_provider: ollama
    builder_model: qwen3.6:27b
  planner_provider: google
  planner_model: gemini-3.1-pro-preview
  auto_fallback: true
  streaming: true
  speak_timeout: 600
  max_turns: 50

web:
  host: 127.0.0.1
  port: 17789
  remote_access: false               # see the Security & Remote Access section

telegram:
  enabled: true
  bot_token: YOUR_TELEGRAM_BOT_TOKEN
  admin_chat_id: 'YOUR_CHAT_ID'

tool_timeouts:
  exec_shell: 120
  execute_python: 60
  generate_image: 180
  generate_video: 300
```

Full provider list (`providers:`), messaging bridges (`discord:`/`whatsapp:`/`gmail:`), social media keys, and per-model context-window overrides all live in the same file — see the generously-commented `config.template.yaml` for every available key.

---

## 22. Appendix B — Where to Learn More

| Doc | For |
|---|---|
| [`README.md`](README.md) | Install steps, provider list, quick architecture overview |
| [`FEATURES.md`](FEATURES.md) | Full technical feature reference — how things work under the hood |
| [`TOOLS.md`](TOOLS.md) | Exhaustive tool catalogue with parameters |
| [`CHANGELOG.md`](CHANGELOG.md) | Version-by-version history of everything shipped |
| [`SECURITY.md`](SECURITY.md) | Supported versions & how to report a vulnerability |
| [`PROJECT_STATE.md`](PROJECT_STATE.md) | Current development status and open items (maintainer-facing) |
| **This manual** | The task-oriented "how do I actually use it" guide |

If something in the app doesn't match what's written here, trust the app — this manual describes v2.1.1 and gets updated alongside new releases, but the running code is always the final word.
