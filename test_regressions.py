"""
Galactic AI — Regression Suite
==============================

This is the file that stops the same three bugs coming back.

Every test below maps to a REAL regression that already shipped and already
cost something (money, a broken hybrid run, a gaslit model). The CHANGELOG is
full of one-off "30-case regression battery green" / "39-case regression suite"
notes for batteries that were written, run once, and thrown away. This file is
that battery, kept.

Three failure classes recur across the project's history:

  (a) PROVIDER-CAPABILITY LISTS silently omitting a provider.
      `supports_native_tools` broke TWICE in v2.2.0 alone: `lmstudio` missing
      meant ~20k tokens of tool schemas got text-injected into every prompt
      (a bare "hello" shipped ~26k tokens and 400'd); `moonshot` missing meant
      the cloud Architect planned blind while billing real credits.

  (b) INTENT / HALLUCINATION REGEXES misfiring in both directions.
      False positives ("Changed a setting and testing again" launching the
      whole hybrid pipeline; the model being accused of hallucinating because
      it said "before they start typing") and false negatives ("scan THIS
      codebase" not matching a literal "scan the codebase" check).

  (c) CONTEXT-WINDOW RESOLUTION. Kimi K3 reported 32k instead of 1M; LM Studio
      needing a hard clamp to its actually-loaded window.

HOW TO RUN
----------
    python -m pytest test_regressions.py -q      # normal
    python test_regressions.py                   # no pytest needed

HONEST COST: `import gateway_v3` takes ~8-12s (it pulls the whole gateway).
The tests themselves are instant — the entire suite is import time plus a
rounding error. Run it pre-commit, NOT on save.

HOW TO ADD A CASE
-----------------
The whole file rests on one trick:

    G.__new__(G)   # a real GalacticGateway, with __init__ skipped entirely

That gives a real instance with real bound methods and real class attributes,
but runs no __init__ — so no network, no asyncio loop, no config load, no
9-second boot. Everything these functions touch is either getattr-guarded or a
plain dict, so a `SimpleNamespace` is a good enough `core` / `llm`. Use the
`gw()` helper below; pass extra `core` attributes as kwargs:

    gw("lmstudio", "qwen3", {"models": {...}}, lmstudio_manager=FakeLMStudio(8192))

Then write a plain `def test_*()` with a one-line comment naming the bug it
guards. Keep every test pure and instant: NO network, NO live model, NO event
loop, NO touching the 600-line streaming methods.

KNOWN GAPS (deliberately recorded, not hidden)
----------------------------------------------
Two tests are marked `known_bug(...)`. They document live, unfixed instances of
failure class (a) and are expected to FAIL. pytest reports them as "xfailed";
the standalone runner prints "XFAIL". If someone fixes the underlying bug, the
marker turns the test RED (strict xfail) so it gets promoted into the normal
provider list instead of quietly rotting. See `test_KNOWN_BUG_*` below.
"""

import io
import os
import re
import sys
from types import SimpleNamespace

# Make the repo importable no matter what cwd pytest was invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gateway_v3                       # noqa: E402  (~8-12s: the whole gateway)
from config_loader import deep_merge    # noqa: E402

G = gateway_v3.GalacticGateway


# ─────────────────────────────────────────────────────────────────────────────
# Harness
# ─────────────────────────────────────────────────────────────────────────────

def gw(provider="moonshot", model="kimi-k3", config=None, **extra):
    """A real GalacticGateway with __init__ skipped.

    `__new__` gives real bound methods and real class attributes with none of
    the boot cost or side effects. Beats MagicMock(spec=[]) — no unbound-method
    gymnastics, and a typo'd attribute name raises instead of silently
    returning a Mock.

    extra kwargs become attributes of the fake `core`
    (e.g. lmstudio_manager=..., ollama_manager=...).
    """
    g = G.__new__(G)
    g.llm = SimpleNamespace(provider=provider, model=model)
    g.core = SimpleNamespace(config=config or {}, **extra)
    return g


class FakeContextManager:
    """Stands in for OllamaManager / LMStudioManager: only get_context_window()
    is ever called by the code under test."""

    def __init__(self, window):
        self.window = window

    def get_context_window(self, model_name, default=0):
        return self.window


def known_bug(reason):
    """Mark a test as documenting a REAL, UNFIXED bug.

    The test is expected to fail. When the bug is fixed the test starts
    passing, which — because the xfail is strict — is itself reported as a
    FAILURE, forcing whoever fixed it to delete this marker and fold the case
    into the normal suite. This is how a known bug stays visible instead of
    being deleted or asserted-as-correct.
    """
    def deco(fn):
        fn.__known_bug__ = reason
        try:
            import pytest
            return pytest.mark.xfail(strict=True, reason=reason)(fn)
        except ImportError:
            return fn
    return deco


# ─────────────────────────────────────────────────────────────────────────────
# 1. supports_native_tools  (failure class (a) — the money bug)
#
# When this property answers False, _build_system_prompt takes the legacy
# branch and stuffs "AVAILABLE TOOLS (with parameter schemas)" + few-shot
# examples into the system prompt as TEXT — roughly 20k tokens, every single
# turn. It is the highest-value assertion in this file: it has been wrong
# twice, and each time it cost real money before anyone noticed.
# ─────────────────────────────────────────────────────────────────────────────

# Every provider the gateway can actually dial. Sources, so this list can be
# re-derived when a provider is added:
#   - gateway_v3._get_provider_base_url  → default_urls (OpenAI-compatible)
#   - gateway_v3._call_llm               → the routing if/elif chain
#   - web_deck / galactic_cli / telegram_bridge  → user-selectable provider lists
# ADD A PROVIDER ANYWHERE? ADD IT HERE TOO.
NATIVE_TOOL_PROVIDERS = [
    "openai", "anthropic", "google", "xai", "nvidia", "groq", "mistral",
    "cerebras", "huggingface", "kimi", "moonshot", "deepseek", "minimax",
    "ollama", "lmstudio", "openrouter", "zai",
]


