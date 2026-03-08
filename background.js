/**
 * Galactic Browser - Background Service Worker
 * Maintains WebSocket connection to Galactic AI and dispatches browser commands.
 * Refactored for resource management and stability.
 */

/* ─── State ─────────────────────────────────────────────────────────────── */

let ws = null;
let connected = false;
let connecting = false;
let authFailed = false;
let reconnectTimer = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
const BASE_WS_URL = 'ws://127.0.0.1:17789/ws/chrome_bridge';

let currentToken = null;

/* Per-tab debugger buffers */
const consoleBuffers = new Map();   // tabId -> [{level, text, timestamp}]
const networkBuffers = new Map();   // tabId -> [{method, url, status, type}]

class DebuggerManager {
  constructor() {
    this.activeAttachments = new Map(); // tabId -> Set<'dom'|'console'|'network'|'emulation'>

    chrome.debugger.onDetach.addListener((source) => {
      this.activeAttachments.delete(source.tabId);
    });

    chrome.tabs.onRemoved.addListener((tabId) => {
      this.activeAttachments.delete(tabId);
      consoleBuffers.delete(tabId);
      networkBuffers.delete(tabId);
    });
  }

  async ensure(tabId, feature) {
    if (!this.activeAttachments.has(tabId)) {
      this.activeAttachments.set(tabId, new Set());
    }
    const attachments = this.activeAttachments.get(tabId);
    if (attachments.has(feature)) return;

    if (attachments.size === 0) {
      await chrome.debugger.attach({ tabId }, '1.3');
    }

    if (feature === 'dom') await chrome.debugger.sendCommand({ tabId }, 'DOM.enable');
    else if (feature === 'console') await chrome.debugger.sendCommand({ tabId }, 'Runtime.enable');
    else if (feature === 'network') await chrome.debugger.sendCommand({ tabId }, 'Network.enable');

    attachments.add(feature);
  }
}

const debuggerManager = new DebuggerManager();

/* ─── WebSocket Connection ──────────────────────────────────────────────── */

function buildWsUrl(token) {
  return `${BASE_WS_URL}?token=${encodeURIComponent(token)}`;
}

function connect(token) {
  if (ws) {
    try { ws.close(); } catch (_) { /* ignore */ }
  }
  currentToken = token;
  authFailed = false;
  connecting = true;
  clearTimeout(reconnectTimer);
  reconnectDelay = 1000;

  chrome.storage.local.set({ galactic_auth_failed: false });
  updateStoredStatus();

  const url = buildWsUrl(token);
  ws = new WebSocket(url);

  ws.onopen = () => {
    connected = true;
    connecting = false;
    reconnectDelay = 1000;
    updateStoredStatus();
    wsSend({ type: 'hello', capabilities: ['chrome', 'tabs', 'network', 'console'] });
    console.log('[Galactic] WebSocket connected');
  };

  ws.onmessage = async (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch (_) { return; }

    if (msg.type === 'ping') {
      wsSend({ type: 'pong' });
      return;
    }

    if (msg.type === 'command' && msg.id && msg.command) {
      try {
        console.log(`[Galactic] Command received: ${msg.command}`, msg.args || {});
        const result = await handleCommand(msg.id, msg.command, msg.args || {});
        if (result && result.error) {
          console.error(`[Galactic] Command error [${msg.command}]:`, result.error);
        }
        wsSend({ type: 'result', id: msg.id, data: result });
      } catch (err) {
        console.error(`[Galactic] Command exception [${msg.command}]:`, err);
        wsSend({ type: 'result', id: msg.id, data: { status: 'error', message: err.message || String(err) } });
      }
    }
  };

  ws.onclose = (event) => {
    connected = false;
    connecting = false;
    if (event.code === 4001) {
      authFailed = true;
      currentToken = null;
      updateStoredStatus();
    } else {
      authFailed = false;
      updateStoredStatus();
      scheduleReconnect();
    }
  };
}

function disconnect() {
  clearTimeout(reconnectTimer);
  currentToken = null;
  authFailed = false;
  connecting = false;
  if (ws) {
    try { ws.close(); } catch (_) { }
    ws = null;
  }
  connected = false;
  updateStoredStatus();
}

function scheduleReconnect() {
  if (!currentToken) return;
  reconnectTimer = setTimeout(() => {
    connect(currentToken);
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
  }, reconnectDelay);
}

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function updateStoredStatus() {
  chrome.storage.local.set({
    galactic_connected: connected,
    galactic_connecting: connecting,
    galactic_auth_failed: authFailed,
    galactic_token: currentToken || ''
  });
}

/* ─── Service Worker Keepalive ─── */

chrome.alarms.create('galactic_keepalive', { periodInMinutes: 0.4 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'galactic_keepalive') {
    chrome.storage.local.get(['galactic_token', 'galactic_auth_failed'], (data) => {
      if (data.galactic_auth_failed) return;
      if (!connected && !connecting && data.galactic_token) {
        if (!currentToken) currentToken = data.galactic_token;
        connect(currentToken);
      }
    });
  }
});

