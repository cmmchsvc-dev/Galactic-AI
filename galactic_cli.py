import asyncio
import aiohttp
import json
import sys
import os
import argparse
import subprocess
import re
import time
import difflib
import ast as ast_module
from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED
from rich.table import Table
from rich.progress import BarColumn
from rich.syntax import Syntax
from rich.highlighter import ReprHighlighter
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog
from prompt_toolkit.completion import Completer, Completion
import glob
import colorama
colorama.init()

# Rich highlighter for diff output
_highlighter = ReprHighlighter()

console = Console()
custom_style = Style.from_dict({
    'prompt': 'ansicyan bold',
})

class MentionCompleter(Completer):
    def get_completions(self, document, complete_event):
        text_before_cursor = document.text_before_cursor
        if not text_before_cursor:
            return
            
        # 1. Slash Command Completion: If the line starts with '/' and does not contain spaces
        if text_before_cursor.startswith('/') and ' ' not in text_before_cursor:
            search_term = text_before_cursor[1:]
            for cmd in COMMAND_GRAPH.keys():
                if cmd.startswith(search_term):
                    yield Completion("/" + cmd, start_position=-len(text_before_cursor), display_meta=COMMAND_GRAPH[cmd].get('desc', ''))
            return

        # 2. File Completion: If the user typed @ and is entering a filename/path
        word = document.get_word_before_cursor(WORD=True)
        if '@' in text_before_cursor:
            last_at_idx = text_before_cursor.rfind('@')
            tail = text_before_cursor[last_at_idx+1:]
            if ' ' not in tail:
                search_term = tail
                # Replace backslashes for glob
                glob_term = search_term.replace('\\', '/')
                files = glob.glob(f"{glob_term}*" if glob_term else "*")
                for f in files:
                    f_formatted = f.replace('\\', '/')
                    if os.path.isdir(f):
                        f_formatted += '/'
                    yield Completion(f_formatted, start_position=-len(search_term))


API_URL = "http://127.0.0.1:17789"
WS_URL = "ws://127.0.0.1:17789/stream"

# State trackers
current_response = ""
current_thinking = ""
current_trace = ""
in_progress_tool = None

# Global toggles
VERBOSE_MODE = True
THINKING_MODE = False

# Thinking effort level: low, medium, high, max (maps to backend reasoning intensity)
EFFORT_LEVEL = "medium"
EFFORT_COLORS = {
    "low": "green",
    "medium": "yellow",
    "high": "orange3",
    "max": "red",
}
EFFORT_ICONS = {
    "low": "💤 Low",
    "medium": "🧠 Medium",
    "high": "🔥 High",
    "max": "⚡ Maximum",
}

# Session hints — temporary instructions appended to system context
session_hints: list[str] = []

# Local session tracking (fallback if backend endpoints don't exist)
session_token_counts = {"input": 0, "output": 0}
sessions_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli_sessions")

# Export directory for conversations
exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli_exports")

import random

# ── Rate-limit cooldown + liveness state ─────────────────────────────
RATE_LIMIT_MAX_RETRIES = 4
STALL_WARN_SECS = 90      # silence before the watchdog starts probing
STALL_POLL_SECS = 15      # how often the watchdog checks
_rate_limit_until = 0.0   # monotonic deadline for the current cooldown
last_event_ts = 0.0       # updated on every WS/stream event
_stall_killed = False     # set by the watchdog when it aborts a dead request

def _parse_retry_after(resp) -> float:
    try:
        ra = resp.headers.get('Retry-After')
        if ra:
            return max(1.0, float(ra))
    except Exception:
        pass
    return 0.0

async def _cooldown_wait(seconds, reason="rate limit"):
    """Visible countdown so the CLI never looks frozen during a cooldown."""
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        safe_print(f"[yellow]⏳ Cooling down ({reason}) — {int(left)+1}s...   [/yellow]", end="\r")
        await asyncio.sleep(min(1.0, left))
    safe_print(" " * 60, end="\r")

