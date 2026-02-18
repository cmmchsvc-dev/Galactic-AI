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
    <p>AUTOMATION SUITE v0.6.0</p>
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
  <div style="background:var(--bg2);border:1px solid var(--cyan);border-radius:20px;width:min(680px,96vw);margin:auto">
    <!-- Header -->
    <div style="padding:28px 32px 0;text-align:center">
      <div style="font-size:2.5em;margin-bottom:8px">⬡</div>
      <div style="font-size:1.3em;font-weight:700;letter-spacing:4px;color:var(--cyan)">GALACTIC AI SETUP</div>
      <div style="color:var(--dim);font-size:0.82em;margin-top:4px">Initial configuration wizard — takes about 2 minutes</div>
    </div>
    <!-- Progress bar -->
    <div style="margin:20px 32px 0;height:3px;background:var(--bg3);border-radius:2px">
      <div id="sw-progress" style="height:100%;background:linear-gradient(90deg,var(--cyan),var(--pink));border-radius:2px;width:20%;transition:width .4s"></div>
    </div>

    <!-- Step 1: Primary Model Provider -->
    <div id="sw-step-1" style="padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:18px">STEP 1 OF 5 — PRIMARY AI PROVIDER</div>
      <div style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Choose your primary AI provider:</label>
        <select id="sw-provider" onchange="swUpdateModelHint()" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
          <option value="google">🌐 Google Gemini (Best overall — free tier available)</option>
          <option value="anthropic">🤖 Anthropic Claude (Best for reasoning & code)</option>
          <option value="xai">⚡ xAI Grok (Fast &amp; capable)</option>
          <option value="nvidia">🚀 NVIDIA AI (Large model access)</option>
          <option value="ollama">🦙 Ollama Local (100% private, no API key needed)</option>
        </select>
      </div>
      <div style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Model ID <span style="color:var(--dim)">(leave blank for default)</span>:</label>
        <input id="sw-model" type="text" placeholder="gemini-2.5-flash" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
      </div>
      <!-- Provider-specific fields -->
      <div id="sw-apikey-wrap" style="margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">API Key for selected provider:</label>
        <input id="sw-apikey" type="password" placeholder="Paste your API key here" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
        <div style="margin-top:6px;font-size:0.72em;color:var(--dim)">
          Google: <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--cyan)">aistudio.google.com/apikey</a> &nbsp;|&nbsp;
          Anthropic: <a href="https://console.anthropic.com/keys" target="_blank" style="color:var(--cyan)">console.anthropic.com/keys</a> &nbsp;|&nbsp;
          xAI: <a href="https://console.x.ai" target="_blank" style="color:var(--cyan)">console.x.ai</a>
        </div>
      </div>
      <div id="sw-ollama-wrap" style="display:none;margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">Ollama Server URL:</label>
        <input id="sw-ollama-url" type="text" placeholder="http://127.0.0.1:11434/v1" value="http://127.0.0.1:11434/v1" style="width:100%;padding:10px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:0.9em">
        <div style="margin-top:8px;padding:10px 14px;background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.2);border-radius:6px;font-size:0.78em;color:var(--dim)">
          💡 Ollama must be running locally. Install from <a href="https://ollama.com" target="_blank" style="color:var(--cyan)">ollama.com</a> then run <code style="background:var(--bg3);padding:2px 6px;border-radius:3px">ollama pull qwen3:8b</code>
        </div>
      </div>
      <div id="sw-nvidia-wrap" style="display:none;margin-bottom:18px">
        <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:6px">NVIDIA AI Foundation API Keys <span style="color:var(--dim)">(get from <a href="https://build.nvidia.com" target="_blank" style="color:var(--cyan)">build.nvidia.com</a>)</span>:</label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div><label style="font-size:0.72em;color:var(--dim)">DeepSeek key</label><input id="sw-nvidia-ds-key" type="password" placeholder="nvapi-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.82em;margin-top:3px"></div>
          <div><label style="font-size:0.72em;color:var(--dim)">Qwen key</label><input id="sw-nvidia-qw-key" type="password" placeholder="nvapi-..." style="width:100%;padding:8px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:0.82em;margin-top:3px"></div>
        </div>
      </div>
      <button onclick="swNextStep(1,2)" style="width:100%;padding:12px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
    </div>

    <!-- Step 2: Additional API Keys -->
    <div id="sw-step-2" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:18px">STEP 2 OF 5 — ADDITIONAL API KEYS <span style="color:var(--dim)">(optional — add more providers)</span></div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">🌐 Google Gemini API Key <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--cyan);font-size:0.85em">[get key]</a></label>
          <input id="sw-google-key" type="password" placeholder="AIzaSy..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">🤖 Anthropic Claude API Key <a href="https://console.anthropic.com/keys" target="_blank" style="color:var(--cyan);font-size:0.85em">[get key]</a></label>
          <input id="sw-anthropic-key" type="password" placeholder="sk-ant-..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
        <div>
          <label style="font-size:0.8em;color:var(--dim);display:block;margin-bottom:5px">⚡ xAI Grok API Key <a href="https://console.x.ai" target="_blank" style="color:var(--cyan);font-size:0.85em">[get key]</a></label>
          <input id="sw-xai-key" type="password" placeholder="xai-..." style="width:100%;padding:9px 13px;background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:0.88em">
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:22px">
        <button onclick="swNextStep(2,1)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
        <button onclick="swNextStep(2,3)" style="flex:1;padding:11px;background:linear-gradient(135deg,var(--cyan),var(--pink));border:none;border-radius:10px;color:#000;font-weight:700;cursor:pointer;font-size:0.95em">Next →</button>
      </div>
    </div>

    <!-- Step 3: Telegram (optional) -->
    <div id="sw-step-3" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 3 OF 5 — TELEGRAM BOT <span style="color:var(--dim)">(optional)</span></div>
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
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 4 OF 5 — SECURITY</div>
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

    <!-- Step 5: Review & Save -->
    <div id="sw-step-5" style="display:none;padding:28px 32px">
      <div style="font-size:0.7em;letter-spacing:3px;color:var(--cyan);margin-bottom:4px">STEP 5 OF 5 — REVIEW &amp; LAUNCH</div>
      <div style="color:var(--dim);font-size:0.78em;margin-bottom:20px">Everything looks good? Hit Save &amp; Launch to start using Galactic AI.</div>
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:16px;font-size:0.82em;line-height:2;margin-bottom:20px">
        <div>Provider: <span id="sw-review-provider" style="color:var(--cyan)">—</span></div>
        <div>Model: <span id="sw-review-model" style="color:var(--cyan)">—</span></div>
        <div>Web password: <span id="sw-review-pw" style="color:var(--green)">—</span></div>
        <div>Telegram: <span id="sw-review-tg" style="color:var(--dim)">—</span></div>
      </div>
      <div style="display:flex;gap:10px">
        <button onclick="swNextStep(5,4)" style="flex:0.4;padding:11px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;font-size:0.9em">← Back</button>
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
  <div id='ollama-pill' onclick='switchTab("models")'>
    <div class="status-dot" id="ollama-dot"></div>
    <span id="ollama-label">Ollama</span>
  </div>
  <div id='model-badge' onclick='switchTab("models")'>Loading...</div>
  <div class="spacer"></div>
  <div id="token-counter">↑0 ↓0 tokens</div>
  <button class="topbar-btn" onclick="clearChat()">🗑 Clear</button>
  <button class="topbar-btn" onclick="switchTab('logs')">📋 Logs</button>
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
          <div id="chat-input-row" style="display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--border);flex-shrink:0;background:var(--bg2)">
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
              <option value="nvidia">NVIDIA</option>
              <option value="xai">xAI</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
          <div class="model-config-row">
            <label>Model ID</label>
            <input id="cfg-model" type="text" placeholder="model-id">
          </div>
          <div style="margin-top:8px">
            <button class="btn primary" onclick="applyModelOverride()">Apply Model</button>
          </div>
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

