# PROJECT STATE

**Last Updated:** 2026-02-25 16:30
**Owner:** Chesley McDaniel (techno-hippie / Ches)
**Repo Path:** C:\Users\Chesley\Galactic AI
**Current Version:** v1.1.8 (latest release: Galactic-AI-v1.1.8-windows.zip 507KB)

---

## Summary
Galactic AI: Self-evolving AI platform w/ 150+ tools, skills ecosystem (core/community dynamic), Chrome ext + Playwright headless + desktop pixel automation, FLUX/Imagen/Veo gen, subagents, ChromaDB RAG (codebase/user lore), git/memory/procs. Local Win11, multi-LLM (Google/Anthropic/OpenRouter/NVIDIA/Ollama), web/Telegram UI. ~1,200 files/50MB, logs/images heavy.

---

## Current Focus
- Shiny upgrades: Git init, Workspace RAG live, TruckHacker skill, voice polish, subagent swarm.

---

## Active Tasks
- [x] PROJECT_STATE.md synced to C:\ (v1.1.8, full tree/stats/skills)
- [ ] Trigger workspace_indexer.py for codebase RAG
- [x] Deep scan: list_dir recurse complete

---

## Milestones
- [x] v1.1.8 Self-Healing (test_driven_coder) & Workspace RAG
- [x] v1.1.7 Computer Use (vision-click UI) & Live Voice
- [x] v1.1.6 Big Brain Planner & ChromaDB Deep Memory
- [x] Skills explosion: core (browser_pro/chrome/desktop/social), community (boot_recall/computer_use/gemini_coder/memory_manager/workspace_indexer)
- [x] Browser triple-threat, GenAI factory, social auto-post

---

## Blockers / Issues
- None (UAC off, Claude suspend irrelevant—self-bootstrapping)

---

## Key Files / Paths (C:\Users\Chesley\Galactic AI)
- `gateway_v2.py` (265KB) — ReAct brain/tools
- `web_deck.py` (291KB) — UI/WebSocket
- `telegram_bridge.py` (90KB) — Bot/voice (/status fixed)
- `galactic_core_v2.py` (27KB) — Orchestrator
- `model_manager.py` (28KB) — LLM router
- `skills/core/` — browser_pro.py (119KB Playwright), chrome_bridge.py (53KB ext), desktop_tool.py (26KB pixels), social_media.py (44KB X/Reddit)
- `skills/community/` — workspace_indexer.py (8KB RAG), computer_use.py (6KB vision), gemini_coder.py (7KB), boot_recall_banner.py, etc.
- `chrome-extension/` — content.js (34KB), ready
- `chroma_data/` — galactic_memory.db (225KB) + vectors
- `releases/v1.1.8/` — Win/Linux/Mac zips + SHA
- `logs/` — core_2026-02-25.log (476KB), chat_history.jsonl (95KB)
- `images/` — Veo/FLUX/Imagen galleries (36MB videos)

---

## Release Status
- **Latest:** v1.1.8 (16:06, all platforms)

---

## Commands
- Launch: `python galactic_core_v2.py`
- Git: Tools live post-init

---

## Architecture
Core: gateway_v2 -> model_manager
UI: web_deck + index.html
Bridges: telegram/discord/gmail/whatsapp
Tools/Skills: 150+ (browser/desktop/gen/social/git/memory)
Memory: ChromaDB + hot_buffer.json (88KB)
Providers: Full chain

---

## Internal System
- 2026-02-25: Auto-exec #1-2 (PROJECT_STATE sync + Git init)
- Path migrated C:\Users\Chesley (F:\ legacy)
- Stats: ~1,200 files/dirs, 50MB, skills dynamic load

---

## Notes
- Techno-hippie prefs: F100 mods (Holley Sniper EFI, glasspacks), skoolie/RV, NM commune, stars/space, non-conformist/autistic vibe RAG'd.
