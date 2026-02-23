import asyncio
import json
import hashlib
import time
import os
from aiohttp import web
import jinja2

class GalacticWebDeck:
    def __init__(self, core):
        self.core = core
        self.config = core.config.get('web', {})
        self.port = self.config.get('port', 18789)
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

        self.app = web.Application(middlewares=middlewares)
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_post('/login', self.handle_login)
        self.app.router.add_post('/api/setup', self.handle_setup)
        self.app.router.add_get('/api/check_setup', self.handle_check_setup)
        self.app.router.add_get('/stream', self.handle_stream)
        self.app.router.add_get('/api/files', self.handle_list_files)
        self.app.router.add_get('/api/file', self.handle_get_file)
        self.app.router.add_post('/api/file', self.handle_save_file)
        # Ollama live endpoints
        self.app.router.add_get('/api/ollama_models', self.handle_ollama_models)
        self.app.router.add_get('/api/ollama_status', self.handle_ollama_status)
        # Control APIs
        self.app.router.add_post('/api/chat', self.handle_chat)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_post('/api/plugin_toggle', self.handle_plugin_toggle)
        self.app.router.add_post('/api/tool_invoke', self.handle_tool_invoke)
        self.app.router.add_get('/api/tools', self.handle_list_tools)
        self.app.router.add_get('/api/plugins', self.handle_list_plugins)
        self.app.router.add_post('/api/switch_model', self.handle_switch_model)
        self.app.router.add_post('/api/browser_cmd', self.handle_browser_cmd)
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
        self.app.router.add_get('/api/logs', self.handle_logs)
        self.app.router.add_get('/api/image/{filename}', self.handle_serve_image)
        self.app.router.add_get('/api/video/{filename}', self.handle_serve_video)
        self.app.router.add_get('/api/images/{subfolder}/{filename}', self.handle_serve_image_sub)
        self.app.router.add_get('/api/traces', self.handle_traces)
        self.app.router.add_post('/api/save_key', self.handle_save_key)
        # Settings endpoints
        self.app.router.add_post('/api/settings/models', self.handle_settings_models)
        self.app.router.add_post('/api/settings/voice', self.handle_settings_voice)
        self.app.router.add_post('/api/settings/system', self.handle_settings_system)
        # Voice API endpoints
        self.app.router.add_post('/api/tts', self.handle_tts)
        self.app.router.add_post('/api/stt', self.handle_stt)
        # Power control endpoints
        self.app.router.add_post('/api/restart', self.handle_restart)
        self.app.router.add_post('/api/shutdown', self.handle_shutdown)
        self.trace_buffer = []  # last 500 agent trace entries for persistence
        
    async def handle_index(self, request):
        html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GALACTIC AI — CONTROL DECK</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#04050d;--bg2:#0a0b18;--bg3:#101120;
  --cyan:#00f3ff;--pink:#ff00c8;--green:#00ff88;--yellow:#ffcc00;--red:#ff4545;--orange:#ff8c00;
  --border:rgba(0,243,255,0.22);--border-hi:rgba(0,243,255,0.45);--text:#e8e8e8;--dim:#8a8aaa;
  --font:'Segoe UI',system-ui,sans-serif;--mono:'Cascadia Code','Consolas',monospace;
  --fs:17px;
}
html{font-size:var(--fs)}
body{background:var(--bg);color:var(--text);font-family:var(--font);height:100vh;overflow:hidden;display:flex;flex-direction:column;font-size:1rem}

/* ── TOPBAR ─────────────────────────────────────────────────────────────── */
#topbar{display:flex;align-items:center;gap:12px;padding:10px 20px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;z-index:100;box-shadow:0 2px 20px rgba(0,0,0,0.4)}
#topbar .logo{font-size:1.05rem;font-weight:800;letter-spacing:5px;color:var(--cyan);text-shadow:0 0 14px var(--cyan),0 0 30px rgba(0,243,255,0.3);white-space:nowrap}
#topbar .spacer{flex:1}
.status-dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green),0 0 16px rgba(0,255,136,0.3);flex-shrink:0}
.status-dot.offline{background:var(--red);box-shadow:0 0 8px var(--red)}
#ollama-pill{display:flex;align-items:center;gap:6px;padding:5px 13px;border:1px solid var(--border);border-radius:20px;font-size:0.82rem;background:var(--bg3);cursor:pointer;transition:border-color .2s}
#ollama-pill:hover{border-color:var(--border-hi)}
#model-badge{padding:5px 13px;border:1px solid var(--pink);border-radius:20px;font-size:0.82rem;color:var(--pink);text-shadow:0 0 8px rgba(255,0,200,0.4);cursor:pointer;white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis;transition:all .2s}
#model-badge:hover{background:rgba(255,0,200,0.08)}
.topbar-btn{padding:6px 14px;border:1px solid var(--border);border-radius:7px;background:var(--bg3);color:var(--text);cursor:pointer;font-size:0.82rem;transition:all .2s}
.topbar-btn:hover{border-color:var(--cyan);color:var(--cyan);text-shadow:0 0 8px var(--cyan)}
#token-counter{font-size:0.78rem;color:var(--dim);font-family:var(--mono)}
#main{display:flex;flex:1;overflow:hidden}

/* ── SIDEBAR ─────────────────────────────────────────────────────────────── */
#sidebar{width:240px;min-width:190px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;transition:width .2s}
#sidebar.collapsed{width:0;min-width:0}
.sidebar-section{padding:11px 14px 7px;font-size:0.72rem;letter-spacing:2px;color:var(--dim);text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0}
.sidebar-item{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;font-size:0.88rem;transition:background .15s;border-bottom:1px solid rgba(255,255,255,0.04)}
.sidebar-item:hover,.sidebar-item.active{background:rgba(0,243,255,0.1);color:var(--cyan)}
.sidebar-item.active{border-left:3px solid var(--cyan);padding-left:11px}
.sidebar-item .icon{width:20px;text-align:center;flex-shrink:0;font-size:1.05em}
.sidebar-item .badge{margin-left:auto;background:var(--pink);color:#fff;font-size:0.72rem;padding:2px 7px;border-radius:10px}
#content{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* ── TAB BAR ─────────────────────────────────────────────────────────────── */
#tabbar{display:flex;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;overflow-x:auto}
.tab-btn{padding:11px 20px;font-size:0.86rem;letter-spacing:1px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;color:var(--dim);background:none;border-top:none;border-left:none;border-right:none;transition:all .2s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--cyan);border-bottom-color:var(--cyan);text-shadow:0 0 10px rgba(0,243,255,0.5)}
.tab-pane{display:none;flex:1;overflow:hidden;flex-direction:column}
.tab-pane.active{display:flex}

/* ── CHAT ────────────────────────────────────────────────────────────────── */
#chat-wrap{display:flex;flex:1;overflow:hidden;gap:0}
#chat-log{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px}
#chat-log::-webkit-scrollbar{width:5px}
#chat-log::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.msg{display:flex;flex-direction:column;gap:5px;max-width:88%}
.msg.user{align-self:flex-end;align-items:flex-end}
.msg.bot{align-self:flex-start;align-items:flex-start}
.msg .bubble{padding:12px 16px;border-radius:16px;font-size:0.95rem;line-height:1.6;word-break:break-word;white-space:pre-wrap}
.msg.user .bubble{background:linear-gradient(135deg,rgba(0,243,255,0.18),rgba(0,243,255,0.09));border:1px solid rgba(0,243,255,0.35);border-bottom-right-radius:4px}
.msg.bot .bubble{background:var(--bg3);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg.bot.thinking .bubble{border-color:rgba(255,0,200,0.3);color:var(--dim)}
.msg .meta{font-size:0.73rem;color:var(--dim)}
#stream-bubble{padding:12px 16px;border-radius:16px;font-size:0.95rem;line-height:1.6;background:var(--bg3);border:1px solid rgba(255,0,200,0.35);color:var(--pink);white-space:pre-wrap;word-break:break-word;align-self:flex-start;max-width:88%;display:none}
#chat-input-row{display:flex;gap:10px;padding:14px 18px;border-top:1px solid var(--border);flex-shrink:0;background:var(--bg2)}
#chat-input{flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:12px;padding:11px 16px;color:var(--text);font-family:var(--font);font-size:0.95rem;resize:none;height:48px;max-height:200px;overflow-y:auto;outline:none;transition:border .2s}
#chat-input:focus{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(0,243,255,0.1)}
#send-btn{padding:11px 24px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:12px;color:#000;font-weight:800;cursor:pointer;font-size:0.95rem;transition:opacity .2s,box-shadow .2s}
#send-btn:hover{box-shadow:0 0 20px rgba(0,243,255,0.4)}
#send-btn:disabled{opacity:0.4;cursor:not-allowed}
#chat-tools-sidebar{width:240px;border-left:1px solid var(--border);background:var(--bg2);display:flex;flex-direction:column;overflow-y:auto;flex-shrink:0}
#chat-tools-sidebar h4{padding:11px 14px;font-size:0.76rem;letter-spacing:2px;color:var(--dim);border-bottom:1px solid var(--border);text-transform:uppercase}
.quick-tool-btn{display:flex;align-items:center;gap:9px;width:100%;padding:9px 14px;background:none;border:none;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--text);font-size:0.86rem;cursor:pointer;text-align:left;transition:background .15s}
.quick-tool-btn:hover{background:rgba(0,243,255,0.07);color:var(--cyan)}
.quick-tool-btn .tool-icon{font-size:1.1em;width:20px;text-align:center}

/* ── TOOLS PANE ──────────────────────────────────────────────────────────── */
#tools-pane{padding:18px;overflow-y:auto}
#tools-pane h3{color:var(--cyan);margin-bottom:14px;font-size:1rem;letter-spacing:2px;text-shadow:0 0 10px rgba(0,243,255,0.3)}
#tool-search{width:100%;padding:9px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:0.9rem;margin-bottom:16px;outline:none;transition:border .2s}
#tool-search:focus{border-color:var(--cyan)}
.tool-group{margin-bottom:18px}
.tool-group-label{font-size:0.75rem;letter-spacing:2px;color:var(--pink);text-transform:uppercase;margin-bottom:9px;padding:5px 0;border-bottom:1px solid rgba(255,0,200,0.22)}
.tool-card{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:11px 15px;margin-bottom:7px;cursor:pointer;transition:all .2s}
.tool-card:hover{border-color:var(--cyan);background:rgba(0,243,255,0.06);transform:translateY(-1px);box-shadow:0 4px 16px rgba(0,0,0,0.3)}
.tool-card h4{font-size:0.9rem;color:var(--cyan);margin-bottom:4px}
.tool-card p{font-size:0.8rem;color:var(--dim);line-height:1.45}
.tool-card .params{font-size:0.75rem;color:var(--yellow);margin-top:5px;font-family:var(--mono)}

/* ── TOOL MODAL ──────────────────────────────────────────────────────────── */
#tool-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:5000;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
#tool-modal.open{display:flex}
#tool-modal-inner{background:var(--bg2);border:1px solid var(--cyan);border-radius:16px;padding:28px;width:520px;max-width:95vw;max-height:90vh;overflow-y:auto;box-shadow:0 0 40px rgba(0,243,255,0.15)}
#tool-modal-inner h3{color:var(--cyan);margin-bottom:10px;font-size:1.05rem}
#tool-modal-inner p{color:var(--dim);font-size:0.88rem;margin-bottom:18px;line-height:1.5}
.param-row{margin-bottom:12px}
.param-row label{display:block;font-size:0.82rem;color:var(--yellow);margin-bottom:5px;font-family:var(--mono)}
.param-row input,.param-row textarea{width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.9rem;outline:none;transition:border .2s}
.param-row input:focus,.param-row textarea:focus{border-color:var(--cyan)}
.modal-btns{display:flex;gap:10px;margin-top:18px;justify-content:flex-end}
.btn{padding:9px 20px;border-radius:9px;cursor:pointer;font-size:0.88rem;border:none;font-weight:600;transition:all .2s}
.btn.primary{background:linear-gradient(135deg,var(--cyan),rgba(0,200,220,1));color:#000}
.btn.primary:hover{box-shadow:0 0 16px rgba(0,243,255,0.4)}
.btn.secondary{background:var(--bg3);border:1px solid var(--border);color:var(--text)}
.btn.secondary:hover{border-color:var(--border-hi)}
#tool-result{margin-top:14px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:7px;font-size:0.84rem;font-family:var(--mono);white-space:pre-wrap;max-height:220px;overflow-y:auto;display:none}

/* ── API KEY MODAL ───────────────────────────────────────────────────────── */
#key-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:5500;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
#key-modal.open{display:flex}
#key-modal-inner{background:var(--bg2);border:1px solid var(--yellow);border-radius:16px;padding:28px;width:500px;max-width:95vw;box-shadow:0 0 40px rgba(255,204,0,0.15)}
#key-modal-inner h3{color:var(--yellow);margin-bottom:10px;font-size:1.05rem}
#key-modal-inner p{color:var(--dim);font-size:0.88rem;margin-bottom:18px;line-height:1.5}
#key-input{width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:0.9rem;font-family:var(--mono);outline:none;transition:border .2s;margin-bottom:6px}
#key-input:focus{border-color:var(--yellow);box-shadow:0 0 0 2px rgba(255,204,0,0.1)}

/* ── PLUGINS PANE ────────────────────────────────────────────────────────── */
#plugins-pane{padding:18px;overflow-y:auto}
#plugins-pane h3{color:var(--cyan);margin-bottom:16px;font-size:1rem;letter-spacing:2px;text-shadow:0 0 10px rgba(0,243,255,0.3)}
.plugin-card{background:var(--bg3);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:11px;display:flex;align-items:center;gap:16px;transition:all .2s}
.plugin-card:hover{border-color:var(--border-hi);box-shadow:0 4px 20px rgba(0,0,0,0.3)}
.plugin-card .plugin-icon{font-size:1.7em;width:38px;text-align:center}
.plugin-card .plugin-info{flex:1}
.plugin-card .plugin-name{font-size:0.95rem;font-weight:700;color:var(--cyan)}
.plugin-card .plugin-desc{font-size:0.8rem;color:var(--dim);margin-top:3px;line-height:1.4}
.plugin-card .plugin-class{font-size:0.73rem;color:var(--pink);font-family:var(--mono);margin-top:3px}
.toggle-switch{position:relative;width:48px;height:26px;flex-shrink:0}
.toggle-switch input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:#2a2a3a;border-radius:26px;cursor:pointer;transition:.3s}
.toggle-slider:before{content:"";position:absolute;height:20px;width:20px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;box-shadow:0 1px 4px rgba(0,0,0,0.4)}
.toggle-switch input:checked + .toggle-slider{background:var(--green);box-shadow:0 0 10px rgba(0,255,136,0.3)}
.toggle-switch input:checked + .toggle-slider:before{transform:translateX(22px)}

/* ── MODELS PANE ─────────────────────────────────────────────────────────── */
#models-pane{padding:18px;overflow-y:auto}
#models-pane h3{color:var(--cyan);margin-bottom:16px;font-size:1rem;letter-spacing:2px;text-shadow:0 0 10px rgba(0,243,255,0.3)}
.provider-section{margin-bottom:22px}
.provider-label{font-size:0.76rem;letter-spacing:2px;color:var(--pink);text-transform:uppercase;margin-bottom:11px;padding-bottom:5px;border-bottom:1px solid rgba(255,0,200,0.22)}
.model-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:9px}
.model-btn{padding:11px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:0.85rem;cursor:pointer;text-align:left;transition:all .2s;line-height:1.35}
.model-btn:hover{border-color:var(--cyan);color:var(--cyan);background:rgba(0,243,255,0.06);transform:translateY(-1px)}
.model-btn.active{border-color:var(--green);color:var(--green);background:rgba(0,255,136,0.09);box-shadow:0 0 12px rgba(0,255,136,0.15)}
#ollama-section .model-btn{border-color:rgba(255,136,0,0.32)}
#ollama-section .model-btn.active{border-color:var(--orange);color:var(--orange)}
#ollama-health-row{display:flex;align-items:center;gap:9px;margin-bottom:14px;padding:9px 14px;background:var(--bg3);border-radius:9px;border:1px solid var(--border);font-size:0.87rem}
#ollama-health{font-weight:700}
.model-config-box{background:var(--bg3);border:1px solid var(--border);border-radius:11px;padding:16px;margin-bottom:16px}
.model-config-box h4{font-size:0.84rem;color:var(--dim);margin-bottom:12px;letter-spacing:1px}
.model-config-row{display:flex;gap:9px;margin-bottom:9px}
.model-config-row label{font-size:0.8rem;color:var(--dim);min-width:76px;display:flex;align-items:center}
.model-config-row input,.model-config-row select{flex:1;padding:7px 11px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.87rem;outline:none;transition:border .2s}
.model-config-row input:focus{border-color:var(--cyan)}

/* ── BROWSER PANE ────────────────────────────────────────────────────────── */
#browser-pane{padding:18px;overflow-y:auto}
#browser-pane h3{color:var(--cyan);margin-bottom:16px;font-size:1rem;letter-spacing:2px}
.browser-url-row{display:flex;gap:9px;margin-bottom:16px}
#browser-url{flex:1;padding:9px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:0.92rem;outline:none;transition:border .2s}
#browser-url:focus{border-color:var(--cyan)}
.browser-action-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:18px}
.browser-btn{padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:0.83rem;cursor:pointer;text-align:center;transition:all .2s}
.browser-btn:hover{border-color:var(--cyan);color:var(--cyan)}
#browser-screenshot{width:100%;border-radius:9px;border:1px solid var(--border);display:none;margin-top:11px}
#browser-status{font-size:0.84rem;color:var(--dim);font-family:var(--mono);padding:9px;background:var(--bg3);border-radius:7px;margin-top:9px;min-height:34px}

/* ── LOGS PANE ───────────────────────────────────────────────────────────── */
#logs-pane{display:flex;flex-direction:column;overflow:hidden}
#log-controls{display:flex;gap:9px;padding:11px 16px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg2)}
#log-filter{padding:6px 11px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85rem;flex:1;outline:none;transition:border .2s}
#log-filter:focus{border-color:var(--cyan)}
#logs-scroll{flex:1;overflow-y:auto;padding:11px 16px;font-family:var(--mono);font-size:0.84rem;line-height:1.75}
#logs-scroll::-webkit-scrollbar{width:5px}
#logs-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.log-line{padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
.log-line.err{color:var(--red)}
.log-line.warn{color:var(--yellow)}
.log-line.ok{color:var(--green)}

/* ── STATUS PANE ─────────────────────────────────────────────────────────── */
#status-pane{padding:18px;overflow-y:auto}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:18px}
.stat-card{background:var(--bg3);border:1px solid var(--border);border-radius:12px;padding:18px;text-align:center;transition:all .2s}
.stat-card:hover{border-color:var(--border-hi);box-shadow:0 4px 20px rgba(0,0,0,0.3)}
.stat-card .val{font-size:2em;font-weight:800;color:var(--cyan);font-family:var(--mono);text-shadow:0 0 12px rgba(0,243,255,0.3)}
.stat-card .lbl{font-size:0.76rem;color:var(--dim);margin-top:6px;letter-spacing:1px;text-transform:uppercase}
.stat-card .val.small{font-size:1.1em}

/* ── TOAST NOTIFICATIONS ──────────────────────────────────────────────── */
#toast-container{position:fixed;top:60px;right:20px;z-index:9000;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{pointer-events:auto;padding:12px 18px;border-radius:10px;font-size:0.85rem;font-family:var(--mono);color:#fff;backdrop-filter:blur(12px);box-shadow:0 4px 24px rgba(0,0,0,0.5);animation:toastIn .3s ease-out;max-width:420px;display:flex;align-items:center;gap:10px}
.toast.warning{background:rgba(255,140,0,0.92);border:1px solid rgba(255,200,0,0.4)}
.toast.success{background:rgba(0,180,80,0.92);border:1px solid rgba(0,255,136,0.4)}
.toast.error{background:rgba(220,40,40,0.92);border:1px solid rgba(255,80,80,0.4)}
.toast.info{background:rgba(0,160,255,0.88);border:1px solid rgba(0,200,255,0.4)}
.toast.fadeout{animation:toastOut .4s ease-in forwards}
@keyframes toastIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}
@keyframes toastOut{from{opacity:1;transform:translateX(0)}to{opacity:0;transform:translateX(40px)}}

/* ── MEMORY PANE ─────────────────────────────────────────────────────────── */
#memory-pane{padding:18px;overflow-y:auto}
.mem-controls{display:flex;gap:9px;margin-bottom:14px}
#mem-file-select{flex:1;padding:8px 11px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88rem;outline:none}
#mem-editor{width:100%;height:calc(100vh - 280px);padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:9px;color:var(--text);font-family:var(--mono);font-size:0.88rem;resize:vertical;outline:none;transition:border .2s;line-height:1.6}
#mem-editor:focus{border-color:var(--cyan)}

/* ── LOGIN ───────────────────────────────────────────────────────────────── */
#login-overlay{position:fixed;inset:0;background:rgba(4,5,13,0.97);z-index:8000;display:flex;align-items:center;justify-content:center}
.login-box{background:var(--bg2);border:1px solid var(--cyan);border-radius:18px;padding:42px;width:370px;text-align:center;box-shadow:0 0 60px rgba(0,243,255,0.12)}
.login-box h2{color:var(--cyan);letter-spacing:5px;margin-bottom:8px;font-size:1.2rem;text-shadow:0 0 16px rgba(0,243,255,0.5)}
.login-box p{color:var(--dim);font-size:0.85rem;margin-bottom:24px}
#pw-input{width:100%;padding:12px 16px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;color:var(--text);font-size:1rem;text-align:center;outline:none;letter-spacing:4px;margin-bottom:14px;transition:border .2s}
#pw-input:focus{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(0,243,255,0.1)}
#login-btn{width:100%;padding:13px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:9px;color:#000;font-weight:800;cursor:pointer;font-size:1rem;transition:box-shadow .2s}
#login-btn:hover{box-shadow:0 0 24px rgba(0,243,255,0.4)}
#login-err{color:var(--red);font-size:0.84rem;margin-top:9px;display:none}

