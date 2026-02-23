# Token Cost Dashboard — Design

**Date:** 2026-02-22
**Status:** Approved

---

## Goal

Add a polished, layman-friendly cost dashboard to the Status tab of the Control Deck. Shows real token costs in multiple currencies (USD default), with interactive charts comparing model spend over time.

## Design Decisions

- **Real API token counts** — Parse actual `prompt_tokens`/`completion_tokens` from provider responses. Fall back to ~4 chars/token estimation when unavailable.
- **Persistent tracking** — Append-only JSONL log (`logs/cost_log.jsonl`) survives restarts. Enables historical views (today, this week, this month).
- **Static exchange rates** — Hardcoded rates updated per release. No external API dependency.
- **Inline in Status tab** — New "Cost Dashboard" section below System Overview. No new tab.
- **Chart.js via CDN** — Lightweight (~70KB gzipped), dark-theme compatible.
- **Free models show FREE** — NVIDIA, Cerebras, Groq, HuggingFace, Ollama tracked for tokens but excluded from spend charts.

---

## Data Layer

### Pricing Dictionary (`gateway_v2.py`)

```python
MODEL_PRICING = {
    # OpenRouter — Frontier
    "google/gemini-3.1-pro-preview":   {"input": 1.25,  "output": 10.00},
    "anthropic/claude-opus-4.6":       {"input": 15.00, "output": 75.00},
    "openai/gpt-5.2":                  {"input": 2.50,  "output": 10.00},
    "openai/gpt-5.2-codex":            {"input": 2.50,  "output": 10.00},
    "x-ai/grok-4.1-fast":              {"input": 3.00,  "output": 15.00},
    "deepseek/deepseek-v3.2":          {"input": 0.27,  "output": 1.10},
    "qwen/qwen3.5-plus-02-15":         {"input": 0.30,  "output": 1.20},

    # OpenRouter — Strong
    "google/gemini-3-pro-preview":     {"input": 1.25,  "output": 5.00},
    "google/gemini-3-flash-preview":   {"input": 0.10,  "output": 0.40},
    "anthropic/claude-sonnet-4.6":     {"input": 3.00,  "output": 15.00},
    "anthropic/claude-opus-4.5":       {"input": 15.00, "output": 75.00},
    "openai/gpt-5.2-pro":             {"input": 2.50,  "output": 10.00},
    "openai/gpt-5.1":                  {"input": 2.00,  "output": 8.00},
    "openai/gpt-5.1-codex":            {"input": 2.00,  "output": 8.00},
    "qwen/qwen3.5-397b-a17b":          {"input": 0.40,  "output": 1.60},
    "qwen/qwen3-coder-next":           {"input": 0.30,  "output": 1.20},
    "moonshotai/kimi-k2.5":            {"input": 0.60,  "output": 2.40},
    "deepseek/deepseek-v3.2-speciale": {"input": 0.27,  "output": 1.10},
    "z-ai/glm-5":                      {"input": 0.50,  "output": 2.00},

    # OpenRouter — Fast
    "mistralai/mistral-large-2512":    {"input": 2.00,  "output": 6.00},
    "mistralai/devstral-2512":         {"input": 0.10,  "output": 0.30},
    "minimax/minimax-m2.5":            {"input": 0.15,  "output": 0.60},
    "perplexity/sonar-pro-search":     {"input": 3.00,  "output": 15.00},
    "nvidia/nemotron-3-nano-30b-a3b":  {"input": 0,     "output": 0},  # FREE
    "stepfun/step-3.5-flash":          {"input": 0.02,  "output": 0.16},
    "openai/gpt-5.2-chat":             {"input": 2.50,  "output": 10.00},

    # Direct providers
    "claude-sonnet-4-20250514":        {"input": 3.00,  "output": 15.00},
    "gemini-2.5-flash":                {"input": 0.15,  "output": 0.60},
    "gpt-4o":                          {"input": 2.50,  "output": 10.00},
    "grok-3":                          {"input": 3.00,  "output": 15.00},
    "mistral-large-latest":            {"input": 2.00,  "output": 6.00},
    "deepseek-chat":                   {"input": 0.27,  "output": 1.10},
}

FREE_PROVIDERS = {"nvidia", "cerebras", "groq", "huggingface", "ollama"}
```

Prices in USD per 1M tokens. Unknown models use a conservative fallback of `{"input": 1.00, "output": 3.00}`.

### Token Extraction Per Provider

| Provider | Input field | Output field |
|----------|------------|--------------|
| OpenAI / OpenRouter / Groq / DeepSeek / Mistral | `usage.prompt_tokens` | `usage.completion_tokens` |
| Anthropic | `usage.input_tokens` | `usage.output_tokens` |
| Google (Gemini) | `usage_metadata.prompt_token_count` | `usage_metadata.candidates_token_count` |
| Ollama | `prompt_eval_count` | `eval_count` |
| NVIDIA | `usage.prompt_tokens` | `usage.completion_tokens` |
| Fallback | `len(text) // 4` | `len(text) // 4` |

