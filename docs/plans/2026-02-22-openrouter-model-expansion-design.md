# OpenRouter Model Expansion — Design

**Date:** 2026-02-22
**Status:** Approved

---

## Goal

Add the user's OpenRouter API key and expand the curated model list from 6 to 26 models across the Control Deck Models page, Telegram model menus, and running config.

## Current State

OpenRouter is already fully integrated as an OpenAI-compatible provider:
- Gateway routing, streaming, headers (`HTTP-Referer`, `X-Title`) all working
- 6 curated models in web_deck.py Models page
- 5 models in telegram_bridge.py model menus
- No API key configured in either config.yaml

## Changes Required

### 1. Config — Add API Key
Add `providers.openrouter.apiKey` to the running installation config at `F:\Galactic AI\config.yaml`.


Also add a placeholder to the template config at `F:\Galactic AI Public Release\config.yaml`.

### 2. web_deck.py — Expand Model Cards (6 → 26)

Replace the existing 6-model OpenRouter section with 26 curated models organized by tier:

**Frontier (7 models):**
- Gemini 3.1 Pro Preview — `google/gemini-3.1-pro-preview`
- Claude Opus 4.6 — `anthropic/claude-opus-4.6`
- GPT-5.2 — `openai/gpt-5.2`
- GPT-5.2 Codex — `openai/gpt-5.2-codex`
- Grok 4.1 Fast — `x-ai/grok-4.1-fast`
- DeepSeek V3.2 — `deepseek/deepseek-v3.2`
- Qwen 3.5 Plus — `qwen/qwen3.5-plus-02-15`

**Strong (12 models):**
- Gemini 3 Pro Preview — `google/gemini-3-pro-preview`
- Gemini 3 Flash Preview — `google/gemini-3-flash-preview`
- Claude Sonnet 4.6 — `anthropic/claude-sonnet-4.6`
- Claude Opus 4.5 — `anthropic/claude-opus-4.5`
- GPT-5.2 Pro — `openai/gpt-5.2-pro`
- GPT-5.1 — `openai/gpt-5.1`
- GPT-5.1 Codex — `openai/gpt-5.1-codex`
- Qwen 3.5 397B — `qwen/qwen3.5-397b-a17b`
- Qwen 3 Coder Next — `qwen/qwen3-coder-next`
- Kimi K2.5 — `moonshotai/kimi-k2.5`
- DeepSeek V3.2 Speciale — `deepseek/deepseek-v3.2-speciale`
- GLM-5 — `z-ai/glm-5`

**Fast / Efficient (7 models):**
- Mistral Large 2512 — `mistralai/mistral-large-2512`
- Devstral 2512 — `mistralai/devstral-2512`
- MiniMax M2.5 — `minimax/minimax-m2.5`
- Sonar Pro Search — `perplexity/sonar-pro-search`
- Nemotron Nano 30B — `nvidia/nemotron-3-nano-30b-a3b`
- Step 3.5 Flash — `stepfun/step-3.5-flash`
- GPT-5.2 Chat — `openai/gpt-5.2-chat`

### 3. telegram_bridge.py — Expand Telegram Model Menus

Update both OpenRouter model menus in the Telegram bridge to include ~10 top models (subset of the 26 — the most commonly used ones).

### 4. model_manager.py — Update Default Model

Update the OpenRouter default fallback model from `anthropic/claude-sonnet-4` to `anthropic/claude-sonnet-4.6`.

## Files Modified

| File | Change |
|------|--------|
| `F:\Galactic AI\config.yaml` | Add OpenRouter API key |
| `F:\Galactic AI Public Release\config.yaml` | Add OpenRouter placeholder section |
| `web_deck.py` | Replace 6 model cards with 26 |
| `telegram_bridge.py` | Expand both model menus to ~10 models |
| `model_manager.py` | Update default fallback model |

## No Gateway Changes Needed

The gateway already handles OpenRouter perfectly — routing, streaming, headers, vision, multi-turn. Zero code changes needed in gateway_v2.py.