function swUpdateModelHint() {
  const prov = document.getElementById('sw-provider').value;
  const hints = {
    google: 'gemini-2.5-flash',
    anthropic: 'claude-sonnet-4-5',
    xai: 'grok-4',
    nvidia: 'deepseek-ai/deepseek-v3.2',
    ollama: 'qwen3:8b (make sure Ollama is running)'
  };
  const inp = document.getElementById('sw-model');
  if (inp && hints[prov]) inp.placeholder = hints[prov];
  // Show/hide API key fields
  const keyField = document.getElementById('sw-apikey-wrap');
  if (keyField) keyField.style.display = prov === 'ollama' ? 'none' : '';
  const nvidiaWrap = document.getElementById('sw-nvidia-wrap');
  if (nvidiaWrap) nvidiaWrap.style.display = prov === 'nvidia' ? '' : 'none';
  const ollamaWrap = document.getElementById('sw-ollama-wrap');
  if (ollamaWrap) ollamaWrap.style.display = prov === 'ollama' ? '' : 'none';
}

function swNextStep(currentStep, nextStep) {
  document.getElementById('sw-step-' + currentStep).style.display = 'none';
  document.getElementById('sw-step-' + nextStep).style.display = '';
  document.getElementById('sw-progress').style.width = (nextStep * 20) + '%';
}

