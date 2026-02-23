# Token Cost Dashboard — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a polished cost dashboard to the Status tab showing real token costs with multi-currency support and interactive Chart.js graphs.

**Architecture:** CostTracker class in gateway_v2.py handles pricing, JSONL persistence, and stats aggregation. Provider methods set `self._last_usage` with real API token counts. web_deck.py adds Chart.js CDN, dashboard HTML, `/api/cost-stats` endpoint, and chart-rendering JS.

**Tech Stack:** Python 3 (aiohttp, httpx), Chart.js 4.x (CDN), vanilla JS, JSONL file storage.

---

### Task 1: Add MODEL_PRICING and CostTracker class to gateway_v2.py

**Files:**
- Modify: `gateway_v2.py:14-15` (add import)
- Modify: `gateway_v2.py:26-45` (add MODEL_PRICING after existing constants)

**Step 1: Add `from collections import defaultdict` to imports**

At `gateway_v2.py` line 10, after `from datetime import datetime`, add:

```python
from collections import defaultdict
```

**Step 2: Add MODEL_PRICING dict and FREE_PROVIDERS set after existing module-level constants**

After the existing `_NVIDIA_NO_STREAM` set (around line 28), add:

```python
# ── Token pricing (USD per 1M tokens) ────────────────────────────────
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
    "nvidia/nemotron-3-nano-30b-a3b":  {"input": 0,     "output": 0},
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
_PRICING_FALLBACK = {"input": 1.00, "output": 3.00}
FREE_PROVIDERS = {"nvidia", "cerebras", "groq", "huggingface", "ollama"}
```

**Step 3: Add CostTracker class after the constants, before GalacticGateway class**

Insert this class before `class GalacticGateway:` (before line 47):

