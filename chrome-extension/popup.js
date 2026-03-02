/**
 * Galactic Browser - Popup Logic
 * Handles connection UI, passphrase hashing, and status polling.
 */

const connectBtn = document.getElementById('connect-btn');
const passphraseInput = document.getElementById('passphrase');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const chatBtn = document.getElementById('chat-btn');

let isConnected = false;
let statusPollInterval = null;

/* ─── SHA-256 Hashing ─────────────────────────────────────────────────── */

async function hashPassphrase(passphrase) {
  const encoder = new TextEncoder();
  const data = encoder.encode(passphrase);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/* ─── UI Updates ──────────────────────────────────────────────────────── */

function setConnectedUI() {
  isConnected = true;
  statusDot.className = 'status-dot connected';
  statusText.textContent = 'Connected';
  connectBtn.textContent = 'DISCONNECT';
  connectBtn.classList.add('connected');
  passphraseInput.disabled = true;
  chatBtn.style.display = 'block';
}

function setDisconnectedUI() {
  isConnected = false;
  statusDot.className = 'status-dot disconnected';
  statusText.textContent = 'Disconnected';
  connectBtn.textContent = 'CONNECT';
  connectBtn.classList.remove('connected');
  passphraseInput.disabled = false;
  chatBtn.style.display = 'none';
}

function setConnectingUI() {
  statusDot.className = 'status-dot connecting';
  statusText.textContent = 'Connecting...';
  connectBtn.textContent = 'CONNECTING...';
  connectBtn.disabled = true;
  passphraseInput.disabled = true;
  chatBtn.style.display = 'none';

  /* Re-enable button after a short delay */
  setTimeout(() => { connectBtn.disabled = false; }, 2000);
}

function setAuthFailedUI() {
  /* If user is currently typing, don't clear the field or show the error state 
     to avoid "Mission Impossible" race condition where input clears every 2s */
  if (document.activeElement === passphraseInput) {
    return;
  }

  isConnected = false;
  statusDot.className = 'status-dot error';
  statusText.textContent = 'Wrong password!';
  connectBtn.textContent = 'CONNECT';
  connectBtn.classList.remove('connected');
  connectBtn.disabled = false;
  passphraseInput.disabled = false;
  passphraseInput.value = '';
  passphraseInput.classList.add('error');
  passphraseInput.focus();
  chatBtn.style.display = 'none';
  setTimeout(() => passphraseInput.classList.remove('error'), 2000);
}

/* ─── Connection Actions ──────────────────────────────────────────────── */

async function doConnect() {
  const passphrase = passphraseInput.value.trim();
  if (!passphrase) {
    passphraseInput.classList.add('error');
    passphraseInput.focus();
    setTimeout(() => passphraseInput.classList.remove('error'), 1500);
    return;
  }

  setConnectingUI();

  const token = await hashPassphrase(passphrase);

  /* Save token AND passphrase to storage so popup can restore it on reopen */
  await chrome.storage.local.set({
    galactic_token: token,
    galactic_passphrase: passphrase,
    galactic_auth_failed: false
  });

  /* Tell background to connect */
  chrome.runtime.sendMessage({ type: 'connect', token }, (_response) => {
    /* Status will be updated by polling */
  });
}

function doDisconnect() {
  chrome.runtime.sendMessage({ type: 'disconnect' }, (_response) => {
    setDisconnectedUI();
    passphraseInput.value = '';
    chrome.storage.local.remove(['galactic_token', 'galactic_passphrase', 'galactic_auth_failed']);
  });
}

/* ─── Chat Panel Button ───────────────────────────────────────────────── */

chatBtn.addEventListener('click', () => {
  chrome.windows.getCurrent((win) => {
    chrome.sidePanel.open({ windowId: win.id });
  });
});

/* ─── Button Handler ──────────────────────────────────────────────────── */

connectBtn.addEventListener('click', () => {
  if (isConnected) {
    doDisconnect();
  } else {
    doConnect();
  }
});

/* Allow Enter key to connect */
passphraseInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !isConnected) {
    doConnect();
  }
});

/* ─── Status Polling ──────────────────────────────────────────────────── */

function pollStatus() {
  chrome.runtime.sendMessage({ type: 'getStatus' }, (response) => {
    if (chrome.runtime.lastError) return;
    if (response?.connected) {
      setConnectedUI();
    } else if (response?.authFailed) {
      /* Wrong password — show error, clear input so user can retype */
      setAuthFailedUI();
    } else if (response?.connecting) {
      /* Background is actively reconnecting */
      setConnectingUI();
    } else if (isConnected) {
      /* Was connected but now disconnected — reconnecting in background */
      setDisconnectedUI();
    }
  });
}

/* ─── Initialization ──────────────────────────────────────────────────── */

async function init() {
  /* Restore saved passphrase so user doesn't have to retype after popup reopens */
  const data = await chrome.storage.local.get([
    'galactic_token', 'galactic_passphrase', 'galactic_auth_failed'
  ]);

  if (data.galactic_passphrase) {
    passphraseInput.value = data.galactic_passphrase;
  }

  /* If we know auth already failed from a previous attempt, show it immediately */
  if (data.galactic_auth_failed) {
    setAuthFailedUI();
  } else if (data.galactic_token) {
    /* Token exists and no auth failure — background is reconnecting */
    setConnectingUI();
  }

  /* Initial status check (will override the above if background reports different state) */
  pollStatus();

  /* Poll every 2 seconds while popup is open */
  statusPollInterval = setInterval(pollStatus, 2000);
}

/* Clean up on popup close */
window.addEventListener('unload', () => {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
  }
});

init();
