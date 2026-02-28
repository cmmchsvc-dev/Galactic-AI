/**
 * Galactic Browser - Content Script
 * Injected into every page. Handles DOM inspection, interaction, and element tracking.
 */

(() => {
  /* Prevent double-injection */
  if (window.__galacticContentLoaded) return;
  window.__galacticContentLoaded = true;

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
      signature += `#${el.id}`;
      return signature; // If it has an ID, that's usually unique enough
    }

    // Classes are moderately stable
    if (el.className && typeof el.className === 'string') {
        const classes = el.className.split(' ').filter(c => c).sort().join('.');
        if (classes) signature += `.${classes}`;
    }

    // Role and Aria labels
    const role = el.getAttribute('role');
    if (role) signature += `[role=${role}]`;
    
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) signature += `[aria=${ariaLabel.substring(0, 15)}]`;
    
    // Form attributes
    if (el.name) signature += `[name=${el.name}]`;
    if (el.type) signature += `[type=${el.type}]`;
    
    // Add text content (truncated) as a strong differentiator for links/buttons
    const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
    if (text && text.length < 50) {
        signature += `|${text}`;
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
      path = `/${current.tagName.toLowerCase()}[${index}]${path}`;
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
    let refId = `ref_${hash}`;

    // Handle extremely rare collisions by appending a counter
    let counter = 1;
    while (refMap.has(refId) && refMap.get(refId) !== element) {
        refId = `ref_${hash}_${counter}`;
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
    /* Quick checks */
    if (el.hidden) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none') return false;
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    if (parseFloat(style.opacity) === 0) return false;
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
        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
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
        let line = `${indent}- ${role || tag}`;

        /* Add name */
        if (name) {
          line += ` "${name}"`;
        }

        /* Ref for interactive elements */
        if (interactive) {
          const refId = assignRef(el);
          line += ` [ref=${refId}]`;
        }

        /* Extra attributes */
        if (role === 'heading') {
          const level = el.tagName.match(/H(\d)/)?.[1];
          if (level) line += ` level=${level}`;
        }

        if (role === 'link' && el.href) {
          line += ` url="${el.getAttribute('href') || ''}"`;
        }

        if ((role === 'textbox' || role === 'combobox' || role === 'searchbox' || role === 'spinbutton') && el.value !== undefined) {
          line += ` value="${el.value}"`;
        }

        if (role === 'checkbox' || role === 'radio') {
          line += ` checked=${el.checked}`;
        }

        if (el.disabled) {
          line += ` disabled`;
        }

        if (el.getAttribute('aria-expanded') !== null) {
          line += ` expanded=${el.getAttribute('aria-expanded')}`;
        }

        if (el.getAttribute('aria-selected') !== null) {
          line += ` selected=${el.getAttribute('aria-selected')}`;
        }

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
            lines.push(`${indent}- text "${text}"`);
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
        return { error: `Invalid CSS selector: ${selector}` };
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

  function performClick(args) {
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

    /* Scroll into view if needed */
    el.scrollIntoView({ block: 'center', behavior: 'instant' });

    /* Dispatch proper mouse events */
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
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
      el.dispatchEvent(new MouseEvent('dblclick', { ...eventOpts, button: 0 }));
    }

    return { status: 'success' };
  }

  /* ─── Type ──────────────────────────────────────────────────────────── */

  function performType(args) {
    let el = null;

    if (args?.ref) {
      el = getElementByRef(args.ref);
    } else if (args?.selector) {
      el = document.querySelector(args.selector);
    }

    if (!el) return { error: 'Element not found' };

    const shouldClear = args?.clear !== false; // default: true

    el.focus();

    /* PRE-CLEAR: only for value-based inputs (contenteditable is cleared via execCommand below) */
    if (shouldClear && 'value' in el) {
      el.value = '';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    const text = args?.text || '';

    if ('value' in el) {
      /* Standard input/textarea */
      el.value = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (el.contentEditable === 'true') {
      // Select and clear existing content if clear is requested
      if (shouldClear) {
        document.execCommand('selectAll', false, null);
        document.execCommand('delete', false, null);
      }

      // Modern SPAs (X.com, Notion) need the 'beforeinput' event to prepare their state
      el.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: text
      }));

      // insertText fires the InputEvent with inputType='insertText'
      const inserted = document.execCommand('insertText', false, text);
      
      if (!inserted) {
        // execCommand fallback
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const range = sel.getRangeAt(0);
          range.deleteContents();
          range.insertNode(document.createTextNode(text));
          range.collapse(false);
        } else {
          el.insertAdjacentText('beforeend', text);
        }
      }

      // Force an 'input' event which is critical for React/Vue state updates
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: text
      }));

      // X.com specifically often needs a KeyboardEvent to trigger the "Post" button activation
      el.dispatchEvent(new KeyboardEvent('keyup', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true
      }));

      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      /* Fallback: dispatch key events character by character */
      for (const char of text) {
        el.dispatchEvent(new KeyboardEvent('keydown', { key: char, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keypress', { key: char, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key: char, bubbles: true }));
      }
    }

    return { status: 'success' };
  }

  /* ─── Scroll ────────────────────────────────────────────────────────── */

  function performScroll(args) {
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

    /* Page scroll by direction */
    const direction = (args?.direction || 'down').toLowerCase();
    const amount = args?.amount || 3;
    const pixels = amount * 100;

    switch (direction) {
      case 'up':    window.scrollBy(0, -pixels); break;
      case 'down':  window.scrollBy(0, pixels); break;
      case 'left':  window.scrollBy(-pixels, 0); break;
      case 'right': window.scrollBy(pixels, 0); break;
      default:      window.scrollBy(0, pixels); break;
    }

    return { status: 'success' };
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
          code: resolvedKey.length === 1 ? `Key${resolvedKey.toUpperCase()}` : resolvedKey,
          bubbles: true,
          cancelable: true,
          ...modifiers
        };

        target.dispatchEvent(new KeyboardEvent('keydown', eventInit));
        if (resolvedKey.length === 1) {
          target.dispatchEvent(new KeyboardEvent('keypress', eventInit));
        }
        target.dispatchEvent(new KeyboardEvent('keyup', eventInit));
      }
    }

    return { status: 'success' };
  }

  /* ─── Hover ─────────────────────────────────────────────────────────── */

  function performHover(args) {
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

    el.scrollIntoView({ block: 'center', behavior: 'instant' });

    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
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
  }

  /* ─── Right Click ───────────────────────────────────────────────────── */

  function performRightClick(args) {
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
    el.dispatchEvent(new MouseEvent('mouseup',   { clientX: cx, clientY: cy, button: 2, buttons: 0, bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('contextmenu', { clientX: cx, clientY: cy, button: 2, bubbles: true, cancelable: true }));
    return { status: 'success' };
  }

  /* ─── Triple Click ───────────────────────────────────────────────────── */

  function performTripleClick(args) {
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
    return { status: 'success' };
  }

  /* ─── Drag ──────────────────────────────────────────────────────────── */

  function performDrag(startX, startY, endX, endY) {
    if (startX < 0 || startY < 0 || startX > window.innerWidth || startY > window.innerHeight) {
      return { success: false, error: `Start coordinates (${startX}, ${startY}) are off-screen. Viewport: ${window.innerWidth}x${window.innerHeight}` };
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
      case 'snapshot':    return buildSnapshot(args);
      case 'find':        return findElements(args);
      case 'wait_for':    return await waitFor(args);
      case 'click':       return performClick(args);
      case 'type':        return performType(args);
      case 'scroll':      return performScroll(args);
      case 'form_input':  return performFormInput(args);
      case 'key_press':   return performKeyPress(args);
      case 'hover':        return performHover(args);
      case 'drag':         return performDrag(args?.start_x, args?.start_y, args?.end_x, args?.end_y);
      case 'right_click':  return performRightClick(args);
      case 'triple_click': return performTripleClick(args);
      case 'get_text':     return getPageText();
      case 'resolve_ref':
        if (!args?.ref) return { error: 'No ref provided' };
        const el = getElementByRef(args.ref);
        if (!el) return { error: `Ref not found: ${args.ref}` };
        /* Generate a unique attribute-based selector by temporarily tagging the element */
        const uid = `gal_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
        el.setAttribute('data-galactic-uid', uid);
        return { status: 'success', selector: `[data-galactic-uid="${uid}"]` };
      default:            return { error: `Unknown content command: ${command}` };
    }
  }

  /* ─── Message Listener ──────────────────────────────────────────────── */

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'galactic') {
      handleCommand(msg.command, msg.args)
        .then(result => sendResponse({ result }))
        .catch(err => sendResponse({ error: err.message }));
      return true; /* Keep channel open for async response */
    }
  });
})();
