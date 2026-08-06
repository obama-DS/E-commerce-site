/**
 * kb.js — Knowledge Base admin panel for Obama Store.
 *
 * A clean, professional management console: browse / search / filter
 * knowledge items, add plain text or Markdown, upload PDF / Word / Markdown /
 * CSV / JSON files, import website URLs, edit or replace entries, re-index
 * failed items and test retrieval — exactly what the chatbot will answer from.
 */
(function () {
  'use strict';

  var API_BASE = window.location.protocol.indexOf('http') === 0
    ? window.location.origin
    : 'http://127.0.0.1:8000';

  var state = {
    q: '',
    category: '',
    tag: '',
    status: '',
    page: 1,
    pageSize: 20,
    total: 0,
    items: [],
    meta: { categories: [], tags: [], stats: {} },
    editing: null,
    timer: null
  };

  function isLoggedIn() {
    return !!(window.ObamaAuth && window.ObamaAuth.isLoggedIn());
  }

  function isAdmin() {
    var user = window.ObamaAuth && window.ObamaAuth.getUser();
    return !!(user && user.is_admin);
  }

  function onKbPage() {
    var hash = (window.location.hash || '').replace(/^#/, '').replace(/^\//, '');
    return hash.split('?')[0].trim() === 'kb';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function kbApi(path, options) {
    options = options || {};
    var headers = Object.assign({}, options.headers || {});
    var token = window.ObamaAuth && window.ObamaAuth.getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    var init = { method: options.method || 'GET', headers: headers };
    if (options.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.json);
    } else if (options.body !== undefined) {
      init.body = options.body;
    }
    return fetch(API_BASE + path, init).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          var message = typeof detail === 'string'
            ? detail : 'Request failed (' + res.status + ').';
          var error = new Error(message);
          error.status = res.status;
          throw error;
        }
        return data;
      });
    });
  }

  function fmtDate(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  function typeLabel(type) {
    var labels = {
      text: 'Text', markdown: 'Markdown', pdf: 'PDF', word: 'Word',
      csv: 'CSV', json: 'JSON', url: 'URL'
    };
    return labels[type] || 'Text';
  }

  function statusClass(status) {
    return status === 'indexed' ? 'ok' : (status === 'error' ? 'bad' : 'wait');
  }

  function loadMeta() {
    return kbApi('/api/kb/meta').then(function (data) {
      state.meta = data;
    });
  }

  function loadItems() {
    var params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.category) params.set('category', state.category);
    if (state.tag) params.set('tag', state.tag);
    if (state.status) params.set('status', state.status);
    params.set('page', String(state.page));
    params.set('page_size', String(state.pageSize));
    return kbApi('/api/kb/items?' + params.toString()).then(function (data) {
      state.items = data.items;
      state.total = data.total;
      state.page = data.page;
    });
  }

  function renderStatusPill() {
    var pill = document.getElementById('kbStatusPill');
    if (!pill) return;
    var s = state.meta.stats || {};
    if (isAdmin()) {
      pill.textContent = s.total + ' items · ' + s.indexed + ' indexed';
    } else {
      pill.textContent = 'Admin access required';
    }
  }

  /* ---- Gate --------------------------------------------------------- */

  function renderGate() {
    var root = document.getElementById('kbRoot');
    if (!root) return;
    if (!isLoggedIn()) {
      root.innerHTML =
        '<div class="kb-gate">' +
        '<div class="kb-gate-icon">🔐</div>' +
        '<h3>Admin access required</h3>' +
        '<p>Sign in with an admin account to manage the Knowledge Base.</p>' +
        '<button type="button" class="button primary" id="kbGateLogin">Sign in</button>' +
        '</div>';
      var btn = document.getElementById('kbGateLogin');
      if (btn) btn.addEventListener('click', function () {
        if (window.ObamaAuth) window.ObamaAuth.openModal('login');
      });
      return;
    }
    if (!isAdmin()) {
      root.innerHTML =
        '<div class="kb-gate">' +
        '<div class="kb-gate-icon">🚫</div>' +
        '<h3>This account is not an admin</h3>' +
        '<p>Knowledge Base management is restricted to store administrators.</p>' +
        '</div>';
    }
  }

  /* ---- Main dashboard ----------------------------------------------- */

  function renderDashboard() {
    var root = document.getElementById('kbRoot');
    if (!root) return;
    var s = state.meta.stats || {};
    var statsCards =
      '<div class="kb-stats">' +
      statCard('Total items', s.total || 0, 'total') +
      statCard('Indexed', s.indexed || 0, 'ok') +
      statCard('Processing', s.processing || 0, 'wait') +
      statCard('Errors', s.error || 0, 'bad') +
      '</div>';

    var catOptions = '<option value="">All categories</option>' +
      (state.meta.categories || []).map(function (c) {
        return '<option value="' + escapeHtml(c.name) + '"' +
          (state.category === c.name ? ' selected' : '') + '>' +
          escapeHtml(c.name) + ' (' + c.count + ')</option>';
      }).join('');
    var tagOptions = '<option value="">All tags</option>' +
      (state.meta.tags || []).map(function (t) {
        return '<option value="' + escapeHtml(t.name) + '"' +
          (state.tag === t.name ? ' selected' : '') + '>' +
          escapeHtml(t.name) + '</option>';
      }).join('');

    var toolbar =
      '<div class="kb-toolbar">' +
      '<input type="search" id="kbSearch" class="kb-search" placeholder="Search knowledge…" value="' +
      escapeHtml(state.q) + '" aria-label="Search knowledge base">' +
      '<select id="kbCatFilter" class="kb-select" aria-label="Filter by category">' +
      catOptions + '</select>' +
      '<select id="kbTagFilter" class="kb-select" aria-label="Filter by tag">' +
      tagOptions + '</select>' +
      '<select id="kbStatusFilter" class="kb-select" aria-label="Filter by status">' +
      '<option value="">All statuses</option>' +
      '<option value="indexed"' + (state.status === 'indexed' ? ' selected' : '') + '>Indexed</option>' +
      '<option value="processing"' + (state.status === 'processing' ? ' selected' : '') + '>Processing</option>' +
      '<option value="error"' + (state.status === 'error' ? ' selected' : '') + '>Errors</option>' +
      '</select>' +
      '<button type="button" class="button primary" id="kbNewItem">+ New item</button>' +
      '</div>';

    var importPanel =
      '<div class="kb-import">' +
      '<div class="kb-import-head"><h3>Import knowledge</h3>' +
      '<p>Upload a file or fetch a webpage. It is processed and indexed automatically.</p></div>' +
      '<div class="kb-import-body">' +
      '<div class="kb-dropzone" id="kbDropzone" tabindex="0" role="button" aria-label="Upload a file">' +
      '<div class="kb-drop-icon">📄</div>' +
      '<strong>Drop a file here or click to browse</strong>' +
      '<span>PDF · Word (.docx) · Markdown · CSV · JSON · TXT</span>' +
      '<input type="file" id="kbFile" multiple accept=".pdf,.docx,.md,.markdown,.csv,.json,.txt,.text" hidden>' +
      '</div>' +
      '<div class="kb-url-box">' +
      '<span class="kb-url-icon">🌐</span>' +
      '<input type="url" id="kbUrl" placeholder="https://example.com/page-to-import" aria-label="Website URL to import">' +
      '<button type="button" class="button" id="kbUrlBtn">Import URL</button>' +
      '</div>' +
      '</div>' +
      '<div id="kbImportStatus" class="kb-import-status" role="status"></div>' +
      '</div>';

    var testPanel =
      '<div class="kb-test">' +
      '<div class="kb-import-head"><h3>Test retrieval</h3>' +
      '<p>See exactly what the assistant would answer from. Ask it the same thing in the chat widget.</p></div>' +
      '<div class="kb-url-box">' +
      '<span class="kb-url-icon">🔎</span>' +
      '<input type="text" id="kbTestQ" placeholder="e.g. what is your return policy?" aria-label="Test question">' +
      '<button type="button" class="button" id="kbTestBtn">Search</button>' +
      '</div>' +
      '<div id="kbTestResults"></div>' +
      '</div>';

    root.innerHTML = statsCards + toolbar + importPanel + testPanel +
      '<div class="kb-list-head"><h3>Knowledge items</h3>' +
      '<span id="kbCount">' + state.total + ' item(s)</span></div>' +
      '<div id="kbList"></div>' +
      '<div class="kb-pager" id="kbPager"></div>';

    bindToolbar();
    bindImport();
    bindTest();
    renderList();
    renderPager();
  }

  function statCard(label, value, kind) {
    return '<div class="kb-stat"><span class="kb-stat-value kb-stat-' + kind + '">' +
      value + '</span><span class="kb-stat-label">' + label + '</span></div>';
  }

  function bindToolbar() {
    var search = document.getElementById('kbSearch');
    var cat = document.getElementById('kbCatFilter');
    var tag = document.getElementById('kbTagFilter');
    var status = document.getElementById('kbStatusFilter');
    var newBtn = document.getElementById('kbNewItem');

    var debounce = null;
    if (search) search.addEventListener('input', function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () {
        state.q = search.value.trim();
        state.page = 1;
        refresh();
      }, 350);
    });
    if (cat) cat.addEventListener('change', function () {
      state.category = cat.value; state.page = 1; refresh();
    });
    if (tag) tag.addEventListener('change', function () {
      state.tag = tag.value; state.page = 1; refresh();
    });
    if (status) status.addEventListener('change', function () {
      state.status = status.value; state.page = 1; refresh();
    });
    if (newBtn) newBtn.addEventListener('click', function () { openEditor(null); });
  }

  function bindImport() {
    var drop = document.getElementById('kbDropzone');
    var fileInput = document.getElementById('kbFile');
    var urlInput = document.getElementById('kbUrl');
    var urlBtn = document.getElementById('kbUrlBtn');

    if (drop && fileInput) {
      drop.addEventListener('click', function () { fileInput.click(); });
      drop.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
      });
      ['dragover', 'dragenter'].forEach(function (name) {
        drop.addEventListener(name, function (e) {
          e.preventDefault();
          drop.classList.add('is-drag');
        });
      });
      ['dragleave', 'drop'].forEach(function (name) {
        drop.addEventListener(name, function (e) {
          e.preventDefault();
          drop.classList.remove('is-drag');
        });
      });
      drop.addEventListener('drop', function (e) {
        var files = e.dataTransfer && e.dataTransfer.files;
        if (files) uploadFiles(files);
      });
      fileInput.addEventListener('change', function () {
        if (fileInput.files && fileInput.files.length) uploadFiles(fileInput.files);
        fileInput.value = '';
      });
    }

    if (urlBtn && urlInput) {
      urlBtn.addEventListener('click', function () {
        var url = urlInput.value.trim();
        if (!url) { importStatus('Enter a URL to import.', 'bad'); return; }
        urlBtn.disabled = true;
        urlBtn.textContent = 'Importing…';
        kbApi('/api/kb/url', {
          method: 'POST',
          json: { url: url }
        }).then(function (data) {
          importStatus('Import started for <strong>' + escapeHtml(url) +
            '</strong> — processing…', 'ok');
          urlInput.value = '';
          refresh();
        }).catch(function (err) {
          importStatus('Import failed: ' + escapeHtml(err.message), 'bad');
        }).finally(function () {
          urlBtn.disabled = false;
          urlBtn.textContent = 'Import URL';
        });
      });
    }
  }

  function uploadFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var statusEl = document.getElementById('kbImportStatus');
    var pending = files.length;
    var done = 0;
    files.forEach(function (file) {
      var form = new FormData();
      form.append('file', file, file.name);
      importStatus('Uploading <strong>' + escapeHtml(file.name) +
        '</strong>…', 'ok');
      kbApi('/api/kb/upload', { method: 'POST', body: form })
        .then(function (data) {
          importStatus('<strong>' + escapeHtml(file.name) + '</strong> uploaded — ' +
            (data.status === 'processing' ? 'indexing…' : 'indexed.'), 'ok');
        })
        .catch(function (err) {
          importStatus('<strong>' + escapeHtml(file.name) + '</strong> rejected: ' +
            escapeHtml(err.message), 'bad');
        })
        .finally(function () {
          done += 1;
          if (done >= pending && statusEl) {
            statusEl.classList.add('is-live');
          }
          refresh();
        });
    });
  }

  function importStatus(message, kind) {
    var el = document.getElementById('kbImportStatus');
    if (!el) return;
    el.innerHTML = message;
    el.className = 'kb-import-status ' + (kind || '');
    el.classList.add('is-live');
  }

  function bindTest() {
    var q = document.getElementById('kbTestQ');
    var btn = document.getElementById('kbTestBtn');
    var results = document.getElementById('kbTestResults');
    if (!q || !btn || !results) return;
    var run = function () {
      var message = q.value.trim();
      if (!message) return;
      btn.disabled = true;
      btn.textContent = 'Searching…';
      results.innerHTML = '<div class="kb-test-empty">Searching the index…</div>';
      kbApi('/api/kb/test', { method: 'POST', json: { message: message } })
        .then(function (data) {
          var items = data.results || [];
          if (!items.length) {
            results.innerHTML = '<div class="kb-test-empty">No confident match — ' +
              'the assistant falls back to its built-in knowledge for this one.</div>';
            return;
          }
          var html = items.map(function (hit, index) {
            var first = index === 0 ? ' is-top' : '';
            return '<div class="kb-hit' + first + '">' +
              '<div class="kb-hit-head">' +
              '<span class="kb-hit-title">' + escapeHtml(hit.title) + '</span>' +
              '<span class="kb-hit-score">' + hit.score + '</span>' +
              '</div>' +
              '<div class="kb-hit-preview">' + escapeHtml(hit.content) + '</div>' +
              '</div>';
          }).join('');
          results.innerHTML = html +
            '<div class="kb-test-note">The assistant answers from the top match when its score ' +
            'is confident enough — this is the "knowledge first" behaviour.</div>';
        })
        .catch(function (err) {
          results.innerHTML = '<div class="kb-test-empty bad">' + escapeHtml(err.message) + '</div>';
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = 'Search';
        });
    };
    btn.addEventListener('click', run);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
  }

  function renderList() {
    var list = document.getElementById('kbList');
    if (!list) return;
    var count = document.getElementById('kbCount');
    if (count) count.textContent = state.total + ' item(s)';

    if (!state.items.length) {
      list.innerHTML = '<div class="kb-empty">No knowledge items yet. ' +
        'Add your first one or upload a file above. 🧠</div>';
      return;
    }

    var html = state.items.map(function (item) {
      var tags = (item.tags || []).map(function (t) {
        return '<span class="kb-tag">' + escapeHtml(t) + '</span>';
      }).join('');
      var errorBlock = item.status === 'error' && item.error
        ? '<div class="kb-error-line">⚠ ' + escapeHtml(item.error) + '</div>' : '';
      var spinner = item.status === 'processing'
        ? '<span class="kb-spinner" aria-label="indexing"></span>' : '';
      return '<div class="kb-item">' +
        '<div class="kb-item-main">' +
        '<div class="kb-item-title-row">' +
        '<span class="kb-item-title">' + escapeHtml(item.title) + '</span>' +
        '<span class="kb-badge kb-type">' + typeLabel(item.content_type) + '</span>' +
        '<span class="kb-badge kb-status-' + statusClass(item.status) + '">' +
        item.status + '</span>' + spinner +
        '</div>' +
        '<div class="kb-item-meta">' +
        '<span class="kb-cat">' + escapeHtml(item.category || 'General') + '</span>' +
        (tags ? '<span class="kb-tags">' + tags + '</span>' : '') +
        '</div>' +
        '<div class="kb-item-preview">' + escapeHtml(item.preview || '') + '</div>' +
        errorBlock +
        '<div class="kb-item-foot">v' + item.version + ' · updated ' +
        fmtDate(item.updated_at) + (item.source ? ' · ' + escapeHtml(item.source) : '') +
        '</div>' +
        '</div>' +
        '<div class="kb-item-actions">' +
        '<button type="button" class="kb-btn" data-act="edit" data-id="' + item.id + '">Edit / Replace</button>' +
        '<button type="button" class="kb-btn" data-act="reindex" data-id="' + item.id + '">Re-index</button>' +
        '<button type="button" class="kb-btn danger" data-act="delete" data-id="' + item.id + '">Delete</button>' +
        '</div>' +
        '</div>';
    }).join('');
    list.innerHTML = html;

    list.querySelectorAll('button[data-act]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var act = btn.getAttribute('data-act');
        var id = btn.getAttribute('data-id');
        if (act === 'edit') openEditor(id);
        else if (act === 'reindex') reindex(id);
        else if (act === 'delete') deleteItem(id);
      });
    });
  }

  function renderPager() {
    var pager = document.getElementById('kbPager');
    if (!pager) return;
    var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
    pager.innerHTML =
      '<button type="button" class="kb-btn" id="kbPrev" ' +
      (state.page <= 1 ? 'disabled' : '') + '>← Previous</button>' +
      '<span class="kb-pageinfo">Page ' + state.page + ' of ' + pages + '</span>' +
      '<button type="button" class="kb-btn" id="kbNext" ' +
      (state.page >= pages ? 'disabled' : '') + '>Next →</button>';
    var prev = document.getElementById('kbPrev');
    var next = document.getElementById('kbNext');
    if (prev) prev.addEventListener('click', function () {
      if (state.page > 1) { state.page -= 1; refresh(); }
    });
    if (next) next.addEventListener('click', function () {
      if (state.page < pages) { state.page += 1; refresh(); }
    });
  }

  function deleteItem(id) {
    var item = state.items.filter(function (i) { return i.id === id; })[0];
    var name = item ? item.title : 'this item';
    if (!window.confirm('Delete "' + name + '" from the Knowledge Base? ' +
      'The assistant will stop using it immediately.')) return;
    kbApi('/api/kb/items/' + id, { method: 'DELETE' })
      .then(function () { refresh(); })
      .catch(function (err) { window.alert(err.message); });
  }

  function reindex(id) {
    kbApi('/api/kb/items/' + id + '/reindex', { method: 'POST' })
      .then(function () { refresh(); })
      .catch(function (err) { window.alert(err.message); });
  }

  /* ---- Editor modal ------------------------------------------------ */

  function openEditor(id) {
    var host = document.getElementById('kbModalHost');
    if (!host) return;
    host.hidden = false;
    if (id) {
      kbApi('/api/kb/items/' + id).then(function (item) {
        state.editing = item;
        renderEditor(item, true);
      }).catch(function (err) { window.alert(err.message); });
    } else {
      state.editing = null;
      renderEditor(null, false);
    }
  }

  function renderEditor(item, isEdit) {
    var host = document.getElementById('kbModalHost');
    if (!host) return;
    var catDatalist = (state.meta.categories || []).map(function (c) {
      return '<option value="' + escapeHtml(c.name) + '"></option>';
    }).join('');
    var title = item ? item.title : '';
    var category = item ? (item.category || 'General') : 'General';
    var tags = item ? (item.tags || []).join(', ') : '';
    var content = item ? item.content : '';
    var source = item ? (item.source || '') : '';
    var type = item ? (item.content_type || 'text') : 'text';

    host.innerHTML =
      '<div class="kb-modal" role="dialog" aria-modal="true" aria-labelledby="kbModalTitle">' +
      '<div class="kb-modal-card">' +
      '<div class="kb-modal-head">' +
      '<h3 id="kbModalTitle">' + (isEdit ? 'Edit / replace item' : 'New knowledge item') + '</h3>' +
      '<button type="button" class="kb-btn" id="kbModalClose" aria-label="Close">✕</button>' +
      '</div>' +
      '<form id="kbForm" novalidate>' +
      '<label class="kb-field">Title' +
      '<input type="text" id="kbTitle" required value="' + escapeHtml(title) +
      '" placeholder="e.g. Return Policy">' +
      '</label>' +
      '<div class="kb-field-row">' +
      '<label class="kb-field">Content type' +
      '<select id="kbType"><option value="text"' + (type === 'text' ? ' selected' : '') +
      '>Plain text</option><option value="markdown"' + (type === 'markdown' ? ' selected' : '') +
      '>Markdown</option></select></label>' +
      '<label class="kb-field">Category' +
      '<input type="text" id="kbCategory" list="kbCatList" value="' + escapeHtml(category) +
      '" placeholder="General"><datalist id="kbCatList">' + catDatalist + '</datalist>' +
      '</label>' +
      '</div>' +
      '<label class="kb-field">Tags (comma separated)' +
      '<input type="text" id="kbTags" value="' + escapeHtml(tags) +
      '" placeholder="returns, refund, policy">' +
      '</label>' +
      '<label class="kb-field">Source (optional — file name or URL)' +
      '<input type="text" id="kbSource" value="' + escapeHtml(source) + '" placeholder="">' +
      '</label>' +
      '<label class="kb-field">Content' +
      '<textarea id="kbContent" rows="12" required placeholder="Write the knowledge the assistant should answer with…">' +
      escapeHtml(content) + '</textarea>' +
      '</label>' +
      '<div class="kb-modal-errors" id="kbFormError" role="alert" hidden></div>' +
      '<div class="kb-modal-foot">' +
      '<button type="button" class="kb-btn" id="kbFormCancel">Cancel</button>' +
      '<button type="submit" class="button primary" id="kbFormSave">' +
      (isEdit ? 'Save changes' : 'Add to knowledge base') + '</button>' +
      '</div>' +
      '</form>' +
      '</div>' +
      '</div>';

    document.getElementById('kbModalClose').addEventListener('click', closeEditor);
    document.getElementById('kbFormCancel').addEventListener('click', closeEditor);
    host.addEventListener('click', function (e) {
      if (e.target === host) closeEditor();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !host.hidden) closeEditor();
    }, { once: true });

    document.getElementById('kbForm').addEventListener('submit', function (e) {
      e.preventDefault();
      saveEditor();
    });
    var titleInput = document.getElementById('kbTitle');
    if (titleInput) titleInput.focus();
  }

  function closeEditor() {
    var host = document.getElementById('kbModalHost');
    if (host) { host.hidden = true; host.innerHTML = ''; }
    state.editing = null;
  }

  function saveEditor() {
    var errEl = document.getElementById('kbFormError');
    var title = document.getElementById('kbTitle').value.trim();
    var content = document.getElementById('kbContent').value.trim();
    if (!title || !content) {
      if (errEl) { errEl.textContent = 'Title and content are required.'; errEl.hidden = false; }
      return;
    }
    var payload = {
      title: title,
      content: content,
      category: document.getElementById('kbCategory').value.trim() || 'General',
      tags: document.getElementById('kbTags').value.split(',').map(function (t) { return t.trim(); })
        .filter(Boolean),
      content_type: document.getElementById('kbType').value,
      source: document.getElementById('kbSource').value.trim()
    };
    var saveBtn = document.getElementById('kbFormSave');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
    var path = state.editing
      ? '/api/kb/items/' + state.editing.id
      : '/api/kb/items';
    var method = state.editing ? 'PUT' : 'POST';
    kbApi(path, { method: method, json: payload })
      .then(function () {
        closeEditor();
        refresh();
      })
      .catch(function (err) {
        if (errEl) { errEl.textContent = err.message; errEl.hidden = false; }
      })
      .finally(function () {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = state.editing ? 'Save changes' : 'Add to knowledge base'; }
      });
  }

  /* ---- Refresh / polling ------------------------------------------- */

  function refresh() {
    loadMeta().then(loadItems).then(function () {
      if (!isAdmin()) { renderGate(); renderStatusPill(); return; }
      var active = onKbPage();
      if (active) {
        renderDashboard();
      } else {
        renderStatusPill();
      }
      schedulePolling();
    }).catch(function (err) {
      if (err.status === 401 || err.status === 403) {
        renderGate();
      } else if (onKbPage()) {
        var root = document.getElementById('kbRoot');
        if (root) root.innerHTML = '<div class="kb-empty bad">Could not load the knowledge base: ' +
          escapeHtml(err.message) + '</div>';
      }
    });
  }

  function schedulePolling() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    var s = (state.meta.stats || {});
    if (s.processing > 0) {
      state.timer = setInterval(function () {
        if (!onKbPage()) {
          clearInterval(state.timer);
          state.timer = null;
          return;
        }
        loadMeta().then(loadItems).then(function () {
          renderStatusPill();
          renderDashboard();
          schedulePolling();
        }).catch(function () { /* keep polling */ });
      }, 1600);
    }
  }

  function render() {
    if (!onKbPage()) {
      if (state.timer) { clearInterval(state.timer); state.timer = null; }
      return;
    }
    if (!isLoggedIn() || !isAdmin()) {
      renderGate();
      renderStatusPill();
      return;
    }
    refresh();
  }

  /* ---- Init --------------------------------------------------------- */

  function init() {
    window.KnowledgeBaseAdmin = { render: render, refresh: refresh };

    window.addEventListener('hashchange', render);

    if (window.ObamaAuth && typeof window.ObamaAuth.render === 'function') {
      var baseRender = window.ObamaAuth.render;
      window.ObamaAuth.render = function () {
        baseRender.apply(window.ObamaAuth, arguments);
        if (onKbPage()) render();
      };
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