```python
class CostTracker:
    """Tracks per-request token costs, persists to JSONL, computes dashboard stats."""

    def __init__(self, logs_dir='./logs'):
        self.logs_dir = logs_dir
        self.log_file = os.path.join(logs_dir, 'cost_log.jsonl')
        os.makedirs(logs_dir, exist_ok=True)
        self.session_start = datetime.now().isoformat()
        self.session_cost = 0.0
        self.last_request_cost = 0.0
        self.entries = []  # in-memory cache of recent entries
        self._load_existing()
        self._prune_old()

    def _load_existing(self):
        """Load existing JSONL entries into memory."""
        if not os.path.exists(self.log_file):
            return
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass

    def _prune_old(self):
        """Remove entries older than 90 days and rewrite the file."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.get('ts', '') >= cutoff]
        if len(self.entries) < before:
            self._rewrite_file()

    def _rewrite_file(self):
        """Rewrite the JSONL file from memory (after prune)."""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                for entry in self.entries:
                    f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    def log_usage(self, model, provider, tokens_in, tokens_out):
        """Calculate cost, append to JSONL, update running totals."""
        is_free = provider in FREE_PROVIDERS
        pricing = MODEL_PRICING.get(model, _PRICING_FALLBACK)
        if is_free:
            pricing = {"input": 0, "output": 0}

        cost_in = (tokens_in / 1_000_000) * pricing["input"]
        cost_out = (tokens_out / 1_000_000) * pricing["output"]
        total_cost = cost_in + cost_out

        entry = {
            "ts": datetime.now().isoformat(),
            "model": model,
            "provider": provider,
            "tin": tokens_in,
            "tout": tokens_out,
            "cost_in": round(cost_in, 6),
            "cost_out": round(cost_out, 6),
            "cost": round(total_cost, 6),
            "free": is_free,
        }

        self.entries.append(entry)
        self.session_cost += total_cost
        self.last_request_cost = total_cost

        # Append to file
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    def get_stats(self):
        """Compute dashboard statistics from in-memory entries."""
        from datetime import timedelta
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week_start = (now - timedelta(days=7)).isoformat()
        month_start = (now - timedelta(days=30)).isoformat()
        fourteen_days_ago = (now - timedelta(days=14)).isoformat()

        today_cost = 0.0
        week_cost = 0.0
        month_cost = 0.0
        month_messages = 0
        daily_map = defaultdict(lambda: {"cost": 0.0, "models": defaultdict(float)})
        model_map = defaultdict(lambda: {"cost": 0.0, "messages": 0, "tokens_in": 0, "tokens_out": 0})
        free_models = set()

        for e in self.entries:
            ts = e.get('ts', '')
            cost = e.get('cost', 0.0)
            model = e.get('model', 'unknown')
            is_free = e.get('free', False)

            if is_free:
                free_models.add(model)

            if ts >= today_start:
                today_cost += cost
            if ts >= week_start:
                week_cost += cost
            if ts >= month_start:
                month_cost += cost
                month_messages += 1

            # Daily series (last 14 days)
            if ts >= fourteen_days_ago:
                day = ts[:10]  # YYYY-MM-DD
                daily_map[day]["cost"] += cost
                short_model = model.split('/')[-1] if '/' in model else model
                daily_map[day]["models"][short_model] += cost

            # By-model aggregation (last 30 days)
            if ts >= month_start and not is_free:
                model_map[model]["cost"] += cost
                model_map[model]["messages"] += 1
                model_map[model]["tokens_in"] += e.get('tin', 0)
                model_map[model]["tokens_out"] += e.get('tout', 0)

        # Build daily series (sorted, last 14 days)
        daily_series = []
        for day in sorted(daily_map.keys()):
            d = daily_map[day]
            daily_series.append({
                "date": day,
                "cost": round(d["cost"], 4),
                "models": {k: round(v, 4) for k, v in d["models"].items()},
            })

        # Build by-model list (sorted by cost descending, top 8)
        by_model = []
        for model, stats in sorted(model_map.items(), key=lambda x: x[1]["cost"], reverse=True)[:8]:
            by_model.append({
                "model": model,
                "cost": round(stats["cost"], 4),
                "messages": stats["messages"],
                "tokens_in": stats["tokens_in"],
                "tokens_out": stats["tokens_out"],
            })

        avg_per_message = (month_cost / month_messages) if month_messages > 0 else 0.0

        return {
            "session_cost": round(self.session_cost, 4),
            "today_cost": round(today_cost, 4),
            "week_cost": round(week_cost, 4),
            "month_cost": round(month_cost, 4),
            "last_request_cost": round(self.last_request_cost, 6),
            "avg_per_message": round(avg_per_message, 4),
            "message_count_month": month_messages,
            "daily": daily_series,
            "by_model": by_model,
            "free_models_used": sorted(list(free_models)),
        }
```

**Step 4: Initialize `_last_usage` in GalacticGateway.__init__**

At `gateway_v2.py` line 73, after `self.total_tokens_out = 0`, add:

```python
        self._last_usage = None  # Populated by provider methods with real API token counts
```

**Step 5: Commit**

```bash
git add gateway_v2.py
git commit -m "feat(cost): add MODEL_PRICING dict and CostTracker class"
```

---

### Task 2: Wire CostTracker into galactic_core_v2.py

**Files:**
- Modify: `galactic_core_v2.py:129` (after gateway init, inside `setup_systems()`)

**Step 1: Add CostTracker initialization after gateway creation**

At `galactic_core_v2.py`, in the `setup_systems()` method (line ~129), after `self.gateway = GalacticGateway(self)`, add:

```python
        # Cost tracking (persistent JSONL)
        from gateway_v2 import CostTracker
        logs_dir = self.config.get('paths', {}).get('logs', './logs')
        self.cost_tracker = CostTracker(logs_dir)
```

**Step 2: Commit**

```bash
git add galactic_core_v2.py
git commit -m "feat(cost): wire CostTracker into core setup"
```

---

### Task 3: Extract real token counts from provider API responses

