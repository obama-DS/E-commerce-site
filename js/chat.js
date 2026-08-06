/**
 * chat.js — "Obama", hybrid AI assistant widget.
 *
 * Backend contract: POST /api/chat
 *   Request:  { message, history, session_id, cart }
 *   Response: { reply, suggestions, cards, flow, session_id, action }
 *
 * Card types supported:
 *   product    — image, price, rating, add-to-cart, view
 *   car        — image, specs, value tag, view recommendations
 *   compare    — side-by-side product comparison table
 *   categories — category grid chips
 *   order      — order status badge (future)
 */
(function () {
  'use strict';

  var SESSION_KEY = 'obama-store-chat-session';
  var HISTORY_KEY  = 'obama-store-chat-history';

  var sessionId = null;
  var history   = [];
  var busy      = false;

  var FLOW_LABELS = { budget: 'Budget', fuel: 'Fuel type', transmission: 'Transmission' };
  var FLOW_ORDER  = { budget: 1, fuel: 2, transmission: 3 };

  /* ================================================================
     HELPERS
     ================================================================ */

  function escapeHtml(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function loadSession() {
    try { sessionId = localStorage.getItem(SESSION_KEY); } catch (e) { sessionId = null; }
  }
  function saveSession() {
    try { if (sessionId) localStorage.setItem(SESSION_KEY, sessionId); } catch (e) { /* ignore */ }
  }
  function loadHistory() {
    try { history = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]'); } catch (e) { history = []; }
    if (!Array.isArray(history)) history = [];
  }
  function saveHistory() {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-40))); } catch (e) { /* ignore */ }
  }

  function scrollToBottom() {
    var el = document.getElementById('chatMessages');
    if (el) el.scrollTop = el.scrollHeight;
  }

  function timestamp() {
    var n = new Date();
    return n.getHours() + ':' + String(n.getMinutes()).padStart(2, '0');
  }

  /* ================================================================
     MARKDOWN RENDERER
     Supports: **bold**, *italic*, `code`, ### headers,
               - / * unordered lists, 1. ordered lists,
               [text](url) links, \n line breaks.
     ================================================================ */

  function renderMarkdown(text) {
    if (!text) return '';
    var t = escapeHtml(text);

    // Fenced code blocks (```...```)
    t = t.replace(/```([^`]*?)```/gs, function (_, code) {
      return '<pre class="chat-code"><code>' + code.trim() + '</code></pre>';
    });

    // Inline code
    t = t.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');

    // Links [label](url)
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener" class="chat-link">$1</a>');

    // Split into paragraphs / list blocks
    var lines = t.split('\n');
    var out = [];
    var inList = null;  // 'ul' | 'ol' | null

    function closeList() {
      if (inList) { out.push('</' + inList + '>'); inList = null; }
    }

    lines.forEach(function (rawLine) {
      var line = rawLine.trimEnd();

      // Heading ### / ## / #
      var headMatch = line.match(/^(#{1,3})\s+(.+)$/);
      if (headMatch) {
        closeList();
        var level = Math.min(headMatch[1].length + 3, 6); // h4-h6 to not overshadow page
        out.push('<h' + level + ' class="chat-heading">' + inlineStyles(headMatch[2]) + '</h' + level + '>');
        return;
      }

      // Unordered list item
      var ulMatch = line.match(/^[-*+]\s+(.+)$/);
      if (ulMatch) {
        if (inList !== 'ul') { closeList(); out.push('<ul class="chat-list">'); inList = 'ul'; }
        out.push('<li>' + inlineStyles(ulMatch[1]) + '</li>');
        return;
      }

      // Ordered list item
      var olMatch = line.match(/^\d+[.)]\s+(.+)$/);
      if (olMatch) {
        if (inList !== 'ol') { closeList(); out.push('<ol class="chat-list">'); inList = 'ol'; }
        out.push('<li>' + inlineStyles(olMatch[1]) + '</li>');
        return;
      }

      // Horizontal rule
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
        closeList();
        out.push('<hr class="chat-hr">');
        return;
      }

      // Empty line — close list, add spacing
      if (!line.trim()) {
        closeList();
        out.push('<div class="chat-para-gap"></div>');
        return;
      }

      // Normal text line
      closeList();
      out.push('<span class="chat-line">' + inlineStyles(line) + '</span><br>');
    });

    closeList();
    return out.join('');
  }

  function inlineStyles(s) {
    // Bold+italic ***text***
    s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
    // Bold **text**
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italic *text*
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Inline code (already escaped, skip double-escape)
    return s;
  }

  /* ================================================================
     CARD RENDERING
     ================================================================ */

  function productCardHtml(card) {
    var badge = card.badge
      ? '<span class="chat-card-badge">' + escapeHtml(card.badge) + '</span>' : '';
    var meta = [];
    if (card.rating)    meta.push('★ ' + escapeHtml(card.rating) + (card.reviewCount ? ' (' + escapeHtml(card.reviewCount) + ')' : ''));
    if (card.discount)  meta.push(escapeHtml(card.discount) + '% off');
    if (card.stock != null) meta.push(escapeHtml(card.stock) + ' in stock');
    return (
      '<div class="chat-card chat-card-product" data-id="' + escapeHtml(card.id || '') + '">' +
        '<div class="chat-card-media">' +
          (card.image ? '<img src="' + escapeHtml(card.image) + '" alt="' + escapeHtml(card.title || '') + '" loading="lazy" onerror="this.parentNode.classList.add(\'no-img\')">' : '') +
          badge +
        '</div>' +
        '<div class="chat-card-body">' +
          '<span class="chat-card-cat">' + escapeHtml(card.category || '') + '</span>' +
          '<h4 class="chat-card-title">' + escapeHtml(card.title || '') + '</h4>' +
          (card.shortDescription ? '<p class="chat-card-desc">' + escapeHtml(card.shortDescription) + '</p>' : '') +
          '<div class="chat-card-price">' + escapeHtml(card.priceText || '') + '</div>' +
          (meta.length ? '<div class="chat-card-meta">' + meta.join(' · ') + '</div>' : '') +
          '<div class="chat-card-actions">' +
            '<button type="button" class="chat-card-btn" data-action="view">View</button>' +
            '<button type="button" class="chat-card-btn primary" data-action="cart"' +
              ' data-title="' + escapeHtml(card.title || '') + '"' +
              ' data-price="' + escapeHtml(card.priceText || '') + '">Add to cart</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function carCardHtml(card) {
    var tag = card.valueTag
      ? '<span class="chat-card-tag ' +
          (card.valueTag === 'Great deal' ? 'is-good' : card.valueTag === 'Priced high' ? 'is-high' : 'is-fair') +
          '">' + escapeHtml(card.valueTag) + '</span>'
      : '';
    var specs = [];
    if (card.fuel)         specs.push('<span>⛽ ' + escapeHtml(card.fuel) + '</span>');
    if (card.transmission) specs.push('<span>⚙️ ' + escapeHtml(card.transmission) + '</span>');
    if (card.km != null)   specs.push('<span>📏 ' + Number(card.km).toLocaleString() + ' km</span>');
    if (card.owner)        specs.push('<span>👤 ' + escapeHtml(card.owner) + '</span>');
    return (
      '<div class="chat-card chat-card-car">' +
        '<div class="chat-card-media">' +
          (card.image ? '<img src="' + escapeHtml(card.image) + '" alt="' + escapeHtml(card.title || '') + '" loading="lazy" onerror="this.parentNode.classList.add(\'no-img\')">' : '') +
          tag +
        '</div>' +
        '<div class="chat-card-body">' +
          '<h4 class="chat-card-title">' + escapeHtml(card.title || '') +
            (card.year ? ' <small>' + escapeHtml(card.year) + '</small>' : '') + '</h4>' +
          '<div class="chat-card-price">' + escapeHtml(card.priceText || '') + '</div>' +
          (specs.length ? '<div class="chat-card-specs">' + specs.join('') + '</div>' : '') +
          (card.valueTag && card.predictedText
            ? '<div class="chat-card-meta">Fair price ~ ' + escapeHtml(card.predictedText) + '</div>' : '') +
          '<div class="chat-card-actions">' +
            '<button type="button" class="chat-card-btn primary" data-action="cars">View recommendations</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function compareCardHtml(card) {
    var products = card.products || [];
    if (products.length < 2) return '';
    var headers = products.map(function (p) {
      return '<th>' +
        (p.image ? '<img src="' + escapeHtml(p.image) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' : '') +
        '<div class="cmp-name">' + escapeHtml(p.title) + '</div>' +
        (p.badge ? '<span class="chat-card-badge">' + escapeHtml(p.badge) + '</span>' : '') +
        '</th>';
    }).join('');

    var rows = [
      { label: 'Price',    key: 'priceText' },
      { label: 'Rating',   fn: function (p) { return p.rating ? '★ ' + p.rating + ' (' + (p.reviewCount || 0) + ')' : '—'; } },
      { label: 'Discount', fn: function (p) { return p.discount ? p.discount + '% off' : '—'; } },
      { label: 'Stock',    fn: function (p) { return p.stock != null ? p.stock + ' units' : '—'; } },
      { label: 'Info',     key: 'shortDescription' },
    ];

    var rowsHtml = rows.map(function (row) {
      var cells = products.map(function (p) {
        var val = row.fn ? row.fn(p) : (p[row.key] || '—');
        return '<td>' + escapeHtml(String(val)) + '</td>';
      }).join('');
      return '<tr><td class="cmp-label">' + escapeHtml(row.label) + '</td>' + cells + '</tr>';
    }).join('');

    var actionCells = products.map(function (p) {
      return '<td>' +
        '<button type="button" class="chat-card-btn primary cmp-add" data-action="cart"' +
          ' data-title="' + escapeHtml(p.title) + '"' +
          ' data-price="' + escapeHtml(p.priceText || '') + '"' +
          ' data-id="' + escapeHtml(p.id || '') + '">Add</button>' +
        '</td>';
    }).join('');

    return (
      '<div class="chat-compare-card">' +
        '<div class="chat-compare-title">Side-by-side comparison</div>' +
        '<div class="chat-compare-scroll">' +
          '<table class="chat-compare-table">' +
            '<thead><tr><th class="cmp-label"></th>' + headers + '</tr></thead>' +
            '<tbody>' + rowsHtml + '</tbody>' +
            '<tfoot><tr><td></td>' + actionCells + '</tr></tfoot>' +
          '</table>' +
        '</div>' +
      '</div>'
    );
  }

  function categoriesCardHtml(card) {
    var cats = card.categories || [];
    var chips = cats.map(function (c) {
      var icon = { Cars: '🚗', Electronics: '💻', Mobile: '📱',
                   Fashion: '👕', Wearables: '⌚', Accessories: '🎧' }[c.name] || '🏪';
      return '<button type="button" class="chat-cat-chip" data-category="' + escapeHtml(c.name) + '">' +
               icon + ' ' + escapeHtml(c.name) +
               (c.count ? '<span class="chat-cat-count">' + c.count + '</span>' : '') +
             '</button>';
    }).join('');
    return '<div class="chat-categories-card"><div class="chat-categories-label">Browse by category</div><div class="chat-categories-grid">' + chips + '</div></div>';
  }

  function orderStatusCardHtml(card) {
    var statusClass = { delivered: 'status-done', shipped: 'status-ship',
                        processing: 'status-proc', cancelled: 'status-cancel' }[card.status] || 'status-proc';
    return (
      '<div class="chat-order-card">' +
        '<div class="chat-order-id">Order ' + escapeHtml(card.orderId || '#—') + '</div>' +
        '<div class="chat-order-status ' + statusClass + '">' + escapeHtml(card.statusLabel || card.status || 'Processing') + '</div>' +
        (card.eta ? '<div class="chat-order-eta">Estimated delivery: ' + escapeHtml(card.eta) + '</div>' : '') +
      '</div>'
    );
  }

  function singleCardHtml(card) {
    if (!card || !card.type) return '';
    if (card.type === 'compare')    return compareCardHtml(card);
    if (card.type === 'categories') return categoriesCardHtml(card);
    if (card.type === 'order')      return orderStatusCardHtml(card);
    if (card.type === 'car')        return carCardHtml(card);
    return productCardHtml(card);
  }

  function cardsHtml(cards) {
    if (!cards || !cards.length) return '';

    // Separate special full-width cards from scrollable product/car cards
    var special = cards.filter(function (c) {
      return c.type === 'compare' || c.type === 'categories' || c.type === 'order';
    });
    var inline = cards.filter(function (c) {
      return c.type === 'product' || c.type === 'car';
    });

    var html = '';
    special.forEach(function (c) { html += singleCardHtml(c); });
    if (inline.length) {
      html += '<div class="chat-card-row">';
      inline.forEach(function (c) { html += singleCardHtml(c); });
      html += '</div>';
    }
    return html;
  }

  /* ================================================================
     MESSAGE RENDERING
     ================================================================ */

  function appendMessage(role, text, cards) {
    var messages = document.getElementById('chatMessages');
    if (!messages) return;
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-msg ' + (role === 'user' ? 'user' : 'assistant');

    var bubbleContent = role === 'assistant' ? renderMarkdown(text) : escapeHtml(text);
    wrapper.innerHTML =
      '<div class="chat-bubble">' + bubbleContent + '</div>' +
      (cards && cards.length ? cardsHtml(cards) : '') +
      '<span class="chat-time">' + timestamp() + '</span>';

    messages.appendChild(wrapper);
    attachCardActions(wrapper);
    scrollToBottom();
  }

  function showTyping() {
    var messages = document.getElementById('chatMessages');
    if (!messages) return null;
    var el = document.createElement('div');
    el.className = 'chat-msg assistant typing';
    el.innerHTML = '<div class="chat-bubble typing-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
    messages.appendChild(el);
    scrollToBottom();
    return el;
  }

  function hideTyping(node) {
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  /* ================================================================
     CHIPS / FLOW TRAY
     ================================================================ */

  function renderSuggestions(list) {
    var quick = document.getElementById('chatQuick');
    if (!quick) return;
    quick.innerHTML = '';
    (list || []).slice(0, 5).forEach(function (s) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chat-chip';
      chip.textContent = s;
      chip.addEventListener('click', function () { send(s); });
      quick.appendChild(chip);
    });
  }

  function renderFlow(flow) {
    var tray = document.getElementById('chatFlow');
    if (!tray) return;
    if (!flow || !flow.step) { tray.hidden = true; tray.innerHTML = ''; return; }
    var label  = FLOW_LABELS[flow.step] || flow.step;
    var number = FLOW_ORDER[flow.step] || 1;
    var opts   = (flow.options || []).map(function (o) {
      return '<button type="button" class="chat-flow-opt" data-value="' + escapeHtml(o) + '">' + escapeHtml(o) + '</button>';
    }).join('');
    tray.hidden = false;
    tray.innerHTML =
      '<div class="chat-flow-head">' +
        '<span class="chat-flow-title">Step ' + number + ' of 3 · ' + escapeHtml(label) + '</span>' +
        '<button type="button" class="chat-flow-reset" id="chatFlowReset">Restart</button>' +
      '</div>' +
      '<div class="chat-flow-options">' + opts + '</div>';
    tray.querySelectorAll('.chat-flow-opt').forEach(function (b) {
      b.addEventListener('click', function () { send(b.dataset.value); });
    });
    var reset = document.getElementById('chatFlowReset');
    if (reset) reset.addEventListener('click', function () { send('cancel'); });
  }

  /* ================================================================
     CART SYNC — reads window.StoreHelpers cart for get_cart_summary
     ================================================================ */

  function getCartItems() {
    try {
      var helpers = window.StoreHelpers;
      if (helpers && typeof helpers.getCartItems === 'function') {
        return helpers.getCartItems() || [];
      }
      // Fallback: read cartEntries from store.js global if exposed
      if (window._cartEntries && Array.isArray(window._cartEntries)) {
        return window._cartEntries;
      }
    } catch (e) { /* ignore */ }
    return [];
  }

  /* ================================================================
     SEND
     ================================================================ */

  function send(text) {
    if (busy) return;
    var message = String(text || '').trim();
    if (!message) return;

    var input = document.getElementById('chatInput');
    if (input) input.value = '';
    renderSuggestions([]);

    appendMessage('user', message);
    history.push({ role: 'user', content: message });
    saveHistory();

    busy = true;
    var typing = showTyping();

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: history.slice(-20),
        session_id: sessionId || '',
        cart: getCartItems(),           // sync current cart for get_cart_summary
      })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.session_id) { sessionId = data.session_id; saveSession(); }
        hideTyping(typing);
        appendMessage('assistant', data.reply || '', data.cards || []);
        history.push({ role: 'assistant', content: data.reply || '' });
        saveHistory();
        renderFlow(data.flow || null);
        renderSuggestions(data.suggestions || []);
        handleAction(data.action || null);
      })
      .catch(function () {
        hideTyping(typing);
        appendMessage('assistant', 'Sorry, I hit a network snag. 📡 Check your connection and try again.');
      })
      .finally(function () { busy = false; });
  }

  /* ================================================================
     ACTION HANDLING (from backend action field)
     ================================================================ */

  function handleAction(action) {
    if (!action || !action.type) return;
    var helpers = window.StoreHelpers;
    var router  = window.AppRouter;

    if (action.type === 'add_to_cart') {
      if (helpers && helpers.addItemToCart) {
        helpers.addItemToCart(action.title, action.priceText);
        if (action.openProduct && action.productId) {
          if (helpers.closeCart) helpers.closeCart();
          if (router) router.navigate('product', { id: action.productId });
          closeChat();
        }
      }
      return;
    }

    if (action.type === 'open_product' && action.productId) {
      if (router) router.navigate('product', { id: action.productId });
      closeChat();
      return;
    }

    if (action.type === 'open_products' && action.category) {
      if (router) router.navigate('products', { category: action.category });
      closeChat();
      return;
    }

    if (action.type === 'open_recommendations') {
      if (router) router.navigate('recommendations');
      closeChat();
      return;
    }
  }

  /* ================================================================
     CARD CLICK DELEGATION
     ================================================================ */

  function attachCardActions(root) {
    var container = root || document.getElementById('chatMessages');
    if (!container) return;
    container.querySelectorAll('.chat-card-btn, .chat-cat-chip, .cmp-add').forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.dataset.bound = 'true';

      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var action = btn.dataset.action;
        var helpers = window.StoreHelpers;

        // Category chip → navigate to products page filtered by category
        if (btn.classList.contains('chat-cat-chip')) {
          var cat = btn.dataset.category;
          if (cat) {
            if (window.AppRouter) window.AppRouter.navigate('products', { category: cat });
            closeChat();
          }
          return;
        }

        if (action === 'cart' || btn.classList.contains('cmp-add')) {
          if (helpers && helpers.addItemToCart) {
            helpers.addItemToCart(btn.dataset.title, btn.dataset.price);
            // visual feedback
            var orig = btn.textContent;
            btn.textContent = '✓ Added';
            btn.disabled = true;
            setTimeout(function () { btn.textContent = orig; btn.disabled = false; }, 1800);
          }
          return;
        }

        if (action === 'view') {
          var card = btn.closest('.chat-card');
          var id   = card && card.dataset.id;
          if (id && window.AppRouter) window.AppRouter.navigate('product', { id: id });
          closeChat();
          return;
        }

        if (action === 'cars') {
          if (window.AppRouter) window.AppRouter.navigate('recommendations');
          closeChat();
          return;
        }
      });
    });
  }

  /* ================================================================
     OPEN / CLOSE
     ================================================================ */

  function openChat() {
    var widget   = document.getElementById('chatWidget');
    var launcher = document.getElementById('chatLauncher');
    var badge    = document.getElementById('chatLauncherBadge');
    if (widget)   widget.classList.add('is-open');
    if (launcher) launcher.setAttribute('aria-expanded', 'true');
    if (widget)   widget.setAttribute('aria-hidden', 'false');
    if (badge)    badge.hidden = true;

    var messages = document.getElementById('chatMessages');
    if (messages) messages.innerHTML = '';

    if (!history.length) {
      appendMessage('assistant',
        "Hi! I'm **Obama**, your store assistant. 🤖\n\n" +
        "I can help you:\n" +
        "- Find products and check prices\n" +
        "- Recommend cars within your budget\n" +
        "- Compare products side-by-side\n" +
        "- Answer questions about delivery, payment, returns\n" +
        "- Or just chat about anything!\n\n" +
        "What would you like to do?"
      );
      renderSuggestions(["What's trending?", 'Recommend a car', 'Show me categories', 'What can you do?']);
    } else {
      history.forEach(function (msg) {
        appendMessage(msg.role, msg.content);
      });
      scrollToBottom();
    }

    var input = document.getElementById('chatInput');
    if (input) setTimeout(function () { input.focus(); }, 60);
  }

  function closeChat() {
    var widget   = document.getElementById('chatWidget');
    var launcher = document.getElementById('chatLauncher');
    if (widget)   widget.classList.remove('is-open');
    if (launcher) launcher.setAttribute('aria-expanded', 'false');
    if (widget)   widget.setAttribute('aria-hidden', 'true');
  }

  /* ================================================================
     INIT
     ================================================================ */

  function init() {
    loadSession();
    loadHistory();

    var launcher = document.getElementById('chatLauncher');
    if (launcher) {
      launcher.addEventListener('click', function () {
        var widget = document.getElementById('chatWidget');
        if (widget && widget.classList.contains('is-open')) closeChat();
        else openChat();
      });
    }

    var closeBtn = document.getElementById('chatCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', closeChat);

    var form = document.getElementById('chatForm');
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = document.getElementById('chatInput');
        send(input ? input.value : '');
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeChat();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
