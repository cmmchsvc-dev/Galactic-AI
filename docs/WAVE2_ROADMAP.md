# Agentic Superpowers — Wave 2 Roadmap

Deferred features from the second Gemini Deep Think review. **Wave 1 (shipped in v2.1.3):** AST-safe editing (`list/read/replace_function`), `ask_user` human-in-the-loop, Terminal-to-Brain button.

These remaining items are deferred because they're larger, touch riskier code paths (the streaming ReAct loop, the browser skills, the write/edit tools I recently hardened), or need design decisions — not because they're bad ideas. Several are excellent. Each entry below is scoped enough to hand straight to a coding agent, ordered by value-to-risk.

The `ask_user` plumbing built in Wave 1 (WS event → `asyncio.Future` keyed by id → `POST /api/ask_user/respond`) is the reusable pattern for anything needing a blocking frontend round-trip — reuse it for #1.

---

## 1. The Crucible — `require_approval` diff gate ✅ SHIPPED (v2.1.4)

Built as an opt-in gate on `write_file`/`edit_file`/`replace_function` — each tool now splits compute-from-write, emits an `approval_request` WS event with a unified diff, and awaits an `asyncio.Future` (resolved by `POST /api/approval/respond`) before writing. Colorized diff modal in the deck with Approve / Reject(+feedback); timeout → reject (safe); default OFF = byte-for-byte unchanged. Settings toggle wired. 17 tests incl. default-off-unchanged for all three tools.

---

## 2. Set-of-Mark browser vision ⭐ (next up)

**What:** before asking a vision model to act on a page, inject JS that draws numbered high-contrast boxes over every clickable element, screenshot that, and let the model reply `click_id: 12`. JS maps the id back to the DOM node. Dramatically cuts selector hallucination on React/Vue DOMs.

**Where:** `chrome_bridge.py` / extension content script + `skills/core/browser_pro`. Add `chrome_annotate` + `chrome_click_id` (and Playwright equivalents).

**Why deferred:** touches two browser stacks; needs the annotation JS + an id→element map that survives between the screenshot and the click.

---

## 3. Swarm Blackboard — shared multi-agent memory ✅ SHIPPED (v2.1.5)

Built as `blackboard.py` (async KV store: write/read/list/`wait_for` with per-key asyncio.Events + timeout) + 4 gateway tools + `core.blackboard` (lazy). The swarm orchestrator mirrors each wave result onto it; Swarm tab shows a live panel (`GET /api/blackboard` + `blackboard_update` WS). 20 tests incl. the concurrency path (wait_for blocks → resolves on peer write → times out). Since sub-agents run via `speak_isolated` on the shared gateway, they get the tools automatically.

---

## 4. Ghost-Cam — headless browser live PiP

**What:** while Playwright is active, capture a low-res base64 JPEG every ~1s, stream over WS, render in a draggable picture-in-picture pane so you can watch background automation.

**Where:** `browser_pro` skill + a PiP component in `deck_modern.html`.

**Why deferred:** continuous JPEG-over-WS is bandwidth-heavy; needs start/stop tied to browser lifecycle and a frame-rate cap. Nice-to-have, not load-bearing.

---

## 5. Mid-thought barge-in — steerable reasoning ✅ SHIPPED (v2.1.7)

Built with the safe layered design: `POST /api/nudge` sets `gateway._pending_nudge` (only while `_speaking`); the 3 provider streamers check it between chunks and break the in-flight `aiter_lines()` loop (clean, they're inside `async with`), setting `_nudge_interrupted`; the choke point after `_call_llm_resilient` discards the partial and `continue`s; the top-of-turn `_consume_pending_nudge()` (extracted + unit-tested) injects the correction as a user message and regenerates. Never hangs. Deck: nudge bar under the thinking orb, shown while working. 14 tests (endpoint + injection state machine); the mid-stream break + regenerate needs a live model stream to fully exercise.

### (original design notes, for reference)

**What:** a "Nudge / Correct" box under the thinking orb. Typing while the model streams sends an `urgent_nudge` WS event; the ReAct loop cancels the current `httpx` stream, appends the nudge as a user correction, and restarts generation.

**Where:** the streaming path in `gateway_v3.py` + frontend.

**Why deferred:** directly manipulates the live streaming loop — the riskiest surface in the app. Cancelling mid-stream cleanly (without corrupting history or the token counters) needs care and thorough testing. High value but do it carefully and in isolation.

---

## 6. Context "Icebox" — interactive token diet ✅ SHIPPED (v2.1.6)

Built as a modal (opened from the CTX meter chip or Ctrl+K) listing each history item with role, preview, and est-token cost + image flag; per-item 🗑 Drop and a Strip-all-images button. `GET /api/context/items`, `POST /api/context/drop` (descending multi-delete, no index shift), `POST /api/context/strip_images`. The tool-pairing risk noted here turned out to be structurally absent: `gw.history` holds only clean user/assistant messages — tool_call/tool_result pairs live in the transient per-turn `messages` list — so dropping any item is safe. Persists like /rewind. 15 tests.

---

## 7. Janitor Daemon — idle background work

**What:** an asyncio task that, after ~30 min of no user input (and with local Ollama available for free compute), purges old `tmp/`, runs `git status`, drafts a commit message for uncommitted changes, and runs the test suite — queuing a chat message if something's broken.

**Why deferred:** autonomous git/test actions while unattended need guardrails (never auto-commit/push without asking; the repo currently has **no test suite** to run — see PROJECT_STATE). Best built as **suggest-only** (it drafts and queues, never executes side effects). Also: this project lives under Google Drive sync, so an idle daemon touching files interacts with that — verify before enabling.

---

### Suggested order

`ask_user` (done) → **Crucible (#1)** → Set-of-Mark (#2) → Blackboard (#3) → Context Icebox (#6) → Ghost-Cam (#4) → mid-thought barge-in (#5, isolate it) → Janitor (#7, suggest-only).