**Files:**
- Modify: `gateway_v2.py:3990-4006` (`_call_gemini`)
- Modify: `gateway_v2.py:4118-4131` (`_call_anthropic_messages`)
- Modify: `gateway_v2.py:4496-4540` (`_call_openai_compatible_messages` non-streaming)
- Modify: `gateway_v2.py:4376-4461` (`_call_openai_compatible_messages` streaming)

The strategy: Each provider method sets `self._last_usage = {"prompt_tokens": X, "completion_tokens": Y}` just before returning. This avoids changing return types.

**Step 1: Update `_call_gemini` to extract `usageMetadata`**

At `gateway_v2.py`, in `_call_gemini()`, after `data = response.json()` (line 3997) and before the return on line 4006, add usage extraction. Replace:

```python
                return candidate['content']['parts'][0]['text']
```

with:

```python
                # Extract real token counts from Google response
                um = data.get('usageMetadata', {})
                self._last_usage = {
                    "prompt_tokens": um.get('promptTokenCount', 0),
                    "completion_tokens": um.get('candidatesTokenCount', 0),
                }
                return candidate['content']['parts'][0]['text']
```

Also add `self._last_usage = None` at the top of the method (first line inside `try:`).

**Step 2: Update `_call_anthropic_messages` to extract `usage`**

At `gateway_v2.py`, in `_call_anthropic_messages()`, after `data = response.json()` (line 4121), add usage extraction before the content check. Add after line 4121:

```python
                # Extract real token counts from Anthropic response
                usage = data.get('usage', {})
                self._last_usage = {
                    "prompt_tokens": usage.get('input_tokens', 0),
                    "completion_tokens": usage.get('output_tokens', 0),
                }
```

Also add `self._last_usage = None` at the top of the method (first line inside `try:`).

**Step 3: Update `_call_openai_compatible_messages` non-streaming path**

At `gateway_v2.py`, in the non-streaming path, after `data = json.loads(body_text)` (line 4527) and before extracting the message (line 4532), add:

```python
                    # Extract real token counts from OpenAI-compatible response
                    usage = data.get('usage', {})
                    if usage:
                        self._last_usage = {
                            "prompt_tokens": usage.get('prompt_tokens', 0),
                            "completion_tokens": usage.get('completion_tokens', 0),
                        }
```

**Step 4: Update `_call_openai_compatible_messages` streaming path**

For streaming, request usage in the final chunk. At the payload construction (around line 4385), add `"stream_options": {"include_usage": True}` to the streaming payload.

Then at the end of the streaming loop, after `result = "".join(full_response)` (line 4451), the final SSE chunk before `[DONE]` may contain usage. Update the streaming chunk processing to capture it. Inside the `async for line in response.aiter_lines():` loop, add after the delta processing:

```python
                                # Capture usage from final streaming chunk (OpenAI/OpenRouter)
                                if 'usage' in chunk:
                                    usage = chunk['usage']
                                    self._last_usage = {
                                        "prompt_tokens": usage.get('prompt_tokens', 0),
                                        "completion_tokens": usage.get('completion_tokens', 0),
                                    }
```

Also add `self._last_usage = None` at the top of `_call_openai_compatible_messages()`.

**Step 5: Commit**

```bash
git add gateway_v2.py
git commit -m "feat(cost): extract real token counts from all provider APIs"
```

---

### Task 4: Hook cost logging into the speak() method

**Files:**
- Modify: `gateway_v2.py:3337` (input token tracking)
- Modify: `gateway_v2.py:3605-3612` (output token tracking, final answer return)

**Step 1: Update input token tracking at line 3337**

Replace:

```python
        self.total_tokens_in += len(user_input) // 4
```

with:

```python
        self._estimated_input_tokens = len(user_input) // 4
        self.total_tokens_in += self._estimated_input_tokens
```

This preserves the existing token counter while also saving the estimate for later comparison with real counts.

**Step 2: Update output token tracking and add cost logging at line 3605-3612**

After the line `self.total_tokens_out += len(display_text) // 4` (line 3606), add cost logging:

