# PROJECT STATE

**Last Updated:** 2026-07-19
**Owner:** Chesley McDaniel (techno-hippie / Ches)
**Repo Path:** C:\Users\Chesley\Galactic AI
**Current Version:** v2.1.8 (LM Studio + Moonshot/Kimi K3)

---

## Summary

Galactic AI: Self-evolving AI platform with a skills ecosystem, auto-compacting context, semantic recall (ChromaDB + SQLite), resumable workflows (checkpoints), and hierarchical subagents. The active brain is `gateway_v3.py` (not `gateway_v2.py`, which is legacy/archived). Voice is now local-first: `faster-whisper` for speech-to-text and a unified `tts_engine.py` for speech synthesis, both GPU-accelerated where available.

---

## Current Focus

- Post-hardening stability: monitoring the new `config.local.yaml` secrets overlay, the local STT/TTS paths, and the memory-recall category filtering under real daily use.
- Optional next steps (not started): wiring Discord/Gmail bridges with real credentials, running `scripts/purge_stale_index.py --apply` to clean ~16K stale codebase-index chunks from old repo copies, moving the repo out of Google Drive sync (`scripts/move_out_of_drive.ps1`).

---

## Active Tasks

- [x] v2.1.1 QOL: 🚀 Boost/⟳ Retry hybrid escalation (`/api/chat/boost`, `/boost`, `/retry`), per-message provenance (model/time/tokens/fallback chips), message hover toolbar (copy/speak/edit), draft persistence + ArrowUp prompt recall, Markdown chat export
- [x] v2.1.1 🧬 Hybrid Coding Mode: cloud Architect writes code into a blueprint, local Builder applies it (`models.hybrid_coding`, `/hybrid`, Settings → Model Configuration incl. new Boost dropdown)
- [x] v2.1.2 Hardening (from a verified external review): fixed a deck XSS hole (formatMsg now escapes before markdown), search_codebase cross-project leak, execute_python temp sandbox+leak, RAM/diff/thread-pool/canvas/upload nits, trimmed .galactic_map.md injection; documented undersold safety features (VCR auto-backup, write verification, Smart Artifacts, tmp/ sandbox, /context viz)
- [x] v2.1.3 Agentic Superpowers Wave 1: AST-safe editing (`list_functions`/`read_function`/`replace_function`, re-parses before writing), `ask_user` human-in-the-loop tool + deck modal (`/api/ask_user/respond`), Terminal-to-Brain "Ask Byte About Last Error" button
- [x] v2.1.4 Wave 2 #1 — **The Crucible**: opt-in `require_approval` diff gate on write/edit/replace_function (colorized diff modal, Approve/Reject+feedback, timeout→reject, default off = unchanged); `/api/approval/respond`; Settings toggle
- [x] v2.1.5 Wave 2 #3 — **Swarm Blackboard**: live shared KV store (`blackboard.py` + 4 tools + Swarm-tab panel, `wait_for` w/ timeout); orchestrator mirrors wave results
- [x] v2.1.6 Wave 2 #6 — **Context Icebox**: itemized context view (CTX chip / palette), per-item drop + strip-all-images to reclaim tokens (`/api/context/items|drop|strip_images`); safe because history has no tool-call pairs
- [x] v2.1.7 Wave 2 #5 — **Mid-Thought Barge-In**: `/api/nudge` + `_pending_nudge`/`_nudge_interrupted` flags; mid-stream break in 3 streamers + top-of-turn `_consume_pending_nudge()` injection + post-call discard; nudge bar under the thinking orb. (Endpoint+injection unit-tested; mid-stream break needs a live model to fully exercise.)
- [ ] Wave 2 remaining (need live browser/hardware to verify): Set-of-Mark browser vision, Ghost-Cam browser PiP; deferred: Janitor idle daemon — see `docs/WAVE2_ROADMAP.md`
- [x] Secrets moved from tracked `config.yaml` to gitignored `config.local.yaml` overlay
- [x] Local speech-to-text (faster-whisper) wired into wake-word agent + `/api/stt`
- [x] Unified TTS engine (`tts_engine.py`) shared by voice agent + API; voice barge-in added
- [x] `search_codebase` tool — semantic search over the Neural Indexer's code index
- [x] Discord + Gmail bridges instantiated and started behind `config.enabled` flags
- [x] Control Deck Memory Browser (search/list/delete memories) + named chat sessions
- [x] Fixed the "no final response" think-only bug, persona name bleed, dead `/ws/terminal` route, broken voice screen-vision, missing CLI memory endpoints, a remote-access JWT bug
- [x] Memory recall excludes `codebase_index` by default (no more code chunks drowning out personal memories)
- [ ] Run `scripts/purge_stale_index.py --apply` to purge stale cross-install code chunks
- [ ] Move repo out of Google Drive sync (`scripts/move_out_of_drive.ps1`)
- [ ] Rotate API keys/tokens that were previously exposed in the tracked config

