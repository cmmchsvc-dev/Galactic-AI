import asyncio
import asyncio.subprocess
import json
import hashlib
import time
import os
import secrets
from aiohttp import web
import jinja2

class GalacticWebDeck:
    def __init__(self, core):
        self.core = core
        self.config = core.config.get('web', {})
        self.port = self.config.get('port', 17789)  # matches config.yaml, CLI, and desktop shell
        self.host = self.config.get('host', '127.0.0.1')
        self.password_hash = self.config.get('password_hash')
        self.remote_access = self.config.get('remote_access', False)
        self.jwt_secret = self.config.get('jwt_secret', '')
        self.cert_fingerprint = ''

        # Remote access: override host to 0.0.0.0, set up TLS & middleware
        if self.remote_access:
            self.host = '0.0.0.0'
            if not self.jwt_secret:
                from remote_access import generate_api_secret
                self.jwt_secret = generate_api_secret()
                cfg = core.config
                if 'web' not in cfg:
                    cfg['web'] = {}
                cfg['web']['jwt_secret'] = self.jwt_secret
                self._save_config(cfg)

        # Build app with middleware
        middlewares = []
        if self.remote_access and self.password_hash:
            from remote_access import create_auth_middleware, RateLimiter, create_cors_middleware
            rate_limit = self.config.get('rate_limit', 60)
            self.rate_limiter = RateLimiter(general_limit=rate_limit)
            middlewares.append(create_auth_middleware(self.password_hash, self.jwt_secret, self.rate_limiter))
            allowed_origins = self.config.get('allowed_origins', [])
            if allowed_origins:
                middlewares.append(create_cors_middleware(allowed_origins))

        self.app = web.Application(middlewares=middlewares, client_max_size=1024 * 1024 * 100)
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_post('/login', self.handle_login)
        self.app.router.add_post('/api/setup', self.handle_setup)
        self.app.router.add_get('/api/check_setup', self.handle_check_setup)
        self.app.router.add_get('/stream', self.handle_stream)
        self.app.router.add_get('/api/files', self.handle_list_files)
        self.app.router.add_get('/api/models', self.handle_get_models)
        self.app.router.add_get('/api/file', self.handle_get_file)
        self.app.router.add_post('/api/file', self.handle_save_file)
        # Ollama live endpoints
        self.app.router.add_get('/api/ollama_models', self.handle_ollama_models)
        self.app.router.add_get('/api/ollama_status', self.handle_ollama_status)
        # Control APIs
        self.app.router.add_post('/api/chat', self.handle_chat)
        self.app.router.add_post('/api/chat/boost', self.handle_chat_boost)
        self.app.router.add_post('/api/ask_user/respond', self.handle_ask_user_respond)
        self.app.router.add_post('/api/approval/respond', self.handle_approval_respond)
        self.app.router.add_get('/api/blackboard', self.handle_blackboard)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/cost-stats', self.handle_cost_stats)
        self.app.router.add_post('/api/plugin_toggle', self.handle_plugin_toggle)
        self.app.router.add_post('/api/tool_invoke', self.handle_tool_invoke)
        self.app.router.add_get('/api/tools', self.handle_list_tools)
        self.app.router.add_get('/api/plugins', self.handle_list_plugins)
        self.app.router.add_post('/api/switch_model', self.handle_switch_model)
        self.app.router.add_post('/api/browser_cmd', self.handle_browser_cmd)
        # Aliases (config.yaml -> aliases:)
        self.app.router.add_get('/api/aliases', self.handle_aliases)
        # OpenClaw migration endpoints
        self.app.router.add_get('/api/check_openclaw', self.handle_check_openclaw)
        self.app.router.add_post('/api/migrate_openclaw', self.handle_migrate_openclaw)
        # Model config endpoint (context window / max tokens)
        self.app.router.add_post('/api/model_config', self.handle_model_config)
        # Per-model overrides
        self.app.router.add_get('/api/model_overrides', self.handle_get_model_overrides)
        self.app.router.add_post('/api/model_overrides', self.handle_set_model_override)
        self.app.router.add_delete('/api/model_overrides', self.handle_delete_model_override)
        self.app.router.add_get('/api/history', self.handle_history)
        self.app.router.add_post('/api/history/load', self.handle_history_load)
        # Named chat sessions (save / switch / delete)
        self.app.router.add_get('/api/sessions', self.handle_sessions_list)
        self.app.router.add_post('/api/sessions/save', self.handle_session_save)
        self.app.router.add_post('/api/sessions/switch', self.handle_session_switch)
        self.app.router.add_post('/api/sessions/delete', self.handle_session_delete)
        self.app.router.add_get('/api/logs', self.handle_logs)
        self.app.router.add_get('/api/image/{filename}', self.handle_serve_image)
        self.app.router.add_get('/api/video/{filename}', self.handle_serve_video)
        self.app.router.add_get('/api/audio/{filename}', self.handle_serve_audio)
        self.app.router.add_get('/api/images/{subfolder}/{filename}', self.handle_serve_image_sub)
        self.app.router.add_get('/api/traces', self.handle_traces)
        self.app.router.add_post('/api/save_key', self.handle_save_key)
        # Settings endpoints
        self.app.router.add_post('/api/settings/models', self.handle_settings_models)
        self.app.router.add_post('/api/settings/voice', self.handle_settings_voice)
        self.app.router.add_post('/api/settings/personality', self.handle_settings_personality)
        self.app.router.add_post('/api/settings/system', self.handle_settings_system)
        self.app.router.add_post('/api/settings/thinking', self.handle_settings_thinking)
        self.app.router.add_get('/api/doctor', self.handle_doctor)
        self.app.router.add_get('/api/config_full', self.handle_config_full)
        self.app.router.add_post('/api/config_update', self.handle_config_update)
        self.app.router.add_post('/api/cli_sync', self.handle_cli_sync)
        # Memory endpoints (used by the CLI's /recall and /compact commands)
        self.app.router.add_post('/api/memory/search', self.handle_memory_search)
        self.app.router.add_post('/api/memory/compact', self.handle_memory_compact)
        # Memory browser (deck Memory tab)
        self.app.router.add_get('/api/memory/list', self.handle_memory_list)
        self.app.router.add_get('/api/memory/stats', self.handle_memory_stats)
        self.app.router.add_post('/api/memory/delete', self.handle_memory_delete)
        # Voice API endpoints
        self.app.router.add_post('/api/tts', self.handle_tts)
        self.app.router.add_post('/api/stt', self.handle_stt)
        self.app.router.add_post('/api/voice/stop', self.handle_voice_stop)
        self.app.router.add_get('/api/voice/wakeword', self.handle_wakeword_get)
        self.app.router.add_post('/api/voice/wakeword', self.handle_wakeword_set)
        # Executable Smart Artifacts
        self.app.router.add_post('/api/artifact/run', self.handle_artifact_run)
        # Power control endpoints
        self.app.router.add_post('/api/restart', self.handle_restart)
        self.app.router.add_post('/api/shutdown', self.handle_shutdown)
        self.app.router.add_post('/api/update', self.handle_update)
        # Resumable Workflows
        self.app.router.add_get('/api/runs', self.handle_runs)
        self.app.router.add_post('/api/resume/{uuid}', self.handle_resume)
        # Cancellation
        self.app.router.add_post('/api/cancel_task', self.handle_cancel_task)
        self.app.router.add_post('/api/stop_agent', self.handle_stop_agent)
        # Subagent Hive Mind API
        self.app.router.add_get('/api/subagents', self.handle_subagents)
        self.app.router.add_delete('/api/subagents/clear', self.handle_clear_subagents)
        self.app.router.add_delete('/api/subagents/{session_id}', self.handle_cancel_subagent)
        self.app.router.add_post('/api/subagents/chain', self.handle_spawn_chain)
        self.app.router.add_get('/api/subagents/default_model', self.handle_get_subagent_model)
        self.app.router.add_post('/api/subagents/default_model', self.handle_set_subagent_model)
        self.app.router.add_get('/api/subagents/models', self.handle_subagent_models)
        self.app.router.add_get('/api/swarm/config', self.handle_get_swarm_config)
        self.app.router.add_post('/api/swarm/config', self.handle_set_swarm_config)
        # Virtual Terminal WebSocket (deck Terminal panel)
        self.app.router.add_get('/ws/terminal', self.handle_terminal_ws)
        # Chrome Bridge WebSocket — connects the Galactic Browser extension
        self.app.router.add_get('/ws/chrome_bridge', self.handle_chrome_bridge_ws)
        self.trace_buffer = []  # last 500 agent trace entries for persistence
        
    async def handle_runs(self, request):
        """GET /api/runs - Lists all saved workflow runs/checkpoints."""
        runs_dir = os.path.join(self.core.config.get('paths', {}).get('logs', './logs'), 'runs')
        if not os.path.exists(runs_dir):
            return web.json_response([])
            
        runs = []
        for d in os.listdir(runs_dir):
            cp_path = os.path.join(runs_dir, d, 'checkpoint.json')
            if os.path.isfile(cp_path):
                try:
                    with open(cp_path, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                    
                    mtime = os.path.getmtime(cp_path)
                    plan_preview = state.get('active_plan', {}).get('original_query', 'No query') if state.get('active_plan') else 'No active plan'
                    turn_count = state.get('turn_count', 0)
                    
                    runs.append({
                        "uuid": d,
                        "mtime": mtime,
                        "turn_count": turn_count,
                        "plan_preview": plan_preview[:100] + ('...' if len(plan_preview) > 100 else '')
                    })
                except Exception:
                    pass
        # Sort by mtime descending
        runs.sort(key=lambda x: x['mtime'], reverse=True)
        return web.json_response(runs)

    async def handle_resume(self, request):
        """POST /api/resume/{uuid} - Triggers the resume_workflow tool."""
        uuid_val = request.match_info.get('uuid')
        if not uuid_val:
            return web.json_response({'error': 'Missing UUID'}, status=400)
            
        # Create an isolated task to run the resume command
        asyncio.create_task(
            self.core.gateway.speak(
                user_input=f"Please resume the workflow for checkpoint {uuid_val}.", 
                context=f"You must use the resume_workflow tool right now with uuid: {uuid_val}", 
                skip_planning=True
            )
        )
        return web.json_response({'ok': True, 'message': f'Resume triggered for {uuid_val}'})

    async def handle_cancel_task(self, request):
        """POST /api/cancel_task - Cancels ALL currently active agent tasks."""
        gateway = self.core.gateway
        count = 0
        for t in list(gateway._active_tasks):
            if not t.done():
                t.cancel()
                count += 1
        
        if count > 0:
            await self.core.log(f"🚫 User clicked CANCEL in Control Deck. Aborting {count} task(s)...", priority=2)
            return web.json_response({'ok': True, 'message': f'Cancellation requested for {count} task(s)'})
        return web.json_response({'ok': False, 'message': 'No active task to cancel'})

    async def handle_stop_agent(self, request):
        """POST /api/stop_agent — escalating stop.

        First press asks the ReAct loop to exit cleanly at the next turn
        boundary (preserves state, finishes the current thought). But that flag
        is only read BETWEEN turns, so it cannot interrupt a tool call that is
        already running — a slow analyze_image or browser action would ignore
        STOP for minutes, which just made users mash the button.

        So: if a stop is already pending (i.e. the graceful request didn't take
        because we're stuck inside a tool), escalate to a hard task cancel —
        the same thing Escape does in the terminal, and the only thing that can
        actually interrupt work in progress.
        """
        gateway = self.core.gateway
        already_stopping = bool(getattr(gateway, '_stop_requested', False))

        # Always cancel subagents — they're independent of the main loop.
        mgr = self._get_subagent_mgr()
        subagent_cancelled_count = 0
        if mgr and hasattr(mgr, 'active_sessions'):
            for session in list(mgr.active_sessions.values()):
                if session.status in ('pending', 'running'):
                    mgr.cancel_session(session.id)
                    subagent_cancelled_count += 1

        if already_stopping:
            # ── Escalation: force-cancel the in-flight tasks ──
            cancelled = 0
            for t in list(getattr(gateway, '_active_tasks', []) or []):
                if not t.done():
                    t.cancel()
                    cancelled += 1
            gateway._stop_requested = False  # consumed; loop is being torn down
            await self.core.log(
                f"🚫 STOP escalated — force-cancelled {cancelled} in-flight task(s) "
                f"(agent was inside a long-running tool).", priority=1)
            return web.json_response({
                'ok': True, 'escalated': True, 'cancelled': cancelled,
                'message': (f'🚫 Force-stopped {cancelled} running task(s).'
                            if cancelled else
                            '🚫 Nothing left running — agent already idle.')
            })

        gateway._stop_requested = True
        await self.core.log(
            f"🛑 STOP signal sent. Stopping at next turn. "
            f"Cancelled {subagent_cancelled_count} running subagents.", priority=1)
        return web.json_response({
            'ok': True, 'escalated': False,
            'message': (f'🛑 Stopping at the next turn'
                        + (f' · cancelled {subagent_cancelled_count} subagent(s)' if subagent_cancelled_count else '')
                        + '. If it\'s mid-tool, press STOP again to force it.')
        })

    # ── Subagent Hive Mind API ───────────────────────────────────────────────

    def _get_subagent_mgr(self):
        for s in self.core.skills:
            if s.skill_name == 'subagent_manager' and s.enabled:
                return s
        return None

    async def handle_subagents(self, request):
        """GET /api/subagents - List all active subagents."""
        mgr = self._get_subagent_mgr()
        if not mgr:
            return web.json_response({'error': 'Subagent manager skill string not loaded/enabled'}, status=404)
        return web.json_response(mgr.get_all_sessions())

    async def handle_clear_subagents(self, request):
        """DELETE /api/subagents/clear"""
        mgr = self._get_subagent_mgr()
        if mgr:
            mgr.clear_completed_sessions()
        return web.json_response({'ok': True})

    async def handle_cancel_subagent(self, request):
        """DELETE /api/subagents/{session_id}"""
        mgr = self._get_subagent_mgr()
        session_id = request.match_info.get('session_id')
        if not mgr or not session_id:
            return web.json_response({'error': 'Invalid request'}, status=400)
        ok = mgr.cancel_session(session_id)
        return web.json_response({'ok': ok})

    async def handle_spawn_chain(self, request):
        """POST /api/subagents/chain"""
        mgr = self._get_subagent_mgr()
        if not mgr:
            return web.json_response({'error': 'Subagent manager strictly disabled'}, status=404)
        try:
            data = await request.json()
            steps = data.get('steps', [])
            if not steps:
                return web.json_response({'error': 'No steps provided'}, status=400)
            chain_id = await mgr.spawn_chain(steps)
            return web.json_response({'ok': True, 'chain_id': chain_id})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)


    async def handle_get_subagent_model(self, request):
        """GET /api/subagents/default_model"""
        model = self.core.config.get("subagents", {}).get("default_model", "")
        return web.json_response({"model": model})

    async def handle_set_subagent_model(self, request):
        """POST /api/subagents/default_model — persists to config.yaml"""
        try:
            data = await request.json()
            model = data.get("model", "").strip()
            if "subagents" not in self.core.config:
                self.core.config["subagents"] = {}
            self.core.config["subagents"]["default_model"] = model or None
            self.core.save_config()
            return web.json_response({"ok": True, "model": model})
            return web.json_response({"ok": True, "model": model})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_get_swarm_config(self, request):
        """GET /api/swarm/config"""
        config = self.core.config.get("subagents", {})
        return web.json_response({
            "allow_auto": config.get("allow_auto", True),
            "allow_online_models": config.get("allow_online_models", False),
            "whitelist": config.get("allowed_online_models", [])
        })

    async def handle_set_swarm_config(self, request):
        """POST /api/swarm/config"""
        try:
            data = await request.json()
            if "subagents" not in self.core.config:
                self.core.config["subagents"] = {}
            
            if "allow_auto" in data:
                self.core.config["subagents"]["allow_auto"] = data["allow_auto"]
            if "allow_online_models" in data:
                self.core.config["subagents"]["allow_online_models"] = data["allow_online_models"]
            if "whitelist" in data:
                self.core.config["subagents"]["allowed_online_models"] = data["whitelist"]
                
            self.core.save_config()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_subagent_models(self, request):
        """GET /api/subagents/models — returns all known model IDs for the selector."""
        try:
            mm = getattr(self.core, "model_manager", None)
            if mm and hasattr(mm, "get_all_models"):
                models = mm.get_all_models()
            elif mm and hasattr(mm, "models"):
                models = mm.models
            else:
                models = []
            # Flatten to list of {id, label} objects
            result = []
            for m in models:
                if isinstance(m, dict):
                    mid = m.get("model") or m.get("id", "")
                    label = m.get("name") or mid
                    result.append({"id": mid, "label": label})
                elif isinstance(m, str):
                    result.append({"id": m, "label": m})
            return web.json_response(result)
        except Exception as e:
            return web.json_response([], status=200)

    async def handle_index(self, request):
        theme = request.cookies.get('theme', 'modern')
        file_map = {
            'legacy': 'deck_legacy.html',
            'modern': 'deck_modern.html'
        }
        filename = file_map.get(theme, 'deck_modern.html')

        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if not os.path.exists(filepath):
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deck_modern.html')

        if not os.path.exists(filepath):
            return web.Response(status=500, text='Deck HTML file missing — reinstall or restore deck_modern.html')

        cache = getattr(self, '_index_cache', None)
        if cache is None:
            cache = self._index_cache = {}
        try:
            mtime = os.path.getmtime(filepath)
            hit = cache.get(filepath)
            if hit and hit[0] == mtime:
                return web.Response(text=hit[1], content_type='text/html')

            loop = asyncio.get_running_loop()
            def _read():
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
            html = await loop.run_in_executor(None, _read)
            cache[filepath] = (mtime, html)
            return web.Response(text=html, content_type='text/html')
        except Exception as e:
            return web.Response(status=500, text=f'Failed to load deck: {e}')

    async def handle_aliases(self, request):
        """GET /api/aliases — return config.yaml -> aliases mapping.

        Output format:
          { aliases: [ {alias, target, provider, model, is_nitro} ], count }

        Notes:
        - If an alias value is "provider/model", we honor it.
        - If it's just "org/model" (OpenRouter style), we default provider to openrouter.
        - If it's a plain model id (no slash), we default provider to current gateway provider.
        """
        aliases = self.core.config.get('aliases', {}) or {}

        known_providers = set((self.core.config.get('providers', {}) or {}).keys())
        known_providers |= {
            'google','anthropic','openai','xai','groq','mistral','cerebras','openrouter',
            'huggingface','kimi','zai','minimax','nvidia','ollama','deepseek'
        }

        current_provider = (self.core.config.get('gateway', {}) or {}).get('provider', '') or 'openrouter'

        out = []
        for alias_name, target in aliases.items():
            t = str(target).strip()
            provider = None
            model = None

            # Explicit separator: provider|model
            if '|' in t:
                provider, model = t.split('|', 1)
                provider = provider.strip()
                model = model.strip()
            else:
                # If first segment matches a provider, treat as provider/model
                pfx = t.split('/', 1)
                if len(pfx) == 2 and pfx[0] in known_providers:
                    provider = pfx[0]
                    model = pfx[1]
                else:
                    # Heuristic: OpenRouter models are typically org/model (contain '/').
                    provider = 'openrouter' if '/' in t else current_provider
                    model = t

            s = (alias_name + ' ' + t).lower()
            out.append({
                'alias': alias_name,
                'target': t,
                'provider': provider,
                'model': model,
                'is_nitro': ('nitro' in s),
            })

        # Sort Nitro to top, then alpha
        out.sort(key=lambda a: (0 if a.get('is_nitro') else 1, str(a.get('alias','')).lower()))
        return web.json_response({'aliases': out, 'count': len(out)})

    async def handle_ollama_models(self, request):
        """Return live discovered Ollama model list from OllamaManager."""
        models = []
        if hasattr(self.core, 'ollama_manager'):
            models = self.core.ollama_manager.discovered_models
        return web.json_response({"models": models})

    async def handle_ollama_status(self, request):
        """Return Ollama health status."""
        if hasattr(self.core, 'ollama_manager'):
            status = self.core.ollama_manager.get_status()
        else:
            status = {"healthy": False, "base_url": "unknown", "models": [], "model_count": 0}
        return web.json_response(status)

    async def handle_serve_audio(self, request):
        """GET /api/audio/{filename} - serve a generated audio from the logs directory."""
        import mimetypes
        filename = request.match_info.get('filename', '')
        filename = os.path.basename(filename)
        logs_dir = os.path.abspath(self.core.config.get('paths', {}).get('logs', './logs'))
        path = os.path.abspath(os.path.join(logs_dir, filename))
        
        # Security: verify path is within logs_dir
        if not path.startswith(logs_dir + os.sep) and path != logs_dir:
            return web.Response(status=403, text='Forbidden')
            
        if not os.path.exists(path):
            return web.Response(status=404, text='Not found')
            
        mt, _ = mimetypes.guess_type(path)
        return web.FileResponse(path, headers={'Content-Type': mt or 'audio/mpeg'})

    async def handle_serve_video(self, request):
        """GET /api/video/{filename} — serve a generated video."""
        filename = request.match_info.get('filename', '')
        filename = os.path.basename(filename)
        images_dir = os.path.abspath(self.core.config.get('paths', {}).get('images', './images'))
        video_dir = os.path.join(images_dir, 'video')
        path = os.path.abspath(os.path.join(video_dir, filename))
        
        # Security: verify path is within video_dir
        if not path.startswith(video_dir + os.sep) and path != video_dir:
            return web.Response(status=403, text='Forbidden')
            
        if not os.path.exists(path):
            return web.Response(status=404, text='Video not found')
        return web.FileResponse(path, headers={
            'Content-Type': 'video/mp4',
            'Cache-Control': 'public, max-age=86400',
        })

    async def handle_serve_image(self, request):
        """GET /api/image/{filename} — serve a generated image from the logs directory."""
        import mimetypes
        filename = request.match_info.get('filename', '')
        # Security: no path traversal — basename only
        filename = os.path.basename(filename)
        logs_dir = os.path.abspath(self.core.config.get('paths', {}).get('logs', './logs'))
        path = os.path.abspath(os.path.join(logs_dir, filename))
        
        # Security: verify path is within logs_dir
        if not path.startswith(logs_dir + os.sep) and path != logs_dir:
            return web.Response(status=403, text='Forbidden')

        if not os.path.exists(path):
            return web.Response(status=404, text='Image not found')
        mime = mimetypes.guess_type(filename)[0] or 'image/jpeg'
        return web.FileResponse(path, headers={
            'Content-Type': mime,
            'Cache-Control': 'public, max-age=86400',
        })

    async def handle_serve_image_sub(self, request):
        """GET /api/images/{subfolder}/{filename} — serve from images/<subfolder>/"""
        import mimetypes
        subfolder = request.match_info.get('subfolder', '')
        filename = request.match_info.get('filename', '')
        # Security: reject traversal characters in both path components
        for part in (subfolder, filename):
            if '..' in part or '/' in part or '\\' in part:
                return web.Response(status=400, text='Invalid path')
        images_dir = os.path.abspath(
            self.core.config.get('paths', {}).get('images', './images')
        )
        candidate = os.path.abspath(os.path.join(images_dir, subfolder, filename))
        if not candidate.startswith(images_dir + os.sep):
            return web.Response(status=403, text='Forbidden')
        if not os.path.exists(candidate):
            return web.Response(status=404, text='Image not found')
        mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        return web.FileResponse(candidate, headers={
            'Content-Type': mime,
            'Cache-Control': 'public, max-age=86400',
        })

    async def handle_chat(self, request):
        """POST /api/chat — send message to the AI and get response.

        Accepts:
          - JSON body: {message, images?: [{name, data, mime}]}
          - multipart/form-data: message field + files parts (text) + optional images_json field
        Images are sent as base64 data URLs and forwarded to the LLM as vision content.
        """
        import base64 as _b64, json as _json, time as _time
        try:
            user_msg = ''
            file_context = ''
            attached_images = []  # list of {name, mime, b64} dicts

            content_type = request.content_type or ''
            if 'multipart/form-data' in content_type:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == 'message':
                        user_msg = (await part.text()).strip()
                    elif part.name == 'images_json':
                        # Pre-encoded images from the frontend
                        try:
                            imgs = _json.loads(await part.text())
                            for img in imgs:
                                data_url = img.get('data', '')
                                if ',' in data_url:
                                    b64 = data_url.split(',', 1)[1]
                                    attached_images.append({
                                        'name': img.get('name', 'image'),
                                        'mime': img.get('mime', 'image/jpeg'),
                                        'b64': b64,
                                    })
                        except Exception:
                            pass
                    elif part.name == 'files':
                        filename = part.filename or 'unnamed'
                        # aiohttp BodyPartReader.read() often does NOT accept a size argument.
                        # Read in chunks and enforce a max upload size (20MB) ourselves.
                        max_bytes = 20 * 1024 * 1024
                        buf = bytearray()
                        while True:
                            chunk = await part.read_chunk(size=256 * 1024)
                            if not chunk:
                                break
                            buf.extend(chunk)
                            if len(buf) > max_bytes:
                                buf = buf[:max_bytes]
                                break
                        raw = bytes(buf)
                        try:
                            text = raw.decode('utf-8', errors='replace')
                        except Exception:
                            text = '[Binary file — could not decode]'
                        if len(text) > 100000:
                            text = text[:100000] + '\n\n... [truncated — file exceeds 100K characters]'
                        file_context += f"\n\n[Attached file: {filename}]\n---\n{text}\n---\n"
            else:
                data = await request.json()
                user_msg = data.get('message', '').strip()
                verbose_req = data.get('verbose', None)
                if verbose_req is not None:
                    # Update gateway streaming verbosity config temporarily for this request
                    self.core.gateway._current_request_verbose = bool(verbose_req)
                
                # Images sent as JSON: [{name, data (data URL), mime}]
                for img in data.get('images', []):
                    data_url = img.get('data', '')
                    if ',' in data_url:
                        b64 = data_url.split(',', 1)[1]
                        attached_images.append({
                            'name': img.get('name', 'image'),
                            'mime': img.get('mime', 'image/jpeg'),
                            'b64': b64,
                        })

            # Build context string for text files
            full_msg = user_msg
            if file_context:
                full_msg = file_context.strip() + ('\n\n' + user_msg if user_msg else '')

            if not full_msg and not attached_images:
                return web.json_response({'error': 'No message'}, status=400)

            # ── Command Interception ──
            cmd_parts = user_msg.strip().split()
            cmd_base = cmd_parts[0].lower() if cmd_parts else ""
            cmd = user_msg.strip().lower()
            # Voice Command Interception for Personality Switch
            import re
            m = re.search(r"(?:change|switch|swap)(?:\s+the)?\s+(?:personality|persona|character)\s+(?:to\s+)?([a-z0-9_ -]+)[.!]*", cmd, re.IGNORECASE)
            if m:
                target_mode = m.group(1).strip().lower()
                # Aliases mapping
                if 'homer' in target_mode: target_mode = 'homer'
                elif 'generic' in target_mode: target_mode = 'generic'
                elif 'byte' in target_mode or 'bite' in target_mode: target_mode = 'byte'
                else: target_mode = target_mode.replace(" ", "_")
                
                cfg = self.core.config
                if 'personality' not in cfg:
                    cfg['personality'] = {}
                cfg['personality']['mode'] = target_mode
                
                try:
                    self._save_config(cfg)
                    from personality import GalacticPersonality
                    self.core.gateway.personality = GalacticPersonality(
                        cfg, cfg.get('paths', {}).get('workspace')
                    )
                    
                    p_name = getattr(self.core.gateway.personality, 'display_name', self.core.gateway.personality.name)
                    await self.core.log(f"🧠 Personality changed to {p_name} via Voice/Chat command", priority=2)
                    
                    return web.json_response({
                        'response': f"Acknowledged. Personality matrix successfully swapped to {p_name}. How can I assist you?",
                        'model': 'Command Interceptor',
                        'tokens': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                        'time': 0,
                    })
                except Exception as e:
                    return web.json_response({'error': str(e)}, status=500)

            if cmd_base in ("/help", "/commands", "/?"):
                return web.json_response({'response': (
                    "🛠️ **Chat commands**\n\n"
                    "- `/help` — this list\n"
                    "- `/context` — token usage of the active model\n"
                    "- `/compact` — summarize & archive old history to free context\n"
                    "- `/clear` — wipe the current conversation\n"
                    "- `/rewind [n]` — undo the last *n* messages (default 2)\n"
                    "- `/boost [model]` — re-run the last answer on your boost model (big cloud brain)\n"
                    "- `/retry` — re-run the last answer on the current model\n"
                    "- `/hybrid [on|off]` — toggle Hybrid Coding (cloud Architect writes, local Builder applies)\n"
                    "- `switch personality to <name>` — hot-swap persona (e.g. byte, homer, generic)\n\n"
                    "💡 The topbar **CTX** chip shows live context usage; the 👂 button toggles wake-word listening; "
                    "the 🗂️ Session bar saves/switches named chats."
                )})

            if cmd_base == "/rewind":
                n = 2
                if len(cmd_parts) > 1:
                    try:
                        n = int(cmd_parts[1])
                    except ValueError:
                        pass
                history = self.core.gateway.history
                if not history:
                    return web.json_response({'response': "⚠️ History is already empty."})
                n = min(n, len(history))
                new_history = history[:-n]
                del history[-n:]
                h_file = getattr(self.core.gateway, 'history_file', None)
                if h_file and os.path.exists(h_file):
                    try:
                        with open(h_file, 'w', encoding='utf-8') as f:
                            for msg in new_history:
                                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    except Exception as e:
                        await self.core.log(f"⚠️ Failed to overwrite chat history file: {e}", priority=1)
                await self.core.log(f"⏪ Rewound conversation by {n} message(s).", priority=2)
                return web.json_response({'response': f"⏪ **Rewound conversation by {n} message(s).**"})

            if cmd == "/clear":
                self.core.gateway.history.clear()
                # Remove the chat_history.jsonl file so it doesn't reload on refresh
                h_file = getattr(self.core.gateway, 'history_file', None)
                if h_file and os.path.exists(h_file):
                    try: os.remove(h_file)
                    except: pass
                await self.core.log("🧹 Session history cleared.", priority=2)
                return web.json_response({'response': "✨ **Context Cleared.** Current conversation history and local cache have been reset."})

            if cmd == "/compact":
                if not self.core.gateway.history:
                    return web.json_response({'response': "⚠️ History is already empty."})
                
                await self.core.log("🧹 Manual context compaction started...", priority=2)
                # Wrap with a dummy system prompt for gateway's logic
                msgs = [{"role": "system", "content": "N/A"}] + self.core.gateway.history
                compacted = await self.core.gateway._compact_history(msgs, 0)
                # Pop the dummy system message back off
                if compacted and len(compacted) > 0 and compacted[0].get('role') == 'system' and compacted[0].get('content') == "N/A":
                    compacted.pop(0)
                self.core.gateway.history = compacted
                return web.json_response({'response': "🧹 **Manual Compaction Successful.** Context summarized and archived in Vector DB."})

            if cmd_base == "/hybrid":
                arg = (cmd_parts[1].lower() if len(cmd_parts) > 1 else '').strip()
                cfg = self.core.config
                hc = cfg.setdefault('models', {}).setdefault('hybrid_coding', {})
                cur = bool(hc.get('enabled'))
                new_state = {'on': True, 'off': False}.get(arg, not cur)
                hc['enabled'] = new_state
                try:
                    self._save_config(cfg)
                except Exception as e:
                    return web.json_response({'response': f"⚠️ Could not save hybrid mode: {e}"})
                arch = (f"{hc.get('architect_provider')}/{hc.get('architect_model')}"
                        if hc.get('architect_provider') and hc.get('architect_model')
                        else 'planner model (set an Architect in Settings → Models)')
                bld = (f"{hc.get('builder_provider')}/{hc.get('builder_model')}"
                       if hc.get('builder_provider') and hc.get('builder_model')
                       else 'local fallback model')
                await self.core.log(f"🧬 Hybrid Coding Mode {'ENABLED' if new_state else 'DISABLED'}", priority=2)
                if new_state:
                    return web.json_response({'response': (
                        "🧬 **Hybrid Coding Mode ON**\n\n"
                        f"- **Architect (writes the code):** `{arch}`\n"
                        f"- **Builder (applies it locally):** `{bld}`\n\n"
                        "Coding tasks now get a big-brain blueprint, executed by the local model. "
                        "Configure the roles in Settings → Model Configuration."
                    )})
                return web.json_response({'response': "🧬 **Hybrid Coding Mode OFF** — coding runs on the primary model as usual."})

            if cmd_base in ("/boost", "/retry"):
                arg = user_msg.strip()[len(cmd_base):].strip()
                result = await self._boost_last_exchange(
                    retry=(cmd_base == "/retry"),
                    model_query=arg or None,
                )
                # Chat-command path: always speak the outcome as a normal response
                if 'error' in result:
                    return web.json_response({'response': f"⚠️ {result['error']}"})
                return web.json_response(result)

            if cmd == "/context":
                gw = self.core.gateway
                usage, ctx_max = self._context_usage()
                pct = (usage / ctx_max * 100) if ctx_max > 0 else 0
                rem = max(0, ctx_max - usage)
                
                msg = (
                    f"📊 **Context Status** ({gw.llm.provider}/{gw.llm.model})\n\n"
                    f"- **Used**: `{usage:,}` tokens (~{pct:.1f}%)\n"
                    f"- **Free**: `{rem:,}` tokens\n"
                    f"- **Total**: `{ctx_max:,}` tokens\n\n"
                    f"*Note: Auto-compaction triggers when usage exceeds ~90% of a model's safety limit.*"
                )
                return web.json_response({'response': msg})

            # Log cleanly
            source = data.get('source', 'web') if 'multipart/form-data' not in content_type else 'web'
            source_label = "Browser" if source == 'extension' else "Web"
            
            parts_log = []
            if file_context:
                parts_log.append(f"+{file_context.count('[Attached file:')} file(s)")
            if attached_images:
                parts_log.append(f"+{len(attached_images)} image(s)")
            suffix = f" [{', '.join(parts_log)}]" if parts_log else ""
            await self.core.log(f"[{source_label}] User: {user_msg or '(no text)'}{suffix}", priority=2)

            # Broadcast to Web Control Deck UI for real-time sync
            if source == 'extension':
                await self.core.relay.emit(3, "chat_from_extension", {"data": user_msg or '(no text)'})

            # Non-blocking chat: if the main agent is busy, route to a quick-reply model
            isolated = False
            if 'multipart/form-data' not in content_type:
                isolated = data.get('isolated', False)

            _t0 = _time.monotonic()
            if isolated:
                try:
                    # Execute in isolation to prevent polluting the history
                    response = await self.core.gateway.speak_isolated(
                        full_msg,
                        context="You are a helpful programming assistant. Provide a brief, direct, and concise answer to this side question.",
                        skip_planning=True
                    )
                except Exception as e:
                    response = f"Error in isolated execution: {e}"
            elif getattr(self.core.gateway, '_speaking', False):
                busy_task = getattr(self.core.gateway, '_current_task_desc', 'a background task')
                quick_ctx  = (
                    f"The main AI agent is currently busy working on: {busy_task}. "
                    f"Give a brief, helpful quick reply to the following message. "
                    f"Mention that the main agent is still working if relevant."
                )
                try:
                    quick_reply = await self.core.gateway.speak_isolated(
                        full_msg or f"[User attached {len(attached_images)} image(s)].",
                        context=quick_ctx
                    )
                    response = f"⚡ **Quick Reply** *(main agent busy)*\n\n{quick_reply}"
                except Exception:
                    response = "⚡ *The main agent is busy — please wait for it to finish before sending this.*"
            elif attached_images:
                response = await self.core.gateway.speak(
                    full_msg or f"[User attached {len(attached_images)} image(s). Please describe and analyse them.]",
                    images=attached_images
                )
            else:
                response = await self.core.gateway.speak(full_msg)

            # Reset the temporary verbose flag
            if hasattr(self.core.gateway, '_current_request_verbose'):
                del self.core.gateway._current_request_verbose

            await self.core.log(f"[Core] {getattr(self.core.gateway.personality, 'display_name', self.core.gateway.personality.name)}: {response}", priority=2)

            # Deliver any generated image inline — fix path for new images/ subfolders
            resp_data = {'response': response,
                         'meta': self._response_meta(_time.monotonic() - _t0)}
            image_file = getattr(self.core.gateway, 'last_image_file', None)
            await self.core.log(
                f"[Image Delivery] last_image_file={image_file!r}, "
                f"exists={os.path.exists(image_file) if image_file else 'N/A'}",
                priority=3
            )
            if image_file and os.path.exists(image_file):
                images_dir = os.path.abspath(
                    self.core.config.get('paths', {}).get('images', './images')
                )
                abs_img = os.path.abspath(image_file)
                if abs_img.startswith(images_dir + os.sep):
                    # New subfolder path → use /api/images/{subfolder}/{filename}
                    rel = os.path.relpath(abs_img, images_dir)
                    parts = rel.replace('\\', '/').split('/', 1)
                    if len(parts) == 2:
                        resp_data['image_url'] = f'/api/images/{parts[0]}/{parts[1]}'
                    else:
                        resp_data['image_url'] = f'/api/image/{os.path.basename(image_file)}'
                else:
                    # Legacy logs/ path
                    resp_data['image_url'] = f'/api/image/{os.path.basename(image_file)}'
                self.core.gateway.last_image_file = None
                await self.core.log(
                    f"[Image Delivery] ✅ image_url={resp_data['image_url']}",
                    priority=2
                )
            elif image_file:
                await self.core.log(
                    f"[Image Delivery] ⚠️ File not found: {os.path.abspath(image_file)} "
                    f"(CWD={os.getcwd()})",
                    priority=1
                )

            # Video delivery (same pattern as image delivery)
            video_file = getattr(self.core.gateway, 'last_video_file', None)
            if video_file and os.path.exists(video_file):
                fname = os.path.basename(video_file)
                resp_data['video_url'] = f'/api/video/{fname}'
                self.core.gateway.last_video_file = None
                await self.core.log(
                    f"[Video Delivery] serving {fname}",
                    priority=3
                )
            # Audio delivery
            voice_file = getattr(self.core.gateway, 'last_voice_file', None)
            if voice_file and os.path.exists(voice_file):
                fname = os.path.basename(voice_file)
                resp_data['audio_url'] = f'/api/audio/{fname}'
                self.core.gateway.last_voice_file = None
                await self.core.log(
                    f"[Voice Delivery] serving {fname}",
                    priority=3
                )


            return web.json_response(resp_data)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    # ── Per-message provenance + Boost/Retry ────────────────────────────────

    def _response_meta(self, elapsed):
        """Who actually answered, and how it went — attached to chat responses.

        llm.provider/model are contextvar-backed, so after awaiting speak()
        they reflect the model that really served the reply (including any
        mid-request fallback), not just the one selected in the UI.
        """
        gw = self.core.gateway
        meta = {
            'provider': getattr(gw.llm, 'provider', None),
            'model': getattr(gw.llm, 'model', None),
            'elapsed': round(elapsed, 1),
        }
        mm = getattr(self.core, 'model_manager', None)
        if mm:
            try:
                meta['mode'] = mm.current_mode
            except Exception:
                pass
        usage = getattr(gw, '_last_usage', None)
        if isinstance(usage, dict):
            meta['tokens_in'] = usage.get('prompt_tokens')
            meta['tokens_out'] = usage.get('completion_tokens')
        return meta

    def _resolve_boost_target(self, model_query=None):
        """Pick the (provider, model) to boost to.

        Priority: explicit query > config models.boost_provider/boost_model >
        first configured cloud model. Returns (provider, model) or (None, err).
        """
        mm = getattr(self.core, 'model_manager', None)
        if model_query and mm:
            resolved = mm.resolve_model_id(model_query)
            if '/' in resolved:
                prov, mod = resolved.split('/', 1)
                return prov, mod
            return None, f"Could not resolve '{model_query}' to a known provider/model."
        mcfg = self.core.config.get('models', {})
        prov = mcfg.get('boost_provider')
        mod = mcfg.get('boost_model')
        if prov and mod:
            return prov, mod
        # Auto-pick: prefer the user's own "king tier" curation — models whose
        # config/models.yaml name carries 👑 — falling back to the first cloud
        # model with a configured key. get_all_models() already excludes
        # providers without keys.
        if mm:
            cloud = [m for m in mm.get_all_models()
                     if m.get('id') and '/' in m['id']
                     and not m['id'].startswith('ollama/')]
            crowned = [m for m in cloud if '\U0001F451' in (m.get('name') or '')]
            pick = crowned[0] if crowned else (cloud[0] if cloud else None)
            if pick:
                prov, mod = pick['id'].split('/', 1)
                return prov, mod
        return None, ("No boost model available. Set models.boost_provider / "
                      "boost_model in config.local.yaml or add a cloud API key.")

    async def _boost_last_exchange(self, retry=False, model_query=None,
                                   provider=None, model=None):
        """Rewind the last user↔assistant exchange and re-run it.

        retry=True re-runs on the current model; otherwise on the boost target.
        The model override is temporary — nothing is persisted to config.
        Returns {'response', 'meta', ...} or {'error': str}.
        """
        import time as _time
        gw = self.core.gateway
        if getattr(gw, '_speaking', False):
            return {'error': 'The agent is busy with a task — wait for it to finish, then boost.'}

        history = gw.history
        last_user_idx = None
        for i in range(len(history) - 1, -1, -1):
            if history[i].get('role') == 'user':
                last_user_idx = i
                break
        if last_user_idx is None:
            return {'error': 'Nothing to re-run yet — the conversation is empty.'}

        user_content = history[last_user_idx].get('content', '')
        if isinstance(user_content, list):
            # Vision turn: content is [{type:text},{type:image_url},...] — replay text only
            user_content = ' '.join(
                part.get('text', '') for part in user_content
                if isinstance(part, dict) and part.get('type') == 'text'
            ).strip()
        if not user_content:
            return {'error': 'The last message had no replayable text (image-only turn).'}

        # Resolve target before touching history so failures are side-effect free
        mm = getattr(self.core, 'model_manager', None)
        if retry:
            target = None
        elif provider and model:
            target = (provider, model)
        else:
            prov, mod = self._resolve_boost_target(model_query)
            if prov is None:
                return {'error': mod}
            target = (prov, mod)

        # Rewind through the last user message (same persistence as /rewind)
        del history[last_user_idx:]
        h_file = getattr(gw, 'history_file', None)
        if h_file and os.path.exists(h_file):
            try:
                with open(h_file, 'w', encoding='utf-8') as f:
                    for msg in history:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except Exception as e:
                await self.core.log(f"⚠️ Boost: failed to rewrite history file: {e}", priority=1)

        saved = None
        if target and mm:
            saved = (mm.primary_provider, mm.primary_model, mm.current_mode)
            mm.primary_provider, mm.primary_model = target
            mm.current_mode = 'primary'
            await self.core.log(
                f"🚀 Boosting last exchange on {target[0]}/{target[1]}", priority=2
            )
        elif retry:
            await self.core.log("⟳ Retrying last exchange on the current model", priority=2)

        _t0 = _time.monotonic()
        try:
            response = await gw.speak(user_content)
        finally:
            if saved and mm:
                # Restore selection without persisting — boost is a one-shot
                mm.primary_provider, mm.primary_model, mm.current_mode = saved
                mm._set_api_key(mm.get_current_model().get('provider'))
        meta = self._response_meta(_time.monotonic() - _t0)
        if target:
            # Report the boost target even if provider internals shifted mid-run
            meta['boosted'] = True
        return {'response': response, 'meta': meta,
                'boosted': bool(target), 'retried': retry}

    async def handle_chat_boost(self, request):
        """POST /api/chat/boost — {retry?: bool, provider?: str, model?: str}

        Re-runs the last exchange: on the configured boost (cloud) model by
        default, or on the current model when retry=true. One-shot override —
        the primary model selection is restored afterwards.
        """
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}
        try:
            result = await self._boost_last_exchange(
                retry=bool(data.get('retry')),
                provider=data.get('provider'),
                model=data.get('model'),
            )
            if 'error' in result:
                return web.json_response(result, status=409)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_ask_user_respond(self, request):
        """POST /api/ask_user/respond — {id, answer} resolves a pending ask_user prompt.

        The gateway's ask_user tool is blocked awaiting an asyncio.Future keyed by
        `id`; setting its result unblocks the ReAct loop with the user's answer.
        Same event loop as the gateway, so set_result is safe here.
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'ok': False, 'error': 'Invalid JSON'}, status=400)
        req_id = (data.get('id') or '').strip()
        answer = data.get('answer', '')
        pending = getattr(self.core.gateway, '_pending_asks', {})
        fut = pending.get(req_id)
        if fut is None or fut.done():
            return web.json_response(
                {'ok': False, 'error': 'This question has expired or was already answered.'},
                status=409)
        try:
            fut.set_result(str(answer))
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)
        return web.json_response({'ok': True})

    async def handle_approval_respond(self, request):
        """POST /api/approval/respond — {id, approved: bool, feedback?} for The Crucible.

        Resolves the asyncio.Future that write_file/edit_file/replace_function is
        blocked on when models.require_approval is enabled.
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'ok': False, 'error': 'Invalid JSON'}, status=400)
        req_id = (data.get('id') or '').strip()
        pending = getattr(self.core.gateway, '_pending_approvals', {})
        fut = pending.get(req_id)
        if fut is None or fut.done():
            return web.json_response(
                {'ok': False, 'error': 'This approval request has expired or was already answered.'},
                status=409)
        try:
            fut.set_result({'approved': bool(data.get('approved')),
                            'feedback': data.get('feedback', '')})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)
        return web.json_response({'ok': True})

    async def handle_blackboard(self, request):
        """GET /api/blackboard — current shared Blackboard state for the Swarm panel."""
        bb = getattr(self.core, 'blackboard', None)
        if bb is None:
            return web.json_response({'entries': []})
        try:
            return web.json_response({'entries': bb.snapshot()})
        except Exception as e:
            return web.json_response({'entries': [], 'error': str(e)})

    async def handle_cost_stats(self, request):
        """GET /api/cost-stats — cost dashboard data."""
        ct = getattr(self.core, 'cost_tracker', None)
        if not ct:
            return web.json_response({"error": "Cost tracking not initialized"}, status=503)
        return web.json_response(ct.get_stats())

    async def handle_status(self, request):
        """GET /api/status — full system status JSON."""
        import time
        uptime = int(time.time() - self.core.start_time)

        # Format uptime as human readable
        def _fmt_uptime(s):
            d, rem = divmod(s, 86400)
            h, rem = divmod(rem, 3600)
            m, _ = divmod(rem, 60)
            parts = []
            if d: parts.append(f"{d}d")
            if h: parts.append(f"{h}h")
            parts.append(f"{m}m")
            return " ".join(parts)

        plugin_statuses = {}
        for p in self.core.plugins:
            pname = getattr(p, 'name', None) or getattr(p, 'skill_name', p.__class__.__name__)
            plugin_statuses[pname] = getattr(p, 'enabled', True)

        ollama_status = {}
        if hasattr(self.core, 'ollama_manager'):
            ollama_status = self.core.ollama_manager.get_status()

        model_status = {}
        mm = getattr(self.core, 'model_manager', None)
        if mm:
            gw = self.core.gateway
            ctx_max = 0
            if hasattr(gw, '_get_context_window_for_model'):
                ctx_max = gw._get_context_window_for_model(0)
            if not ctx_max and hasattr(self.core, 'ollama_manager') and gw.llm.provider == 'ollama':
                ctx_max = self.core.ollama_manager.get_context_window(gw.llm.model) or 0
                
            model_status = {
                'provider': gw.llm.provider,
                'model': gw.llm.model,
                'mode': mm.current_mode,
                'context_used': self._context_usage()[0],
                'context_max': ctx_max,
            }

        # Fallback chain + provider health
        fallback_status = mm.get_fallback_status() if mm else {'chain': [], 'provider_health': {}}

        # Provider key status (configured yes/no — NOT the keys themselves)
        providers_configured = {}
        for name, cfg in self.core.config.get('providers', {}).items():
            if name == 'ollama':
                providers_configured[name] = True  # Always "configured" (local)
            elif isinstance(cfg, dict):
                key = cfg.get('apiKey') or cfg.get('api_key') or ''
                providers_configured[name] = bool(key and key.strip() and key.strip() != '""')

        # Bridge statuses
        tg_cfg = self.core.config.get('telegram', {})
        discord_cfg = self.core.config.get('discord', {})
        gmail_cfg = self.core.config.get('gmail', {})
        wa_cfg = self.core.config.get('whatsapp', {})

        # Model config
        models_cfg = self.core.config.get('models', {})

        # Memory Stats (QoL/Premium Visibility)
        indexer = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'neural_indexer'), None)
        return web.json_response({
            'global_max_tokens': models_cfg.get('max_tokens', 0),
            'global_context_window': models_cfg.get('context_window', 0),
            # Core stats
            'uptime': uptime,
            'uptime_formatted': _fmt_uptime(uptime),
            'version': self.core.config.get('system', {}).get('version', '2.1.0'),
            'system_name': self.core.config.get('system', {}).get('name', 'Galactic AI'),
            'personality': (lambda p: getattr(p, 'display_name', None) or getattr(p, 'name', '--') if p else self.core.config.get('personality', {}).get('name', '--'))(getattr(self.core.gateway, 'personality', None)),
            'personality_mode': getattr(self.core.gateway, 'personality', None).mode if getattr(self.core.gateway, 'personality', None) else self.core.config.get('personality', {}).get('mode', 'byte'),
            'tokens_in': self.core.gateway.total_tokens_in,
            'tokens_out': self.core.gateway.total_tokens_out,

            # Model info
            'model': model_status,
            'primary_model': f"{mm.primary_provider}/{mm.primary_model}" if mm else '--',
            'fallback_model': f"{mm.fallback_provider}/{mm.fallback_model}" if mm else '--',
            'planner_model': f"{models_cfg.get('planner_provider', 'openrouter')}/{models_cfg.get('planner_model', 'openai/gpt-5.2')}",
            'planner_fallback_model': f"{models_cfg.get('planner_fallback_provider', 'openrouter')}/{models_cfg.get('planner_fallback_model', 'openai/gpt-5.2-codex')}",
            'boost_model': (f"{models_cfg['boost_provider']}/{models_cfg['boost_model']}"
                            if models_cfg.get('boost_provider') and models_cfg.get('boost_model') else ''),
            'require_approval': bool(models_cfg.get('require_approval')),
            'hybrid_coding_enabled': bool((models_cfg.get('hybrid_coding') or {}).get('enabled')),
            'architect_model': (lambda hc: f"{hc['architect_provider']}/{hc['architect_model']}"
                                if hc.get('architect_provider') and hc.get('architect_model') else '')(
                                    models_cfg.get('hybrid_coding') or {}),
            'builder_model': (lambda hc: f"{hc['builder_provider']}/{hc['builder_model']}"
                              if hc.get('builder_provider') and hc.get('builder_model') else '')(
                                  models_cfg.get('hybrid_coding') or {}),
            'summarizer_model': f"{models_cfg.get('summarizer_provider', 'ollama')}/{models_cfg.get('summarizer_model', 'qwen3.6:27b')}",
            'auto_fallback': mm.auto_fallback_enabled if mm else False,
            'smart_routing': models_cfg.get('smart_routing', False),
            'streaming': models_cfg.get('streaming', True),
            'max_turns': models_cfg.get('max_turns', 50),
            'speak_timeout': models_cfg.get('speak_timeout', 600),
            'autonomous_coding': self.core.config.get('coding_agent', {}).get('autonomous', False),
            'thinking_level': getattr(self.core.gateway, 'thinking_level', models_cfg.get('thinking_level', 'low')),
            
            'memory': {
                'vector_count': self._memory_row_count(),
                'auto_recall_enabled': any(getattr(s, 'skill_name', '') == 'conversation_auto_recall' for s in self.core.skills),
                'indexer_progress': getattr(indexer, 'progress', 0) if indexer else 0,
                'is_indexing': getattr(indexer, 'is_scanning', False) if indexer else False,
            },
            'nitro_only': models_cfg.get('nitro_only', False),

            # Fallback chain + health
            'fallback_chain': fallback_status.get('chain', []),
            'provider_health': fallback_status.get('provider_health', {}),

            # Providers
            'providers_configured': providers_configured,

            # Plugins
            'plugins': plugin_statuses,

            # Ollama
            'ollama': ollama_status,

            # Bridges
            'telegram': {
                'configured': bool(tg_cfg.get('bot_token')),
                'admin_chat_id': str(tg_cfg.get('admin_chat_id', '')),
            },
            'discord': {
                'configured': bool(discord_cfg.get('bot_token')),
            },
            'gmail': {
                'configured': bool(gmail_cfg.get('email')),
                'email': gmail_cfg.get('email', '--') or '--',
            },
            'whatsapp': {
                'configured': bool(wa_cfg.get('phone_number_id')),
            },

            # Scheduler
            'scheduled_tasks': len(getattr(self.core, 'scheduler', None) and getattr(self.core.scheduler, 'tasks', []) or []),
            'scheduler_running': getattr(getattr(self.core, 'scheduler', None), 'running', False),

            # Tool count
            'tool_count': len(self.core.gateway.tools) if hasattr(self.core, 'gateway') else 0,

            # Voice + update check (for Settings tab)
            'voice': self.core.config.get('voice_agent', {}).get('engine', 'edge-tts') if self.core.config.get('voice_agent', {}).get('engine', 'edge-tts') in ['piper', 'pyttsx3', 'gtts', 'chatterbox', 'fish-speech'] else self.core.config.get('elevenlabs', {}).get('voice', 'Guy'),
            'reference_audio': self.core.config.get('voice_agent', {}).get('reference_audio', ''),
            'wake_word_enabled': bool(self.core.config.get('voice_agent', {}).get('wake_word_enabled', True)),
            'wake_word_listening': bool(getattr(self._get_voice_agent_skill(), 'listening', False)),
            'update_check_interval': self.core.config.get('system', {}).get('update_check_interval', 21600),
        })

    async def handle_plugin_toggle(self, request):
        """POST /api/plugin_toggle — {name, enabled: bool}"""
        try:
            data = await request.json()
            name = data.get('name', '')
            enabled = data.get('enabled', True)
            for p in self.core.plugins:
                # Standardize plugin identification: prefer skill_name (v1.5.2)
                pname = getattr(p, 'skill_name', None) or getattr(p, 'name', p.__class__.__name__)
                if pname == name:
                    setattr(p, 'enabled', bool(enabled))
                    await self.core.log(f"Plugin {name}: {'ENABLED' if enabled else 'DISABLED'}", priority=2)
                    return web.json_response({'ok': True, 'name': name, 'enabled': enabled})
            return web.json_response({'error': f'Plugin not found: {name}'}, status=404)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_tool_invoke(self, request):
        """POST /api/tool_invoke — {tool, args} — directly invoke a gateway tool."""
        try:
            data = await request.json()
            tool_name = data.get('tool', '')
            args = data.get('args', {})
            if tool_name not in self.core.gateway.tools:
                return web.json_response({'error': f'Unknown tool: {tool_name}'}, status=404)
            tool_fn = self.core.gateway.tools[tool_name]['fn']
            result = await tool_fn(args)
            return web.json_response({'result': result})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_list_tools(self, request):
        """GET /api/tools — list all registered gateway tools."""
        tools = []
        for name, tool in self.core.gateway.tools.items():
            tools.append({
                'name': name,
                'description': tool.get('description', ''),
                'params': list(tool.get('parameters', {}).get('properties', {}).keys())
            })
        return web.json_response({'tools': tools, 'count': len(tools)})

    async def handle_list_plugins(self, request):
        """GET /api/plugins — list all loaded skills with rich metadata."""
        plugins = []
        for p in self.core.plugins:
            tool_names = list(p.get_tools().keys()) if hasattr(p, 'get_tools') else []
            s_name = getattr(p, 'skill_name', None) or getattr(p, 'name', p.__class__.__name__)
            # Use explicit display_name if provided, otherwise fall back to title-cased skill_name
            d_name = getattr(p, 'display_name', None) or s_name.replace('_', ' ').title()
            
            plugins.append({
                'name':         s_name,
                'display_name': d_name,
                'enabled':      getattr(p, 'enabled', True),
                'class':        p.__class__.__name__,
                'version':      getattr(p, 'version', '—'),
                'author':       getattr(p, 'author', '—'),
                'description':  getattr(p, 'description', p.__class__.__name__),
                'category':     getattr(p, 'category', 'general'),
                'icon':         getattr(p, 'icon', '⚙️'),
                'is_core':      getattr(p, 'is_core', False),
                'tools':        tool_names,
                'tool_count':   len(tool_names),
            })
        return web.json_response({'plugins': plugins})

    async def handle_switch_model(self, request):
        """POST /api/switch_model — {provider, model}"""
        try:
            data = await request.json()
            provider = data.get('provider', '')
            model = data.get('model', '')
            if not provider or not model:
                return web.json_response({'error': 'provider and model required'}, status=400)

            # If the AI is actively processing a task, queue the switch instead
            # of disrupting it mid-conversation (prevents smart-routing breakage)
            if getattr(self.core.gateway, '_speaking', False):
                self.core.gateway._queued_switch = (provider, model)
                # Still persist as new primary so it survives restarts
                if hasattr(self.core, 'model_manager'):
                    self.core.model_manager.primary_provider = provider
                    self.core.model_manager.primary_model = model
                    self.core.model_manager.current_mode = 'primary'
                    await self.core.model_manager._save_config()
                await self.core.log(
                    f"🔄 Model switch queued (task in progress): {model}", priority=2
                )
                return web.json_response({
                    'ok': True, 'queued': True, 'provider': provider, 'model': model,
                    'message': 'Model switch queued — will apply after current task completes'
                })

            self.core.gateway.llm.provider = provider
            self.core.gateway.llm.model = model
            if hasattr(self.core, 'model_manager'):
                self.core.model_manager._set_api_key(provider)
                # Persist as new primary so it survives restarts
                self.core.model_manager.primary_provider = provider
                self.core.model_manager.primary_model = model
                self.core.model_manager.current_mode = 'primary'
                try:
                    await self.core.model_manager._save_config()
                except Exception:
                    pass  # Prevent file lock recursion loops
            # Check if API key is actually configured
            current_key = getattr(self.core.gateway.llm, 'api_key', '')
            if provider not in ('ollama',) and (not current_key or current_key == 'NONE'):
                return web.json_response({'ok': False, 'needs_key': True, 'provider': provider, 'model': model})
            await self.core.log(f"Shifted Model via Web Deck: {model}", priority=2)
            return web.json_response({'ok': True, 'provider': provider, 'model': model})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_save_key(self, request):
        """POST /api/save_key — {provider, api_key} — save an API key and apply it."""
        try:
            import yaml
            data = await request.json()
            provider = data.get('provider', '')
            api_key = data.get('api_key', '').strip()
            if not provider or not api_key:
                return web.json_response({'error': 'provider and api_key required'}, status=400)
            # Update in-memory config
            cfg = self.core.config
            if 'providers' not in cfg:
                cfg['providers'] = {}
            if provider not in cfg['providers']:
                cfg['providers'][provider] = {}
            cfg['providers'][provider]['apiKey'] = api_key
            # Persist to config.yaml (safe read-modify-write with model-key protection)
            self._save_config(cfg)
            # Apply to live gateway
            self.core.gateway.llm.api_key = api_key
            await self.core.log(f"API key saved for {provider} via Web Deck", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    # ── Settings Endpoints ─────────────────────────────────────────────

    async def handle_settings_models(self, request):
        """POST /api/settings/models — save primary/fallback model + toggles."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        mm = getattr(self.core, 'model_manager', None)
        if not mm:
            return web.json_response({'error': 'Model manager not initialized'}, status=503)

        try:
            pp = data.get('primary_provider', '').strip()
            pm = data.get('primary_model', '').strip()
            fp = data.get('fallback_provider', '').strip()
            fm = data.get('fallback_model', '').strip()
            plp = data.get('planner_provider', '').strip()
            plm = data.get('planner_model', '').strip()
            plfp = data.get('planner_fallback_provider', '').strip()
            plfm = data.get('planner_fallback_model', '').strip()
            sp = data.get('summarizer_provider', '').strip()
            sm = data.get('summarizer_model', '').strip()

            if pp and pm:
                await mm.set_primary(pp, pm)
            if fp and fm:
                await mm.set_fallback(fp, fm)

            # Toggles & Planner — update in-memory, then save ONCE
            cfg = self.core.config
            cfg.setdefault('models', {})
            toggle_changed = False
            
            if plp and plm:
                if cfg['models'].get('planner_provider') != plp or cfg['models'].get('planner_model') != plm:
                    cfg['models']['planner_provider'] = plp
                    cfg['models']['planner_model'] = plm
                    toggle_changed = True
            if plfp and plfm:
                if cfg['models'].get('planner_fallback_provider') != plfp or cfg['models'].get('planner_fallback_model') != plfm:
                    cfg['models']['planner_fallback_provider'] = plfp
                    cfg['models']['planner_fallback_model'] = plfm
                    toggle_changed = True
            if sp and sm:
                if cfg['models'].get('summarizer_provider') != sp or cfg['models'].get('summarizer_model') != sm:
                    cfg['models']['summarizer_provider'] = sp
                    cfg['models']['summarizer_model'] = sm
                    toggle_changed = True

            # 🚀 Boost model (one-shot escalation target)
            bp = data.get('boost_provider', '').strip()
            bm = data.get('boost_model', '').strip()
            if bp and bm:
                if cfg['models'].get('boost_provider') != bp or cfg['models'].get('boost_model') != bm:
                    cfg['models']['boost_provider'] = bp
                    cfg['models']['boost_model'] = bm
                    toggle_changed = True

            # 🧬 Hybrid Coding Mode (Architect writes, Builder applies)
            if any(k in data for k in ('hybrid_coding_enabled', 'architect_provider', 'builder_provider')):
                hc = cfg['models'].setdefault('hybrid_coding', {})
                if 'hybrid_coding_enabled' in data and hc.get('enabled') != bool(data['hybrid_coding_enabled']):
                    hc['enabled'] = bool(data['hybrid_coding_enabled'])
                    toggle_changed = True
                ap = data.get('architect_provider', '').strip()
                am = data.get('architect_model', '').strip()
                if ap and am and (hc.get('architect_provider') != ap or hc.get('architect_model') != am):
                    hc['architect_provider'] = ap
                    hc['architect_model'] = am
                    toggle_changed = True
                bup = data.get('builder_provider', '').strip()
                bum = data.get('builder_model', '').strip()
                if bup and bum and (hc.get('builder_provider') != bup or hc.get('builder_model') != bum):
                    hc['builder_provider'] = bup
                    hc['builder_model'] = bum
                    toggle_changed = True

            if 'auto_fallback' in data:
                mm.auto_fallback_enabled = bool(data['auto_fallback'])
                cfg['models']['auto_fallback'] = mm.auto_fallback_enabled
                toggle_changed = True
            if 'smart_routing' in data:
                cfg['models']['smart_routing'] = bool(data['smart_routing'])
                toggle_changed = True
            if 'streaming' in data:
                cfg['models']['streaming'] = bool(data['streaming'])
                toggle_changed = True
            if 'nitro_only' in data:
                cfg['models']['nitro_only'] = bool(data['nitro_only'])
                toggle_changed = True
            if 'require_approval' in data:
                cfg['models']['require_approval'] = bool(data['require_approval'])
                toggle_changed = True
            if toggle_changed:
                self._save_config(cfg)

            await self.core.log("⚙️ Model settings updated via Settings tab", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_settings_voice(self, request):
        """POST /api/settings/voice — save default TTS voice."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        voice = (data.get('voice') or '').strip()
        if not voice:
            return web.json_response({'error': 'voice is required'}, status=400)

        cfg = self.core.config
        if 'voice_agent' not in cfg:
            cfg['voice_agent'] = {}
        if 'elevenlabs' not in cfg:
            cfg['elevenlabs'] = {}
            
        local_engines = ['piper', 'pyttsx3', 'chatterbox', 'fish-speech']
        edge_voices = ['Guy', 'Aria', 'Jenny', 'Steffan']
        eleven_voices = ['Nova', 'Byte']

        if 'reference_audio' in data:
            cfg['voice_agent']['reference_audio'] = data['reference_audio'].strip()

        if voice in local_engines:
            cfg['voice_agent']['engine'] = voice
            # Note: We don't change the character voice name for local engines here,
            # as they often have fixed models or read from defaults.
        else:
            # It's a specific character voice
            cfg['elevenlabs']['voice'] = voice
            
            if voice in edge_voices:
                cfg['voice_agent']['engine'] = 'edge-tts'
            elif voice in eleven_voices:
                cfg['voice_agent']['engine'] = 'elevenlabs'
            elif voice == 'gtts':
                cfg['voice_agent']['engine'] = 'gtts'

        try:
            self._save_config(cfg)
            engine_name = cfg['voice_agent'].get('engine', 'unknown')
            await self.core.log(f"🔊 Voice set to {voice} (Engine: {engine_name}) via Settings", priority=2)
            return web.json_response({'ok': True, 'voice': voice})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_settings_personality(self, request):
        """POST /api/settings/personality — save active personality."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        persona = (data.get('personality') or '').strip().lower()
        if not persona:
            return web.json_response({'error': 'personality is required'}, status=400)

        cfg = self.core.config
        if 'personality' not in cfg:
            cfg['personality'] = {}
        cfg['personality']['mode'] = persona
        try:
            self._save_config(cfg)
            # Live reload personality without touching files
            from personality import GalacticPersonality
            self.core.gateway.personality = GalacticPersonality(
                cfg, cfg.get('paths', {}).get('workspace')
            )
            await self.core.log(f"🧠 Personality changed to {persona.title()} via Settings", priority=2)
            return web.json_response({'ok': True, 'personality': persona})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_settings_system(self, request):
        """POST /api/settings/system — save system settings."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        cfg = self.core.config
        if 'system' not in cfg:
            cfg['system'] = {}
        if 'models' not in cfg:
            cfg['models'] = {}

        if 'update_check_interval' in data:
            try:
                cfg['system']['update_check_interval'] = int(data['update_check_interval'])
            except (TypeError, ValueError):
                pass

        if 'speak_timeout' in data:
            try:
                cfg['models']['speak_timeout'] = int(data['speak_timeout'])
            except (TypeError, ValueError):
                pass

        if 'max_turns' in data:
            try:
                cfg['models']['max_turns'] = int(data['max_turns'])
            except (TypeError, ValueError):
                pass

        if 'autonomous_coding' in data:
            if 'coding_agent' not in cfg:
                cfg['coding_agent'] = {}
            cfg['coding_agent']['autonomous'] = bool(data['autonomous_coding'])

        try:
            self._save_config(cfg)
            await self.core.log("⚙️ System settings updated via Settings tab", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_settings_thinking(self, request):
        """POST /api/settings/thinking — set thinking/reasoning level."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        level = str(data.get('level', 'low')).lower().strip()
        if level not in ('off', 'low', 'medium', 'high'):
            return web.json_response({'error': f'Invalid level: {level}'}, status=400)

        # Update gateway runtime
        gw = getattr(self.core, 'gateway', None)
        if gw:
            gw.thinking_level = level

        # Also update Telegram bridge if present
        tb = getattr(self.core, 'telegram_bridge', None)
        if tb:
            tb.thinking_level = level.upper()

        # Persist to config.yaml
        cfg = self.core.config
        cfg.setdefault('models', {})
        cfg['models']['thinking_level'] = level
        try:
            self._save_config(cfg)
            await self.core.log(f"🧠 Thinking level set to: {level.upper()}", priority=2)
            return web.json_response({'ok': True, 'level': level})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_doctor(self, request):
        """GET /api/doctor — on-demand health check (same checks as boot preflight)."""
        try:
            checks = await self.core.diagnostics()
            summary = {
                'ok': sum(1 for c in checks if c['status'] == 'ok'),
                'warn': sum(1 for c in checks if c['status'] == 'warn'),
                'info': sum(1 for c in checks if c['status'] == 'info'),
            }
            return web.json_response({'checks': checks, 'summary': summary,
                                      'healthy': summary['warn'] == 0})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_config_full(self, request):
        import config_loader
        data = config_loader.load_config(getattr(self.core, 'config_path', None))
        return web.json_response(data or {})

    async def handle_config_update(self, request):
        try:
            payload = await request.json()
            key_path = payload.get("key")
            value = payload.get("value")
            if not key_path:
                return web.json_response({"error": "No key provided"}, status=400)
            
            import config_loader
            cfg = config_loader.load_config(getattr(self.core, 'config_path', None)) or {}
                
            parts = key_path.split(".")
            d = cfg
            for p in parts[:-1]:
                if p not in d or not isinstance(d[p], dict):
                    d[p] = {}
                d = d[p]
                
            existing = d.get(parts[-1])
            if existing is not None:
                try:
                    if isinstance(existing, bool):
                        if str(value).lower() in ("true", "1", "yes"): value = True
                        elif str(value).lower() in ("false", "0", "no"): value = False
                        else: value = bool(value)
                    elif isinstance(existing, int):
                        value = int(value)
                    elif isinstance(existing, float):
                        value = float(value)
                except Exception:
                    pass
                    
            d[parts[-1]] = value
            self._save_config(cfg)
            return web.json_response({"status": "success", "key": key_path, "value": value})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_cli_sync(self, request):
        try:
            payload = await request.json()
            key = payload.get("key")
            value = payload.get("value")
            
            # Broadcast to CLI via websockets
            msg = json.dumps({"type": "cli_settings_sync", "data": {"key": key, "value": value}})
            for adapter in self.core.clients:
                if hasattr(adapter, 'ws') and not adapter.ws.closed:
                    asyncio.create_task(adapter.ws.send_str(msg))
                    
            return web.json_response({"status": "broadcasted"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_restart(self, request):
        """POST /api/restart — restart the Galactic AI process."""
        await self.core.log("🔄 Restart requested via Control Deck", priority=1)
        import sys, subprocess
        # Give the response time to reach the client before restarting
        async def _do_restart():
            await asyncio.sleep(1.5)
            await self.core.log("🔄 Restarting now...", priority=1)
            # Spawn a new process, then shut down this one cleanly
            subprocess.Popen([sys.executable] + sys.argv)
            # Trigger clean shutdown of this process
            shutdown_event = getattr(self.core, 'shutdown_event', None)
            if shutdown_event:
                shutdown_event.set()
            else:
                sys.exit(0)
        asyncio.create_task(_do_restart())
        return web.json_response({'ok': True, 'message': 'Restarting...'})

    async def handle_shutdown(self, request):
        """POST /api/shutdown — gracefully shut down Galactic AI."""
        await self.core.log("⏻ Shutdown requested via Control Deck", priority=1)
        async def _do_shutdown():
            await asyncio.sleep(1.5)
            await self.core.log("⏻ Shutting down now...", priority=1)
            # Trigger the proper shutdown chain via shutdown_event
            # This unblocks main_loop() → server.close() → self.shutdown() → clean exit
            shutdown_event = getattr(self.core, 'shutdown_event', None)
            if shutdown_event:
                shutdown_event.set()
            else:
                # Fallback: force exit if shutdown_event not available
                os._exit(0)
        asyncio.create_task(_do_shutdown())
        return web.json_response({'ok': True, 'message': 'Shutting down...'})

    async def handle_update(self, request):
        """POST /api/update — trigger the self-update script."""
        try:
            data = await request.json()
            force = data.get('force', False)
        except Exception:
            force = False

        self.core.log(f"🚀 Update triggered via Web Deck (force={force})", priority=1)

        try:
            # On Windows, we use Popen with DETACHED_PROCESS to ensure update.ps1 survives
            # The script itself handles backing up and relaunching.
            import subprocess
            import platform
            
            # Use 'powershell.exe' specifically to ensure consistent execution
            cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "update.ps1"]
            if force:
                cmd.append("-Force")
            
            # Trigger detached process
            if platform.system() == "Windows":
                # 0x00000008 is DETACHED_PROCESS
                subprocess.Popen(cmd, creationflags=0x00000008, close_fds=True, start_new_session=True)
            else:
                # Basic Linux support (sh-based update script would be needed)
                subprocess.Popen(cmd, start_new_session=True)
                
            return web.json_response({'ok': True, 'message': 'Update script launched.'})
        except Exception as e:
            self.core.log(f"❌ Error launching update script: {e}", priority=1)
            return web.json_response({'ok': False, 'error': str(e)})

    async def handle_browser_cmd(self, request):
        """POST /api/browser_cmd — {command, args} — browser quick commands."""
        try:
            data = await request.json()
            cmd = data.get('command', '')
            args = data.get('args', {})
            bp = next(
                (p for p in self.core.plugins
                 if 'BrowserExecutorPro' in p.__class__.__name__
                 or getattr(p, 'skill_name', '') == 'browser_pro'),
                None
            )
            if not bp:
                return web.json_response({'error': 'Browser plugin not loaded'}, status=503)
            method = getattr(bp, cmd, None)
            if not method or not callable(method):
                return web.json_response({'error': f'Unknown browser command: {cmd}'}, status=404)
            result = await method(**args)
            return web.json_response({'result': result})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    def _hash_password(self, password, salt=None, iterations=600000):
        """Secure PBKDF2 hashing with high iterations."""
        if salt is None: salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
        return f"{dk.hex()}:{salt}:{iterations}"

    async def handle_login(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'success': False, 'error': 'Invalid JSON'}, status=400)
        password = data.get('password', '')
        if not password:
            return web.json_response({'success': False, 'error': 'No password'}, status=400)

        current_hash_entry = (self.password_hash or "").strip()
        
        # 1. Handle First-Run or Placeholder
        if not current_hash_entry or current_hash_entry == "YOUR_PASSWORD_HASH" or current_hash_entry == "SHA256_HASH_OF_YOUR_PASSWORD":
            await self.core.log(f"[Auth] First-run bypass: setting master password", priority=2)
            new_entry = self._hash_password(password)
            self.password_hash = new_entry
            cfg = self.core.config
            if 'web' not in cfg: cfg['web'] = {}
            cfg['web']['password_hash'] = new_entry
            try: self._save_config(cfg)
            except: pass
            return web.json_response(self._make_token_response(new_entry))

        # 2. Verify Hashing
        if ':' in current_hash_entry:
            parts = current_hash_entry.split(':')
            try:
                if len(parts) == 3: # hash:salt:iterations
                    stored_h, salt, iters = parts
                    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iters))
                    if secrets.compare_digest(dk.hex(), stored_h):
                        return web.json_response(self._make_token_response(current_hash_entry))
                elif len(parts) == 2: # hash:salt (backward compatibility 100k)
                    stored_h, salt = parts
                    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
                    if secrets.compare_digest(dk.hex(), stored_h):
                        # Upgrade to 600k iterations
                        new_entry = self._hash_password(password)
                        self.password_hash = new_entry
                        cfg = self.core.config
                        if 'web' in cfg: cfg['web']['password_hash'] = new_entry
                        try: self._save_config(cfg)
                        except: pass
                        return web.json_response(self._make_token_response(new_entry))
            except: pass

        return web.json_response({'success': False, 'error': 'Invalid passphrase'}, status=401)

        return web.json_response({'success': False, 'error': 'Invalid passphrase'}, status=401)

    def _make_token_response(self, password_hash):
        """Build login response with JWT (remote mode) or legacy hash token."""
        if self.remote_access and self.jwt_secret:
            from remote_access import create_jwt
            jwt_token, expires = create_jwt(password_hash, self.jwt_secret)
            return {'success': True, 'token': jwt_token, 'expires': expires, 'jwt': True}
        return {'success': True, 'token': password_hash}

    async def handle_setup(self, request):
        """POST /api/setup — first-run configuration: save API keys, passwords, provider, etc."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        cfg = self.core.config

        # Password
        pw = data.get('password', '')
        if pw:
            h = self._hash_password(pw)
            if 'web' not in cfg:
                cfg['web'] = {}
            cfg['web']['password_hash'] = h
            cfg['web']['enabled'] = True
            cfg['web']['host'] = '127.0.0.1'
            cfg['web']['port'] = int(data.get('port', 17789))
            self.password_hash = h

        # Provider + model
        provider = data.get('provider', '')
        model = data.get('model', '')
        if provider and model:
            if 'gateway' not in cfg:
                cfg['gateway'] = {}
            cfg['gateway']['provider'] = provider
            cfg['gateway']['model'] = model
            cfg['gateway']['api_key'] = data.get('api_key', 'NONE')

        # API keys per provider
        if 'providers' not in cfg:
            cfg['providers'] = {}

        # Standard API-key providers (OpenAI-compatible)
        openai_compat_providers = {
            'google':      ('apiKey',  'https://generativelanguage.googleapis.com/v1beta'),
            'anthropic':   ('apiKey',  'https://api.anthropic.com/v1'),
            'openai':      ('apiKey',  'https://api.openai.com/v1'),
            'xai':         ('apiKey',  'https://api.x.ai/v1'),
            'groq':        ('apiKey',  'https://api.groq.com/openai/v1'),
            'mistral':     ('apiKey',  'https://api.mistral.ai/v1'),
            'cerebras':    ('apiKey',  'https://api.cerebras.ai/v1'),
            'openrouter':  ('apiKey',  'https://openrouter.ai/api/v1'),
            'huggingface': ('apiKey',  'https://router.huggingface.co/v1'),
            'kimi':        ('apiKey',  'https://api.kimi.com/v1'),
            'zai':         ('apiKey',  'https://api.z.ai/api/paas/v4'),
            'minimax':     ('apiKey',  'https://api.minimax.io/v1'),
        }
        for prov, (key_field, base_url) in openai_compat_providers.items():
            key = data.get(f'{prov}_key', '')
            if key:
                if prov not in cfg['providers']:
                    cfg['providers'][prov] = {}
                cfg['providers'][prov][key_field] = key
                if 'baseUrl' not in cfg['providers'][prov]:
                    cfg['providers'][prov]['baseUrl'] = base_url

        # NVIDIA — single unified API key (one key works for all 500+ models)
        nv_key = data.get('nvidia_key', '').strip()
        if nv_key:
            if 'nvidia' not in cfg['providers']:
                cfg['providers']['nvidia'] = {}
            cfg['providers']['nvidia']['apiKey'] = nv_key
            cfg['providers']['nvidia']['baseUrl'] = 'https://integrate.api.nvidia.com/v1'

        # Ollama URL
        ollama_url = data.get('ollama_url', '')
        if ollama_url:
            if 'ollama' not in cfg['providers']:
                cfg['providers']['ollama'] = {}
            cfg['providers']['ollama']['baseUrl'] = ollama_url

        # ElevenLabs TTS
        el_key = data.get('elevenlabs_key', '')
        el_voice = data.get('elevenlabs_voice', 'nova')
        if el_key or el_voice:
            if 'elevenlabs' not in cfg:
                cfg['elevenlabs'] = {}
            if el_key:
                cfg['elevenlabs']['api_key'] = el_key
            cfg['elevenlabs']['voice'] = el_voice or 'nova'

        # Telegram
        tg_token = data.get('telegram_token', '')
        tg_chat = data.get('telegram_chat_id', '')
        if tg_token or tg_chat:
            if 'telegram' not in cfg:
                cfg['telegram'] = {}
            if tg_token:
                cfg['telegram']['bot_token'] = tg_token
            if tg_chat:
                cfg['telegram']['admin_chat_id'] = tg_chat

        # System name
        name = data.get('system_name', '')
        if name:
            if 'system' not in cfg:
                cfg['system'] = {}
            cfg['system']['name'] = name

        # Save personality config
        persona_mode = data.get('persona_mode', 'byte')
        persona_name = data.get('persona_name', '')
        persona_soul = data.get('persona_soul', '')
        persona_context = data.get('persona_context', '')
        if 'personality' not in cfg:
            cfg['personality'] = {}
        cfg['personality']['mode'] = persona_mode
        if persona_mode == 'custom':
            cfg['personality']['name'] = persona_name or 'Assistant'
            cfg['personality']['soul'] = persona_soul or 'Be helpful, accurate, and concise.'
            cfg['personality']['user_context'] = persona_context
        elif persona_mode == 'byte':
            cfg['personality']['name'] = 'Byte'
        elif persona_mode == 'generic':
            cfg['personality']['name'] = 'Assistant'

        # Save (safe read-modify-write)
        try:
            # Update ModelManager so defensive writeback preserves the wizard's choice
            if provider and model:
                mm = getattr(self.core, 'model_manager', None)
                if mm:
                    mm.primary_provider = provider
                    mm.primary_model = model
            self._save_config(cfg)
            # Apply to live gateway immediately
            if provider and model:
                self.core.gateway.llm.provider = provider
                self.core.gateway.llm.model = model
                self.core.gateway.llm.api_key = data.get('api_key', 'NONE')
            return web.json_response({'ok': True, 'message': 'Configuration saved!'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_check_setup(self, request):
        """GET /api/check_setup — returns whether first-run setup is needed."""
        cfg = self.core.config
        has_any_key = any([
            cfg.get('providers', {}).get('google', {}).get('apiKey', ''),
            cfg.get('providers', {}).get('anthropic', {}).get('apiKey', ''),
            cfg.get('providers', {}).get('xai', {}).get('apiKey', ''),
            cfg.get('providers', {}).get('nvidia', {}).get('keys', {}),
            cfg.get('gateway', {}).get('provider', '') == 'ollama',
        ])
        has_password = bool(self.password_hash)
        needs_setup = not has_any_key
        return web.json_response({
            'needs_setup': needs_setup,
            'has_password': has_password,
            'has_any_key': has_any_key,
            'current_provider': cfg.get('gateway', {}).get('provider', ''),
            'current_model': cfg.get('gateway', {}).get('model', ''),
        })

    async def handle_check_openclaw(self, request):
        """GET /api/check_openclaw — detect OpenClaw installation and list importable .md files."""
        import pathlib
        openclaw_workspace = pathlib.Path.home() / '.openclaw' / 'workspace'
        md_files = ['USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md', 'VAULT.md']
        found_files = []
        if openclaw_workspace.exists():
            for f in md_files:
                if (openclaw_workspace / f).exists():
                    found_files.append(f)
            return web.json_response({
                'found': True,
                'path': str(openclaw_workspace),
                'files': found_files
            })
        return web.json_response({'found': False, 'path': '', 'files': []})

    async def handle_migrate_openclaw(self, request):
        """POST /api/migrate_openclaw — copy selected .md files from OpenClaw workspace."""
        import pathlib, shutil
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        files_to_import = data.get('files', [])
        if not files_to_import:
            return web.json_response({'error': 'No files specified'}, status=400)
        openclaw_workspace = pathlib.Path.home() / '.openclaw' / 'workspace'
        if not openclaw_workspace.exists():
            return web.json_response({'error': 'OpenClaw workspace not found'}, status=404)
        # Destination: one level up from this file (the workspace parent dir)
        dest_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__))).parent
        imported = []
        failed = []
        allowed = {'USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md', 'VAULT.md'}
        for fname in files_to_import:
            if fname not in allowed:
                failed.append(fname + ' (not allowed)')
                continue
            src = os.path.abspath(openclaw_workspace / fname)
            dst = os.path.abspath(dest_dir / fname)
            
            # Security: verify source is within openclaw_workspace and dest is within dest_dir
            if not src.startswith(str(openclaw_workspace) + os.sep):
                failed.append(f"{fname} (source outside workspace)")
                continue
            if not dst.startswith(str(dest_dir) + os.sep):
                failed.append(f"{fname} (destination outside workspace)")
                continue

            try:
                shutil.copy2(src, dst)
                imported.append(fname)
                await self.core.log(f"Migrated from OpenClaw: {fname}", priority=2)
            except Exception as e:
                failed.append(f"{fname} ({e})")
        return web.json_response({'ok': True, 'imported': imported, 'failed': failed})

    async def handle_model_config(self, request):
        """POST /api/model_config — {max_tokens, context_window} — persist per-session model config."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        import yaml
        cfg = self.core.config
        if 'models' not in cfg:
            cfg['models'] = {}
        max_tokens = data.get('max_tokens')
        context_window = data.get('context_window')
        if max_tokens is not None:
            try:
                cfg['models']['max_tokens'] = int(max_tokens) if max_tokens else 0
            except (ValueError, TypeError):
                pass
        if context_window is not None:
            try:
                cfg['models']['context_window'] = int(context_window) if context_window else 0
            except (ValueError, TypeError):
                pass
        if 'nitro_only' in data:
            cfg['models']['nitro_only'] = bool(data['nitro_only'])
        if 'nitro_only' in data:
            cfg['models']['nitro_only'] = bool(data['nitro_only'])
        # Persist to config.yaml (safe read-modify-write)
        try:
            self._save_config(cfg)
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})
        return web.json_response({'ok': True, 'max_tokens': cfg['models'].get('max_tokens', 0), 'context_window': cfg['models'].get('context_window', 0)})

    def _save_config(self, cfg):
        """Safely merge in-memory config into config.local.yaml (read-modify-write).

        Uses deep_merge_safe to prevent memory placeholders from erasing disk values.
        All writes land in the gitignored overlay — the tracked config.yaml
        template is never modified.
        """
        import config_loader
        cfg_path = getattr(self.core, 'config_path', None)

        # 1. Read existing merged config (template + overlay) to preserve all keys
        try:
            on_disk = config_loader.load_config(cfg_path)
        except Exception:
            on_disk = {}

        # 2. Define placeholder patterns to avoid overwriting real data with defaults
        PLACEHOLDERS = {
            "YOUR_GOOGLE_API_KEY", "YOUR_OPENROUTER_API_KEY", "YOUR_ANTHROPIC_API_KEY",
            "YOUR_OPENAI_API_KEY", "YOUR_XAI_API_KEY", "YOUR_GROQ_API_KEY",
            "YOUR_DEEPSEEK_API_KEY", "YOUR_NVIDIA_API_KEY", "YOUR_TELEGRAM_BOT_TOKEN",
            "YOUR_TELEGRAM_CHAT_ID", "YOUR_DISCORD_BOT_TOKEN", "YOUR_DISCORD_USER_ID",
            "YOUR_WHATSAPP_ACCESS_TOKEN", "YOUR_PHONE_NUMBER_ID", "YOUR_PHONE_NUMBER",
            "YOUR_WEBHOOK_VERIFY_TOKEN", "YOUR_GMAIL_APP_PASSWORD", "your-email@example.com",
            "SHA256_HASH_OF_YOUR_PASSWORD", "GENERATE_A_RANDOM_SECRET_FOR_SECURITY"
        }

        def deep_merge_safe(source, destination):
            """Merge source into destination, skipping placeholder values."""
            for key, value in source.items():
                if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
                    deep_merge_safe(value, destination[key])
                else:
                    # Skip if the source value is a placeholder and the destination has SOMETHING else
                    is_placeholder = isinstance(value, str) and (
                        value in PLACEHOLDERS or value.startswith("YOUR_") or "API_KEY" in value.upper()
                    )
                    
                    has_real_value = key in destination and destination[key]
                    if has_real_value and isinstance(destination[key], str) and destination[key] in PLACEHOLDERS:
                        has_real_value = False
                    if is_placeholder and has_real_value:
                        continue # Keep the real value on disk
                    destination[key] = value
            return destination

        # 3. Perform the safe merge
        _REPLACE_KEYS = {'model_overrides', 'aliases'} 
        for key, value in cfg.items():
            if key in _REPLACE_KEYS:
                on_disk[key] = value # Explicitly requested full replacement
            elif isinstance(value, dict) and key in on_disk and isinstance(on_disk[key], dict):
                deep_merge_safe(value, on_disk[key])
            else:
                on_disk[key] = value

        # 4. Mandatory sync for models (ModelManager is source of truth)
        mm = getattr(self.core, 'model_manager', None)
        if mm:
            on_disk.setdefault('models', {})
            on_disk['models'].update({
                'primary_provider': mm.primary_provider,
                'primary_model': mm.primary_model,
                'fallback_provider': mm.fallback_provider,
                'fallback_model': mm.fallback_model
            })

        # 5. Write back safely — to the overlay only
        config_loader.save_config(on_disk, cfg_path)

    async def handle_get_model_overrides(self, request):
        """GET /api/model_overrides — return all per-model overrides."""
        overrides = self.core.config.get('model_overrides') or {}
        return web.json_response({'overrides': overrides})

    async def handle_set_model_override(self, request):
        """POST /api/model_overrides — {model, max_tokens, context_window}"""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        model = (data.get('model') or '').strip()
        if not model:
            return web.json_response({'error': 'model is required'}, status=400)
        cfg = self.core.config
        if 'model_overrides' not in cfg or not isinstance(cfg.get('model_overrides'), dict):
            cfg['model_overrides'] = {}
        entry = cfg['model_overrides'].get(model) or {}
        max_tokens = data.get('max_tokens')
        context_window = data.get('context_window')
        if max_tokens is not None:
            try:
                entry['max_tokens'] = int(max_tokens)
            except (TypeError, ValueError):
                pass
        if context_window is not None:
            try:
                entry['context_window'] = int(context_window)
            except (TypeError, ValueError):
                pass
        cfg['model_overrides'][model] = entry
        try:
            self._save_config(cfg)
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})
        return web.json_response({'ok': True, 'model': model, 'entry': entry})

    async def handle_delete_model_override(self, request):
        """DELETE /api/model_overrides — {model}"""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        model = (data.get('model') or '').strip()
        cfg = self.core.config
        overrides = cfg.get('model_overrides') or {}
        if model in overrides:
            del overrides[model]
            cfg['model_overrides'] = overrides
            try:
                self._save_config(cfg)
            except Exception as e:
                return web.json_response({'ok': False, 'error': str(e)})
        return web.json_response({'ok': True})

    # ── Chrome Bridge WebSocket ────────────────────────────────────────
    async def handle_chrome_bridge_ws(self, request):
        """WebSocket endpoint for the Galactic Browser Chrome extension."""
        ws = web.WebSocketResponse(heartbeat=30)
        try:
            await ws.prepare(request)
        except Exception:
            return ws

        token = request.query.get('token')
        # Accept either legacy password hash or JWT token
        # First-run logic: if current hash is unset or the placeholder, accept the incoming token and save it
        current_hash = (self.password_hash or "").strip()
        if (not current_hash or current_hash == "SHA256_HASH_OF_YOUR_PASSWORD") and token:
            await self.core.log(f"[Chrome Bridge] First-run bypass: setting master password from extension", priority=2)
            self.password_hash = token
            cfg = self.core.config
            if 'web' not in cfg: cfg['web'] = {}
            cfg['web']['password_hash'] = token
            try: self._save_config(cfg)
            except: pass
            token_valid = True
        else:
            token_valid = (token == self.password_hash)
            if not token_valid and self.jwt_secret:
                from remote_access import verify_jwt
                token_valid = verify_jwt(token, self.jwt_secret)
        
        if not token_valid:
            await self.core.log(f"[Chrome Bridge] Auth failed for token: {token[:8]}...", priority=1)
            await ws.close(code=4001)
            return ws

        # ... (rest of the setup logic remains identical) ...
        bridge = next(
            (p for p in self.core.plugins
             if 'ChromeBridge' in p.__class__.__name__
             or getattr(p, 'skill_name', '') == 'chrome_bridge'),
            None
        )
        if not bridge:
            await ws.send_str(json.dumps({'type': 'error', 'message': 'ChromeBridge plugin not loaded'}))
            await ws.close(code=4002)
            return ws

        # Register the WebSocket with the bridge plugin
        bridge.ws_connection = ws
        await self.core.log("[Chrome Bridge] Extension connected", priority=2)

        # Send hello acknowledgement
        await ws.send_str(json.dumps({'type': 'hello', 'status': 'connected', 'version': '1.4.9'}))

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        # Pass raw string — handle_ws_message does its own json.loads()
                        await bridge.handle_ws_message(msg.data)
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        await self.core.log(f"[Chrome Bridge] Message error: {e}", priority=1)
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        except Exception as e:
            await self.core.log(f"[Chrome Bridge] Connection error: {e}", priority=1)
        finally:
            bridge.ws_connection = None
            # Cancel any pending futures
            for req_id, fut in list(bridge._pending.items()):
                if not fut.done():
                    fut.set_exception(ConnectionError("Chrome extension disconnected"))
            bridge._pending.clear()
            await self.core.log("[Chrome Bridge] Extension disconnected", priority=2)
        return ws

    # ── Virtual Terminal WebSocket ──────────────────────────────────────
    async def handle_terminal_ws(self, request):
        """WebSocket endpoint for the Virtual Gemini Terminal."""
        ws = web.WebSocketResponse(heartbeat=30)
        try:
            await ws.prepare(request)
        except Exception:
            return ws

        # Auth check
        token = request.query.get('token')
        token_valid = (token == self.password_hash)
        if not token_valid and self.jwt_secret:
            from remote_access import verify_jwt
            token_valid = verify_jwt(token, self.jwt_secret)
        if not token_valid:
            await ws.close(code=4001)
            return ws

        # Setup environment with current keys
        env = os.environ.copy()
        google_api_key = self.core.config.get('providers', {}).get('google', {}).get('apiKey')
        if google_api_key:
            env['GOOGLE_API_KEY'] = google_api_key
            env['GEMINI_API_KEY'] = google_api_key

        # Spawn a shell process
        shell_cmd = "cmd.exe" if os.name == 'nt' else "bash"
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=self.core.config.get('system', {}).get('workspace_dir', os.getcwd())
        )

        async def read_stdout():
            try:
                while True:
                    data = await process.stdout.read(4096)
                    if not data:
                        break
                    try:
                        text = data.decode('utf-8', errors='replace')
                    except Exception:
                        text = repr(data)
                    if text and not ws.closed:
                        await ws.send_str(json.dumps({'type': 'output', 'data': text}))
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        stdout_task = asyncio.create_task(read_stdout())

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    p = json.loads(msg.data)
                    if p['type'] == 'input':
                        raw = p['data']
                        try:
                            process.stdin.write(raw.encode('utf-8'))
                            await process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                        # Local echo: piped stdin doesn't echo on Windows
                        if not ws.closed:
                            echo = raw.replace('\r', '\r\n')
                            await ws.send_str(json.dumps({'type': 'output', 'data': echo}))
                    elif p['type'] == 'command':
                        cmd = p['data']
                        if cmd == 'gemini':
                            launch_cmd = 'npx -y @google/gemini-cli\n'
                        else:
                            launch_cmd = f'{cmd}\n'
                        try:
                            process.stdin.write(launch_cmd.encode('utf-8'))
                            await process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        except Exception:
            pass
        finally:
            if not stdout_task.done():
                stdout_task.cancel()
            try:
                await stdout_task
            except (asyncio.CancelledError, Exception):
                pass
            # Safely terminate the subprocess
            try:
                if process.returncode is None:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        pass
            except Exception:
                pass
            if not ws.closed:
                await ws.close()
        return ws

    async def handle_stream(self, request):
        ws = web.WebSocketResponse()
        try:
            await ws.prepare(request)
        except Exception:
            return ws

        # Local connections (127.0.0.1, ::1) bypass token auth — matches
        # the middleware pattern in remote_access.py so the Chrome extension
        # side-panel (which connects without a token) works from localhost.
        peername = request.transport.get_extra_info('peername')
        client_ip = peername[0] if peername else (request.remote or '127.0.0.1')
        is_local = client_ip in {'127.0.0.1', '::1', 'localhost'}

        if not is_local:
            token = request.query.get('token')
            # Accept either legacy password hash or JWT token
            token_valid = (token == self.password_hash)
            if not token_valid and self.jwt_secret:
                from remote_access import verify_jwt
                token_valid = verify_jwt(token, self.jwt_secret)
            if not token_valid:
                await ws.close(code=4001)
                return ws

        web_deck = self
        class WebAdapter:
            MAX_QUEUE = 500          # frames; token chunks are small, 500 ≈ seconds of stream
            OVERFLOW_STRIKES = 3     # consecutive overflows before we give up on the client

            def __init__(self, ws):
                self.ws = ws
                self._send_queue = asyncio.Queue(maxsize=self.MAX_QUEUE)
                self._overflows = 0
                self._send_task = asyncio.create_task(self._send_loop())

            async def _send_loop(self):
                while not self.ws.closed:
                    try:
                        msg = await self._send_queue.get()
                        if msg is None: break
                        await self.ws.send_str(msg)
                        self._send_queue.task_done()
                    except Exception:
                        break

            def write(self, data):
                decoded = data.decode()
                try:
                    self._send_queue.put_nowait(decoded)
                    self._overflows = 0
                except asyncio.QueueFull:
                    # Slow/wedged client: drop the oldest frame to make room so
                    # the newest state wins. Repeated overflow = dead client.
                    self._overflows += 1
                    try:
                        self._send_queue.get_nowait()
                        self._send_queue.put_nowait(decoded)
                    except Exception:
                        pass
                    if self._overflows >= self.OVERFLOW_STRIKES * self.MAX_QUEUE:
                        asyncio.ensure_future(self.ws.close(code=1011))
                try:
                    msg = json.loads(decoded.strip())
                    if msg.get('type') == 'agent_trace' and msg.get('data'):
                        web_deck.trace_buffer.append(msg['data'])
                        if len(web_deck.trace_buffer) > 500:
                            web_deck.trace_buffer = web_deck.trace_buffer[-500:]
                except Exception:
                    pass
            async def drain(self): pass

        adapter = WebAdapter(ws)
        self.core.clients.append(adapter)
        
        # Start a periodic update task for this specific socket
        async def updater():
            while not ws.closed:
                try:
                    uptime = int(time.time() - self.core.start_time)
                    plugins_status = {
                        "sniper": next((p.enabled for p in self.core.plugins if "Sniper" in p.name), False),
                        "watchdog": next((p.enabled for p in self.core.plugins if "Watchdog" in p.name), False)
                    }
                    _ctx_used, _ctx_max = self._context_usage()
                    telemetry = {
                        "type": "telemetry",
                        "data": {
                            "model": self.core.gateway.llm.model,
                            "provider": self.core.gateway.llm.provider,
                            "tin": self.core.gateway.total_tokens_in,
                            "tout": self.core.gateway.total_tokens_out,
                            "uptime": uptime,
                            "ctx_used": _ctx_used,
                            "ctx_max": _ctx_max,
                            "plugins": plugins_status
                        }
                    }
                    await ws.send_str(json.dumps(telemetry))
                    
                    # Update Aura Imprints
                    aura_data = {
                        "type": "aura_update",
                        "data": self.core.memory.index.get('memories', [])[-15:]
                    }
                    await ws.send_str(json.dumps(aura_data))
                    
                    await asyncio.sleep(2)
                except: break

        update_task = asyncio.create_task(updater())
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    if payload.get('type') == 'chat':
                        response = await self.core.gateway.speak(payload['data'])
                        await self.core.log(f"[Web] User: {payload['data']}", priority=3)
                        await self.core.log(f"[Core] {getattr(self.core.gateway.personality, 'display_name', self.core.gateway.personality.name)}: {response}", priority=3)
                    elif payload.get('type') == 'switch_model':
                        prov = payload['provider']
                        mod = payload['model']
                        
                        # Use ModelManager for resolution and persistent selection
                        model_mgr = getattr(self.core, 'model_manager', None)
                        if model_mgr:
                            resolved_id = model_mgr.resolve_model_id(mod)
                            # If resolved ID includes a provider (provider/model), split it
                            if '/' in resolved_id:
                                parts = resolved_id.split('/')
                                if parts[0] in ['google', 'nvidia', 'groq', 'cerebras', 'ollama', 'openrouter']:
                                    prov, mod = parts[0], "/".join(parts[1:])
                                else:
                                    mod = resolved_id
                            else:
                                mod = resolved_id
                            
                            await model_mgr.set_primary(prov, mod)
                        else:
                            # Fallback if model_manager is missing
                            self.core.gateway.llm.provider = prov
                            self.core.gateway.llm.model = mod
                        
                        if prov == 'google': self.core.gateway.llm.api_key = self.core.config['providers']['google']['apiKey']
                        elif prov == 'nvidia':
                            keys = self.core.config['providers']['nvidia']['keys']
                            if "deepseek" in mod: self.core.gateway.llm.api_key = keys['deepseek']
                            elif "qwen" in mod: self.core.gateway.llm.api_key = keys['qwen']
                        await self.core.log(f"Shifted Model via Web Deck: {mod} ({prov})", priority=1)
                    elif payload.get('type') == 'toggle_plugin':
                        name = payload['name']
                        state = payload['state']
                        plugin = next((p for p in self.core.plugins if name in p.name.lower()), None)
                        if plugin:
                            plugin.enabled = state
                            action = "Activated" if state else "Deactivated"
                            await self.core.log(f"Plugin {plugin.name} {action} via Web Deck", priority=2)
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            update_task.cancel()
            adapter._send_task.cancel()
            self.core.clients.remove(adapter)
            
        return ws

    async def handle_history(self, request):
        """GET /api/history — return last N chat messages for UI restore on page refresh."""
        try:
            import json as _json
            limit = int(request.query.get('limit', '50'))
            history_file = getattr(self.core.gateway, 'history_file', '')
            entries = []
            if history_file and os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for line in lines[-(limit * 2):]:  # Read 2x limit to account for user+bot pairs
                    try:
                        entries.append(_json.loads(line.strip()))
                    except Exception:
                        pass
                # Return only last `limit` entries
                entries = entries[-limit:]
            return web.json_response({'messages': entries})
        except Exception as e:
            return web.json_response({'messages': [], 'error': str(e)})

    async def handle_history_load(self, request):
        """POST /api/history/load - overwrite the current session history with provided data."""
        try:
            import json as _json
            data = await request.json()
            history = data.get('history', [])
            
            # Overwrite memory history array
            self.core.gateway.history = history
            
            # Overwrite history file on disk
            history_file = getattr(self.core.gateway, 'history_file', '')
            if history_file:
                with open(history_file, 'w', encoding='utf-8') as f:
                    for msg in history:
                        f.write(_json.dumps(msg, ensure_ascii=False) + '\n')
                        
            await self.core.log(f"Session context synced from CLI load ({len(history)} messages).", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)

    # ── Named chat sessions ─────────────────────────────────────────────────────

    def _sessions_dir(self):
        logs = self.core.config.get('paths', {}).get('logs', './logs')
        d = os.path.join(logs, 'sessions')
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _safe_session_name(name):
        import re
        n = re.sub(r'[^A-Za-z0-9 _\-]+', '', (name or '').strip())
        return n[:60].strip()

    async def handle_sessions_list(self, request):
        """GET /api/sessions — list saved sessions with message count + mtime."""
        import json as _json
        d = self._sessions_dir()
        out = []
        try:
            for fn in os.listdir(d):
                if not fn.endswith('.jsonl'):
                    continue
                path = os.path.join(d, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        count = sum(1 for line in f if line.strip())
                except Exception:
                    count = 0
                out.append({
                    'name': fn[:-6],
                    'messages': count,
                    'updated': int(os.path.getmtime(path)),
                })
            out.sort(key=lambda s: s['updated'], reverse=True)
        except Exception as e:
            return web.json_response({'sessions': [], 'error': str(e)})
        return web.json_response({'sessions': out})

    async def handle_session_save(self, request):
        """POST /api/sessions/save — {name} — snapshot the current chat to a named session."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        name = self._safe_session_name(data.get('name'))
        if not name:
            return web.json_response({'error': 'A valid session name is required'}, status=400)
        import json as _json
        dest = os.path.join(self._sessions_dir(), name + '.jsonl')
        history_file = getattr(self.core.gateway, 'history_file', '')
        try:
            if history_file and os.path.exists(history_file):
                import shutil
                shutil.copyfile(history_file, dest)
            else:
                # Fall back to the in-memory history
                with open(dest, 'w', encoding='utf-8') as f:
                    for msg in (self.core.gateway.history or []):
                        f.write(_json.dumps(msg, ensure_ascii=False) + '\n')
            with open(dest, 'r', encoding='utf-8') as f:
                count = sum(1 for line in f if line.strip())
            await self.core.log(f"💾 Chat session saved: '{name}' ({count} messages)", priority=2)
            return web.json_response({'ok': True, 'name': name, 'messages': count})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)

    async def handle_session_switch(self, request):
        """POST /api/sessions/switch — {name} — load a saved session as the live chat."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        name = self._safe_session_name(data.get('name'))
        src = os.path.join(self._sessions_dir(), name + '.jsonl')
        if not name or not os.path.exists(src):
            return web.json_response({'error': 'Session not found'}, status=404)
        import json as _json
        try:
            entries = []
            with open(src, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(_json.loads(line))
                    except Exception:
                        pass
            # Rebuild the gateway's in-memory context (role/content only, recent tail)
            norm = [{'role': e['role'], 'content': e['content']}
                    for e in entries if e.get('role') and e.get('content') is not None]
            self.core.gateway.history = norm[-20:]
            # Make it the persistent live history so a restart restores it too.
            history_file = getattr(self.core.gateway, 'history_file', '')
            if history_file:
                with open(history_file, 'w', encoding='utf-8') as f:
                    for e in entries:
                        f.write(_json.dumps(e, ensure_ascii=False) + '\n')
            await self.core.log(f"🔀 Switched to chat session '{name}' ({len(norm)} messages).", priority=2)
            return web.json_response({'ok': True, 'name': name, 'messages': entries})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)

    async def handle_session_delete(self, request):
        """POST /api/sessions/delete — {name} — remove a saved session file."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        name = self._safe_session_name(data.get('name'))
        src = os.path.join(self._sessions_dir(), name + '.jsonl')
        if not name or not os.path.exists(src):
            return web.json_response({'error': 'Session not found'}, status=404)
        try:
            os.remove(src)
            await self.core.log(f"🗑️ Deleted chat session '{name}'.", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)}, status=500)

    async def handle_logs(self, request):
        """GET /api/logs — return last N log lines for UI restore on page refresh.

        Query params:
          limit=200           — number of lines to return (default 200)
          component=telegram  — if set, read the component daily log instead of system_log.txt
                                Valid: gateway, telegram, web_deck, discord, gmail, whatsapp, core
        """
        try:
            import glob as _glob
            limit = int(request.query.get('limit', '200'))
            component = request.query.get('component', '').strip().lower()
            logs_dir = self.core.config.get('paths', {}).get('logs', './logs')

            if component:
                VALID = {'gateway', 'telegram', 'web_deck', 'discord', 'gmail', 'whatsapp', 'core'}
                if component not in VALID:
                    return web.json_response({'logs': [], 'error': f'Unknown component: {component}'}, status=400)
                # Find most recent daily log file for this component
                matches = sorted(_glob.glob(os.path.join(logs_dir, f"{component}_*.log")), reverse=True)
                if not matches:
                    return web.json_response({'logs': [], 'component': component})
                log_file = matches[0]
            else:
                log_file = os.path.join(logs_dir, 'system_log.txt')

            lines = []
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                lines = [l.rstrip('\n') for l in lines[-limit:]]
            return web.json_response({'logs': lines, 'component': component or 'system'})
        except Exception as e:
            return web.json_response({'logs': [], 'error': str(e)})

    async def handle_traces(self, request):
        """GET /api/traces — return buffered agent trace entries for Thinking tab restore."""
        return web.json_response({'traces': self.trace_buffer[-500:]})

    async def handle_list_files(self, request):
        """List workspace files — auto-creates missing .md files with starter templates and personality scoping."""
        try:
            workspace = self.core.config.get('paths', {}).get('workspace', '')
            if not workspace:
                workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
            os.makedirs(workspace, exist_ok=True)
            mode = self.core.config.get('personality', {}).get('mode', 'byte')

            # Auto-create missing .md files with defaults
            DEFAULTS = {
                'MEMORY.md': '# Memory\n\nThe AI will store important things here.\n',
                'IDENTITY.md': '# Identity\n\nDefine who your AI is here.\n',
                'SOUL.md': '# Soul\n\nDefine your AI\'s core values and personality here.\n',
            }

            GLOBAL_DEFAULTS = {
                'USER.md': '# User Profile\n\nTell your AI about yourself here.\n',
                'TOOLS.md': '# Tools\n\nNotes about available tools and workflows.\n',
                'VAULT.md': '# VAULT — Personal Credentials & Private Data\n\nStore login credentials, API keys, and personal info here.\nThe AI loads this file into every prompt for automation tasks.\n**Never share this file publicly.**\n',
            }

            active_files = []
            
            for fname, default_content in DEFAULTS.items():
                base, ext = os.path.splitext(fname)
                mode_fname = f"{base}_{mode}{ext}"
                
                fpath_mode = os.path.join(workspace, mode_fname)
                fpath_generic = os.path.join(workspace, fname)
                
                if os.path.exists(fpath_mode):
                    active_files.append(mode_fname)
                else:
                    # Auto-create mode file by cloning generic file or using default
                    content_to_write = default_content
                    if os.path.exists(fpath_generic):
                        try:
                            with open(fpath_generic, 'r', encoding='utf-8') as gf:
                                content_to_write = gf.read()
                        except Exception:
                            pass
                    try:
                        with open(fpath_mode, 'w', encoding='utf-8') as f:
                            f.write(content_to_write)
                        active_files.append(mode_fname)
                    except Exception:
                        active_files.append(fname)

            # Global files that shouldn't be duplicated per-personality
            for fname, default_content in GLOBAL_DEFAULTS.items():
                fpath = os.path.join(workspace, fname)
                if not os.path.exists(fpath):
                    try:
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(default_content)
                    except Exception:
                        pass
                active_files.append(fname)
                
            if os.path.exists(os.path.join(workspace, 'HEARTBEAT.md')):
                active_files.append('HEARTBEAT.md')

            files = []
            workspace_abs = os.path.abspath(workspace)
            for f in active_files:
                path = os.path.abspath(os.path.join(workspace_abs, f))
                # Security: verify path is within workspace
                if not path.startswith(workspace_abs + os.sep) and path != workspace_abs:
                    continue
                if os.path.exists(path):
                    files.append({'name': f, 'size': os.path.getsize(path)})
            return web.json_response({'files': files})
        except Exception as e:
            return web.json_response({'files': [], 'error': str(e)})
    
    async def handle_get_models(self, request):
        """Serve the models.yaml file to the frontend."""
        try:
            import yaml
            project_root = self.core.config.get('paths', {}).get('workspace', '.')
            models_path = os.path.join(project_root, 'config', 'models.yaml')
            if not os.path.exists(models_path):
                models_path = os.path.join(os.path.dirname(__file__), 'config', 'models.yaml')
                if not os.path.exists(models_path):
                    return web.json_response({'providers': {}})
            with open(models_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            out_map = {}
            for prov, items in data.get('providers', {}).items():
                filtered = []
                for i in items:
                    if i.get('enabled', True):
                        i_copy = dict(i)
                        i_copy['provider'] = prov
                        filtered.append(i_copy)
                if filtered:
                    out_map[prov] = filtered
            return web.json_response({'providers': out_map})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_file(self, request):
        """Get file contents"""
        filename = request.query.get('name')
        if not filename or not filename.endswith('.md'):
            return web.json_response({'error': 'Invalid file'}, status=400)
        workspace = os.path.normpath(self.core.config['paths']['workspace'])
        path = os.path.normpath(os.path.join(workspace, filename))
        if not path.startswith(workspace):
            return web.json_response({'error': 'Path traversal detected'}, status=403)
        if not os.path.exists(path):
            return web.json_response({'error': 'File not found'}, status=404)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return web.json_response({'name': filename, 'content': content})
    
    async def handle_save_file(self, request):
        """Save file contents"""
        data = await request.json()
        filename = data.get('name')
        content = data.get('content')
        if not filename or not filename.endswith('.md'):
            return web.json_response({'error': 'Invalid file'}, status=400)
        workspace = os.path.normpath(self.core.config['paths']['workspace'])
        path = os.path.normpath(os.path.join(workspace, filename))
        if not path.startswith(workspace):
            return web.json_response({'error': 'Path traversal detected'}, status=403)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        await self.core.log(f"File saved via Web Deck: {filename}", priority=2)
        return web.json_response({'success': True})

    # ── Executable Smart Artifacts ─────────────────────────────────────────────

    async def handle_artifact_run(self, request):
        """POST /api/artifact/run — execute code from a Smart Artifact card.
        Accepts {code: str, language: str}. Returns {output: str, exit_code: int}.
        """
        try:
            data = await request.json()
            code = data.get('code', '').strip()
            language = data.get('language', 'python').lower()
            if not code:
                return web.json_response({'error': 'No code provided', 'exit_code': 1}, status=400)

            await self.core.log(f"[Artifact Run] Executing {language} code ({len(code)} chars)...", priority=2)

            if language == 'python':
                result = await self.core.gateway.tool_execute_python({'code': code, 'timeout': 60})
            elif language in ('powershell', 'shell', 'bash', 'cmd', 'sh'):
                # Find the shell executor skill
                shell_skill = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'shell_executor'), None)
                if shell_skill:
                    result = await shell_skill.execute(code, timeout=60)
                else:
                    result = await self.core.gateway.tool_execute_python({
                        'code': f'import subprocess; r = subprocess.run({repr(code)}, shell=True, capture_output=True, text=True, timeout=60); print(r.stdout); print(r.stderr)',
                        'timeout': 65
                    })
            else:
                return web.json_response({'error': f'Unsupported language: {language}', 'exit_code': 1}, status=400)

            # Parse exit code from result if present
            exit_code = 0
            result_str = str(result)
            if 'EXIT CODE:' in result_str:
                import re
                m = re.search(r'EXIT CODE:\s*(\d+)', result_str)
                if m: exit_code = int(m.group(1))
            elif '[ERROR]' in result_str or '[Timeout]' in result_str:
                exit_code = 1

            await self.core.log(f"[Artifact Run] Done (exit={exit_code})", priority=2)
            return web.json_response({'output': result_str, 'exit_code': exit_code})

        except Exception as e:
            return web.json_response({'error': str(e), 'exit_code': 1}, status=500)

    # ── Memory API Endpoints (CLI /recall + /compact) ───────────────────────────

    async def handle_memory_search(self, request):
        """POST /api/memory/search — {query, top_k} → [{score, content, category}]"""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        query = (data.get('query') or '').strip()
        if not query:
            return web.json_response({'error': 'query is required'}, status=400)
        top_k = max(1, min(int(data.get('top_k') or 5), 25))
        memory = getattr(self.core, 'memory', None)
        if not memory:
            return web.json_response({'error': 'Memory system unavailable'}, status=503)
        try:
            hits = await memory.query_memory(query, n_results=top_k) or []
            results = []
            for h in hits:
                dist = h.get('distance')
                score = round(1.0 - dist, 3) if isinstance(dist, (int, float)) else None
                results.append({
                    'score': score,
                    'content': h.get('content', ''),
                    'category': (h.get('metadata') or {}).get('category', ''),
                })
            return web.json_response(results)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_memory_list(self, request):
        """GET /api/memory/list?limit=&category= — recent memories (with vector_id)."""
        memory = getattr(self.core, 'memory', None)
        if not memory:
            return web.json_response({'error': 'Memory system unavailable'}, status=503)
        try:
            limit = max(1, min(int(request.query.get('limit', 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        category = request.query.get('category') or None
        try:
            items = await memory.list_memories(limit=limit, category=category)
            return web.json_response({'items': items, 'count': len(items)})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_memory_stats(self, request):
        """GET /api/memory/stats — per-category counts."""
        memory = getattr(self.core, 'memory', None)
        if not memory:
            return web.json_response({'error': 'Memory system unavailable'}, status=503)
        try:
            counts = await memory.category_counts()
            return web.json_response({'categories': counts, 'total': sum(counts.values())})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_memory_delete(self, request):
        """POST /api/memory/delete — {vector_id} — remove one memory."""
        memory = getattr(self.core, 'memory', None)
        if not memory:
            return web.json_response({'error': 'Memory system unavailable'}, status=503)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        vector_id = (data.get('vector_id') or '').strip()
        if not vector_id:
            return web.json_response({'error': 'vector_id is required'}, status=400)
        try:
            ok = await memory.delete_memory(vector_id)
            if ok:
                await self.core.log(f"🗑️ Memory deleted via Control Deck ({vector_id[:8]}…)", priority=2)
            return web.json_response({'ok': ok})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_memory_compact(self, request):
        """POST /api/memory/compact — manually compact the main chat history."""
        try:
            gw = self.core.gateway
            history = gw.history
            before_msgs = len(history)
            before_chars = sum(len(str(m.get('content', ''))) for m in history)
            if before_msgs <= 4:
                return web.json_response({'ok': True, 'message': 'History too small to compact',
                                          'messages': before_msgs, 'chars': before_chars})
            target = max(4000, before_chars // 2)
            compacted = await gw._compact_history(list(history), target)
            history.clear()
            history.extend(compacted)
            after_chars = sum(len(str(m.get('content', ''))) for m in history)
            await self.core.log(
                f"🧼 Manual compaction: {before_msgs}→{len(history)} messages, "
                f"{before_chars}→{after_chars} chars", priority=2)
            return web.json_response({'ok': True, 'messages_before': before_msgs,
                                      'messages_after': len(history),
                                      'chars_before': before_chars, 'chars_after': after_chars})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    # ── Voice API Endpoints ─────────────────────────────────────────────────────

    async def handle_voice_stop(self, request):
        """POST /api/voice/stop — stops TTS playback if active."""
        try:
            for s in self.core.skills:
                if s.skill_name == 'voice_agent' and getattr(s, 'enabled', False):
                    s._abort_speaking = True
                    return web.json_response({'ok': True, 'message': 'TTS playback stopped'})
            return web.json_response({'ok': False, 'message': 'Voice Agent skill not loaded/enabled'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    def _get_voice_agent_skill(self):
        return next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'voice_agent'), None)

    def _memory_row_count(self):
        """Total stored memories. Works with the semantic engine (SQLite) and
        the Lite keyword engine (no db_conn)."""
        mem = getattr(self.core.gateway, 'galactic_memory', None) or getattr(self.core, 'memory', None)
        if not mem:
            return 0
        try:
            conn = getattr(mem, 'db_conn', None)
            if conn is not None:
                return conn.execute("SELECT COUNT(*) FROM episodic_memories").fetchone()[0]
            return len(getattr(mem, '_rows', []) or [])
        except Exception:
            return 0

    def _context_usage(self):
        """(used_tokens, max_tokens) for the active model. Prefers real token
        counts from the last LLM call; falls back to a chars/4 estimate of the
        in-memory history so the meter is never stuck at 0."""
        gw = self.core.gateway
        ctx_max = 0
        try:
            if hasattr(gw, '_get_context_window_for_model'):
                ctx_max = gw._get_context_window_for_model(0) or 0
            if not ctx_max and hasattr(self.core, 'ollama_manager') and gw.llm.provider == 'ollama':
                ctx_max = self.core.ollama_manager.get_context_window(gw.llm.model) or 0
        except Exception:
            ctx_max = 0
        try:
            char_count = sum(len(str(m.get('content', ''))) for m in (gw.history or []))
        except Exception:
            char_count = 0
        est_tokens = char_count // 4
        last = getattr(gw, '_last_usage', None) or {}
        usage = max(int(last.get('prompt_tokens') or 0), est_tokens)
        return usage, int(ctx_max or 0)

    async def handle_wakeword_get(self, request):
        """GET /api/voice/wakeword — current state of always-on wake-word listening."""
        skill = self._get_voice_agent_skill()
        return web.json_response({
            'enabled': bool(self.core.config.get('voice_agent', {}).get('wake_word_enabled', True)),
            'listening': bool(getattr(skill, 'listening', False)),
            'available': skill is not None,
        })

    async def handle_wakeword_set(self, request):
        """POST /api/voice/wakeword — {enabled: bool} — turn the always-on
        wake-word mic on/off. Persists to config.yaml and starts/stops the
        listener live (no restart needed)."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        enabled = bool(data.get('enabled'))

        cfg = self.core.config
        cfg.setdefault('voice_agent', {})['wake_word_enabled'] = enabled
        try:
            self._save_config(cfg)
        except Exception as e:
            return web.json_response({'ok': False, 'error': f'Config save failed: {e}'}, status=500)

        skill = self._get_voice_agent_skill()
        if skill:
            if enabled and not skill.listening:
                asyncio.create_task(skill.run())
            elif not enabled and skill.listening:
                skill.stop()
        await self.core.log(
            f"{'👂 Wake-word listening ENABLED — mic is live' if enabled else '🙉 Wake-word listening DISABLED — mic released'} (via Control Deck)",
            priority=2)
        return web.json_response({'ok': True, 'enabled': enabled, 'available': skill is not None})

    async def handle_tts(self, request):
        """POST /api/tts — text-to-speech via server-side engines. Returns MP3 audio."""
        try:
            data = await request.json()
            text = data.get('text', '').strip()
            voice = data.get('voice', 'Guy')
            if not text:
                return web.json_response({'error': 'No text provided'}, status=400)
            if len(text) > 5000:
                return web.json_response({'error': 'Text too long (max 5000 chars)'}, status=400)

            result = await self.core.gateway.tool_text_to_speech({'text': text, 'voice': voice})
            if '[VOICE]' in str(result):
                import re
                m = re.search(r'Generated speech.*?:\s*(.+\.(?:mp3|wav))', str(result))
                if m:
                    audio_path = m.group(1).strip()
                    if os.path.exists(audio_path):
                        with open(audio_path, 'rb') as f:
                            audio_data = f.read()
                        is_wav = audio_path.lower().endswith('.wav')
                        ctype = 'audio/wav' if is_wav else 'audio/mpeg'
                        fname = 'tts.wav' if is_wav else 'tts.mp3'
                        return web.Response(body=audio_data, content_type=ctype,
                                           headers={'Content-Disposition': f'inline; filename="{fname}"'})
            return web.json_response({'error': 'TTS generation failed', 'detail': str(result)}, status=500)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_stt(self, request):
        """POST /api/stt — speech-to-text via Whisper (OpenAI or Groq fallback).
        Accepts multipart form with 'audio' file field.
        """
        try:
            reader = await request.multipart()
            audio_data = None
            filename = 'audio.wav'
            async for part in reader:
                if part.name == 'audio':
                    filename = part.filename or 'audio.wav'
                    audio_data = await part.read()
                    break

            if not audio_data:
                return web.json_response({'error': 'No audio file provided'}, status=400)

            # Save temp file for transcription
            logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
            os.makedirs(logs_dir, exist_ok=True)
            temp_path = os.path.join(logs_dir, f'stt_temp_{int(time.time())}.wav')
            with open(temp_path, 'wb') as f:
                f.write(audio_data)

            transcription = None
            error_msg = 'no Whisper API key configured'
            try:
                # Local-first: faster-whisper keeps audio on this machine.
                _va_cfg = self.core.config.get('voice_agent', {})
                if _va_cfg.get('local_stt', True):
                    try:
                        import local_stt
                        local_stt.configure(_va_cfg.get('stt_model'))
                        local_text = await asyncio.to_thread(local_stt.transcribe_path, temp_path)
                        if local_text:
                            transcription = local_text
                            error_msg = None
                    except Exception as e:
                        error_msg = f'Local STT error: {e}'

                # Try OpenAI Whisper
                openai_key = self.core.config.get('providers', {}).get('openai', {}).get('apiKey', '')
                if not transcription and openai_key:
                    import httpx
                    async with httpx.AsyncClient(timeout=30) as client:
                        with open(temp_path, 'rb') as af:
                            resp = await client.post(
                                'https://api.openai.com/v1/audio/transcriptions',
                                headers={'Authorization': f'Bearer {openai_key}', 'User-Agent': 'Mozilla/5.0'},
                                files={'file': (filename, af, 'audio/wav')},
                                data={'model': 'whisper-1'}
                            )
                        if resp.status_code == 200:
                            transcription = resp.json().get('text', '')
                        else:
                            error_msg = f'OpenAI Error: {resp.status_code} {resp.text}'
                # Fallback: Groq Whisper
                if not transcription:
                    groq_key = self.core.config.get('providers', {}).get('groq', {}).get('apiKey', '')
                    if groq_key:
                        import httpx
                        async with httpx.AsyncClient(timeout=30) as client:
                            with open(temp_path, 'rb') as af:
                                resp = await client.post(
                                    'https://api.groq.com/openai/v1/audio/transcriptions',
                                    headers={'Authorization': f'Bearer {groq_key}', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                                    files={'file': (filename, af, 'audio/wav')},
                                    data={'model': 'whisper-large-v3'}
                                )
                            if resp.status_code == 200:
                                transcription = resp.json().get('text', '')
                            else:
                                error_msg = f'Groq Error: {resp.status_code} {resp.text}'
                                
                # Fallback: Local Whisper
                if not transcription:
                    try:
                        import whisper
                        if not hasattr(self.core, '_local_whisper_model'):
                            await self.core.log("Loading local Whisper model ('base') for STT... This will take a few seconds on first run.", priority=1)
                            # Load synchronously for the first time
                            self.core._local_whisper_model = whisper.load_model('base')
                            
                        def run_whisper():
                            return self.core._local_whisper_model.transcribe(temp_path)
                            
                        result = await asyncio.to_thread(run_whisper)
                        transcription = result.get('text', '').strip()
                        error_msg = None
                    except ImportError:
                        pass
                    except Exception as e:
                        error_msg += f" (Local Whisper error: {e})"
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            if transcription:
                return web.json_response({'text': transcription})
            return web.json_response({'error': f'Transcription failed — {error_msg}'}, status=500)

        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def _broadcast(self, msg_dict):
        """Send a JSON payload to all connected stream clients."""
        import json
        payload = (json.dumps(msg_dict) + "\n").encode('utf-8')
        for adapter in self.core.clients:
            try:
                adapter.write(payload)
            except Exception:
                pass

    async def _start_site(self, site):
        """Start the TCP site with a human-readable failure instead of a
        stack trace when the port is already taken (usually a second
        Galactic AI instance)."""
        try:
            await site.start()
            return True
        except OSError as e:
            if getattr(e, 'errno', None) in (48, 98, 10048) or 'address' in str(e).lower():
                await self.core.log(
                    f"❌ Control Deck port {self.port} is already in use — another Galactic AI "
                    f"instance (or app) is listening there. Close it and restart, or change "
                    f"web.port in config.local.yaml. Core keeps running (Telegram/CLI still work).",
                    priority=1)
                return False
            raise

    async def run(self):
        runner = web.AppRunner(self.app, access_log=None)
        self._runner = runner  # Store for cleanup on shutdown
        await runner.setup()

        protocol = 'http'
        if self.remote_access:
            # Remote mode: plain HTTP on 0.0.0.0 for LAN access.
            # TLS with self-signed certs causes browser warnings,
            # so we skip it for LAN use. Auth is handled by JWT + password.

            site = web.TCPSite(runner, '0.0.0.0', self.port, ssl_context=None)
            if not await self._start_site(site):
                return

            # Detect LAN IP for the log message
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = '0.0.0.0'

            await self.core.log(
                f"REMOTE ACCESS ENABLED - Control Deck at http://{local_ip}:{self.port}  (LAN + localhost)",
                priority=1
            )
        else:
            site = web.TCPSite(runner, self.host, self.port)
            if not await self._start_site(site):
                return