```python
                # Log cost with real token counts if available, otherwise estimates
                if hasattr(self.core, 'cost_tracker'):
                    real = self._last_usage
                    if real and (real.get('prompt_tokens') or real.get('completion_tokens')):
                        tin = real['prompt_tokens']
                        tout = real['completion_tokens']
                        # Update running totals with real counts (overwrite estimates)
                        self.total_tokens_in += tin - self._estimated_input_tokens
                        self.total_tokens_out += tout - (len(display_text) // 4)
                    else:
                        tin = self._estimated_input_tokens
                        tout = len(display_text) // 4
                    self.core.cost_tracker.log_usage(
                        model=self.llm.model,
                        provider=self.llm.provider,
                        tokens_in=tin,
                        tokens_out=tout,
                    )
```

**Step 3: Commit**

```bash
git add gateway_v2.py
git commit -m "feat(cost): hook cost logging into speak() with real/estimated fallback"
```

---

### Task 5: Add `/api/cost-stats` endpoint to web_deck.py

**Files:**
- Modify: `web_deck.py:57` (route registration area)
- Modify: `web_deck.py:3555` (add handler before handle_status)

**Step 1: Register the route**

At `web_deck.py`, near line 57 where `/api/status` is registered, add:

```python
        self.app.router.add_get('/api/cost-stats', self.handle_cost_stats)
```

**Step 2: Add the handler method**

Before the `handle_status` method (line 3555), add:

```python
    async def handle_cost_stats(self, request):
        """GET /api/cost-stats — cost dashboard data."""
        ct = getattr(self.core, 'cost_tracker', None)
        if not ct:
            return web.json_response({"error": "Cost tracking not initialized"}, status=503)
        return web.json_response(ct.get_stats())
```

**Step 3: Commit**

```bash
git add web_deck.py
git commit -m "feat(cost): add /api/cost-stats endpoint"
```

---

### Task 6: Add Chart.js CDN and Cost Dashboard HTML to web_deck.py

**Files:**
- Modify: `web_deck.py:1265` (before opening `<script>` tag — add Chart.js CDN)
- Modify: `web_deck.py:1014` (after System Overview stat-grid closing `</div>`)

**Step 1: Add Chart.js CDN import**

At `web_deck.py`, just before the inline `<script>` tag (line ~1265), add:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
```

**Step 2: Add Cost Dashboard HTML section after System Overview**

At `web_deck.py`, after the System Overview stat-grid closing `</div>` (line 1014), insert the Cost Dashboard section:

```html
        <!-- Cost Dashboard -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin:18px 0 8px">
          <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);text-transform:uppercase">💰 Cost Dashboard</div>
          <select id="cost-currency" onchange="saveCurrency();refreshCostDashboard()" style="background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:0.78rem;font-family:var(--mono);cursor:pointer">
            <option value="USD">💲 USD</option>
            <option value="EUR">€ EUR</option>
            <option value="GBP">£ GBP</option>
            <option value="CAD">🇨🇦 CAD</option>
            <option value="AUD">🇦🇺 AUD</option>
            <option value="JPY">¥ JPY</option>
            <option value="INR">₹ INR</option>
            <option value="BRL">🇧🇷 BRL</option>
            <option value="KRW">₩ KRW</option>
          </select>
        </div>
        <div class="stat-grid" id="cost-cards">
          <div class="stat-card"><div class="val" id="cost-session">--</div><div class="lbl">Session Cost</div></div>
          <div class="stat-card"><div class="val" id="cost-today">--</div><div class="lbl">Today</div></div>
          <div class="stat-card"><div class="val" id="cost-week">--</div><div class="lbl">This Week</div></div>
          <div class="stat-card"><div class="val" id="cost-month">--</div><div class="lbl">This Month</div></div>
          <div class="stat-card"><div class="val" id="cost-last">--</div><div class="lbl">Last Request</div></div>
          <div class="stat-card"><div class="val" id="cost-avg">--</div><div class="lbl">Avg / Message</div></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
          <div class="stat-card" style="padding:16px">
            <div class="lbl" style="margin-bottom:10px;text-align:left">Daily Spend (14 days)</div>
            <canvas id="chart-daily" height="180"></canvas>
          </div>
          <div class="stat-card" style="padding:16px">
            <div class="lbl" style="margin-bottom:10px;text-align:left">Cost by Model (30 days)</div>
            <canvas id="chart-models" height="180"></canvas>
          </div>
        </div>
        <div class="stat-card" style="padding:16px;margin-bottom:12px">
          <div class="lbl" style="margin-bottom:10px;text-align:left">Cost per Message Trend (14 days)</div>
          <canvas id="chart-trend" height="120"></canvas>
        </div>
        <div id="cost-free-note" style="font-size:0.72rem;color:var(--dim);margin-bottom:18px"></div>