# v2.2.0: `lmstudio` missing here made a bare "hello" ship ~26k tokens and 400.
# v2.2.0: `moonshot` missing here made the cloud Architect plan blind on paid credits.
def test_supports_native_tools_covers_every_routable_provider():
    missing = [p for p in NATIVE_TOOL_PROVIDERS
               if not gw(provider=p, model="some-model").supports_native_tools]
    assert not missing, (
        "Providers routable by the gateway but absent from the "
        "supports_native_tools list: %s. Each one silently falls back to "
        "text-injecting ~20k tokens of tool schemas into EVERY prompt." % missing)


# The property lowercases before comparing; a capitalised provider from config
# must not fall through to the legacy text-tools branch.
def test_supports_native_tools_is_case_insensitive():
    assert gw(provider="MoonShot", model="kimi-k3").supports_native_tools
    assert gw(provider="LMStudio", model="qwen3").supports_native_tools


# The per-model `supports_tools` override is the manual escape hatch used when a
# specific model on a good provider has broken tool calling.
def test_supports_native_tools_per_model_override_wins():
    off = gw(provider="openai", model="broken-model",
             config={"model_overrides": {"broken-model": {"supports_tools": False}}})
    assert off.supports_native_tools is False

    on = gw(provider="some-new-provider", model="good-model",
            config={"model_overrides": {"good-model": {"supports_tools": True}}})
    assert on.supports_native_tools is True


# A genuinely unknown provider must fail CLOSED (text tools) rather than
# claiming a native-tools API that isn't there.
def test_supports_native_tools_false_for_unknown_provider():
    assert gw(provider="totally-made-up", model="x").supports_native_tools is False


# KNOWN BUG (unfixed as of writing): model_manager.primary_provider may be a
# SEGMENT name like "openrouter-frontier" (its own comment says so), and
# LLMProxy.provider returns that value verbatim. _call_llm does normalise
# `openrouter-*` → `openrouter`, but only AFTER _build_system_prompt has already
# run — so the system prompt for a segment provider is built with
# supports_native_tools == False and gets the text tool blob.
@known_bug("openrouter-* segment providers are normalised too late to help supports_native_tools")
def test_KNOWN_BUG_openrouter_segment_missing_from_supports_native_tools():
    assert gw(provider="openrouter-frontier", model="x-ai/grok-4").supports_native_tools


# ─────────────────────────────────────────────────────────────────────────────
# 2. _sanitize_tool_pairing
#
# Pure @staticmethod. Enforces the OpenAI tool-calling invariant: every
# assistant tool_call is answered by exactly one tool message. Lenient
# providers shrug; Moonshot hard-400s.
# ─────────────────────────────────────────────────────────────────────────────

SANITIZE = G._sanitize_tool_pairing
STUB = "[result unavailable — proceed with what you have]"


def test_sanitize_empty_input():
    assert SANITIZE([]) == []


# Strict providers 400 on an unanswered tool_call — the missing reply is what
# happens when a tool times out or the loop breaks mid-turn.
def test_sanitize_stubs_missing_tool_replies():
    out = SANITIZE([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "A"},
    ])
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "tool"]
    assert out[2]["content"] == "A"
    assert out[3]["tool_call_id"] == "b"
    assert out[3]["content"] == STUB


# A tool reply with no owning assistant message (history trimmed mid-block) is
# an instant 400 on Moonshot.
def test_sanitize_drops_orphan_tool_replies():
    out = SANITIZE([
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "ghost", "content": "Z"},
        {"role": "assistant", "content": "hello"},
    ])
    assert [m["role"] for m in out] == ["user", "assistant"]


# Two replies claiming the same tool_call_id: keep the first, drop the rest,
# and do NOT then also append a stub for it.
def test_sanitize_drops_duplicate_tool_call_ids():
    out = SANITIZE([
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "first"},
        {"role": "tool", "tool_call_id": "a", "content": "second"},
    ])
    assert len(out) == 2
    assert out[1]["content"] == "first"


# A reply whose id matches no tool_call is dropped, and the real call still
# gets its stub.
def test_sanitize_drops_unknown_tool_call_id_and_still_stubs():
    out = SANITIZE([
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "not-a-real-id", "content": "Q"},
    ])
    assert len(out) == 2
    assert out[1]["tool_call_id"] == "a"
    assert out[1]["content"] == STUB


# Sanitising must never reorder the conversation — models are extremely
# sensitive to system/user/assistant sequencing.
def test_sanitize_preserves_order_and_passes_plain_messages_through():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "A"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "u2"},
    ]
    out = SANITIZE(msgs)
    assert [m["role"] for m in out] == \
        ["system", "user", "assistant", "tool", "assistant", "user"]
    assert [m.get("content") for m in out] == ["s", "u1", None, "A", "done", "u2"]


# Multi-step ReAct turns produce several consecutive call/reply blocks; each is
# sanitised independently.
def test_sanitize_handles_multiple_tool_blocks():
    out = SANITIZE([
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "A"},
        {"role": "assistant", "tool_calls": [{"id": "b"}, {"id": "c"}]},
        {"role": "tool", "tool_call_id": "b", "content": "B"},
    ])
    assert [m.get("tool_call_id") for m in out] == [None, "a", None, "b", "c"]
    assert out[-1]["content"] == STUB


# Malformed tool_calls (no id) must not crash or generate a stub with id=None.
def test_sanitize_ignores_tool_calls_without_ids():
    out = SANITIZE([{"role": "assistant", "tool_calls": [{"function": {"name": "f"}}]}])
    assert len(out) == 1
    assert out[0]["role"] == "assistant"


# The caller passes self.history slices; mutating them in place would corrupt
# the live conversation.
def test_sanitize_does_not_mutate_the_input_list():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "A"},
        {"role": "tool", "tool_call_id": "a", "content": "dupe"},
    ]
    before = len(msgs)
    SANITIZE(msgs)
    assert len(msgs) == before
    assert msgs[2]["content"] == "dupe"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Coding-intent detection
#
# Mirrors the composite in _speak_logic: a strong verb alone, OR a weak verb
# AND a code-ish object, OR the /code command. A false positive fires the whole
# hybrid Architect/Planner/Builder pipeline (a paid cloud call) on small talk; a
# false negative means the hybrid coder the user configured never runs at all.
# ─────────────────────────────────────────────────────────────────────────────

