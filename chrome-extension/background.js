/**
 * Galactic Browser - Background Service Worker
 * Maintains WebSocket connection to Galactic AI and dispatches browser commands.
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
const debuggerAttached = new Map(); // tabId -> Set<'console'|'network'>

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

  updateStoredStatus();

  const url = buildWsUrl(token);
  ws = new WebSocket(url);

  ws.onopen = () => {
    connected = true;
    connecting = false;
    reconnectDelay = 1000;
    updateStoredStatus();
    /* Send hello so ChromeBridge marks itself as fully connected */
    wsSend({ type: 'hello', capabilities: ['chrome', 'tabs', 'network', 'console'] });
    console.log('[Galactic] WebSocket connected');
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }

    /* Keepalive ping/pong */
    if (msg.type === 'ping') {
      wsSend({ type: 'pong' });
      return;
    }

    /* Command dispatch */
    if (msg.type === 'command' && msg.id && msg.command) {
      try {
        const result = await handleCommand(msg.id, msg.command, msg.args || {});
        /* Use 'data' key — matches what ChromeBridge.handle_ws_message expects */
        wsSend({ type: 'result', id: msg.id, data: result });
      } catch (err) {
        wsSend({ type: 'result', id: msg.id, data: { status: 'error', message: err.message || String(err) } });
      }
    }
  };

  ws.onerror = (err) => {
    console.warn('[Galactic] WebSocket error', err);
  };

  ws.onclose = (event) => {
    connected = false;
    connecting = false;

    if (event.code === 4001) {
      /* Authentication failure — wrong password. Stop reconnecting. */
      authFailed = true;
      currentToken = null;
      updateStoredStatus();
      console.log('[Galactic] Auth failed — wrong password (code 4001)');
    } else {
      /* Normal disconnect or server restart — schedule reconnect */
      authFailed = false;
      updateStoredStatus();
      console.log('[Galactic] WebSocket closed, scheduling reconnect');
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
    try { ws.close(); } catch (_) { /* ignore */ }
    ws = null;
  }
  connected = false;
  updateStoredStatus();
}

function scheduleReconnect() {
  if (!currentToken) return;
  reconnectTimer = setTimeout(() => {
    console.log(`[Galactic] Reconnecting (delay=${reconnectDelay}ms)...`);
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

/* ─── Service Worker Keepalive (prevents Chrome from killing idle SW) ─── */

/* Repeating alarm every ~25 seconds keeps the service worker alive and
   re-establishes the connection if it dropped while the SW was idle. */
chrome.alarms.create('galactic_keepalive', { periodInMinutes: 0.4 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'galactic_keepalive') {
    /* Re-read token from storage in case this is a fresh SW invocation */
    chrome.storage.local.get(['galactic_token', 'galactic_auth_failed'], (data) => {
      if (data.galactic_auth_failed) return; /* Don't retry bad password */
      if (!connected && !connecting && data.galactic_token) {
        if (!currentToken) currentToken = data.galactic_token;
        console.log('[Galactic] Keepalive: reconnecting after SW wake...');
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
  switch (command) {
    case 'screenshot':    return await cmdScreenshot(args);
    case 'navigate':      return await cmdNavigate(args);
    case 'read_page':     return await cmdReadPage(args);
    case 'find_element':  return await cmdFindElement(args);
    case 'click':         return await cmdClick(args);
    case 'type':          return await cmdType(args);
    case 'scroll':        return await cmdScroll(args);
    case 'form_input':    return await cmdFormInput(args);
    case 'execute_js':    return await cmdExecuteJS(args);
    case 'get_page_text': return await cmdGetPageText(args);
    case 'tabs_list':     return await cmdTabsList(args);
    case 'tabs_create':   return await cmdTabsCreate(args);
    case 'key_press':     return await cmdKeyPress(args);
    case 'read_console':  return await cmdReadConsole(args);
    case 'read_network':  return await cmdReadNetwork(args);
    case 'hover':         return await cmdHover(args);
    case 'zoom':          return await cmdZoom(args);
    case 'drag':          return await cmdDrag(args);
    default:              return { error: `Unknown command: ${command}` };
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
    const response = await chrome.tabs.sendMessage(tabId, {
      type: 'galactic', command, args
    });
    return response?.result !== undefined ? response.result : response;
  } catch (_) {
    /* Content script not injected yet; inject and retry */
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content.js']
    });
    /* Small delay for script initialization */
    await new Promise(r => setTimeout(r, 100));
    const response = await chrome.tabs.sendMessage(tabId, {
      type: 'galactic', command, args
    });
    return response?.result !== undefined ? response.result : response;
  }
}

/* ─── Command Implementations ───────────────────────────────────────────── */

async function cmdScreenshot(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };

  /* Ensure the tab is in focus for captureVisibleTab */
  const tab = await chrome.tabs.get(tabId);
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tabId, { active: true });

  /* Brief delay for rendering */
  await new Promise(r => setTimeout(r, 150));

  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: 'jpeg',
    quality: args?.quality || 80
  });
  return { status: 'success', image_b64: dataUrl };
}

async function cmdNavigate(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };

  const url = args?.url;
  if (!url) return { error: 'No url provided' };

  if (url === 'back') {
    await chrome.tabs.goBack(tabId);
    return { status: 'success', action: 'back' };
  }
  if (url === 'forward') {
    await chrome.tabs.goForward(tabId);
    return { status: 'success', action: 'forward' };
  }

  const updatedTab = await chrome.tabs.update(tabId, { url });
  return { status: 'success', url: updatedTab.url || url };
}