/* ── SCROLLBARS ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:rgba(0,243,255,0.25);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:rgba(0,243,255,0.45)}

/* ── THINKING TAB ────────────────────────────────────────────────────────── */
#thinking-pane{display:flex;flex-direction:column;overflow:hidden;height:100%}
#thinking-controls{display:flex;gap:9px;padding:11px 16px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg2);align-items:center;flex-wrap:wrap}
#thinking-filter{padding:6px 11px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85rem;flex:1;min-width:110px;outline:none;transition:border .2s}
#thinking-filter:focus{border-color:var(--pink)}
#thinking-phase-filter{padding:6px 9px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85rem;outline:none}
#thinking-turn-counter{font-size:0.76rem;color:var(--dim);margin-left:auto;font-family:var(--mono);white-space:nowrap}
#thinking-scroll{flex:1;overflow-y:auto;padding:16px;font-family:var(--mono);font-size:0.86rem;line-height:1.65}
#thinking-scroll::-webkit-scrollbar{width:5px}
#thinking-scroll::-webkit-scrollbar-thumb{background:rgba(255,0,200,0.2);border-radius:3px}
.trace-session{margin-bottom:18px;border:1px solid rgba(56,217,169,0.22);border-radius:11px;overflow:hidden}
.trace-session-header{padding:10px 16px;background:rgba(56,217,169,0.06);border-bottom:1px solid rgba(56,217,169,0.13);display:flex;align-items:center;gap:9px;cursor:pointer;user-select:none;transition:background .15s}
.trace-session-header:hover{background:rgba(56,217,169,0.11)}
.trace-sid{font-size:0.76rem;color:var(--cyan);font-family:var(--mono);flex-shrink:0}
.trace-query{font-size:0.87rem;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trace-toggle{color:var(--dim);font-size:0.78rem;flex-shrink:0;transition:transform .2s}
.trace-session.collapsed .trace-session-body{display:none}
.trace-session.collapsed .trace-toggle{transform:rotate(-90deg)}
.trace-session-body{padding:9px 14px}
.trace-turn{margin-bottom:11px;border-left:2px solid rgba(255,121,198,0.38);padding-left:11px}
.trace-turn-header{font-size:0.76rem;font-weight:700;color:var(--pink);letter-spacing:1px;margin-bottom:6px;cursor:pointer;user-select:none}
.trace-turn-header:hover{color:#ff99dd}
.trace-turn.collapsed .trace-turn-entries{display:none}
.trace-entry{padding:7px 11px;margin-bottom:5px;border-radius:7px;border:1px solid transparent;position:relative}
.trace-entry.phase-thinking{background:rgba(255,121,198,0.07);border-color:rgba(255,121,198,0.24)}
.trace-entry.phase-thinking .trace-label{color:var(--pink)}
.trace-entry.phase-llm_response{background:rgba(56,217,169,0.05);border-color:rgba(56,217,169,0.17)}
.trace-entry.phase-llm_response .trace-label{color:var(--cyan)}
.trace-entry.phase-tool_call{background:rgba(241,250,140,0.06);border-color:rgba(241,250,140,0.22)}
.trace-entry.phase-tool_call .trace-label{color:var(--yellow)}
.trace-entry.phase-tool_result{background:rgba(80,250,123,0.05);border-color:rgba(80,250,123,0.2)}
.trace-entry.phase-tool_result .trace-label{color:var(--green)}
.trace-entry.phase-tool_result.error{background:rgba(255,85,85,0.07);border-color:rgba(255,85,85,0.24)}
.trace-entry.phase-tool_result.error .trace-label{color:var(--red)}
.trace-entry.phase-final_answer{background:rgba(56,217,169,0.09);border-color:rgba(56,217,169,0.32)}
.trace-entry.phase-final_answer .trace-label{color:var(--cyan);font-weight:700}
.trace-entry.phase-duplicate_blocked,.trace-entry.phase-tool_not_found{background:rgba(255,85,85,0.06);border-color:rgba(255,85,85,0.2)}
.trace-entry.phase-duplicate_blocked .trace-label,.trace-entry.phase-tool_not_found .trace-label{color:var(--red)}
.trace-entry.phase-session_abort{background:rgba(255,85,85,0.09);border-color:rgba(255,85,85,0.27)}
.trace-entry.phase-session_abort .trace-label{color:var(--red);font-weight:700}
.trace-label{font-size:0.72rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
.trace-content{font-size:0.86rem;color:var(--text);white-space:pre-wrap;word-break:break-word;max-height:190px;overflow-y:auto}
.trace-content.expanded{max-height:none}
.trace-expand-btn{font-size:0.72rem;color:var(--dim);cursor:pointer;margin-top:4px;display:inline-block}
.trace-expand-btn:hover{color:var(--cyan)}
.trace-tool-badge{display:inline-block;padding:2px 8px;background:rgba(241,250,140,0.13);border-radius:5px;font-size:0.82rem;color:var(--yellow);margin-right:5px;font-family:var(--mono)}
.trace-ts{font-size:0.66rem;color:var(--dim);position:absolute;top:7px;right:9px}

/* ── CRT SCANLINES (toggled via body.crt class) ──────────────────────────── */
body.crt::after{content:"";position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.18) 2px,rgba(0,0,0,0.18) 4px);pointer-events:none;z-index:9000;animation:flicker 8s infinite}
@keyframes flicker{0%,100%{opacity:1}92%{opacity:0.97}93%{opacity:0.92}94%{opacity:0.98}}

/* ── GLOW INTENSITY CLASSES ──────────────────────────────────────────────── */
body.glow-off #topbar .logo{text-shadow:none}
body.glow-off .tab-btn.active{text-shadow:none}
body.glow-off .stat-card .val{text-shadow:none}
body.glow-off #models-pane h3,body.glow-off #tools-pane h3,body.glow-off #plugins-pane h3{text-shadow:none}
body.glow-off .status-dot{box-shadow:none}
body.glow-off #model-badge{text-shadow:none}
body.glow-max #topbar .logo{text-shadow:0 0 20px var(--cyan),0 0 40px var(--cyan),0 0 60px rgba(0,243,255,0.4)}
body.glow-max .tab-btn.active{text-shadow:0 0 16px var(--cyan),0 0 30px rgba(0,243,255,0.5)}
body.glow-max .stat-card .val{text-shadow:0 0 20px rgba(0,243,255,0.6)}
body.glow-max .status-dot{box-shadow:0 0 14px var(--green),0 0 28px rgba(0,255,136,0.5)}
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-overlay" style="display:none">
  <div class="login-box">
    <div style="font-size:2em;margin-bottom:8px">⬡</div>
    <h2>GALACTIC AI</h2>
    <p>AUTOMATION SUITE v0.9.1</p>
    <input id="pw-input" type="password" placeholder="Enter passphrase" autocomplete="off">
    <button id="login-btn" onclick="doLogin()">ACCESS</button>
    <div id="login-err" style="display:none;color:var(--red);font-size:0.8em;margin-top:8px">Invalid passphrase</div>
    <div style="margin-top:16px;font-size:0.72em;color:var(--dim)">
      <span style="cursor:pointer;text-decoration:underline" onclick="showSetupWizard({})">First time? Run Setup Wizard</span>
    </div>
  </div>
</div>

<!-- SETUP SUCCESS -->
<div id="setup-success" style="display:none;position:fixed;inset:0;background:rgba(5,6,10,0.97);z-index:9500;align-items:center;justify-content:center;flex-direction:column;gap:16px">
  <div style="font-size:3em">✅</div>
  <div style="font-size:1.3em;color:var(--green);font-weight:700;letter-spacing:3px">CONFIGURATION SAVED</div>
  <div style="color:var(--dim);font-size:0.85em">Launching Galactic AI...</div>
</div>

<!-- SETUP WIZARD -->
<div id="setup-wizard" style="display:none;position:fixed;inset:0;background:rgba(5,6,10,0.98);z-index:9000;align-items:flex-start;justify-content:center;overflow-y:auto;padding:20px 0">
  <div style="background:var(--bg2);border:1px solid var(--cyan);border-radius:20px;width:min(720px,96vw);margin:auto">
    <!-- Header -->
    <div style="padding:28px 32px 0;text-align:center">
      <div style="font-size:2.5em;margin-bottom:8px">⬡</div>
      <div style="font-size:1.3em;font-weight:700;letter-spacing:4px;color:var(--cyan)">GALACTIC AI SETUP</div>
      <div style="color:var(--dim);font-size:0.82em;margin-top:4px">Initial configuration wizard — takes about 2 minutes</div>
    </div>
    <!-- Progress bar -->
    <div style="margin:20px 32px 0;height:3px;background:var(--bg3);border-radius:2px">
      <div id="sw-progress" style="height:100%;background:linear-gradient(90deg,var(--cyan),var(--pink));border-radius:2px;width:16.7%;transition:width .4s"></div>
    </div>

    <!-- Step 1: Primary Model Provider -->
    <div id="sw-step-1" style="padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:18px">STEP 1 OF 7 — PRIMARY AI PROVIDER</div>
      <div style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Choose your primary AI provider:</label>
        <select id="sw-provider" onchange="swUpdateModelHint()" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
          <option value="google">🌐 Google Gemini — Best overall, free tier available</option>
          <option value="anthropic">🤖 Anthropic Claude — Best for reasoning &amp; code</option>
          <option value="openai">🧠 OpenAI GPT — GPT-4o, GPT-4.1</option>
          <option value="xai">⚡ xAI Grok — Fast &amp; capable</option>
          <option value="groq">🚀 Groq — Ultra-fast free inference</option>
          <option value="mistral">🇪🇺 Mistral AI — Codestral, Magistral</option>
          <option value="cerebras">⚙️ Cerebras — Lightning fast Llama/Qwen</option>
          <option value="openrouter">🔀 OpenRouter — 100+ models, one key</option>
          <option value="huggingface">🤗 HuggingFace — Free tier, Llama/Qwen/DeepSeek</option>
          <option value="kimi">🌙 Kimi / Moonshot — Kimi K2.5 coding model</option>
          <option value="zai">🔷 ZAI / GLM — GLM-4.5, GLM-4.7</option>
          <option value="minimax">🎵 MiniMax — M2 multimodal + TTS</option>
          <option value="nvidia">🟢 NVIDIA AI — DeepSeek, Qwen 480B, Kimi</option>
          <option value="ollama">🦙 Ollama Local — 100% private, no API key needed</option>
        </select>
      </div>
      <div style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Model ID <span style="color:var(--dim)">(leave blank for recommended default)</span>:</label>
        <input id="sw-model" type="text" placeholder="gemini-2.5-flash" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
        <div id="sw-model-hint" style="margin-top:5px;font-size:0.72em;color:var(--dim)"></div>
      </div>
      <!-- Standard API Key field -->
      <div id="sw-apikey-wrap" style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">API Key:</label>
        <input id="sw-apikey" type="password" placeholder="Paste your API key here" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
        <div id="sw-key-link" style="margin-top:6px;font-size:0.72em;color:var(--dim)"></div>
      </div>
      <!-- Ollama URL field -->
      <div id="sw-ollama-wrap" style="display:none;margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Ollama Server URL:</label>
        <input id="sw-ollama-url" type="text" placeholder="http://127.0.0.1:11434/v1" value="http://127.0.0.1:11434/v1" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
        <div style="margin-top:8px;padding:10px 14px;background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.2);border-radius:6px;font-size:0.78em;color:var(--dim)">
          💡 Ollama must be running locally. Install from <a href="https://ollama.com" target="_blank" style="color:var(--cyan)">ollama.com</a> then run <code style="background:var(--bg3);padding:2px 6px;border-radius:3px">ollama pull qwen3:8b</code>
        </div>
      </div>
      <!-- NVIDIA single-key field -->
      <div id="sw-nvidia-wrap" style="display:none;margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">
          NVIDIA API Key — one key works for <strong>all 500+ models</strong> on
          <a href="https://build.nvidia.com/models" target="_blank" style="color:var(--cyan)">build.nvidia.com</a>
        </label>
        <input id="sw-nvidia-key" type="password" placeholder="nvapi-..." style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em;margin-bottom:10px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">
          Model — pick a popular one or paste any model ID from
          <a href="https://build.nvidia.com/models" target="_blank" style="color:var(--cyan)">build.nvidia.com</a>:
        </label>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
          <button type="button" onclick="swNvSet('deepseek-ai/deepseek-v3.2')"         style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">DeepSeek V3.2</button>
          <button type="button" onclick="swNvSet('qwen/qwen3-coder-480b-a35b-instruct')" style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">Qwen3-Coder 480B</button>
          <button type="button" onclick="swNvSet('moonshot-ai/kimi-k2-instruct')"       style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">Kimi K2</button>
          <button type="button" onclick="swNvSet('meta/llama-3.3-70b-instruct')"        style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">Llama 3.3 70B</button>
          <button type="button" onclick="swNvSet('mistralai/mistral-large-2-instruct')" style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">Mistral Large 2</button>
          <button type="button" onclick="swNvSet('nvidia/llama-3.3-nemotron-super-49b-v1')" style="padding:4px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:5px;color:var(--cyan);font-size:0.75em;cursor:pointer">Nemotron 49B</button>
        </div>
        <input id="sw-nvidia-model" type="text" placeholder="or paste any model ID, e.g. deepseek-ai/deepseek-v3.2" style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.82em">
      </div>
      <button onclick="swNextStep(1,2)" style="width:100%;padding:12px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
    </div>

    <!-- Step 2: Additional API Keys -->
    <div id="sw-step-2" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 2 OF 7 — ADDITIONAL PROVIDERS</div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:8px">Add more providers to unlock the full model grid. Keys entered here are saved but only used when you switch to that provider. All optional.</div>
      <div style="background:rgba(6,182,212,0.08);border:1px solid rgba(6,182,212,0.25);border-radius:8px;padding:8px 12px;margin-bottom:14px;font-size:0.78em;color:var(--cyan)">🎤 <strong>Voice messages (STT):</strong> Add an <strong>OpenAI</strong> or <strong>Groq</strong> key to enable Telegram voice transcription. Groq is free.</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div id="sw-extra-google">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🌐 Google Gemini <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-google-key" type="password" placeholder="AIzaSy..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-anthropic">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🤖 Anthropic Claude <a href="https://console.anthropic.com/keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-anthropic-key" type="password" placeholder="sk-ant-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-openai">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🧠 OpenAI <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-openai-key" type="password" placeholder="sk-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-xai">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">⚡ xAI Grok <a href="https://console.x.ai" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-xai-key" type="password" placeholder="xai-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-groq">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🚀 Groq <a href="https://console.groq.com/keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-groq-key" type="password" placeholder="gsk_..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-mistral">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🇪🇺 Mistral <a href="https://console.mistral.ai/api-keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-mistral-key" type="password" placeholder="..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-cerebras">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">⚙️ Cerebras <a href="https://cloud.cerebras.ai" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-cerebras-key" type="password" placeholder="csk-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-openrouter">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🔀 OpenRouter <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-openrouter-key" type="password" placeholder="sk-or-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-huggingface">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🤗 HuggingFace <a href="https://huggingface.co/settings/tokens" target="_blank" style="color:var(--cyan)">[get token]</a></label>
          <input id="sw-huggingface-key" type="password" placeholder="hf_..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-kimi">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🌙 Kimi / Moonshot <a href="https://platform.moonshot.cn/console/api-keys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-kimi-key" type="password" placeholder="Bearer token..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-zai">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🔷 ZAI / GLM <a href="https://open.bigmodel.cn/usercenter/apikeys" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-zai-key" type="password" placeholder="zai-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
        <div id="sw-extra-minimax">
          <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">🎵 MiniMax <a href="https://platform.minimaxi.com/user-center/basic-information/interface-key" target="_blank" style="color:var(--cyan)">[get key]</a></label>
          <input id="sw-minimax-key" type="password" placeholder="..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
        </div>
      </div>
      <!-- TTS Section -->
      <div style="margin-top:18px;padding:14px;background:rgba(0,243,255,0.04);border:1px solid rgba(0,243,255,0.15);border-radius:10px">
        <div style="font-size:0.72em;letter-spacing:2px;color:var(--cyan);margin-bottom:10px">🔊 TEXT-TO-SPEECH (OPTIONAL)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div>
            <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">ElevenLabs API Key <a href="https://elevenlabs.io" target="_blank" style="color:var(--cyan)">[get key]</a> <span style="color:var(--dim)">(optional)</span></label>
            <input id="sw-elevenlabs-key" type="password" placeholder="xi_... (leave blank for free voices)" style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
          </div>
          <div>
            <label style="font-size:0.75em;color:var(--dim);display:block;margin-bottom:4px">TTS Voice</label>
            <select id="sw-elevenlabs-voice" style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em">
              <optgroup label="FREE — Microsoft Neural (no key needed)">
                <option value="Guy" selected>Guy — natural male (free) ✓</option>
                <option value="Davis">Davis — expressive male (free)</option>
                <option value="Aria">Aria — natural female (free)</option>
                <option value="Jenny">Jenny — friendly female (free)</option>
              </optgroup>
              <optgroup label="Premium — ElevenLabs (API key required)">
                <option value="Byte">Byte (Adam) — AI male</option>
                <option value="Nova">Nova (Rachel) — warm female</option>
              </optgroup>
              <optgroup label="Fallback">
                <option value="gtts">gTTS — basic female (free)</option>
              </optgroup>
            </select>
          </div>
        </div>
        <div style="margin-top:6px;font-size:0.72em;color:var(--dim)">💡 Free Microsoft voices work without any API key. ElevenLabs provides the highest quality.</div>
      </div>
      <div style="display:flex;gap:10px;margin-top:20px">
        <button onclick="swNextStep(2,1)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(2,3)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 3: Telegram (optional) -->
    <div id="sw-step-3" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 3 OF 7 — TELEGRAM BOT <span style="color:var(--dim)">(optional)</span></div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:18px">Connect a Telegram bot to control Galactic AI from anywhere on your phone.</div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">Bot Token <span style="font-size:0.85em">(from <a href="https://t.me/BotFather" target="_blank" style="color:var(--cyan)">@BotFather</a>)</span></label>
          <input id="sw-tg-token" type="password" placeholder="1234567890:AAF..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">Your Chat ID <span style="font-size:0.85em">(message <a href="https://t.me/userinfobot" target="_blank" style="color:var(--cyan)">@userinfobot</a>)</span></label>
          <input id="sw-tg-chat" type="text" placeholder="123456789" style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:22px">
        <button onclick="swNextStep(3,2)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(3,4)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 4: Security -->
    <div id="sw-step-4" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 4 OF 7 — SECURITY</div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:18px">Set a passphrase to protect your Galactic AI web UI.</div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">System Name <span style="color:var(--dim)">(shown in UI)</span></label>
          <input id="sw-sysname" type="text" placeholder="Galactic AI" value="Galactic AI" style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">Web UI Passphrase <span style="color:var(--dim)">(leave blank for no password)</span></label>
          <input id="sw-pw" type="password" placeholder="Choose a passphrase..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:22px">
        <button onclick="swNextStep(4,3)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(4,5)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 5: Personality -->
    <div id="sw-step-5" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 5 OF 7 — PERSONALITY</div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:18px">Choose the personality for your AI assistant.</div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <label style="display:flex;align-items:flex-start;gap:10px;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;cursor:pointer" onclick="document.getElementById('sw-persona-byte').checked=true;document.getElementById('sw-custom-fields').style.display='none'">
          <input type="radio" name="sw-persona" id="sw-persona-byte" value="byte" checked style="margin-top:3px">
          <div><div style="font-weight:600;font-size:0.88em">⬡ Byte <span style="color:var(--dim);font-weight:400;font-size:0.85em">(Recommended)</span></div><div style="font-size:0.75em;color:var(--dim);margin-top:2px">Techno-hippie AI familiar. Chill, resourceful, opinionated. The default Galactic AI personality.</div></div>
        </label>
        <label style="display:flex;align-items:flex-start;gap:10px;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;cursor:pointer" onclick="document.getElementById('sw-persona-custom').checked=true;document.getElementById('sw-custom-fields').style.display='block'">
          <input type="radio" name="sw-persona" id="sw-persona-custom" value="custom" style="margin-top:3px">
          <div><div style="font-weight:600;font-size:0.88em">✏️ Custom</div><div style="font-size:0.75em;color:var(--dim);margin-top:2px">Define your own AI name, personality, and behavior.</div></div>
        </label>
        <label style="display:flex;align-items:flex-start;gap:10px;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:9px;cursor:pointer" onclick="document.getElementById('sw-persona-generic').checked=true;document.getElementById('sw-custom-fields').style.display='none'">
          <input type="radio" name="sw-persona" id="sw-persona-generic" value="generic" style="margin-top:3px">
          <div><div style="font-weight:600;font-size:0.88em">🤖 Generic Assistant</div><div style="font-size:0.75em;color:var(--dim);margin-top:2px">Neutral, professional AI. No personality — just the facts.</div></div>
        </label>
      </div>
      <div id="sw-custom-fields" style="display:none;margin-top:16px;display:flex;flex-direction:column;gap:12px">
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">AI Name</label>
          <input id="sw-persona-name" type="text" placeholder="e.g. Nova, Spark, Atlas..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">Personality / Soul <span style="color:var(--dim)">(describe how the AI should behave)</span></label>
          <textarea id="sw-persona-soul" rows="3" placeholder="e.g. You are a witty, curious assistant who loves science and dad jokes..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em;resize:vertical"></textarea>
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">User Context <span style="color:var(--dim)">(optional — tell the AI about yourself)</span></label>
          <textarea id="sw-persona-context" rows="2" placeholder="e.g. I'm a software developer who likes hiking and coffee..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.85em;resize:vertical"></textarea>
        </div>
      </div>
      <div style="margin-top:14px;padding:10px;background:rgba(0,243,255,0.05);border:1px solid rgba(0,243,255,0.15);border-radius:8px;font-size:0.72em;color:var(--dim)">
        💡 If you import files from OpenClaw in the next step, your IDENTITY.md and SOUL.md will override this selection.
      </div>
      <div style="display:flex;gap:10px;margin-top:22px">
        <button onclick="swNextStep(5,4)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(5,6)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 6: OpenClaw Migration -->
    <div id="sw-step-6" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 6 OF 7 — OPENCLAW MIGRATION <span style="color:var(--dim)">(optional)</span></div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:18px">Import your identity and memory files from an existing OpenClaw installation. This copies your USER.md, IDENTITY.md, SOUL.md, MEMORY.md, and TOOLS.md into Galactic AI.</div>
      <div id="sw-oc-checking" style="padding:16px;text-align:center;color:var(--dim);font-size:0.85em">🔍 Checking for OpenClaw installation...</div>
      <div id="sw-oc-not-found" style="display:none;padding:16px;background:rgba(136,136,136,0.07);border:1px solid rgba(136,136,136,0.2);border-radius:10px;text-align:center;color:var(--dim);font-size:0.85em">
        OpenClaw installation not detected — nothing to import. Click Next to continue.
      </div>
      <div id="sw-oc-found" style="display:none">
        <div style="padding:10px 14px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.2);border-radius:8px;font-size:0.78em;color:var(--green);margin-bottom:14px">
          ✅ OpenClaw detected at <span id="sw-oc-path" style="font-family:var(--mono)"></span>
        </div>
        <div style="font-size:0.78em;color:var(--dim);margin-bottom:10px">Select files to import (all available files are checked by default):</div>
        <div id="sw-oc-file-list" style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px"></div>
        <button onclick="swMigrateOpenClaw()" id="sw-oc-import-btn" style="width:100%;padding:10px;background:linear-gradient(135deg,rgba(0,255,136,0.8),rgba(0,243,255,0.8));border:none;border-radius:9px;color:#000;font-weight:700;cursor:pointer;font-size:0.88em">⬡ Import Selected Files</button>
        <div id="sw-oc-result" style="margin-top:10px;font-size:0.78em;display:none"></div>
      </div>
      <div style="display:flex;gap:10px;margin-top:22px">
        <button onclick="swNextStep(6,5)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(6,7)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 7: Review & Save -->
    <div id="sw-step-7" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 7 OF 7 — REVIEW &amp; LAUNCH</div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:20px">Everything looks good? Hit Save &amp; Launch to start using Galactic AI.</div>
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:16px;font-size:0.82em;line-height:2;margin-bottom:20px">
        <div>Provider: <span id="sw-review-provider" style="color:var(--cyan)">—</span></div>
        <div>Model: <span id="sw-review-model" style="color:var(--cyan)">—</span></div>
        <div>Additional providers: <span id="sw-review-extras" style="color:var(--dim)">—</span></div>
        <div>TTS: <span id="sw-review-tts" style="color:var(--dim)">—</span></div>
        <div>Web password: <span id="sw-review-pw" style="color:var(--green)">—</span></div>
        <div>Telegram: <span id="sw-review-tg" style="color:var(--dim)">—</span></div>
        <div>Personality: <span id="sw-review-persona" style="color:var(--cyan)">—</span></div>
      </div>
      <div style="display:flex;gap:10px">
        <button onclick="swNextStep(7,6)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button id="sw-save-btn" onclick="swFillReview();swSave()" style="flex:1;padding:13px;background:linear-gradient(135deg,var(--green),var(--cyan));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:1em">⬡ Save &amp; Launch</button>
      </div>
      <div style="margin-top:16px;text-align:center;font-size:0.75em;color:var(--dim)">
        Settings are saved to <code style="background:var(--bg3);padding:2px 6px;border-radius:3px">config.yaml</code> in your Galactic AI folder. You can edit them anytime.
      </div>
    </div>
  </div>
</div>

<!-- TOAST NOTIFICATIONS -->
<div id="toast-container"></div>

<!-- TOP BAR -->
<div id="topbar">
  <div class="logo">⬡ GALACTIC AI</div>
  <div style="font-size:0.7em;color:var(--cyan);letter-spacing:2px;opacity:0.7;font-weight:600">CONTROL DECK</div>
  <div id="version-badge" style="font-size:0.65em;color:var(--dim);letter-spacing:1px;padding:2px 7px;border:1px solid var(--border);border-radius:10px;cursor:default" title="Galactic AI version">v0.9.1</div>
  <div id='ollama-pill' onclick='switchTab("models")'>
    <div class="status-dot" id="ollama-dot"></div>
    <span id="ollama-label">Ollama</span>
  </div>
  <div id='model-badge' onclick='switchTab("models")'>Loading...</div>
  <div class="spacer"></div>
  <div id="token-counter">↑0 ↓0 tokens</div>
  <button class="topbar-btn" onclick="clearChat()">🗑 Clear</button>
  <button class="topbar-btn" onclick="switchTab('logs')">📋 Logs</button>
  <button class="topbar-btn" onclick="showSetupWizard({})" title="Re-run Setup Wizard — add API keys, change settings">⚙ Setup</button>
  <button class="topbar-btn" onclick="openDisplaySettings()" title="Display Settings — font size, CRT effect, etc.">🖥 Display</button>
  <button class="topbar-btn" onclick="location.reload()">↺</button>
</div>

<!-- DISPLAY SETTINGS MODAL -->
<div id="display-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:6000;align-items:center;justify-content:center;backdrop-filter:blur(4px)">
  <div style="background:var(--bg2);border:1px solid var(--cyan);border-radius:18px;padding:30px 34px;width:420px;max-width:95vw;box-shadow:0 0 50px rgba(0,243,255,0.15)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px">
      <h3 style="color:var(--cyan);letter-spacing:2px;font-size:1.05rem;text-shadow:0 0 10px rgba(0,243,255,0.4)">🖥 DISPLAY SETTINGS</h3>
      <span onclick="closeDisplaySettings()" style="cursor:pointer;color:var(--dim);font-size:1.4em;line-height:1" title="Close">&times;</span>
    </div>

    <!-- Font Size -->
    <div style="margin-bottom:22px">
      <label style="display:flex;justify-content:space-between;align-items:center;font-size:0.85rem;color:var(--dim);margin-bottom:10px;letter-spacing:1px;text-transform:uppercase">
        Font Size
        <span id="fs-label" style="color:var(--cyan);font-family:var(--mono);font-weight:700;font-size:1rem">17px</span>
      </label>
      <input type="range" id="fs-slider" min="13" max="26" step="1" value="17"
        oninput="applyFontSize(this.value)"
        style="width:100%;accent-color:var(--cyan);cursor:pointer;height:6px">
      <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--dim);margin-top:5px">
        <span>Small (13px)</span><span>Large (26px)</span>
      </div>
    </div>

    <!-- CRT Scanlines -->
    <div style="margin-bottom:22px;display:flex;align-items:center;justify-content:space-between;padding:14px 16px;background:var(--bg3);border-radius:10px;border:1px solid var(--border)">
      <div>
        <div style="font-size:0.88rem;color:var(--text);margin-bottom:3px">CRT Scanlines</div>
        <div style="font-size:0.76rem;color:var(--dim)">Retro scanline overlay effect</div>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" id="crt-toggle" onchange="applyCRT(this.checked)">
        <span class="toggle-slider"></span>
      </label>
    </div>

    <!-- Glow Intensity -->
    <div style="margin-bottom:24px">
      <label style="display:flex;justify-content:space-between;align-items:center;font-size:0.85rem;color:var(--dim);margin-bottom:10px;letter-spacing:1px;text-transform:uppercase">
        Neon Glow Intensity
        <span id="glow-label" style="color:var(--cyan);font-family:var(--mono);font-weight:700;font-size:1rem">Medium</span>
      </label>
      <input type="range" id="glow-slider" min="0" max="2" step="1" value="1"
        oninput="applyGlow(this.value)"
        style="width:100%;accent-color:var(--cyan);cursor:pointer;height:6px">
      <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--dim);margin-top:5px">
        <span>Off</span><span>Medium</span><span>Max</span>
      </div>
    </div>

    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn secondary" onclick="resetDisplaySettings()">Reset Defaults</button>
      <button class="btn primary" onclick="closeDisplaySettings()">Done</button>
    </div>
  </div>
