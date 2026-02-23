# Galactic AI v1.1.2

## What's New — Skills Ecosystem

### ⚡ GalacticSkill Base Class
Every capability in Galactic AI is now a \ subclass. Skills declare structured metadata and register their tools dynamically — no more hardcoded gateway monolith. Add new capabilities by writing a skill class and dropping it in \.

**Metadata every skill carries:** \, \, \, \, \, \, 

**Lifecycle hooks:** \, \, \ (background loop)

---

### ⚡ 6 Core Skills (88 Tools Migrated)

All 6 built-in capabilities are now proper skills:

| Skill | Tools | Category |
|-------|-------|----------|
| ShellSkill | 1 — \ | system |
| DesktopSkill | 8 — mouse, keyboard, screenshot | desktop |
| ChromeBridgeSkill | 16 — real Chrome browser control | browser |
| SocialMediaSkill | 6 — Twitter/X + Reddit | social |
| SubAgentSkill | 2 — spawn + monitor subagents | agents |
| BrowserProSkill | 55 — full Playwright automation | browser |

**Total: 147 tools**

---

### ⚡ AI Self-Authoring
Byte can create new skills at runtime with three new meta-tools:

- **\** — Write Python code in chat, Byte validates (AST), saves to \, and loads it immediately. No restart required.
- **\** — See all loaded skills with full metadata and tool lists.
- **\** — Safely unload a community skill and delete its file.

Community skills persist across restarts via \.

**Example:** Ask Byte to "create a skill called weather_checker that fetches current weather for a city" and \ is immediately available as a tool.

---

### ⚡ Skills Tab in Control Deck
The Plugins tab is now the **Skills tab**. Rich skill cards show:
- Icon, display name, version, author
- **CORE** or **COMMUNITY** badge
- Full description
- Tool count and tool name preview

---

## Updating

\n\n
Pin to this version:
\n
---

## Files Added

| File | Description |
|------|-------------|
| \ | GalacticSkill base class |
| \ | Package init |
| \ | Core skills package |
| \ | Community skills package |
| \ | ShellSkill (1 tool) |
| \ | DesktopSkill (8 tools) |
| \ | ChromeBridgeSkill (16 tools) |
| \ | SocialMediaSkill (6 tools) |
| \ | SubAgentSkill (2 tools) |
| \ | BrowserProSkill (55 tools) |
| \ | Community skill manifest |

## Files Modified

| File | Changes |
|------|----------|
| \ | \, \, \, removed \ |
| \ | \, \ / \ / \ meta-tools, removed 88 hardcoded tool handlers |
| \ | Skills tab with rich metadata, skill_name fallbacks, toggle support |

---

## Previous Releases

- **v1.1.1**: Galactic Browser Chrome extension, Social Media plugin, Telegram reliability overhaul, WebSocket auth fix
- **v1.1.0**: OpenRouter model expansion (26 models), Token Cost Dashboard, multi-currency support
- **v1.0.9**: Google Veo video generation, NVIDIA provider hardening, chat scroll fix

---

**Full documentation:** [README.md](../../README.md) | [FEATURES.md](../../FEATURES.md) | [CHANGELOG.md](../../CHANGELOG.md)

**License:** MIT
