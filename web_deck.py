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
        self.app = web.Application()
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
  --bg:#05060a;--bg2:#0d0e18;--bg3:#12131f;
  --cyan:#00f3ff;--pink:#ff00c8;--green:#00ff88;--yellow:#ffcc00;--red:#ff4444;--orange:#ff8800;
  --border:rgba(0,243,255,0.2);--text:#e0e0e0;--dim:#888;
  --font:'Segoe UI',system-ui,sans-serif;--mono:'Cascadia Code','Consolas',monospace;
}
body{background:var(--bg);color:var(--text);font-family:var(--font);height:100vh;overflow:hidden;display:flex;flex-direction:column}
body::after{content:"";position:fixed;inset:0;background:linear-gradient(rgba(18,16,16,0) 50%,rgba(0,0,0,0.15) 50%);background-size:100% 3px;pointer-events:none;z-index:9000;opacity:0.4}
#topbar{display:flex;align-items:center;gap:10px;padding:8px 16px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;z-index:100}
#topbar .logo{font-size:1.1em;font-weight:700;letter-spacing:4px;color:var(--cyan);text-shadow:0 0 10px var(--cyan);white-space:nowrap}
#topbar .spacer{flex:1}
.status-dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);flex-shrink:0}
.status-dot.offline{background:var(--red);box-shadow:0 0 6px var(--red)}
#ollama-pill{display:flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid var(--border);border-radius:20px;font-size:0.75em;background:var(--bg3);cursor:pointer}
#model-badge{padding:4px 10px;border:1px solid var(--pink);border-radius:20px;font-size:0.75em;color:var(--pink);cursor:pointer;white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.topbar-btn{padding:5px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);color:var(--text);cursor:pointer;font-size:0.78em;transition:all .2s}
.topbar-btn:hover{border-color:var(--cyan);color:var(--cyan)}
#token-counter{font-size:0.72em;color:var(--dim);font-family:var(--mono)}
#main{display:flex;flex:1;overflow:hidden}
#sidebar{width:220px;min-width:180px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;transition:width .2s}
#sidebar.collapsed{width:0;min-width:0}
.sidebar-section{padding:10px 12px 6px;font-size:0.68em;letter-spacing:2px;color:var(--dim);text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.05);flex-shrink:0}
.sidebar-item{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;font-size:0.82em;transition:background .15s;border-bottom:1px solid rgba(255,255,255,0.03)}
.sidebar-item:hover,.sidebar-item.active{background:rgba(0,243,255,0.08);color:var(--cyan)}
.sidebar-item .icon{width:18px;text-align:center;flex-shrink:0}
.sidebar-item .badge{margin-left:auto;background:var(--pink);color:#fff;font-size:0.7em;padding:1px 6px;border-radius:10px}
#content{flex:1;display:flex;flex-direction:column;overflow:hidden}
#tabbar{display:flex;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;overflow-x:auto}
.tab-btn{padding:9px 18px;font-size:0.8em;letter-spacing:1px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;color:var(--dim);background:none;border-top:none;border-left:none;border-right:none;transition:all .2s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--cyan);border-bottom-color:var(--cyan)}
.tab-pane{display:none;flex:1;overflow:hidden;flex-direction:column}
.tab-pane.active{display:flex}
#chat-wrap{display:flex;flex:1;overflow:hidden;gap:0}
#chat-log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
#chat-log::-webkit-scrollbar{width:4px}
#chat-log::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.msg{display:flex;flex-direction:column;gap:4px;max-width:90%}
.msg.user{align-self:flex-end;align-items:flex-end}
.msg.bot{align-self:flex-start;align-items:flex-start}
.msg .bubble{padding:10px 14px;border-radius:14px;font-size:0.88em;line-height:1.55;word-break:break-word;white-space:pre-wrap}
.msg.user .bubble{background:linear-gradient(135deg,rgba(0,243,255,0.15),rgba(0,243,255,0.08));border:1px solid rgba(0,243,255,0.3);border-bottom-right-radius:3px}
.msg.bot .bubble{background:var(--bg3);border:1px solid var(--border);border-bottom-left-radius:3px}
.msg.bot.thinking .bubble{border-color:rgba(255,0,200,0.3);color:var(--dim)}
.msg .meta{font-size:0.68em;color:var(--dim)}
#stream-bubble{padding:10px 14px;border-radius:14px;font-size:0.88em;line-height:1.55;background:var(--bg3);border:1px solid rgba(255,0,200,0.3);color:var(--pink);white-space:pre-wrap;word-break:break-word;align-self:flex-start;max-width:90%;display:none}
#chat-input-row{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--border);flex-shrink:0;background:var(--bg2)}
#chat-input{flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--text);font-family:var(--font);font-size:0.9em;resize:none;height:44px;max-height:200px;overflow-y:auto;outline:none;transition:border .2s}
#chat-input:focus{border-color:var(--cyan)}
#send-btn{padding:10px 20px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.9em;transition:opacity .2s}
#send-btn:disabled{opacity:0.4;cursor:not-allowed}
#chat-tools-sidebar{width:220px;border-left:1px solid var(--border);background:var(--bg2);display:flex;flex-direction:column;overflow-y:auto;flex-shrink:0}
#chat-tools-sidebar h4{padding:10px 12px;font-size:0.72em;letter-spacing:2px;color:var(--dim);border-bottom:1px solid var(--border);text-transform:uppercase}
.quick-tool-btn{display:flex;align-items:center;gap:8px;width:100%;padding:8px 12px;background:none;border:none;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--text);font-size:0.8em;cursor:pointer;text-align:left;transition:background .15s}
.quick-tool-btn:hover{background:rgba(0,243,255,0.06);color:var(--cyan)}
.quick-tool-btn .tool-icon{font-size:1em;width:18px;text-align:center}
#tools-pane{padding:16px;overflow-y:auto}
#tools-pane h3{color:var(--cyan);margin-bottom:12px;font-size:0.9em;letter-spacing:2px}
#tool-search{width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.85em;margin-bottom:14px;outline:none}
#tool-search:focus{border-color:var(--cyan)}
.tool-group{margin-bottom:16px}
.tool-group-label{font-size:0.7em;letter-spacing:2px;color:var(--pink);text-transform:uppercase;margin-bottom:8px;padding:4px 0;border-bottom:1px solid rgba(255,0,200,0.2)}
.tool-card{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:6px;cursor:pointer;transition:all .2s}
.tool-card:hover{border-color:var(--cyan);background:rgba(0,243,255,0.05)}
.tool-card h4{font-size:0.85em;color:var(--cyan);margin-bottom:3px}
.tool-card p{font-size:0.75em;color:var(--dim);line-height:1.4}
.tool-card .params{font-size:0.7em;color:var(--yellow);margin-top:4px;font-family:var(--mono)}
#tool-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:5000;align-items:center;justify-content:center}
#tool-modal.open{display:flex}
#tool-modal-inner{background:var(--bg2);border:1px solid var(--cyan);border-radius:14px;padding:24px;width:480px;max-width:95vw;max-height:90vh;overflow-y:auto}
#tool-modal-inner h3{color:var(--cyan);margin-bottom:8px}
#tool-modal-inner p{color:var(--dim);font-size:0.85em;margin-bottom:16px}
.param-row{margin-bottom:10px}
.param-row label{display:block;font-size:0.78em;color:var(--yellow);margin-bottom:4px;font-family:var(--mono)}
.param-row input,.param-row textarea{width:100%;padding:7px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.85em;outline:none}
.param-row input:focus,.param-row textarea:focus{border-color:var(--cyan)}
.modal-btns{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
.btn{padding:8px 18px;border-radius:8px;cursor:pointer;font-size:0.85em;border:none}
.btn.primary{background:var(--cyan);color:#000;font-weight:700}
.btn.secondary{background:var(--bg3);border:1px solid var(--border);color:var(--text)}
.btn:hover{opacity:0.85}
#tool-result{margin-top:12px;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;font-size:0.8em;font-family:var(--mono);white-space:pre-wrap;max-height:200px;overflow-y:auto;display:none}
#plugins-pane{padding:16px;overflow-y:auto}
#plugins-pane h3{color:var(--cyan);margin-bottom:14px;font-size:0.9em;letter-spacing:2px}
.plugin-card{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:10px;display:flex;align-items:center;gap:14px}
.plugin-card .plugin-icon{font-size:1.5em;width:36px;text-align:center}
.plugin-card .plugin-info{flex:1}
.plugin-card .plugin-name{font-size:0.9em;font-weight:600;color:var(--cyan)}
.plugin-card .plugin-desc{font-size:0.75em;color:var(--dim);margin-top:2px}
.plugin-card .plugin-class{font-size:0.68em;color:var(--pink);font-family:var(--mono);margin-top:2px}
.toggle-switch{position:relative;width:44px;height:24px;flex-shrink:0}
.toggle-switch input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:#333;border-radius:24px;cursor:pointer;transition:.3s}
.toggle-slider:before{content:"";position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s}
.toggle-switch input:checked + .toggle-slider{background:var(--green)}
.toggle-switch input:checked + .toggle-slider:before{transform:translateX(20px)}
#models-pane{padding:16px;overflow-y:auto}
#models-pane h3{color:var(--cyan);margin-bottom:14px;font-size:0.9em;letter-spacing:2px}
.provider-section{margin-bottom:20px}
.provider-label{font-size:0.72em;letter-spacing:2px;color:var(--pink);text-transform:uppercase;margin-bottom:10px;padding-bottom:4px;border-bottom:1px solid rgba(255,0,200,0.2)}
.model-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.model-btn{padding:10px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.8em;cursor:pointer;text-align:left;transition:all .2s;line-height:1.3}
.model-btn:hover{border-color:var(--cyan);color:var(--cyan);background:rgba(0,243,255,0.05)}
.model-btn.active{border-color:var(--green);color:var(--green);background:rgba(0,255,136,0.08)}
#ollama-section .model-btn{border-color:rgba(255,136,0,0.3)}
#ollama-section .model-btn.active{border-color:var(--orange);color:var(--orange)}
#ollama-health-row{display:flex;align-items:center;gap:8px;margin-bottom:12px;padding:8px 12px;background:var(--bg3);border-radius:8px;border:1px solid var(--border);font-size:0.82em}
#ollama-health{font-weight:600}
.model-config-box{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px}
.model-config-box h4{font-size:0.8em;color:var(--dim);margin-bottom:10px;letter-spacing:1px}
.model-config-row{display:flex;gap:8px;margin-bottom:8px}
.model-config-row label{font-size:0.75em;color:var(--dim);min-width:70px;display:flex;align-items:center}
.model-config-row input,.model-config-row select{flex:1;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.82em;outline:none}
.model-config-row input:focus{border-color:var(--cyan)}
#browser-pane{padding:16px;overflow-y:auto}
#browser-pane h3{color:var(--cyan);margin-bottom:14px;font-size:0.9em;letter-spacing:2px}
.browser-url-row{display:flex;gap:8px;margin-bottom:14px}
#browser-url{flex:1;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.88em;outline:none}
#browser-url:focus{border-color:var(--cyan)}
.browser-action-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px}
.browser-btn{padding:10px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.78em;cursor:pointer;text-align:center;transition:all .2s}
.browser-btn:hover{border-color:var(--cyan);color:var(--cyan)}
#browser-screenshot{width:100%;border-radius:8px;border:1px solid var(--border);display:none;margin-top:10px}
#browser-status{font-size:0.8em;color:var(--dim);font-family:var(--mono);padding:8px;background:var(--bg3);border-radius:6px;margin-top:8px;min-height:32px}
#logs-pane{display:flex;flex-direction:column;overflow:hidden}
#log-controls{display:flex;gap:8px;padding:10px 14px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg2)}
#log-filter{padding:5px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.8em;flex:1;outline:none}
#logs-scroll{flex:1;overflow-y:auto;padding:10px 14px;font-family:var(--mono);font-size:0.78em;line-height:1.7}
#logs-scroll::-webkit-scrollbar{width:4px}
#logs-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.log-line{padding:1px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
.log-line.err{color:var(--red)}
.log-line.warn{color:var(--yellow)}
.log-line.ok{color:var(--green)}
#status-pane{padding:16px;overflow-y:auto}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:16px}
.stat-card{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
.stat-card .val{font-size:1.6em;font-weight:700;color:var(--cyan);font-family:var(--mono)}
.stat-card .lbl{font-size:0.72em;color:var(--dim);margin-top:4px;letter-spacing:1px;text-transform:uppercase}
#memory-pane{padding:16px;overflow-y:auto}
.mem-controls{display:flex;gap:8px;margin-bottom:12px}
#mem-file-select{flex:1;padding:7px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.83em;outline:none}
#mem-editor{width:100%;height:calc(100vh - 280px);padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--mono);font-size:0.82em;resize:vertical;outline:none}
#mem-editor:focus{border-color:var(--cyan)}
#login-overlay{position:fixed;inset:0;background:rgba(5,6,10,0.97);z-index:8000;display:flex;align-items:center;justify-content:center}
.login-box{background:var(--bg2);border:1px solid var(--cyan);border-radius:16px;padding:36px;width:340px;text-align:center}
.login-box h2{color:var(--cyan);letter-spacing:4px;margin-bottom:6px;font-size:1.1em}
.login-box p{color:var(--dim);font-size:0.82em;margin-bottom:22px}
#pw-input{width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em;text-align:center;outline:none;letter-spacing:3px;margin-bottom:12px}
#pw-input:focus{border-color:var(--cyan)}
#login-btn{width:100%;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:8px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em}
#login-err{color:var(--red);font-size:0.8em;margin-top:8px;display:none}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-overlay" style="display:none">
  <div class="login-box">
    <div style="font-size:2em;margin-bottom:8px">⬡</div>
    <h2>GALACTIC AI</h2>
    <p>AUTOMATION SUITE v0.7.0</p>
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

<!-- TOP BAR -->
<div id="topbar">
  <div class="logo">⬡ GALACTIC AI</div>
  <div id="version-badge" style="font-size:0.65em;color:var(--dim);letter-spacing:1px;padding:2px 7px;border:1px solid var(--border);border-radius:10px;cursor:default" title="Galactic AI version">v0.7.1</div>
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
  <button class="topbar-btn" onclick="location.reload()">↺</button>
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
    <div class="sidebar-item" onclick="switchTab('logs')"><span class="icon">📋</span> Logs</div>
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
      <button class="tab-btn" onclick="switchTab('logs')">📋 Logs</button>
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
            <input type="file" id="chat-file-input" multiple accept=".txt,.md,.py,.js,.ts,.json,.yaml,.yml,.xml,.html,.css,.csv,.log,.toml,.ini,.cfg,.sh,.ps1,.bat,.rs,.go,.java,.c,.cpp,.h,.hpp,.rb,.php,.sql,.r,.swift,.kt,.dart,.env,.conf,.properties" style="display:none" onchange="handleFileAttach(this)">
            <button id="attach-btn" onclick="document.getElementById('chat-file-input').click()" title="Attach files" style="padding:10px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--dim);cursor:pointer;font-size:1.1em;transition:border .2s,color .2s" onmouseover="this.style.borderColor='var(--cyan)';this.style.color='var(--cyan)'" onmouseout="this.style.borderColor='var(--border)';this.style.color='var(--dim)'">📎</button>
            <textarea id="chat-input-main" placeholder="Message Byte... (Enter to send, Shift+Enter for newline)" style="flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--text);font-family:var(--font);font-size:0.9em;resize:none;height:44px;max-height:200px;overflow-y:auto;outline:none;transition:border .2s" onkeydown="handleKeyMain(event)" oninput="autoResize(this)"></textarea>
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
              <div style="font-size:0.72em;color:var(--dim);margin-bottom:3px">Model ID / Alias</div>
              <input id="pmo-model" type="text" placeholder="e.g. gemini-2.5-flash" style="width:100%;padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
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
      <div id="status-pane">
        <h3>📊 SYSTEM STATUS</h3>
        <div class="stat-grid">
          <div class="stat-card"><div class="val" id="st-uptime">--</div><div class="lbl">Uptime (s)</div></div>
          <div class="stat-card"><div class="val" id="st-tin">--</div><div class="lbl">Tokens In</div></div>
          <div class="stat-card"><div class="val" id="st-tout">--</div><div class="lbl">Tokens Out</div></div>
          <div class="stat-card"><div class="val" id="st-model">--</div><div class="lbl">Active Model</div></div>
          <div class="stat-card"><div class="val" id="st-provider">--</div><div class="lbl">Provider</div></div>
          <div class="stat-card"><div class="val" id="st-ollama-models">--</div><div class="lbl">Ollama Models</div></div>
        </div>
        <button class="btn secondary" onclick="refreshStatus()" style="margin-bottom:12px">Refresh Status</button>
        <div id="status-plugins-list"></div>
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

<script>
// State
let token = localStorage.getItem('gal_token') || '';
let socket = null;
let allToolsData = [];
let currentTool = null;
let autoScroll = true;
let allLogs = [];
let httpChatPending = false;  // suppresses WS 'thought' dupes while HTTP /api/chat in flight

// ── Setup Wizard ─────────────────────────────────────────────────────────────
async function checkSetup() {
  try {
    const r = await fetch('/api/check_setup');
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
  google:      {placeholder:'gemini-2.5-flash', link:'Get key: <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--cyan)">aistudio.google.com/apikey</a>'},
  anthropic:   {placeholder:'claude-opus-4-6', link:'Get key: <a href="https://console.anthropic.com/keys" target="_blank" style="color:var(--cyan)">console.anthropic.com/keys</a>'},
  openai:      {placeholder:'gpt-4o', link:'Get key: <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--cyan)">platform.openai.com/api-keys</a>'},
  xai:         {placeholder:'grok-4', link:'Get key: <a href="https://console.x.ai" target="_blank" style="color:var(--cyan)">console.x.ai</a>'},
  groq:        {placeholder:'llama-4-scout-17b-16e-instruct', link:'Get key: <a href="https://console.groq.com/keys" target="_blank" style="color:var(--cyan)">console.groq.com/keys</a>'},
  mistral:     {placeholder:'mistral-small-latest', link:'Get key: <a href="https://console.mistral.ai/api-keys" target="_blank" style="color:var(--cyan)">console.mistral.ai/api-keys</a>'},
  cerebras:    {placeholder:'llama3.3-70b', link:'Get key: <a href="https://cloud.cerebras.ai" target="_blank" style="color:var(--cyan)">cloud.cerebras.ai</a>'},
  openrouter:  {placeholder:'anthropic/claude-opus-4-6', link:'Get key: <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--cyan)">openrouter.ai/keys</a>'},
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
    const r = await fetch('/api/setup', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
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
    const r = await fetch('/api/check_openclaw');
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
    const r = await fetch('/api/migrate_openclaw', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({files})});
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
async function init() {
  await loadChatHistory();
  await loadLogHistory();
  connectWS();
  await loadTools();
  await loadPlugins();
  loadOllamaStatus();
  renderModelGrid();
  refreshStatus();
  loadFileList();
}


// WebSocket
function connectWS() {
  socket = new WebSocket(`ws://${location.host}/stream?token=${token}`);
  socket.onmessage = e => {
    const p = JSON.parse(e.data);
    if (p.type === 'stream_chunk') {
      const sb = document.getElementById('stream-bubble');
      sb.style.display = 'block';
      // accumulate raw text on a data attr, render formatted
      sb._rawText = (sb._rawText || '') + p.data;
      sb.innerHTML = formatMsg(sb._rawText);
      if (autoScroll) document.getElementById('chat-log').scrollTop = 99999;
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
    }
  };
  socket.onclose = () => setTimeout(connectWS, 3000);
}

// Chat
function appendBotMsg(text) {
  const sb = document.getElementById('stream-bubble');
  sb.style.display = 'none'; sb.textContent = ''; sb._rawText = '';
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble">${formatMsg(text)}</div><div class="meta">Byte • now</div>`;
  log.appendChild(div);
  if (autoScroll) log.scrollTop = 99999;
}

async function loadChatHistory() {
  try {
    const r = await fetch('/api/history?limit=50');
    const d = await r.json();
    const msgs = d.messages || [];
    if (msgs.length > 0) {
      // Clear the default welcome message before restoring history
      document.getElementById('chat-log').innerHTML = '<div id="stream-bubble" style="display:none"></div>';
      msgs.forEach(m => {
        if (m.role === 'user') appendUserMsg(m.content);
        else if (m.role === 'assistant') appendBotMsg(m.content);
      });
    }
  } catch(e) { console.error('loadChatHistory:', e); }
}

async function loadLogHistory() {
  try {
    const r = await fetch('/api/logs?limit=200');
    const d = await r.json();
    (d.logs || []).forEach(l => addLog(l));
  } catch(e) { console.error('loadLogHistory:', e); }
}

function appendUserMsg(text) {
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="bubble">${escHtml(text)}</div><div class="meta">You • now</div>`;
  log.appendChild(div);
  if (autoScroll) log.scrollTop = 99999;
}

// ─── File Attachment State ───
let pendingFiles = [];

function handleFileAttach(input) {
  for (const f of input.files) {
    if (f.size > 5 * 1024 * 1024) { appendBotMsg('[File too large] ' + f.name + ' exceeds 5 MB limit.'); continue; }
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
  bar.innerHTML = pendingFiles.map((f, i) =>
    '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;font-size:0.78em;color:var(--cyan)">' +
    '📄 ' + escHtml(f.name) + ' <span style="font-size:0.75em;color:var(--dim)">(' + (f.size < 1024 ? f.size + 'B' : (f.size/1024).toFixed(1) + 'KB') + ')</span>' +
    '<span onclick="removeAttachment(' + i + ')" style="cursor:pointer;color:var(--red);margin-left:4px;font-weight:700" title="Remove">&times;</span></span>'
  ).join('');
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
      const fd = new FormData();
      fd.append('message', msg);
      for (const f of filesToSend) fd.append('files', f);
      r = await fetch('/api/chat', {method:'POST', body: fd});
    } else {
      r = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: msg})});
    }
    const d = await r.json();
    stream.style.display = 'none'; stream.textContent = '';
    appendBotMsg(d.response || d.error || 'No response');
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
  const r = await fetch('/api/tools');
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
    const r = await fetch('/api/tool_invoke', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tool: currentTool.name, args})});
    const d = await r.json();
    resEl.textContent = typeof d.result === 'string' ? d.result : JSON.stringify(d.result || d.error, null, 2);
  } catch(err) { resEl.textContent = 'Error: ' + err.message; }
}

// Plugins
async function loadPlugins() {
  const r = await fetch('/api/plugins');
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
  await fetch('/api/plugin_toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, enabled})});
}

// Models
const ALL_MODELS = {
  'Google': [
    {name:'Gemini 3 Flash ⚡ [LATEST]', id:'gemini-3-flash-preview', provider:'google'},
    {name:'Gemini 2.5 Flash', id:'gemini-2.5-flash', provider:'google'},
    {name:'Gemini 3 Pro [LATEST]', id:'gemini-3-pro-preview', provider:'google'},
    {name:'Gemini 2.5 Pro', id:'gemini-2.5-pro', provider:'google'},
    {name:'Gemini 2.0 Flash', id:'gemini-2.0-flash', provider:'google'},
  ],
  'Anthropic': [
    {name:'Claude Opus 4.6 [LATEST]', id:'claude-opus-4-6', provider:'anthropic'},
    {name:'Claude Sonnet 4.5', id:'claude-sonnet-4-5', provider:'anthropic'},
    {name:'Claude 3.7 Sonnet', id:'claude-3-7-sonnet-20250219', provider:'anthropic'},
    {name:'Claude 3.5 Sonnet', id:'claude-3-5-sonnet-20241022', provider:'anthropic'},
    {name:'Claude 3.5 Haiku', id:'claude-3-5-haiku-20241022', provider:'anthropic'},
    {name:'Claude 3 Opus', id:'claude-3-opus-20240229', provider:'anthropic'},
  ],
  'OpenAI': [
    {name:'GPT-4o [LATEST]', id:'gpt-4o', provider:'openai'},
    {name:'GPT-4.1', id:'gpt-4.1', provider:'openai'},
    {name:'GPT-4o Mini', id:'gpt-4o-mini', provider:'openai'},
    {name:'o3 Mini', id:'o3-mini', provider:'openai'},
    {name:'o1', id:'o1', provider:'openai'},
  ],
  'xAI': [
    {name:'Grok 4 [LATEST]', id:'grok-4', provider:'xai'},
    {name:'Grok 4 Fast', id:'grok-4-fast', provider:'xai'},
    {name:'Grok 3', id:'grok-3', provider:'xai'},
    {name:'Grok 3 Mini', id:'grok-3-mini', provider:'xai'},
  ],
  'Groq (Fast)': [
    {name:'Llama 4 Scout 17B [FAST]', id:'llama-4-scout-17b-16e-instruct', provider:'groq'},
    {name:'Llama 4 Maverick 17B', id:'llama-4-maverick-17b-128e-instruct', provider:'groq'},
    {name:'Llama 3.3 70B', id:'llama-3.3-70b-versatile', provider:'groq'},
    {name:'DeepSeek R1 70B', id:'deepseek-r1-distill-llama-70b', provider:'groq'},
    {name:'Qwen 3 32B', id:'qwen-3-32b', provider:'groq'},
    {name:'Gemma 3 27B', id:'gemma2-9b-it', provider:'groq'},
  ],
  'Mistral': [
    {name:'Mistral Small 3.1', id:'mistral-small-latest', provider:'mistral'},
    {name:'Codestral (Code)', id:'codestral-latest', provider:'mistral'},
    {name:'Devstral (Agents)', id:'devstral-small-latest', provider:'mistral'},
    {name:'Mistral Large 2', id:'mistral-large-latest', provider:'mistral'},
    {name:'Magistral Medium', id:'magistral-medium-latest', provider:'mistral'},
  ],
  'Cerebras': [
    {name:'Llama 3.3 70B [FAST]', id:'llama3.3-70b', provider:'cerebras'},
    {name:'Llama 3.1 8B', id:'llama3.1-8b', provider:'cerebras'},
    {name:'Qwen 3 32B', id:'qwen-3-32b', provider:'cerebras'},
  ],
  'OpenRouter': [
    {name:'Claude Opus 4.6 (via OR)', id:'anthropic/claude-opus-4-6', provider:'openrouter'},
    {name:'GPT-4o (via OR)', id:'openai/gpt-4o', provider:'openrouter'},
    {name:'Gemini 2.5 Pro (via OR)', id:'google/gemini-2.5-pro', provider:'openrouter'},
    {name:'Llama 4 Scout (via OR)', id:'meta-llama/llama-4-scout', provider:'openrouter'},
    {name:'DeepSeek V3 (via OR)', id:'deepseek/deepseek-chat', provider:'openrouter'},
  ],
  'HuggingFace': [
    {name:'Qwen3 235B', id:'Qwen/Qwen3-235B-A22B', provider:'huggingface'},
    {name:'Llama 4 Scout', id:'meta-llama/Llama-4-Scout-17B-16E-Instruct', provider:'huggingface'},
    {name:'DeepSeek V3', id:'deepseek-ai/DeepSeek-V3-0324', provider:'huggingface'},
  ],
  'Kimi / Moonshot': [
    {name:'Kimi K2.5 (Coding)', id:'kimi-k2.5', provider:'kimi'},
    {name:'Kimi K2 Thinking', id:'kimi-k2-thinking', provider:'kimi'},
  ],
  'ZAI / GLM': [
    {name:'GLM-4 Plus', id:'glm-4-plus', provider:'zai'},
    {name:'GLM-4.5 Air', id:'glm-4.5-air', provider:'zai'},
    {name:'GLM-4V Plus (Vision)', id:'glm-4v-plus', provider:'zai'},
  ],
  'MiniMax': [
    {name:'MiniMax Text-01', id:'MiniMax-Text-01', provider:'minimax'},
    {name:'MiniMax M2', id:'MiniMax-M2', provider:'minimax'},
  ],
  'NVIDIA': [
    {name:'DeepSeek V3.2 [TITAN]', id:'deepseek-ai/deepseek-v3.2', provider:'nvidia'},
    {name:'Qwen3 Coder 480B', id:'qwen/qwen3-coder-480b-a35b-instruct', provider:'nvidia'},
    {name:'Llama 3.3 70B', id:'meta/llama-3.3-70b-instruct', provider:'nvidia'},
    {name:'Llama 3.1 405B', id:'meta/llama-3.1-405b-instruct', provider:'nvidia'},
    {name:'Nemotron 340B', id:'nvidia/nemotron-4-340b-instruct', provider:'nvidia'},
    {name:'GLM-5', id:'z-ai/glm5', provider:'nvidia'},
    {name:'Kimi K2.5', id:'moonshotai/kimi-k2.5', provider:'nvidia'},
    {name:'Mistral Large 2', id:'mistralai/mistral-large-2-instruct', provider:'nvidia'},
  ],
  'Ollama (Local)': []
};
let currentProvider = '', currentModelId = '';

async function loadOllamaStatus() {
  try {
    const r = await fetch('/api/ollama_status');
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
  ALL_MODELS['Ollama (Local)'] = models.map(m => ({name: m, id: m, provider: 'ollama'}));
  renderModelGrid();
}

async function refreshOllama() {
  await loadOllamaStatus();
  const r = await fetch('/api/ollama_models');
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
    if (provName === 'Ollama (Local)') sec.id = 'ollama-section';
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

async function switchModel(provider, modelId, btn) {
  const r = await fetch('/api/switch_model', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider, model: modelId})});
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
    openrouter: 'anthropic/claude-opus-4-6', huggingface: 'Qwen/Qwen3-235B-A22B',
    kimi: 'kimi-k2.5', zai: 'glm-4-plus', minimax: 'MiniMax-Text-01',
    nvidia: 'deepseek-ai/deepseek-v3.2', ollama: 'qwen3:8b'
  };
  document.getElementById('cfg-model').value = presets[p] || '';
}

async function applyModelConfig() {
  const maxTokens = document.getElementById('cfg-max-tokens').value.trim();
  const contextWindow = document.getElementById('cfg-context-window').value.trim();
  try {
    const r = await fetch('/api/model_config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max_tokens: maxTokens || 0, context_window: contextWindow || 0})});
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
    const r = await fetch('/api/model_overrides');
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
  document.getElementById('pmo-model').value = model;
  document.getElementById('pmo-max-tokens').value = maxTokens || '';
  document.getElementById('pmo-context-window').value = contextWindow || '';
}

async function pmoSave() {
  const model = document.getElementById('pmo-model').value.trim();
  if (!model) { addLog('[Web] Per-model override: model name required'); return; }
  const maxTokens = parseInt(document.getElementById('pmo-max-tokens').value) || 0;
  const contextWindow = parseInt(document.getElementById('pmo-context-window').value) || 0;
  try {
    const r = await fetch('/api/model_overrides', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model, max_tokens: maxTokens, context_window: contextWindow})});
    const d = await r.json();
    if (d.ok) {
      addLog(`[Web] Override saved for ${model}: max_tokens=${maxTokens||'global'}, context_window=${contextWindow||'global'}`);
      document.getElementById('pmo-model').value = '';
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
    const r = await fetch('/api/model_overrides', {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model})});
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
  const r = await fetch('/api/browser_cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({command:'navigate', args:{url}})});
  const d = await r.json();
  setBrowserStatus(JSON.stringify(d.result || d.error));
}

async function browserCmd(cmd, extraArgs) {
  setBrowserStatus('Running: ' + cmd + '...');
  try {
    const r = await fetch('/api/browser_cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({command: cmd, args: extraArgs || {}})});
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

// Status
async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('st-uptime').textContent = d.uptime || '--';
    document.getElementById('st-tin').textContent = (d.tokens_in||0).toLocaleString();
    document.getElementById('st-tout').textContent = (d.tokens_out||0).toLocaleString();
    document.getElementById('st-model').textContent = (d.model?.model||'--').split('/').pop().substring(0,14);
    document.getElementById('st-provider').textContent = d.model?.provider || '--';
    document.getElementById('st-ollama-models').textContent = d.ollama?.model_count ?? '--';
    currentModelId = d.model?.model || '';
    currentProvider = d.model?.provider || '';
    document.getElementById('model-badge').textContent = currentModelId.split('/').pop().substring(0,24) || 'No model';
    if (d.version) document.getElementById('version-badge').textContent = 'v' + d.version;
    const pl = document.getElementById('status-plugins-list');
    if (pl && d.plugins) {
      pl.innerHTML = '<div style="font-size:0.8em;color:var(--dim);margin-bottom:8px;letter-spacing:2px">PLUGIN STATUS</div>';
      for (const [name, enabled] of Object.entries(d.plugins)) {
        pl.innerHTML += `<div style="display:flex;align-items:center;gap:10px;padding:6px 10px;background:var(--bg3);border-radius:6px;margin-bottom:6px;font-size:0.83em"><span style="color:${enabled?'var(--green)':'var(--red)'}">${enabled?'●':'○'}</span><span>${name}</span><span style="margin-left:auto;color:var(--dim);font-size:0.75em">${enabled?'ACTIVE':'PAUSED'}</span></div>`;
      }
    }
  } catch(e) {}
}

// Memory
async function loadFileList() {
  try {
    const r = await fetch('/api/files');
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
    const r = await fetch('/api/file?name=' + encodeURIComponent(name));
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
    await fetch('/api/file', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, content})});
    addLog('[Web] Saved: ' + name);
  } catch(e) { alert('Save failed: ' + e.message); }
}

// Logs
function addLog(msg) {
  allLogs.push(msg);
  const filterVal = document.getElementById('log-filter').value || '';
  if (!filterVal || msg.toLowerCase().includes(filterVal.toLowerCase())) {
    const el = document.getElementById('logs-scroll');
    const div = document.createElement('div');
    div.className = 'log-line' + (msg.includes('ERROR')||msg.includes('Error') ? ' err' : msg.includes('✅')||msg.includes('ONLINE') ? ' ok' : msg.includes('⚠️')||msg.includes('WARN') ? ' warn' : '');
    div.textContent = msg;
    el.appendChild(div);
    if (autoScroll) el.scrollTop = 99999;
  }
}

function filterLogs(q2) {
  const el = document.getElementById('logs-scroll');
  el.innerHTML = '';
  allLogs.filter(l => !q2 || l.toLowerCase().includes(q2.toLowerCase())).forEach(l => {
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

    async def handle_chat(self, request):
        """POST /api/chat — send message to the AI and get response.
        Accepts JSON body OR multipart/form-data with file attachments.
        """
        try:
            user_msg = ''
            file_context = ''

            content_type = request.content_type or ''
            if 'multipart/form-data' in content_type:
                # File upload mode
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == 'message':
                        user_msg = (await part.text()).strip()
                    elif part.name == 'files':
                        filename = part.filename or 'unnamed'
                        raw = await part.read(chunk_size=5 * 1024 * 1024)
                        try:
                            text = raw.decode('utf-8', errors='replace')
                        except Exception:
                            text = '[Binary file — could not decode]'
                        # Truncate extremely large files to avoid blowing up context
                        if len(text) > 100000:
                            text = text[:100000] + '\n\n... [truncated — file exceeds 100K characters]'
                        file_context += f"\n\n[Attached file: {filename}]\n---\n{text}\n---\n"
            else:
                # Standard JSON mode
                data = await request.json()
                user_msg = data.get('message', '').strip()

            # Build final message with file contents prepended
            full_msg = user_msg
            if file_context:
                full_msg = file_context.strip() + ('\n\n' + user_msg if user_msg else '')

            if not full_msg:
                return web.json_response({'error': 'No message'}, status=400)

            # Log a clean version (don't dump entire files into terminal)
            if file_context:
                file_count = file_context.count('[Attached file:')
                log_msg = f"[Web] User: {user_msg or '(no text)'} [+{file_count} file(s) attached]"
            else:
                log_msg = f"[Web] User: {user_msg}"
            await self.core.log(log_msg, priority=2)

            response = await self.core.gateway.speak(full_msg)
            await self.core.log(f"[Core] Byte: {response}", priority=2)
            return web.json_response({'response': response})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_status(self, request):
        """GET /api/status — full system status JSON."""
        import time
        uptime = int(time.time() - self.core.start_time)
        plugin_statuses = {}
        for p in self.core.plugins:
            plugin_statuses[p.name] = getattr(p, 'enabled', True)
        ollama_status = {}
        if hasattr(self.core, 'ollama_manager'):
            ollama_status = self.core.ollama_manager.get_status()
        model_status = {}
        if hasattr(self.core, 'model_manager'):
            model_status = {
                'provider': self.core.gateway.llm.provider,
                'model': self.core.gateway.llm.model,
                'mode': self.core.model_manager.current_mode,
            }
        return web.json_response({
            'uptime': uptime,
            'plugins': plugin_statuses,
            'ollama': ollama_status,
            'model': model_status,
            'tokens_in': self.core.gateway.total_tokens_in,
            'tokens_out': self.core.gateway.total_tokens_out,
            'version': self.core.config.get('system', {}).get('version', '0.7.1'),
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
            self.core.gateway.llm.provider = provider
            self.core.gateway.llm.model = model
            if hasattr(self.core, 'model_manager'):
                self.core.model_manager._set_api_key(provider)
            await self.core.log(f"Shifted Model via Web Deck: {model}", priority=2)
            return web.json_response({'ok': True, 'provider': provider, 'model': model})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

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
            # Save to config.yaml
            try:
                import yaml
                cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            except Exception as e:
                pass  # Non-fatal — hash saved in memory
            return web.json_response({'success': True, 'token': h, 'first_run': True})

        if h == self.password_hash:
            return web.json_response({'success': True, 'token': h})
        return web.json_response({'success': False, 'error': 'Invalid passphrase'}, status=401)

    async def handle_setup(self, request):
        """POST /api/setup — first-run configuration: save API keys, passwords, provider, etc."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        import yaml
        cfg = self.core.config
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')

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
            'huggingface': ('apiKey',  'https://api-inference.huggingface.co/v1'),
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

        # Save
        try:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
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
        md_files = ['USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md']
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
        allowed = {'USER.md', 'IDENTITY.md', 'SOUL.md', 'MEMORY.md', 'TOOLS.md'}
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
        # Persist to config.yaml
        try:
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            return web.json_response({'ok': False, 'error': str(e)})
        return web.json_response({'ok': True, 'max_tokens': cfg['models'].get('max_tokens', 0), 'context_window': cfg['models'].get('context_window', 0)})

    def _save_config(self, cfg):
        """Write config dict to config.yaml."""
        import yaml
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

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
        if token != self.password_hash:
            await ws.close(code=4001)
            return ws

        class WebAdapter:
            def __init__(self, ws):
                self.ws = ws
            def write(self, data):
                asyncio.create_task(self.ws.send_str(data.decode()))
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
        """GET /api/logs — return last N system log lines for UI restore on page refresh."""
        try:
            limit = int(request.query.get('limit', '200'))
            logs_dir = self.core.config.get('paths', {}).get('logs', './logs')
            log_file = os.path.join(logs_dir, 'system_log.txt')
            lines = []
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                lines = [l.rstrip('\n') for l in lines[-limit:]]
            return web.json_response({'logs': lines})
        except Exception as e:
            return web.json_response({'logs': [], 'error': str(e)})

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
            for f in ['MEMORY.md', 'USER.md', 'SOUL.md', 'IDENTITY.md', 'TOOLS.md', 'HEARTBEAT.md']:
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

    async def run(self):
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        # await self.core.log(f"Galactic Web Deck Active at http://{self.host}:{self.port}", priority=1)
