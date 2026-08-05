/**
 * auth.js — client for the Obama Store account system.
 *
 * Handles sign-in / account creation through a modal, persists the
 * bearer session in localStorage, validates it against /api/auth/me on
 * load, and reflects the signed-in state across the navbar and the
 * My Account page.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'obama-store-session';
  var session = null;

  function loadSession() {
    try {
      session = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    } catch (error) {
      session = null;
    }
    if (!session || !session.token || !session.user) session = null;
  }

  function saveSession() {
    try {
      if (session) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (error) {
      /* storage may be unavailable — ignore */
    }
  }

  function isLoggedIn() {
    return !!(session && session.token && session.user);
  }

  function getUser() {
    return isLoggedIn() ? session.user : null;
  }

  function getToken() {
    return isLoggedIn() ? session.token : null;
  }

  function api(path, options) {
    return fetch(path, options).then(function (res) {
      return res.json().catch(function () {
        return null;
      }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          var message = typeof detail === 'string' ? detail : 'Something went wrong. Please try again.';
          throw new Error(message);
        }
        return data;
      });
    });
  }

  function login(email, password) {
    return api('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: password })
    }).then(function (data) {
      session = data;
      saveSession();
      render();
      return data.user;
    });
  }

  function register(name, email, password) {
    return api('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, email: email, password: password })
    }).then(function (data) {
      session = data;
      saveSession();
      render();
      return data.user;
    });
  }

  function logout() {
    var token = getToken();
    if (token) {
      api('/api/auth/logout', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + token }
      }).catch(function () { /* ignore network errors */ });
    }
    session = null;
    saveSession();
    render();
  }

  function initials(name) {
    return (name || 'O').trim().split(/\s+/).slice(0, 2).map(function (word) {
      return word.charAt(0);
    }).join('').toUpperCase() || 'O';
  }

  function render() {
    var signedIn = isLoggedIn();
    var user = getUser();

    var btn = document.getElementById('authBtn');
    if (btn) {
      if (signedIn) {
        btn.textContent = 'Hi, ' + (user.name.split(' ')[0] || 'there');
        btn.classList.add('is-authed');
        btn.setAttribute('aria-label', 'Open your account');
      } else {
        btn.textContent = 'Sign in';
        btn.classList.remove('is-authed');
        btn.setAttribute('aria-label', 'Sign in or create an account');
      }
    }

    var avatar = document.getElementById('profileAvatar');
    var nameEl = document.getElementById('profileName');
    var subtitleEl = document.getElementById('profileSubtitle');
    var actions = document.getElementById('profileActions');

    if (avatar) avatar.textContent = signedIn ? initials(user.name) : 'O';
    if (nameEl) nameEl.textContent = signedIn ? user.name : 'Guest shopper';
    if (subtitleEl) {
      if (signedIn) {
        var created = user.created_at ? new Date(user.created_at * 1000) : null;
        var since = created ? created.toLocaleDateString(undefined, { year: 'numeric', month: 'short' }) : '';
        subtitleEl.textContent = user.email + (since ? ' \u2022 Member since ' + since : '');
      } else {
        subtitleEl.textContent = 'Sign in to sync your cart, wishlist and orders across devices.';
      }
    }

    if (actions) {
      if (signedIn) {
        actions.innerHTML = '<button type="button" class="button secondary" id="authLogoutBtn">Sign out</button>';
        var outBtn = document.getElementById('authLogoutBtn');
        if (outBtn) outBtn.addEventListener('click', logout);
      } else {
        actions.innerHTML = '<button type="button" class="button primary" id="authOpenBtn">Sign in / Create account</button>';
        var openBtn = document.getElementById('authOpenBtn');
        if (openBtn) openBtn.addEventListener('click', function () { openModal('login'); });
      }
    }
  }

  /* ---- Modal ------------------------------------------------------- */

  function openModal(tab) {
    var modal = document.getElementById('authModal');
    var backdrop = document.getElementById('authBackdrop');
    if (!modal) return;
    setTab(tab || 'login');
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.hidden = false;
    var first = document.getElementById('loginEmail');
    if (first) setTimeout(function () { first.focus(); }, 50);
  }

  function closeModal() {
    var modal = document.getElementById('authModal');
    var backdrop = document.getElementById('authBackdrop');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    if (backdrop) backdrop.hidden = true;
  }

  function setTab(tab) {
    document.querySelectorAll('[data-auth-tab]').forEach(function (btn) {
      var active = btn.getAttribute('data-auth-tab') === tab;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    var loginForm = document.getElementById('loginForm');
    var registerForm = document.getElementById('registerForm');
    if (loginForm) loginForm.hidden = tab !== 'login';
    if (registerForm) registerForm.hidden = tab !== 'register';
    ['loginError', 'registerError'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.hidden = true;
    });
  }

  function showError(el, message) {
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
  }

  function handleLogin(event) {
    event.preventDefault();
    var email = document.getElementById('loginEmail').value.trim();
    var password = document.getElementById('loginPassword').value;
    var errEl = document.getElementById('loginError');
    var submit = document.getElementById('loginSubmit');

    if (!email || !password) {
      showError(errEl, 'Please enter your email and password.');
      return;
    }

    submit.disabled = true;
    submit.textContent = 'Signing in\u2026';
    login(email, password)
      .then(function () {
        closeModal();
        document.getElementById('loginForm').reset();
      })
      .catch(function (error) {
        showError(errEl, error.message);
      })
      .finally(function () {
        submit.disabled = false;
        submit.textContent = 'Sign in';
      });
  }

  function handleRegister(event) {
    event.preventDefault();
    var name = document.getElementById('regName').value.trim();
    var email = document.getElementById('regEmail').value.trim();
    var password = document.getElementById('regPassword').value;
    var errEl = document.getElementById('registerError');
    var submit = document.getElementById('registerSubmit');

    if (!name || !email || !password) {
      showError(errEl, 'Please fill in all fields.');
      return;
    }
    if (password.length < 6) {
      showError(errEl, 'Password must be at least 6 characters.');
      return;
    }

    submit.disabled = true;
    submit.textContent = 'Creating account\u2026';
    register(name, email, password)
      .then(function () {
        closeModal();
        document.getElementById('registerForm').reset();
      })
      .catch(function (error) {
        showError(errEl, error.message);
      })
      .finally(function () {
        submit.disabled = false;
        submit.textContent = 'Create account';
      });
  }

  function init() {
    loadSession();

    var token = getToken();
    if (token) {
      api('/api/auth/me', { headers: { Authorization: 'Bearer ' + token } })
        .then(function (data) {
          if (data && data.user) {
            session = { token: token, user: data.user };
            saveSession();
            render();
          }
        })
        .catch(function () {
          session = null;
          saveSession();
          render();
        });
    }

    render();

    var authBtn = document.getElementById('authBtn');
    if (authBtn) {
      authBtn.addEventListener('click', function () {
        if (isLoggedIn()) {
          if (window.AppRouter) window.AppRouter.navigate('profile');
        } else {
          openModal('login');
        }
      });
    }

    var closeBtn = document.getElementById('authCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);

    var backdrop = document.getElementById('authBackdrop');
    if (backdrop) backdrop.addEventListener('click', closeModal);

    document.querySelectorAll('[data-auth-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () { setTab(btn.getAttribute('data-auth-tab')); });
    });

    var loginForm = document.getElementById('loginForm');
    if (loginForm) loginForm.addEventListener('submit', handleLogin);

    var registerForm = document.getElementById('registerForm');
    if (registerForm) registerForm.addEventListener('submit', handleRegister);

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeModal();
    });
  }

  window.ObamaAuth = {
    isLoggedIn: isLoggedIn,
    getUser: getUser,
    getToken: getToken,
    login: login,
    register: register,
    logout: logout,
    openModal: openModal,
    closeModal: closeModal,
    render: render
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