</div>

<!-- MAIN -->
<div id="main">

  <!-- SIDEBAR -->
  <div id="sidebar">
    <div class="sidebar-section">Navigation</div>
    <div class="sidebar-item active" onclick="switchTab('chat')"><span class="icon">💬</span> Chat</div>
    <div class="sidebar-item" onclick="switchTab('tools')"><span class="icon">🔧</span> Tools<span class="badge" id="tool-count-badge">72</span></div>
    <div class="sidebar-item" onclick="switchTab('plugins')"><span class="icon">🔌</span> Plugins</div>
    <div class="sidebar-item" onclick="switchTab('models')"><span class="icon">🧠</span> Models</div>
    <div class="sidebar-item" onclick="switchTab('browser')"><span class="icon">🌐</span> Browser</div>
    <div class="sidebar-item" onclick="switchTab('memory')"><span class="icon">💾</span> Memory</div>
    <div class="sidebar-item" onclick="switchTab('status')"><span class="icon">📊</span> Status</div>
    <div class="sidebar-item" onclick="switchTab('settings')"><span class="icon">⚙️</span> Settings</div>
    <div class="sidebar-item" onclick="switchTab('logs')"><span class="icon">📋</span> Logs</div>
    <div class="sidebar-item" onclick="switchTab('thinking')"><span class="icon">🧠</span> Thinking</div>
  </div>

  <!-- CONTENT -->
  <div id="content">
    <div id="tabbar">
      <button class="tab-btn active" onclick="switchTab('chat')">💬 Chat</button>
      <button class="tab-btn" onclick="switchTab('tools')">🔧 Tools</button>
      <button class="tab-btn" onclick="switchTab('plugins')">🔌 Plugins</button>
      <button class="tab-btn" onclick="switchTab('models')">🧠 Models</button>
      <button class="tab-btn" onclick="switchTab('browser')">🌐 Browser</button>
      <button class="tab-btn" onclick="switchTab('memory')">💾 Memory</button>
      <button class="tab-btn" onclick="switchTab('status')">📊 Status</button>
      <button class="tab-btn" onclick="switchTab('settings')">⚙️ Settings</button>
      <button class="tab-btn" onclick="switchTab('logs')">📋 Logs</button>
      <button class="tab-btn" id="thinking-tab-btn" onclick="switchTab('thinking')">🧠 Thinking</button>
    </div>

    <!-- CHAT -->
    <div class="tab-pane active" id="tab-chat">
      <div id="chat-wrap">
        <div style="display:flex;flex-direction:column;flex:1;overflow:hidden">
          <div id="chat-log">
            <div class="msg bot"><div class="bubble">⬡ Galactic AI online. How can I help?</div></div>
            <div id="stream-bubble"></div>
          </div>
          <div id="chat-attach-bar" style="display:none;padding:4px 16px 0;border-top:1px solid var(--border);background:var(--bg2)"></div>
          <div id="chat-input-row" style="display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--border);flex-shrink:0;background:var(--bg2)">
            <input type="file" id="chat-file-input" multiple accept=".txt,.md,.py,.js,.ts,.json,.yaml,.yml,.xml,.html,.css,.csv,.log,.toml,.ini,.cfg,.sh,.ps1,.bat,.rs,.go,.java,.c,.cpp,.h,.hpp,.rb,.php,.sql,.r,.swift,.kt,.dart,.env,.conf,.properties,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif,.heic,.heif,.avif,.svg,image/*" style="display:none" onchange="handleFileAttach(this)">
            <button id="attach-btn" onclick="document.getElementById('chat-file-input').click()" title="Attach files" style="padding:10px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--dim);cursor:pointer;font-size:1.1em;transition:border .2s,color .2s" onmouseover="this.style.borderColor='var(--cyan)';this.style.color='var(--cyan)'" onmouseout="this.style.borderColor='var(--border)';this.style.color='var(--dim)'">📎</button>
            <textarea id="chat-input-main" placeholder="Message Byte... (Enter to send, Shift+Enter for newline)" style="flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--text);font-family:var(--font);font-size:0.9em;resize:none;height:44px;max-height:200px;overflow-y:auto;outline:none;transition:border .2s" onkeydown="handleKeyMain(event)" oninput="autoResize(this)"></textarea>
            <button id="voice-btn" onclick="toggleVoiceInput()" title="Voice input (hold or click to record)" style="padding:10px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--dim);cursor:pointer;font-size:1.1em;transition:border .2s,color .2s,background .2s" onmouseover="if(!this.classList.contains('recording'))this.style.borderColor='var(--cyan)',this.style.color='var(--cyan)'" onmouseout="if(!this.classList.contains('recording'))this.style.borderColor='var(--border)',this.style.color='var(--dim)'">🎤</button>
            <button id="send-btn-main" onclick="sendChatMain()" style="padding:10px 22px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.9em">Send ▶</button>
          </div>
        </div>
        <div id="chat-tools-sidebar">
          <h4>Quick Tools</h4>
          <button class="quick-tool-btn" onclick="quickTool('web_search')"><span class="tool-icon">🔍</span>Web Search</button>
          <button class="quick-tool-btn" onclick="quickTool('web_fetch')"><span class="tool-icon">🌐</span>Web Fetch</button>
          <button class="quick-tool-btn" onclick="quickTool('screenshot')"><span class="tool-icon">📸</span>Screenshot</button>
          <button class="quick-tool-btn" onclick="quickTool('open_browser')"><span class="tool-icon">🌍</span>Open URL</button>
          <button class="quick-tool-btn" onclick="quickTool('exec_shell')"><span class="tool-icon">💻</span>Shell</button>
          <button class="quick-tool-btn" onclick="quickTool('read_file')"><span class="tool-icon">📄</span>Read File</button>
          <button class="quick-tool-btn" onclick="quickTool('write_file')"><span class="tool-icon">✏️</span>Write File</button>
          <button class="quick-tool-btn" onclick="quickTool('memory_search')"><span class="tool-icon">🧠</span>Memory Search</button>
          <button class="quick-tool-btn" onclick="quickTool('memory_imprint')"><span class="tool-icon">💡</span>Imprint Memory</button>
          <button class="quick-tool-btn" onclick="quickTool('analyze_image')"><span class="tool-icon">👁️</span>Analyze Image</button>
          <button class="quick-tool-btn" onclick="quickTool('text_to_speech')"><span class="tool-icon">🔊</span>Text to Speech</button>
          <div style="padding:2px 14px 8px;border-bottom:1px solid rgba(255,255,255,0.04)">
            <div style="font-size:0.65em;color:var(--dim);letter-spacing:1px;margin-bottom:3px">VOICE</div>
            <select id="quick-voice-select" onchange="saveQuickVoice(this.value)" style="width:100%;padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--text);font-size:0.78em;cursor:pointer">
              <option value="Guy">🗣️ Guy — Edge TTS</option>
              <option value="Aria">🗣️ Aria — Edge TTS</option>
              <option value="Jenny">🗣️ Jenny — Edge TTS</option>
              <option value="Davis">🗣️ Davis — Edge TTS</option>
              <option value="Nova">⭐ Nova — ElevenLabs</option>
              <option value="Byte">⭐ Byte — ElevenLabs</option>
              <option value="gtts">🗣️ Google TTS</option>
            </select>
          </div>
          <button class="quick-tool-btn" onclick="quickTool('browser_save_session')"><span class="tool-icon">💾</span>Save Session</button>
          <button class="quick-tool-btn" onclick="quickTool('browser_response_body')"><span class="tool-icon">📡</span>Response Body</button>
          <button class="quick-tool-btn" onclick="quickTool('schedule_task')"><span class="tool-icon">⏰</span>Schedule Task</button>
        </div>
      </div>
    </div>

    <!-- TOOLS -->
    <div class="tab-pane" id="tab-tools">
      <div id="tools-pane">
        <h3>🔧 ALL TOOLS (72 registered)</h3>
        <input id="tool-search" type="text" placeholder="Search tools..." oninput="filterTools(this.value)">
        <div id="tools-list"></div>
      </div>
    </div>

    <!-- PLUGINS -->
    <div class="tab-pane" id="tab-plugins">
      <div id="plugins-pane">
        <h3>🔌 PLUGINS &amp; SYSTEMS</h3>
        <div id="plugins-list">Loading...</div>
      </div>
    </div>

    <!-- MODELS -->
    <div class="tab-pane" id="tab-models">
      <div id="models-pane">
        <h3>🧠 MODEL MATRIX</h3>
        <div id="ollama-health-row">
          <div class="status-dot" id="ollama-health-dot"></div>
          <span id="ollama-health">Checking Ollama...</span>
          <span style="margin-left:auto;font-size:0.75em;color:var(--dim)" id="ollama-model-count"></span>
          <button onclick="refreshOllama()" style="padding:3px 10px;background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--text);cursor:pointer;font-size:0.75em">Refresh</button>
        </div>
        <div class="model-config-box">
          <h4>ACTIVE MODEL OVERRIDE</h4>
          <div class="model-config-row">
            <label>Provider</label>
            <select id="cfg-provider" onchange="updateModelList()">
              <option value="google">Google</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="xai">xAI</option>
              <option value="groq">Groq</option>
              <option value="mistral">Mistral</option>
              <option value="cerebras">Cerebras</option>
              <option value="openrouter">OpenRouter</option>
              <option value="huggingface">HuggingFace</option>
              <option value="kimi">Kimi</option>
              <option value="zai">ZAI/GLM</option>
              <option value="minimax">MiniMax</option>
              <option value="nvidia">NVIDIA</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
          <div class="model-config-row">
            <label>Model ID</label>
            <input id="cfg-model" type="text" placeholder="model-id">
          </div>
          <div class="model-config-row">
            <label title="Max output tokens (0 = provider default)">Max Tokens</label>
            <input id="cfg-max-tokens" type="number" placeholder="0 = default" min="0" max="200000">
          </div>
          <div class="model-config-row">
            <label title="Context window size (0 = auto-detect)">Context Window</label>
            <input id="cfg-context-window" type="number" placeholder="0 = auto" min="0" max="2000000">
          </div>
          <div style="margin-top:8px;display:flex;gap:8px">
            <button class="btn primary" onclick="applyModelOverride()">Apply Model</button>
            <button class="btn secondary" onclick="applyModelConfig()">Save Token Config</button>
          </div>
        </div>
        <!-- PER-MODEL OVERRIDES -->
        <div class="model-config-box" style="margin-top:18px">
          <h4>PER-MODEL OVERRIDES</h4>
          <div style="font-size:0.78em;color:var(--dim);margin-bottom:10px">
            Set max tokens and context window per model. Takes precedence over global settings above.
            Use the exact model ID (e.g. <code>gemini-2.5-flash</code>, <code>claude-sonnet-4-5</code>, <code>llama3.3:70b</code>) or an alias.
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:flex-end;margin-bottom:8px">
            <div style="flex:2;min-width:120px">
              <div style="font-size:0.72em;color:var(--dim);margin-bottom:3px">Model</div>
              <select id="pmo-model" style="width:100%;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em;cursor:pointer">
                <option value="">-- select model --</option>
              </select>
              <input id="pmo-model-custom" type="text" placeholder="or type custom model ID..." style="width:100%;padding:5px 10px;background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--dim);font-size:0.76em;margin-top:4px">
            </div>
            <div style="flex:1;min-width:90px">
              <div style="font-size:0.72em;color:var(--dim);margin-bottom:3px">Max Tokens</div>
              <input id="pmo-max-tokens" type="number" placeholder="0 = global" min="0" max="200000" style="width:100%;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
            </div>
            <div style="flex:1;min-width:90px">
              <div style="font-size:0.72em;color:var(--dim);margin-bottom:3px">Context Window</div>
              <input id="pmo-context-window" type="number" placeholder="0 = global" min="0" max="2000000" style="width:100%;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
            </div>
            <button class="btn primary" onclick="pmoSave()" style="padding:7px 16px;white-space:nowrap">Add / Update</button>
          </div>
          <div id="pmo-list" style="margin-top:4px"></div>
        </div>
        <div id="model-grid-root"></div>
      </div>
    </div>

    <!-- BROWSER -->
    <div class="tab-pane" id="tab-browser">
      <div id="browser-pane">
        <h3>🌐 BROWSER CONTROL</h3>
        <div class="browser-url-row">
          <input id="browser-url" type="text" placeholder="https://example.com" onkeydown="if(event.key==='Enter')browserNav()">
          <button class="btn primary" onclick="browserNav()">Go</button>
          <button class="btn secondary" onclick="browserCmd('start')">Launch</button>
        </div>
        <div class="browser-action-grid">
          <button class="browser-btn" onclick="browserCmd('screenshot_quick')">📸 Screenshot</button>
          <button class="browser-btn" onclick="browserCmd('scroll',{direction:'down'})">↓ Scroll Down</button>
          <button class="browser-btn" onclick="browserCmd('scroll',{direction:'up'})">↑ Scroll Up</button>
          <button class="browser-btn" onclick="browserCmd('snapshot_quick')">🔍 Snapshot</button>
          <button class="browser-btn" onclick="browserCmd('get_frames')">🖼 List Frames</button>
          <button class="browser-btn" onclick="browserCmd('get_console_logs')">🖥 Console Logs</button>
          <button class="browser-btn" onclick="browserCmd('get_page_errors')">⚠️ Page Errors</button>
          <button class="browser-btn" onclick="browserCmd('get_network_requests')">📡 Network</button>
          <button class="browser-btn" onclick="browserCmd('save_session',{session_name:'default'})">&#x1f4be; Save Session</button>
          <button class="browser-btn" onclick="browserCmd('load_session',{session_name:'default'})">&#x1f4c2; Load Session</button>
          <button class="browser-btn" onclick="browserCmd('generate_pdf')">📄 PDF</button>
          <button class="browser-btn" onclick="browserCmd('close')">&#x2715; Close</button>
        </div>
        <div id="browser-status">Browser not started.</div>
        <img id="browser-screenshot" alt="screenshot">
      </div>
    </div>

    <!-- MEMORY -->
    <div class="tab-pane" id="tab-memory">
      <div id="memory-pane">
        <h3>💾 MEMORY FILES</h3>
        <div class="mem-controls">
          <select id="mem-file-select" onchange="loadMemFile(this.value)"><option>Loading...</option></select>
          <button class="btn primary" onclick="saveMemFile()">Save</button>
          <button class="btn secondary" onclick="loadFileList()">Refresh</button>
        </div>
        <textarea id="mem-editor" placeholder="Select a file to edit..."></textarea>
      </div>
    </div>

    <!-- STATUS -->
    <div class="tab-pane" id="tab-status">
      <div id="status-pane" style="overflow-y:auto;padding-bottom:40px">
        <h3>📊 SYSTEM STATUS</h3>
        <button class="btn secondary" onclick="refreshStatus()" style="margin-bottom:14px">Refresh Status</button>

        <!-- Section 1: System Overview -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:14px 0 8px;text-transform:uppercase">System Overview</div>
        <div class="stat-grid">
          <div class="stat-card"><div class="val" id="st-uptime">--</div><div class="lbl">Uptime</div></div>
          <div class="stat-card"><div class="val" id="st-version">--</div><div class="lbl">Version</div></div>
          <div class="stat-card"><div class="val" id="st-personality">--</div><div class="lbl">Personality</div></div>
          <div class="stat-card"><div class="val" id="st-tin">--</div><div class="lbl">Tokens In</div></div>
          <div class="stat-card"><div class="val" id="st-tout">--</div><div class="lbl">Tokens Out</div></div>
          <div class="stat-card"><div class="val" id="st-tools">--</div><div class="lbl">Tools</div></div>
        </div>

        <!-- Section 2: Model & AI -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Model & AI</div>
        <div class="stat-grid">
          <div class="stat-card"><div class="val" id="st-model" style="font-size:1.1em">--</div><div class="lbl">Active Model</div></div>
          <div class="stat-card"><div class="val" id="st-provider">--</div><div class="lbl">Provider</div></div>
          <div class="stat-card"><div class="val" id="st-mode">--</div><div class="lbl">Mode</div></div>
          <div class="stat-card"><div class="val" id="st-max-turns">--</div><div class="lbl">Max Turns</div></div>
          <div class="stat-card"><div class="val" id="st-streaming">--</div><div class="lbl">Streaming</div></div>
          <div class="stat-card"><div class="val" id="st-auto-fb">--</div><div class="lbl">Auto-Fallback</div></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
          <div class="stat-card" style="text-align:left;padding:14px 18px">
            <div class="lbl" style="margin-bottom:8px">Primary Model</div>
            <div id="st-primary" style="font-family:var(--mono);font-size:0.9em;color:var(--green)">--</div>
          </div>
          <div class="stat-card" style="text-align:left;padding:14px 18px">
            <div class="lbl" style="margin-bottom:8px">Fallback Model</div>
            <div id="st-fallback" style="font-family:var(--mono);font-size:0.9em;color:var(--yellow)">--</div>
          </div>
        </div>

        <!-- Fallback Chain -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Fallback Chain</div>
        <div id="st-fallback-chain" style="margin-bottom:12px"></div>

        <!-- Section 3: Connections -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Connections</div>
        <div class="stat-grid" id="st-connections"></div>

        <!-- Section 4: Providers -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Configured Providers</div>
        <div class="stat-grid" id="st-providers"></div>

        <!-- Section 5: Plugins -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Plugins</div>
        <div id="status-plugins-list"></div>

        <!-- Section 6: Ollama -->
        <div style="font-size:0.72rem;letter-spacing:2px;color:var(--dim);margin:18px 0 8px;text-transform:uppercase">Ollama</div>
        <div class="stat-grid">
          <div class="stat-card"><div class="val" id="st-ollama-status">--</div><div class="lbl">Status</div></div>
          <div class="stat-card"><div class="val" id="st-ollama-models">--</div><div class="lbl">Models</div></div>
        </div>
      </div>
    </div>

    <!-- LOGS -->
    <div class="tab-pane" id="tab-logs">
      <div id="logs-pane">
        <div id="log-controls">
          <input id="log-filter" type="text" placeholder="Filter logs..." oninput="filterLogs(this.value)">
          <button class="btn secondary" onclick="clearLogs()">Clear</button>
          <button class="btn secondary" id="log-auto-scroll-btn" onclick="toggleAutoScroll()">Auto-scroll: ON</button>
        </div>
        <div id="logs-scroll"></div>
      </div>
    </div>

    <!-- THINKING / AGENT TRACE -->
    <!-- SETTINGS -->
    <div class="tab-pane" id="tab-settings">
      <div id="settings-pane" style="padding:18px;overflow-y:auto">
        <h3>⚙️ SETTINGS</h3>

        <!-- Section 1: Model Configuration -->
        <div class="model-config-box">
          <h4>MODEL CONFIGURATION</h4>
          <div class="model-config-row">
            <label>Primary Model</label>
            <div style="display:flex;gap:8px;flex:1">
              <select id="set-primary-provider" onchange="updateSettingsModelList('primary')" style="flex:0.4;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
              </select>
              <select id="set-primary-model" style="flex:0.6;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
              </select>
            </div>
          </div>
          <div class="model-config-row">
            <label>Fallback Model</label>
            <div style="display:flex;gap:8px;flex:1">
              <select id="set-fallback-provider" onchange="updateSettingsModelList('fallback')" style="flex:0.4;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
              </select>
              <select id="set-fallback-model" style="flex:0.6;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
              </select>
            </div>
          </div>
          <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:14px">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.88em">
              <input type="checkbox" id="set-auto-fallback" checked style="accent-color:var(--cyan);width:18px;height:18px;cursor:pointer">
              <span>Auto-Fallback</span>
              <span style="font-size:0.72em;color:var(--dim)">(automatically switch models on API errors)</span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.88em">
              <input type="checkbox" id="set-smart-routing" style="accent-color:var(--cyan);width:18px;height:18px;cursor:pointer">
              <span>Smart Routing</span>
              <span style="font-size:0.72em;color:var(--dim)">(route tasks to best model by type)</span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.88em">
              <input type="checkbox" id="set-streaming" checked style="accent-color:var(--cyan);width:18px;height:18px;cursor:pointer">
              <span>Streaming</span>
            </label>
          </div>
          <div style="margin-top:12px">
            <button class="btn primary" onclick="saveModelSettings()">Save Model Settings</button>
          </div>
        </div>

        <!-- Section 2: Voice -->
        <div class="model-config-box" style="margin-top:18px">
          <h4>VOICE</h4>
          <div style="font-size:0.78em;color:var(--dim);margin-bottom:10px">
            Select the default voice for text-to-speech. ElevenLabs voices require an API key.
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <select id="set-voice" style="flex:1;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em;cursor:pointer">
              <option value="Guy">🗣️ Guy — Edge TTS (Free, male)</option>
              <option value="Aria">🗣️ Aria — Edge TTS (Free, female)</option>
              <option value="Jenny">🗣️ Jenny — Edge TTS (Free, female)</option>
              <option value="Davis">🗣️ Davis — Edge TTS (Free, male)</option>
              <option value="Nova">⭐ Nova — ElevenLabs (Premium, female)</option>
              <option value="Byte">⭐ Byte — ElevenLabs (Premium, male)</option>
              <option value="gtts">🗣️ Google TTS (Free, female)</option>
            </select>
            <button class="btn primary" onclick="saveVoiceSettings()">Save</button>
            <button class="btn secondary" onclick="testVoice()">Test Voice</button>
          </div>
        </div>

        <!-- Section 3: System -->
        <div class="model-config-box" style="margin-top:18px">
          <h4>SYSTEM</h4>
          <div class="model-config-row">
            <label>Update Check Interval</label>
            <select id="set-update-interval" style="flex:1;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
              <option value="21600">Every 6 hours (default)</option>
              <option value="43200">Every 12 hours</option>
              <option value="86400">Every 24 hours</option>
              <option value="0">Disabled</option>
            </select>
          </div>
          <div class="model-config-row">
            <label title="Maximum time a single speak() call can run before being stopped">Speak Timeout (seconds)</label>
            <input id="set-speak-timeout" type="number" value="600" min="60" max="3600" style="flex:1;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
          </div>
          <div class="model-config-row">
            <label title="Maximum ReAct loop turns per query">Max ReAct Turns</label>
            <input id="set-max-turns" type="number" value="50" min="5" max="200" style="flex:1;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
          </div>
          <div style="margin-top:12px">
            <button class="btn primary" onclick="saveSystemSettings()">Save System Settings</button>
          </div>
        </div>

        <!-- Section 4: Display -->
        <div class="model-config-box" style="margin-top:18px">
          <h4>DISPLAY</h4>
          <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
            <label style="display:flex;align-items:center;gap:8px;font-size:0.88em;cursor:pointer">
              <span>Font Size</span>
              <input type="range" id="ds-fontsize" min="13" max="26" value="17" style="accent-color:var(--cyan);width:120px;cursor:pointer" oninput="applyFontSize(this.value)">
              <span id="ds-fontsize-label" style="font-size:0.78em;color:var(--dim);min-width:30px">17px</span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;font-size:0.88em;cursor:pointer">
              <input type="checkbox" id="crt-toggle" onchange="applyCRT(this.checked)" style="accent-color:var(--cyan);width:18px;height:18px;cursor:pointer">
              <span>CRT Scanlines</span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;font-size:0.88em;cursor:pointer">
              <span>Glow</span>
              <select id="ds-glow" onchange="applyGlow(this.value)" style="padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--text);font-size:0.85em;cursor:pointer">
                <option value="0">Off</option>
                <option value="1">Medium</option>
                <option value="2" selected>Max</option>
              </select>
            </label>
          </div>
        </div>

        <!-- Section 5: Power Controls -->
        <div class="model-config-box" style="margin-top:18px">
          <h4>POWER CONTROLS</h4>
          <div style="font-size:0.78em;color:var(--dim);margin-bottom:12px">
            Restart or shut down the Galactic AI process. Restart will reload all modules and reconnect.
          </div>
          <div style="display:flex;gap:12px;flex-wrap:wrap">
            <button class="btn primary" onclick="confirmRestart()" style="background:linear-gradient(135deg,#f0c040,#e08020);color:#000;font-weight:700;padding:10px 28px;font-size:0.92em">
              🔄 Restart Galactic AI
            </button>
            <button class="btn primary" onclick="confirmShutdown()" style="background:linear-gradient(135deg,#ff4060,#c00030);color:#fff;font-weight:700;padding:10px 28px;font-size:0.92em">
              ⏻ Shutdown Galactic AI
            </button>
          </div>
        </div>

      </div>
    </div>

    <div class="tab-pane" id="tab-thinking">
      <div id="thinking-pane">
        <div id="thinking-controls">
          <input id="thinking-filter" type="text" placeholder="Filter traces..." oninput="filterTraces()">
          <select id="thinking-phase-filter" onchange="filterTraces()">
            <option value="">All Phases</option>
            <option value="thinking">Thinking</option>
            <option value="tool_call">Tool Calls</option>
            <option value="tool_result">Tool Results</option>
            <option value="final_answer">Final Answers</option>
            <option value="llm_response">LLM Response</option>
          </select>
          <button class="btn secondary" onclick="clearTraces()">Clear</button>
          <button class="btn secondary" id="thinking-auto-scroll-btn" onclick="toggleThinkingAutoScroll()">Auto-scroll: ON</button>
          <span id="thinking-turn-counter">Turns: 0</span>
        </div>
        <div id="thinking-scroll"></div>
      </div>
    </div>

  </div><!-- /content -->