def is_coding(text):
    """Exactly the `fresh_coding` expression from _speak_logic."""
    lower = text.lower()
    stripped = G._strip_pasted_output(lower)
    return bool(
        lower.startswith("/code")
        or G._CODING_STRONG_RE.search(stripped)
        or (G._CODING_VERB_RE.search(stripped) and G._CODE_CONTEXT_RE.search(stripped))
    )


# 2026-07-25 live incident: a support question about PowerShell versions spawned
# the cloud Architect. The pasted `$PSVersionTable` table supplied the verb —
# "Major  Minor  Build  Revision" — and the prose supplied the object, "my
# windows button". Neither signal came from anything the user meant as a task.
PASTED_TRANSCRIPTS_NOT_CODING = [
    ("why i right click on my windows button and seletc powershell and run the "
     "command this is whta I get.. Windows PowerShell\n"
     "Copyright (C) Microsoft Corporation. All rights reserved.\n\n"
     r"PS C:\Users\Chesley> $PSVersionTable.PSVersion" "\n\n"
     "Major  Minor  Build  Revision\n"
     "-----  -----  --------\n"
     "5      1      26100  8894"),
    # A prompt line carrying a real build/git command must not leak signals
    # either. re.I on _PASTED_PROMPT_RE is what makes these two pass, because
    # detection runs on an already-lowercased string.
    ("here's what I ran, any idea why it errors?\n"
     r"PS C:\Users\Chesley> npm run build --prefix ./app"),
    ("what does this mean\n"
     r"PS C:\dev> git add . ; git commit -m 'fix the api endpoint'"),
]


def test_pasted_console_output_does_not_trigger_coding():
    wrong = [t.splitlines()[0][:60] for t in PASTED_TRANSCRIPTS_NOT_CODING if is_coding(t)]
    assert not wrong, (
        "A pasted terminal transcript supplied the coding signals, spawning the "
        "paid cloud Architect on a support question: %s" % wrong)


# ...but a genuine coding request that HAPPENS to include pasted output must
# still be detected — stripping must not swallow the user's actual ask.
def test_real_coding_request_with_pasted_traceback_still_detected():
    assert is_coding(
        "fix this error in my python script\n"
        "Traceback (most recent call last):\n"
        '  File "app.py", line 3, in <module>\n'
        "ValueError: bad input")


# Same incident: the workspace silently became C:\Users\Chesley because
# %USERPROFILE%\.claude is a GLOBAL Claude Code config dir that satisfied the
# project-marker test. Every later prompt then told the agent to do its coding
# work in the user's home directory.
def test_home_and_shell_folders_are_never_project_roots():
    home = os.path.expanduser("~")
    gw_ = G.__new__(G)
    wrong = [p for p in (home,
                         os.path.join(home, "Desktop"),
                         os.path.join(home, "Downloads"))
             if gw_._looks_like_project_root(p)]
    assert not wrong, (
        "Home/shell folders accepted as project roots — a pasted shell prompt "
        "will hijack the active workspace: %s" % wrong)


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM-STATE HALLUCINATION GUARD
# 2026-07-25: asked to make PowerShell 7 the Windows default, the model replied
# "**7.6.4** is locked and loaded!" having called ZERO tools — and invented the
# version number (7.5.5 was installed). Desktop automation is this app's whole
# purpose, so a false "done" costs more here than anywhere else.
# ─────────────────────────────────────────────────────────────────────────────

PS_ASK = ("when i right click on my windows button and select PowerShell and run the "
          "command this is what I get. I want the latest powershell to be the windows "
          "default..\nWindows PowerShell\n"
          "Copyright (C) Microsoft Corporation. All rights reserved.\n\n"
          r"PS C:\Users\Chesley> $PSVersionTable.PSVersion" "\n\n"
          "Major  Minor  Build  Revision\n-----  -----  --------\n5      1      26100  8894")


def system_claim_flagged(reply, user_ask, backed_by_tool=False):
    """Mirrors the system-state branch of the ReAct loop."""
    rt = reply.lower()
    ask = G._strip_pasted_output(user_ask.lower())
    hedged = bool(G._NO_CLAIM_HEDGE_RE.search(rt)) or rt.rstrip().endswith('?')
    claimed = (bool(G._SYSTEM_CLAIM_RE.search(rt))
               or (bool(G._SYSTEM_TASK_RE.search(ask)) and not hedged))
    return claimed and not backed_by_tool and not hedged


def test_slang_completion_claim_with_no_tools_is_caught():
    # The verbatim reply from the incident. No regex will match "locked and
    # loaded" — layer 2 catches it via what the USER asked for instead.
    assert system_claim_flagged(
        "Hell yeah, brother! **7.6.4** is locked and loaded!\nNow your whole "
        "Windows shell is riding on the latest tech instead of that old 5.1 hardware.",
        PS_ASK)


def test_explicit_system_claim_with_no_tools_is_caught():
    assert system_claim_flagged("I've set the default profile to PowerShell 7.", PS_ASK)


def test_system_claim_backed_by_a_real_tool_call_is_not_flagged():
    assert not system_claim_flagged(
        "Done! Both Win+X shortcuts are now repinned to pwsh.", PS_ASK,
        backed_by_tool=True)


def test_asking_advising_or_declining_is_not_a_completion_claim():
    wrong = [r for r in (
        "To make PowerShell 7 the default, you'll need to open Terminal settings. "
        "Want me to do it?",
        "Should I change the Windows Terminal default profile for you?",
        "I can't change that setting without admin rights.",
        "Here's how the WinX menu works: it launches Windows Terminal, which opens "
        "whatever profile is set as default.",
    ) if system_claim_flagged(r, PS_ASK)]
    assert not wrong, "Hedged/questioning replies wrongly flagged: %s" % wrong


# ─────────────────────────────────────────────────────────────────────────────
# CTX METER / USAGE CAPTURE
# 2026-07-25: measured 2 real usage captures out of 4,677 logged calls — the
# cost log was writing "actual": false for essentially everything, and the deck's
# CTX meter was showing a chars/4 estimate of chat history (missing the system
# prompt, ~15k of tool schemas, and injected memories).
#
# Cause: every capture site gated on `not self._session_trace_sid.get()`, but
# _speak_logic assigns the main chat an "m-<uuid>" sid BEFORE any LLM call, so
# that test is False exactly when it needs to be True. is_main_chat already
# encodes the right rule.
# ─────────────────────────────────────────────────────────────────────────────