---

## Milestones

- [x] v2.1.0 Local Voice & Smarter Memory Update (this release)
- [x] v1.6.9 The Loop Defense / Hallucination Defense Update
- [x] v1.4.x Security Hardening (Discord/WhatsApp "Default Deny")
- [x] v1.3.0 The Intelligence Update (Agentic Code Intelligence, SOUL v2, Surgical Editing)
- [x] v1.2.1 The Control Update (Centralized Model Manager, OpenClaw provider parity)
- [x] v1.2.0 The Hivemind Update (Resumables, Oracle, CLI Bridge)

---

## Blockers / Issues

- None functionally, but two housekeeping items are open (see Active Tasks): key rotation and the Google Drive sync risk (Drive has already produced conflict-copy artifacts in this working tree; `git fsck` is currently clean).

---

## Key Files / Paths (C:\Users\Chesley\Galactic AI)

- `gateway_v3.py` — active ReAct brain (gateway_v2.py is legacy, archived)
- `gateway_tools.py` — tool implementations mixed into the gateway
- `config_loader.py` — template + gitignored-overlay config loader (`config.yaml` + `config.local.yaml`)
- `galactic_memory.py` — the real vector/episodic memory engine (ChromaDB + SQLite)
- `local_stt.py` — local speech-to-text (faster-whisper)
- `tts_engine.py` — shared text-to-speech synthesis (edge-tts/ElevenLabs/Fish Speech/Piper/Chatterbox)
- `web_deck.py` — Control Deck server (aiohttp), serves `deck_modern.html`
- `skills/core/voice_agent.py` — wake-word listening + TTS playback + barge-in
- `skills/core/neural_indexer.py` — background codebase vector indexer (feeds `search_codebase`)
- `config/models.yaml` — centralized model configuration
- `scripts/purge_stale_index.py`, `scripts/move_out_of_drive.ps1` — maintenance tooling
- `logs/runs/` — persistent workflow checkpoints
- `_archive/cleanup_2026-07-16/` — dead/duplicate files archived this release

---

## Release Status

- **Latest:** v2.1.0 (Current)

---

## Commands

- Launch: `python galactic_core_v2.py`
- CLI: `python galactic_cli.py`
- Build: `python scripts/release.py`
- Purge stale code-index chunks: `python scripts/purge_stale_index.py --apply`

---

## Architecture

Core: `gateway_v3.py` -> `model_manager.py`
UI: `web_deck.py` + `deck_modern.html` (+ `index.html` for the public landing page)
Voice: `local_stt.py` (faster-whisper) + `tts_engine.py` (unified synthesis) via `skills/core/voice_agent.py`
Bridges: telegram (active) / discord + gmail (wired, off by default) / whatsapp (unwired)
Tools/Skills: core (`skills/core/`) + community (`skills/community/`, via `skills/registry.json`)
Memory: `galactic_memory.py` (ChromaDB + SQLite), category-filtered recall, Neural Indexer feeds `codebase_index`
Providers: full redundant fallback chain (`model_manager.py`)

---

## Notes

- Techno-hippie prefs: F100 mods (Holley Sniper EFI, glasspacks), skoolie/RV, NM commune, stars/space, non-conformist vibe.