/* ─── Auto-reconnect on startup ─────────────────────────────────────────── */

chrome.storage.local.get(['galactic_token', 'galactic_auth_failed'], (data) => {
  if (data.galactic_token && !data.galactic_auth_failed) {
    currentToken = data.galactic_token;
    connect(currentToken);
  }
});

/* ─── Command Router ────────────────────────────────────────────────────── */

async function handleCommand(id, command, args) {
  // Higher-order wrapper for tab validation
  const tabId = await getTargetTabId(args);
  if (!tabId && command !== 'tabs_list' && command !== 'tabs_create') return { error: 'No active tab' };

  switch (command) {
    case 'screenshot': return await cmdScreenshot(tabId, args);
    case 'navigate': return await cmdNavigate(tabId, args);
    case 'read_page': return await sendToContent(tabId, 'snapshot', args);
    case 'find_element': return await sendToContent(tabId, 'find', args);
    case 'wait_for': return await sendToContent(tabId, 'wait_for', args);
    case 'click': return await sendToContent(tabId, 'click', args);
    case 'type':
    case 'type_text': return await sendToContent(tabId, 'type', args);
    case 'scroll':
    case 'scroll_page': return await sendToContent(tabId, 'scroll', args);
    case 'form_input': return await sendToContent(tabId, 'form_input', args);
    case 'execute_js': return await cmdExecuteJS(tabId, args);
    case 'get_page_text':
    case 'get_text': return await sendToContent(tabId, 'get_text', args);
    case 'get_dom': return await sendToContent(tabId, 'get_dom', args);
    case 'show_status': return await sendToContent(tabId, 'show_status', args);
    case 'hide_status': return await sendToContent(tabId, 'hide_status', args);
    case 'tabs_list': return await cmdTabsList(args);
    case 'tabs_create': return await cmdTabsCreate(args);
    case 'key_press': return await sendToContent(tabId, 'key_press', args);
    case 'read_console': return await cmdReadConsole(tabId, args);
    case 'read_network': return await cmdReadNetwork(tabId, args);
    case 'get_network_body': return await cmdGetNetworkBody(tabId, args);
    case 'hover': return await sendToContent(tabId, 'hover', args);
    case 'zoom': return await cmdZoom(tabId, args);
    case 'drag': return await sendToContent(tabId, 'drag', args);
    case 'right_click': return await sendToContent(tabId, 'right_click', args);
    case 'triple_click': return await sendToContent(tabId, 'triple_click', args);
    case 'upload_file': return await cmdUploadFile(tabId, args);
    case 'resize_window': return await cmdResizeWindow(tabId, args);
    default: return { error: `Unknown command: ${command}` };
  }
}

/* ─── Helpers ───────────────────────────────────────────────────────────── */

async function getTargetTabId(args) {
  if (args?.tab_id) return args.tab_id;
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0]?.id;
}

async function sendToContent(tabId, command, args) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: 'galactic', command, args });
  } catch (_) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    await new Promise(r => setTimeout(r, 100));
    return await chrome.tabs.sendMessage(tabId, { type: 'galactic', command, args });
  }
}

/* ─── Command Implementations ───────────────────────────────────────────── */

async function cmdScreenshot(tabId, args) {
  const tab = await chrome.tabs.get(tabId);
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tabId, { active: true });
  await new Promise(r => setTimeout(r, 150));
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: args?.quality || 80 });
  return { status: 'success', image_b64: dataUrl };
}

async function cmdNavigate(tabId, args) {
  const url = args?.url;
  if (!url) return { error: 'No url provided' };
  if (url === 'back') { await chrome.tabs.goBack(tabId); return { status: 'success', action: 'back' }; }
  if (url === 'forward') { await chrome.tabs.goForward(tabId); return { status: 'success', action: 'forward' }; }
  await chrome.tabs.update(tabId, { url });
  return { status: 'success', url };
}

async function cmdExecuteJS(tabId, args) {
  const script = args?.script || args?.code || '';
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: (code) => new Function(code)(),
      args: [script]
    });
    return { status: 'success', result: results?.[0]?.result };
  } catch (err) {
    return { status: 'error', error: err.message };
  }
}

async function cmdTabsList(_args) {
  const tabs = await chrome.tabs.query({});
  return { status: 'success', tabs: tabs.map(t => ({ id: t.id, title: t.title, url: t.url, active: t.active })) };
}

async function cmdTabsCreate(args) {
  const tab = await chrome.tabs.create({ url: args?.url || 'about:blank' });
  return { status: 'success', id: tab.id, url: tab.url };
}