</div><!-- /main -->

<!-- TOOL MODAL -->
<div id="tool-modal" onclick="closeToolModal(event)">
  <div id="tool-modal-inner">
    <h3 id="modal-title">Tool Name</h3>
    <p id="modal-desc"></p>
    <div id="modal-params"></div>
    <div id="tool-result"></div>
    <div class="modal-btns">
      <button class="btn secondary" onclick="document.getElementById('tool-modal').classList.remove('open')">Cancel</button>
      <button class="btn primary" onclick="runTool()">Run Tool ▶</button>
    </div>
  </div>
</div>

<!-- API KEY MODAL -->
<div id="key-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div id="key-modal-inner">
    <h3 id="key-modal-title">\ud83d\udd11 API Key Required</h3>
    <p id="key-modal-desc">Enter your API key to use this provider.</p>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:0.82rem;color:var(--yellow);margin-bottom:6px;font-family:var(--mono)" id="key-modal-label">API Key</label>
      <input id="key-input" type="password" placeholder="Paste your API key here..." autocomplete="off">
      <div style="font-size:0.72rem;color:var(--dim);margin-top:4px">Your key will be saved to config.yaml and never shared.</div>
    </div>
    <div class="modal-btns">
      <button class="btn secondary" onclick="document.getElementById('key-modal').classList.remove('open')">Cancel</button>
      <button class="btn primary" onclick="submitApiKey()" style="background:linear-gradient(135deg,var(--yellow),var(--orange))">Save &amp; Switch</button>
    </div>
  </div>
</div>

<script>
// State
let token = localStorage.getItem('gal_token') || '';
let socket = null;
let allToolsData = [];
let currentTool = null;
let autoScroll = true;
let allLogs = [];
let httpChatPending = false;  // suppresses WS 'thought' dupes while HTTP /api/chat in flight

// Auth helper — adds JWT Bearer header to all fetch calls
function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}
async function authFetch(url, opts) {
  opts = opts || {};
  opts.headers = authHeaders(opts.headers);
  const r = await fetch(url, opts);
  if (r.status === 401) { localStorage.removeItem('gal_token'); token = ''; document.getElementById('login-overlay').style.display = 'flex'; }
  return r;
}

// ── Setup Wizard ─────────────────────────────────────────────────────────────
async function checkSetup() {
  try {
    const r = await authFetch('/api/check_setup');
    const d = await r.json();
    if (d.needs_setup) {
      showSetupWizard(d);
      return true;
    }
  } catch(e) {}
  return false;
}

function showSetupWizard(status) {
  document.getElementById('login-overlay').style.display = 'none';
  document.getElementById('setup-wizard').style.display = 'flex';
  // pre-fill current provider if known
  if (status && status.current_provider) {
    const sel = document.getElementById('sw-provider');
    if (sel) sel.value = status.current_provider;
    swUpdateModelHint();
  }
}

const SW_MODEL_HINTS = {
  google:      {placeholder:'gemini-3.1-pro-preview', link:'Get key: <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--cyan)">aistudio.google.com/apikey</a>'},
  anthropic:   {placeholder:'claude-sonnet-4-6', link:'Get key: <a href="https://console.anthropic.com/keys" target="_blank" style="color:var(--cyan)">console.anthropic.com/keys</a>'},
  openai:      {placeholder:'gpt-4o', link:'Get key: <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--cyan)">platform.openai.com/api-keys</a>'},
  xai:         {placeholder:'grok-4', link:'Get key: <a href="https://console.x.ai" target="_blank" style="color:var(--cyan)">console.x.ai</a>'},
  groq:        {placeholder:'llama-4-scout-17b-16e-instruct', link:'Get key: <a href="https://console.groq.com/keys" target="_blank" style="color:var(--cyan)">console.groq.com/keys</a>'},
  mistral:     {placeholder:'mistral-small-latest', link:'Get key: <a href="https://console.mistral.ai/api-keys" target="_blank" style="color:var(--cyan)">console.mistral.ai/api-keys</a>'},
  cerebras:    {placeholder:'llama3.3-70b', link:'Get key: <a href="https://cloud.cerebras.ai" target="_blank" style="color:var(--cyan)">cloud.cerebras.ai</a>'},
  openrouter:  {placeholder:'google/gemini-3.1-pro-preview', link:'Get key: <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--cyan)">openrouter.ai/keys</a>'},
  huggingface: {placeholder:'Qwen/Qwen3-235B-A22B', link:'Get token: <a href="https://huggingface.co/settings/tokens" target="_blank" style="color:var(--cyan)">huggingface.co/settings/tokens</a>'},
  kimi:        {placeholder:'kimi-k2.5', link:'Get key: <a href="https://platform.moonshot.cn/console/api-keys" target="_blank" style="color:var(--cyan)">platform.moonshot.cn</a>'},
  zai:         {placeholder:'glm-4-plus', link:'Get key: <a href="https://open.bigmodel.cn/usercenter/apikeys" target="_blank" style="color:var(--cyan)">open.bigmodel.cn</a>'},
  minimax:     {placeholder:'MiniMax-Text-01', link:'Get key: <a href="https://platform.minimaxi.com" target="_blank" style="color:var(--cyan)">platform.minimaxi.com</a>'},
  nvidia:      {placeholder:'deepseek-ai/deepseek-v3.2', link:'500+ models available: <a href="https://build.nvidia.com/models" target="_blank" style="color:var(--cyan)">build.nvidia.com/models</a>'},
  ollama:      {placeholder:'qwen3:8b', link:''}
};

// Quick-pick button helper for NVIDIA model chips
function swNvSet(modelId) {
  const el = document.getElementById('sw-nvidia-model');
  if (el) { el.value = modelId; el.focus(); }
  // Also update the main sw-model field so it is saved correctly
  const swm = document.getElementById('sw-model');
  if (swm) swm.value = modelId;
}

function swUpdateModelHint() {
  const prov = document.getElementById('sw-provider').value;
  const hint = SW_MODEL_HINTS[prov] || {placeholder:'', link:''};
  const inp = document.getElementById('sw-model');
  if (inp) inp.placeholder = hint.placeholder;
  const linkEl = document.getElementById('sw-key-link');
  if (linkEl) linkEl.innerHTML = hint.link;
  // Show/hide API key fields
  document.getElementById('sw-apikey-wrap').style.display = (prov === 'ollama' || prov === 'nvidia') ? 'none' : '';
  document.getElementById('sw-nvidia-wrap').style.display = prov === 'nvidia' ? '' : 'none';
  document.getElementById('sw-ollama-wrap').style.display = prov === 'ollama' ? '' : 'none';
  // Update API key placeholder
  const keyPlaceholders = {
    google:'AIzaSy...', anthropic:'sk-ant-...', openai:'sk-...', xai:'xai-...',
    groq:'gsk_...', mistral:'key...', cerebras:'csk-...', openrouter:'sk-or-...',
    huggingface:'hf_...', kimi:'Bearer token...', zai:'zai-...', minimax:'key...'
  };
  const keyInp = document.getElementById('sw-apikey');
  if (keyInp) keyInp.placeholder = keyPlaceholders[prov] || 'API key...';
}

function swNextStep(currentStep, nextStep) {
  document.getElementById('sw-step-' + currentStep).style.display = 'none';
  document.getElementById('sw-step-' + nextStep).style.display = '';
  document.getElementById('sw-progress').style.width = (nextStep * (100/7)).toFixed(1) + '%';
  // When entering Step 2: pre-fill the provider key from Step 1 to avoid duplicate entry
  if (nextStep === 2) {
    const prov = document.getElementById('sw-provider').value;
    const step1Key = (document.getElementById('sw-apikey') || {value:''}).value.trim();
    if (step1Key) {
      const provMap = {
        google:'sw-google-key', anthropic:'sw-anthropic-key', openai:'sw-openai-key',
        xai:'sw-xai-key', groq:'sw-groq-key', mistral:'sw-mistral-key',
        cerebras:'sw-cerebras-key', openrouter:'sw-openrouter-key',
        huggingface:'sw-huggingface-key', kimi:'sw-kimi-key', zai:'sw-zai-key',
        minimax:'sw-minimax-key'
      };
      const targetId = provMap[prov];
      if (targetId) {
        const targetEl = document.getElementById(targetId);
        if (targetEl && !targetEl.value) {
          targetEl.value = step1Key;
          // Mark the field visually as already-set from step 1
          const container = document.getElementById('sw-extra-' + prov);
          if (container) {
            const note = container.querySelector('.sw-prefill-note');
            if (!note) {
              const n = document.createElement('div');
              n.className = 'sw-prefill-note';
              n.style.cssText = 'font-size:0.7em;color:var(--green);margin-top:3px';
              n.textContent = '✓ Pre-filled from Step 1';
              container.appendChild(n);
            }
          }
        }
      }
    }
  }
  // When entering Step 6: check for OpenClaw
  if (nextStep === 6) swCheckOpenClaw();
  if (nextStep === 7) swFillReview();
}

async function swSave() {
  const btn = document.getElementById('sw-save-btn');
  btn.textContent = 'Saving...';
  btn.disabled = true;

  const prov = document.getElementById('sw-provider').value;
  // For NVIDIA, prefer the dedicated model field / quick-pick chip over sw-model
  const nvModelEl = document.getElementById('sw-nvidia-model');
  const nvModelVal = nvModelEl ? nvModelEl.value.trim() : '';
  const modelVal = (prov === 'nvidia' && nvModelVal) ? nvModelVal : document.getElementById('sw-model').value.trim();
  const modelFinal = modelVal || document.getElementById('sw-model').placeholder.split(' ')[0];

  function gv(id) { const el = document.getElementById(id); return el ? el.value.trim() : ''; }

  const payload = {
    provider: prov,
    model: modelFinal,
    api_key: gv('sw-apikey'),
    password: gv('sw-pw'),
    system_name: gv('sw-sysname') || 'Galactic AI',
    // Per-provider keys
    google_key: gv('sw-google-key'),
    anthropic_key: gv('sw-anthropic-key'),
    openai_key: gv('sw-openai-key'),
    xai_key: gv('sw-xai-key'),
    groq_key: gv('sw-groq-key'),
    mistral_key: gv('sw-mistral-key'),
    cerebras_key: gv('sw-cerebras-key'),
    openrouter_key: gv('sw-openrouter-key'),
    huggingface_key: gv('sw-huggingface-key'),
    kimi_key: gv('sw-kimi-key'),
    zai_key: gv('sw-zai-key'),
    minimax_key: gv('sw-minimax-key'),
    // NVIDIA single key + optional custom model
    nvidia_key: gv('sw-nvidia-key'),
    nvidia_model: gv('sw-nvidia-model'),
    ollama_url: gv('sw-ollama-url') || 'http://127.0.0.1:11434/v1',
    // Telegram
    telegram_token: gv('sw-tg-token'),
    telegram_chat_id: gv('sw-tg-chat'),
    // ElevenLabs TTS
    elevenlabs_key: gv('sw-elevenlabs-key'),
    elevenlabs_voice: gv('sw-elevenlabs-voice') || 'Guy',
    persona_mode: (document.getElementById('sw-persona-custom').checked ? 'custom' : document.getElementById('sw-persona-generic').checked ? 'generic' : 'byte'),
    persona_name: (document.getElementById('sw-persona-name') || {}).value || '',
    persona_soul: (document.getElementById('sw-persona-soul') || {}).value || '',
    persona_context: (document.getElementById('sw-persona-context') || {}).value || '',
  };

  // If primary provider key wasn't entered in step 1, pull from step 2
  if (!payload.api_key) {
    payload.api_key = payload[prov + '_key'] || '';
  }

  try {
    const r = await authFetch('/api/setup', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const d = await r.json();
    if (d.ok) {
      // After setup, save token from new password and go to main UI
      if (payload.password) {
        const lr = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({password: payload.password})});
        const ld = await lr.json();
        if (ld.success) {
          token = ld.token;
          localStorage.setItem('gal_token', token);
        }
      }
      document.getElementById('setup-wizard').style.display = 'none';
      document.getElementById('setup-success').style.display = 'flex';
      setTimeout(() => { document.getElementById('setup-success').style.display = 'none'; init(); }, 2500);
    } else {
      alert('Setup error: ' + (d.error || 'Unknown error'));
      btn.textContent = 'Save & Launch';
      btn.disabled = false;
    }
  } catch(e) {
    alert('Network error: ' + e.message);
    btn.textContent = 'Save & Launch';
    btn.disabled = false;
  }
}

// ── Login ─────────────────────────────────────────────────────────────────────
async function doLogin() {
  const loginBtn = document.getElementById('login-btn');
  const errEl = document.getElementById('login-err');
  const pwEl = document.getElementById('pw-input');
  if (!pwEl) return;
  const pw = pwEl.value.trim();
  if (!pw) { errEl.textContent = 'Enter your passphrase'; errEl.style.display = 'block'; return; }

  if (loginBtn) { loginBtn.disabled = true; loginBtn.textContent = '...'; }
  errEl.style.display = 'none';

  try {
    const r = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw})
    });
    const d = await r.json();
    if (d.success) {
      token = d.token;
      localStorage.setItem('gal_token', token);
      document.getElementById('login-overlay').style.display = 'none';
      if (d.first_run) { showSetupWizard({}); } else { init(); }
    } else {
      errEl.textContent = d.error || 'Invalid passphrase';
      errEl.style.display = 'block';
      if (loginBtn) { loginBtn.disabled = false; loginBtn.textContent = 'ACCESS'; }
    }
  } catch(e) {
    errEl.textContent = 'Connection error: ' + e.message;
    errEl.style.display = 'block';
    if (loginBtn) { loginBtn.disabled = false; loginBtn.textContent = 'ACCESS'; }
  }
}

function swFillReview() {
  const prov = document.getElementById('sw-provider').value;
  const modelVal = document.getElementById('sw-model').value.trim() || document.getElementById('sw-model').placeholder.split(' ')[0];
  const pw = document.getElementById('sw-pw').value;
  const tgToken = document.getElementById('sw-tg-token').value.trim();
  const elevenlabsKey = (document.getElementById('sw-elevenlabs-key') || {value:''}).value.trim();
  const voice = (document.getElementById('sw-elevenlabs-voice') || {value:'gtts'}).value;
  // Count extra providers with keys
  const extraProviders = ['google','anthropic','openai','xai','groq','mistral','cerebras','openrouter','huggingface','kimi','zai','minimax']
    .filter(p => {
      const el = document.getElementById('sw-' + p + '-key');
      return el && el.value.trim();
    });
  document.getElementById('sw-review-provider').textContent = prov;
  document.getElementById('sw-review-model').textContent = modelVal;
  document.getElementById('sw-review-extras').textContent = extraProviders.length ? extraProviders.join(', ') : 'None';
  const freeVoices = ['Guy','Davis','Aria','Jenny','gtts'];
  document.getElementById('sw-review-tts').textContent = (elevenlabsKey && !freeVoices.includes(voice)) ? 'ElevenLabs (' + voice + ')' : 'Free voice: ' + voice;
  document.getElementById('sw-review-pw').textContent = pw ? '✓ Set' : 'None (open access)';
  document.getElementById('sw-review-tg').textContent = tgToken ? '✓ Configured' : 'Not configured';
  const personaMode = document.getElementById('sw-persona-custom').checked ? 'Custom' : document.getElementById('sw-persona-generic').checked ? 'Generic' : 'Byte';
  document.getElementById('sw-review-persona').textContent = personaMode;
}

async function swCheckOpenClaw() {
  document.getElementById('sw-oc-checking').style.display = '';
  document.getElementById('sw-oc-not-found').style.display = 'none';
  document.getElementById('sw-oc-found').style.display = 'none';
  try {
    const r = await authFetch('/api/check_openclaw');
    const d = await r.json();
    document.getElementById('sw-oc-checking').style.display = 'none';
    if (d.found && d.files && d.files.length) {
      document.getElementById('sw-oc-path').textContent = d.path;
      const listEl = document.getElementById('sw-oc-file-list');
      listEl.innerHTML = '';
      d.files.forEach(f => {
        const row = document.createElement('label');
        row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:0.83em';
        row.innerHTML = '<input type="checkbox" checked value="' + f + '" style="accent-color:var(--cyan)"> <span style="color:var(--cyan)">📄 ' + f + '</span>';
        listEl.appendChild(row);
      });
      document.getElementById('sw-oc-found').style.display = '';
    } else {
      document.getElementById('sw-oc-not-found').style.display = '';
    }
  } catch(e) {
    document.getElementById('sw-oc-checking').style.display = 'none';
    document.getElementById('sw-oc-not-found').style.display = '';
  }
}

async function swMigrateOpenClaw() {
  const checkboxes = document.querySelectorAll('#sw-oc-file-list input[type=checkbox]:checked');
  const files = Array.from(checkboxes).map(c => c.value);
  if (!files.length) { alert('No files selected.'); return; }
  const btn = document.getElementById('sw-oc-import-btn');
  btn.textContent = '⏳ Importing...';
  btn.disabled = true;
  try {
    const r = await authFetch('/api/migrate_openclaw', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({files})});
    const d = await r.json();
    const resultEl = document.getElementById('sw-oc-result');
    resultEl.style.display = '';
    if (d.ok) {
      resultEl.innerHTML = '<span style="color:var(--green)">✅ Imported: ' + (d.imported || []).join(', ') + '</span>';
      if (d.failed && d.failed.length) {
        resultEl.innerHTML += '<br><span style="color:var(--red)">⚠️ Failed: ' + d.failed.join(', ') + '</span>';
      }
    } else {
      resultEl.innerHTML = '<span style="color:var(--red)">Error: ' + (d.error || 'Unknown') + '</span>';
    }
    btn.textContent = '✅ Done';
  } catch(e) {
    document.getElementById('sw-oc-result').innerHTML = '<span style="color:var(--red)">Network error: ' + e.message + '</span>';
    document.getElementById('sw-oc-result').style.display = '';
    btn.textContent = '⬡ Import Selected Files';
    btn.disabled = false;
  }
}