```

**Step 3: Commit**

```bash
git add web_deck.py
git commit -m "feat(cost): add Chart.js CDN and cost dashboard HTML to Status tab"
```

---

### Task 7: Add Cost Dashboard JavaScript to web_deck.py

**Files:**
- Modify: `web_deck.py` — add JS functions after `refreshStatus()` (after line 2594)

**Step 1: Add exchange rates, currency helpers, and chart state**

After the `refreshStatus()` function (line 2594), add:

```javascript
// ── Cost Dashboard ───────────────────────────────────────────────────
const EXCHANGE_RATES = {
  USD:1, EUR:0.92, GBP:0.79, CAD:1.44,
  AUD:1.57, JPY:149.5, INR:83.1, BRL:5.05, KRW:1345
};
const CURRENCY_SYMBOLS = {
  USD:'$', EUR:'€', GBP:'£', CAD:'CA$', AUD:'AU$', JPY:'¥', INR:'₹', BRL:'R$', KRW:'₩'
};
let costChartDaily = null, costChartModels = null, costChartTrend = null;

function getCurrency() {
  try { return localStorage.getItem('gal_currency') || 'USD'; } catch(e) { return 'USD'; }
}
function saveCurrency() {
  const c = document.getElementById('cost-currency').value;
  try { localStorage.setItem('gal_currency', c); } catch(e) {}
}
function fmtCost(usd, decimals) {
  const cur = getCurrency();
  const rate = EXCHANGE_RATES[cur] || 1;
  const val = usd * rate;
  const sym = CURRENCY_SYMBOLS[cur] || cur;
  if (decimals === undefined) {
    // Auto-format: small values get more decimals
    if (val === 0) return 'FREE';
    if (val < 0.01) return sym + val.toFixed(4);
    if (val < 1) return sym + val.toFixed(3);
    if (val < 100) return sym + val.toFixed(2);
    return sym + val.toLocaleString(undefined, {maximumFractionDigits:0});
  }
  return sym + val.toFixed(decimals);
}
function costColor(usd) {
  if (usd === 0) return 'var(--green)';
  if (usd < 0.01) return 'var(--green)';
  if (usd < 0.10) return 'var(--yellow)';
  return 'var(--red)';
}