def test_main_chat_is_recognised_when_it_has_an_m_prefixed_sid():
    g = G.__new__(G)
    g._session_isolated = gateway_v3.contextvars.ContextVar("iso", default=False)
    g._session_trace_sid = gateway_v3.contextvars.ContextVar("sid", default=None)
    g._session_trace_sid.set("m-0ad0d09c")
    assert g.is_main_chat, (
        "The main chat carries an 'm-' sid; is_main_chat must still be True or "
        "usage capture, chat logging and the CTX meter all silently switch off.")
    # ...and the naive test that caused the bug must indeed be False, proving
    # these two are NOT interchangeable.
    assert not (not g._session_trace_sid.get())


def test_isolated_subagent_is_not_main_chat():
    g = G.__new__(G)
    g._session_isolated = gateway_v3.contextvars.ContextVar("iso", default=False)
    g._session_trace_sid = gateway_v3.contextvars.ContextVar("sid", default=None)
    g._session_isolated.set(True)
    g._session_trace_sid.set("planner")
    assert not g.is_main_chat


def test_no_usage_capture_site_uses_the_naive_sid_test():
    """The regression is textual: guards around _last_usage_final must not go
    back to `not self._session_trace_sid.get()`."""
    src = io.open(gateway_v3.__file__, encoding="utf-8").read().splitlines(True)
    bad = []
    for i, ln in enumerate(src):
        if "_session_trace_sid.get()" in ln and "_last_usage_final" in "".join(src[i:i + 3]):
            bad.append(i + 1)
    assert not bad, (
        "usage-capture guards regressed to the naive sid test at line(s) %s — "
        "_last_usage_final will never be written for the main chat" % bad)


# ─────────────────────────────────────────────────────────────────────────────
# PREFIX CACHING (Moonshot bills a cache HIT at 10% of a miss)
# The cache matches byte-for-byte from the start of the request, so the tool
# array must serialise identically every turn. Relevance filtering rebuilt it
# from the current message, which missed the cache on every single call.
# ─────────────────────────────────────────────────────────────────────────────

def _cache_gw(msg, provider="moonshot", model="kimi-k3", config=None):
    import contextvars
    x = G.__new__(G)
    x._session_isolated = contextvars.ContextVar("i", default=False)
    x._session_trace_sid = contextvars.ContextVar("s", default=None)
    x._session_is_coding = contextvars.ContextVar("c", default=False)
    x.llm = SimpleNamespace(provider=provider, model=model)
    x.core = SimpleNamespace(config=config or {"models": {}})
    x.tools = {n: {"description": "d" + n, "parameters": {}} for n in
               ["read_file", "write_file", "exec_shell", "find_tools", "list_dir",
                "web_search", "browser_navigate", "chrome_click", "generate_image",
                "memory_search", "edit_file"]}
    x.history = [{"role": "user", "content": msg}]
    x._ollama_discovered = []
    return x


def test_kimi_k3_has_pricing_and_a_cached_rate():
    p = gateway_v3.MODEL_PRICING.get("kimi-k3")
    assert p, "kimi-k3 missing from MODEL_PRICING — costs fall back to $1/$3 and under-report ~3-5x"
    assert p["input"] == 3.00 and p["output"] == 15.00
    assert p.get("cached_input") == 0.30, "cache-hit rate missing; hits would be billed as misses"


def test_cloud_tool_array_is_sorted_and_stable_across_messages():
    a = list(_cache_gw("read the config file and search the web")._get_active_tools())
    b = list(_cache_gw("generate an image of a cat")._get_active_tools())
    assert a == sorted(a), "tool array must be sorted — dict order is what gets serialised"
    assert a == b, (
        "tool array changed with the user's message, so the cached prefix misses "
        "on every turn. At 10x the token price that costs more than the tokens saved.")


def test_local_backends_are_also_cache_stable():
    """Measured 2026-07-25 on qwen3.6:27b via Ollama, ~8.9k-token prompt,
    identical total size in both conditions:
        stable prefix   0.87s prefill / 1.92s wall
        varying prefix  6.12s prefill / 7.30s wall  -> 74% slower
    llama.cpp reuses the KV cache for whatever prefix matches, so a tool array
    that changes per message forces a full re-prefill every turn."""
    for provider, model in (("ollama", "qwen3.6:27b"),
                            ("lmstudio", "qwen3.6-27b-mtp@q4_k_s")):
        a = list(_cache_gw("read the config and search the web",
                           provider=provider, model=model)._get_active_tools())
        b = list(_cache_gw("generate an image of a cat",
                           provider=provider, model=model)._get_active_tools())
        assert a, "%s returned no tools" % provider
        assert a == sorted(a), "%s tool array not sorted" % provider
        assert a == b, (
            "%s tool array changed with the user's message — that re-prefills "
            "the whole prompt through the model every turn (~5.4s on a 27B)"
            % provider)


def test_cache_stable_mode_does_not_widen_the_local_tool_set():
    """Stability must not come at the cost of the tighter set local models
    select better from — the _OLLAMA_* caps still apply."""
    n = len(_cache_gw("do something", provider="ollama",
                      model="qwen3.6:27b")._get_active_tools())
    assert n <= G._OLLAMA_MAX_TOOLS, (
        "local tool set (%d) exceeded _OLLAMA_MAX_TOOLS (%d)" % (n, G._OLLAMA_MAX_TOOLS))


def test_cached_tokens_are_billed_at_the_cached_rate():
    p = gateway_v3.MODEL_PRICING["kimi-k3"]
    tin, cached = 10_000, 9_000
    fresh_cost = (tin / 1e6) * p["input"]
    mixed_cost = ((tin - cached) / 1e6) * p["input"] + (cached / 1e6) * p["cached_input"]
    assert mixed_cost < fresh_cost / 4, (
        "a 90%% hit rate should cut input cost by roughly 5x; got %.5f vs %.5f"
        % (mixed_cost, fresh_cost))


# ─────────────────────────────────────────────────────────────────────────────
# NEURAL INDEXER SELF-TRIGGER LOOP
# 2026-07-25: "Synchronized 3 files" repeated every few minutes forever. The
# indexer watched db/neural_indexer_cache.json — the file it writes at the END
# of a scan — so finishing a scan changed an mtime it was watching and started
# the next one. logs/system_log.txt and logs/conversations/*.json did the same.
# Change-detection and the scan also disagreed about what to skip: the scan used
# `any(p in root for p in [...])`, a substring test that never excluded logs/.
# ─────────────────────────────────────────────────────────────────────────────

