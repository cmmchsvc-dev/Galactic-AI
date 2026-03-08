/**
 * Galactic Browser - Content Script
 * Injected into every page. Handles DOM inspection, interaction, and element tracking.
 */

(() => {
  /* Prevent double-injection */
  if (window.__galacticContentLoaded) return;
  window.__galacticContentLoaded = true;

  let shadowHost = null;
  let shadowRoot = window.__galacticShadowRoot || null;
  let currentStatusPill = null;
  let currentBorderGlow = null;
  let statusHideTimeout = null;
  let virtualCursor = null;
  let currentScrollPromise = null;
  let isAnimating = false;

  function ensureShadow() {
    if (shadowRoot && shadowHost && document.documentElement.contains(shadowHost)) return shadowRoot;

    // Check if host already exists but was disconnected or needs re-creation
    let existingHost = document.getElementById('galactic-ui-container');
    if (existingHost) {
      existingHost.remove();
    }

    shadowHost = document.createElement('div');
    shadowHost.id = 'galactic-ui-container';
    shadowHost.style.cssText = 'position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 2147483647; pointer-events: none; overflow: visible;';
    document.documentElement.appendChild(shadowHost);

    // Switch to open for debugging/resilience
    shadowRoot = shadowHost.attachShadow({ mode: 'open' });
    window.__galacticShadowRoot = shadowRoot;

    // Inject ALL styles into shadow root once
    const style = document.createElement('style');
    style.id = 'galactic-core-styles';
    style.textContent = `
      :host { all: initial; pointer-events: none; }
      .galactic-ripple {
        position: fixed;
        border: 2px solid rgba(255, 0, 255, 0.8);
        background: radial-gradient(circle, rgba(255, 0, 255, 0.4) 0%, rgba(0, 255, 255, 0.2) 100%);
        border-radius: 50%;
        pointer-events: none;
        z-index: 2147483646;
        transform: translate(-50%, -50%) scale(0);
        animation: galactic-ripple-out 0.6s ease-out forwards;
      }
      @keyframes galactic-ripple-out {
        to { transform: translate(-50%, -50%) scale(4); opacity: 0; }
      }

      #galactic-virtual-cursor {
        position: fixed;
        top: -10px; left: -10px;
        width: 32px;
        height: 32px;
        background-size: contain;
        background-repeat: no-repeat;
        pointer-events: none;
        z-index: 2147483647 !important;
        transform: translate3d(0, 0, 0) rotate(0deg);
        transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.4s ease;
        opacity: 0;
        filter: drop-shadow(2px 2px 8px rgba(255, 0, 255, 0.8)) drop-shadow(-2px -2px 8px rgba(0, 255, 255, 0.8));
      }

      #galactic-virtual-cursor.default {
        background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzIiIGhlaWdodD0iMzIiIHZpZXdCb3g9IjAgMCAzMiAzMiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNNSA1djE4bDQtNGwzIDZoNGwtMy02bDUtMUw1IDV6IiBmaWxsPSIjMDAwIiBzdHJva2U9IiNmZmYiIHN0cm9rZS13aWR0aD0iMSIgc2hhcGUtcmVuZGVyaW5nPSJjcmlzcEVkZ2VzIi8+PC9zdmc+");
      }

      #galactic-virtual-cursor.pointer {
        background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzIiIGhlaWdodD0iMzIiIHZpZXdCb3g9IjAgMCAzMiAzMiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTEgM2gxMXYxMWgtMnYyaC0ydjJoLTJWMTNoMHYxaDFoMVY0aC0ydjloLTJWN2gtMlY0aC0ydjloLTJWMTFoLTJWMTN2MTNoMnYyaDEwdjNoMnYyaDJoMnYtMmg0di0yaDJ2LTJoNXYtMmgwVjEzSDExeiIgZmlsbD0iIzAwMCIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjEiIHNoYXBlLXJlbmRlcmluZz0iY3Jpc3BFZGdlcyIvPjwvc3ZnPg==");
      }

      @keyframes galactic-glow-pulse {
        0% { box-shadow: inset 0 0 40px rgba(59, 130, 246, 0.4); }
        50% { box-shadow: inset 0 0 70px rgba(59, 130, 246, 0.7); }
        100% { box-shadow: inset 0 0 40px rgba(59, 130, 246, 0.4); }
      }
    `;
    shadowRoot.appendChild(style);

    return shadowRoot;
  }

  function ensureVirtualCursor() {
    if (virtualCursor) return virtualCursor;
    const root = ensureShadow();
    virtualCursor = document.createElement('div');
    virtualCursor.id = 'galactic-virtual-cursor';
    virtualCursor.className = 'default';
    root.appendChild(virtualCursor);
    return virtualCursor;
  }

  function moveCursor(x, y, type = 'default') {
    const cursor = ensureVirtualCursor();

    // If hidden, snap to a random edge first for a "glide in" effect
    if (cursor.style.opacity === '0' || !cursor.dataset.moved) {
      const edges = [
        { x: -50, y: Math.random() * window.innerHeight },
        { x: window.innerWidth + 50, y: Math.random() * window.innerHeight },
        { x: Math.random() * window.innerWidth, y: -50 },
        { x: Math.random() * window.innerWidth, y: window.innerHeight + 50 }
      ];
      const start = edges[Math.floor(Math.random() * edges.length)];
      cursor.style.transition = 'none';
      cursor.style.transform = `translate3d(${start.x}px, ${start.y}px, 0) rotate(0deg)`;
      // Force reflow
      cursor.offsetHeight;
      cursor.style.transition = '';
      cursor.dataset.moved = 'true';
    }

    const lastX = parseFloat(cursor.dataset.lastX || x);
    const deltaX = x - lastX;
    const rotation = Math.max(-20, Math.min(20, deltaX / 5)); // Tilt based on movement

    cursor.className = type;
    cursor.style.opacity = '1';
    cursor.style.transform = `translate3d(${x - 10}px, ${y - 10}px, 0) rotate(${rotation}deg)`;
    cursor.dataset.lastX = x;
  }

  function showRipple(x, y) {
    const root = ensureShadow();
    const ripple = document.createElement('div');
    ripple.className = 'galactic-ripple';
    ripple.style.left = x + 'px';
    ripple.style.top = y + 'px';
    ripple.style.width = '20px';
    ripple.style.height = '20px';
    root.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  }

  function getCursorType(el) {
    if (!el) return 'default';
    try {
      const style = window.getComputedStyle(el);
      if (style.cursor === 'pointer' || el.tagName === 'A' || el.closest('a') || el.tagName === 'BUTTON' || el.closest('button')) {
        return 'pointer';
      }
    } catch (e) { }
    return 'default';
  }

  function hideCursor() {
    if (virtualCursor) {
      virtualCursor.style.opacity = '0';
      delete virtualCursor.dataset.moved;
    }
  }

  function showStatusPill(text) {
    console.log('[Galactic] showStatusPill:', text);
    const root = ensureShadow();

    if (statusHideTimeout) {
      clearTimeout(statusHideTimeout);
      statusHideTimeout = null;
    }

    if (!currentBorderGlow) {
      currentBorderGlow = document.createElement('div');
      currentBorderGlow.id = 'galactic-border-glow';
      currentBorderGlow.style.cssText = `
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        pointer-events: none;
        z-index: 2147483640;
        opacity: 0;
        transition: opacity 0.8s ease;
        box-shadow: inset 0 0 40px rgba(59, 130, 246, 0.5);
      `;
      currentBorderGlow.style.animation = 'galactic-glow-pulse 3s infinite ease-in-out';
      root.appendChild(currentBorderGlow);
      setTimeout(() => { if (currentBorderGlow) currentBorderGlow.style.opacity = '1'; }, 10);
    }

    // --- Status Pill ---
    if (currentStatusPill) {
      const label = currentStatusPill.querySelector('span');
      if (label) label.textContent = text;
      currentStatusPill.style.opacity = '1';
      currentStatusPill.style.transform = 'translateX(-50%) translateY(0)';
      return;
    }

    const pill = document.createElement('div');
    pill.id = 'galactic-status-pill';
    pill.style.cssText = `
      position: fixed;
      bottom: 40px;
      left: 50%;
      transform: translateX(-50%) translateY(40px);
      opacity: 0;
      background: rgba(15, 15, 25, 0.8);
      backdrop-filter: blur(12px) saturate(180%);
      -webkit-backdrop-filter: blur(12px) saturate(180%);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 999px;
      padding: 12px 24px;
      color: #fff;
      font-family: 'Inter', system-ui, sans-serif;
      font-size: 14px;
      font-weight: 500;
      z-index: 2147483647;
      display: flex;
      align-items: center;
      gap: 12px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), inset 0 0 0 1px rgba(255, 255, 255, 0.05);
      transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: none;
      white-space: nowrap;
    `;

    pill.innerHTML = `
      <div style="width: 12px; height: 12px; background: #3b82f6; border-radius: 50%; box-shadow: 0 0 15px #3b82f6; animation: galactic-orb-pulse 2s infinite ease-in-out;"></div>
      <span>${text}</span>
    `;

    // Add pulse animation for the orb if not already present in core styles
    const coreStyles = root.querySelector('#galactic-core-styles');
    if (coreStyles && !coreStyles.textContent.includes('galactic-orb-pulse')) {
      coreStyles.textContent += `
        @keyframes galactic-orb-pulse {
          0% { transform: scale(1); box-shadow: 0 0 10px #3b82f6; }
          50% { transform: scale(1.2); box-shadow: 0 0 20px #60a5fa; }
          100% { transform: scale(1); box-shadow: 0 0 10px #3b82f6; }
        }
      `;
    }

    root.appendChild(pill);
    currentStatusPill = pill;
    setTimeout(() => {
      pill.style.opacity = '1';
      pill.style.transform = 'translateX(-50%) translateY(0)';
    }, 10);
  }
  function hideStatusPill(immediate = false) {
    if (statusHideTimeout) clearTimeout(statusHideTimeout);

    if (!immediate) {
      statusHideTimeout = setTimeout(() => {
        statusHideTimeout = null;
        hideStatusPill(true);
      }, 2500);
      return;
    }

    if (currentStatusPill) {
      currentStatusPill.style.opacity = '0';
      currentStatusPill.style.transform = 'translateX(-50%) translateY(20px)';
      const p = currentStatusPill;
      currentStatusPill = null;
      setTimeout(() => { if (p && p.parentElement) p.remove(); }, 600);
    }

    if (currentBorderGlow) {
      currentBorderGlow.style.opacity = '0';
      const g = currentBorderGlow;
      currentBorderGlow = null;
      setTimeout(() => { if (g && g.parentElement) g.remove(); }, 800);
    }
  }

  /* ─── Element Reference System ──────────────────────────────────────── */

  let refMap = new Map();   // refId (string) -> Element
  let elementToRefMap = new WeakMap(); // Element -> refId (string)

  function resetRefs() {
    refMap.clear();
    // We don't need to clear the WeakMap, it handles its own garbage collection
  }

  // Simple string hashing function (djb2)
  function hashString(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) + hash) + str.charCodeAt(i); /* hash * 33 + c */
    }
    // Convert to positive integer and make it shorter
    return Math.abs(hash).toString(36).slice(0, 6);
  }

  // Generate a stable signature for an element based on its DOM path and attributes
  function generateElementSignature(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return 'unknown';

    let signature = el.tagName.toLowerCase();

    // ID is highly stable
    if (el.id) {
      signature += `#${el.id} `;
      return signature; // If it has an ID, that's usually unique enough
    }

    // Classes are moderately stable
    if (el.className && typeof el.className === 'string') {
      const classes = el.className.split(' ').filter(c => c).sort().join('.');
      if (classes) signature += `.${classes} `;
    }

    // Role and Aria labels
    const role = el.getAttribute('role');
    if (role) signature += `[role = ${role}]`;

    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) signature += `[aria = ${ariaLabel.substring(0, 15)}]`;

    // Form attributes
    if (el.name) signature += `[name = ${el.name}]`;
    if (el.type) signature += `[type = ${el.type}]`;

    // Add text content (truncated) as a strong differentiator for links/buttons
    const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
    if (text && text.length < 50) {
      signature += `| ${text} `;
    }

    // DOM Path (up to 3 levels) to differentiate siblings
    let path = '';
    let current = el;
    let depth = 0;
    while (current && current.parentElement && depth < 3) {
      let index = 1;
      let sibling = current.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === current.tagName) index++;
        sibling = sibling.previousElementSibling;
      }
      path = `/ ${current.tagName.toLowerCase()} [${index}]${path} `;
      current = current.parentElement;
      depth++;
    }

    return signature + path;
  }

  function assignRef(element) {
    // Return existing ref if already assigned during this snapshot cycle
    if (elementToRefMap.has(element)) {
      const existingRef = elementToRefMap.get(element);
      // Ensure it's in the current active map
      refMap.set(existingRef, element);
      return existingRef;
    }

    // Generate a stable hash-based ID
    const signature = generateElementSignature(element);
    let hash = hashString(signature);
    let refId = `ref_${hash} `;

    // Handle extremely rare collisions by appending a counter
    let counter = 1;
    while (refMap.has(refId) && refMap.get(refId) !== element) {
      refId = `ref_${hash}_${counter} `;
      counter++;
    }

    refMap.set(refId, element);
    elementToRefMap.set(element, refId);
    return refId;
  }

  function getElementByRef(refId) {
    return refMap.get(refId) || null;
  }

  /* ─── Visibility Check ─────────────────────────────────────────────── */

  function isVisible(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;

    // Check if it's our own UI
    if (el.closest('#galactic-cursor-container')) return false;

    /* Quick checks */
    if (el.hidden) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none') return false;
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    if (parseFloat(style.opacity) === 0) return false;

    // Check if element has dimensions
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      if (el.tagName !== 'OPTION') return false;
    }

    /* offsetParent is null for hidden elements, but also for position:fixed, body, html */
    if (!el.offsetParent && style.position !== 'fixed' && style.position !== 'sticky'
      && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
      return false;
    }
    return true;
  }

  /* ─── Role / Name Inference ─────────────────────────────────────────── */

  const TAG_ROLE_MAP = {
    'A': 'link',
    'BUTTON': 'button',
    'INPUT': 'textbox',
    'TEXTAREA': 'textbox',
    'SELECT': 'combobox',
    'IMG': 'image',
    'NAV': 'navigation',
    'MAIN': 'main',
    'HEADER': 'banner',
    'FOOTER': 'contentinfo',
    'ASIDE': 'complementary',
    'SECTION': 'region',
    'ARTICLE': 'article',
    'FORM': 'form',
    'TABLE': 'table',
    'THEAD': 'rowgroup',
    'TBODY': 'rowgroup',
    'TR': 'row',
    'TH': 'columnheader',
    'TD': 'cell',
    'UL': 'list',
    'OL': 'list',
    'LI': 'listitem',
    'H1': 'heading',
    'H2': 'heading',
    'H3': 'heading',
    'H4': 'heading',
    'H5': 'heading',
    'H6': 'heading',
    'DIALOG': 'dialog',
    'DETAILS': 'group',
    'SUMMARY': 'button',
    'LABEL': 'label',
    'FIELDSET': 'group',
    'LEGEND': 'legend',
    'P': 'paragraph',
    'PRE': 'code',
    'BLOCKQUOTE': 'blockquote',
    'IFRAME': 'iframe'
  };

  const INPUT_TYPE_ROLE = {
    'checkbox': 'checkbox',
    'radio': 'radio',
    'range': 'slider',
    'number': 'spinbutton',
    'search': 'searchbox',
    'email': 'textbox',
    'tel': 'textbox',
    'url': 'textbox',
    'password': 'textbox',
    'text': 'textbox',
    'submit': 'button',
    'reset': 'button',
    'button': 'button',
    'image': 'button',
    'file': 'textbox'
  };

  function getRole(el) {
    const explicitRole = el.getAttribute('role');
    if (explicitRole) return explicitRole;

    const tag = el.tagName;
    if (tag === 'INPUT') {
      const type = (el.type || 'text').toLowerCase();
      return INPUT_TYPE_ROLE[type] || 'textbox';
    }
    return TAG_ROLE_MAP[tag] || null;
  }

  function getAccessibleName(el) {
    /* aria-label takes priority */
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel.trim();

    /* aria-labelledby */
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map(id => {
        const ref = document.getElementById(id);
        return ref ? ref.textContent.trim() : '';
      }).filter(Boolean);
      if (parts.length > 0) return parts.join(' ');
    }

    /* Specific element types */
    const tag = el.tagName;

    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      /* Associated label */
      if (el.id) {
        const label = document.querySelector(`label[for= "${CSS.escape(el.id)}"]`);
        if (label) return label.textContent.trim();
      }
      /* Placeholder */
      if (el.placeholder) return el.placeholder;
      /* Name attribute as fallback */
      if (el.name) return el.name;
      return '';
    }

    if (tag === 'IMG') {
      return el.alt || el.title || '';
    }

    if (tag === 'A') {
      return (el.textContent || el.title || '').trim();
    }

    /* title attribute */
    if (el.title) return el.title.trim();

    /* Direct text content (not too deep) */
    const text = getDirectText(el);
    return text;
  }

  function getDirectText(el) {
    let text = '';
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent;
      }
    }
    text = text.trim().replace(/\s+/g, ' ');
    if (text.length > 80) text = text.substring(0, 77) + '...';
    return text;
  }

  function isInteractive(el) {
    const tag = el.tagName;
    if (['BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT', 'SUMMARY'].includes(tag)) return true;
    if (el.getAttribute('role') && ['button', 'link', 'textbox', 'checkbox', 'radio',
      'tab', 'menuitem', 'option', 'switch', 'slider', 'combobox', 'searchbox',
      'spinbutton', 'treeitem'].includes(el.getAttribute('role'))) return true;
    if (el.hasAttribute('onclick') || el.hasAttribute('tabindex')) return true;
    if (el.hasAttribute('contenteditable') && el.contentEditable === 'true') return true;
    return false;
  }

  /* ─── Snapshot / Accessibility Tree ─────────────────────────────────── */

  function buildSnapshot(args) {
    resetRefs();

    const maxDepth = args?.max_depth || 15;
    const interactiveOnly = args?.filter === 'interactive';
    const maxChars = args?.max_chars || 60000;
    const lines = [];

    function walk(el, depth) {
      if (depth > maxDepth) return;
      if (!isVisible(el)) return;
      if (lines.join('\n').length > maxChars) return;

      const role = getRole(el);
      const tag = el.tagName.toLowerCase();
      const name = getAccessibleName(el);
      const interactive = isInteractive(el);

      /* Decide whether to include this element */
      const hasRole = !!role;
      const hasName = !!name;
      const isStructural = ['main', 'navigation', 'banner', 'contentinfo',
        'complementary', 'region', 'article', 'form', 'dialog', 'list',
        'heading', 'table', 'row', 'cell', 'columnheader', 'rowgroup',
        'group', 'iframe'].includes(role);

      const shouldInclude = interactive || isStructural || hasRole;

      if (interactiveOnly && !interactive) {
        /* Still walk children for interactive-only mode */
        for (const child of el.children) {
          walk(child, depth);
        }
        return;
      }

      if (shouldInclude) {
        const indent = '  '.repeat(depth);
        let line = `${indent} - ${role || tag} `;

        /* Add name */
        if (name) {
          line += ` "${name}"`;
        }

        /* Ref for interactive elements */
        if (interactive) {
          const refId = assignRef(el);
          line += ` [ref = ${refId}]`;
        }

        /* Extra attributes */
        if (role === 'heading') {
          const level = el.tagName.match(/H(\d)/)?.[1];
          if (level) line += ` level = ${level} `;
        }

        if (role === 'link' && el.href) {
          line += ` url = "${el.getAttribute('href') || ''}"`;
        }

        if ((role === 'textbox' || role === 'combobox' || role === 'searchbox' || role === 'spinbutton') && el.value !== undefined) {
          const inputType = el.type ? ` type=${el.type}` : '';
          line += ` value="${el.value}"${inputType}`;
        }

        if (role === 'checkbox' || role === 'radio') {
          line += ` checked = ${el.checked} `;
        }

        if (el.disabled) {
          line += ` disabled`;
        }

        if (el.getAttribute('aria-expanded') !== null) {
          line += ` expanded = ${el.getAttribute('aria-expanded')} `;
        }

        if (el.getAttribute('aria-selected') !== null) {
          line += ` selected = ${el.getAttribute('aria-selected')} `;
        }

        const rect = el.getBoundingClientRect();
        line += ` coord=(${Math.round(rect.x)},${Math.round(rect.y)})`;

        lines.push(line);

        /* Walk children at increased depth */
        for (const child of el.children) {
          walk(child, depth + 1);
        }
      } else {
        /* Not significant, but walk children at same depth to find nested content */
        /* Include text-only elements (paragraphs, spans with text) */
        if (['P', 'SPAN', 'DIV', 'STRONG', 'EM', 'B', 'I', 'LABEL', 'LEGEND',
          'FIGCAPTION', 'CAPTION', 'BLOCKQUOTE', 'PRE', 'CODE', 'DD', 'DT'].includes(el.tagName)) {
          const text = getDirectText(el);
          if (text && text.length > 1) {
            const indent = '  '.repeat(depth);
            lines.push(`${indent} - text "${text}"`);
          }
        }

        for (const child of el.children) {
          walk(child, depth);
        }
      }
    }

    /* Start from body */
    if (document.body) {
      lines.push('- document');
      for (const child of document.body.children) {
        walk(child, 1);
      }
    }

    return { status: 'success', tree: lines.join('\n'), ref_count: refMap.size };
  }

  /* ─── Find Elements ─────────────────────────────────────────────────── */

  function findElements(args) {
    resetRefs();
    const query = args?.query || '';
    const selector = args?.selector || null;
    const maxResults = args?.max_results || 20;
    const results = [];

    if (selector) {
      /* CSS selector search */
      try {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          if (results.length >= maxResults) break;
          if (!isVisible(el)) continue;
          const refId = assignRef(el);
          results.push({
            ref: refId,
            tag: el.tagName.toLowerCase(),
            role: getRole(el) || el.tagName.toLowerCase(),
            name: getAccessibleName(el),
            text: getDirectText(el),
            rect: el.getBoundingClientRect().toJSON()
          });
        }
      } catch (_) {
        return { error: `Invalid CSS selector: ${selector} ` };
      }
    }

    if (query) {
      /* Text-based search */
      const lowerQuery = query.toLowerCase();
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
      let node;
      while ((node = walker.nextNode()) && results.length < maxResults) {
        if (!isVisible(node)) continue;

        const text = (node.textContent || '').toLowerCase();
        const ariaLabel = (node.getAttribute('aria-label') || '').toLowerCase();
        const placeholder = (node.placeholder || '').toLowerCase();
        const title = (node.title || '').toLowerCase();
        const alt = (node.alt || '').toLowerCase();

        const matches = text.includes(lowerQuery) || ariaLabel.includes(lowerQuery)
          || placeholder.includes(lowerQuery) || title.includes(lowerQuery)
          || alt.includes(lowerQuery);

        if (matches) {
          /* Prefer leaf/interactive elements over containers */
          const isLeaf = node.children.length === 0 || isInteractive(node);
          const directText = getDirectText(node).toLowerCase();
          const directMatch = directText.includes(lowerQuery) || ariaLabel.includes(lowerQuery)
            || placeholder.includes(lowerQuery);

          if (isLeaf || directMatch) {
            const refId = assignRef(node);
            results.push({
              ref: refId,
              tag: node.tagName.toLowerCase(),
              role: getRole(node) || node.tagName.toLowerCase(),
              name: getAccessibleName(node),
              text: getDirectText(node),
              rect: node.getBoundingClientRect().toJSON()
            });
          }
        }
      }
    }

    return { status: 'success', elements: results, count: results.length };
  }

  /* ─── Click ─────────────────────────────────────────────────────────── */

  async function performClick(args) {
    if (isAnimating) {
      console.warn('[Galactic] Animation lock active, waiting...');
      await new Promise(r => {
        const start = Date.now();
        const check = setInterval(() => {
          if (!isAnimating || (Date.now() - start > 10000)) {
            clearInterval(check);
            r();
          }
        }, 100);
      });
    }
    isAnimating = true;
    try {
      showStatusPill(args?.double_click ? 'Double Clicking...' : 'Clicking Element...');
      let el = null;

      if (args?.ref) {
        el = getElementByRef(args.ref);
      } else if (args?.selector) {
        el = document.querySelector(args.selector);
      } else if (args?.coordinate) {
        const [x, y] = args.coordinate;
        el = document.elementFromPoint(x, y);
      }

      if (!el) {
        /* WIKIPEDIA SPECIFIC: Fallback for search bar */
        const isWiki = window.location.hostname.includes('wikipedia.org');
        if (isWiki) {
          el = document.querySelector('input[name="search"], input#searchInput, .cdx-text-input__input, input.mw-ui-background-icon-search');
        }
      }

      if (!el) return { error: 'Element not found' };

      /* Scroll into view if needed */
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      await new Promise(r => setTimeout(r, 100)); // Minimal settle time

      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;

      // --- Custom Cursor Move ---
      moveCursor(cx, cy, getCursorType(el));
      await new Promise(r => setTimeout(r, 850)); // Match 800ms transition + tiny buffer
      showRipple(cx, cy);

      /* Dispatch proper mouse events */
      const eventOpts = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: cx,
        clientY: cy
      };

      el.dispatchEvent(new MouseEvent('mouseover', eventOpts));
      el.dispatchEvent(new MouseEvent('mouseenter', { ...eventOpts, bubbles: false }));
      el.dispatchEvent(new MouseEvent('mousedown', { ...eventOpts, button: 0 }));
      el.focus();
      el.dispatchEvent(new MouseEvent('mouseup', { ...eventOpts, button: 0 }));
      el.dispatchEvent(new MouseEvent('click', { ...eventOpts, button: 0 }));

      /* Double click if requested */
      if (args?.double_click) {
        await new Promise(r => setTimeout(r, 100));
        showRipple(cx, cy);
        el.dispatchEvent(new MouseEvent('dblclick', { ...eventOpts, button: 0 }));
      }

      return { status: 'success' };
    } finally {
      isAnimating = false;
      hideStatusPill();
    }
  }

  /* ─── Type ──────────────────────────────────────────────────────────── */

  async function performType(args) {
    if (isAnimating) {
      console.warn('[Galactic] Animation lock active, waiting...');
      await new Promise(r => {
        const start = Date.now();
        const check = setInterval(() => {
          if (!isAnimating || (Date.now() - start > 10000)) {
            clearInterval(check);
            r();
          }
        }, 100);
      });
    }
    isAnimating = true;
    try {
      showStatusPill('Typing...');
      let el = null;

      if (args?.ref) {
        el = getElementByRef(args.ref);
      } else if (args?.selector) {
        el = document.querySelector(args.selector);
      }

      if (!el) {
        /* Universal smart auto-detect: find the best input element */
        // 1. Check if there's already a focused input
        const focused = document.activeElement;
        if (focused && (focused.tagName === 'INPUT' || focused.tagName === 'TEXTAREA' || focused.contentEditable === 'true')) {
          el = focused;
        }
        // 2. Try search-specific inputs (works on Wikipedia, Google, DuckDuckGo, etc.)
        if (!el) {
          el = document.querySelector(
            'input[type="search"]:not([hidden]), ' +
            'input[name="search"]:not([hidden]), ' +
            'input[name="q"]:not([hidden]), ' +
            'input[role="searchbox"]:not([hidden]), ' +
            'input#searchInput, ' +
            'input.search-input, ' +
            '.cdx-text-input__input, ' +
            'input[aria-label*="search" i], ' +
            'input[placeholder*="search" i]'
          );
        }
        // 3. Try any visible, non-hidden text input that's empty or small
        if (!el) {
          const candidates = document.querySelectorAll(
            'input[type="text"]:not([hidden]), ' +
            'input[type="email"]:not([hidden]), ' +
            'input[type="url"]:not([hidden]), ' +
            'input:not([type]):not([hidden]), ' +
            'textarea:not([hidden])'
          );
          for (const c of candidates) {
            if (isVisible(c) && !c.disabled && !c.readOnly) {
              el = c;
              break;
            }
          }
        }
      }

      if (!el) return { error: 'No suitable input element found. Try specifying a ref or selector.' };

      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;

      // --- Custom Cursor Move ---
      moveCursor(cx, cy, getCursorType(el));
      await new Promise(r => setTimeout(r, 850)); // Match 800ms transition

      const shouldClear = args?.clear !== false; // default: true

      el.focus();

      /* PRE-CLEAR: only for value-based inputs (contenteditable is cleared via execCommand below) */
      if (shouldClear && 'value' in el) {
        el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }

      const text = args?.text || '';
      const isLongText = text.length > 100;

      if (isLongText) {
        /* Optimization: For long text (marketing posts, etc.), use instant injection 
           to avoid 30s tool timeouts while still triggering necessary events. */
        if ('value' in el) {
          el.value = text;
          el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
        } else if (el.contentEditable === 'true') {
          document.execCommand('selectAll', false, null);
          document.execCommand('insertText', false, text);
        }
      } else {
        /* Organic jitter for short strings */
        for (const char of text) {
          const jitter = 15 + Math.random() * 35; // Reduced jitter for better responsiveness
          const eventInit = { key: char, bubbles: true, cancelable: true, composed: true };

          el.dispatchEvent(new KeyboardEvent('keydown', eventInit));
          el.dispatchEvent(new KeyboardEvent('keypress', eventInit));

          if ('value' in el) {
            const start = el.selectionStart;
            const end = el.selectionEnd;
            el.value = el.value.substring(0, start) + char + el.value.substring(end);
            el.selectionStart = el.selectionEnd = start + 1;
            el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: char }));
          } else if (el.contentEditable === 'true') {
            document.execCommand('insertText', false, char);
          }
          el.dispatchEvent(new KeyboardEvent('keyup', eventInit));
          await new Promise(r => setTimeout(r, jitter));
        }
      }

      if (el.contentEditable === 'true') {
        // X.com specifically often needs a KeyboardEvent to trigger the "Post" button activation
        el.dispatchEvent(new KeyboardEvent('keyup', {
          key: 'Enter',
          code: 'Enter',
          keyCode: 13,
          which: 13,
          bubbles: true
        }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else if ('value' in el) {
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }
      else {
        /* Fallback: dispatch key events character by character */
        for (const char of text) {
          el.dispatchEvent(new KeyboardEvent('keydown', { key: char, bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keypress', { key: char, bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keyup', { key: char, bubbles: true }));
        }
      }

      /* OPTIONAL ENTER: Use specialized press_enter arg, or detect from text_amount/etc */
      if (args?.enter || args?.press_enter) {
        await new Promise(r => setTimeout(r, 200));

        // 1. Dispatch full KeyboardEvent suite
        const keyEvents = ['keydown', 'keypress', 'keyup'];
        for (const evName of keyEvents) {
          el.dispatchEvent(new KeyboardEvent(evName, {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true
          }));
        }

        // 2. Try to find and click the search/submit button within the same form or container
        // This is often more reliable than Enter keys on complex sites like Wikipedia/Amazon
        const searchButton = el.form?.querySelector('button[type="submit"], input[type="submit"], button.cdx-search-input__end-button, button[aria-label="Search Wikipedia"]') ||
          el.parentElement?.querySelector('button, .search-button, .cdx-search-input__submit');

        if (searchButton && searchButton !== el) {
          searchButton.click();
        } else if (el.form && typeof el.form.submit === 'function') {
          // 3. Last resort: direct form submission
          try {
            el.form.submit();
          } catch (e) {
            // Some forms override .submit with a button named "submit"
            if (HTMLFormElement.prototype.submit) {
              HTMLFormElement.prototype.submit.call(el.form);
            }
          }
        }
      }

      return { status: 'success' };
    } finally {
      isAnimating = false;
      hideStatusPill();
    }
  }

  function getPageText() {
    return { status: 'success', text: document.body.innerText };
  }

  function getPageDom() {
    return { status: 'success', html: document.documentElement.outerHTML };
  }

  let scrollAnimationFrame = null;

  async function fluidScroll(targetY) {
    if (scrollAnimationFrame) {
      cancelAnimationFrame(scrollAnimationFrame);
    }

    const startY = window.scrollY;
    const distanceTotal = targetY - startY;
    if (Math.abs(distanceTotal) < 2) return Promise.resolve();

    // Proportional duration: minimum 800ms, maximum 2500ms
    const duration = Math.min(2500, Math.max(800, Math.abs(distanceTotal) / 1.5));
    const start = performance.now();

    return new Promise(resolve => {
      function step(now) {
        const time = now - start;
        const progress = Math.min(time / duration, 1);

        // Easing: easeInOutCubic
        const ease = progress < 0.5
          ? 4 * progress * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 3) / 2;

        window.scrollTo(0, startY + (distanceTotal * ease));

        if (progress < 1) {
          scrollAnimationFrame = requestAnimationFrame(step);
        } else {
          scrollAnimationFrame = null;
          resolve();
        }
      }
      scrollAnimationFrame = requestAnimationFrame(step);
    });
  }

  /* ─── Scroll ────────────────────────────────────────────────────────── */

  async function performScroll(args) {
    if (document.readyState !== 'complete') {
      await new Promise(r => {
        window.addEventListener('load', r, { once: true });
        setTimeout(r, 2000); // 2 seconds fallback
      });
    }

    if (isAnimating) {
      console.warn('[Galactic] Animation lock active, waiting...');
      await new Promise(r => {
        const start = Date.now();
        const check = setInterval(() => {
          if (!isAnimating || (Date.now() - start > 10000)) {
            clearInterval(check);
            r();
          }
        }, 100);
      });
    }
    isAnimating = true;
    try {
      showStatusPill('Scrolling...');
      if (args?.ref) {
        const el = getElementByRef(args.ref);
        if (!el) return { error: 'Element not found' };
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return { status: 'success' };
      }

      if (args?.selector) {
        const el = document.querySelector(args.selector);
        if (!el) return { error: 'Element not found' };
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return { status: 'success' };
      }

      /* Percent-based absolute scroll */
      if (args?.percent != null) {
        const pct = Math.max(0, Math.min(100, parseFloat(args.percent)));
        const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
        const targetY = Math.round((pct / 100) * maxScroll);
        await fluidScroll(targetY);
        return {
          status: 'success',
          y: Math.round(window.scrollY),
          max_y: maxScroll,
          message: `Scrolled to ${pct}% (${Math.round(window.scrollY)}/${maxScroll}px)`
        };
      }

      /* Page scroll by direction or target */
      const direction = (args?.direction || 'down').toLowerCase();

      // If amount is small (e.g. 3), treat as "ticks" of 100px. If large (e.g. 500), treat as raw pixels.
      const rawAmount = args?.amount || 3;
      const pixels = rawAmount < 50 ? rawAmount * 100 : rawAmount;

      // Support specific targets
      if (direction === 'bottom' || (args?.text_amount || '').includes('bottom')) {
        await fluidScroll(document.documentElement.scrollHeight - window.innerHeight);
        return { status: 'success' };
      }
      if (direction === 'middle' || (args?.text_amount || '').includes('middle')) {
        await fluidScroll((document.documentElement.scrollHeight - window.innerHeight) / 2);
        return { status: 'success' };
      }
      if (direction === 'top') {
        await fluidScroll(0);
        return { status: 'success' };
      }

      let targetY = window.scrollY;
      switch (direction) {
        case 'up': targetY -= pixels; break;
        case 'down': targetY += pixels; break;
        default: targetY += pixels; break;
      }

      // Clamp
      targetY = Math.max(0, Math.min(targetY, document.documentElement.scrollHeight - window.innerHeight));
      await fluidScroll(targetY);

      return {
        status: 'success',
        y: Math.round(window.scrollY),
        max_y: document.documentElement.scrollHeight - window.innerHeight,
        message: `Scrolled to ${Math.round(window.scrollY)} / ${document.documentElement.scrollHeight - window.innerHeight}`
      };
    } finally {
      isAnimating = false;
      hideStatusPill();
    }
  }

  /* ─── Form Input ────────────────────────────────────────────────────── */

  function performFormInput(args) {
    let el = null;

    if (args?.ref) {
      el = getElementByRef(args.ref);
    } else if (args?.selector) {
      el = document.querySelector(args.selector);
    }

    if (!el) return { error: 'Element not found' };

    const value = args?.value;

    const tag = el.tagName;
    const type = (el.type || '').toLowerCase();

    if (tag === 'SELECT') {
      /* Try matching by value first, then by text */
      let matched = false;
      for (const opt of el.options) {
        if (opt.value === String(value) || opt.textContent.trim() === String(value)) {
          el.value = opt.value;
          matched = true;
          break;
        }
      }
      if (!matched && typeof value === 'number') {
        el.selectedIndex = value;
      }
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return { status: 'success' };
    }

    if (type === 'checkbox' || type === 'radio') {
      const shouldBeChecked = typeof value === 'boolean' ? value : value === 'true' || value === true;
      if (el.checked !== shouldBeChecked) {
        el.checked = shouldBeChecked;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return { status: 'success' };
    }

    if (type === 'file') {
      return { error: 'Cannot programmatically set file inputs for security reasons' };
    }

    /* Text inputs, textareas, etc. */
    el.focus();
    el.value = String(value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { status: 'success' };
  }

  /* ─── Key Press ─────────────────────────────────────────────────────── */

  function performKeyPress(args) {
    const keys = args?.text || args?.key || '';
    const target = args?.ref ? getElementByRef(args.ref) : document.activeElement || document.body;

    if (!target) return { error: 'No target element' };

    /* Parse space-separated key sequences, handle modifiers like "ctrl+a" */
    const keySequences = keys.split(' ').filter(Boolean);
    const repeat = Math.min(args?.repeat || 1, 100);

    for (let r = 0; r < repeat; r++) {
      for (const keyCombo of keySequences) {
        const parts = keyCombo.split('+');
        const key = parts.pop();
        const modifiers = {
          ctrlKey: parts.includes('ctrl') || parts.includes('Control'),
          shiftKey: parts.includes('shift') || parts.includes('Shift'),
          altKey: parts.includes('alt') || parts.includes('Alt'),
          metaKey: parts.includes('meta') || parts.includes('cmd') || parts.includes('Meta')
        };

        const keyMap = {
          'Enter': 'Enter', 'Tab': 'Tab', 'Escape': 'Escape', 'Esc': 'Escape',
          'Backspace': 'Backspace', 'Delete': 'Delete', 'Space': ' ',
          'ArrowUp': 'ArrowUp', 'ArrowDown': 'ArrowDown',
          'ArrowLeft': 'ArrowLeft', 'ArrowRight': 'ArrowRight',
          'Home': 'Home', 'End': 'End', 'PageUp': 'PageUp', 'PageDown': 'PageDown',
          'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4', 'F5': 'F5',
          'F6': 'F6', 'F7': 'F7', 'F8': 'F8', 'F9': 'F9', 'F10': 'F10',
          'F11': 'F11', 'F12': 'F12'
        };
        const resolvedKey = keyMap[key] || key;

        const eventInit = {
          key: resolvedKey,
          code: resolvedKey.length === 1 ? `Key${resolvedKey.toUpperCase()} ` : resolvedKey,
          bubbles: true,
          cancelable: true,
          ...modifiers
        };

        target.dispatchEvent(new KeyboardEvent('keydown', eventInit));
        if (resolvedKey.length === 1 || resolvedKey === 'Enter') {
          target.dispatchEvent(new KeyboardEvent('keypress', eventInit));
        }
        target.dispatchEvent(new KeyboardEvent('keyup', eventInit));

        // Hardened fallback for 'Enter' key press on form inputs
        if (resolvedKey === 'Enter') {
          const searchButton = target.form?.querySelector('button[type="submit"], input[type="submit"], button.cdx-search-input__end-button, button[aria-label="Search Wikipedia"]') ||
            target.parentElement?.querySelector('button, .search-button, .cdx-search-input__submit');

          if (searchButton && searchButton !== target) {
            searchButton.click();
          } else if (target.form && typeof target.form.submit === 'function') {
            try {
              target.form.submit();
            } catch (e) {
              if (HTMLFormElement.prototype.submit) {
                HTMLFormElement.prototype.submit.call(target.form);
              }
            }
          }
        }
      }
    }

    return { status: 'success' };
  }

  /* ─── Hover ─────────────────────────────────────────────────────────── */

  async function performHover(args) {
    if (isAnimating) {
      console.warn('[Galactic] Animation lock active, waiting...');
      await new Promise(r => {
        const start = Date.now();
        const check = setInterval(() => {
          if (!isAnimating || (Date.now() - start > 10000)) {
            clearInterval(check);
            r();
          }
        }, 100);
      });
    }
    isAnimating = true;
    try {
      showStatusPill('Hovering...');
      let el = null;

      if (args?.ref) {
        el = getElementByRef(args.ref);
      } else if (args?.selector) {
        el = document.querySelector(args.selector);
      } else if (args?.coordinate) {
        const [x, y] = args.coordinate;
        el = document.elementFromPoint(x, y);
      }

      if (!el) return { error: 'Element not found' };

      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      await new Promise(r => setTimeout(r, 100));

      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;

      // --- Custom Cursor Move ---
      moveCursor(cx, cy, getCursorType(el));
      await new Promise(r => setTimeout(r, 850));

      const eventOpts = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: cx,
        clientY: cy
      };

      el.dispatchEvent(new MouseEvent('mouseenter', { ...eventOpts, bubbles: false }));
      el.dispatchEvent(new MouseEvent('mouseover', eventOpts));
      el.dispatchEvent(new MouseEvent('mousemove', eventOpts));

      return { status: 'success' };
    } finally {
      isAnimating = false;
      hideStatusPill();
    }
  }

  /* ─── Right Click ───────────────────────────────────────────────────── */

  function performRightClick(args) {
    showStatusPill('Right Clicking...');
    let el = null;
    if (args?.ref) {
      el = getElementByRef(args.ref);
    } else if (args?.selector) {
      el = document.querySelector(args.selector);
    } else if (args?.x !== undefined && args?.y !== undefined) {
      el = document.elementFromPoint(args.x, args.y);
    }
    if (!el) return { error: 'Element not found' };

    const rect = el.getBoundingClientRect();
    const cx = args?.x !== undefined ? args.x : rect.left + rect.width / 2;
    const cy = args?.y !== undefined ? args.y : rect.top + rect.height / 2;

    el.dispatchEvent(new MouseEvent('mousedown', { clientX: cx, clientY: cy, button: 2, buttons: 2, bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { clientX: cx, clientY: cy, button: 2, buttons: 0, bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('contextmenu', { clientX: cx, clientY: cy, button: 2, bubbles: true, cancelable: true }));
    hideStatusPill();
    return { status: 'success' };
  }

  /* ─── Triple Click ───────────────────────────────────────────────────── */

  function performTripleClick(args) {
    showStatusPill('Triple Clicking...');
    let el = null;
    if (args?.ref) {
      el = getElementByRef(args.ref);
    } else if (args?.selector) {
      el = document.querySelector(args.selector);
    } else if (args?.x !== undefined && args?.y !== undefined) {
      el = document.elementFromPoint(args.x, args.y);
    }
    if (!el) return { error: 'Element not found' };

    el.focus();
    // Select all text: use execCommand for contenteditable, .select() for inputs
    if (el.contentEditable === 'true') {
      document.execCommand('selectAll', false, null);
    } else if (typeof el.select === 'function') {
      el.select();
    }
    // Dispatch triple-click events
    for (let i = 1; i <= 3; i++) {
      el.dispatchEvent(new MouseEvent('click', { detail: i, bubbles: true, cancelable: true }));
    }
    hideStatusPill();
    return { status: 'success' };
  }

  /* ─── Drag ──────────────────────────────────────────────────────────── */

  function performDrag(startX, startY, endX, endY) {
    showStatusPill('Dragging...');
    if (startX < 0 || startY < 0 || startX > window.innerWidth || startY > window.innerHeight) {
      return { success: false, error: `Start coordinates(${startX}, ${startY}) are off - screen.Viewport: ${window.innerWidth}x${window.innerHeight} ` };
    }
    const startEl = document.elementFromPoint(startX, startY);
    if (!startEl) return { success: false, error: 'No element at start coordinates' };

    function mouseEvt(type, x, y, target, buttons) {
      target.dispatchEvent(new MouseEvent(type, {
        clientX: x, clientY: y, screenX: x, screenY: y,
        bubbles: true, cancelable: true, view: window,
        buttons: buttons !== undefined ? buttons : (type === 'mouseup' ? 0 : 1),
        button: type === 'contextmenu' ? 2 : 0
      }));
    }

    mouseEvt('mousedown', startX, startY, startEl, 1);

    const steps = 10;
    for (let i = 1; i <= steps; i++) {
      const x = startX + (endX - startX) * i / steps;
      const y = startY + (endY - startY) * i / steps;
      const el = document.elementFromPoint(x, y) || startEl;
      mouseEvt('mousemove', x, y, el, 1);
    }

    const endEl = document.elementFromPoint(endX, endY) || startEl;
    mouseEvt('mouseup', endX, endY, endEl, 0);

    hideStatusPill();
    return { success: true };
  }

  /* ─── Get Page Text ─────────────────────────────────────────────────── */

  function getPageText() {
    const text = (document.body?.innerText || '').trim();
    return { status: 'success', text };
  }

  /* ─── Wait For ──────────────────────────────────────────────────────── */

  async function waitFor(args) {
    const selector = args?.selector;
    const text = args?.text;
    const timeout = args?.timeout || 10000;
    const interval = 250;
    const start = Date.now();

    return new Promise((resolve) => {
      const check = () => {
        let found = false;
        if (selector) {
          const el = document.querySelector(selector);
          if (el && isVisible(el)) found = true;
        } else if (text) {
          if (document.body.innerText.includes(text)) found = true;
        }

        if (found) {
          resolve({ status: 'success' });
        } else if (Date.now() - start > timeout) {
          resolve({ status: 'timeout', message: `Timed out waiting for ${selector || text}` });
        } else {
          setTimeout(check, interval);
        }
      };
      check();
    });
  }

  /* ─── Command Dispatcher ────────────────────────────────────────────── */

  async function handleCommand(command, args) {
    switch (command) {
      case 'snapshot':
      case 'read_page': return buildSnapshot(args);
      case 'find':
      case 'find_element': return findElements(args);
      case 'wait_for': return await waitFor(args);
      case 'click': return await performClick(args);
      case 'type':
      case 'type_text': return await performType(args);
      case 'scroll':
      case 'scroll_page': return await performScroll(args);
      case 'form_input': return performFormInput(args);
      case 'key_press': return performKeyPress(args);
      case 'hover': return await performHover(args);
      case 'drag': return performDrag(args?.start_x, args?.start_y, args?.end_x, args?.end_y);
      case 'right_click': return performRightClick(args);
      case 'triple_click': return performTripleClick(args);
      case 'get_text':
      case 'get_page_text': return getPageText();
      case 'get_dom': return getPageDom();
      case 'show_status': return showStatusPill(args?.text || 'Working...');
      case 'hide_status':
        hideCursor();
        return hideStatusPill();
      case 'resolve_ref':
        if (!args?.ref) return { error: 'No ref provided' };
        const el = getElementByRef(args.ref);
        if (!el) return { error: `Ref not found: ${args.ref} ` };
        /* Generate a unique attribute-based selector by temporarily tagging the element */
        const uid = `gal_${Date.now()}_${Math.random().toString(36).slice(2, 7)} `;
        el.setAttribute('data-galactic-uid', uid);
        return { status: 'success', selector: `[data - galactic - uid= "${uid}"]` };
      default: return { error: `Unknown content command: ${command} ` };
    }
  }

  /* ─── Message Listener ──────────────────────────────────────────────── */

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'galactic') {
      handleCommand(msg.command, msg.args)
        .then(result => sendResponse({ result }))
        .catch(err => {
          console.error('[Galactic] Command error:', err);
          sendResponse({ error: err.message || 'Unknown error' });
        });
      return true; /* Keep channel open for async response */
    }
  });
})();