### Persistent Storage

File: `logs/cost_log.jsonl`

```json
{"ts":"2026-02-22T15:30:00","model":"google/gemini-3.1-pro-preview","provider":"openrouter","tin":1523,"tout":892,"cost_in":0.0019,"cost_out":0.0089}
```

- One line per API call
- Auto-trimmed: entries older than 90 days pruned on startup
- All costs stored in USD; currency conversion is client-side only

### CostTracker Class (`gateway_v2.py`)

```
CostTracker:
  - __init__(logs_dir): loads existing JSONL, computes running totals
  - log_usage(model, provider, tokens_in, tokens_out): calculates cost, appends to file, updates totals
  - get_stats(): returns {session, today, week, month, last_request, avg_per_message, daily_series, by_model}
  - _prune_old(): removes entries > 90 days on startup
```

---

## UI — Status Tab Cost Dashboard

### Currency Selector

Small dropdown pinned to section header:
```
💰 COST DASHBOARD  [💲 USD ▾]
```
Options: USD, EUR, GBP, CAD, AUD, JPY, INR, BRL, KRW. Saved to localStorage.

### Summary Cards (6 cards, same `.stat-grid` style)

| Card | Example | Description |
|------|---------|-------------|
| Session Cost | $0.42 | Since last gateway restart |
| Today | $1.87 | Rolling 24 hours |
| This Week | $8.23 | Last 7 days |
| This Month | $31.50 | Last 30 days |
| Last Request | $0.003 | Most recent API call |
| Avg per Message | $0.02 | Month cost / message count |

Color thresholds: green (<$0.01), yellow ($0.01-$0.10), red (>$0.10) for per-message; scaled up for aggregate cards.

### Chart 1 — Daily Spend (Bar Chart)

- Last 14 days, one bar per day
- Color-coded by dominant model
- Hover tooltip: model breakdown for that day
- Y-axis: cost in selected currency

### Chart 2 — Model Cost Comparison (Horizontal Bar)

- Top 5-8 paid models by total spend
- Each bar labeled: model name, total cost, message count
- Free models noted separately: "Also used: NVIDIA Nemotron, Groq Llama (free)"

### Chart 3 — Cost per Message Trend (Line Chart)

- Rolling 7-day average cost per message
- Last 14 days
- Shows cost trend direction

### Free Model Handling

- Free providers (NVIDIA, Cerebras, Groq, HuggingFace, Ollama) show `FREE` badge on cards
- Token counts still logged for usage visibility
- Excluded from spend charts (only paid models appear)
- Noted in a small line below the Model Cost Comparison chart

---

## API Endpoint

### `GET /api/cost-stats`

Returns:
```json
{
  "session_cost": 0.42,
  "today_cost": 1.87,
  "week_cost": 8.23,
  "month_cost": 31.50,
  "last_request_cost": 0.003,
  "avg_per_message": 0.02,
  "message_count_month": 1575,
  "daily": [
    {"date": "2026-02-22", "cost": 2.15, "models": {"gpt-5.2": 1.50, "claude-sonnet-4.6": 0.65}},
    ...
  ],
  "by_model": [
    {"model": "openai/gpt-5.2", "cost": 12.50, "messages": 450, "tokens_in": 500000, "tokens_out": 200000},
    ...
  ],
  "free_models_used": ["nvidia/nemotron-3-nano-30b-a3b", "ollama/qwen3:8b"]
}
```

All costs in USD. Currency conversion applied client-side.

---

## Exchange Rates (Static)

```javascript
const EXCHANGE_RATES = {
  USD: 1, EUR: 0.92, GBP: 0.79, CAD: 1.44,
  AUD: 1.57, JPY: 149.5, INR: 83.1, BRL: 5.05, KRW: 1345
};
```

Updated manually each release.

---

## Files Modified

| File | Change |
|------|--------|
| `gateway_v2.py` | `MODEL_PRICING` dict, `CostTracker` class, real token extraction from API responses, cost logging after each call |
| `web_deck.py` | Chart.js CDN, Cost Dashboard HTML section, `/api/cost-stats` endpoint, `refreshCostDashboard()` JS, currency selector |
| `galactic_core_v2.py` | Wire `CostTracker` into core for gateway + web_deck access |

---

## Out of Scope

- Live exchange rate API (static rates are sufficient)
- Per-conversation cost breakdown (future enhancement)
- Budget alerts / spending limits (future enhancement)
- Export to CSV (future enhancement)