def test_indexer_never_watches_its_own_runtime_output():
    from skills.core.neural_indexer import NeuralIndexer
    root = os.path.dirname(os.path.abspath(gateway_v3.__file__))
    files = [f.lower() for f in NeuralIndexer._walk_source_files(NeuralIndexer, root)]
    assert files, "indexer found no source files at all"

    selftrigger = [f for f in files
                   if "neural_indexer_cache" in f
                   or f.endswith("system_log.txt")
                   or "hot_buffer.json" in f
                   or "current_session.json" in f]
    assert not selftrigger, (
        "indexer is watching files it writes itself — this re-triggers a scan "
        "forever: %s" % selftrigger[:5])

    runtime = [f for f in files
               if any(("%s%s%s" % (os.sep, d, os.sep)) in f
                      for d in ("logs", "db", "tmp", "scratch", "chroma_data",
                                "releases", "_archive", "messages"))]
    assert not runtime, "indexer walked runtime dirs: %s" % runtime[:5]


def test_indexer_change_detection_and_scan_use_the_same_filter():
    """They diverged once and the scan re-read files the mtime pass ignored."""
    from skills.core.neural_indexer import NeuralIndexer
    import inspect
    for fn in (NeuralIndexer._get_workspace_mtimes, NeuralIndexer._count_files,
               NeuralIndexer.scan_and_index):
        assert "_walk_source_files" in inspect.getsource(fn), (
            "%s no longer routes through _walk_source_files — the two filters "
            "can drift apart again" % fn.__name__)


def test_ctx_meter_reads_the_effective_limit_not_the_advertised_window():
    """2026-07-25: background compaction fired at 111,174 chars while the deck
    showed "CTX 5% - 48K/1049K". Both were correct; the meter was dividing by
    kimi-k3's advertised 1,048,576-token window instead of the
    max_billable_context cap that actually governs trimming. 48K against the
    real 32,768 limit is 146%, not 5%."""
    gw_ = _cache_gw("hi", provider="moonshot", model="kimi-k3")
    gw_.core = SimpleNamespace(config={"models": {}})
    assert gw_._get_effective_context_limit() == 32768

    gw_.core = SimpleNamespace(config={"models": {"max_billable_context": 131072}})
    assert gw_._get_effective_context_limit() == 131072

    # Local backends bill nothing, so they keep the whole window.
    loc = _cache_gw("hi", provider="ollama", model="qwen3.6:27b")
    loc.core = SimpleNamespace(config={"models": {"context_window": 64000}})
    assert loc._get_effective_context_limit() == 64000

    src = io.open(gateway_v3.__file__, encoding="utf-8").read()
    assert "_get_effective_context_limit" in src


def test_unrelated_turns_never_trip_the_system_guard():
    wrong = [r for r, a in (
        ("I've updated the retry logic in that function.", "fix the bug in gateway_v3.py"),
        ("It's sunny and about 84 degrees today.", "what's the weather like today"),
        ("The deck's settings tab lets you pick a model.", "what's the weather like today"),
    ) if system_claim_flagged(r, a)]
    assert not wrong, "Non-system turns wrongly flagged: %s" % wrong


# v2.2.0 false positive: this exact sentence launched Senior Coder mode plus a
# paid cloud planning call, because bare "changed" counted as a coding verb.
NOT_CODING = [
    "Nice, it worked!! Changed a setting and testing again.",
    "review my resume",                        # v2.2.0 regression suite case
    "optimize my morning routine",             # v2.2.0 regression suite case
    "analyze the stock market for me",
    "add milk and eggs to the shopping list",
    "can you write a poem about the ocean",
    "thanks, that fixed my mood",
    "how was your day?",
    "what's the weather like",
]

# v2.2.0 false negative: "scan this codebase..." did not trigger hybrid at all,
# because the gate tested for the literal string "scan the codebase".
CODING = [
    "scan this codebase and offer improvements",
    "audit the codebase for security issues",
    "tackle the critical issues first",
    "fix the bug in web_deck.py",
    "add a button to the deck",
    "review the `speak` function",
    "refactor this",          # strong verb, stands alone
    "debug it",               # strong verb, stands alone
    "implement dark mode",    # strong verb, stands alone
]


def test_casual_chat_is_not_coding():
    wrong = [t for t in NOT_CODING if is_coding(t)]
    assert not wrong, "Casual chat wrongly routed to the coding pipeline: %s" % wrong


def test_real_coding_requests_are_coding():
    wrong = [t for t in CODING if not is_coding(t)]
    assert not wrong, "Real coding work missed by intent detection: %s" % wrong


# /code is the manual override and must win regardless of wording.
def test_slash_code_always_forces_coding():
    assert is_coding("/code make it prettier")
    assert is_coding("/CODE MAKE IT PRETTIER".lower())


# Continuation imperatives carry no verb+object of their own but ARE the coding
# task when they follow one. Only honoured inside the armed follow-up window.
def test_followup_imperatives_are_recognised():
    followups = [
        "tackle the critical issues first",
        "go ahead with #2",
        "do the rest",
        "knock them out",
        "start with number 3",
        "start phase 1",
        "next item",
        "proceed",
        "continue",
    ]
    wrong = [t for t in followups if not G._CODING_FOLLOWUP_RE.search(t.lower())]
    assert not wrong, "Coding follow-ups not recognised: %s" % wrong


# The follow-up window is armed for several turns after coding work — ordinary
# chat during that window must not re-enter the pipeline.
def test_casual_chat_is_not_a_coding_followup():
    casual = ["how's the weather", "thanks!", "tell me a joke",
              "what do you think about jazz", "who won the game"]
    wrong = [t for t in casual if G._CODING_FOLLOWUP_RE.search(t.lower())]
    assert not wrong, "Casual chat matched the coding follow-up regex: %s" % wrong


