/**
 * chat.js — "Obama", the store's interactive AI assistant widget.
 *
 * Talks to POST /api/chat (contract: {message, history, session_id} ->
 * {reply, suggestions, cards, flow, session_id}).
 *
 * UI features:
 *  - message bubbles with markdown-lite (bold + newlines)
 *  - rich product cards (image, price, add-to-cart, view)
 *  - rich car spec cards (image, specs, value tag, view)
 *  - multi-step "flow" picker tray (budget -> fuel -> transmission)
 *  - quick-reply chips, typing indicator, timestamps
 *  - per-tab session id + conversation history persistence
 */
(function () {
  'use strict';

  var SESSION_KEY = 'obama-store-chat-session';
  var HISTORY_KEY = 'obama-store-chat-history';

  var sessionId = null;
  var history = [];
  var busy = false;

  var FLOW_LABELS = { budget: 'Budget', fuel: 'Fuel type', transmission: 'Transmission' };
  var FLOW_ORDER = { budget: 1, fuel: 2, transmission: 3 };

  /* ---- helpers ---------------------------------------------------- */

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function loadSession() {
    try {
      sessionId = localStorage.getItem(SESSION_KEY);
    } catch (error) {
      sessionId = null;
    }
  }

  function saveSession() {
    try {
      if (sessionId) localStorage.setItem(SESSION_KEY, sessionId);
    } catch (error) {
      /* ignore */
    }
  }

  function loadHistory() {
    try {
      history = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
    } catch (error) {
      history = [];
    }
    if (!Array.isArray(history)) history = [];
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-40)));
    } catch (error) {
      /* ignore */
    }
  }

  function scrollToBottom() {
    var messages = document.getElementById('chatMessages');
    if (messages) messages.scrollTop = messages.scrollHeight;
  }

  function timestamp() {
    var now = new Date();
    var hours = now.getHours();
    var minutes = String(now.getMinutes()).padStart(2, '0');
    return hours + ':' + minutes;
  }

  /* ---- text rendering --------------------------------------------- */

  function renderInline(text) {
    var escaped = escapeHtml(text);
    escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/\n/g, '<br>');
    return '<span>' + escaped + '</span>';
  }

  /* ---- card rendering --------------------------------------------- */

  function productCardHtml(card) {
    var image = card.image ? card.image : '';
    var badge = card.badge
      ? '<span class="chat-card-badge">' + escapeHtml(card.badge) + '</span>'
      : '';
    var meta = [];
    if (card.rating) meta.push('★ ' + escapeHtml(card.rating) + (card.reviewCount ? ' (' + escapeHtml(card.reviewCount) + ')' : ''));
    if (card.discount) meta.push(escapeHtml(card.discount) + '% off');
    if (card.stock != null) meta.push(escapeHtml(card.stock) + ' in stock');
    var priceHtml = card.priceText ? escapeHtml(card.priceText) : '';
    return (
      '<div class="chat-card chat-card-product" data-id="' + escapeHtml(card.id || '') + '">' +
        '<div class="chat-card-media">' +
          (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(card.title || '') + '" loading="lazy" onerror="this.parentNode.classList.add(\'no-img\')">' : '') +
          badge +
        '</div>' +
        '<div class="chat-card-body">' +
          '<span class="chat-card-cat">' + escapeHtml(card.category || '') + '</span>' +
          '<h4 class="chat-card-title">' + escapeHtml(card.title || '') + '</h4>' +
          '<div class="chat-card-price">' + priceHtml + '</div>' +
          (meta.length ? '<div class="chat-card-meta">' + meta.join(' · ') + '</div>' : '') +
          '<div class="chat-card-actions">' +
            '<button type="button" class="chat-card-btn" data-action="view">View</button>' +
            '<button type="button" class="chat-card-btn primary" data-action="cart" data-title="' + escapeHtml(card.title || '') + '" data-price="' + escapeHtml(card.priceText || '') + '">Add to cart</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function carCardHtml(card) {
    var image = card.image ? card.image : '';
    var tag = card.valueTag
      ? '<span class="chat-card-tag ' + (card.valueTag === 'Great deal' ? 'is-good' : card.valueTag === 'Priced high' ? 'is-high' : 'is-fair') + '">' + escapeHtml(card.valueTag) + '</span>'
      : '';
    var specs = [];
    if (card.fuel) specs.push('⛽ ' + escapeHtml(card.fuel));
    if (card.transmission) specs.push('⚙️ ' + escapeHtml(card.transmission));
    if (card.km != null) specs.push('📏 ' + Number(card.km).toLocaleString() + ' km');
    if (card.owner) specs.push('👤 ' + escapeHtml(card.owner));
    return (
      '<div class="chat-card chat-card-car">' +
        '<div class="chat-card-media">' +
          (image ? '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(card.title || '') + '" loading="lazy" onerror="this.parentNode.classList.add(\'no-img\')">' : '') +
          tag +
        '</div>' +
        '<div class="chat-card-body">' +
          '<h4 class="chat-card-title">' + escapeHtml(card.title || '') + (card.year ? ' <small>' + escapeHtml(card.year) + '</small>' : '') + '</h4>' +
          '<div class="chat-card-price">' + escapeHtml(card.priceText || '') + '</div>' +
          (specs.length ? '<div class="chat-card-specs">' + specs.join('') + '</div>' : '') +
          (card.valueTag && card.predictedText ? '<div class="chat-card-meta">Fair price ~ ' + escapeHtml(card.predictedText) + '</div>' : '') +
          '<div class="chat-card-actions">' +
            '<button type="button" class="chat-card-btn primary" data-action="cars">View recommendations</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function cardsHtml(cards) {
    if (!cards || !cards.length) return '';
    var html = '';
    cards.forEach(function (card) {
      if (card.type === 'car') html += carCardHtml(card);
      else html += productCardHtml(card);
    });
    return '<div class="chat-card-row">' + html + '</div>';
  }

  /* ---- message appending ------------------------------------------ */

  function appendMessage(role, text, cards) {
    var messages = document.getElementById('chatMessages');
    if (!messages) return;
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-msg ' + (role === 'user' ? 'user' : 'assistant');
    wrapper.innerHTML =
      '<div class="chat-bubble">' + renderInline(text) + '</div>' +
      (cards && cards.length ? cardsHtml(cards) : '') +
      '<span class="chat-time">' + timestamp() + '</span>';
    messages.appendChild(wrapper);
    scrollToBottom();
  }

  function showTyping() {
    var messages = document.getElementById('chatMessages');
    if (!messages) return null;
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-msg assistant typing';
    wrapper.innerHTML = '<div class="chat-bubble typing-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
    messages.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
  }

  function hideTyping(node) {
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  /* ---- chips / flow tray ------------------------------------------ */

  function clearChips() {
    var quick = document.getElementById('chatQuick');
    if (quick) quick.innerHTML = '';
  }

  function renderSuggestions(list) {
    var quick = document.getElementById('chatQuick');
    if (!quick) return;
    quick.innerHTML = '';
    (list || []).slice(0, 4).forEach(function (suggestion) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chat-chip';
      chip.textContent = suggestion;
      chip.addEventListener('click', function () { send(suggestion); });
      quick.appendChild(chip);
    });
  }

  function renderFlow(flow) {
    var tray = document.getElementById('chatFlow');
    if (!tray) return;
    if (!flow || !flow.step) {
      tray.hidden = true;
      tray.innerHTML = '';
      return;
    }
    var label = FLOW_LABELS[flow.step] || flow.step;
    var number = FLOW_ORDER[flow.step] || 1;
    var options = (flow.options || []).map(function (option) {
      return '<button type="button" class="chat-flow-opt" data-value="' + escapeHtml(option) + '">' + escapeHtml(option) + '</button>';
    }).join('');
    tray.hidden = false;
    tray.innerHTML =
      '<div class="chat-flow-head"><span class="chat-flow-title">Step ' + number + ' of 3 · ' + escapeHtml(label) + '</span>' +
      '<button type="button" class="chat-flow-reset" id="chatFlowReset">Restart</button></div>' +
      '<div class="chat-flow-options">' + options + '</div>';
    tray.querySelectorAll('.chat-flow-opt').forEach(function (button) {
      button.addEventListener('click', function () { send(button.dataset.value); });
    });
    var reset = document.getElementById('chatFlowReset');
    if (reset) reset.addEventListener('click', function () { send('cancel'); });
  }

  /* ---- send ------------------------------------------------------- */

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
        session_id: sessionId || ''
      })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.session_id) {
          sessionId = data.session_id;
          saveSession();
        }
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
      .finally(function () {
        busy = false;
      });
  }

  /* ---- card actions ----------------------------------------------- */

  function attachCardActions() {
    var messages = document.getElementById('chatMessages');
    if (!messages) return;
    messages.querySelectorAll('.chat-card').forEach(function (card) {
      if (card.dataset.bound) return;
      card.dataset.bound = 'true';
      card.addEventListener('click', function (event) {
        var button = event.target.closest('.chat-card-btn');
        if (!button) return;
        var action = button.dataset.action;
        if (action === 'cart') {
          var helpers = window.StoreHelpers;
          if (helpers && helpers.addItemToCart) {
            helpers.addItemToCart(button.dataset.title, button.dataset.price);
          }
        } else if (action === 'view') {
          var id = card.dataset.id;
          if (window.AppRouter) window.AppRouter.navigate('product', { id: id });
          closeChat();
        } else if (action === 'cars') {
          if (window.AppRouter) window.AppRouter.navigate('recommendations');
          closeChat();
        }
      });
    });
  }

  /* ---- open / close ----------------------------------------------- */

  function openChat() {
    var widget = document.getElementById('chatWidget');
    var launcher = document.getElementById('chatLauncher');
    var badge = document.getElementById('chatLauncherBadge');
    if (widget) widget.classList.add('is-open');
    if (launcher) launcher.setAttribute('aria-expanded', 'true');
    if (widget) widget.setAttribute('aria-hidden', 'false');
    if (badge) badge.hidden = true;

    var messages = document.getElementById('chatMessages');
    if (messages) messages.innerHTML = '';

    if (!history.length) {
      appendMessage('assistant', "Hi! I'm Obama, your store assistant. 🤖 Ask me for products, car recommendations, deals, delivery — anything about the store.");
      renderSuggestions(['What can you do?', 'Recommend a car', "What's trending?"]);
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
    var widget = document.getElementById('chatWidget');
    var launcher = document.getElementById('chatLauncher');
    if (widget) widget.classList.remove('is-open');
    if (launcher) launcher.setAttribute('aria-expanded', 'false');
    if (widget) widget.setAttribute('aria-hidden', 'true');
  }

  /* ---- init ------------------------------------------------------- */

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
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var input = document.getElementById('chatInput');
        send(input ? input.value : '');
      });
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeChat();
    });

    document.getElementById('chatMessages').addEventListener('click', attachCardActions);
    document.addEventListener('click', attachCardActions);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