async function cmdReadConsole(tabId, args) {
  await debuggerManager.ensure(tabId, 'console');
  let messages = consoleBuffers.get(tabId) || [];
  if (args?.pattern) {
    try {
      const re = new RegExp(args.pattern, 'i');
      messages = messages.filter(m => re.test(m.text));
    } catch (_) { }
  }
  if (args?.only_errors) messages = messages.filter(m => m.level === 'error' || m.level === 'exception');
  const limit = args?.limit || 100;
  if (args?.clear) consoleBuffers.set(tabId, []);
  return { messages: messages.slice(-limit) };
}

async function cmdReadNetwork(tabId, args) {
  await debuggerManager.ensure(tabId, 'network');
  let requests = networkBuffers.get(tabId) || [];
  if (args?.url_pattern) requests = requests.filter(r => r.url.includes(args.url_pattern));
  const limit = args?.limit || 100;
  if (args?.clear) networkBuffers.set(tabId, []);
  return { requests: requests.slice(-limit) };
}

async function cmdGetNetworkBody(tabId, args) {
  if (!args?.request_id) return { error: 'request_id is required' };
  try {
    await debuggerManager.ensure(tabId, 'network');
    const result = await chrome.debugger.sendCommand({ tabId }, 'Network.getResponseBody', { requestId: args.request_id });
    return { status: 'success', body: result.body, base64Encoded: result.base64Encoded };
  } catch (e) { return { error: `Failed: ${e.message}` }; }
}

async function cmdUploadFile(tabId, args) {
  const filePath = args?.file_path;
  if (!filePath) return { error: 'file_path required' };
  let selector = args?.selector || null;
  if (!selector && args?.ref) {
    const refResult = await sendToContent(tabId, 'resolve_ref', { ref: args.ref });
    selector = refResult?.selector || null;
  }
  if (!selector) return { error: 'Selector required' };

  await debuggerManager.ensure(tabId, 'dom');
  const { root } = await chrome.debugger.sendCommand({ tabId }, 'DOM.getDocument', { depth: 0 });
  const { nodeId } = await chrome.debugger.sendCommand({ tabId }, 'DOM.querySelector', { nodeId: root.nodeId, selector });
  await chrome.debugger.sendCommand({ tabId }, 'DOM.setFileInputFiles', { nodeId, files: [filePath] });
  return { status: 'success', file_path: filePath };
}

async function cmdResizeWindow(tabId, args) {
  let width, height;
  const PRESETS = { mobile: [375, 812], tablet: [768, 1024], desktop: [1280, 800] };
  if (args.preset) [width, height] = PRESETS[args.preset];
  else { width = parseInt(args.width); height = parseInt(args.height); }

  await debuggerManager.ensure(tabId, 'emulation');
  await chrome.debugger.sendCommand({ tabId }, 'Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 0, mobile: false });
  return { status: 'success', width, height };
}

async function cmdZoom(tabId, args) {
  const region = args?.region;
  const tab = await chrome.tabs.get(tabId);
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tabId, { active: true });
  await new Promise(r => setTimeout(r, 150));

  const fullDataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 85 });
  const [x0, y0, x1, y1] = region;
  const width = x1 - x0, height = y1 - y0;

  const resp = await fetch(fullDataUrl);
  const blob = await resp.blob();
  const bitmap = await createImageBitmap(blob);
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bitmap, x0, y0, width, height, 0, 0, width, height);
  const croppedBlob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
  const reader = new FileReader();

  return new Promise(resolve => {
    reader.onloadend = () => resolve({ status: 'success', image_b64: reader.result.split(',')[1] });
    reader.onerror = () => resolve({ status: 'error', error: 'Crop failed' });
    reader.readAsDataURL(croppedBlob);
  });
}

/* ─── Event Listeners ───────────────────────────────────────────────────── */

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;
  if (method === 'Runtime.consoleAPICalled') {
    const buffer = consoleBuffers.get(tabId) || [];
    buffer.push({ level: params.type || 'log', text: (params.args || []).map(a => a.value || a.description || '').join(' '), timestamp: Date.now() });
    if (buffer.length > 500) buffer.shift();
    consoleBuffers.set(tabId, buffer);
  } else if (method === 'Network.requestWillBeSent') {
    const buffer = networkBuffers.get(tabId) || [];
    buffer.push({ _requestId: params.requestId, method: params.request.method, url: params.request.url, status: 0 });
    if (buffer.length > 500) buffer.shift();
    networkBuffers.set(tabId, buffer);
  } else if (method === 'Network.responseReceived') {
    const buffer = networkBuffers.get(tabId) || [];
    const entry = buffer.find(r => r._requestId === params.requestId);
    if (entry) entry.status = params.response.status;
    networkBuffers.set(tabId, buffer);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'connect') connect(msg.token);
  else if (msg.type === 'disconnect') disconnect();
  else if (msg.type === 'getStatus') sendResponse({ connected, connecting, authFailed, wsUrl: BASE_WS_URL });
  return true;
});
