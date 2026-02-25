# PROJECT STATE

**Last Updated:** 2026-02-24
**Owner:** Chesley McDaniel (DirtyHippie / Ches)
**Repo Path:** F:\Galactic AI
**Public Release Path:** F:\Galactic AI Public Release
**Current Version:** v1.1.4

---

## Summary
Galactic AI is a fully custom AI assistant platform built by Chesley McDaniel. It runs locally on Windows, connects to multiple LLM providers, has a web-based Control Deck UI, Telegram/Discord/Gmail/WhatsApp bridges, a Chrome extension, a skills/plugin system, memory persistence, and a scheduler. Development was primarily done in Claude Code (now suspended) and continues here.

---

## Current Focus
- Telegram UX polish: `/status` lite/full, menu + `/help` docs

---

## Active Tasks
- [x] Get automation ability working reliably (Browser stable IDs, Wait tools, Desktop Window awareness)
- [x] Deep scan all files and build full mental map of codebase
- [x] Resume development that was happening in Claude Code
- [x] Implement Strategic Planner in ReAct loop
- [x] Add Long-Term Vector Memory (ChromaDB)
- [x] Build auto-release script
- [x] Implement Self-Healing Code Execution (Test-Driven Development)
- [x] Implement Workspace Context Awareness (RAG for Local Codebase)

---

## Milestones
- [x] v1.1.8 Self-Healing Code & Workspace RAG updates completed
- [x] v1.1.8 Computer Use & Live Voice updates completed
- [x] v1.1.6 Strategic Planning & Deep Memory updates completed
- [x] Restart resilience: conversation_auto_recall + boot_recall_banner community skills
- [x] v1.1.2 release implementation plan completed
- [x] v1.1.4 current version
- [x] SCAN_REPORT.md generated (full recursive scan of F:\Galactic AI)
- [x] SCAN_REPORT_PUBLIC_RELEASE.md generated (full recursive scan of F:\Galactic AI Public Release)
- [x] PROJECT_STATE.md created with auto-update workflow

---

## Blockers / Issues
- Anthropic suspended the Claude Code account used to build Galactic AI
- Session memory loss on restart (being addressed with this file)

---

## Key Files / Paths
- `F:\Galactic AI\gateway_v2.py` — Main LLM router, tool registry, ReAct loop (255KB)
- `F:\Galactic AI\galactic_core_v2.py` — Orchestrator, startup, config loader
- `F:\Galactic AI\web_deck.py` — Control Deck UI + REST API + WebSocket relay (275KB)
- `F:\Galactic AI\telegram_bridge.py` — Telegram bot + voice (64KB)
- `F:\Galactic AI\memory_module_v2.py` — Memory persistence
- `F:\Galactic AI\model_manager.py` — Provider routing + fallback chain
- `F:\Galactic AI\config.yaml` — Main config
- `F:\Galactic AI\plugins\` — Runtime tool adapters
- `F:\Galactic AI\skills\` — Core + community skills
- `F:\Galactic AI\chrome-extension\` — Chrome extension + sidepanel UI
- `F:\Galactic AI\docs\plans\` — Design + implementation plans
- `F:\Galactic AI\SCAN_REPORT.md` — Full recursive scan report
- `F:\Galactic AI\SCAN_REPORT_PUBLIC_RELEASE.md` — Public release scan report
- `C:\Users\Chesley\Downloads\Plan complete and saved to docsplan.txt` — Saved plan
- `F:\Galactic AI\docs\plans\2026-02-23-v1.1.2-release-implementation.md` — COMPLETED

---

## Release Status
- **Current:** v1.1.4
- **Previous:** v1.1.2 (plan completed, see docs/plans/)
- **Public Release Folder:** F:\Galactic AI Public Release

---

## Commands / How to Run
- Launch: `python galactic_core_v2.py` or `launch.ps1` / `launch.sh`
- Install: `install.ps1` (Windows) / `install.sh` (Linux/Mac) / `install-chromebook.sh`
- Update: `update.ps1` / `update.sh`
- Flush logs: `python flusher.py`

---

## Architecture Overview
- **Core:** galactic_core_v2.py -> gateway_v2.py (ReAct loop + tools) -> model_manager.py (LLM routing)
- **UI:** web_deck.py (Control Deck) + index.html
- **Bridges:** telegram_bridge.py, discord_bridge.py, gmail_bridge.py, whatsapp_bridge.py
- **Tools:** plugins/ + skills/ (core + community)
- **Memory:** memory_module_v2.py + imprint_engine.py + MEMORY.md
- **Chrome:** chrome-extension/ (background.js, content.js, sidepanel)
- **Providers:** Google, Anthropic, OpenAI-compatible (OpenRouter, Groq, Mistral, XAI, Cerebras, HuggingFace, Kimi, MiniMax, ZAI), NVIDIA/NIM, Ollama (local)

---

## Internal System
- 2026-02-23: Full recursive scan completed for both F:\Galactic AI and F:\Galactic AI Public Release
- 2026-02-23: PROJECT_STATE.md created with auto-update workflow enabled
- 2026-02-23: Session memory workaround implemented via this file
- Scan Reports:
  - `F:\Galactic AI\SCAN_REPORT.md` — Full recursive file tree of the main working directory (F:\Galactic AI). Includes every file path, size, timestamp, and file-type breakdown. Use this to orient quickly after a session reset — shows all source files, plugins, skills, docs, logs, releases, and assets in one place.
  - `F:\Galactic AI\SCAN_REPORT_PUBLIC_RELEASE.md` — Full recursive file tree of the public release folder (F:\Galactic AI Public Release). Tracks what has been packaged and shipped to end users. Compare against main working directory to spot what's been released vs what's still in dev.

---

## Notes
- Ches identifies as a techno-hippie, non-conformist, likely autistic (undiagnosed)
- Was building Galactic AI in Claude Code before Anthropic suspended account
- Development now continues directly inside Galactic AI itself
- The platform IS the working directory — F:\Galactic AI is where Galactic AI runs from