// Chart.js dark theme defaults
function applyChartDefaults() {
  if (typeof Chart === 'undefined') return;
  Chart.defaults.color = 'rgba(180,190,200,0.7)';
  Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';
  Chart.defaults.font.family = "'JetBrains Mono', monospace";
  Chart.defaults.font.size = 10;
}
```

**Step 2: Add the main refreshCostDashboard() function**

Immediately after the helpers above, add:

```javascript
async function refreshCostDashboard() {
  try {
    const r = await authFetch('/api/cost-stats');
    if (!r.ok) return;
    const d = await r.json();
    if (d.error) return;

    // Restore saved currency
    const sel = document.getElementById('cost-currency');
    if (sel) sel.value = getCurrency();

    // Summary cards
    const el = id => document.getElementById(id);
    const setCard = (id, usd) => {
      const e = el(id);
      if (!e) return;
      e.textContent = fmtCost(usd);
      e.style.color = costColor(usd);
    };
    setCard('cost-session', d.session_cost);
    setCard('cost-today', d.today_cost);
    setCard('cost-week', d.week_cost);
    setCard('cost-month', d.month_cost);
    setCard('cost-last', d.last_request_cost);
    setCard('cost-avg', d.avg_per_message);

    applyChartDefaults();
    if (typeof Chart === 'undefined') return; // Chart.js not loaded yet

    const cur = getCurrency();
    const rate = EXCHANGE_RATES[cur] || 1;
    const sym = CURRENCY_SYMBOLS[cur] || cur;

    // ── Chart 1: Daily Spend ──
    const dailyCanvas = el('chart-daily');
    if (dailyCanvas && d.daily) {
      const labels = d.daily.map(x => x.date.slice(5)); // MM-DD
      const values = d.daily.map(x => x.cost * rate);
      // Color by dominant model
      const PALETTE = ['#00f3ff','#a78bfa','#34d399','#f59e0b','#ef4444','#f472b6','#60a5fa','#10b981'];
      const colors = d.daily.map((x, i) => PALETTE[i % PALETTE.length]);

      if (costChartDaily) costChartDaily.destroy();
      costChartDaily = new Chart(dailyCanvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            data: values,
            backgroundColor: colors.map(c => c + '99'),
            borderColor: colors,
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: ctx => {
                  const day = d.daily[ctx.dataIndex];
                  const lines = [sym + (day.cost * rate).toFixed(2)];
                  for (const [m, c] of Object.entries(day.models || {})) {
                    lines.push('  ' + m + ': ' + sym + (c * rate).toFixed(3));
                  }
                  return lines;
                }
              }
            }
          },
          scales: {
            y: { beginAtZero: true, ticks: { callback: v => sym + v.toFixed(2) } },
            x: { grid: { display: false } },
          },
        },
      });
    }

    // ── Chart 2: Model Cost Comparison ──
    const modelsCanvas = el('chart-models');
    if (modelsCanvas && d.by_model) {
      const labels = d.by_model.map(x => {
        const short = x.model.includes('/') ? x.model.split('/')[1] : x.model;
        return short.length > 20 ? short.slice(0, 18) + '…' : short;
      });
      const values = d.by_model.map(x => x.cost * rate);
      const PALETTE = ['#00f3ff','#a78bfa','#34d399','#f59e0b','#ef4444','#f472b6','#60a5fa','#10b981'];

      if (costChartModels) costChartModels.destroy();
      costChartModels = new Chart(modelsCanvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            data: values,
            backgroundColor: PALETTE.slice(0, values.length).map(c => c + '99'),
            borderColor: PALETTE.slice(0, values.length),
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: ctx => {
                  const m = d.by_model[ctx.dataIndex];
                  return [
                    sym + (m.cost * rate).toFixed(2),
                    m.messages + ' messages',
                    (m.tokens_in / 1000).toFixed(1) + 'k in / ' + (m.tokens_out / 1000).toFixed(1) + 'k out',
                  ];
                }
              }
            }
          },
          scales: {
            x: { beginAtZero: true, ticks: { callback: v => sym + v.toFixed(2) } },
            y: { grid: { display: false } },
          },
        },
      });
    }

    // ── Chart 3: Cost per Message Trend ──
    const trendCanvas = el('chart-trend');
    if (trendCanvas && d.daily) {
      const labels = d.daily.map(x => x.date.slice(5));
      // Simple per-day average (cost / messages that day, approximated from models)
      const values = d.daily.map(x => {
        const msgs = Object.keys(x.models || {}).length || 1;
        return (x.cost / Math.max(msgs, 1)) * rate;
      });

      if (costChartTrend) costChartTrend.destroy();
      costChartTrend = new Chart(trendCanvas, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data: values,
            borderColor: '#00f3ff',
            backgroundColor: 'rgba(0,243,255,0.1)',
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: '#00f3ff',
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { callback: v => sym + v.toFixed(3) } },
            x: { grid: { display: false } },
          },
        },
      });
    }

    // Free models note
    const freeNote = el('cost-free-note');
    if (freeNote && d.free_models_used && d.free_models_used.length > 0) {
      const names = d.free_models_used.map(m => m.split('/').pop()).join(', ');
      freeNote.textContent = '🆓 Also used (free): ' + names;
    } else if (freeNote) {
      freeNote.textContent = '';
    }
  } catch(e) { console.error('Cost dashboard error:', e); }
}
```

**Step 3: Hook refreshCostDashboard into the Status tab refresh**

In `refreshStatus()` (line 2494), add a call to `refreshCostDashboard()` at the very end, just before the closing `catch`:

At the end of the `try` block in `refreshStatus()`, before the `} catch(e)` on line 2593, add:

```javascript
    // Refresh cost dashboard
    refreshCostDashboard();
