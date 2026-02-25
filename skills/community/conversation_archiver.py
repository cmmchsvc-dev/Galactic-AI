from __future__ import annotations

import asyncio
import json
import threading
import types
import uuid
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from skills.base import GalacticSkill


@dataclass
class _HotBuffer:
    max_chars: int
    messages: List[Dict[str, Any]]

    @property
    def total_chars(self) -> int:
        return sum(len(str(m.get('content', ''))) for m in self.messages)


class ConversationArchiverSkill(GalacticSkill):
    """Forever conversation archive + rolling hot buffer.

    Writes to:
      - logs/conversations/YYYY-MM/session_<session_id>.jsonl
      - logs/conversations/hot_buffer.json

    Fixes restart timing issues by retrying patch install until core.gateway exists.

    NOTE:
      This skill used to rely on an asyncio task started in async on_load().
      Some runtimes (including Control Deck startup paths) may load the skill
      without awaiting on_load(), which means the patch loop never starts and
      patched_gateway_log stays false.

      To make this bulletproof, we start a small daemon thread in __init__ that
      keeps retrying the patch until it succeeds.
    """

    skill_name = 'conversation_archiver'
    version = '1.0.2'
    author = 'Chesley + Byte'
    description = 'Archives full chat transcripts to logs/conversations and keeps a rolling hot buffer (robust patch that survives restarts).'
    category = 'memory'
    icon = '🗂️'

    def __init__(self, core):
        super().__init__(core)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Config
        self.max_chars = 100_000

        # Paths
        logs_dir = (core.config.get('paths', {}) or {}).get('logs', './logs')
        self.base_dir = (Path(logs_dir).resolve() / 'conversations')
        self.base_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        self.session_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.session_month = now.strftime('%Y-%m')
        self.session_dir = self.base_dir / self.session_month
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.session_dir / f"session_{self.session_id}.jsonl"

        self.hot_path = self.base_dir / 'hot_buffer.json'
        self.session_info_path = self.base_dir / 'current_session.json'

        self.hot = self._load_hot_buffer()

        # Patch state
        self._orig_log_chat = None
        self._patched = False
        self._last_patch_error = ''

        # Always write session info immediately
        self._write_current_session_info()

        # Start patch loop in a daemon thread (works even if on_load isn't awaited)
        self._patch_thread = threading.Thread(
            target=self._ensure_patch_loop_thread,
            name='conversation_archiver_patch_loop',
            daemon=True,
        )
        self._patch_thread.start()

    async def on_load(self):
        # Keep for compatibility with loaders that DO call/await on_load.
        # The real work is already started in __init__.
        return

    async def on_unload(self):
        # Stop thread
        try:
            self._stop_event.set()
        except Exception:
            pass

        # Unpatch gateway
        gw = getattr(self.core, 'gateway', None)
        if gw and getattr(gw, '_conversation_archiver_patched', False) and self._orig_log_chat:
            try:
                gw._log_chat = self._orig_log_chat
                setattr(gw, '_conversation_archiver_patched', False)
            except Exception:
                pass

    def get_tools(self) -> dict:
        return {
            'conversation_get_hot': {
                'description': 'Get the most recent messages from the rolling hot buffer (last ~100k chars).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'limit': {'type': 'integer', 'description': 'Max messages to return (default 50).'}
                    },
                },
                'fn': self.tool_conversation_get_hot,
            },
            'conversation_search': {
                'description': 'Search archived conversations (hot buffer, current session, or all archives) for a text query.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': 'Search string (case-insensitive).'},
                        'limit': {'type': 'integer', 'description': 'Max matches to return (default 10).'},
                        'scope': {'type': 'string', 'description': 'hot | session | all (default all).'},
                    },
                    'required': ['query'],
                },
                'fn': self.tool_conversation_search,
            },
            'conversation_current_session': {
                'description': 'Return metadata about the current live session archive file.',
                'parameters': {'type': 'object', 'properties': {}},
                'fn': self.tool_conversation_current_session,
            },
        }

    def _ensure_patch_loop_thread(self):
        # Quick backoff sequence, then slow retry forever.
        delays = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 5.0, 5.0]
        for d in delays:
            if self._stop_event.is_set():
                return
            if d:
                time.sleep(d)
            if self._install_patch():
                return

        while not self._stop_event.is_set() and not self._patched:
            time.sleep(10)
            self._install_patch()

    def _install_patch(self) -> bool:
        gw = getattr(self.core, 'gateway', None)
        if not gw or not hasattr(gw, '_log_chat'):
            self._last_patch_error = 'core.gateway missing or has no _log_chat yet'
            return False

        if getattr(gw, '_conversation_archiver_patched', False):
            self._patched = True
            self._last_patch_error = ''
            return True

        try:
            self._orig_log_chat = gw._log_chat
            orig = self._orig_log_chat

            def patched(self_gateway, role, content, source='web'):
                try:
                    # orig is already a bound method
                    orig(role, content, source=source)
                finally:
                    try:
                        self.record(role=role, content=content, source=source)
                    except Exception:
                        pass

            gw._log_chat = types.MethodType(patched, gw)
            setattr(gw, '_conversation_archiver_patched', True)
            self._patched = True
            self._last_patch_error = ''
            return True
        except Exception as e:
            self._patched = False
            self._last_patch_error = f"patch failed: {type(e).__name__}: {e}"
            return False

    def record(self, role: str, content: str, source: str = 'web'):
        ts = datetime.now().isoformat()
        entry = {
            'ts': ts,
            'role': role,
            'content': content,
            'source': source,
            'session_id': self.session_id,
        }
        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            with open(self.session_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')

            self.hot.messages.append(entry)
            self._trim_hot_buffer_in_place()
            self._save_hot_buffer()

    def _load_hot_buffer(self) -> _HotBuffer:
        try:
            if self.hot_path.exists():
                data = json.loads(self.hot_path.read_text(encoding='utf-8', errors='replace'))
                msgs = data.get('messages', [])
                maxc = int(data.get('max_chars', self.max_chars))
                if isinstance(msgs, list):
                    return _HotBuffer(max_chars=maxc, messages=msgs)
        except Exception:
            pass
        return _HotBuffer(max_chars=self.max_chars, messages=[])

    def _trim_hot_buffer_in_place(self):
        maxc = int(self.hot.max_chars or self.max_chars)
        while self.hot.messages and sum(len(str(m.get('content', ''))) for m in self.hot.messages) > maxc:
            self.hot.messages.pop(0)

    def _save_hot_buffer(self):
        payload = {
            'last_updated': datetime.now().isoformat(),
            'max_chars': int(self.hot.max_chars or self.max_chars),
            'total_chars': self.hot.total_chars,
            'messages': self.hot.messages,
        }
        tmp = self.hot_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.hot_path)

    def _write_current_session_info(self):
        info = {
            'session_id': self.session_id,
            'created': datetime.now().isoformat(),
            'session_file': str(self.session_file),
            'hot_buffer': str(self.hot_path),
        }
        tmp = self.session_info_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.session_info_path)

    async def tool_conversation_get_hot(self, args: dict):
        limit = int(args.get('limit', 50) or 50)
        limit = max(1, min(500, limit))
        with self._lock:
            msgs = list(self.hot.messages)[-limit:]
        return {
            'hot_buffer': str(self.hot_path),
            'max_chars': self.hot.max_chars,
            'total_chars': self.hot.total_chars,
            'message_count': len(self.hot.messages),
            'messages': msgs,
        }

    async def tool_conversation_current_session(self, args: dict):
        return {
            'session_id': self.session_id,
            'session_file': str(self.session_file),
            'month_dir': str(self.session_dir),
            'patched_gateway_log': bool(self._patched),
            'last_patch_error': self._last_patch_error,
        }

    async def tool_conversation_search(self, args: dict):
        query = (args.get('query') or '').strip()
        if not query:
            return {'error': 'query is required'}
        limit = int(args.get('limit', 10) or 10)
        limit = max(1, min(50, limit))
        scope = (args.get('scope') or 'all').strip().lower()
        if scope not in {'hot', 'session', 'all'}:
            scope = 'all'

        q = query.lower()
        matches: List[Dict[str, Any]] = []

        def _check_entry(e: Dict[str, Any], where: str, path: str):
            nonlocal matches
            txt = str(e.get('content', ''))
            if q in txt.lower():
                idx = txt.lower().find(q)
                start = max(0, idx - 160)
                end = min(len(txt), idx + len(query) + 160)
                snippet = txt[start:end]
                matches.append({
                    'where': where,
                    'path': path,
                    'ts': e.get('ts'),
                    'role': e.get('role'),
                    'source': e.get('source'),
                    'snippet': snippet,
                })

        with self._lock:
            if scope in {'hot', 'all'}:
                for e in reversed(self.hot.messages):
                    _check_entry(e, 'hot', str(self.hot_path))
                    if len(matches) >= limit:
                        return {'query': query, 'scope': scope, 'matches': matches[:limit]}

        if scope in {'session', 'all'}:
            if self.session_file.exists():
                try:
                    lines = self.session_file.read_text(encoding='utf-8', errors='replace').splitlines()
                    for line in reversed(lines):
                        try:
                            e = json.loads(line)
                        except Exception:
                            continue
                        _check_entry(e, 'session', str(self.session_file))
                        if len(matches) >= limit:
                            return {'query': query, 'scope': scope, 'matches': matches[:limit]}
                except Exception:
                    pass

        if scope == 'all':
            try:
                files = sorted(self.base_dir.glob('*/*session_*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
                for fp in files:
                    if fp == self.session_file:
                        continue
                    try:
                        lines = fp.read_text(encoding='utf-8', errors='replace').splitlines()
                    except Exception:
                        continue
                    for line in reversed(lines):
                        try:
                            e = json.loads(line)
                        except Exception:
                            continue
                        _check_entry(e, 'archive', str(fp))
                        if len(matches) >= limit:
                            return {'query': query, 'scope': scope, 'matches': matches[:limit]}
            except Exception:
                pass

        return {'query': query, 'scope': scope, 'matches': matches[:limit]}
