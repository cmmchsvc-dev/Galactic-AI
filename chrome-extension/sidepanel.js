/**
 * Galactic Browser - Side Panel Chat Logic
 *
 * Architecture:
 *   - WebSocket to ws://127.0.0.1:17789/stream  → receives stream_chunk events
 *     (server bypasses token auth for loopback connections)
 *   - POST to http://127.0.0.1:17789/api/chat   → sends user messages
 *   - Chrome extension host_permissions (<all_urls>) bypasses CORS for extension pages
 *
 * Resilience: If WebSocket is down, the HTTP response body from /api/chat is
 * used as a fallback so the user always sees Byte's reply.
 */

const BASE_URL = 'http://127.0.0.1:17789';
const WS_URL   = 'ws://127.0.0.1:17789/stream';

/* ─── DOM Refs ────────────────────────────────────────────────────────── */

const chatLog   = document.getElementById('sp-chat-log');
const input     = document.getElementById('sp-input');
const sendBtn   = document.getElementById('sp-send-btn');
const statusDot = document.getElementById('sp-status-dot');

/* ─── State ───────────────────────────────────────────────────────────── */

let socket        = null;
let streamBubble  = null;   // Current Byte bubble being streamed into
let isStreaming   = false;
let chunksReceived = 0;     // Track whether WS delivered anything for this message

/* ─── WebSocket Connection ───────────────────────────────────────────── */

function connectWS() {
  if (socket && socket.readyState <= WebSocket.OPEN) return;

  try {
    socket = new WebSocket(WS_URL);
  } catch (_) {
    setTimeout(connectWS, 5000);
    return;
  }

  socket.onopen = () => {
    updateDot(true);
  };

  socket.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }

    if (msg.type === 'stream_chunk') {
      appendStreamChunk(msg.data || '');
    }
    /* Ignore logs, telemetry, agent_trace etc. — chat-only mode */
  };

  socket.onclose = () => {
    updateDot(false);
    /* Auto-reconnect after 3s */
    setTimeout(connectWS, 3000);
  };

  socket.onerror = () => {
    /* onclose fires after onerror — nothing extra needed */
  };
}

/* ─── Status Dot ──────────────────────────────────────────────────────── */

function updateDot(connected) {
  statusDot.className = `sp-dot ${connected ? 'connected' : 'disconnected'}`;
  statusDot.title     = connected ? 'Connected to Galactic AI' : 'Disconnected — reconnecting...';
}

/* ─── Sending Messages ────────────────────────────────────────────────── */

async function sendMessage() {
  const text = input.value.trim();
  if (!text || isStreaming) return;

  /* Hide welcome screen on first message */
  const welcome = chatLog.querySelector('.sp-welcome');
  if (welcome) welcome.remove();

  /* Append user bubble */
  appendBubble('user', text);

  /* Clear input and reset height */
  input.value = '';
  input.style.height = 'auto';

  /* Create empty Byte bubble — chunks will stream into it */
  streamBubble = appendBubble('byte', '');
  streamBubble.classList.add('streaming');
  isStreaming = true;
  chunksReceived = 0;
  setInputLocked(true);

  let httpResponse = null;

  try {
    const resp = await fetch(`${BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    });
    if (resp.ok) {
      const data = await resp.json();
      httpResponse = data.response || null;
    }
  } catch (err) {
    /* Network error — show inline */
    if (streamBubble && !streamBubble.textContent.trim()) {
      streamBubble.textContent = `\u26a0 Could not reach Galactic AI: ${err.message}`;
    }
  } finally {
    /* If WebSocket didn't deliver any chunks, fall back to HTTP response */
    if (streamBubble && !streamBubble.textContent.trim() && httpResponse) {
      streamBubble.textContent = httpResponse;
    }
    finalizeStream();
  }
}

/* ─── Streaming Helpers ───────────────────────────────────────────────── */

function appendStreamChunk(chunk) {
  if (!streamBubble) return;
  chunksReceived++;
  streamBubble.textContent += chunk;
  scrollToBottom();
}

function finalizeStream() {
  if (streamBubble) {
    streamBubble.classList.remove('streaming');
    /* If nothing was streamed AND no fallback, remove empty bubble */
    if (!streamBubble.textContent.trim()) {
      streamBubble.remove();
    }
    streamBubble = null;
  }
  isStreaming = false;
  chunksReceived = 0;
  setInputLocked(false);
  input.focus();
}

/* ─── DOM Helpers ─────────────────────────────────────────────────────── */

function appendBubble(role, text) {
  const div = document.createElement('div');
  div.className = `sp-msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  scrollToBottom();
  return div;
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setInputLocked(locked) {
  input.disabled  = locked;
  sendBtn.disabled = locked;
}

/* ─── Auto-resize Textarea ────────────────────────────────────────────── */

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
});

/* ─── Keyboard Shortcuts ──────────────────────────────────────────────── */

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener('click', () => sendMessage());

/* ─── Boot ────────────────────────────────────────────────────────────── */

connectWS();
input.focus();