// Startup: check setup first, then check saved token
(async () => {
  const needsSetup = await checkSetup();
  if (needsSetup) return;
  if (token) {
    document.getElementById('login-overlay').style.display = 'none';
    init();
    return;
  }
  // Show login form
  document.getElementById('login-overlay').style.display = 'flex';
})();

document.getElementById('pw-input').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

// Init
async function loadTraceHistory() {
  try {
    const r = await authFetch('/api/traces');
    const d = await r.json();
    (d.traces || []).forEach(t => handleAgentTrace(t));
  } catch(e) { console.error('loadTraceHistory:', e); }
}

async function init() {
  await loadChatHistory();
  await loadLogHistory();
  await loadTraceHistory();
  connectWS();
  await loadTools();
  await loadPlugins();
  loadOllamaStatus();
  renderModelGrid();
  refreshStatus();
  loadFileList();
  // Settings tab initialization
  populateSettingsProviders();
  populatePmoDropdown();
  loadSettingsValues();
  // Restore the last active tab (defaults to 'chat' if none saved)
  const savedTab = localStorage.getItem('gal_activeTab') || 'chat';
  switchTab(savedTab);

  // Smart auto-scroll: pause auto-scroll when user scrolls up, resume at bottom
  document.getElementById('chat-log').addEventListener('scroll', function() {
    const atBottom = (this.scrollHeight - this.scrollTop - this.clientHeight) < 60;
    autoScroll = atBottom;
  });
  document.getElementById('thinking-scroll').addEventListener('scroll', function() {
    const atBottom = (this.scrollHeight - this.scrollTop - this.clientHeight) < 60;
    traceAutoScroll = atBottom;
  });
}


// WebSocket
function connectWS() {
  const wsProt = location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${wsProt}//${location.host}/stream?token=${token}`);
  socket.onmessage = e => {
    const p = JSON.parse(e.data);
    if (p.type === 'stream_chunk') {
      const sb = document.getElementById('stream-bubble');
      sb.style.display = 'block';
      // accumulate raw text on a data attr, render formatted
      sb._rawText = (sb._rawText || '') + p.data;
      sb.innerHTML = formatMsg(sb._rawText);
      if (autoScroll) document.getElementById('chat-log').scrollTop = document.getElementById('chat-log').scrollHeight;
    } else if (p.type === 'log') {
      const sb = document.getElementById('stream-bubble');
      sb.style.display = 'none'; sb.textContent = '';
      addLog(p.data);
    } else if (p.type === 'telemetry') {
      document.getElementById('token-counter').textContent = '↑' + p.data.tin + ' ↓' + p.data.tout + ' tokens';
      document.getElementById('st-uptime').textContent = p.data.uptime;
      document.getElementById('st-tin').textContent = p.data.tin;
      document.getElementById('st-tout').textContent = p.data.tout;
      if (p.data.model) {
        document.getElementById('model-badge').textContent = p.data.model.split('/').pop().substring(0,24);
        document.getElementById('st-model').textContent = p.data.model.split('/').pop().substring(0,12);
        document.getElementById('st-provider').textContent = p.data.provider || '--';
      }
    } else if (p.type === 'ollama_models') {
      renderOllamaModels(p.data);
    } else if (p.type === 'ollama_status') {
      updateOllamaHealth(p.data);
    } else if (p.type === 'thought') {
      if (!httpChatPending) appendBotMsg(p.data);  // skip if HTTP /api/chat will handle it
    } else if (p.type === 'chat_from_telegram') {
      // Telegram messages relayed to web UI
      const tg = p.data || {};
      if (tg.data) appendUserMsg('[Telegram] ' + tg.data);
      if (tg.response) appendBotMsg(tg.response);
    } else if (p.type === 'alert') {
      // optional alert sound
    } else if (p.type === 'agent_trace') {
      handleAgentTrace(p.data);
      // Flash the Thinking tab button pink when it's not the active tab
      const tBtn = document.getElementById('thinking-tab-btn');
      if (tBtn && !tBtn.classList.contains('active')) {
        tBtn.style.color = 'var(--pink)';
        tBtn.style.textShadow = '0 0 8px var(--pink)';
        setTimeout(() => { tBtn.style.color = ''; tBtn.style.textShadow = ''; }, 1800);
      }
    } else if (p.type === 'model_fallback') {
      // Fallback activation toast — show when primary model fails and chain kicks in
      const fb = p.data || {};
      showToast(`⚡ Fallback active: ${fb.fallback || '?'} (${fb.reason || 'error'})`, 'warning', 10000);
    } else if (p.type === 'update_available') {
      const u = p.data || {};
      showToast(`🆕 Update available: v${u.latest} — Run ./update.ps1`, 'info', 30000);
      showUpdateBanner(u);
    }
  };
  socket.onclose = () => setTimeout(connectWS, 3000);
}

// Chat
function fmtTime(ts) {
  if (!ts) return new Date().toLocaleTimeString();
  if (typeof ts === 'string') return new Date(ts).toLocaleTimeString();
  if (typeof ts === 'number') return new Date(ts * 1000).toLocaleTimeString();
  return new Date().toLocaleTimeString();
}

function appendBotMsg(text, ts) {
  const sb = document.getElementById('stream-bubble');
  sb.style.display = 'none'; sb.textContent = ''; sb._rawText = '';
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble">${formatMsg(text)}</div><div class="meta">Byte \u2022 ${fmtTime(ts)}</div>`;
  log.insertBefore(div, sb);
  if (autoScroll) log.scrollTop = log.scrollHeight;
}

function appendBotImage(url) {
  const log = document.getElementById('chat-log');
  const sb = document.getElementById('stream-bubble');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble" style="padding:8px">
    <img src="${url}" style="max-width:100%;max-height:512px;border-radius:8px;display:block;cursor:pointer"
         onclick="window.open('${url}','_blank')" title="Click to open full size" />
    <div style="font-size:0.75em;color:var(--dim);margin-top:4px">🎨 Click image to open full size</div>
  </div><div class="meta">Byte \u2022 ${fmtTime()}</div>`;
  log.insertBefore(div, sb);
  if (autoScroll) log.scrollTop = log.scrollHeight;
}

function appendBotVideo(url) {
  const log = document.getElementById('chat-log');
  const sb = document.getElementById('stream-bubble');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble" style="padding:8px">
    <video src="${url}" controls autoplay muted loop
           style="max-width:100%;max-height:512px;border-radius:8px;display:block"></video>
    <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
      <span style="font-size:0.75em;color:var(--dim)">🎬 Generated video</span>
      <a href="${url}" download style="font-size:0.75em;color:var(--cyan);text-decoration:none">⬇ Download MP4</a>
    </div>
  </div><div class="meta">Byte \u2022 ${fmtTime()}</div>`;
  log.insertBefore(div, sb);
  if (autoScroll) log.scrollTop = log.scrollHeight;
}

async function loadChatHistory() {
  try {
    const r = await authFetch('/api/history?limit=50');
    const d = await r.json();
    const msgs = d.messages || [];
    if (msgs.length > 0) {
      // Clear the default welcome message before restoring history
      document.getElementById('chat-log').innerHTML = '<div id="stream-bubble" style="display:none"></div>';
      // Render oldest→newest; each insertBefore(sb) puts newest at bottom
      msgs.forEach(m => {
        if (m.role === 'user') appendUserMsg(m.content, m.ts);
        else if (m.role === 'assistant') appendBotMsg(m.content, m.ts);
      });
    }
  } catch(e) { console.error('loadChatHistory:', e); }
}

async function loadLogHistory() {
  try {
    const r = await authFetch('/api/logs?limit=200');
    const d = await r.json();
    (d.logs || []).forEach(l => addLog(l));
  } catch(e) { console.error('loadLogHistory:', e); }
}