async function cmdReadPage(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'snapshot', args);
}

async function cmdFindElement(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'find', args);
}

async function cmdClick(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'click', args);
}

async function cmdType(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'type', args);
}

async function cmdScroll(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'scroll', args);
}

async function cmdFormInput(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'form_input', args);
}

async function cmdExecuteJS(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  const script = args?.script || args?.code || '';
  if (!script) return { error: 'No script provided' };

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: (code) => {
        /* Execute the provided code string in the page's main world */
        return new Function(code)();
      },
      args: [script]
    });
    const value = results?.[0]?.result;
    return { status: 'success', result: value };
  } catch (err) {
    return { status: 'error', error: err.message };
  }
}

async function cmdGetPageText(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'get_text', args);
}

async function cmdTabsList(_args) {
  const tabs = await chrome.tabs.query({});
  return {
    status: 'success',
    tabs: tabs.map(t => ({
      id: t.id,
      title: t.title || '',
      url: t.url || '',
      active: t.active
    }))
  };
}

async function cmdTabsCreate(args) {
  const tab = await chrome.tabs.create({ url: args?.url || 'about:blank' });
  return { status: 'success', id: tab.id, url: tab.url || args?.url || 'about:blank' };
}

async function cmdKeyPress(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'key_press', args);
}

async function cmdHover(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'hover', args);
}

async function cmdDrag(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };
  return await sendToContent(tabId, 'drag', args);
}

async function cmdZoom(args) {
  const region = args?.region;
  if (!region || region.length !== 4) {
    return { status: 'error', error: 'region must be [x0, y0, x1, y1]' };
  }

  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };

  /* Ensure the tab is in focus for captureVisibleTab */
  const tab = await chrome.tabs.get(tabId);
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tabId, { active: true });
  await new Promise(r => setTimeout(r, 150));

  return await new Promise((resolve) => {
    chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 85 }, (fullDataUrl) => {
      if (chrome.runtime.lastError) {
        resolve({ status: 'error', error: chrome.runtime.lastError.message });
        return;
      }
      (async () => {
        try {
          const [x0, y0, x1, y1] = region;
          const width = x1 - x0;
          const height = y1 - y0;
          const resp = await fetch(fullDataUrl);
          const blob = await resp.blob();
          const bitmap = await createImageBitmap(blob);
          const canvas = new OffscreenCanvas(width, height);
          const ctx = canvas.getContext('2d');
          ctx.drawImage(bitmap, x0, y0, width, height, 0, 0, width, height);
          const croppedBlob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
          const reader = new FileReader();
          reader.onloadend = () => {
            const b64 = reader.result.split(',')[1];
            resolve({ status: 'success', image_b64: b64, region, width, height });
          };
          reader.readAsDataURL(croppedBlob);
        } catch (err) {
          resolve({ status: 'error', error: err.message });
        }
      })();
    });
  });
}

/* ─── Debugger-based: Console ───────────────────────────────────────────── */

async function ensureDebuggerConsole(tabId) {
  if (!debuggerAttached.has(tabId)) {
    debuggerAttached.set(tabId, new Set());
  }
  const attachments = debuggerAttached.get(tabId);
  if (attachments.has('console')) return;

  if (attachments.size === 0) {
    await chrome.debugger.attach({ tabId }, '1.3');
  }
  await chrome.debugger.sendCommand({ tabId }, 'Runtime.enable');
  attachments.add('console');

  if (!consoleBuffers.has(tabId)) {
    consoleBuffers.set(tabId, []);
  }
}

async function cmdReadConsole(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };

  await ensureDebuggerConsole(tabId);

  const buffer = consoleBuffers.get(tabId) || [];
  let messages = [...buffer];

  /* Filter by pattern if provided */
  if (args?.pattern) {
    try {
      const re = new RegExp(args.pattern, 'i');
      messages = messages.filter(m => re.test(m.text));
    } catch (_) { /* invalid regex, return all */ }
  }

  /* Filter errors only */
  if (args?.only_errors) {
    messages = messages.filter(m => m.level === 'error' || m.level === 'exception');
  }

  /* Limit */
  const limit = args?.limit || 100;
  messages = messages.slice(-limit);

  /* Clear if requested */
  if (args?.clear) {
    consoleBuffers.set(tabId, []);
  }

  return { messages };
}