async function swSave() {
  const btn = document.getElementById('sw-save-btn');
  btn.textContent = 'Saving...';
  btn.disabled = true;

  const prov = document.getElementById('sw-provider').value;
  const modelVal = document.getElementById('sw-model').value.trim();
  const modelFinal = modelVal || document.getElementById('sw-model').placeholder.split(' ')[0];

  const payload = {
    provider: prov,
    model: modelFinal,
    api_key: (document.getElementById('sw-apikey') || {value:''}).value.trim(),
    password: (document.getElementById('sw-pw') || {value:''}).value.trim(),
    system_name: (document.getElementById('sw-sysname') || {value:'Galactic AI'}).value.trim() || 'Galactic AI',
    // Per-provider keys
    google_key: (document.getElementById('sw-google-key') || {value:''}).value.trim(),
    anthropic_key: (document.getElementById('sw-anthropic-key') || {value:''}).value.trim(),
    xai_key: (document.getElementById('sw-xai-key') || {value:''}).value.trim(),
    nvidia_deepseek_key: (document.getElementById('sw-nvidia-ds-key') || {value:''}).value.trim(),
    nvidia_qwen_key: (document.getElementById('sw-nvidia-qw-key') || {value:''}).value.trim(),
    ollama_url: (document.getElementById('sw-ollama-url') || {value:'http://127.0.0.1:11434/v1'}).value.trim() || 'http://127.0.0.1:11434/v1',
    telegram_token: (document.getElementById('sw-tg-token') || {value:''}).value.trim(),
    telegram_chat_id: (document.getElementById('sw-tg-chat') || {value:''}).value.trim(),
  };

  // If primary provider is one of the named ones, copy its key to api_key
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
  document.getElementById('sw-review-provider').textContent = prov;
  document.getElementById('sw-review-model').textContent = modelVal;
  document.getElementById('sw-review-pw').textContent = pw ? '✓ Set' : 'None (open access)';
  document.getElementById('sw-review-tg').textContent = tgToken ? '✓ Configured' : 'Not configured';
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
      sb.textContent += p.data;
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
  sb.style.display = 'none'; sb.textContent = '';
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = `<div class="bubble">${escHtml(text)}</div><div class="meta">Byte • now</div>`;
  log.appendChild(div);
  if (autoScroll) log.scrollTop = 99999;
}