```

Also add to `refreshCurrentTab()` (line 3327): the status case already calls `refreshStatus()` which now chains to `refreshCostDashboard()`, so no change needed there.

**Step 4: Initialize saved currency on page load**

In the DOMContentLoaded or page init section, add:

```javascript
// Restore saved currency on load
try {
  const saved = localStorage.getItem('gal_currency');
  if (saved) { const sel = document.getElementById('cost-currency'); if (sel) sel.value = saved; }
} catch(e) {}
```

**Step 5: Commit**

```bash
git add web_deck.py
git commit -m "feat(cost): add cost dashboard JavaScript with Chart.js rendering"
```

---

### Task 8: Deploy to running installation and verify

**Files:**
- Copy: `gateway_v2.py` → `F:\Galactic AI\gateway_v2.py`
- Copy: `web_deck.py` → `F:\Galactic AI\web_deck.py`
- Copy: `galactic_core_v2.py` → `F:\Galactic AI\galactic_core_v2.py`

**Step 1: Copy all modified files to the running installation**

```bash
cp "F:/Galactic AI Public Release/gateway_v2.py" "F:/Galactic AI/gateway_v2.py"
cp "F:/Galactic AI Public Release/web_deck.py" "F:/Galactic AI/web_deck.py"
cp "F:/Galactic AI Public Release/galactic_core_v2.py" "F:/Galactic AI/galactic_core_v2.py"
```

**Step 2: Verify the cost_log.jsonl directory exists**

```bash
ls "F:/Galactic AI/logs/" || mkdir -p "F:/Galactic AI/logs/"
```

**Step 3: Prompt user to restart Galactic AI and test**

Tell the user to restart Galactic AI, navigate to the Status tab, and verify:
- Cost Dashboard section appears below System Overview
- Currency selector works and persists
- Sending a message populates the cost cards
- Charts render after a few messages
- Free models show "FREE" instead of $0.00

**Step 4: Final commit with all changes**

```bash
git add gateway_v2.py web_deck.py galactic_core_v2.py
git commit -m "feat: token cost dashboard — real API costs, Chart.js graphs, multi-currency"
```

---

## Task Summary

| # | Task | Files | Estimated Time |
|---|------|-------|---------------|
| 1 | MODEL_PRICING + CostTracker class | gateway_v2.py | 5 min |
| 2 | Wire CostTracker into core | galactic_core_v2.py | 2 min |
| 3 | Real token extraction from providers | gateway_v2.py | 5 min |
| 4 | Hook cost logging into speak() | gateway_v2.py | 3 min |
| 5 | /api/cost-stats endpoint | web_deck.py | 2 min |
| 6 | Chart.js CDN + dashboard HTML | web_deck.py | 3 min |
| 7 | Dashboard JavaScript + charts | web_deck.py | 5 min |
| 8 | Deploy and verify | all files | 3 min |

**Total:** ~28 minutes
