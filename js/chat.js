/**
 * chat.js — Obama Store assistant widget (Phase 1).
 *
 * Floating chat panel that talks to /api/chat. The backend picks intent
 * based replies from the store's own catalog + recommender. The widget
 * keeps a per-session conversation in sessionStorage.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'obama-store-chat';
  var WELCOME = "Hello! I'm the Obama Store assistant. \uD83E\uDD16 Ask me about products, car recommendations, delivery, payment or returns.";
  var SUGGESTIONS = ['What can you do?', 'Recommend a car', "What's trending?"];

  var history = [];
  var busy = false;

  function loadHistory() {
    try {
      history = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
    } catch (error) {
      history = [];
    }
    if (!Array.isArray(history)) history = [];
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-40)));
    } catch (error) {
      /* storage may be unavailable — ignore */
    }
  }

  function scrollToBottom() {
    var messages = document.getElementById('chatMessages');
    if (messages) messages.scrollTop = messages.scrollHeight;
  }

  function appendMessage(role, text) {
    var messages = document.getElementById('chatMessages');
    if (!messages) return;
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-msg ' + (role === 'user' ? 'user' : 'assistant');
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.textContent = text;
    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    scrollToBottom();
  }

  function showTyping() {
    var messages = document.getElementById('chatMessages');
    if (!messages) return null;
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-msg assistant typing';
    wrapper.innerHTML = '<div class="chat-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
    messages.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
  }

  function hideTyping(node) {
    if (node && node.parentNode) node.parentNode.removeChild(node);
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

  function send(text) {
    if (busy) return;
    var message = (text || '').trim();
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
      body: JSON.stringify({ message: message, history: history.slice(-20) })
    })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (!res.ok) throw new Error((data && data.detail) || 'Chat error');
          return data;
        });
      })
      .then(function (data) {
        hideTyping(typing);
        appendMessage('assistant', data.reply);
        history.push({ role: 'assistant', content: data.reply });
        saveHistory();
        renderSuggestions(data.suggestions);
      })
      .catch(function () {
        hideTyping(typing);
        appendMessage('assistant', 'Sorry, I hit a snag. Please try again in a moment.');
      })
      .finally(function () {
        busy = false;
      });
  }

  /* ---- Open / close ------------------------------------------------ */

  function openChat() {
    var widget = document.getElementById('chatWidget');
    var launcher = document.getElementById('chatLauncher');
    if (widget) widget.classList.add('is-open');
    if (launcher) launcher.setAttribute('aria-expanded', 'true');
    if (widget) widget.setAttribute('aria-hidden', 'false');

    var messages = document.getElementById('chatMessages');
    if (messages) messages.innerHTML = '';
    if (!history.length) {
      appendMessage('assistant', WELCOME);
      renderSuggestions(SUGGESTIONS);
    } else {
      history.forEach(function (msg) { appendMessage(msg.role, msg.content); });
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

  function init() {
    loadHistory();

    var launcher = document.getElementById('chatLauncher');
    if (launcher) launcher.addEventListener('click', function () {
      var widget = document.getElementById('chatWidget');
      if (widget && widget.classList.contains('is-open')) {
        closeChat();
      } else {
        openChat();
      }
    });

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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