# v2.2.0: this was a bare `"scan the codebase" in text` literal, so "scan THIS
# codebase" — the exact phrasing the user typed — slipped through.
def test_scan_codebase_trigger_is_determiner_agnostic():
    for text in ["scan this codebase", "scan the codebase", "scan my codebase",
                 "review our repository", "map out this repo",
                 "audit your project", "examine the source"]:
        assert G._SCAN_CODEBASE_RE.search(text.lower()), text
    for text in ["scan my inbox", "review my resume", "scan the room"]:
        assert not G._SCAN_CODEBASE_RE.search(text.lower()), text


# ─────────────────────────────────────────────────────────────────────────────
# 4. _get_context_window_for_model  (failure class (c))
#
# Precedence: per-model override > global config > live provider-reported >
# name rules > provider default. LM Studio is special — its discovered window
# is a HARD CAP, not a fallback.
#
# Note: the cloud-refresh path calls asyncio.get_running_loop() and already
# catches RuntimeError for exactly this situation ("no running loop (e.g. unit
# test)"), which is why these tests need no event loop.
# ─────────────────────────────────────────────────────────────────────────────

# v2.2.0: the deck showed kimi-k3 capped at 32,768 while Moonshot's own /models
# reports context_length 1,048,576 — history was trimmed to 3% of the window.
def test_kimi_k3_resolves_to_one_million_not_32k():
    assert gw("moonshot", "kimi-k3")._get_context_window_for_model() == 1048576


def test_other_kimi_models_resolve_to_256k():
    assert gw("moonshot", "kimi-k2-0711-preview")._get_context_window_for_model() == 262144
    assert gw("moonshot", "moonshot-v1-8k")._get_context_window_for_model() == 262144


# v2.2.0: LM Studio loads a model with a FIXED window and 400s anything larger
# — there is no per-request num_ctx like Ollama. A configured 128k against an
# 8k load is a guaranteed hard failure, so the discovered value must CLAMP.
def test_lmstudio_clamps_configured_window_to_the_loaded_window():
    g = gw("lmstudio", "qwen3-30b",
           {"models": {"context_window": 131072}},
           lmstudio_manager=FakeContextManager(8192))
    assert g._get_context_window_for_model() == 8192


def test_lmstudio_uses_discovered_window_when_nothing_configured():
    g = gw("lmstudio", "qwen3-30b", {}, lmstudio_manager=FakeContextManager(16384))
    assert g._get_context_window_for_model() == 16384


# A configured value BELOW the loaded window is legitimate (deliberate trim).
def test_lmstudio_keeps_a_configured_window_smaller_than_the_loaded_one():
    g = gw("lmstudio", "qwen3-30b",
           {"models": {"context_window": 4096}},
           lmstudio_manager=FakeContextManager(16384))
    assert g._get_context_window_for_model() == 4096


# Server warming up / older build with no /api/v0/models: stay conservative,
# because overshooting is a hard 400 rather than a soft truncation.
def test_lmstudio_falls_back_conservatively_without_a_manager():
    assert gw("lmstudio", "qwen3-30b", {})._get_context_window_for_model() == 8192


def test_per_model_override_beats_global_config():
    g = gw("moonshot", "kimi-k3", {
        "models": {"context_window": 65536},
        "model_overrides": {"kimi-k3": {"context_window": 200000}},
    })
    assert g._get_context_window_for_model() == 200000


def test_global_config_beats_name_based_detection():
    g = gw("moonshot", "kimi-k3", {"models": {"context_window": 65536}})
    assert g._get_context_window_for_model() == 65536


# Ollama's Modelfile default is frequently 2k-8k, which silently truncates the
# system prompt — hence asking the manager for the model's real max.
def test_ollama_uses_the_managers_reported_window():
    g = gw("ollama", "qwen3:8b", {}, ollama_manager=FakeContextManager(40960))
    assert g._get_context_window_for_model() == 40960
    assert gw("ollama", "qwen3:8b", {})._get_context_window_for_model() == 32768


# The cloud path kicks off a background /models refresh; with no running loop it
# must swallow the RuntimeError and return the static fallback, not explode.
def test_cloud_context_lookup_survives_having_no_event_loop():
    assert gw("deepseek", "deepseek-chat")._get_context_window_for_model() == 64000
    assert gw("anthropic", "claude-opus-4-6")._get_context_window_for_model() == 200000
    assert gw("nosuchprovider", "nosuchmodel")._get_context_window_for_model() == 32768


# ─────────────────────────────────────────────────────────────────────────────
# 5. config_loader.deep_merge
#
# config.yaml (tracked template) + config.local.yaml (live overlay). The hard-won
# rule: `model_overrides` and `aliases` are OVERLAY-AUTHORITATIVE. Deep-merging
# them means a user can never DELETE an entry that also exists in the tracked
# template — the merge re-injects it on every load and the deletion "comes back".
# ─────────────────────────────────────────────────────────────────────────────

def test_deep_merge_merges_nested_dicts_with_overlay_winning():
    merged = deep_merge({"a": {"x": 1, "y": 2}, "b": 3}, {"a": {"y": 9}, "c": 4})
    assert merged == {"a": {"x": 1, "y": 9}, "b": 3, "c": 4}


def test_deep_merge_does_not_mutate_the_base():
    base = {"a": {"x": 1}}
    deep_merge(base, {"a": {"x": 99}, "z": 1})
    assert base == {"a": {"x": 1}}


# THE BUG: delete a per-model override in the deck, reload, and it was back —
# because config.yaml still had it and the deep merge kept resurrecting it.
def test_deep_merge_model_overrides_deletions_stick():
    base = {"model_overrides": {"kept": {"context_window": 1},
                                "deleted": {"context_window": 2}}}
    overlay = {"model_overrides": {"kept": {"context_window": 999}}}
    assert deep_merge(base, overlay) == {"model_overrides": {"kept": {"context_window": 999}}}


# Same rule for command aliases — a deleted alias must not come back.
def test_deep_merge_aliases_deletions_stick():
    merged = deep_merge({"aliases": {"a": "x", "b": "y"}}, {"aliases": {"a": "z"}})
    assert merged == {"aliases": {"a": "z"}}


# Clearing the collection entirely must also stick.
def test_deep_merge_empty_authoritative_overlay_clears_the_base():
    base = {"model_overrides": {"m1": {"ctx": 1}}}
    assert deep_merge(base, {"model_overrides": {}}) == {"model_overrides": {}}