function appendUserMsg(text, ts) {
  const log = document.getElementById('chat-log');
  const sb = document.getElementById('stream-bubble');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="bubble">${escHtml(text)}</div><div class="meta">You \u2022 ${fmtTime(ts)}</div>`;
  log.insertBefore(div, sb);
  if (autoScroll) log.scrollTop = log.scrollHeight;
}

// ─── File Attachment State ───
let pendingFiles = [];
const IMAGE_TYPES = new Set(['image/jpeg','image/jpg','image/png','image/gif','image/webp','image/bmp','image/tiff','image/heic','image/heif','image/avif','image/svg+xml']);

function isImageFile(f) {
  return IMAGE_TYPES.has(f.type) || /\.(jpg|jpeg|png|gif|webp|bmp|tiff?|heic|heif|avif|svg)$/i.test(f.name);
}

function fileToBase64(f) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result); // data:image/png;base64,...
    reader.onerror = reject;
    reader.readAsDataURL(f);
  });
}

function handleFileAttach(input) {
  for (const f of input.files) {
    if (f.size > 20 * 1024 * 1024) { appendBotMsg('[File too large] ' + f.name + ' exceeds 20 MB limit.'); continue; }
    pendingFiles.push(f);
  }
  input.value = '';
  renderAttachBar();
}

function removeAttachment(idx) {
  pendingFiles.splice(idx, 1);
  renderAttachBar();
}

function renderAttachBar() {
  const bar = document.getElementById('chat-attach-bar');
  if (!pendingFiles.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  bar.style.flexWrap = 'wrap';
  bar.style.gap = '6px';
  bar.style.alignItems = 'center';
  bar.innerHTML = pendingFiles.map((f, i) => {
    const isImg = isImageFile(f);
    const icon = isImg ? '🖼️' : '📄';
    const sizeStr = f.size < 1024 ? f.size + 'B' : f.size < 1024*1024 ? (f.size/1024).toFixed(1) + 'KB' : (f.size/1024/1024).toFixed(1) + 'MB';
    return '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:var(--bg3);border:1px solid ' + (isImg ? 'var(--cyan)' : 'var(--border)') + ';border-radius:8px;font-size:0.78em;color:var(--cyan)">' +
      icon + ' ' + escHtml(f.name) + ' <span style="font-size:0.75em;color:var(--dim)">(' + sizeStr + ')</span>' +
      '<span onclick="removeAttachment(' + i + ')" style="cursor:pointer;color:var(--red);margin-left:4px;font-weight:700" title="Remove">&times;</span></span>';
  }).join('');
}

// ─── Drag & Drop ───
(function initDragDrop() {
  const wrap = document.getElementById('tab-chat');
  if (!wrap) return;
  let dragCounter = 0;
  wrap.addEventListener('dragenter', function(e) { e.preventDefault(); dragCounter++; wrap.style.outline = '2px dashed var(--cyan)'; });
  wrap.addEventListener('dragleave', function(e) { e.preventDefault(); dragCounter--; if (dragCounter <= 0) { dragCounter = 0; wrap.style.outline = ''; } });
  wrap.addEventListener('dragover', function(e) { e.preventDefault(); });
  wrap.addEventListener('drop', function(e) {
    e.preventDefault(); dragCounter = 0; wrap.style.outline = '';
    if (e.dataTransfer.files.length) {
      for (const f of e.dataTransfer.files) {
        if (f.size > 5 * 1024 * 1024) { appendBotMsg('[File too large] ' + f.name + ' exceeds 5 MB limit.'); continue; }
        pendingFiles.push(f);
      }
      renderAttachBar();
    }
  });
})();

async function sendChatMain() {
  const inp = document.getElementById('chat-input-main');
  const msg = inp.value.trim();
  if (!msg && !pendingFiles.length) return;
  const filesToSend = [...pendingFiles];
  pendingFiles = [];
  renderAttachBar();
  inp.value = ''; inp.style.height = '44px';
  const displayMsg = msg + (filesToSend.length ? '\n📎 ' + filesToSend.map(f => f.name).join(', ') : '');
  appendUserMsg(displayMsg);
  document.getElementById('send-btn-main').disabled = true;
  document.getElementById('send-btn-main').textContent = '...';
  const stream = document.getElementById('stream-bubble');
  stream.style.display = 'block'; stream.textContent = '';
  httpChatPending = true;
  try {
    let r;
    if (filesToSend.length) {
      // Separate images from text files
      const imgFiles = filesToSend.filter(f => isImageFile(f));
      const textFiles = filesToSend.filter(f => !isImageFile(f));

      if (imgFiles.length > 0) {
        // Encode images as base64 and send as JSON (vision-capable)
        const images = await Promise.all(imgFiles.map(async f => ({
          name: f.name,
          data: await fileToBase64(f),   // full data URL: data:image/png;base64,...
          mime: f.type || 'image/jpeg'
        })));
        const body = { message: msg, images };
        // Attach any text files as context too
        if (textFiles.length) {
          const fd = new FormData();
          fd.append('message', msg);
          fd.append('images_json', JSON.stringify(images));
          for (const f of textFiles) fd.append('files', f);
          r = await authFetch('/api/chat', {method:'POST', body: fd});
        } else {
          r = await authFetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        }
      } else {
        // Text files only — multipart
        const fd = new FormData();
        fd.append('message', msg);
        for (const f of textFiles) fd.append('files', f);
        r = await authFetch('/api/chat', {method:'POST', body: fd});
      }
    } else {
      r = await authFetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: msg})});
    }
    const d = await r.json();
    stream.style.display = 'none'; stream.textContent = ''; stream._rawText = '';
    appendBotMsg(d.response || d.error || 'No response');
    console.log('[Image Delivery] response keys:', Object.keys(d), 'image_url:', d.image_url || 'NONE');
    if (d.image_url) appendBotImage(d.image_url);
    if (d.video_url) appendBotVideo(d.video_url);
  } catch(err) {
    stream.style.display = 'none';
    appendBotMsg('[ERROR] ' + err.message);
  }
  httpChatPending = false;
  document.getElementById('send-btn-main').disabled = false;
  document.getElementById('send-btn-main').textContent = 'Send ▶';
}

function handleKeyMain(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMain(); }
}
function autoResize(el) {
  el.style.height = '44px';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}
function clearChat() {
  const log = document.getElementById('chat-log');
  log.innerHTML = '<div class="msg bot"><div class="bubble">⬡ Galactic AI online. Context cleared.</div></div><div id="stream-bubble" style="display:none"></div>';
  pendingFiles = [];
  renderAttachBar();
}

// Quick Tool
function quickTool(name) {
  const tool = allToolsData.find(t => t.name === name);
  if (tool) openToolModal(tool);
}

// Tools Tab
async function loadTools() {
  const r = await authFetch('/api/tools');
  const d = await r.json();
  allToolsData = d.tools || [];
  document.getElementById('tool-count-badge').textContent = allToolsData.length;
  document.querySelector('#tab-tools h3').textContent = `🔧 ALL TOOLS (${allToolsData.length} registered)`;
  renderTools(allToolsData);
}

const TOOL_GROUPS = {
  'Browser': ['browser_', 'open_browser', 'browser_search', 'screenshot'],
  'File System': ['read_file','write_file','edit_file','list_directory'],
  'Shell': ['exec_shell','process_start','process_status','process_kill'],
  'Web': ['web_search','web_fetch'],
  'Memory': ['memory_search','memory_imprint'],
  'Vision & Audio': ['analyze_image','text_to_speech'],
  'Task & Schedule': ['schedule_task','list_tasks'],
  'Browser Session': ['browser_save_session','browser_load_session','browser_intercept','browser_clear_intercept','browser_set_proxy'],
  'Browser Debug': ['browser_trace','browser_response_body','browser_get_frames','browser_frame_action','browser_click_coords'],
  'Browser Env': ['browser_set_locale','browser_set_timezone','browser_emulate_media','browser_set_geolocation','browser_set_offline','browser_set_headers'],
  'Other': []
};

function classifyTool(name) {
  for (const [group, prefixes] of Object.entries(TOOL_GROUPS)) {
    if (group === 'Other') continue;
    if (prefixes.some(p => name.startsWith(p) || name === p)) return group;
  }
  return 'Other';
}

function renderTools(tools) {
  const groups = {};
  tools.forEach(t => {
    const g = classifyTool(t.name);
    if (!groups[g]) groups[g] = [];
    groups[g].push(t);
  });
  const container = document.getElementById('tools-list');
  container.innerHTML = '';
  for (const [gname, gtools] of Object.entries(groups)) {
    if (!gtools.length) continue;
    const sec = document.createElement('div');
    sec.className = 'tool-group';
    sec.innerHTML = `<div class="tool-group-label">${gname} (${gtools.length})</div>`;
    gtools.forEach(t => {
      const card = document.createElement('div');
      card.className = 'tool-card';
      card.innerHTML = '<h4>'+t.name+'</h4><p>'+t.description+'</p>'+(t.params.length ? '<div class="params">Params: '+t.params.join(', ')+'</div>' : '');
      card.onclick = () => openToolModal(t);
      sec.appendChild(card);
    });
    container.appendChild(sec);
  }
}

function filterTools(q2) {
  const filtered = allToolsData.filter(t =>
    t.name.includes(q2) || t.description.toLowerCase().includes(q2.toLowerCase())
  );
  renderTools(filtered);
}

// Tool Modal
function openToolModal(tool) {
  currentTool = tool;
  document.getElementById('modal-title').textContent = tool.name;
  document.getElementById('modal-desc').textContent = tool.description;
  document.getElementById('tool-result').style.display = 'none';
  document.getElementById('tool-result').textContent = '';
  const pane = document.getElementById('modal-params');
  pane.innerHTML = '';
  tool.params.forEach(p => {
    pane.innerHTML += `<div class="param-row"><label>${p}</label><input type="text" id="param-${p}" placeholder="${p}"></div>`;
  });
  if (!tool.params.length) pane.innerHTML = '<p style="color:var(--dim);font-size:0.82em">No parameters required.</p>';
  document.getElementById('tool-modal').classList.add('open');
}

function closeToolModal(e) {
  if (e.target.id === 'tool-modal') document.getElementById('tool-modal').classList.remove('open');
}

async function runTool() {
  if (!currentTool) return;
  const args = {};
  currentTool.params.forEach(p => {
    const v = document.getElementById(`param-${p}`)?.value;
    if (v !== undefined && v !== '') {
      try { args[p] = JSON.parse(v); } catch { args[p] = v; }
    }
  });
  const resEl = document.getElementById('tool-result');
  resEl.style.display = 'block';
  resEl.textContent = '⏳ Running...';
  try {
    const r = await authFetch('/api/tool_invoke', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tool: currentTool.name, args})});
    const d = await r.json();
    resEl.textContent = typeof d.result === 'string' ? d.result : JSON.stringify(d.result || d.error, null, 2);
  } catch(err) { resEl.textContent = 'Error: ' + err.message; }
}

// Plugins
async function loadPlugins() {
  const r = await authFetch('/api/plugins');
  const d = await r.json();
  const icons = {SniperPlugin:'🎯', WatchdogPlugin:'👁', ShellPlugin:'💻', BrowserExecutorPro:'🌐', SubAgentPlugin:'🤖'};
  const descs = {SniperPlugin:'Lead prospecting & Reddit hunting', WatchdogPlugin:'Email monitoring & alerting', ShellPlugin:'PowerShell command execution', BrowserExecutorPro:'Full Playwright browser automation (54 tools)', SubAgentPlugin:'Multi-agent task orchestration'};
  const list = document.getElementById('plugins-list');
  list.innerHTML = '';
  (d.plugins || []).forEach(p => {
    const card = document.createElement('div');
    card.className = 'plugin-card';
    const icon = icons[p.class] || '⚙️';
    const desc = descs[p.class] || p.class;
    card.innerHTML = `
      <div class="plugin-icon">${icon}</div>
      <div class="plugin-info">
        <div class="plugin-name">${p.name}</div>
        <div class="plugin-desc">${desc}</div>
        <div class="plugin-class">${p.class}</div>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="togglePlugin('${p.name}', this.checked)">
        <span class="toggle-slider"></span>
      </label>`;
    list.appendChild(card);
  });
}

async function togglePlugin(name, enabled) {
  await authFetch('/api/plugin_toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, enabled})});
}

// Models
const ALL_MODELS = {
  '\ud83d\udd35 Google': [
    {name:'Gemini 3.1 Pro \ud83e\udde0 [LATEST]', id:'gemini-3.1-pro-preview', provider:'google'},
    {name:'Gemini 3 Flash \u26a1', id:'gemini-3-flash-preview', provider:'google'},
    {name:'Gemini 3 Pro \ud83e\udde0', id:'gemini-3-pro-preview', provider:'google'},
    {name:'Gemini 2.5 Flash \ud83c\udfce\ufe0f', id:'gemini-2.5-flash', provider:'google'},
    {name:'Gemini 2.5 Pro \ud83e\uddbe', id:'gemini-2.5-pro', provider:'google'},
    {name:'Gemini 2.0 Flash \u26a1', id:'gemini-2.0-flash', provider:'google'},
  ],
  '\ud83d\udfe3 Anthropic': [
    {name:'Claude Opus 4.6 \ud83d\udc51 [LATEST]', id:'claude-opus-4-6', provider:'anthropic'},
    {name:'Claude Sonnet 4.6 \ud83c\udf1f', id:'claude-sonnet-4-6', provider:'anthropic'},
    {name:'Claude Haiku 4.5 \u26a1 (fast)', id:'claude-haiku-4-5', provider:'anthropic'},
    {name:'Claude Sonnet 4.5 \ud83d\ude80 (legacy)', id:'claude-sonnet-4-5', provider:'anthropic'},
    {name:'Claude Opus 4.5 \ud83c\udfdb\ufe0f (legacy)', id:'claude-opus-4-5', provider:'anthropic'},
  ],
  '\ud83d\udfe2 OpenAI': [
    {name:'GPT-4o \ud83e\udde0 [LATEST]', id:'gpt-4o', provider:'openai'},
    {name:'GPT-4.1 \ud83c\udf1f', id:'gpt-4.1', provider:'openai'},
    {name:'GPT-4o Mini \u26a1', id:'gpt-4o-mini', provider:'openai'},
    {name:'o3 Mini \ud83e\uddee', id:'o3-mini', provider:'openai'},
    {name:'o1 \ud83c\udfdb\ufe0f', id:'o1', provider:'openai'},
  ],
  '\u26a1 xAI': [
    {name:'Grok 4 \ud83e\udde0 [LATEST]', id:'grok-4', provider:'xai'},
    {name:'Grok 4 Fast \u26a1', id:'grok-4-fast', provider:'xai'},
    {name:'Grok 3 \ud83c\udf0c', id:'grok-3', provider:'xai'},
    {name:'Grok 3 Mini \ud83c\udfaf', id:'grok-3-mini', provider:'xai'},
  ],
  '\ud83d\udd2e DeepSeek': [
    {name:'DeepSeek V3 \ud83e\udde0 [LATEST]', id:'deepseek-chat', provider:'deepseek'},
    {name:'DeepSeek R1 (Reasoning) \ud83e\uddee', id:'deepseek-reasoner', provider:'deepseek'},
  ],
  '\ud83c\udfce\ufe0f Groq (Fast)': [
    {name:'Llama 4 Scout 17B \u26a1 [FAST]', id:'llama-4-scout-17b-16e-instruct', provider:'groq'},
    {name:'Llama 4 Maverick 17B \ud83e\uddbe', id:'llama-4-maverick-17b-128e-instruct', provider:'groq'},
    {name:'Llama 3.3 70B \ud83c\udfdb\ufe0f', id:'llama-3.3-70b-versatile', provider:'groq'},
    {name:'DeepSeek R1 70B \ud83e\uddee', id:'deepseek-r1-distill-llama-70b', provider:'groq'},
    {name:'Qwen 3 32B \ud83e\udde0', id:'qwen-3-32b', provider:'groq'},
    {name:'Gemma 3 27B \ud83c\udf0c', id:'gemma2-9b-it', provider:'groq'},
  ],
  '\ud83c\udf0a Mistral': [
    {name:'Mistral Small 3.1 \u26a1', id:'mistral-small-latest', provider:'mistral'},
    {name:'Codestral (Code) \ud83e\uddbe', id:'codestral-latest', provider:'mistral'},
    {name:'Devstral (Agents) \ud83e\udd16', id:'devstral-small-latest', provider:'mistral'},
    {name:'Mistral Large 2 \ud83c\udfdb\ufe0f', id:'mistral-large-latest', provider:'mistral'},
    {name:'Magistral Medium \ud83e\udde0', id:'magistral-medium-latest', provider:'mistral'},
  ],
  '\u26a1 Cerebras': [
    {name:'Llama 3.3 70B \u26a1 [FAST]', id:'llama3.3-70b', provider:'cerebras'},
    {name:'Llama 3.1 8B \ud83c\udfce\ufe0f', id:'llama3.1-8b', provider:'cerebras'},
    {name:'Qwen 3 32B \ud83e\udde0', id:'qwen-3-32b', provider:'cerebras'},
  ],
  '\ud83d\udd00 OpenRouter — Frontier': [
    {name:'Gemini 3.1 Pro Preview \ud83d\udc51', id:'google/gemini-3.1-pro-preview', provider:'openrouter'},
    {name:'Claude Opus 4.6 \ud83d\udc51', id:'anthropic/claude-opus-4.6', provider:'openrouter'},
    {name:'GPT-5.2 \ud83d\udc51', id:'openai/gpt-5.2', provider:'openrouter'},
    {name:'GPT-5.2 Codex \ud83d\udcbb', id:'openai/gpt-5.2-codex', provider:'openrouter'},
    {name:'Grok 4.1 Fast \u26a1', id:'x-ai/grok-4.1-fast', provider:'openrouter'},
    {name:'DeepSeek V3.2 \ud83d\ude80', id:'deepseek/deepseek-v3.2', provider:'openrouter'},
    {name:'Qwen 3.5 Plus (1M ctx) \ud83e\udde0', id:'qwen/qwen3.5-plus-02-15', provider:'openrouter'},
  ],
  '\ud83d\udd00 OpenRouter — Strong': [
    {name:'Gemini 3 Pro Preview \ud83c\udf1f', id:'google/gemini-3-pro-preview', provider:'openrouter'},
    {name:'Gemini 3 Flash Preview \u26a1', id:'google/gemini-3-flash-preview', provider:'openrouter'},
    {name:'Claude Sonnet 4.6 \ud83c\udf1f', id:'anthropic/claude-sonnet-4.6', provider:'openrouter'},
    {name:'Claude Opus 4.5 \ud83e\uddbe', id:'anthropic/claude-opus-4.5', provider:'openrouter'},
    {name:'GPT-5.2 Pro \ud83e\uddbe', id:'openai/gpt-5.2-pro', provider:'openrouter'},
    {name:'GPT-5.1 \ud83e\udde0', id:'openai/gpt-5.1', provider:'openrouter'},
    {name:'GPT-5.1 Codex \ud83d\udcbb', id:'openai/gpt-5.1-codex', provider:'openrouter'},
    {name:'Qwen 3.5 397B \ud83e\udde0', id:'qwen/qwen3.5-397b-a17b', provider:'openrouter'},
    {name:'Qwen 3 Coder Next \ud83d\udcbb', id:'qwen/qwen3-coder-next', provider:'openrouter'},
    {name:'Kimi K2.5 \ud83c\udf19', id:'moonshotai/kimi-k2.5', provider:'openrouter'},
    {name:'DeepSeek V3.2 Speciale \ud83d\ude80', id:'deepseek/deepseek-v3.2-speciale', provider:'openrouter'},
    {name:'GLM-5 \ud83e\uddbe', id:'z-ai/glm-5', provider:'openrouter'},
  ],
  '\ud83d\udd00 OpenRouter — Fast': [
    {name:'Mistral Large 2512 \ud83c\udf1f', id:'mistralai/mistral-large-2512', provider:'openrouter'},
    {name:'Devstral 2512 \ud83d\udcbb', id:'mistralai/devstral-2512', provider:'openrouter'},
    {name:'MiniMax M2.5 \u26a1', id:'minimax/minimax-m2.5', provider:'openrouter'},
    {name:'Sonar Pro Search \ud83d\udd0d', id:'perplexity/sonar-pro-search', provider:'openrouter'},
    {name:'Nemotron Nano 30B \u26a1', id:'nvidia/nemotron-3-nano-30b-a3b', provider:'openrouter'},
    {name:'Step 3.5 Flash \u26a1', id:'stepfun/step-3.5-flash', provider:'openrouter'},
    {name:'GPT-5.2 Chat \ud83d\udcac', id:'openai/gpt-5.2-chat', provider:'openrouter'},
  ],
  '\ud83e\udd17 HuggingFace': [
    {name:'Qwen3 235B \ud83e\udde0', id:'Qwen/Qwen3-235B-A22B', provider:'huggingface'},
    {name:'Llama 4 Scout \u26a1', id:'meta-llama/Llama-4-Scout-17B-16E-Instruct', provider:'huggingface'},
    {name:'DeepSeek V3 \ud83d\ude80', id:'deepseek-ai/DeepSeek-V3-0324', provider:'huggingface'},
  ],
  '\ud83c\udf19 Kimi / Moonshot': [
    {name:'Kimi K2.5 (Thinking) \ud83c\udf19 [via NVIDIA]', id:'moonshotai/kimi-k2.5', provider:'nvidia'},
  ],
  '\ud83e\udde0 ZAI / GLM': [
    {name:'GLM-5 (Thinking) \ud83e\udde0 [via NVIDIA]', id:'z-ai/glm5', provider:'nvidia'},
  ],
  '\ud83c\udfaf MiniMax': [
    {name:'MiniMax M2.1 \ud83c\udfaf [via NVIDIA]', id:'minimaxai/minimax-m2.1', provider:'nvidia'},
  ],
  '\ud83d\uddbc\ufe0f Google Imagen': [
    {name:'Imagen 4 Ultra \u2b50 (best quality)', id:'imagen-4-ultra', provider:'google'},
    {name:'Imagen 4 \ud83d\uddbc\ufe0f (standard)', id:'imagen-4', provider:'google'},
    {name:'Imagen 4 Fast \u26a1\ufe0f (quick)', id:'imagen-4-fast', provider:'google'},
  ],
  '\ud83c\udfa8 FLUX (Image Gen)': [
    {name:'FLUX.1 Schnell \u26a1\ufe0f (fast)', id:'black-forest-labs/flux.1-schnell', provider:'nvidia'},
    {name:'FLUX.1 Dev \ud83c\udfa8 (quality)', id:'black-forest-labs/flux.1-dev', provider:'nvidia'},
  ],
  '\ud83d\udfe9 NVIDIA': [
    {name:'GLM-5 (Thinking) \ud83e\udde0', id:'z-ai/glm5', provider:'nvidia'},
    {name:'Kimi K2.5 (Thinking) \ud83c\udf19', id:'moonshotai/kimi-k2.5', provider:'nvidia'},
    {name:'Qwen 3.5 397B (Thinking) \ud83e\uddbe', id:'qwen/qwen3.5-397b-a17b', provider:'nvidia'},
    {name:'Nemotron Super 49B (Thinking) \ud83d\ude80', id:'nvidia/llama-3.3-nemotron-super-49b-v1.5', provider:'nvidia'},
    {name:'Nemotron Nano 9B (Thinking) \u26a1', id:'nvidia/nvidia-nemotron-nano-9b-v2', provider:'nvidia'},
    {name:'Nemotron 30B (Reasoning) \u269b\ufe0f', id:'nvidia/nemotron-3-nano-30b-a3b', provider:'nvidia'},
    {name:'Nemotron Nano VL \ud83d\udc41\ufe0f', id:'nvidia/nemotron-nano-12b-v2-vl', provider:'nvidia'},
    {name:'Phi-3 Medium (Chat) \ud83d\udcac', id:'microsoft/phi-3-medium-4k-instruct', provider:'nvidia'},
    {name:'StepFun 3.5 Flash \u26a1\ufe0f', id:'stepfun-ai/step-3.5-flash', provider:'nvidia'},
    {name:'MiniMax M2.1 \ud83c\udfaf', id:'minimaxai/minimax-m2.1', provider:'nvidia'},
    {name:'DeepSeek V3.2 (Thinking) \ud83d\ude80', id:'deepseek-ai/deepseek-v3.2', provider:'nvidia'},
    {name:'Llama 405B (Reasoning) \ud83c\udfdb\ufe0f', id:'meta/llama-3.1-405b-instruct', provider:'nvidia'},
    {name:'Phi-3.5 Vision (OCR) \ud83d\udc41\ufe0f', id:'microsoft/phi-3.5-vision-instruct', provider:'nvidia'},
    {name:'Gemma 3 27B (Chat) \ud83c\udf0c', id:'google/gemma-3-27b-it', provider:'nvidia'},
    {name:'Mistral Large 3 (General) \ud83c\udf0a', id:'mistralai/mistral-large-3-675b-instruct-2512', provider:'nvidia'},
    {name:'Qwen 480B Coder \ud83e\uddbe', id:'qwen/qwen3-coder-480b-a35b-instruct', provider:'nvidia'}
  ],
  '\ud83e\udd99 Ollama (Local)': []
};
let currentProvider = '', currentModelId = '';

async function loadOllamaStatus() {
  try {
    const r = await authFetch('/api/ollama_status');
    const d = await r.json();
    updateOllamaHealth(d);
  } catch(e) {}
}

function updateOllamaHealth(d) {
  const dot = document.getElementById('ollama-dot');
  const dot2 = document.getElementById('ollama-health-dot');
  const lbl = document.getElementById('ollama-health');
  const cnt = document.getElementById('ollama-model-count');
  const topLbl = document.getElementById('ollama-label');
  if (d.healthy) {
    [dot, dot2].forEach(el => el && (el.className = 'status-dot'));
    if (lbl) lbl.textContent = '🠂 Ollama Online — ' + d.base_url;
    if (cnt) cnt.textContent = d.model_count + ' models';
    if (topLbl) topLbl.textContent = 'Ollama: ' + d.model_count + ' models';
  } else {
    [dot, dot2].forEach(el => el && (el.className = 'status-dot offline'));
    if (lbl) { lbl.textContent = '🔴 Ollama Offline'; lbl.style.color = 'var(--red)'; }
  }
  if (d.models && d.models.length) renderOllamaModels(d.models);
}

function renderOllamaModels(models) {
  const ollamaKey = Object.keys(ALL_MODELS).find(k => k.includes('Ollama'));
  if (ollamaKey) ALL_MODELS[ollamaKey] = models.map(m => ({name: m + ' \ud83e\udd99', id: m, provider: 'ollama'}));
  renderModelGrid();
}

async function refreshOllama() {
  await loadOllamaStatus();
  const r = await authFetch('/api/ollama_models');
  const d = await r.json();
  if (d.models) renderOllamaModels(d.models);
}

function renderModelGrid() {
  const root = document.getElementById('model-grid-root');
  if (!root) return;
  root.innerHTML = '';
  for (const [provName, models] of Object.entries(ALL_MODELS)) {
    const sec = document.createElement('div');
    sec.className = 'provider-section';
    if (provName.includes('Ollama')) sec.id = 'ollama-section';
    sec.innerHTML = `<div class="provider-label">${provName}</div><div class="model-grid"></div>`;
    const grid = sec.querySelector('.model-grid');
    if (!models.length) {
      grid.innerHTML = `<div style="color:var(--dim);font-size:0.8em;padding:4px">No models discovered</div>`;
    } else {
      models.forEach(m => {
        const btn = document.createElement('button');
        btn.className = 'model-btn' + (m.id === currentModelId ? ' active' : '');
        btn.textContent = m.name;
        btn.onclick = () => switchModel(m.provider, m.id, btn);
        grid.appendChild(btn);
      });
    }
    root.appendChild(sec);
  }
}

let pendingKeySwitch = null;

async function switchModel(provider, modelId, btn) {
  const r = await authFetch('/api/switch_model', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider, model: modelId})});
  const d = await r.json();
  if (d.ok) {
    currentProvider = provider;
    currentModelId = modelId;
    document.querySelectorAll('.model-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    document.getElementById('model-badge').textContent = modelId.split('/').pop().substring(0,24);
    document.getElementById('cfg-provider').value = provider;
    document.getElementById('cfg-model').value = modelId;
    addLog(`[Web] Switched model: ${provider}/${modelId}`);
  } else if (d.needs_key) {
    pendingKeySwitch = {provider, modelId, btn};
    const pName = provider.charAt(0).toUpperCase() + provider.slice(1);
    document.getElementById('key-modal-title').textContent = '\ud83d\udd11 ' + pName + ' API Key Required';
    document.getElementById('key-modal-desc').textContent = 'No API key configured for ' + pName + '. Enter your key to activate ' + modelId + '.';
    document.getElementById('key-modal-label').textContent = pName + ' API Key';
    document.getElementById('key-input').value = '';
    document.getElementById('key-modal').classList.add('open');
    setTimeout(() => document.getElementById('key-input').focus(), 100);
  }
}

async function submitApiKey() {
  const key = document.getElementById('key-input').value.trim();
  if (!key) { document.getElementById('key-input').style.borderColor = 'var(--red)'; return; }
  if (!pendingKeySwitch) return;
  const r = await authFetch('/api/save_key', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider: pendingKeySwitch.provider, api_key: key})});
  const d = await r.json();
  if (d.ok) {
    document.getElementById('key-modal').classList.remove('open');
    addLog('[Web] API key saved for ' + pendingKeySwitch.provider);
    await switchModel(pendingKeySwitch.provider, pendingKeySwitch.modelId, pendingKeySwitch.btn);
    pendingKeySwitch = null;
  } else {
    document.getElementById('key-input').style.borderColor = 'var(--red)';
    addLog('[Error] Failed to save key: ' + (d.error || 'Unknown'));
  }
}

async function applyModelOverride() {
  const provider = document.getElementById('cfg-provider').value;
  const model = document.getElementById('cfg-model').value.trim();
  if (!model) return alert('Enter a model ID');
  await switchModel(provider, model, null);
  renderModelGrid();
}

function updateModelList() {
  const p = document.getElementById('cfg-provider').value;
  const presets = {
    google: 'gemini-2.5-flash', anthropic: 'claude-opus-4-6',
    openai: 'gpt-4o', xai: 'grok-4', groq: 'llama-4-scout-17b-16e-instruct',
    mistral: 'mistral-small-latest', cerebras: 'llama3.3-70b',
    openrouter: 'google/gemini-3.1-pro-preview', huggingface: 'Qwen/Qwen3-235B-A22B',
    kimi: 'kimi-k2.5', zai: 'glm-4-plus', minimax: 'MiniMax-Text-01',
    nvidia: 'deepseek-ai/deepseek-v3.2', ollama: 'qwen3:8b'
  };
  document.getElementById('cfg-model').value = presets[p] || '';
}

async function applyModelConfig() {
  const maxTokens = document.getElementById('cfg-max-tokens').value.trim();
  const contextWindow = document.getElementById('cfg-context-window').value.trim();
  try {
    const r = await authFetch('/api/model_config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max_tokens: maxTokens || 0, context_window: contextWindow || 0})});
    const d = await r.json();
    if (d.ok) {
      addLog('[Web] Token config saved — max_tokens: ' + (d.max_tokens || 'default') + ', context_window: ' + (d.context_window || 'auto'));
    } else {
      addLog('[Web] Token config error: ' + (d.error || 'unknown'));
    }
  } catch(e) { addLog('[Web] Token config error: ' + e.message); }
}

// ── Per-Model Overrides ────────────────────────────────────────────────────────
async function pmoLoad() {
  try {
    const r = await authFetch('/api/model_overrides');
    const d = await r.json();
    pmoRender(d.overrides || {});
  } catch(e) { console.error('pmoLoad:', e); }
}

function pmoRender(overrides) {
  const el = document.getElementById('pmo-list');
  if (!el) return;
  const keys = Object.keys(overrides);
  if (!keys.length) {
    el.innerHTML = '<div style="color:var(--dim);font-size:0.8em;padding:6px 0">No per-model overrides set.</div>';
    return;
  }
  let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82em">';
  html += '<tr style="color:var(--dim);border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px 6px">Model</th><th style="text-align:right;padding:4px 6px">Max Tokens</th><th style="text-align:right;padding:4px 6px">Context Window</th><th style="padding:4px 6px"></th></tr>';
  for (const model of keys) {
    const entry = overrides[model] || {};
    const mt = entry.max_tokens || 0;
    const cw = entry.context_window || 0;
    html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
      <td style="padding:5px 6px;font-family:monospace;color:var(--cyan)">${escHtml(model)}</td>
      <td style="text-align:right;padding:5px 6px;color:${mt?'var(--text)':'var(--dim)'}">${mt || '<span style="color:var(--dim)">global</span>'}</td>
      <td style="text-align:right;padding:5px 6px;color:${cw?'var(--text)':'var(--dim)'}">${cw || '<span style="color:var(--dim)">global</span>'}</td>
      <td style="padding:5px 6px;text-align:right">
        <button onclick="pmoEdit('${escHtml(model)}',${mt},${cw})" style="padding:2px 8px;background:var(--bg3);border:1px solid var(--border);border-radius:4px;color:var(--text);cursor:pointer;font-size:0.85em;margin-right:4px">Edit</button>
        <button onclick="pmoDelete('${escHtml(model)}')" style="padding:2px 8px;background:var(--bg3);border:1px solid #f55;border-radius:4px;color:#f77;cursor:pointer;font-size:0.85em">✕</button>
      </td>
    </tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}

function pmoEdit(model, maxTokens, contextWindow) {
  // Try to select in dropdown first, fall back to custom input
  const sel = document.getElementById('pmo-model');
  const custom = document.getElementById('pmo-model-custom');
  sel.value = model;
  if (sel.value !== model && custom) {
    sel.value = '';
    custom.value = model;
  } else if (custom) {
    custom.value = '';
  }
  document.getElementById('pmo-max-tokens').value = maxTokens || '';
  document.getElementById('pmo-context-window').value = contextWindow || '';
}

async function pmoSave() {
  // Get model from dropdown OR custom input
  let model = document.getElementById('pmo-model').value.trim();
  const custom = document.getElementById('pmo-model-custom');
  if (!model && custom) model = custom.value.trim();
  if (!model) { addLog('[Web] Per-model override: model name required'); return; }
  const maxTokens = parseInt(document.getElementById('pmo-max-tokens').value) || 0;
  const contextWindow = parseInt(document.getElementById('pmo-context-window').value) || 0;
  try {
    const r = await authFetch('/api/model_overrides', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model, max_tokens: maxTokens, context_window: contextWindow})});
    const d = await r.json();
    if (d.ok) {
      addLog(`[Web] Override saved for ${model}: max_tokens=${maxTokens||'global'}, context_window=${contextWindow||'global'}`);
      document.getElementById('pmo-model').value = '';
      if (custom) custom.value = '';
      document.getElementById('pmo-max-tokens').value = '';
      document.getElementById('pmo-context-window').value = '';
      pmoLoad();
    } else {
      addLog('[Web] Override error: ' + (d.error || 'unknown'));
    }
  } catch(e) { addLog('[Web] Override error: ' + e.message); }
}

async function pmoDelete(model) {
  try {
    const r = await authFetch('/api/model_overrides', {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model})});
    const d = await r.json();
    if (d.ok) {
      addLog(`[Web] Override removed for ${model}`);
      pmoLoad();
    }
  } catch(e) { addLog('[Web] Override delete error: ' + e.message); }
}

// Browser
async function browserNav() {
  const url = document.getElementById('browser-url').value.trim();
  if (!url) return;
  setBrowserStatus('Navigating to ' + url + '...');
  const r = await authFetch('/api/browser_cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({command:'navigate', args:{url}})});
  const d = await r.json();
  setBrowserStatus(JSON.stringify(d.result || d.error));
}

async function browserCmd(cmd, extraArgs) {
  setBrowserStatus('Running: ' + cmd + '...');
  try {
    const r = await authFetch('/api/browser_cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({command: cmd, args: extraArgs || {}})});
    const d = await r.json();
    if (cmd === 'screenshot_quick' && d.result?.path) {
      const img = document.getElementById('browser-screenshot');
      img.src = '/api/file?path=' + encodeURIComponent(d.result.path) + '&t=' + Date.now();
      img.style.display = 'block';
    }
    setBrowserStatus(typeof d.result === 'string' ? d.result : JSON.stringify(d.result || d.error, null, 2));
  } catch(e) { setBrowserStatus('Error: ' + e.message); }
}

function setBrowserStatus(msg) {
  document.getElementById('browser-status').textContent = msg;
}

// ── Toast Notification System ──────────────────────────────────────────
function showToast(message, type='info', duration=6000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fadeout');
    setTimeout(() => toast.remove(), 500);
  }, duration);
}

// ── Status ────────────────────────────────────────────────────────────
async function refreshStatus() {
  try {
    const r = await authFetch('/api/status');
    const d = await r.json();

    // Section 1: System Overview
    const el = id => document.getElementById(id);
    el('st-uptime').textContent = d.uptime_formatted || '--';
    el('st-version').textContent = d.version ? 'v'+d.version : '--';
    el('st-personality').textContent = d.personality || '--';
    el('st-tin').textContent = (d.tokens_in||0).toLocaleString();
    el('st-tout').textContent = (d.tokens_out||0).toLocaleString();
    el('st-tools').textContent = d.tool_count || '--';

    // Section 2: Model & AI
    const modelName = (d.model?.model||'--').split('/').pop();
    el('st-model').textContent = modelName.substring(0, 22);
    el('st-provider').textContent = d.model?.provider || '--';
    const mode = d.model?.mode || 'primary';
    el('st-mode').textContent = mode.toUpperCase();
    el('st-mode').style.color = mode === 'primary' ? 'var(--green)' : 'var(--yellow)';
    el('st-max-turns').textContent = d.max_turns || '--';
    el('st-streaming').textContent = d.streaming ? 'ON' : 'OFF';
    el('st-streaming').style.color = d.streaming ? 'var(--green)' : 'var(--dim)';
    el('st-auto-fb').textContent = d.auto_fallback ? 'ON' : 'OFF';
    el('st-auto-fb').style.color = d.auto_fallback ? 'var(--green)' : 'var(--dim)';
    el('st-primary').textContent = d.primary_model || '--';
    el('st-fallback').textContent = d.fallback_model || '--';

    // Update topbar
    currentModelId = d.model?.model || '';
    currentProvider = d.model?.provider || '';
    el('model-badge').textContent = modelName.substring(0, 24) || 'No model';
    if (d.version) el('version-badge').textContent = 'v' + d.version;

    // Fallback Chain
    const fcEl = el('st-fallback-chain');
    if (fcEl && d.fallback_chain) {
      if (d.fallback_chain.length === 0) {
        fcEl.innerHTML = '<div style="color:var(--dim);font-size:0.83em;padding:8px 12px;background:var(--bg3);border-radius:8px">No fallback chain configured (add provider API keys to enable)</div>';
      } else {
        fcEl.innerHTML = d.fallback_chain.map((e,i) => {
          const dot = e.available ? '🟢' : (e.failures > 0 ? '🔴' : '🟡');
          const tier = 'T'+e.tier;
          const fails = e.failures > 0 ? ` <span style="color:var(--red);font-size:0.75em">(${e.failures} fails)</span>` : '';
          return `<div style="display:flex;align-items:center;gap:10px;padding:7px 12px;background:var(--bg3);border-radius:8px;margin-bottom:4px;font-size:0.83em;font-family:var(--mono)"><span>${dot}</span><span style="color:var(--dim);font-size:0.8em;min-width:22px">${tier}</span><span style="color:var(--text)">${e.provider}/<span style="color:var(--cyan)">${(e.model||'auto').split('/').pop()}</span></span>${fails}</div>`;
        }).join('');
      }
    }

    // Section 3: Connections
    const connEl = el('st-connections');
    if (connEl) {
      const bridges = [
        {name:'Telegram', ok:d.telegram?.configured, detail:d.telegram?.admin_chat_id ? 'Chat: '+d.telegram.admin_chat_id : ''},
        {name:'Discord', ok:d.discord?.configured, detail:''},
        {name:'Gmail', ok:d.gmail?.configured, detail:d.gmail?.email && d.gmail.email !== '--' ? d.gmail.email : ''},
        {name:'WhatsApp', ok:d.whatsapp?.configured, detail:''},
        {name:'Ollama', ok:d.ollama?.online !== false, detail:(d.ollama?.model_count||0)+' models'},
      ];
      connEl.innerHTML = bridges.map(b => {
        const icon = b.ok ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--red)">✗</span>';
        const sub = b.detail ? `<div style="font-size:0.72em;color:var(--dim);margin-top:2px">${b.detail}</div>` : '';
        return `<div class="stat-card" style="text-align:left;padding:12px 16px"><div style="display:flex;align-items:center;gap:8px;font-size:0.92em">${icon} <strong>${b.name}</strong></div>${sub}</div>`;
      }).join('');
    }

    // Section 4: Providers
    const provEl = el('st-providers');
    if (provEl && d.providers_configured) {
      const health = d.provider_health || {};
      provEl.innerHTML = Object.entries(d.providers_configured).map(([name, hasKey]) => {
        const h = health[name];
        let dot = hasKey ? '🟢' : '⚫';
        if (h && h.cooldown_until) dot = '🟡';
        if (h && h.failures > 2) dot = '🔴';
        const label = hasKey ? 'Key set' : 'No key';
        const labelColor = hasKey ? 'var(--green)' : 'var(--dim)';
        return `<div class="stat-card" style="text-align:left;padding:12px 16px"><div style="display:flex;align-items:center;gap:8px;font-size:0.88em">${dot} <strong style="text-transform:capitalize">${name}</strong></div><div style="font-size:0.72em;color:${labelColor};margin-top:3px">${label}</div></div>`;
      }).join('');
    }

    // Section 5: Plugins
    const pl = el('status-plugins-list');
    if (pl && d.plugins) {
      pl.innerHTML = '';
      for (const [name, enabled] of Object.entries(d.plugins)) {
        pl.innerHTML += `<div style="display:flex;align-items:center;gap:10px;padding:7px 12px;background:var(--bg3);border-radius:6px;margin-bottom:5px;font-size:0.83em"><span style="color:${enabled?'var(--green)':'var(--red)'}">${enabled?'●':'○'}</span><span>${name}</span><span style="margin-left:auto;color:var(--dim);font-size:0.75em">${enabled?'ACTIVE':'PAUSED'}</span></div>`;
      }
      if (d.scheduled_tasks !== undefined) {
        pl.innerHTML += `<div style="display:flex;align-items:center;gap:10px;padding:7px 12px;background:var(--bg3);border-radius:6px;margin-bottom:5px;font-size:0.83em"><span style="color:var(--cyan)">◆</span><span>Scheduler</span><span style="margin-left:auto;color:var(--dim);font-size:0.75em">${d.scheduled_tasks} tasks</span></div>`;
      }
    }

    // Section 6: Ollama
    el('st-ollama-status').textContent = (d.ollama?.online !== false) ? 'ONLINE' : 'OFFLINE';
    el('st-ollama-status').style.color = (d.ollama?.online !== false) ? 'var(--green)' : 'var(--red)';
    el('st-ollama-models').textContent = d.ollama?.model_count ?? '--';

  } catch(e) { console.error('Status refresh error:', e); }
}

// ── Settings Tab ──────────────────────────────────────────────────────

// Build a flat list of {provider, id, name} from ALL_MODELS for dropdown use
function _flatModels() {
  const flat = [];
  for (const [group, models] of Object.entries(ALL_MODELS)) {
    models.forEach(m => flat.push(m));
  }
  return flat;
}

// Get unique provider list from ALL_MODELS (excluding image-only providers)
function _modelProviders() {
  const IMAGE_ONLY = ['Google Imagen', 'FLUX'];
  const provs = new Map();
  for (const [group, models] of Object.entries(ALL_MODELS)) {
    if (IMAGE_ONLY.some(x => group.includes(x))) continue;
    models.forEach(m => {
      if (!provs.has(m.provider)) provs.set(m.provider, group);
    });
  }
  return provs;
}

function populateSettingsProviders() {
  const provs = _modelProviders();
  ['primary', 'fallback'].forEach(role => {
    const sel = document.getElementById(`set-${role}-provider`);
    sel.innerHTML = '';
    for (const [prov, label] of provs) {
      const opt = document.createElement('option');
      opt.value = prov;
      opt.textContent = prov.charAt(0).toUpperCase() + prov.slice(1);
      sel.appendChild(opt);
    }
  });
}

function updateSettingsModelList(role) {
  const provSel = document.getElementById(`set-${role}-provider`);
  const modSel = document.getElementById(`set-${role}-model`);
  const prov = provSel.value;
  modSel.innerHTML = '';
  const flat = _flatModels();
  const provModels = flat.filter(m => m.provider === prov);
  provModels.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.name.replace(/\[LATEST\]/g, '').trim();
    modSel.appendChild(opt);
  });
  // If Ollama, add discovered models
  if (prov === 'ollama') {
    const ollamaKey = Object.keys(ALL_MODELS).find(k => k.includes('Ollama'));
    if (ollamaKey) {
      ALL_MODELS[ollamaKey].forEach(m => {
        if (!provModels.find(x => x.id === m.id)) {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name;
          modSel.appendChild(opt);
        }
      });
    }
  }
}

function populatePmoDropdown() {
  const sel = document.getElementById('pmo-model');
  if (!sel || sel.tagName !== 'SELECT') return;
  const flat = _flatModels();
  sel.innerHTML = '<option value="">-- select model --</option>';
  const IMAGE_ONLY = ['Google Imagen', 'FLUX'];
  for (const [group, models] of Object.entries(ALL_MODELS)) {
    if (IMAGE_ONLY.some(x => group.includes(x))) continue;
    if (!models.length) continue;
    const optGroup = document.createElement('optgroup');
    optGroup.label = group;
    models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.name.replace(/\[LATEST\]/g, '').trim();
      optGroup.appendChild(opt);
    });
    sel.appendChild(optGroup);
  }
}

async function loadSettingsValues() {
  try {
    const r = await authFetch('/api/status');
    const d = await r.json();
    // Model settings
    const prim = (d.primary_model || '/').split('/');
    const fb = (d.fallback_model || '/').split('/');
    const primProv = prim.length > 1 ? prim[0] : '';
    const primModel = prim.length > 1 ? prim.slice(1).join('/') : prim[0];
    const fbProv = fb.length > 1 ? fb[0] : '';
    const fbModel = fb.length > 1 ? fb.slice(1).join('/') : fb[0];

    const setProv = (role, val) => {
      const sel = document.getElementById(`set-${role}-provider`);
      if (sel) { sel.value = val; updateSettingsModelList(role); }
    };
    const setModel = (role, val) => {
      const sel = document.getElementById(`set-${role}-model`);
      if (sel) sel.value = val;
    };
    setProv('primary', primProv); setModel('primary', primModel);
    setProv('fallback', fbProv); setModel('fallback', fbModel);

    // Toggles
    const el = id => document.getElementById(id);
    if (el('set-auto-fallback')) el('set-auto-fallback').checked = d.auto_fallback !== false;
    if (el('set-smart-routing')) el('set-smart-routing').checked = !!d.smart_routing;
    if (el('set-streaming')) el('set-streaming').checked = d.streaming !== false;

    // Voice
    if (d.voice && el('set-voice')) el('set-voice').value = d.voice;
    if (d.voice && el('quick-voice-select')) el('quick-voice-select').value = d.voice;

    // System
    if (d.update_check_interval !== undefined && el('set-update-interval'))
      el('set-update-interval').value = String(d.update_check_interval);
    if (d.speak_timeout && el('set-speak-timeout')) el('set-speak-timeout').value = d.speak_timeout;
    if (d.max_turns && el('set-max-turns')) el('set-max-turns').value = d.max_turns;
  } catch(e) { console.error('loadSettingsValues:', e); }
}

async function saveModelSettings() {
  const primProv = document.getElementById('set-primary-provider').value;
  const primModel = document.getElementById('set-primary-model').value;
  const fbProv = document.getElementById('set-fallback-provider').value;
  const fbModel = document.getElementById('set-fallback-model').value;
  if (!primProv || !primModel) { showToast('Select a primary model', 'error', 3000); return; }
  if (!fbProv || !fbModel) { showToast('Select a fallback model', 'error', 3000); return; }
  try {
    const r = await authFetch('/api/settings/models', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        primary_provider: primProv, primary_model: primModel,
        fallback_provider: fbProv, fallback_model: fbModel,
        auto_fallback: document.getElementById('set-auto-fallback').checked,
        smart_routing: document.getElementById('set-smart-routing').checked,
        streaming: document.getElementById('set-streaming').checked,
      })
    });
    const d = await r.json();
    if (d.ok) {
      showToast('Model settings saved!', 'success', 3000);
      refreshStatus();
    } else {
      showToast(d.error || 'Failed to save', 'error', 4000);
    }
  } catch(e) { showToast('Error: ' + e.message, 'error', 4000); }
}

async function saveVoiceSettings() {
  const voice = document.getElementById('set-voice').value;
  try {
    const r = await authFetch('/api/settings/voice', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({voice})
    });
    const d = await r.json();
    if (d.ok) {
      showToast(`Voice set to ${voice}`, 'success', 3000);
      // Sync the Quick Tools voice selector
      const qs = document.getElementById('quick-voice-select');
      if (qs) qs.value = voice;
    }
  } catch(e) { showToast('Error: ' + e.message, 'error', 4000); }
}

async function saveQuickVoice(voice) {
  try {
    await authFetch('/api/settings/voice', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({voice})
    });
    showToast(`Voice changed to ${voice}`, 'success', 3000);
    // Sync Settings tab voice selector
    const sv = document.getElementById('set-voice');
    if (sv) sv.value = voice;
  } catch(e) {}
}

function testVoice() {
  const voice = document.getElementById('set-voice').value;
  const msg = 'Hello! I am ' + voice + ', your AI assistant voice.';
  showToast('Generating voice preview...', 'info', 3000);
  authFetch('/api/tts', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({text: msg, voice: voice})
  }).then(r => {
    if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'TTS failed'); });
    return r.blob();
  }).then(blob => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    audio.play().then(() => {
      showToast('Playing voice preview', 'success', 3000);
    }).catch(e => showToast('Browser blocked audio playback. Click anywhere first.', 'error', 4000));
  }).catch(e => showToast('Error: ' + e.message, 'error', 4000));
}

// ── Voice Input (Microphone) ──────────────────────────────────────────
let _voiceRecorder = null;
let _voiceChunks = [];
let _voiceRecording = false;

function toggleVoiceInput() {
  if (_voiceRecording) { stopVoiceInput(); return; }
  startVoiceInput();
}

async function startVoiceInput() {
  const btn = document.getElementById('voice-btn');
  // MediaRecorder requires a secure context (HTTPS or localhost).
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast('Mic unavailable: requires secure context (HTTPS or localhost).', 'error', 4000);
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    _voiceChunks = [];
    _voiceRecorder = new MediaRecorder(stream, {mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4'});
    _voiceRecorder.ondataavailable = e => { if (e.data.size > 0) _voiceChunks.push(e.data); };
    _voiceRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      if (_voiceChunks.length > 0) sendVoiceForTranscription();
    };
    _voiceRecorder.start();
    _voiceRecording = true;
    btn.classList.add('recording');
    btn.style.background = 'var(--red)';
    btn.style.color = '#fff';
    btn.style.borderColor = 'var(--red)';
    btn.title = 'Click to stop recording';
    showToast('Recording... click mic to stop', 'info', 10000);
  } catch(e) {
    showToast('Microphone access denied: ' + e.message, 'error', 4000);
  }
}

function stopVoiceInput() {
  const btn = document.getElementById('voice-btn');
  if (_voiceRecorder && _voiceRecorder.state !== 'inactive') _voiceRecorder.stop();
  _voiceRecording = false;
  btn.classList.remove('recording');
  btn.style.background = 'var(--bg3)';
  btn.style.color = 'var(--dim)';
  btn.style.borderColor = 'var(--border)';
  btn.title = 'Voice input (click to record)';
}

async function sendVoiceForTranscription() {
  const btn = document.getElementById('voice-btn');
  btn.textContent = '...';
  showToast('Transcribing...', 'info', 5000);
  try {
    const blob = new Blob(_voiceChunks, {type: _voiceChunks[0]?.type || 'audio/webm'});
    const form = new FormData();
    form.append('audio', blob, 'recording.webm');
    const r = await authFetch('/api/stt', {method: 'POST', body: form});
    const d = await r.json();
    if (d.text) {
      const inp = document.getElementById('chat-input-main');
      inp.value = inp.value ? inp.value + ' ' + d.text : d.text;
      inp.focus();
      autoResize(inp);
      showToast('Transcribed!', 'success', 2000);
    } else {
      showToast(d.error || 'Transcription failed', 'error', 4000);
    }
  } catch(e) {
    showToast('STT error: ' + e.message, 'error', 4000);
  }
  btn.textContent = '\uD83C\uDFA4';
}

async function saveSystemSettings() {
  try {
    const r = await authFetch('/api/settings/system', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        update_check_interval: parseInt(document.getElementById('set-update-interval').value) || 21600,
        speak_timeout: parseInt(document.getElementById('set-speak-timeout').value) || 600,
        max_turns: parseInt(document.getElementById('set-max-turns').value) || 50,
      })
    });
    const d = await r.json();
    if (d.ok) showToast('System settings saved!', 'success', 3000);
    else showToast(d.error || 'Failed to save', 'error', 4000);
  } catch(e) { showToast('Error: ' + e.message, 'error', 4000); }
}

// ── Update Banner ─────────────────────────────────────────────────────
function showUpdateBanner(info) {
  if (document.getElementById('update-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'update-banner';
  banner.style.cssText = 'padding:10px 20px;background:rgba(0,160,255,0.12);border-bottom:1px solid rgba(0,200,255,0.3);display:flex;align-items:center;gap:12px;font-size:0.85em;flex-shrink:0';
  banner.innerHTML = `<span style="font-size:1.2em">🆕</span><span><strong>Galactic AI v${info.latest}</strong> is available <span style="color:var(--dim)">(you have v${info.current})</span></span><code style="padding:3px 8px;background:var(--bg);border-radius:5px;font-size:0.85em">./update.ps1</code><button onclick="this.parentElement.remove()" style="margin-left:auto;background:none;border:1px solid var(--border);border-radius:5px;color:var(--text);padding:3px 10px;cursor:pointer;font-size:0.85em">Dismiss</button>`;
  const topbar = document.getElementById('topbar');
  if (topbar) topbar.after(banner);
}

// Memory
async function loadFileList() {
  try {
    const r = await authFetch('/api/files');
    const d = await r.json();
    const sel = document.getElementById('mem-file-select');
    sel.innerHTML = '<option value="">-- select file --</option>';
    (d.files || []).forEach(f => {
      // f may be a string OR an object {name, size}
      const fname = (typeof f === 'string') ? f : (f.name || f);
      const label = (typeof f === 'object' && f.size !== undefined) ? fname + ' (' + f.size + 'b)' : fname;
      const opt = document.createElement('option');
      opt.value = fname;
      opt.textContent = label;
      sel.appendChild(opt);
    });
  } catch(e) { console.error('loadFileList error:', e); }
}
async function loadMemFile(name) {
  if (!name) return;
  try {
    const r = await authFetch('/api/file?name=' + encodeURIComponent(name));
    const d = await r.json();
    if (d.error) { document.getElementById('mem-editor').value = '// Error: ' + d.error; return; }
    document.getElementById('mem-editor').value = d.content || '';
    addLog('[Web] Loaded: ' + name);
  } catch(e) { document.getElementById('mem-editor').value = '// Load error: ' + e.message; }
}
async function saveMemFile() {
  const name = document.getElementById('mem-file-select').value;
  const content = document.getElementById('mem-editor').value;
  if (!name) return alert('Select a file first');
  try {
    await authFetch('/api/file', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, content})});
    addLog('[Web] Saved: ' + name);
  } catch(e) { alert('Save failed: ' + e.message); }
}

// Logs — newest at top
function addLog(msg) {
  allLogs.push(msg);
  const filterVal = document.getElementById('log-filter').value || '';
  if (!filterVal || msg.toLowerCase().includes(filterVal.toLowerCase())) {
    const el = document.getElementById('logs-scroll');
    const div = document.createElement('div');
    div.className = 'log-line' + (msg.includes('ERROR')||msg.includes('Error') ? ' err' : msg.includes('✅')||msg.includes('ONLINE') ? ' ok' : msg.includes('⚠️')||msg.includes('WARN') ? ' warn' : '');
    div.textContent = msg;
    el.append(div);
    if (autoScroll) el.scrollTop = el.scrollHeight;
    // Trim DOM for performance — keep max 500 visible entries (remove oldest)
    while (el.children.length > 500) el.removeChild(el.firstChild);
  }
}

function filterLogs(q2) {
  const el = document.getElementById('logs-scroll');
  el.innerHTML = '';
  const filtered = allLogs.filter(l => !q2 || l.toLowerCase().includes(q2.toLowerCase()));
  // Render oldest→newest (chronological), limit to 500
  filtered.slice(-500).forEach(l => {
    const div = document.createElement('div');
    div.className = 'log-line';
    div.textContent = l;
    el.appendChild(div);
  });
}

function clearLogs() { allLogs = []; document.getElementById('logs-scroll').innerHTML = ''; }

function toggleAutoScroll() {
  autoScroll = !autoScroll;
  document.getElementById('log-auto-scroll-btn').textContent = 'Auto-scroll: ' + (autoScroll ? 'ON' : 'OFF');
}

// Tabs
function switchTab(name) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
  const pane = document.getElementById('tab-' + name);
  if (pane) pane.classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => { if (b.textContent.toLowerCase().includes(name)) b.classList.add('active'); });
  document.querySelectorAll('.sidebar-item').forEach(s => { if (s.textContent.toLowerCase().includes(name)) s.classList.add('active'); });
  if (name === 'status') refreshStatus();
  if (name === 'models') { loadOllamaStatus(); pmoLoad(); }
  if (name === 'plugins') loadPlugins();
  if (name === 'thinking') {
    const tBtn = document.getElementById('thinking-tab-btn');
    if (tBtn) { tBtn.style.color = ''; tBtn.style.textShadow = ''; }
  }
  // Scroll to bottom when switching to content tabs (newest-last layout)
  if (name === 'chat') {
    requestAnimationFrame(() => {
      const el = document.getElementById('chat-log');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
  if (name === 'logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('logs-scroll');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
  if (name === 'thinking') {
    requestAnimationFrame(() => {
      const el = document.getElementById('thinking-scroll');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
  try { localStorage.setItem('gal_activeTab', name); } catch(e) {}
}

// Utility
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatMsg(text) {
  // Render markdown-ish formatting for chat bubbles
  let s = String(text);
  // Fenced code blocks (```lang\n...\n``` or ```\n...\n```)
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, function(_, lang, code) {
    const label = lang ? '<span style="font-size:0.7em;color:var(--dim);display:block;margin-bottom:4px">' + escHtml(lang) + '</span>' : '';
    return '<pre style="background:#0d0d14;border:1px solid var(--border);border-radius:7px;padding:10px 12px;overflow-x:auto;margin:6px 0;font-size:0.82em;line-height:1.6">' + label + escHtml(code.trimEnd()) + '</pre>';
  });
  // Inline code `...`
  s = s.replace(/`([^`\n]+)`/g, '<code style="background:rgba(255,255,255,0.07);border-radius:4px;padding:1px 5px;font-size:0.88em">$1</code>');
  // Bold **text**
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic *text* (single star, not double)
  s = s.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
  // Headers ### ## #
  s = s.replace(/^###\s+(.+)$/gm, '<div style="font-weight:700;font-size:0.95em;color:var(--cyan);margin:8px 0 2px">$1</div>');
  s = s.replace(/^##\s+(.+)$/gm, '<div style="font-weight:700;font-size:1em;color:var(--cyan);margin:10px 0 3px">$1</div>');
  s = s.replace(/^#\s+(.+)$/gm, '<div style="font-weight:800;font-size:1.05em;color:var(--cyan);margin:12px 0 4px">$1</div>');
  // Bullet lists - line
  s = s.replace(/^[ \t]*[-*]\s+(.+)$/gm, '<div style="padding-left:14px;margin:1px 0">• $1</div>');
  // Numbered lists
  s = s.replace(/^[ \t]*(\d+)\.\s+(.+)$/gm, '<div style="padding-left:14px;margin:1px 0">$1. $2</div>');
  // Newlines to <br> (after block-level replacements)
  s = s.replace(/\n/g, '<br>');
  return s;
}
function handleKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMain(); } }
function sendChat() { sendChatMain(); }

// ── THINKING TAB ────────────────────────────────────────────────────────────
let traceAutoScroll = true;
let traceSessions = {};   // session_id -> { el, body, turnEls, maxTurn }
let traceAllEntries = []; // flat list for filter replay

function handleAgentTrace(data) {
  const sid   = data.session_id || 'anon';
  const turn  = data.turn  || 0;
  const phase = data.phase || 'unknown';
  const scroll = document.getElementById('thinking-scroll');
  if (!scroll) return;

  // ── SESSION START ──
  if (phase === 'session_start') {
    const sEl = document.createElement('div');
    sEl.className = 'trace-session';
    sEl.dataset.sid = sid;
    const query = (data.query || '').substring(0, 140);
    sEl.innerHTML =
      '<div class="trace-session-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">' +
        '<span class="trace-sid">#' + escHtml(sid) + '</span>' +
        '<span class="trace-query">' + escHtml(query) + '</span>' +
        '<span class="trace-toggle">&#9660;</span>' +
      '</div>' +
      '<div class="trace-session-body"></div>';
    scroll.append(sEl);
    traceSessions[sid] = { el: sEl, body: sEl.querySelector('.trace-session-body'), turnEls: {}, maxTurn: 0 };
    if (traceAutoScroll) scroll.scrollTop = scroll.scrollHeight;
    return;
  }

  // ── Ensure session container exists (joined mid-session) ──
  if (!traceSessions[sid]) {
    const sEl = document.createElement('div');
    sEl.className = 'trace-session';
    sEl.dataset.sid = sid;
    sEl.innerHTML =
      '<div class="trace-session-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">' +
        '<span class="trace-sid">#' + escHtml(sid) + '</span>' +
        '<span class="trace-query">(mid-session)</span>' +
        '<span class="trace-toggle">&#9660;</span>' +
      '</div>' +
      '<div class="trace-session-body"></div>';
    scroll.append(sEl);
    traceSessions[sid] = { el: sEl, body: sEl.querySelector('.trace-session-body'), turnEls: {}, maxTurn: 0 };
  }
  const sess = traceSessions[sid];

  // ── TURN START ──
  if (phase === 'turn_start') {
    const tEl = document.createElement('div');
    tEl.className = 'trace-turn';
    tEl.dataset.turn = turn;
    tEl.innerHTML =
      '<div class="trace-turn-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">TURN ' + turn + ' &#9660;</div>' +
      '<div class="trace-turn-entries"></div>';
    sess.body.append(tEl);
    sess.turnEls[turn] = tEl;
    if (turn > sess.maxTurn) {
      sess.maxTurn = turn;
      const ctr = document.getElementById('thinking-turn-counter');
      if (ctr) ctr.textContent = 'Turns: ' + turn;
    }
    if (traceAutoScroll) scroll.scrollTop = scroll.scrollHeight;
    return;
  }

  // ── Get or create turn container ──
  let turnEl = sess.turnEls[turn];
  if (!turnEl) {
    turnEl = document.createElement('div');
    turnEl.className = 'trace-turn';
    turnEl.dataset.turn = turn;
    turnEl.innerHTML =
      '<div class="trace-turn-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">TURN ' + turn + ' &#9660;</div>' +
      '<div class="trace-turn-entries"></div>';
    sess.body.append(turnEl);
    sess.turnEls[turn] = turnEl;
  }
  const entries = turnEl.querySelector('.trace-turn-entries');

  // ── Build entry ──
  const entry = document.createElement('div');
  let cls = 'trace-entry phase-' + phase;
  if (phase === 'tool_result' && data.success === false) cls += ' error';
  entry.className = cls;

  const ts = data.ts ? new Date(data.ts * 1000).toLocaleTimeString() : '';

  let label = phase.replace(/_/g, ' ').toUpperCase();
  let html  = '';

  if (phase === 'thinking') {
    html = escHtml(data.content || '');
  } else if (phase === 'llm_response') {
    const txt = (data.content || '').substring(0, 1500);
    html = escHtml(txt) + ((data.content || '').length > 1500 ? '\n...(truncated)' : '');
  } else if (phase === 'tool_call') {
    label = 'TOOL CALL';
    const argsStr = (typeof data.args === 'object') ? JSON.stringify(data.args, null, 2) : String(data.args || '');
    html = '<span class="trace-tool-badge">' + escHtml(data.tool || '') + '</span>\n' + escHtml(argsStr);
  } else if (phase === 'tool_result') {
    label = data.success ? 'TOOL RESULT' : 'TOOL ERROR';
    html = '<span class="trace-tool-badge">' + escHtml(data.tool || '') + '</span>\n' + escHtml(data.result || '');
  } else if (phase === 'final_answer') {
    label = 'FINAL ANSWER';
    html = escHtml((data.content || '').substring(0, 2000));
  } else if (phase === 'duplicate_blocked') {
    label = 'DUPLICATE BLOCKED';
    html = 'Blocked repeated call to <span class="trace-tool-badge">' + escHtml(data.tool || '') + '</span>';
  } else if (phase === 'tool_not_found') {
    label = 'TOOL NOT FOUND';
    html = 'Unknown tool: <span class="trace-tool-badge">' + escHtml(data.tool || '') + '</span>';
  } else if (phase === 'session_abort') {
    label = 'ABORTED';
    html = escHtml(data.reason || 'max turns exceeded');
  } else {
    html = escHtml(JSON.stringify(data).substring(0, 500));
  }

  entry.innerHTML =
    '<span class="trace-ts">' + ts + '</span>' +
    '<div class="trace-label">' + label + '</div>' +
    '<div class="trace-content">' + html + '</div>';

  // Add expand toggle for long content
  const contentEl = entry.querySelector('.trace-content');
  if (contentEl && (html.length > 300 || html.includes('\n'))) {
    const btn = document.createElement('span');
    btn.className = 'trace-expand-btn';
    btn.textContent = contentEl.scrollHeight > 180 ? 'show more' : '';
    btn.onclick = function() {
      contentEl.classList.toggle('expanded');
      this.textContent = contentEl.classList.contains('expanded') ? 'show less' : 'show more';
    };
    entry.appendChild(btn);
    // Set button text after render
    setTimeout(() => { if (contentEl.scrollHeight > 180) btn.textContent = 'show more'; else btn.remove(); }, 50);
  }

  traceAllEntries.push({ el: entry, phase, sid, turn });
  entries.appendChild(entry);
  applyTraceEntryFilter(entry);

  if (traceAutoScroll) scroll.scrollTop = scroll.scrollHeight;
}

function applyTraceEntryFilter(entry) {
  const fText  = (document.getElementById('thinking-filter').value || '').toLowerCase();
  const fPhase = document.getElementById('thinking-phase-filter').value;
  let show = true;
  if (fPhase && !entry.classList.contains('phase-' + fPhase)) show = false;
  if (fText && !entry.textContent.toLowerCase().includes(fText)) show = false;
  entry.style.display = show ? '' : 'none';
}

function filterTraces() {
  traceAllEntries.forEach(t => applyTraceEntryFilter(t.el));
}

function clearTraces() {
  traceAllEntries = [];
  traceSessions   = {};
  document.getElementById('thinking-scroll').innerHTML = '';
  document.getElementById('thinking-turn-counter').textContent = 'Turns: 0';
}

function toggleThinkingAutoScroll() {
  traceAutoScroll = !traceAutoScroll;
  document.getElementById('thinking-auto-scroll-btn').textContent = 'Auto-scroll: ' + (traceAutoScroll ? 'ON' : 'OFF');
}

// ─── POWER CONTROLS ─────────────────────────────────────────────────────────
function confirmRestart() {
  if (!confirm('⚠️ Restart Galactic AI?\\n\\nAll active sessions will be interrupted. The system will reload and reconnect automatically.')) return;
  showToast('🔄 Restarting Galactic AI...', 'info', 8000);
  authFetch('/api/restart', { method: 'POST' }).catch(() => {});
  // Poll for reconnection after a few seconds
  setTimeout(() => {
    const poll = setInterval(async () => {
      try {
        const r = await fetch('/api/status');
        if (r.ok) { clearInterval(poll); location.reload(); }
      } catch(_) {}
    }, 2000);
    // Stop polling after 60s
    setTimeout(() => clearInterval(poll), 60000);
  }, 3000);
}

function confirmShutdown() {
  if (!confirm('⚠️ Shutdown Galactic AI?\\n\\nThis will stop the entire process. You will need to manually restart the application.')) return;
  showToast('⏻ Shutting down Galactic AI...', 'warning', 10000);
  authFetch('/api/shutdown', { method: 'POST' }).catch(() => {});
}

// ─── DISPLAY SETTINGS ───────────────────────────────────────────────────────
const DS_FS_KEY   = 'gal_fontSize';
const DS_CRT_KEY  = 'gal_crt';
const DS_GLOW_KEY = 'gal_glow';
const GLOW_LABELS = ['Off', 'Medium', 'Max'];

function applyFontSize(px) {
  px = Math.min(26, Math.max(13, parseInt(px)));
  document.documentElement.style.setProperty('--fs', px + 'px');
  const lbl = document.getElementById('fs-label');
  if (lbl) lbl.textContent = px + 'px';
  const sl = document.getElementById('fs-slider');
  if (sl) sl.value = px;
  try { localStorage.setItem(DS_FS_KEY, px); } catch(e) {}
}

function applyCRT(on) {
  document.body.classList.toggle('crt', !!on);
  const tog = document.getElementById('crt-toggle');
  if (tog) tog.checked = !!on;
  try { localStorage.setItem(DS_CRT_KEY, on ? '1' : '0'); } catch(e) {}
}

function applyGlow(level) {
  level = parseInt(level);
  document.body.classList.remove('glow-off', 'glow-max');
  if (level === 0) document.body.classList.add('glow-off');
  else if (level === 2) document.body.classList.add('glow-max');
  const lbl = document.getElementById('glow-label');
  if (lbl) lbl.textContent = GLOW_LABELS[level] || 'Medium';
  const sl = document.getElementById('glow-slider');
  if (sl) sl.value = level;
  try { localStorage.setItem(DS_GLOW_KEY, level); } catch(e) {}
}

function openDisplaySettings() {
  // Sync controls to current values before showing
  try {
    const fs   = parseInt(localStorage.getItem(DS_FS_KEY)) || 17;
    const crt  = localStorage.getItem(DS_CRT_KEY) === '1';
    const glow = parseInt(localStorage.getItem(DS_GLOW_KEY) ?? '1');
    applyFontSize(fs);
    applyCRT(crt);
    applyGlow(glow);
  } catch(e) {}
  document.getElementById('display-modal').style.display = 'flex';
}

function closeDisplaySettings() {
  document.getElementById('display-modal').style.display = 'none';
}

function resetDisplaySettings() {
  applyFontSize(17);
  applyCRT(false);
  applyGlow(1);
}

// Apply saved display settings on page load
(function() {
  try {
    const fs   = localStorage.getItem(DS_FS_KEY);
    const crt  = localStorage.getItem(DS_CRT_KEY);
    const glow = localStorage.getItem(DS_GLOW_KEY);
    if (fs)   applyFontSize(parseInt(fs));
    if (crt)  applyCRT(crt === '1');
    if (glow != null) applyGlow(parseInt(glow));
  } catch(e) {}
})();

// Close display modal on backdrop click
document.getElementById('display-modal').addEventListener('click', function(e) {
  if (e.target === this) closeDisplaySettings();
});

// Real-time data: refresh current tab's data when window regains focus
function refreshCurrentTab() {
  const active = document.querySelector('.tab-pane.active');
  if (!active) return;
  const id = active.id;
  if (id === 'tab-status') refreshStatus();
  else if (id === 'tab-models') { loadOllamaStatus(); pmoLoad(); }
  else if (id === 'tab-plugins') loadPlugins();
  else if (id === 'tab-ollama') loadOllamaStatus();
  else if (id === 'tab-logs') loadLogHistory();
  else if (id === 'tab-memory') loadFileList();
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshCurrentTab();
});

// Periodic refresh: keep Status and token counter current every 15s
setInterval(() => {
  if (!document.hidden) refreshCurrentTab();
}, 15000);
</script>
</body>
</html>"""
        return web.Response(text=html, content_type='text/html')

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

    async def handle_serve_video(self, request):
        """GET /api/video/{filename} — serve a generated video."""
        filename = request.match_info.get('filename', '')
        filename = os.path.basename(filename)
        images_dir = self.core.config.get('paths', {}).get('images', './images')
        video_dir = os.path.join(images_dir, 'video')
        path = os.path.join(video_dir, filename)
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
        logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
        path = os.path.join(logs_dir, filename)
        if not os.path.exists(path):
            return web.Response(status=404, text='Image not found')
        mime = mimetypes.guess_type(filename)[0] or 'image/jpeg'
        with open(path, 'rb') as f:
            data = f.read()
        return web.Response(body=data, content_type=mime)

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
        with open(candidate, 'rb') as f:
            data = f.read()
        return web.Response(body=data, content_type=mime)

    async def handle_chat(self, request):
        """POST /api/chat — send message to the AI and get response.

        Accepts:
          - JSON body: {message, images?: [{name, data, mime}]}
          - multipart/form-data: message field + files parts (text) + optional images_json field
        Images are sent as base64 data URLs and forwarded to the LLM as vision content.
        """
        import base64 as _b64, json as _json
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
                        raw = await part.read(20 * 1024 * 1024)
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

            # Log cleanly
            parts_log = []
            if file_context:
                parts_log.append(f"+{file_context.count('[Attached file:')} file(s)")
            if attached_images:
                parts_log.append(f"+{len(attached_images)} image(s)")
            suffix = f" [{', '.join(parts_log)}]" if parts_log else ""
            await self.core.log(f"[Web] User: {user_msg or '(no text)'}{suffix}", priority=2)

            # Forward to gateway — pass images to speak() if present
            if attached_images:
                response = await self.core.gateway.speak(
                    full_msg or f"[User attached {len(attached_images)} image(s). Please describe and analyse them.]",
                    images=attached_images
                )
            else:
                response = await self.core.gateway.speak(full_msg)

            await self.core.log(f"[Core] Byte: {response}", priority=2)

            # Deliver any generated image inline — fix path for new images/ subfolders
            resp_data = {'response': response}
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

            return web.json_response(resp_data)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

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
            plugin_statuses[p.name] = getattr(p, 'enabled', True)

        ollama_status = {}
        if hasattr(self.core, 'ollama_manager'):
            ollama_status = self.core.ollama_manager.get_status()

        model_status = {}
        mm = getattr(self.core, 'model_manager', None)
        if mm:
            model_status = {
                'provider': self.core.gateway.llm.provider,
                'model': self.core.gateway.llm.model,
                'mode': mm.current_mode,
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

        return web.json_response({
            # Core stats
            'uptime': uptime,
            'uptime_formatted': _fmt_uptime(uptime),
            'version': self.core.config.get('system', {}).get('version', '0.9.2'),
            'system_name': self.core.config.get('system', {}).get('name', 'Galactic AI'),
            'personality': self.core.config.get('personality', {}).get('name', '--'),
            'tokens_in': self.core.gateway.total_tokens_in,
            'tokens_out': self.core.gateway.total_tokens_out,

            # Model info
            'model': model_status,
            'primary_model': f"{mm.primary_provider}/{mm.primary_model}" if mm else '--',
            'fallback_model': f"{mm.fallback_provider}/{mm.fallback_model}" if mm else '--',
            'auto_fallback': mm.auto_fallback_enabled if mm else False,
            'smart_routing': models_cfg.get('smart_routing', False),
            'streaming': models_cfg.get('streaming', True),
            'max_turns': models_cfg.get('max_turns', 50),
            'speak_timeout': models_cfg.get('speak_timeout', 600),

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
            'voice': self.core.config.get('elevenlabs', {}).get('voice', 'Guy'),
            'update_check_interval': self.core.config.get('system', {}).get('update_check_interval', 21600),
        })

    async def handle_plugin_toggle(self, request):
        """POST /api/plugin_toggle — {name, enabled: bool}"""
        try:
            data = await request.json()
            name = data.get('name', '')
            enabled = data.get('enabled', True)
            for p in self.core.plugins:
                if p.name == name:
                    p.enabled = bool(enabled)
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
        """GET /api/plugins — list all loaded plugins with status."""
        plugins = []
        for p in self.core.plugins:
            plugins.append({
                'name': p.name,
                'enabled': getattr(p, 'enabled', True),
                'class': p.__class__.__name__,
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
                await self.core.model_manager._save_config()
            # Check if API key is actually configured
            current_key = getattr(self.core.gateway.llm, 'api_key', '')
            if provider != 'ollama' and (not current_key or current_key == 'NONE'):
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

            if pp and pm:
                await mm.set_primary(pp, pm)
            if fp and fm:
                await mm.set_fallback(fp, fm)

            # Toggles — update in-memory, then save ONCE (not 3x)
            cfg = self.core.config
            cfg.setdefault('models', {})
            toggle_changed = False
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
        if 'elevenlabs' not in cfg:
            cfg['elevenlabs'] = {}
        cfg['elevenlabs']['voice'] = voice
        try:
            self._save_config(cfg)
            await self.core.log(f"🔊 Voice set to {voice} via Settings", priority=2)
            return web.json_response({'ok': True, 'voice': voice})
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

        try:
            self._save_config(cfg)
            await self.core.log("⚙️ System settings updated via Settings tab", priority=2)
            return web.json_response({'ok': True})
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})

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

    async def handle_browser_cmd(self, request):
        """POST /api/browser_cmd — {command, args} — browser quick commands."""
        try:
            data = await request.json()
            cmd = data.get('command', '')
            args = data.get('args', {})
            bp = next((p for p in self.core.plugins if 'BrowserExecutorPro' in p.__class__.__name__), None)
            if not bp:
                return web.json_response({'error': 'Browser plugin not loaded'}, status=503)
            method = getattr(bp, cmd, None)
            if not method or not callable(method):
                return web.json_response({'error': f'Unknown browser command: {cmd}'}, status=404)
            result = await method(**args)
            return web.json_response({'result': result})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_login(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'success': False, 'error': 'Invalid JSON'}, status=400)
        password = data.get('password', '')
        if not password:
            return web.json_response({'success': False, 'error': 'No password'}, status=400)
        h = hashlib.sha256(password.encode()).hexdigest()

        # If no password_hash is set yet, treat as first-run (accept any password and save it)
        if not self.password_hash:
            self.password_hash = h
            cfg = self.core.config
            if 'web' not in cfg:
                cfg['web'] = {}
            cfg['web']['password_hash'] = h
            # Save to config.yaml (safe read-modify-write)
            try:
                self._save_config(cfg)
            except Exception:
                pass  # Non-fatal — hash saved in memory
            # Return JWT if remote access is enabled, otherwise legacy hash token
            token_resp = self._make_token_response(h)
            token_resp['first_run'] = True
            return web.json_response(token_resp)

        if h == self.password_hash:
            return web.json_response(self._make_token_response(h))
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
            h = hashlib.sha256(pw.encode()).hexdigest()
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
            src = openclaw_workspace / fname
            dst = dest_dir / fname
            try:
                shutil.copy2(str(src), str(dst))
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
        # Persist to config.yaml (safe read-modify-write)
        try:
            self._save_config(cfg)
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})
        return web.json_response({'ok': True, 'max_tokens': cfg['models'].get('max_tokens', 0), 'context_window': cfg['models'].get('context_window', 0)})

    def _save_config(self, cfg):
        """Safely merge in-memory config into config.yaml (read-modify-write).

        Reads the existing file first so keys written by other code paths
        (especially model_manager._save_config) are never lost.
        """
        import yaml
        cfg_path = getattr(self.core, 'config_path', None)
        if not cfg_path:
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        # 1. Read existing config from disk to preserve all keys
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                on_disk = yaml.safe_load(f) or {}
        except Exception:
            on_disk = {}
        # 2. Deep-merge: update top-level sections from in-memory cfg
        for key, value in cfg.items():
            if isinstance(value, dict) and isinstance(on_disk.get(key), dict):
                on_disk[key].update(value)
            else:
                on_disk[key] = value
        # 3. Defensive: always write current model keys from ModelManager
        #    This makes it IMPOSSIBLE for any save to erase model settings.
        mm = getattr(self.core, 'model_manager', None)
        if mm:
            on_disk.setdefault('models', {})
            on_disk['models']['primary_provider'] = mm.primary_provider
            on_disk['models']['primary_model'] = mm.primary_model
            on_disk['models']['fallback_provider'] = mm.fallback_provider
            on_disk['models']['fallback_model'] = mm.fallback_model
            on_disk.setdefault('gateway', {})
            on_disk['gateway']['provider'] = mm.primary_provider
            on_disk['gateway']['model'] = mm.primary_model
        # 4. Write back
        with open(cfg_path, 'w', encoding='utf-8') as f:
            yaml.dump(on_disk, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

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

    async def handle_stream(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
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
            def __init__(self, ws):
                self.ws = ws
            def write(self, data):
                decoded = data.decode()
                asyncio.create_task(self.ws.send_str(decoded))
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
                    telemetry = {
                        "type": "telemetry",
                        "data": {
                            "model": self.core.gateway.llm.model,
                            "provider": self.core.gateway.llm.provider,
                            "tin": self.core.gateway.total_tokens_in,
                            "tout": self.core.gateway.total_tokens_out,
                            "uptime": uptime,
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
                        await self.core.log(f"[Core] Byte: {response}", priority=3)
                    elif payload.get('type') == 'switch_model':
                        prov = payload['provider']
                        mod = payload['model']
                        self.core.gateway.llm.provider = prov
                        self.core.gateway.llm.model = mod
                        if prov == 'google': self.core.gateway.llm.api_key = self.core.config['providers']['google']['apiKey']
                        elif prov == 'nvidia':
                            keys = self.core.config['providers']['nvidia']['keys']
                            if "deepseek" in mod: self.core.gateway.llm.api_key = keys['deepseek']
                            elif "qwen" in mod: self.core.gateway.llm.api_key = keys['qwen']
                        await self.core.log(f"Shifted Model via Web Deck: {mod}", priority=1)
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
        """List workspace files — auto-creates missing .md files with starter templates."""
        try:
            workspace = self.core.config.get('paths', {}).get('workspace', '')
            if not workspace:
                workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

            # Auto-create missing .md files with defaults
            DEFAULTS = {
                'USER.md': '# User Profile\n\nTell your AI about yourself here.\n',
                'MEMORY.md': '# Memory\n\nThe AI will store important things here.\n',
                'IDENTITY.md': '# Identity\n\nDefine who your AI is here.\n',
                'SOUL.md': '# Soul\n\nDefine your AI\'s core values and personality here.\n',
                'TOOLS.md': '# Tools\n\nNotes about available tools and workflows.\n',
                'VAULT.md': '# VAULT — Personal Credentials & Private Data\n\nStore login credentials, API keys, and personal info here.\nThe AI loads this file into every prompt for automation tasks.\n**Never share this file publicly.**\n',
            }
            os.makedirs(workspace, exist_ok=True)
            for fname, default_content in DEFAULTS.items():
                fpath = os.path.join(workspace, fname)
                if not os.path.exists(fpath):
                    try:
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(default_content)
                    except Exception:
                        pass

            files = []
            for f in ['MEMORY.md', 'USER.md', 'SOUL.md', 'IDENTITY.md', 'TOOLS.md', 'VAULT.md', 'HEARTBEAT.md']:
                path = os.path.join(workspace, f)
                if os.path.exists(path):
                    files.append({'name': f, 'size': os.path.getsize(path)})
            return web.json_response({'files': files})
        except Exception as e:
            return web.json_response({'files': [], 'error': str(e)})
    
    async def handle_get_file(self, request):
        """Get file contents"""
        filename = request.query.get('name')
        if not filename or not filename.endswith('.md'):
            return web.json_response({'error': 'Invalid file'}, status=400)
        workspace = self.core.config['paths']['workspace']
        path = os.path.join(workspace, filename)
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
        workspace = self.core.config['paths']['workspace']
        path = os.path.join(workspace, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        await self.core.log(f"File saved via Web Deck: {filename}", priority=2)
        return web.json_response({'success': True})

    # ── Voice API Endpoints ─────────────────────────────────────────────────────

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
                m = re.search(r'Generated speech.*?:\s*(.+\.mp3)', str(result))
                if m:
                    audio_path = m.group(1).strip()
                    if os.path.exists(audio_path):
                        with open(audio_path, 'rb') as f:
                            audio_data = f.read()
                        return web.Response(body=audio_data, content_type='audio/mpeg',
                                           headers={'Content-Disposition': 'inline; filename="tts.mp3"'})
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
            try:
                # Try OpenAI Whisper
                openai_key = self.core.config.get('providers', {}).get('openai', {}).get('apiKey', '')
                if openai_key:
                    import httpx
                    async with httpx.AsyncClient(timeout=30) as client:
                        with open(temp_path, 'rb') as af:
                            resp = await client.post(
                                'https://api.openai.com/v1/audio/transcriptions',
                                headers={'Authorization': f'Bearer {openai_key}'},
                                files={'file': (filename, af, 'audio/wav')},
                                data={'model': 'whisper-1'}
                            )
                        if resp.status_code == 200:
                            transcription = resp.json().get('text', '')
                # Fallback: Groq Whisper
                if not transcription:
                    groq_key = self.core.config.get('providers', {}).get('groq', {}).get('apiKey', '')
                    if groq_key:
                        import httpx
                        async with httpx.AsyncClient(timeout=30) as client:
                            with open(temp_path, 'rb') as af:
                                resp = await client.post(
                                    'https://api.groq.com/openai/v1/audio/transcriptions',
                                    headers={'Authorization': f'Bearer {groq_key}'},
                                    files={'file': (filename, af, 'audio/wav')},
                                    data={'model': 'whisper-large-v3'}
                                )
                            if resp.status_code == 200:
                                transcription = resp.json().get('text', '')
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            if transcription:
                return web.json_response({'text': transcription})
            return web.json_response({'error': 'Transcription failed — no Whisper API key configured'}, status=500)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

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
            await site.start()

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
            await site.start()