/* ─── Debugger-based: Network ───────────────────────────────────────────── */

async function ensureDebuggerNetwork(tabId) {
  if (!debuggerAttached.has(tabId)) {
    debuggerAttached.set(tabId, new Set());
  }
  const attachments = debuggerAttached.get(tabId);
  if (attachments.has('network')) return;

  if (attachments.size === 0) {
    await chrome.debugger.attach({ tabId }, '1.3');
  }
  await chrome.debugger.sendCommand({ tabId }, 'Network.enable');
  attachments.add('network');

  if (!networkBuffers.has(tabId)) {
    networkBuffers.set(tabId, []);
  }
}

async function cmdReadNetwork(args) {
  const tabId = await getTargetTabId(args);
  if (!tabId) return { error: 'No active tab' };

  await ensureDebuggerNetwork(tabId);

  const buffer = networkBuffers.get(tabId) || [];
  let requests = [...buffer];

  /* Filter by URL pattern */
  if (args?.url_pattern) {
    requests = requests.filter(r => r.url.includes(args.url_pattern));
  }

  /* Limit */
  const limit = args?.limit || 100;
  requests = requests.slice(-limit);

  /* Clear if requested */
  if (args?.clear) {
    networkBuffers.set(tabId, []);
  }

  return { requests };
}

/* ─── Debugger Event Listener (single unified handler) ─────────────────── */

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;

  /* ── Console events ── */
  if (method === 'Runtime.consoleAPICalled') {
    const buffer = consoleBuffers.get(tabId);
    if (buffer) {
      const text = (params.args || []).map(a => {
        if (a.type === 'string') return a.value;
        if (a.type === 'number' || a.type === 'boolean') return String(a.value);
        if (a.description) return a.description;
        if (a.value !== undefined) return JSON.stringify(a.value);
        return a.type;
      }).join(' ');

      buffer.push({
        level: params.type || 'log',
        text,
        timestamp: params.timestamp || Date.now()
      });
      if (buffer.length > 500) buffer.splice(0, buffer.length - 500);
    }
  }

  if (method === 'Runtime.exceptionThrown') {
    const buffer = consoleBuffers.get(tabId);
    if (buffer && params.exceptionDetails) {
      const desc = params.exceptionDetails.exception?.description
        || params.exceptionDetails.text
        || 'Unknown exception';
      buffer.push({
        level: 'exception',
        text: desc,
        timestamp: params.timestamp || Date.now()
      });
    }
  }

  /* ── Network events ── */
  if (method === 'Network.requestWillBeSent') {
    const buffer = networkBuffers.get(tabId);
    if (buffer && params.request) {
      buffer.push({
        _requestId: params.requestId,
        method: params.request.method || 'GET',
        url: params.request.url || '',
        status: 0,
        type: params.type || 'Other',
        mime_type: ''
      });
      if (buffer.length > 500) buffer.splice(0, buffer.length - 500);
    }
  }

  if (method === 'Network.responseReceived') {
    const buffer = networkBuffers.get(tabId);
    if (buffer && params.response) {
      /* Try to update the matching requestWillBeSent entry */
      const idx = params.requestId
        ? buffer.findIndex(r => r._requestId === params.requestId)
        : -1;
      if (idx !== -1) {
        buffer[idx].status = params.response.status || 0;
        buffer[idx].mime_type = params.response.mimeType || '';
        buffer[idx].type = params.type || buffer[idx].type;
        buffer[idx].url = params.response.url || buffer[idx].url;
      } else {
        /* No matching request found; create a standalone entry */
        buffer.push({
          method: 'GET',
          url: params.response.url || '',
          status: params.response.status || 0,
          type: params.type || 'Other',
          mime_type: params.response.mimeType || ''
        });
        if (buffer.length > 500) buffer.splice(0, buffer.length - 500);
      }
    }
  }
});

/* ─── Debugger detach on tab close ─────────────────────────────────────── */

chrome.debugger.onDetach.addListener((source, _reason) => {
  const tabId = source.tabId;
  debuggerAttached.delete(tabId);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  consoleBuffers.delete(tabId);
  networkBuffers.delete(tabId);
  debuggerAttached.delete(tabId);
});

/* ─── Extension Message Handler (popup, etc.) ───────────────────────────── */

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'connect') {
    connect(msg.token);
    sendResponse({ status: 'connecting' });
  } else if (msg.type === 'disconnect') {
    disconnect();
    sendResponse({ status: 'disconnected' });
  } else if (msg.type === 'getStatus') {
    sendResponse({ connected, connecting, authFailed, wsUrl: BASE_WS_URL });
  }
  return true;
});