# Authoritative ONLY when the overlay actually has the key — otherwise the base
# still provides it normally (a fresh install with no overlay must keep them).
def test_deep_merge_authoritative_keys_pass_through_when_overlay_lacks_them():
    base = {"model_overrides": {"m1": {"ctx": 1}}, "aliases": {"a": "x"}}
    merged = deep_merge(base, {"models": {"temperature": 0.7}})
    assert merged["model_overrides"] == {"m1": {"ctx": 1}}
    assert merged["aliases"] == {"a": "x"}


# A missing / empty / non-dict config file must not wipe the other side.
def test_deep_merge_handles_none_and_scalars():
    assert deep_merge({"a": 1}, None) == {"a": 1}       # overlay file missing
    assert deep_merge({"a": 1}, {}) == {"a": 1}         # overlay file empty
    assert deep_merge({}, {"a": 1}) == {"a": 1}         # no template
    assert deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}   # dict → scalar


# ─────────────────────────────────────────────────────────────────────────────
# 6. Hallucination detectors  (failure class (b))
#
# These bind to the class constants `_BROWSER_CLAIM_RE` / `_FILE_CLAIM_RE` on
# GalacticGateway, which is what you want: the tests then exercise the REAL
# patterns. They were inline in _speak_logic until recently, so the verbatim
# copies below remain as a fallback in case that hoist is ever reverted.
#
# ⚠️ IF THE FALLBACK IS EVER IN USE, THESE COPIES MUST BE KEPT IN SYNC WITH
# gateway_v3.py BY HAND. test_hallucination_patterns_are_in_sync_with_gateway
# enforces that automatically: it asserts every fragment below still appears
# verbatim in gateway_v3.py's source, so editing the regex there without
# updating it here fails the suite instead of silently testing a stale copy.
# While the class constants exist, that test is a no-op.
# ─────────────────────────────────────────────────────────────────────────────

_BROWSER_CLAIM_FRAGMENTS = [
    r"""\bi(?:'ve| have| am|'m| just| now| already| then)*\s+""",
    r"""(?:clicked|clicking|typed|typing|searched|searching|submitted|submitting|entered|entering)\b""",
    r"""|(?:^|(?<=[.!?:])\s|(?<=\n))(?:now\s+|just\s+)?""",
    r"""(?:clicked|clicking|typed|typing|submitted|submitting|entered|entering)\s+""",
    r"""(?:the|on|in|into|my|your|it|that|[\"'])""",
]

_FILE_CLAIM_FRAGMENTS = [
    r"""\bi(?:'ve| have)(?: just| now| already| also)?\s+""",
    r"""(?:written|saved|updated|added|created|appended|patched|deleted|removed|moved|renamed)\b""",
    r"""[^.!?\n]{0,80}?""",
    r"""(?:\bfiles?\b|\bdisk\b|\bconfig(?:uration)?\b|\bmemor(?:y|ies)\b|[\w\-\\/]+\.[a-z0-9]{1,5}\b)""",
    r"""|\bsuccessfully\s+(?:written|saved|updated|created|deleted|patched)\b""",
    r"""|\bfiles?\s+ha(?:s|ve)\s+been\s+(?:updated|written|created|saved|deleted|modified)\b""",
    r"""|\bdone[.!]\s+i(?:'ve| have)\s+(?:made|applied|finished|completed|written|updated|fixed)\b""",
]

BROWSER_CLAIM_RE = getattr(G, "_BROWSER_CLAIM_RE", None)
FILE_CLAIM_RE = getattr(G, "_FILE_CLAIM_RE", None)
USING_LOCAL_REGEX_COPY = BROWSER_CLAIM_RE is None or FILE_CLAIM_RE is None
if BROWSER_CLAIM_RE is None:
    BROWSER_CLAIM_RE = re.compile("".join(_BROWSER_CLAIM_FRAGMENTS))
if FILE_CLAIM_RE is None:
    FILE_CLAIM_RE = re.compile("".join(_FILE_CLAIM_FRAGMENTS))


def visible_lower(text):
    """The exact preprocessing the guard applies before matching: strip <think>
    blocks (closed and unterminated), then lowercase. Reasoning ABOUT an action
    is not a claim of having performed it."""
    v = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    v = re.sub(r'<think>.*\Z', '', v, flags=re.DOTALL)
    return v.lower()


# v2.2.0, the incident that triggered the rewrite: Qwen was explaining that
# reasoning models pause "before they start typing" and got hit with
# "⚠️ HALLUCINATION DETECTED" mid-conversation, with no browser task in sight.
# It then spent a think-block defending itself — correctly.
BROWSER_INNOCENT = [
    "Most models think for a while before they actually start typing out the answer.",
    "Once she starts typing, the form validates each field.",
    "I'm researching the best approach right now.",     # "re-SEARCHING"
    "We're prototyping a new layout.",                  # "proto-TYPING"
    "The heading is centered on the page.",             # "c-ENTERED"
    "I found the issue in the config.",
    "You could try clicking the login button yourself.",  # not a first-person claim
    "I will click the button next.",                    # future intent, not a claim
]

BROWSER_GUILTY = [
    "I clicked the login button.",
    "I've typed the password into the field.",
    "Now clicking the 'Submit' button.",
    "I am typing the search query.",
    "I just entered the credentials.",
    "I have searched for the product.",
]


def test_browser_claim_ignores_innocent_text():
    wrong = [t for t in BROWSER_INNOCENT if BROWSER_CLAIM_RE.search(visible_lower(t))]
    assert not wrong, "Innocent text flagged as a phantom browser action: %s" % wrong


def test_browser_claim_still_catches_real_claims():
    wrong = [t for t in BROWSER_GUILTY if not BROWSER_CLAIM_RE.search(visible_lower(t))]
    assert not wrong, "Real phantom browser claims no longer caught: %s" % wrong


# Reasoning inside <think> is deliberation, not a claim — and it never reaches
# the user. Covers both a closed block and an unterminated one (truncated stream).
def test_think_blocks_are_stripped_before_matching():
    closed = "<think>I clicked the login button already</think>Here is what I think."
    unterminated = "<think>Now clicking the 'Submit' button and then typing the password"
    assert not BROWSER_CLAIM_RE.search(visible_lower(closed))
    assert not BROWSER_CLAIM_RE.search(visible_lower(unterminated))
    assert not FILE_CLAIM_RE.search(
        visible_lower("<think>I've updated SOUL.md with the new persona</think>What next?"))