async def _stall_watchdog(session, victim):
    """
    Fixes the 'silent death' failure mode. If no event arrives for
    STALL_WARN_SECS, ask the backend whether it is still working. Busy →
    reassure the user and keep waiting. Idle → the job ended without a
    completion event: cancel the hung request and print recovery steps.
    """
    global last_event_ts, _stall_killed
    last_event_ts = time.monotonic()
    warned = False
    while True:
        await asyncio.sleep(STALL_POLL_SECS)
        quiet = time.monotonic() - last_event_ts
        if quiet < STALL_WARN_SECS:
            warned = False
            continue
        try:
            async with session.get(f"{API_URL}/api/status",
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
            speaking = bool(d.get('speaking', d.get('busy', False)))
        except Exception:
            speaking = None  # status unreachable — don't kill on a guess
        if speaking is False:
            _stall_killed = True
            victim.cancel()
            return
        if not warned:
            safe_print(f"\n[dim yellow]⏱️ Still working — {int(quiet)}s without output (long tool call or slow model). Watchdog active.[/dim yellow]")
            warned = True

# ==========================================
# PHASE 2-6: Advanced Systems
# ==========================================

# --- Session Tags & Management ---
session_tags: list[str] = []
session_history_store: dict = {}  # name -> session data for /resume

# --- Skill System ---
skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
loaded_skills: list[dict] = []

# --- Plan Mode ---
plan_mode_active = False
current_plan: list[str] = []
plan_step_index = -1

# --- Context Window Tracking ---
class ContextTracker:
    def __init__(self, max_tokens=128000):
        self.max_tokens = max_tokens
        self.current_tokens = 0
        self.system_prompt_tokens = 0
        self.messages_tokens = 0
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (~4 chars per token)."""
        return len(text) // 4 + 1
    
    def add_message(self, role: str, content: str):
        tokens = self.estimate_tokens(content)
        self.messages_tokens += tokens
        self.current_tokens = self.system_prompt_tokens + self.messages_tokens
    
    def usage_percent(self) -> float:
        return (self.current_tokens / self.max_tokens) * 100 if self.max_tokens > 0 else 0
    
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.current_tokens)

context_tracker = ContextTracker()

# --- Cost Analytics ---
class CostAnalytics:
    PRICES_PER_MILION_INPUT = {
        "claude": {"haiku": 2.50, "sonnet": 3.75, "opus": 18.75},
        "gpt": {"4o-mini": 0.15, "4o": 2.50, "4-turbo": 10.00},
        "gemini": {"flash": 0.075, "pro": 0.35, "ultra": 2.50},
    }
    
    def __init__(self):
        self.session_cost = 0.0
        self.daily_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
    
    def update(self, input_tokens: int = 0, output_tokens: int = 0, model: str = "unknown"):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        # Rough cost estimate at ~$3M per million tokens (Sonnet-ish)
        cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
        self.session_cost += cost
    
    def reset_session(self):
        self.daily_cost += self.session_cost
        self.session_cost = 0.0

cost_analytics = CostAnalytics()

# --- Provider System ---
class ProviderManager:
    KNOWN_PROVIDERS = {
        "anthropic": {"prefixes": ["claude"], "base_url_hint": "api.anthropic.com"},
        "openai": {"prefixes": ["gpt"], "base_url_hint": "api.openai.com"},
        "google": {"prefixes": ["gemini"], "base_url_hint": "generativelanguage.googleapis.com"},
        "ollama": {"prefixes": ["llama", "mistral", "qwen"], "base_url_hint": "localhost"},
        "custom": {"prefixes": [], "base_url_hint": ""},
    }
    
    @classmethod
    def detect_provider(cls, model_id: str) -> str:
        for provider, info in cls.KNOWN_PROVIDERS.items():
            for prefix in info["prefixes"]:
                if prefix.lower() in model_id.lower():
                    return provider
        return "custom"

# --- Advanced Compaction Strategies ---
def compact_keep_recent(messages: list[dict], keep_last: int = 8, max_tokens: int = 32000):
    """Simple compaction: keep last N messages, summarize the rest."""
    if len(messages) <= keep_last + 2:
        return messages
    old = messages[:-keep_last]
    kept = messages[-keep_last:]
    summary_text = f"[Previously summarized {len(old)} messages covering earlier conversation context]"
    summary_msg = {"role": "assistant", "content": summary_text}
    return [summary_msg] + kept

def compact_by_token_budget(messages: list[dict], max_tokens: int = 32000):
    """Aggressive compaction: reduce to fit token budget."""
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total < max_tokens * 4:
        return messages
    # Keep first (system) + last 6, summarize middle
    if len(messages) > 8:
        old = messages[1:-6]
        kept = [messages[0]] + messages[-6:]
        summary = f"[Summarized {len(old)} conversation turns to fit context window]"
        return kept + [{"role": "assistant", "content": summary}]
    return messages

def compact_microcompact(messages: list[dict]):
    """Microcompaction: trim whitespace and repeated patterns in tool results."""
    result = []
    for m in messages:
        content = str(m.get("content", ""))
        # Trim long tool outputs
        if len(content) > 2000:
            content = content[:1500] + "\n...[truncated]"
        result.append({**m, "content": content})
    return result


async def _load_skills_from_disk():
    """Scan the skills directory for YAML/JSON skill definitions."""
    global loaded_skills
    loaded_skills = []
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
        return
    import glob
    for fpath in glob.glob(os.path.join(skills_dir, "*.yaml")) + glob.glob(os.path.join(skills_dir, "*.yml")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            # Minimal YAML-ish parser (key: value pairs)
            skill = {"file": os.path.basename(fpath), "name": "", "trigger": "", "prompt_template": ""}
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("name:") and not line.startswith("name_"):
                    skill["name"] = line.split(":", 1)[1].strip().strip("'\"")
                elif line.startswith("trigger:"):
                    skill["trigger"] = line.split(":", 1)[1].strip().strip("'\"")
                elif line.startswith("prompt_template:"):
                    skill["prompt_template"] = line.split(":", 1)[1].strip().strip("'\"")
            if skill.get("name"):
                loaded_skills.append(skill)
        except Exception:
            pass


async def _execute_skill_trigger(text: str, session, extra_payload=None):
    """Check if input matches a skill trigger and execute it."""
    for skill in loaded_skills:
        trigger = skill.get("trigger", "")
        if trigger and trigger.lower() in text.lower():
            template = skill.get("prompt_template", "")
            # Replace {input} with the user's actual message
            expanded = template.replace("{input}", text) if template else text
            safe_print(f"\n[dim yellow]⚡ Skill triggered: [bold]{skill['name']}[/bold][/dim yellow]\n")
            await send_chat(session, expanded, extra_payload)
            return True
    return False


async def _execute_plan_step(session, extra_payload=None):
    """Execute the next step in the current plan."""
    global plan_step_index
    if plan_step_index >= len(current_plan) - 1:
        safe_print("\n[green]✅ All plan steps complete![/green]\n")
        await send_chat(session, "/plan done", extra_payload)
        return
    plan_step_index += 1
    step = current_plan[plan_step_index]
    remaining = len(current_plan) - plan_step_index
    safe_print(f"\n[dim blue]📋 Executing Step {plan_step_index + 1}/{len(current_plan)} ({remaining} remaining)[/dim blue]\n")
    await send_chat(session, step, extra_payload)


# Plan mode helper for parsing structured plans
def parse_plan(text: str) -> list[str]:
    """Parse numbered plan steps from text."""
    steps = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Match patterns like "1. Do something" or "- Do something" or "Step 1: Do something"
        cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
        cleaned = re.sub(r'^[-*•]\s*', '', cleaned)
        cleaned = re.sub(r'^[Ss]tep\s+\d+\s*[:\-]\s*', '', cleaned)
        if cleaned:
            steps.append(cleaned)
    return steps if steps else [text.strip()]


# ==========================================
# WEBSOCKET EVENT HANDLER (verbose-aware)

def reset_stream_state():
    global current_response, current_thinking, current_trace, in_progress_tool, in_think_block
    current_response = ""
    current_thinking = ""
    current_trace = ""
    in_progress_tool = None
    in_think_block = False

# ==========================================
# WEBSOCKET EVENT HANDLER (verbose-aware)
# ==========================================


def safe_print(*args, **kwargs):
    from prompt_toolkit.application.current import get_app
    app = get_app()
    if app and app.is_running:
        app.run_in_terminal(lambda: console.print(*args, **kwargs))
    else:
        console.print(*args, **kwargs)

from rich.markdown import Markdown

class StreamRenderer:
    """
    Buffered streaming renderer. Chunks accumulate and a single background
    task flushes them every 100ms, so the terminal repaints ~10x/second
    instead of once per token (safe_print's run_in_terminal tears down and
    redraws the whole prompt_toolkit application on every call).
    On finalize, the full response is re-rendered once as rich Markdown.
    """
    FLUSH_INTERVAL = 0.1

    def __init__(self):
        self._buf = []
        self._task = None
        self._streamed_any = False

    def feed(self, text, style="white"):
        if not text:
            return
        self._buf.append((text, style))
        self._streamed_any = True
        if self._task is None or self._task.done():
            try:
                self._task = asyncio.get_running_loop().create_task(self._flusher())
            except RuntimeError:
                self.flush_now()

    def flush_now(self):
        if not self._buf:
            return
        pending, self._buf = self._buf, []
        out = Text()
        for txt, style in pending:
            out.append(txt, style=style)
        safe_print(out, end="")

    async def _flusher(self):
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            if not self._buf:
                break
            self.flush_now()

    def finalize(self):
        self.flush_now()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        # One-shot polished re-render of the complete response when it
        # contains markdown structure (code fences, tables, headings).
        if self._streamed_any and current_response.strip() and any(
                tok in current_response for tok in ('```', '# ', '**', '- ', '|')):
            try:
                clean = re.sub(r'<think>.*?</think>', '', current_response, flags=re.DOTALL).strip()
                if clean:
                    safe_print()
                    safe_print(Panel(Markdown(clean), border_style="dim cyan",
                                     box=ROUNDED, title="[dim]formatted[/dim]", title_align="right"))
            except Exception:
                pass
        self._streamed_any = False

stream_renderer = StreamRenderer()

def handle_ws_event(payload):

    global current_response, current_thinking, current_trace, in_progress_tool, in_think_block, VERBOSE_MODE, auto_mode_active, plan_mode_active, last_event_ts
    last_event_ts = time.monotonic()
    if 'in_think_block' not in globals():
        in_think_block = False
    
    msg_type = payload.get('type')
    data = payload.get('data')
    
    if not msg_type:
        return

    # Any non-chunk event (tool panels, traces, progress) flushes pending
    # stream text first so output ordering is preserved.
    if msg_type not in ('stream_chunk', 'thinking_chunk'):
        stream_renderer.flush_now()

    if msg_type == 'stream_chunk':
        chunk = str(data)
        current_response += chunk

        # Parse <think> tags for CLI styling
        parts = re.split(r'(<think>|</think>)', chunk)
        for part in parts:
            if part == '<think>':
                in_think_block = True
                if VERBOSE_MODE:
                    stream_renderer.feed(part, style="dim magenta")
            elif part == '</think>':
                if VERBOSE_MODE:
                    stream_renderer.feed(part, style="dim magenta")
                in_think_block = False
            elif part:
                if in_think_block:
                    if VERBOSE_MODE:
                        stream_renderer.feed(part, style="dim magenta")
                else:
                    stream_renderer.feed(part, style="white")

    elif msg_type == 'thinking_chunk':
        chunk = str(data)
        current_thinking += chunk
        if VERBOSE_MODE:
            stream_renderer.feed(chunk, style="dim magenta")
            
    elif msg_type == 'rewrite_thought':
        # Models using native JSON arguments for their "thought" emit it here instead of stream_chunk
        thought_text = str(data).strip()
        if thought_text and thought_text not in current_thinking and thought_text not in current_response:
            if VERBOSE_MODE:
                safe_print(Text(f"\n💡 Analysis: {thought_text}\n", style="dim magenta"))
                
    elif msg_type == 'token_counts':
        # Capture token counts from backend if available
        if isinstance(data, dict):
            session_token_counts['input'] = data.get('input_tokens', session_token_counts['input'])
            session_token_counts['output'] = data.get('output_tokens', session_token_counts['output'])
            
    elif msg_type == 'agent_trace':
        if isinstance(data, dict):
            phase = data.get('phase')
            sid = data.get('session_id', '')
            prefix = f"[Subagent {sid}] " if sid and sid.startswith('s-') else ""
            if phase == 'turn_start':
                safe_print(f"\n[dim bright_black]{prefix}⚙️ Commencing turn {data.get('turn', 1)}...[/dim bright_black]\n")
            elif phase == 'final_answer':
                safe_print(f"\n[dim bright_black]{prefix}✅ Final Answer Reached[/dim bright_black]\n")
            elif phase == 'tool':
                try:
                    tool_name = data.get('tool', 'unknown')
                    args = data.get('args', {})
                    in_progress_tool = tool_name
                    args_str = json.dumps(args, indent=2)
                    if len(args_str) > 200:
                        args_str = args_str[:197] + "..."
                    
                    panel = Panel(Text(f"{prefix}Running Tool: {tool_name}\n\n{args_str}", style="cyan"), box=ROUNDED, border_style="blue")
                    safe_print("\n")
                    safe_print(panel)
                except Exception as e:
                    import traceback
                    safe_print(f"[red]Error in tool panel: {traceback.format_exc()}[/red]")
            elif phase == 'tool_result':
                try:
                    result_text = str(data.get('result', ''))
                    if len(result_text) > 300:
                        result_text = result_text[:297] + "\n...[SNIPPED FOR COMPACTION]..."
                    panel = Panel(Text(f"{prefix}Result:\n{result_text}", style="green"), box=ROUNDED, border_style="green")
                    safe_print(panel)
                    safe_print("\n")
                    in_progress_tool = None
                except Exception as e:
                    import traceback
                    safe_print(f"[red]Error in tool result panel: {traceback.format_exc()}[/red]")
            
    elif msg_type == 'progress':
        if isinstance(data, dict):
            status = data.get('status', '')
            sid = data.get('session_id', '')
            prefix = f"[Subagent {sid}] " if sid and sid.startswith('s-') else ""
            safe_print(f"\n[dim cyan]🔄 {prefix}{status}[/dim cyan]\n")
        
    elif msg_type == 'tool_invoke':
        try:
            if isinstance(data, str):
                data = json.loads(data)
            tool_name = data.get('tool', 'unknown')
            args = data.get('args', {})
            in_progress_tool = tool_name
            args_str = json.dumps(args, indent=2)
            if len(args_str) > 200:
                args_str = args_str[:197] + "..."
            
            if VERBOSE_MODE:
                panel = Panel(Text(f"Running Tool: {tool_name}\n\n{args_str}", style="cyan"), box=ROUNDED, border_style="blue")
                safe_print("\n")
                safe_print(panel)
            else:
                # Spinners for compact mode
                safe_print(f"[cyan]⚙️ Executing {tool_name}...[/cyan]", end="\r")
                import sys; sys.stdout.flush()
        except Exception:
            pass
            
    elif msg_type == 'tool_result':
        try:
            if isinstance(data, str):
                data = json.loads(data)
            result_text = str(data.get('result', data) if isinstance(data, dict) else data)
        except Exception:
            result_text = str(data)
            
        if len(result_text) > 300:
            result_text = result_text[:297] + "\n...[SNIPPED FOR COMPACTION]..."
            
        if VERBOSE_MODE:
            panel = Panel(Text(f"Result:\n{result_text}", style="green"), box=ROUNDED, border_style="green")
            safe_print(panel)
            safe_print("\n")
        else:
            # Collapsed UI result for compact mode
            safe_print(f"\r[green]✅ Finished {in_progress_tool or 'Tool'}             [/green]\n")
        in_progress_tool = None

    elif msg_type == 'cli_settings_sync':
        if isinstance(data, dict):
            key = data.get('key')
            val = data.get('value')
            if key == 'auto_mode':
                auto_mode_active = bool(val)
                safe_print(f"\n[yellow]⚙️ Auto Mode {'enabled' if val else 'disabled'} via Web Deck.[/yellow]")
            elif key == 'plan_mode':
                plan_mode_active = bool(val)
                safe_print(f"\n[yellow]⚙️ Plan Mode {'enabled' if val else 'disabled'} via Web Deck.[/yellow]")
            elif key == 'verbose_mode':
                VERBOSE_MODE = bool(val)
                safe_print(f"\n[yellow]⚙️ Verbose Mode {'enabled' if val else 'disabled'} via Web Deck.[/yellow]")

    elif msg_type == 'status':
        if data == 'done':
            stream_renderer.finalize()
            safe_print("\n")
            # Print token summary if verbose mode is on
            if VERBOSE_MODE:
                total = session_token_counts['input'] + session_token_counts['output']
                safe_print(f"\n[dim]Token Usage — Input: {session_token_counts['input']} | Output: {session_token_counts['output']} | Total: {total}[/dim]\n")

async def send_chat(session, text, extra_payload=None):
    global current_response, in_progress_tool, current_plan
    global _rate_limit_until, _stall_killed, last_event_ts

    if not text.strip():
        return

    payload = {
        'message': text,
        'stream': True,
        'verbose': VERBOSE_MODE,
        'thinking': THINKING_MODE,
        'effort_level': EFFORT_LEVEL,
        'hints': session_hints
    }
    if extra_payload:
        payload.update(extra_payload)

    est_tokens = context_tracker.estimate_tokens(text)
    cost_analytics.update(input_tokens=est_tokens)

    reset_stream_state()
    safe_print("\n", end="")

    _stall_killed = False
    watchdog = asyncio.create_task(_stall_watchdog(session, asyncio.current_task()))
    attempt = 0
    try:
        while True:
            hold = _rate_limit_until - time.monotonic()
            if hold > 0:
                await _cooldown_wait(hold)
            try:
                async with session.post(f"{API_URL}/api/chat", json=payload) as resp:
                    if resp.status == 429 or resp.status in (502, 503, 504):
                        attempt += 1
                        if attempt > RATE_LIMIT_MAX_RETRIES:
                            safe_print(f"[red]Giving up after {RATE_LIMIT_MAX_RETRIES} retries (HTTP {resp.status}).[/red]")
                            break
                        backoff = _parse_retry_after(resp) or min(2 ** attempt + random.uniform(0, 1), 60)
                        _rate_limit_until = time.monotonic() + backoff
                        label = "Rate limit" if resp.status == 429 else f"Server error {resp.status}"
                        safe_print(f"\n[yellow]🚦 {label} — attempt {attempt}/{RATE_LIMIT_MAX_RETRIES}.[/yellow]")
                        continue
                    if resp.status != 200:
                        err = await resp.text()
                        safe_print(f"[red]Error: {resp.status} - {err}[/red]")
                        break

                    async for line in resp.content:
                        if not line:
                            continue
                        last_event_ts = time.monotonic()
                        line_str = line.decode('utf-8').strip()
                        if not line_str:
                            continue
                        data_str = line_str
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data_json = json.loads(data_str)
                            if 'type' in data_json:
                                handle_ws_event(data_json)
                            else:
                                chunk = data_json.get('response', '')
                                if chunk and not current_response.strip():
                                    current_response += chunk
                                    safe_print(chunk, end="", style="white")
                        except json.JSONDecodeError:
                            pass

                    # Backend surfaced a rate limit inside a 200 body. Only
                    # auto-retry when the turn produced NOTHING but the error —
                    # re-sending after partial output would duplicate work.
                    body = current_response.strip()
                    if body.startswith("[ERROR]") and any(
                            k in body.lower() for k in ("rate limit", "429", "quota", "overloaded")):
                        attempt += 1
                        if attempt <= RATE_LIMIT_MAX_RETRIES:
                            backoff = min(5 * attempt + random.uniform(0, 2), 90)
                            safe_print(f"\n[yellow]🚦 Provider rate-limited — retrying in {int(backoff)}s (attempt {attempt}/{RATE_LIMIT_MAX_RETRIES}).[/yellow]")
                            await _cooldown_wait(backoff)
                            reset_stream_state()
                            continue
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt > RATE_LIMIT_MAX_RETRIES:
                    safe_print(f"\n[red]Connection error (final): {e}[/red]")
                    break
                backoff = min(2 ** attempt, 30)
                safe_print(f"\n[yellow]⚠️ Connection error: {e} — retry {attempt}/{RATE_LIMIT_MAX_RETRIES} in {backoff}s.[/yellow]")
                await _cooldown_wait(backoff, reason="connection")
    except asyncio.CancelledError:
        if _stall_killed:
            safe_print("\n[red]🛑 Watchdog: backend went idle without a completion event — the job likely ended early. Partial output is above; check /logs or continue with /resume.[/red]")
        else:
            raise
    finally:
        watchdog.cancel()

    safe_print()

    if auto_mode_active:
        await check_auto_mode(session)

# ==========================================
# AUTO MODE (Autonomous Agent Loop)
# ==========================================
auto_mode_active = False
auto_mode_max_turns = 15
auto_mode_current_turn = 0

async def cmd_auto(session, arg):
    """Toggle Auto Mode (autonomous loop)."""
    global auto_mode_active, auto_mode_current_turn
    if auto_mode_active:
        auto_mode_active = False
        safe_print("\n[yellow]🛑 Auto Mode disabled.[/yellow]")
    else:
        auto_mode_active = True
        auto_mode_current_turn = 0
        safe_print("\n[green]🤖 Auto Mode enabled! The agent will execute tools continuously until the task is complete.[/green]")
        if arg:
            # If they provided a prompt right away
            await send_chat(session, arg)

async def check_auto_mode(session):
    """Called after a chat response. If Auto Mode is active, check if we should continue."""
    global auto_mode_active, auto_mode_current_turn
    if not auto_mode_active:
        return
        
    # Check if we hit the turn limit
    auto_mode_current_turn += 1
    if auto_mode_current_turn >= auto_mode_max_turns:
        safe_print(f"\n[red]🛑 Auto Mode reached max turns ({auto_mode_max_turns}). Stopping loop.[/red]")
        auto_mode_active = False
        return
        
    # How to detect if the agent is done? 
    # Usually, if the response does NOT contain tool calls, it's done. 
    # Or if it explicitly says "I am finished".
    # For now, we will look for a special string or just let the backend decide.
    # Actually, the backend stream handler executes tools and then recursively generates.
    # But if the user wants continuous looping across MULTIPLE turns (like Claude Code),
    # we can append a prompt like "Continue execution. If you are finished, output <FINISHED>."
    if "<FINISHED>" in current_response or "Task complete" in current_response:
        safe_print("\n[green]✅ Auto Mode detected task completion. Stopping loop.[/green]")
        auto_mode_active = False
        return
        
    safe_print(f"\n[dim cyan]🤖 Auto Mode (Turn {auto_mode_current_turn}/{auto_mode_max_turns}) — Continuing...[/dim cyan]")
    # Give a short pause so user can CTRL+C if it goes rogue
    await asyncio.sleep(1.5)
    await send_chat(session, "Continue executing the plan. If you are done, explicitly say <FINISHED>.")

# ==========================================
# CONTEXT VISUALIZATION SYSTEM
# ==========================================
async def _show_context_visualization(session):
    """
    Simulates the Context Visualization (Ctx Viz) from Claude Code.
    Shows a tree map of the current context window token usage.
    """
    safe_print("\n[cyan]📊 Context Visualization[/cyan]")
    
    # We will simulate the data structure that the backend would provide
    # In a full implementation, this data would come from the /api/status endpoint
    
    # Mock data for demonstration, but using real session tokens for the total
    total_estimated = session_token_counts['input'] + session_token_counts['output']
    if total_estimated == 0:
         total_estimated = 450 # fake a baseline if fresh
         
    system_prompt = int(total_estimated * 0.4)
    chat_history = int(total_estimated * 0.45)
    tool_results = int(total_estimated * 0.15)
    
    table = Table(box=ROUNDED, show_header=False)
    table.add_column("Component", style="cyan")
    table.add_column("Tokens", style="white", justify="right")
    table.add_column("Visual", style="magenta")
    
    def make_bar(val, total, max_width=30):
        if total == 0: return ""
        pct = val / total
        filled = int(max_width * pct)
        return "█" * filled + "░" * (max_width - filled)
        
    table.add_row("System Prompt & Instructions", f"{system_prompt:,}", f"[dim]{make_bar(system_prompt, total_estimated)}[/dim]")
    table.add_row("Recent Chat History", f"{chat_history:,}", f"[dim]{make_bar(chat_history, total_estimated)}[/dim]")
    table.add_row("Tool Results (Memory/Files)", f"{tool_results:,}", f"[dim]{make_bar(tool_results, total_estimated)}[/dim]")
    
    safe_print(table)
    safe_print(f"[dim]Total Context Window Payload: {total_estimated:,} tokens[/dim]\n")
    return

# ==========================================
# SLASH COMMAND HANDLERS
# ==========================================

async def cmd_rewind(session, arg):
    """Remove the last N messages/turns to undo conversation."""
    num = arg.strip() if arg else "1"
    safe_print(f"[dim cyan]⏪ Rewinding conversation by {num} turn(s)...[/dim cyan]")
    await send_chat(session, f"/rewind {num}")

async def cmd_boost(session, arg):
    """Re-run the last exchange on the boost (cloud) model."""
    target = f" {arg.strip()}" if arg and arg.strip() else ""
    safe_print("[cyan]🚀 Boosting the last answer on the big brain...[/cyan]")
    await send_chat(session, f"/boost{target}")

async def cmd_retry(session, arg):
    """Re-run the last exchange on the current model."""
    safe_print("[cyan]⟳ Retrying the last answer...[/cyan]")
    await send_chat(session, "/retry")

async def cmd_hybrid(session, arg):
    """Toggle Hybrid Coding Mode (cloud Architect writes, local Builder applies)."""
    state = f" {arg.strip().lower()}" if arg and arg.strip().lower() in ("on", "off") else ""
    await send_chat(session, f"/hybrid{state}")

async def cmd_clear(session, arg):
    """Clear the screen and reset conversation history."""
    os.system('cls' if os.name == 'nt' else 'clear')
    await send_chat(session, "/clear")
    safe_print("[green]Session history cleared and screen reset.[/green]")

async def cmd_help(session, arg):
    """Show available commands."""
    table = Table(title="Galactic AI Slash Commands", box=ROUNDED)
    table.add_column("Command", style="cyan bold")
    table.add_column("Description", style="white")
    for cmd, data in COMMAND_GRAPH.items():
        table.add_row(f"[bold cyan]/[bold]{cmd}", data["desc"])
    safe_print("\n")
    safe_print(table)
    safe_print("\n[dim]Type any command or just start chatting[/dim]\n")

async def cmd_agents(session, arg):
    """List all active background agents."""
    try:
        async with session.get(f"{API_URL}/api/subagents") as resp:
            if resp.status == 200:
                data = await resp.json()
                if not data:
                    safe_print("\n[yellow]No active subagents running.[/yellow]\n")
                    return
                table = Table(title="Galactic AI Subagents", box=ROUNDED)
                table.add_column("Session ID", style="cyan")
                table.add_column("Agent", style="magenta")
                table.add_column("Status", style="green")
                table.add_column("Task")
                table.add_column("Elapsed", justify="right")
                
                for agent in data:
                    status = agent.get('status', 'unknown')
                    status_color = "green" if status == "running" else "yellow" if status == "pending" else "dim white"
                    table.add_row(
                        agent.get('session_id', ''),
                        agent.get('agent', ''),
                        f"[{status_color}]{status}[/{status_color}]",
                        agent.get('task', '')[:50] + "...",
                        agent.get('elapsed', '')
                    )
                safe_print("\n")
                safe_print(table)
                safe_print("\n")
            else:
                safe_print(f"\n[red]Failed to fetch agents: HTTP {resp.status}[/red]\n")
    except Exception as e:
        safe_print(f"\n[red]Connection error: {e}[/red]\n")

async def cmd_desktop(session, arg):
    """Launch the Galactic Control Deck UI."""
    safe_print("\n[cyan]🚀 Launching Galactic Control Deck...[/cyan]\n")
    if sys.platform == 'win32':
        subprocess.Popen(['python', 'launcher_desktop.py'], creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(['python', 'launcher_desktop.py'])

async def cmd_btw(session, arg):
    """Ask a side question without polluting the conversation history."""
    if not arg.strip():
        safe_print("[yellow]Usage: /btw <your question>[/yellow]")
        return
    safe_print(f"\n[dim cyan]🤔 Thinking (by the way)...[/dim cyan]")
    try:
        payload = {
            'message': arg,
            'isolated': True,
            'stream': False
        }
        async with session.post(f"{API_URL}/api/chat", json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                response_text = data.get('response', '')
                
                panel = Panel(
                    Syntax(response_text, "markdown", theme="monokai", word_wrap=True) if not response_text.startswith("Error") else response_text,
                    title="[bold yellow]🤔 By-The-Way Response[/bold yellow]",
                    border_style="yellow",
                    box=ROUNDED,
                    padding=(1, 2)
                )
                safe_print(panel)
                safe_print("\n")
            else:
                safe_print(f"[red]Error: HTTP {resp.status}[/red]")
    except Exception as e:
        safe_print(f"[red]Connection Error: {e}[/red]")

async def cmd_compact(session, arg):
    """Manually trigger Layer 2 History Compaction."""
    safe_print("\n[dim cyan]🧼 Triggering Manual History Compaction...[/dim cyan]")
    try:
        # Fast API endpoint hit for compaction
        async with session.post(f"{API_URL}/api/memory/compact", timeout=10) as resp:
            if resp.status == 200:
                safe_print("[green]✨ Memory successfully compacted! Token context freed.✨[/green]\n")
            else:
                # Fallback to chat command handler if endpoint doesn't exist
                await send_chat(session, "/compact")
    except:
        await send_chat(session, "/compact")

async def cmd_commit(session, arg):
    """Auto-generate a git commit message and commit changes."""
    safe_print("\n[cyan]⌨️ Analyzing Git diff for commit...[/cyan]")
    try:
        diff = subprocess.check_output(['git', 'diff'], text=True)
        if not diff:
            safe_print("[yellow]No unstaged changes to commit.[/yellow]")
            return
            
        safe_print("[dim]Generating commit message via AI...[/dim]")
        # Let's hand it to the AI to draft it.
        await send_chat(session, "Write a professional git commit message for the following diff. Only return the commit message text:\n" + diff)
        # Since it's a TUI loop, an active interactive popup confirmation would go here next!
    except Exception as e:
        safe_print(f"[red]Git Error: {e}[/red]")



async def cmd_context(session, arg):
    """Show current context window usage and model info. Can also show Context Visualization (/ctx)."""
    if arg and arg.strip() == "viz":
        return await _show_context_visualization(session)

    try:
        async with session.get(f"{API_URL}/api/status") as resp:
            if resp.status == 200:
                data = await resp.json()
                
                model_name = data.get('model', 'unknown')
                current_turn = data.get('current_turn', 0)
                max_turns = data.get('max_turns', '∞')
                context_window = data.get('context_window', 131072)
                estimated_tokens = data.get('estimated_tokens_used', session_token_counts['input'] + session_token_counts['output'])
                
                usage_pct = min(100, (estimated_tokens / context_window) * 100) if context_window > 0 else 0
                
                # Color-code the usage percentage
                if usage_pct < 50:
                    pct_color = "green"
                elif usage_pct < 80:
                    pct_color = "yellow"
                else:
                    pct_color = "red"
                
                bar_len = 30
                filled = int(bar_len * usage_pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                
                p = Panel(
                    f"[bold cyan]Model:[/bold cyan] {model_name}\n"
                    f"[bold cyan]Current Turn:[/bold cyan] {current_turn} / {max_turns}\n"
                    f"[bold cyan]Context Window:[/bold cyan] {context_window:,} tokens\n"
                    f"[bold cyan]Estimated Used:[/bold cyan] {estimated_tokens:,} tokens\n"
                    f"\n[bold cyan]Usage:[/bold cyan] [{pct_color}]{usage_pct:.1f}%[/{pct_color}] "
                    f"[dim]{bar}[/dim]\n"
                    f"\n[dim]Input Tokens: {session_token_counts['input']:,} | Output Tokens: {session_token_counts['output']:,}[/dim]\n\n"
                    f"[dim italic]Tip: Type '/context viz' for a visual breakdown of context items.[/dim italic]",
                    title="Context Window",
                    border_style="cyan",
                    box=ROUNDED
                )
                safe_print("\n")
                safe_print(p)
                safe_print("\n")
            else:
                safe_print(f"\n[red]Failed to fetch status: HTTP {resp.status}[/red]\n")
    except Exception as e:
        safe_print(f"\n[red]Connection error: {e}[/red]\n")

async def cmd_cost(session, arg):
    """Show session/today/week cost and token stats."""
    try:
        async with session.get(f"{API_URL}/api/cost-stats", timeout=3) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                dialog_text = (
                    f"Current Session Cost: ${data.get('session_cost', 0.00):.4f}\n"
                    f"Today's Total Cost:   ${data.get('today_cost', 0.00):.4f}\n"
                    f"This Week's Cost:     ${data.get('week_cost', 0.00):.4f}\n"
                    f"This Month's Cost:    ${data.get('month_cost', 0.00):.4f}\n\n"
                    f"Input Tokens:         {session_token_counts['input']:,}\n"
                    f"Output Tokens:        {session_token_counts['output']:,}"
                )
                
                # Pop up the prompt_toolkit dialog natively
                await button_dialog(
                    title="💰 Galactic Usage & Cost Stats",
                    text=dialog_text,
                    buttons=[("Close", None)],
                ).run_async()

            else:
                await _show_local_cost()
    except Exception:
        # Fallback to local tracking if endpoint doesn't exist
        await _show_local_cost()

async def _show_local_cost():
    """Fallback cost display using local token tracking."""
    total = session_token_counts['input'] + session_token_counts['output']
    # Rough estimate: ~$0.0001 per 1K tokens (local run assumption)
    estimated_cost = total * 0.0000001
    
    dialog_text = (
        f"Input Tokens:  {session_token_counts['input']:,}\n"
        f"Output Tokens: {session_token_counts['output']:,}\n"
        f"Total Tokens:  {total:,}\n\n"
        f"Estimated Cost: ~${estimated_cost:.6f}"
    )

    await button_dialog(
        title="💰 Local Token Stats (Approximate)",
        text=dialog_text,
        buttons=[("Close", None)],
    ).run_async()

async def cmd_verbose(session, arg):
    """Toggle verbose mode for expanded thinking display."""
    global VERBOSE_MODE
    VERBOSE_MODE = not VERBOSE_MODE
    if VERBOSE_MODE:
        safe_print("[green]Verbose mode ON[/green] — thinking blocks and token counts will be shown expanded.")
    else:
        safe_print("[yellow]Verbose mode OFF[/yellow] — thinking collapsed, token counts hidden.")

async def cmd_thinking(session, arg):
    """Toggle extended thinking mode."""
    global THINKING_MODE
    THINKING_MODE = not THINKING_MODE
    level = 'high' if THINKING_MODE else 'off'
    try:
        async with session.post(f"{API_URL}/api/settings/thinking", json={"level": level}, timeout=2) as resp:
            pass
    except Exception:
        pass

    if THINKING_MODE:
        safe_print("[green]Extended Thinking ON[/green] - model will think more deeply before responding.")
    else:
        safe_print("[yellow]Extended Thinking OFF[/yellow] - back to standard response mode.")



async def cmd_cwd(session, arg):
    """Show or change current working directory."""
    if arg:
        # Change directory
        target = os.path.expanduser(arg.strip())
        if os.path.isdir(target):
            os.chdir(target)
            safe_print(f"[green]Changed to [bold]{os.getcwd()}[/bold][/green]")
        else:
            safe_print(f"[red]Directory not found: {target}[/red]")
    else:
        # Show current directory
        cwd = os.getcwd()
        project_name = os.path.basename(cwd)
        
        p = Panel(
            f"[bold cyan]Current Working Directory:[/bold cyan]\n{cwd}\n\n"
            f"[dim]Project: {project_name}[/dim]",
            title="Working Directory",
            border_style="cyan",
            box=ROUNDED
        )
        safe_print("\n")
        safe_print(p)
        safe_print("\n")

async def cmd_memory(session, arg):
    """Search memory for context."""
    if not arg:
        safe_print("[yellow]Usage: /memory <search query>[/yellow]")
        # Show recent memory entries
        memory_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MEMORY.md")
        if os.path.exists(memory_file):
            with open(memory_file, 'r', encoding='utf-8') as f:
                content = f.read()[:500]
            p = Panel(content + "...", title="MEMORY.md Preview", border_style="magenta", box=ROUNDED)
            safe_print("\n")
            safe_print(p)
        else:
            safe_print("[dim yellow]No MEMORY.md found in project root[/dim yellow]")
        return
    
    # Send search request to backend memory endpoint
    try:
        async with session.post(f"{API_URL}/api/memory/search", json={"query": arg, "top_k": 5}, timeout=5) as resp:
            if resp.status == 200:
                results = await resp.json()
                table = Table(title=f"Memory Search: \"{arg}\"", box=ROUNDED)
                table.add_column("Relevance", style="green")
                table.add_column("Content", style="white")
                for r in results:
                    score = r.get('score', 'N/A')
                    content = r.get('content', '')[:200]
                    table.add_row(f"{score:.3f}" if isinstance(score, float) else str(score), content)
                safe_print("\n")
                safe_print(table)
                safe_print("\n")
            else:
                _local_memory_search(arg)
    except Exception:
        _local_memory_search(arg)

def _local_memory_search(query):
    """Fallback local memory search."""
    memory_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MEMORY.md")
    if os.path.exists(memory_file):
        with open(memory_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        matches = [l.strip() for l in lines if query.lower() in l.lower()][:10]
        if matches:
            table = Table(title=f"Local Memory Search (approximate)", box=ROUNDED)
            table.add_column("Match", style="white")
            for m in matches:
                table.add_row(m[:200])
            safe_print("\n")
            safe_print(table)
            safe_print("\n[dim yellow]Backend memory API unavailable — local file search only[/dim yellow]\n")
        else:
            safe_print(f"[yellow]No matches for \"{query}\" in MEMORY.md[/yellow]")

async def _show_context_visualization(session):
    """Fetch and display a detailed visualization of context token usage."""
    try:
        async with session.get(f"{API_URL}/api/status") as resp:
            if resp.status == 200:
                data = await resp.json()
                context_window = data.get('context_window', 131072)
                
                # We'll simulate breakdown if backend doesn't provide exact itemized list yet
                # Eventually, the backend should return `context_breakdown: [{type: 'file', name: 'main.py', tokens: 1500}, ...]`
                breakdown = data.get('context_breakdown', [
                    {"type": "system", "name": "System Prompt", "tokens": 4500},
                    {"type": "history", "name": "Chat History", "tokens": session_token_counts['input']},
                    {"type": "tools", "name": "Tool Schema", "tokens": 1200}
                ])
                
                total_used = sum(item['tokens'] for item in breakdown)
                
                table = Table(title="Context Token Visualization", box=ROUNDED, show_lines=True)
                table.add_column("Type", justify="center", style="cyan")
                table.add_column("Item", style="white")
                table.add_column("Tokens", justify="right", style="magenta")
                table.add_column("% of Used", justify="right", style="green")
                table.add_column("Visual Map", style="dim")
                
                for item in sorted(breakdown, key=lambda x: x['tokens'], reverse=True):
                    pct = (item['tokens'] / total_used) * 100 if total_used > 0 else 0
                    
                    # Generate a mini bar chart for the visual map
                    bar_len = 20
                    filled = int(bar_len * pct / 100)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    
                    icon = "🔧" if item['type'] == 'tools' else "📜" if item['type'] == 'history' else "⚙️" if item['type'] == 'system' else "📄"
                    
                    table.add_row(
                        icon,
                        item['name'],
                        f"{item['tokens']:,}",
                        f"{pct:.1f}%",
                        f"[{'red' if pct > 50 else 'yellow' if pct > 20 else 'green'}]{bar}[/]"
                    )
                
                safe_print("\n")
                safe_print(table)
                safe_print(f"\n[dim italic]Total Estimated: {total_used:,} / {context_window:,} tokens ({((total_used/context_window)*100) if context_window else 0:.1f}%)[/dim italic]\n")
            else:
                safe_print(f"\n[red]Failed to fetch status for visualization. HTTP {resp.status}[/red]\n")
    except Exception as e:
        safe_print(f"\n[red]Connection error: {e}[/red]\n")


async def cmd_skills(session, arg):
    """List available tools and skills."""
    try:
        async with session.get(f"{API_URL}/api/status") as resp:
            if resp.status == 200:
                data = await resp.json()
                tools = data.get('available_tools', [])
                
                if not tools:
                    # Fallback to known tool list
                    tools = [
                        "read_file", "write_file", "edit_file", "list_dir", "find_files",
                        "execute_python", "exec_shell", "web_search", "web_fetch",
                        "generate_image", "chrome_navigate", "chrome_screenshot",
                        "chrome_read_page", "chrome_click", "chrome_type", "chrome_scroll",
                        "desktop_screenshot", "desktop_click", "desktop_type",
                        "spawn_subagent", "spawn_chain", "memory_search", "memory_imprint"
                    ]
                
                table = Table(title="Available Tools & Skills", box=ROUNDED)
                table.add_column("Tool", style="cyan bold")
                table.add_column("Category", style="dim white")
                
                categories = {
                    "read_file": "FS", "write_file": "FS", "edit_file": "FS", 
                    "list_dir": "FS", "find_files": "FS",
                    "execute_python": "Code", "exec_shell": "Shell",
                    "web_search": "Web", "web_fetch": "Web",
                    "generate_image": "Creative",
                    "chrome_navigate": "Browser", "chrome_screenshot": "Browser",
                    "chrome_read_page": "Browser", "chrome_click": "Browser",
                    "chrome_type": "Browser", "chrome_scroll": "Browser",
                    "desktop_screenshot": "Desktop", "desktop_click": "Desktop",
                    "spawn_subagent": "Agents", "spawn_chain": "Agents",
                    "memory_search": "Memory", "memory_imprint": "Memory"
                }
                
                for tool in tools[:20]:
                    cat = categories.get(tool, "Core")
                    table.add_row(tool, f"[dim]{cat}[/dim]")
                
                if len(tools) > 20:
                    safe_print(f"\n[dim]... and {len(tools) - 20} more tools[/dim]\n")
                
                safe_print("\n")
                safe_print(table)
                safe_print("\n")
            else:
                _show_default_skills()
    except Exception:
        _show_default_skills()

def _show_default_skills():
    """Default skills list when backend unavailable."""
    tools = [
        ("read_file", "Read file contents"),
        ("write_file", "Write content to file"),
        ("edit_file", "Safe partial file edit"),
        ("execute_python", "Run Python code"),
        ("exec_shell", "Run shell commands"),
        ("web_search", "Search the web"),
        ("chrome_navigate", "Browser navigation"),
        ("spawn_subagent", "Spawn background agent"),
        ("memory_search", "Search long-term memory"),
    ]
    table = Table(title="Available Tools (default list)", box=ROUNDED)
    table.add_column("Tool", style="cyan bold")
    table.add_column("Description", style="white")
    for t, d in tools:
        table.add_row(t, d)
    safe_print("\n")
    safe_print(table)
    safe_print("\n[dim yellow]Backend unavailable — showing default tool list[/dim yellow]\n")

async def cmd_skill(session, arg):
    """List, load, or trigger prompt templates (skills)."""
    global loaded_skills
    await _load_skills_from_disk()
    
    arg = arg.strip()
    if not arg:
        if not loaded_skills:
            safe_print("\n[yellow]No prompt skills loaded. Place YAML skill definitions in C:\\Users\\Chesley\\Galactic AI\\skills\\[/yellow]")
            safe_print("[dim]Example skill YAML format:[/dim]")
            safe_print("[dim]name: Explain Code\ntrigger: explain\nprompt_template: \"Please explain the following: {input}\"[/dim]\n")
            return
            
        table = Table(title="Prompt Template Skills", box=ROUNDED)
        table.add_column("Name", style="cyan bold")
        table.add_column("Trigger", style="magenta")
        table.add_column("Template Preview", style="white")
        table.add_column("File", style="dim")
        
        for skill in loaded_skills:
            tpl = skill.get("prompt_template", "")
            preview = tpl[:50] + "..." if len(tpl) > 50 else tpl
            table.add_row(skill.get("name", ""), skill.get("trigger", ""), preview, skill.get("file", ""))
            
        safe_print("\n")
        safe_print(table)
        safe_print("\n[dim]Usage: /skill trigger <trigger> [input] - Or type trigger directly in chat[/dim]\n")
        return
        
    parts = arg.split(" ", 1)
    subcmd = parts[0].lower()
    subarg = parts[1] if len(parts) > 1 else ""
    
    if subcmd == "load":
        await _load_skills_from_disk()
        safe_print(f"[green]Successfully loaded {len(loaded_skills)} skills from disk.[/green]")
        return
        
    elif subcmd in ("trigger", "run"):
        if not subarg:
            safe_print("[red]Usage: /skill trigger <trigger_name> [input][/red]")
            return
        subparts = subarg.split(" ", 1)
        trigger = subparts[0]
        user_input = subparts[1] if len(subparts) > 1 else ""
        
        for skill in loaded_skills:
            if skill.get("trigger", "").lower() == trigger.lower() or skill.get("name", "").lower() == trigger.lower():
                template = skill.get("prompt_template", "")
                expanded = template.replace("{input}", user_input) if template else user_input
                safe_print(f"\n[dim yellow]⚡ Triggering skill: [bold]{skill['name']}[/bold][/dim yellow]\n")
                await send_chat(session, expanded)
                return
        safe_print(f"[red]No skill found with trigger or name: {trigger}[/red]")
        
    else:
        # Treat as directly triggering a skill by trigger name
        trigger = subcmd
        user_input = subarg
        for skill in loaded_skills:
            if skill.get("trigger", "").lower() == trigger.lower() or skill.get("name", "").lower() == trigger.lower():
                template = skill.get("prompt_template", "")
                expanded = template.replace("{input}", user_input) if template else user_input
                safe_print(f"\n[dim yellow]⚡ Triggering skill: [bold]{skill['name']}[/bold][/dim yellow]\n")
                await send_chat(session, expanded)
                return
        safe_print(f"[red]Unknown subcommand or skill trigger: {arg}[/red]")

async def cmd_plan(session, arg):
    """Toggle Plan Mode (prompts LLM to act as planner)."""
    global plan_mode_active
    arg = arg.strip().lower()
    if arg in ("on", "true", "1"):
        plan_mode_active = True
    elif arg in ("off", "false", "0"):
        plan_mode_active = False
    else:
        plan_mode_active = not plan_mode_active
    
    status = "[bold green]enabled[/bold green]" if plan_mode_active else "[bold red]disabled[/bold red]"
    safe_print(f"📋 Plan Mode is now {status}.")
    if plan_mode_active:
        safe_print("[dim]Backend will now act as a planner and structure responses as step-by-step instructions.[/dim]")

async def cmd_rewind(session, arg):
    """Remove the last N messages/turns to undo conversation."""
    n = 2
    if arg:
        try:
            n = int(arg.strip())
        except ValueError:
            safe_print(f"[red]Invalid number of messages: {arg}[/red]")
            return
            
    try:
        payload = {'message': f"/rewind {n}", 'images_json': '[]'}
        async with session.post(f"{API_URL}/api/chat", json=payload) as resp:
            if resp.status == 200:
                res = await resp.json()
                response_text = res.get('response', f"⏪ Rewound conversation by {n} message(s).")
                safe_print(f"[green]{response_text}[/green]")
            else:
                safe_print(f"[red]Failed to rewind session: HTTP {resp.status}[/red]")
    except Exception as e:
        safe_print(f"[red]Connection error: {e}[/red]")

async def cmd_save(session, arg):
    """Save current session to a JSON file."""
    name = arg.strip() if arg else f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not os.path.exists(sessions_dir):
        os.makedirs(sessions_dir, exist_ok=True)
    
    filepath = os.path.join(sessions_dir, f"{name}.json")
    
    data = {
        "saved_at": datetime.now().isoformat(),
        "cwd": os.getcwd(),
        "tokens": session_token_counts.copy(),
        "verbose": VERBOSE_MODE,
        "thinking": THINKING_MODE,
        "response_snapshot": current_response[-2000:] if current_response else "",
    }
    
    # Try to get full conversation history from backend
    try:
        async with session.get(f"{API_URL}/api/history", timeout=3) as resp:
            if resp.status == 200:
                data["history"] = await resp.json()
    except Exception:
        pass
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    safe_print(f"[green]Session saved to [bold]{filepath}[/bold][/green]")

async def cmd_load(session, arg):
    """Load a previously saved session."""
    if not arg:
        # List available sessions
        if not os.path.exists(sessions_dir):
            safe_print("[yellow]No saved sessions found.[/yellow]")
            return
        
        files = [f for f in os.listdir(sessions_dir) if f.endswith('.json')]
        if not files:
            safe_print("[yellow]No saved sessions found.[/yellow]")
            return
        
        table = Table(title="Saved Sessions", box=ROUNDED)
        table.add_column("File", style="cyan")
        table.add_column("Size", justify="right")
        table.add_column("Modified", justify="right")
        
        for f in sorted(files):
            filepath = os.path.join(sessions_dir, f)
            size_kb = os.path.getsize(filepath) / 1024
            mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M")
            table.add_row(f, f"{size_kb:.1f} KB", mod_time)
        
        safe_print("\n")
        safe_print(table)
        safe_print(f"\n[dim]Usage: /load <filename> (e.g., /load session_20260618.json)[/dim]\n")
        return
    
    # Strip extension for arg resolution
    arg_clean = arg.strip()
    if arg_clean.endswith('.json'):
        arg_clean = arg_clean[:-5]
    
    filepath = os.path.join(sessions_dir, f"{arg_clean}.json")
    
    if not os.path.exists(filepath):
        safe_print(f"[red]Session file not found: {filepath}[/red]")
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Try to push loaded history back to the backend
    try:
        history = data.get("history", [])
        if history:
            async with session.post(f"{API_URL}/api/history/load", json={"history": history}, timeout=5) as resp:
                if resp.status == 200:
                    safe_print("[green]Context synced to backend.[/green]")
                else:
                    safe_print(f"[yellow]Backend sync failed (HTTP {resp.status}) - context loaded locally only.[/yellow]")
    except Exception:
        safe_print("[dim]Backend unavailable - context loaded locally only.[/dim]")

    safe_print(f"[green]Session [bold]{arg_clean}[/bold] loaded. Saved at: {data.get('saved_at', 'unknown')}[/green]")

async def cmd_history(session, arg):
    """Show recent conversation history."""
    count = 10
    if arg:
        try:
            count = int(arg.strip())
        except ValueError:
            safe_print(f"[red]Invalid count: {arg}[/red]")
            return
    
    try:
        async with session.get(f"{API_URL}/api/history?limit={count}", timeout=3) as resp:
            if resp.status == 200:
                messages = await resp.json()
                
                table = Table(title=f"Recent History (last {count})", box=ROUNDED)
                table.add_column("#", style="dim")
                table.add_column("Role", style="cyan")
                table.add_column("Content", style="white")
                
                for i, msg in enumerate(messages[:count]):
                    role = msg.get('role', 'system')
                    content = str(msg.get('content', ''))[:150]
                    if len(content) > 149:
                        content += "..."
                    table.add_row(str(i + 1), role, content.replace('\n', ' '))
                
                safe_print("\n")
                safe_print(table)
                safe_print("\n")
            else:
                safe_print(f"[yellow]History unavailable from backend. HTTP {resp.status}[/yellow]")
    except Exception:
        safe_print("[yellow]History endpoint unavailable. Use /save to preserve sessions locally.[/yellow]")

async def cmd_config(session, arg):
    """View or edit config settings (config.local.yaml overlay when present)."""
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(_base_dir, "config.local.yaml")
    if not os.path.exists(config_path):
        config_path = os.path.join(_base_dir, "config.yaml")
    
    if not arg:
        # Show current config
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            p = Panel(
                content[:800] + ("..." if len(content) > 800 else ""),
                title="config.yaml",
                border_style="magenta",
                box=ROUNDED
            )
            safe_print("\n")
            safe_print(p)
            safe_print(f"\n[dim]Usage: /config key=value to edit (e.g., /config llm_model=qwen3.6)[/dim]\n")
        else:
            safe_print("[red]config.yaml not found.[/red]")
        return
    
    # Edit config
    if "=" not in arg.strip():
        safe_print(f"[red]Usage: /config key=value (e.g., /config llm_model=qwen3.6)[/red]")
        return
    
    key, value = arg.strip().split("=", 1)
    key = key.strip()
    value = value.strip()
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith(f"{key}:"):
                # Handle quoted and unquoted values
                indent = len(line) - len(line.lstrip())
                new_lines.append(" " * indent + f"{key}: {value}\n")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            new_lines.append(f"{key}: {value}\n")
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        safe_print(f"[green]Config updated: [bold]{key}[/bold] = {value}[/green]")
    else:
        safe_print("[red]config.yaml not found.[/red]")

async def cmd_status(session, arg):
    """Show full system status."""
    try:
        async with session.get(f"{API_URL}/api/status") as resp:
            if resp.status == 200:
                data = await resp.json()
                
                table = Table(title="Galactic AI System Status", box=ROUNDED)
                table.add_column("Property", style="cyan bold")
                table.add_column("Value", style="white")
                
                for key, val in data.items():
                    if isinstance(val, dict):
                        val = json.dumps(val)[:100]
                    table.add_row(key.replace("_", " ").title(), str(val))
                
                safe_print("\n")
                safe_print(table)
                safe_print("\n")
            else:
                safe_print(f"[red]Status check failed: HTTP {resp.status}[/red]")
    except Exception as e:
        safe_print(f"[red]Connection error: {e}[/red]")

async def cmd_exit(session, arg):
    """Gracefully shut down the CLI."""
    safe_print("[dim cyan]👋 Shutting down Galactic AI CLI...[/dim cyan]")
    raise KeyboardInterrupt



# ==========================================
# COMMUNITY COMMANDS
# ==========================================

import subprocess
import os

async def cmd_worktree(session, arg):
    """Manage isolated git worktrees for safe sandboxing."""
    parts = arg.strip().split()
    if not parts:
        # List active worktrees
        try:
            res = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, cwd=os.getcwd())
            if res.returncode == 0:
                safe_print("\n[bold cyan]Active Git Worktrees:[/bold cyan]")
                lines = res.stdout.strip().splitlines()
                for idx, line in enumerate(lines):
                    safe_print(f"  [green]{idx + 1}.[/green] {line}")
                safe_print("\n[dim]Usage: /worktree <create|remove> <branch>[/dim]\n")
            else:
                safe_print(f"\n[red]Failed to list worktrees: {res.stderr}[/red]\n")
        except Exception as e:
            safe_print(f"\n[red]Error: {e}[/red]\n")
        return

    action = parts[0].lower()
    if action == "create":
        if len(parts) < 2:
            safe_print("[red]Error: Specify a branch name. Usage: /worktree create <branch_name>[/red]")
            return
        branch = parts[1]
        workspace_dir = os.path.abspath(os.path.join(os.getcwd(), "workspace"))
        wt_dir = os.path.join(workspace_dir, ".worktrees", f"wt_{branch}")
        
        safe_print(f"[cyan]Creating isolated git worktree in {wt_dir} on branch '{branch}'...[/cyan]")
        try:
            os.makedirs(os.path.dirname(wt_dir), exist_ok=True)
            res = subprocess.run(["git", "worktree", "add", "-b", branch, wt_dir], capture_output=True, text=True, cwd=os.getcwd())
            if res.returncode == 0:
                safe_print(f"[green]✓ Worktree created successfully at {wt_dir}[/green]")
                safe_print(f"[dim]Switch to it with: cd {wt_dir}[/dim]")
            else:
                safe_print(f"[red]Failed to create worktree: {res.stderr}[/red]")
        except Exception as e:
            safe_print(f"[red]Error: {e}[/red]")
    elif action == "remove":
        if len(parts) < 2:
            safe_print("[red]Error: Specify a worktree path or branch. Usage: /worktree remove <path_or_branch>[/red]")
            return
        target = parts[1]
        safe_print(f"[cyan]Removing worktree '{target}'...[/cyan]")
        try:
            res = subprocess.run(["git", "worktree", "remove", target], capture_output=True, text=True, cwd=os.getcwd())
            if res.returncode == 0:
                safe_print(f"[green]✓ Worktree removed successfully[/green]")
            else:
                safe_print(f"[red]Failed to remove worktree: {res.stderr}[/red]")
        except Exception as e:
            safe_print(f"[red]Error: {e}[/red]")
    else:
        safe_print("[yellow]Usage: /worktree <create|remove> <branch_name/worktree_path>[/yellow]")


async def cmd_vcr(session, arg):
    """Control file-level snapshots (VCR & Thinkback)."""
    parts = arg.strip().split()
    if not parts:
        safe_print("[yellow]Usage: /vcr <snapshot|undo|list> <file_path>[/yellow]")
        return
    action = parts[0].lower()
    if len(parts) < 2:
        safe_print("[red]Error: File path is required.[/red]")
        return
    filepath = parts[1]
    
    # Normalize path
    if not os.path.isabs(filepath):
        filepath = os.path.abspath(os.path.join(os.getcwd(), filepath))
    
    if action == "snapshot":
        safe_print(f"[cyan]Taking VCR snapshot of '{filepath}'...[/cyan]")
        await send_chat(session, f"Please create a VCR snapshot of {filepath}")
    elif action == "undo":
        safe_print(f"[cyan]Undoing last change to '{filepath}' via VCR...[/cyan]")
        await send_chat(session, f"Please undo the last change to {filepath} using VCR")
    elif action == "list":
        safe_print(f"[cyan]Listing VCR history for '{filepath}'...[/cyan]")
        await send_chat(session, f"Please list VCR history for {filepath}")
    else:
        safe_print("[yellow]Usage: /vcr <snapshot|undo|list> <file_path>[/yellow]")


async def cmd_permissions(session, arg):
    """View or update tool permissions (allow/deny lists)."""
    parts = arg.strip().split()
    if not parts:
        # Show current permissions
        safe_print("\n[bold cyan]Current Tool Permissions:[/bold cyan]")
        safe_print("[dim]Use /permissions <allow|deny> <tool_pattern> to modify[/dim]\n")
        await send_chat(session, "Please show current tool permissions")
        return
    
    action = parts[0].lower()
    if action in ("allow", "deny"):
        if len(parts) < 2:
            safe_print(f"[red]Error: Specify a tool pattern. Usage: /permissions {action} <tool_pattern>[/red]")
            return
        pattern = parts[1]
        safe_print(f"[cyan]{action.capitalize()}ing tool pattern: {pattern}[/cyan]")
        await send_chat(session, f"Please {action} tool pattern: {pattern}")
    else:
        safe_print("[yellow]Usage: /permissions <allow|deny> <tool_pattern>[/yellow]")



# ==========================================
# DIFF RENDERING (Colored ANSI Output)
# ==========================================

def render_diff(old_text: str, new_text: str, context_lines: int = 3) -> Text:
    """Render a colored diff between old and new text using difflib + Rich."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(old_lines, new_lines, lineterm='', n=context_lines)
    result = Text()

    for line in diff:
        if not line.endswith('\n'):
            line += '\n'

        if line.startswith('+++'):
            # File header for new file
            result.append(line.rstrip(), style="bold green")
        elif line.startswith('---'):
            # File header for old file
            result.append(line.rstrip(), style="bold red")
        elif line.startswith('@@'):
            # Hunk header
            result.append(line.rstrip(), style="bold cyan")
        elif line.startswith('+'):
            # Added line
            result.append(line[0], style="bold green background_color(on_green)")
            result.append(line[1:].rstrip(), style="green")
            result.append('\n')
        elif line.startswith('-'):
            # Removed line
            result.append(line[0], style="bold red background_color(on_red)")
            result.append(line[1:].rstrip(), style="red")
            result.append('\n')
        elif line.startswith(' '):
            # Context line (unchanged)
            result.append(line.rstrip(), style="dim white")
            result.append('\n')
        else:
            # Other lines (file headers, etc.)
            result.append(line.rstrip(), style="dim yellow")
            result.append('\n')

    return result


def render_file_diff(filepath: str, old_content: str, new_content: str) -> None:
    """Render a file diff with filename header in a Rich Panel."""
    diff_text = render_diff(old_content, new_content)
    rel_path = os.path.relpath(filepath)
    panel = Panel(
        diff_text,
        title=f"[bold magenta]diff[/bold magenta] [cyan]{rel_path}[/cyan]",
        border_style="blue",
        box=ROUNDED,
        padding=(0, 1),
    )
    safe_print(panel)


# ==========================================
# EFFORT COMMAND (Thinking Intensity Control)
# ==========================================

async def cmd_effort(session, arg):
    """Set or display thinking effort level: low, medium, high, max."""
    global EFFORT_LEVEL

    if not arg:
        # Show current level
        color = EFFORT_COLORS.get(EFFORT_LEVEL, "white")
        icon_text = EFFORT_ICONS.get(EFFORT_LEVEL, EFFORT_LEVEL)
        p = Panel(
            f"[bold]{icon_text}[/bold] [dim](effort: {EFFORT_LEVEL})[/dim]\n\n"
            f"[dim]Usage:[/dim] [cyan]/effort [low|medium|high|max][/cyan]\n\n"
            f"[dim]Controls model reasoning intensity. Higher = more thinking, slower but deeper.[/dim]",
            title="Thinking Effort",
            border_style=color,
            box=ROUNDED,
        )
        safe_print("\n")
        safe_print(p)
        safe_print("\n")
        return

    level = arg.strip().lower()
    if level not in EFFORT_COLORS:
        safe_print(f"[red]Invalid effort level: {level}[/red]")
        safe_print(f"[dim]Valid levels: [cyan]{', '.join(EFFORT_COLORS.keys())}[/cyan][/dim]")
        return

    old_level = EFFORT_LEVEL
    EFFORT_LEVEL = level

    # Try to push to backend config
    try:
        async with session.post(
            f"{API_URL}/api/config",
            json={"thinking_effort": level},
            timeout=3,
        ) as resp:
            if resp.status in (200, 404):
                # 404 is OK — backend may not have the endpoint yet
                pass
    except Exception:
        # Silently fail — EFFORT_LEVEL is still stored locally
        pass

    color = EFFORT_COLORS[level]
    icon_text = EFFORT_ICONS[level]
    if old_level != level:
        safe_print(f"[green]Thinking effort changed:[/green] [bold]{old_level}[/bold] → [{color} bold]{icon_text}[/]")
    else:
        safe_print(f"[dim]Thinking effort is already set to[/dim] [{color} bold]{icon_text}[/]")


# ==========================================
# HINT COMMAND (Session-level Instructions)
# ==========================================

async def cmd_hint(session, arg):
    """Add temporary instructions to system context for this session."""
    global session_hints

    if not arg:
        # Show current hints
        if not session_hints:
            safe_print("[yellow]No active hints. Use /hint <text> to add one.[/yellow]")
            return

        p = Panel(
            "\n".join(f"[bold]{i+1}.[/bold] {h}" for i, h in enumerate(session_hints)),
            title=f"Active Hints ({len(session_hints)})",
            border_style="magenta",
            box=ROUNDED,
        )
        safe_print("\n")
        safe_print(p)
        safe_print("[dim]\nHint: Clear all hints with /hint --clear[/dim]")
        return

    if arg.strip() == "--clear":
        session_hints.clear()
        safe_print("[green]All hints cleared.[/green]")
        return

    # Append hint
    session_hints.append(arg.strip())
    safe_print(f"[magenta]💡 Hint added:[/magenta] {arg.strip()}")


# ==========================================
# EXPORT COMMAND (Save Conversation)
# ==========================================

async def cmd_export(session, arg):
    """Export conversation history to file."""
    fmt = "json"
    if arg:
        fmt = arg.strip().lower()
    if fmt not in ("json", "md", "txt"):
        safe_print(f"[red]Invalid format: {fmt}[/red]")
        safe_print("[dim]Valid formats: [cyan]json, md, txt[/cyan][/dim]")
        return

    # Create exports directory
    os.makedirs(exports_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Try to get conversation history from backend
    history = None
    try:
        async with session.get(f"{API_URL}/api/history", timeout=3) as resp:
            if resp.status == 200:
                history = await resp.json()
    except Exception:
        pass

    if history is None:
        # Fallback: export what we have locally
        history = [
            {"role": "system", "content": f"Galactic AI Session — {timestamp}", "meta": {
                "tokens": session_token_counts,
                "verbose": VERBOSE_MODE,
                "thinking": THINKING_MODE,
                "effort": EFFORT_LEVEL,
            }},
        ]
        if current_response:
            history.append({"role": "assistant", "content": current_response[-5000:]})

    # Build export content
    if fmt == "json":
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "effort_level": EFFORT_LEVEL,
            "hints_active": list(session_hints),
            "tokens": session_token_counts,
            "history": history,
        }
        filename = f"conversation_{timestamp}.json"
        filepath = os.path.join(exports_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

    elif fmt == "md":
        lines = [f"# Galactic AI Conversation — {timestamp}\n",
                 f"**Exported:** {datetime.now().isoformat()}\n",
                 f"**Effort Level:** {EFFORT_LEVEL}\n",
                 f"**Tokens:** Input: {session_token_counts['input']:,} | Output: {session_token_counts['output']:,}\n"]
        if session_hints:
            lines.append(f"\n**Active Hints:**\n")
            for h in session_hints:
                lines.append(f"- {h}")
        lines.append("\n---\n")
        for msg in history:
            if isinstance(msg, dict):
                role = msg.get('role', 'unknown').upper()
                content = str(msg.get('content', ''))
                truncated = content[:4000] + ('...' if len(content) > 4000 else '')
                lines.append(f"\n### [{role}]\n\n{truncated}\n")

        filename = f"conversation_{timestamp}.md"
        filepath = os.path.join(exports_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    else:  # txt
        lines = [f"Galactic AI Conversation — {timestamp}\n",
                 f"Exported: {datetime.now().isoformat()}\n",
                 f"Effort Level: {EFFORT_LEVEL}\n",
                 f"Tokens: Input: {session_token_counts['input']:,} | Output: {session_token_counts['output']:,}\n"]
        if session_hints:
            lines.append(f"\nActive Hints:")
            for h in session_hints:
                lines.append(f"  - {h}")
        lines.append("\n" + "=" * 60 + "\n")
        for msg in history:
            if isinstance(msg, dict):
                role = msg.get('role', 'unknown').upper()
                content = str(msg.get('content', ''))
                truncated = content[:4000] + ('...' if len(content) > 4000 else '')
                lines.append(f"\n[{role}]\n{truncated}\n")

        filename = f"conversation_{timestamp}.txt"
        filepath = os.path.join(exports_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    safe_print(f"[green]Export saved to[/green] [bold]{filepath}[/bold] ({len(str(history)):,} bytes)")


# ==========================================
# COMMAND REGISTRY
# ==========================================

async def cmd_shutup(session, arg):
    """Stop currently playing Text-to-Speech (TTS)."""
    try:
        async with session.post(f"{API_URL}/api/voice/stop", timeout=2) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get('ok'):
                    safe_print("[green]TTS playback interrupted.[/green]")
                else:
                    safe_print(f"[yellow]{data.get('message', 'Failed to stop TTS')}[/yellow]")
            else:
                safe_print(f"[red]Failed to stop TTS. HTTP {resp.status}[/red]")
    except Exception as e:
        safe_print(f"[red]Connection error while trying to stop TTS: {e}[/red]")



COMMAND_GRAPH = {
    "help": {"handler": cmd_help, "desc": "Show this help message"},
    "clear": {"handler": cmd_clear, "desc": "Clear context and terminal"},
    "compact": {"handler": cmd_compact, "desc": "Trigger deep history compaction to save tokens"},
    "agents": {"handler": cmd_agents, "desc": "List active sub-agents"},
    "tasks": {"handler": cmd_agents, "desc": "List active sub-agents (alias)"},
    "desktop": {"handler": cmd_desktop, "desc": "Launch Desktop UI"},
    "btw": {"handler": cmd_btw, "desc": "Ask a side question without polluting conversation history"},

    
    "commit": {"handler": cmd_commit, "desc": "Auto-generate git commit and commit changes"},
    # NEW: Extra commands
    "context": {"handler": cmd_context, "desc": "Show context window usage & model info"},
    "cost": {"handler": cmd_cost, "desc": "Show session cost & token statistics"},
    "verbose": {"handler": cmd_verbose, "desc": "Toggle verbose mode (expanded thinking)"},
    "thinking": {"handler": cmd_thinking, "desc": "Toggle extended thinking mode"},
    "cwd": {"handler": cmd_cwd, "desc": "Show/change current working directory"},
    "cd": {"handler": cmd_cwd, "desc": "Change directory (alias)"},
    "memory": {"handler": cmd_memory, "desc": "Search long-term memory"},
    "skills": {"handler": cmd_skills, "desc": "List available tools & skills"},
    "skill": {"handler": cmd_skill, "desc": "List, load, or trigger prompt templates (skills)"},
    "plan": {"handler": cmd_plan, "desc": "Toggle Plan Mode (prompts LLM to act as planner)"},
    "auto": {"handler": cmd_auto, "desc": "Toggle Auto Mode (autonomous agent loop)"},
    "rewind": {"handler": cmd_rewind, "desc": "Remove the last N messages/turns to undo conversation"},
    "boost": {"handler": cmd_boost, "desc": "Re-run the last answer on the boost (cloud) model — /boost [model]"},
    "retry": {"handler": cmd_retry, "desc": "Re-run the last answer on the current model"},
    "hybrid": {"handler": cmd_hybrid, "desc": "Toggle Hybrid Coding Mode — cloud Architect writes, local Builder applies"},
    "save": {"handler": cmd_save, "desc": "Save current session to JSON file"},
    "load": {"handler": cmd_load, "desc": "Load a saved session or list files"},
    "history": {"handler": cmd_history, "desc": "Show recent conversation history"},
    "config": {"handler": cmd_config, "desc": "View/edit config.yaml settings"},
    "status": {"handler": cmd_status, "desc": "Show full system status"},
    "exit": {"handler": cmd_exit, "desc": "Gracefully exit the CLI"},

    "worktree": {"handler": cmd_worktree, "desc": "Manage isolated git worktrees"},
    "vcr": {"handler": cmd_vcr, "desc": "Control file-level snapshots (VCR & Thinkback)"},
    "permissions": {"handler": cmd_permissions, "desc": "View or update tool permissions"},
    "shutup": {"handler": cmd_shutup, "desc": "Stop currently playing Text-to-Speech"},
    "quiet": {"handler": cmd_shutup, "desc": "Stop currently playing Text-to-Speech (alias)"},
}

async def process_slash_command(session, user_input):
    """Route input to command if it starts with /"""
    parts = user_input.split(" ", 1)
    cmd_name = parts[0][1:].lower()
    arg = parts[1] if len(parts) > 1 else ""
    
    if cmd_name in COMMAND_GRAPH:
        await COMMAND_GRAPH[cmd_name]["handler"](session, arg)
        return True
    return False

# ==========================================
# AGENT NOTIFICATION HELPER
# ==========================================

async def check_background_agents(session):
    """Fetch and display status of background subagents."""
    try:
        async with session.get(f"{API_URL}/api/subagents", timeout=2) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    running = [a for a in data if a.get('status') == 'running']
                    pending = [a for a in data if a.get('status') == 'pending']
                    completed = [a for a in data if a.get('status') in ('completed', 'finished')]
                    
                    parts = []
                    if running:
                        parts.append(f"[green]● {len(running)} running[/green]")
                    if pending:
                        parts.append(f"[yellow]◐ {len(pending)} pending[/yellow]")
                    if completed:
                        parts.append(f"[dim]✓ {len(completed)} completed[/dim]")
                    
                    if parts:
                        safe_print(f"  [dim]Subagents: {' | '.join(parts)}[/dim]")
    except Exception:
        pass

# ==========================================
# DYNAMIC PROMPT BUILDER
# ==========================================

def build_prompt_text():
    """Build dynamic prompt prefix with CWD + live context usage."""
    cwd = os.getcwd()
    project_name = os.path.basename(cwd)
    prefix = ""
    if plan_mode_active:
        prefix += "[PLAN MODE] "
    if auto_mode_active:
        prefix += "[AUTO MODE] "
    ctx = ""
    total = session_token_counts['input'] + session_token_counts['output']
    if total > 0 and context_tracker.max_tokens:
        pct = min(100, int(total / context_tracker.max_tokens * 100))
        icon = "🟢" if pct < 60 else ("🟡" if pct < 85 else "🔴")
        ctx = f"{icon}{pct}% "
    return f"{prefix}{ctx}[{project_name}] ❯ "

# ==========================================
# ARGUMENT PARSING & MAIN LOOP
# ==========================================

def parse_args():
    parser = argparse.ArgumentParser(description="Galactic AI CLI")
    parser.add_argument("-p", "--prompt", type=str, help="Run a single prompt headlessly and exit")
    parser.add_argument("-c", "--resume", type=str, help="Resume a specific session ID")
    parser.add_argument("--fork-session", action="store_true", help="Fork the resumed session into a new ID")
    parser.add_argument("--json-schema", type=str, help="Force structured JSON output matching schema")
    parser.add_argument("--append-system-prompt", type=str, help="Append extra rules to the system prompt")
    return parser.parse_args()

async def main():
    args = parse_args()
    
    piped_input = ""
    if not sys.stdin.isatty():
        piped_input = sys.stdin.read().strip()
        
    initial_prompt = args.prompt or ""
    if piped_input:
        initial_prompt = (initial_prompt + "\n" + piped_input).strip()
        
    is_headless = bool(initial_prompt)

    try:
        timeout = aiohttp.ClientTimeout(total=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{API_URL}/api/status", timeout=2) as resp:
                if resp.status != 200:
                    safe_print("[red]Galactic AI server is running but returned error on status check.[/red]")
                    return
    except Exception:
        safe_print("[red]Could not connect to Galactic AI.[/red]")
        safe_print("[yellow]Please start the Control Deck (launcher_desktop.py or web_deck.py) first.[/yellow]")
        return
    
    if not is_headless:
        os.system('cls' if os.name == 'nt' else 'clear')
        safe_print(Panel("[bold cyan]GALACTIC AI CLI[/bold cyan]", border_style="cyan"))
        safe_print("Connected to background core. Type [bold]exit[/bold] or [bold]quit[/bold] to leave. Type [bold]/help[/bold] for commands.\n")
    
    try:
        from prompt_toolkit.output.defaults import create_output
        output = create_output()
        prompt_session = PromptSession(output=output, completer=MentionCompleter(), complete_while_typing=True)
    except Exception:
        # Fallback for non-console environments
        from prompt_toolkit.output.plain_text import PlainTextOutput
        prompt_session = PromptSession(output=PlainTextOutput(sys.stdout), completer=MentionCompleter(), complete_while_typing=True)
    headless_done = asyncio.Event()

    async with aiohttp.ClientSession(timeout=timeout) as http_session:

        class WSManager:
            """
            Self-healing event-stream connection. The CLI previously connected
            once; if the socket dropped, every stream_chunk, tool panel, and
            the final 'done' event vanished silently. This reconnects forever
            with exponential backoff + jitter and announces the gap.
            """
            def __init__(self, session, url):
                self.session = session
                self.url = url
                self.connected = asyncio.Event()
                self.task = None
                self._stopped = False

            async def run(self):
                import random
                delay = 1.0
                while not self._stopped:
                    try:
                        ws = await self.session.ws_connect(self.url, heartbeat=20)
                        if delay > 1.0:
                            safe_print("\n[green]🔌 Event stream reconnected.[/green]")
                        delay = 1.0
                        self.connected.set()
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    payload = json.loads(msg.data)
                                    handle_ws_event(payload)
                                    if payload.get('type') == 'status' and payload.get('data') == 'done':
                                        headless_done.set()
                                except json.JSONDecodeError:
                                    pass
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                    self.connected.clear()
                    if self._stopped:
                        break
                    safe_print(f"\n[yellow]⚠️ Event stream lost — reconnecting in {delay:.0f}s...[/yellow]")
                    await asyncio.sleep(delay + random.uniform(0, delay * 0.3))
                    delay = min(delay * 2, 30.0)

            def start(self):
                self.task = asyncio.create_task(self.run())
                return self.task

            async def stop(self):
                self._stopped = True
                if self.task:
                    self.task.cancel()
                    try:
                        await self.task
                    except BaseException:
                        pass

        ws_mgr = WSManager(http_session, WS_URL)
        ws_mgr.start()
        try:
            await asyncio.wait_for(ws_mgr.connected.wait(), timeout=6)
        except asyncio.TimeoutError:
            safe_print("[yellow]Event stream not up yet — continuing, will keep retrying in background.[/yellow]")

        # Load skills from disk on startup
        try:
            await _load_skills_from_disk()
        except Exception:
            pass

        extra_payload = {}
        if args.resume: extra_payload['resume_session'] = args.resume
        if args.fork_session: extra_payload['fork_session'] = True
        if args.json_schema: extra_payload['json_schema'] = args.json_schema
        if args.append_system_prompt: extra_payload['append_system_prompt'] = args.append_system_prompt

        if is_headless:
            reset_stream_state()
            await send_chat(http_session, initial_prompt, extra_payload)
            try:
                await asyncio.wait_for(headless_done.wait(), timeout=120)
            except asyncio.TimeoutError:
                safe_print("[yellow]⚠️ No completion event within 120s of response end — exiting anyway.[/yellow]")
            await ws_mgr.stop()
            return

        while True:
            # Show background agent status before prompt
            await check_background_agents(http_session)
            
            if sys.platform == 'win32':
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)
                except Exception:
                    pass
            
            try:
                with patch_stdout():
                    user_input = await prompt_session.prompt_async(build_prompt_text(), style=custom_style)
            except Exception:
                try:
                    user_input = await prompt_session.prompt_async(build_prompt_text(), style=custom_style)
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
                    continue
                except EOFError:
                    break
                    
            user_input = user_input.strip()
            if not user_input:
                continue

            # --- YOLO MODE INTERACTIVE TUIs ---
            if user_input.lower() in ('/stats', '/cost'):
                try:
                    text_content = \
                        "📊 SESSION ANALYTICS\n\n" + \
                        f"Input Tokens:  {cost_analytics.total_input_tokens:,}\n" + \
                        f"Output Tokens: {cost_analytics.total_output_tokens:,}\n" + \
                        f"Current Cost:  ${cost_analytics.session_cost:.4f}\n\n" + \
                        "[Use Arrow Keys + Enter to close]"
                    await button_dialog(title='Galactic Analytics', text=text_content, buttons=[('Close', None)]).run_async()
                except Exception:
                    await cmd_cost(http_session, "")
                continue


            if user_input.lower() in ('exit', 'quit'):
                break
                
            if user_input.startswith('/'):
                handled = await process_slash_command(http_session, user_input)
                if handled:
                    continue
                # Context-management commands live in the backend's command
                # interceptor (web_deck handle_chat) — forward instead of failing.
                if user_input.split()[0].lower() in ('/compact', '/context', '/clear', '/rewind',
                                                     '/boost', '/retry', '/hybrid'):
                    reset_stream_state()
                    await send_chat(http_session, user_input, extra_payload)
                    continue
                safe_print(f"[yellow]Unknown command: {user_input}. Type /help for a list.[/yellow]")
                continue

            reset_stream_state()
            await send_chat(http_session, user_input, extra_payload)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        safe_print("\n[dim]👋 Galactic AI CLI exiting.[/dim]")
        sys.exit(0)