function appendUserMsg(text) {
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="bubble">${escHtml(text)}</div><div class="meta">You • now</div>`;
  log.appendChild(div);
  if (autoScroll) log.scrollTop = 99999;
}

async function sendChatMain() {
  const inp = document.getElementById('chat-input-main');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = ''; inp.style.height = '44px';
  appendUserMsg(msg);
  document.getElementById('send-btn-main').disabled = true;
  document.getElementById('send-btn-main').textContent = '...';
  const stream = document.getElementById('stream-bubble');
  stream.style.display = 'block'; stream.textContent = '';
  httpChatPending = true;
  try {
    const r = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: msg})});
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
    {name:'Gemini 3 Pro 🪾 [LATEST]', id:'gemini-3-pro-preview', provider:'google'},
    {name:'Gemini 2.5 Pro', id:'gemini-2.5-pro', provider:'google'},
    {name:'Gemini 2.0 Flash', id:'gemini-2.0-flash', provider:'google'},
  ],
  'Anthropic': [
    {name:'Claude Opus 4.6 🏆 [LATEST]', id:'claude-opus-4-6', provider:'anthropic'},
    {name:'Claude Sonnet 4.5', id:'claude-sonnet-4-5', provider:'anthropic'},
    {name:'Claude 3.7 Sonnet', id:'claude-3-7-sonnet-20250219', provider:'anthropic'},
    {name:'Claude 3.5 Sonnet', id:'claude-3-5-sonnet-20241022', provider:'anthropic'},
    {name:'Claude 3.5 Haiku ⚡', id:'claude-3-5-haiku-20241022', provider:'anthropic'},
    {name:'Claude 3 Opus', id:'claude-3-opus-20240229', provider:'anthropic'},
  ],
  'NVIDIA': [
    {name:'DeepSeek V3.2 🚀 [TITAN]', id:'deepseek-ai/deepseek-v3.2', provider:'nvidia'},
    {name:'Qwen3 Coder 480B 🪾', id:'qwen/qwen3-coder-480b-a35b-instruct', provider:'nvidia'},
    {name:'Llama 3.3 70B', id:'meta/llama-3.3-70b-instruct', provider:'nvidia'},
    {name:'Llama 3.1 405B', id:'meta/llama-3.1-405b-instruct', provider:'nvidia'},
    {name:'Nemotron 340B', id:'nvidia/nemotron-4-340b-instruct', provider:'nvidia'},
    {name:'GLM-5', id:'z-ai/glm5', provider:'nvidia'},
    {name:'Kimi K2.5', id:'moonshotai/kimi-k2.5', provider:'nvidia'},
    {name:'Mistral Large 2', id:'mistralai/mistral-large-2-instruct', provider:'nvidia'},
  ],
  'xAI': [
    {name:'Grok 4 🧠 [LATEST]', id:'grok-4', provider:'xai'},
    {name:'Grok 4 Fast ⚡', id:'grok-4-fast', provider:'xai'},
    {name:'Grok 3', id:'grok-3', provider:'xai'},
    {name:'Grok 3 Mini', id:'grok-3-mini', provider:'xai'},
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
    nvidia: 'deepseek-ai/deepseek-v3.2', xai: 'grok-4', ollama: 'qwen3:8b'
  };
  document.getElementById('cfg-model').value = presets[p] || '';
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
  if (name === 'models') loadOllamaStatus();
  if (name === 'plugins') loadPlugins();
}

// Utility
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
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
        """POST /api/chat — send message to the AI and get response."""
        try:
            data = await request.json()
            user_msg = data.get('message', '')
            if not user_msg:
                return web.json_response({'error': 'No message'}, status=400)
            await self.core.log(f"[Web] User: {user_msg}", priority=2)
            response = await self.core.gateway.speak(user_msg)
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

        for prov in ['google', 'anthropic', 'xai', 'ollama']:
            key = data.get(f'{prov}_key', '')
            if key:
                if prov not in cfg['providers']:
                    cfg['providers'][prov] = {}
                cfg['providers'][prov]['apiKey'] = key

        # NVIDIA keys
        nv_keys = {}
        for slot in ['deepseek', 'qwen', 'glm', 'kimi', 'stepfun']:
            k = data.get(f'nvidia_{slot}_key', '')
            if k:
                nv_keys[slot] = k
        if nv_keys:
            if 'nvidia' not in cfg['providers']:
                cfg['providers']['nvidia'] = {}
            cfg['providers']['nvidia']['keys'] = nv_keys
            cfg['providers']['nvidia']['baseUrl'] = 'https://integrate.api.nvidia.com/v1'

        # Ollama URL
        ollama_url = data.get('ollama_url', '')
        if ollama_url:
            if 'ollama' not in cfg['providers']:
                cfg['providers']['ollama'] = {}
            cfg['providers']['ollama']['baseUrl'] = ollama_url

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

    async def handle_list_files(self, request):
        """List workspace files"""
        workspace = self.core.config['paths']['workspace']
        files = []
        for f in ['MEMORY.md', 'USER.md', 'SOUL.md', 'IDENTITY.md', 'TOOLS.md', 'HEARTBEAT.md']:
            path = os.path.join(workspace, f)
            if os.path.exists(path):
                files.append({'name': f, 'size': os.path.getsize(path)})
        return web.json_response({'files': files})
    
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