# v2.2.0: "I've created a table below" tripped the file guard. A past-tense
# claim now has to sit near a file-ish object.
FILE_INNOCENT = [
    "I've created a table below to compare them.",
    "I've added a few thoughts on that.",
    "I'll update SOUL.md next.",                 # future intent
    "You should update config.yaml yourself.",   # not a first-person claim
    "I found the issue.",
]

FILE_GUILTY = [
    "I've updated SOUL.md with your new persona.",
    "I have written the changes to disk.",
    "I've patched gateway_v3.py for you.",
    "I've saved that to memory.",
    "Successfully saved.",
    "The file has been updated.",
    "Done. I've applied the fix.",
]


def test_file_claim_ignores_innocent_text():
    wrong = [t for t in FILE_INNOCENT if FILE_CLAIM_RE.search(visible_lower(t))]
    assert not wrong, "Innocent text flagged as a phantom file write: %s" % wrong


def test_file_claim_still_catches_real_claims():
    wrong = [t for t in FILE_GUILTY if not FILE_CLAIM_RE.search(visible_lower(t))]
    assert not wrong, "Real phantom file claims no longer caught: %s" % wrong


# Guards the fallback copies above. Only meaningful while gateway_v3 keeps the
# patterns inline; once _BROWSER_CLAIM_RE / _FILE_CLAIM_RE exist as class
# constants the tests above bind to the real objects and this becomes a no-op.
def test_hallucination_patterns_are_in_sync_with_gateway():
    if not USING_LOCAL_REGEX_COPY:
        return  # binding directly to the class constants — nothing to sync
    with open(gateway_v3.__file__, "r", encoding="utf-8") as f:
        source = f.read()
    stale = [frag for frag in _BROWSER_CLAIM_FRAGMENTS + _FILE_CLAIM_FRAGMENTS
             if frag not in source]
    assert not stale, (
        "gateway_v3.py's hallucination regexes changed but the copies in "
        "test_regressions.py did not. Missing fragments: %s" % stale)


# ─────────────────────────────────────────────────────────────────────────────
# 7. _get_tool_timeout
#
# With require_approval on, the gated write tools block INSIDE the tool waiting
# on a human Approve/Reject click — and that human wait is wrapped by this same
# dispatch timeout.
# ─────────────────────────────────────────────────────────────────────────────

# v2.2.0: write_file's base timeout is 10s, so every gated write died 10 seconds
# in — long before anyone could click Approve. It surfaced as "write_file
# raised: Timeout (took longer than 10s)", which the model then misread as
# "file too large" and thrashed on retries.
# Iterates the real tuple rather than a hardcoded list, so a newly gated tool
# is covered automatically the day it is added.
def test_every_gated_tool_gets_headroom_for_the_human_to_click_approve():
    g = gw(config={"models": {"require_approval": True}})   # default approval_timeout 300
    starved = [t for t in G._APPROVAL_GATED_TOOLS if g._get_tool_timeout(t) < 330]
    assert not starved, (
        "Approval-gated tools whose dispatch timeout is shorter than the "
        "approval window — the clock kills them before the human can click "
        "Approve: %s" % starved)
    assert gw(config={})._get_tool_timeout("write_file") == 10  # base, unchanged


# The file-mutation tools are the ones the 10s bug actually killed; dropping any
# of them from the gate tuple brings it straight back.
def test_file_mutation_tools_are_still_approval_gated():
    for tool in ("write_file", "edit_file", "replace_function"):
        assert tool in G._APPROVAL_GATED_TOOLS, tool


def test_custom_approval_timeout_is_respected():
    g = gw(config={"models": {"require_approval": True, "approval_timeout": 60}})
    assert g._get_tool_timeout("write_file") == 90


# Only the approval-gated tools get headroom; everything else keeps its budget.
# (Pick examples that are NOT in _APPROVAL_GATED_TOOLS — the tuple has grown to
# cover code execution too, so exec_shell/execute_python are gated now.)
def test_non_gated_tools_are_unaffected_by_the_approval_gate():
    g = gw(config={"models": {"require_approval": True}})
    for tool, budget in (("read_file", 10), ("web_search", 15), ("web_fetch", 30)):
        assert tool not in G._APPROVAL_GATED_TOOLS, tool
        assert g._get_tool_timeout(tool) == budget, tool


def test_approval_off_leaves_timeouts_untouched():
    g = gw(config={"models": {"require_approval": False}})
    assert g._get_tool_timeout("write_file") == 10


# The documented precedence is config override > built-in default > 60s, and a
# config override must survive the approval bump when it is already larger.
def test_config_override_beats_the_builtin_default():
    assert gw(config={"tool_timeouts": {"write_file": 999}})._get_tool_timeout("write_file") == 999
    both = gw(config={"tool_timeouts": {"write_file": 999},
                      "models": {"require_approval": True}})
    assert both._get_tool_timeout("write_file") == 999


def test_unknown_tool_falls_back_to_sixty_seconds():
    assert gw(config={})._get_tool_timeout("some_brand_new_tool") == 60


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner — `python test_regressions.py` with no pytest installed.
# ─────────────────────────────────────────────────────────────────────────────

def _main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed = failed = xfailed = xpassed = 0
    failures = []
    for name, fn in tests:
        known = getattr(fn, "__known_bug__", None)
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001
            if known:
                xfailed += 1
                print("XFAIL %s\n        known bug: %s" % (name, known))
            else:
                failed += 1
                failures.append((name, exc))
                print("FAIL  %s\n        %s: %s" % (name, type(exc).__name__, exc))
        else:
            if known:
                xpassed += 1
                failures.append((name, "XPASS: known bug appears FIXED — remove the "
                                       "known_bug() marker and fold this case in"))
                print("XPASS %s  <-- bug fixed? remove the known_bug() marker" % name)
            else:
                passed += 1
                print("ok    %s" % name)
    print("\n%d passed, %d failed, %d xfailed, %d xpassed" %
          (passed, failed, xfailed, xpassed))
    return 1 if (failed or xpassed) else 0


if __name__ == "__main__":
    sys.exit(_main())
