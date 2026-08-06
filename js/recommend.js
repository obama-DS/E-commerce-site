/**
 * Recommendations — AI recommendation system for Obama Store.
 *
 * Layered, production-ready architecture (no build step, React 18 + htm):
 *
 *  1. Signals journal      — an append-only activity log (views, searches,
 *                            wishlist, cart, purchases) persisted to
 *                            localStorage so personalization survives sessions.
 *  2. API client           — talks to the FastAPI `/api/v1/recommendations`
 *                            endpoints with promise-based caching (TTL) and
 *                            request timeouts.
 *  3. Fallback engine      — a local content-based recommender over
 *                            js/catalog.js so the feature degrades gracefully
 *                            when the API is unreachable.
 *  4. Reusable UI          — <RecSection> (async, auto-refreshing) renders
 *                            <RecRow> → <RecCard> with loading / empty / error
 *                            states. Shared by home.js and product.js.
 *
 * Consumers call window.Recommendations (data) and window.RecommendUI (React).
 */
(function () {
  'use strict';

  var API_BASE = window.location.protocol.indexOf('http') === 0
    ? window.location.origin
    : 'http://127.0.0.1:8000';

  /* ==================================================================
     Signals journal
     ================================================================== */

  var STORAGE_KEY = 'obama-store-signals';
  var listeners = new Set();

  function emptySignals() {
    return { views: [], searches: [], wishlist: [], cart: [], purchases: [] };
  }

  function loadSignals() {
    try {
      var raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (raw && typeof raw === 'object') return raw;
    } catch (e) { /* corrupted storage — reset */ }
    return emptySignals();
  }

  function saveSignals() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(signals));
    } catch (e) { /* storage unavailable — ignore */ }
  }

  var signals = loadSignals();

  function notify() {
    cache.clear();
    listeners.forEach(function (fn) {
      try { fn(signals); } catch (e) { /* listener error — ignore */ }
    });
  }

  function track(list, entry, max) {
    signals[list] = [entry].concat(signals[list] || []).slice(0, max);
    saveSignals();
    notify();
  }

  var Signals = {
    trackView: function (id) {
      if (!id) return;
      track('views', { id: id, at: Date.now() }, 50);
    },
    trackSearch: function (query) {
      var q = String(query || '').trim().toLowerCase();
      if (!q) return;
      track('searches', { q: q, at: Date.now() }, 30);
    },
    trackCart: function (id, qty) {
      if (!id) return;
      track('cart', { id: id, qty: Math.max(1, Number(qty) || 1), at: Date.now() }, 20);
    },
    trackWishlist: function (id) {
      if (!id) return;
      track('wishlist', String(id), 30);
    },
    trackPurchase: function (ids) {
      var list = (ids || []).filter(Boolean).map(String);
      if (!list.length) return;
      list.forEach(function (id) {
        signals.purchases = [id].concat(signals.purchases || []).slice(0, 50);
      });
      saveSignals();
      notify();
    },
    clear: function () {
      signals = emptySignals();
      saveSignals();
      notify();
    },
    get: function () {
      function idList(list) {
        return (list || []).map(function (entry) {
          if (entry && typeof entry === 'object') return entry.id;
          return entry;
        }).filter(Boolean);
      }
      return {
        views: (signals.views || []).slice(),
        searches: (signals.searches || []).slice(),
        wishlist: idList(signals.wishlist),
        cart: (signals.cart || []).slice(),
        purchases: idList(signals.purchases)
      };
    }
  };

  /* ==================================================================
     API client + caching
     ================================================================== */

  var API_ROOT = '/api/v1/recommendations';
  var TTL_PERSONAL = 60 * 1000;      // 60s
  var TTL_STATIC = 5 * 60 * 1000;    // 5m
  var cache = new Map();

  function cacheGet(key) {
    var entry = cache.get(key);
    if (entry && entry.expires > Date.now()) return entry.promise;
    return null;
  }

  function cacheSet(key, ttl, promise) {
    cache.set(key, { expires: Date.now() + ttl, promise: promise });
    return promise;
  }

  function api(path, body, opts) {
    opts = opts || {};
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, opts.timeout || 6000) : null;
    return fetch(API_BASE + path, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl ? ctrl.signal : undefined,
      cache: 'no-store'
    }).then(function (res) {
      if (!res.ok) throw new Error('Recommendation API HTTP ' + res.status);
      return res.json();
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  function postSections(context) {
    var key = 'ctx:' + (context.page || '') + ':' + (context.productId || '');
    var hit = cacheGet(key);
    if (hit) return hit;
    var promise = api(API_ROOT, { context: context, signals: Signals.get() });
    promise.catch(function () { cache.delete(key); });
    return cacheSet(key, TTL_PERSONAL, promise);
  }

  function getStatic(path) {
    var hit = cacheGet(path);
    if (hit) return hit;
    var promise = api(path);
    promise.catch(function () { cache.delete(path); });
    return cacheSet(path, TTL_STATIC, promise);
  }

  /* ==================================================================
     Slot registry
     ================================================================== */

  var SLOTS = {
    recommended: { key: 'recommended', title: 'Recommended for You', reason: 'Personalized picks based on your activity', endpoint: 'post' },
    trending: { key: 'trending', title: 'Trending Products', reason: 'What shoppers are buying right now', endpoint: 'get', path: API_ROOT + '/trending' },
    'best-sellers': { key: 'best_sellers', title: 'Best Sellers', reason: 'Our most popular products', endpoint: 'get', path: API_ROOT + '/best-sellers' },
    'new-arrivals': { key: 'new_arrivals', title: 'New Arrivals', reason: 'Just added to the store', endpoint: 'get', path: API_ROOT + '/new-arrivals' },
    similar: { key: 'similar', title: 'Similar Products', reason: 'Products most similar to what you are viewing', endpoint: 'post' },
    'also-viewed': { key: 'also_viewed', title: 'Customers Also Viewed', reason: 'Shoppers who viewed this item also looked at', endpoint: 'post' },
    'frequently-bought': { key: 'frequently_bought', title: 'Frequently Bought Together', reason: 'Customers who bought this item also bought', endpoint: 'post' }
  };

  function normalize(slot, section, generatedAt, source) {
    var cfg = SLOTS[slot];
    var products = (section.products || []).map(function (p, i) {
      p.recommendKey = slot + ':' + (p.id || i);
      return p;
    });
    return {
      slot: slot,
      title: section.title || cfg.title,
      reason: section.reason || cfg.reason,
      products: products,
      personalized: !!section.personalized,
      source: source,
      generatedAt: generatedAt || null
    };
  }

  function fetchFromApi(slot, context) {
    var cfg = SLOTS[slot];
    if (!cfg) return Promise.reject(new Error('Unknown slot ' + slot));

    if (cfg.endpoint === 'get') {
      return getStatic(cfg.path).then(function (data) {
        return normalize(slot, data.sections[cfg.key] || {}, null, 'api');
      });
    }

    return postSections(context).then(function (data) {
      return normalize(slot, data.sections[cfg.key] || {}, data.generated_at, 'api');
    });
  }

  /* ==================================================================
     Local fallback engine (mirrors backend logic over js/catalog.js)
     ================================================================== */

  function localEngine() {
    var catalog = window.ObamaCatalog;
    if (!catalog) return null;

    function tagSet(p) { return new Set((p.tags || []).map(function (t) { return t.toLowerCase(); })); }

    function jaccard(a, b) {
      var A = tagSet(a), B = tagSet(b);
      if (!A.size && !B.size) return 0;
      var inter = 0;
      A.forEach(function (t) { if (B.has(t)) inter += 1; });
      var union = new Set(A);
      B.forEach(function (t) { union.add(t); });
      return union.size ? inter / union.size : 0;
    }

    function affinity(a, b) {
      return jaccard(a, b) + (a.category === b.category ? 0.35 : 0) + (a.brand === b.brand ? 0.2 : 0);
    }

    function popularity(p) { return (p.rating || 0) * Math.log1p(p.reviewCount || 1); }

    function decay(at) {
      var HALF = 7 * 86400000;
      return Math.pow(0.5, Math.max(0, (Date.now() - Number(at || 0)) / HALF));
    }

    function profileWeights() {
      var weights = {};
      function add(id, w) { if (catalog.getProduct(id)) weights[id] = (weights[id] || 0) + w; }
      Signals.get().views.forEach(function (v) { if (v.id) add(v.id, 0.6 * decay(v.at)); });
      Signals.get().wishlist.forEach(function (id) { add(id, 1.0); });
      Signals.get().cart.forEach(function (c) { if (c.id) add(c.id, 1.2 * (c.qty || 1)); });
      Signals.get().purchases.forEach(function (id) { add(id, 2.0); });
      Signals.get().searches.forEach(function (s) {
        var tokens = String(s.q || '').toLowerCase().split(/\s+/).filter(function (t) { return t.length > 2; });
        catalog.products.forEach(function (p) {
          var hay = (p.title + ' ' + p.category + ' ' + (p.tags || []).join(' ')).toLowerCase();
          if (tokens.some(function (t) { return hay.indexOf(t) !== -1; })) add(p.id, 0.35 * decay(s.at));
        });
      });
      return weights;
    }

    function personal(excludeId, limit) {
      var weights = profileWeights();
      var maxPop = Math.max.apply(null, catalog.products.map(popularity).concat([1e-9]));
      var scored = catalog.products
        .filter(function (p) { return p.id !== excludeId; })
        .map(function (p) {
          var content = 0;
          Object.keys(weights).forEach(function (sid) {
            var s = catalog.getProduct(sid);
            if (s) content += weights[sid] * affinity(p, s);
          });
          return { p: p, score: content + 0.3 * (popularity(p) / maxPop) };
        })
        .sort(function (a, b) { return b.score - a.score; });
      var products = scored.slice(0, limit || 8).map(function (x) { return x.p; });
      var personalized = Object.keys(weights).length > 0;
      return {
        personalized: personalized,
        reason: personalized ? 'Because you browsed similar items' : 'Popular picks for you',
        products: products
      };
    }

    function similar(productId, limit) {
      var p = catalog.getProduct(productId);
      if (!p) return [];
      return catalog.products
        .filter(function (q) { return q.id !== productId; })
        .map(function (q) { return { q: q, s: affinity(p, q) }; })
        .filter(function (x) { return x.s > 0.05; })
        .sort(function (a, b) { return b.s - a.s; })
        .slice(0, limit || 6)
        .map(function (x) { return x.q; });
    }

    function alsoViewed(productId) {
      var p = catalog.getProduct(productId);
      if (!p) return [];
      var out = [];
      var seen = new Set([productId]);
      catalog.products.forEach(function (q) {
        if (q.category === p.category && q.id !== productId && !seen.has(q.id)) { seen.add(q.id); out.push(q); }
      });
      catalog.products
        .slice()
        .sort(function (a, b) { return popularity(b) - popularity(a); })
        .forEach(function (q) {
          if (!seen.has(q.id)) { seen.add(q.id); out.push(q); }
        });
      return out.slice(0, 6);
    }

    function frequentlyBought(productId) {
      var p = catalog.getProduct(productId);
      return p ? catalog.getBundle(p) : [];
    }

    function trending(limit) {
      return catalog.products
        .slice()
        .sort(function (a, b) {
          var ta = popularity(a) * ((a.badge || '').toLowerCase().indexOf('new arrival') !== -1 ? 1.15 : 1);
          var tb = popularity(b) * ((b.badge || '').toLowerCase().indexOf('new arrival') !== -1 ? 1.15 : 1);
          return tb - ta;
        })
        .slice(0, limit || 8);
    }

    function bestSellers(limit) {
      return catalog.products.slice().sort(function (a, b) { return (b.reviewCount || 0) - (a.reviewCount || 0); }).slice(0, limit || 8);
    }

    function newArrivals(limit) {
      return catalog.products
        .filter(function (p) { return (p.badge || '').toLowerCase().indexOf('new arrival') !== -1; })
        .sort(function (a, b) { return (b.reviewCount || 0) - (a.reviewCount || 0); })
        .slice(0, limit || 8);
    }

    return {
      personal: personal,
      similar: similar,
      alsoViewed: alsoViewed,
      frequentlyBought: frequentlyBought,
      trending: trending,
      bestSellers: bestSellers,
      newArrivals: newArrivals
    };
  }

  function fetchFromLocal(slot, context, limit) {
    var engine = localEngine();
    var cfg = SLOTS[slot];
    if (!engine || !cfg) return Promise.reject(new Error('Fallback engine unavailable for ' + slot));

    var data;
    switch (slot) {
      case 'recommended': data = engine.personal(context.productId, limit); break;
      case 'similar': data = { reason: cfg.reason, products: engine.similar(context.productId, limit) }; break;
      case 'also-viewed': data = { reason: cfg.reason, products: engine.alsoViewed(context.productId) }; break;
      case 'frequently-bought': data = { reason: cfg.reason, products: engine.frequentlyBought(context.productId) }; break;
      case 'trending': data = { reason: cfg.reason, products: engine.trending(limit) }; break;
      case 'best-sellers': data = { reason: cfg.reason, products: engine.bestSellers(limit) }; break;
      case 'new-arrivals': data = { reason: cfg.reason, products: engine.newArrivals(limit) }; break;
      default: data = { reason: cfg.reason, products: [] };
    }
    return Promise.resolve(normalize(slot, data, null, 'fallback'));
  }

  function fetchSection(slot, context, limit) {
    return fetchFromApi(slot, context).catch(function () {
      return fetchFromLocal(slot, context, limit);
    });
  }

  function clearUserData() {
    Signals.clear();
  }

  /* ==================================================================
     Reusable React UI components
     ================================================================== */

  var RecCard = null;
  var RecRow = null;
  var RecSection = null;

  if (window.React && window.ReactDOM && window.htm) {
    var React2 = window.React;
    var htm = window.htm;
      var html = (window.MotionHtm || htm.bind)(React2.createElement);
    var useState = React2.useState;
    var useEffect = React2.useEffect;
    var useRef = React2.useRef;

    function openProduct(id) {
      if (window.AppRouter) window.AppRouter.navigate('product', { id: id });
    }

    function currentRoute() {
      var m = String(window.location.hash).match(/^#\/([a-z-]+)/);
      return m ? m[1] : 'home';
    }

    function valuePercent(score) {
      var v = Number(score);
      if (!Number.isFinite(v)) return null;
      var pct = Math.max(0, Math.min(100, Math.round(((v + 0.3) / 0.6) * 100)));
      return Math.round(pct / 5) * 5;
    }

    function Stars({ rating, count }) {
      var full = Math.round(Number(rating) || 0);
      var stars = [];
      for (var i = 1; i <= 5; i += 1) {
        stars.push(html`<span key=${i} className="rec-star ${i <= full ? 'is-full' : ''}" aria-hidden="true">★</span>`);
      }
      return html`
        <span className="rec-stars" role="img" aria-label=${'Rated ' + (Number(rating) || 0) + ' out of 5'}>
          ${stars}
          ${count ? html`<span className="rec-stars-count">${count} reviews</span>` : null}
        </span>
      `;
    }

    RecCard = function RecCard({ product, onOpen, showReason }) {
      var helpers = window.StoreHelpers;
      var favState = useState(helpers ? helpers.isFavoriteProduct(product.id) : false);
      var isFav = favState[0];
      var setIsFav = favState[1];
      var label = isFav ? 'Remove from wishlist' : 'Add to wishlist';
      var srcList = (product.images && product.images.length ? product.images : [product.imageUrl]);
      var onImgError = function (event) {
        var img = event.currentTarget;
        if (img.dataset.fbDone) return;
        var current = img.getAttribute('src');
        var index = srcList.indexOf(current);
        var candidate = srcList[index + 1] || srcList[0];
        if (candidate && candidate !== current) {
          img.dataset.fbDone = '1';
          img.src = candidate;
        }
      };
      return html`
        <motion.article
          className="rec-card"
          variants=${{ hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } } }}
          whileHover=${{ y: -4 }}
          transition=${{ type: 'spring', stiffness: 320, damping: 26 }}
        >
          <button type="button" className="rec-card-img" onClick=${() => (onOpen || openProduct)(product.id)} aria-label=${'View ' + product.title}>
            <img src=${product.imageUrl} alt=${product.title} loading="lazy" decoding="async" onError=${onImgError} />
            ${product.badge ? html`<span className="rec-card-badge">${product.badge}</span>` : null}
          </button>
          <div className="rec-card-body">
            <span className="rec-card-cat">${product.category}</span>
            <h3><button type="button" className="rec-card-title" onClick=${() => (onOpen || openProduct)(product.id)}>${product.title}</button></h3>
            ${product.rating ? html`<${Stars} rating=${product.rating} count=${product.reviewCount} />` : null}
            <div className="rec-card-footer">
              <span className="rec-card-price">${product.priceText}</span>
              ${typeof product.valueScore === 'number' ? html`<span className="rec-card-value" title="AI value index from the car price model" aria-label=${'AI value index ' + valuePercent(product.valueScore) + ' percent'}>AI ${valuePercent(product.valueScore)}%</span>` : null}
              <div className="rec-card-actions">
                <button type="button" className="rec-card-cart" onClick=${() => {
                  if (window.addItemToCart) window.addItemToCart(product.title, product.priceText);
                }}>Add</button>
                ${helpers ? html`
                  <button type="button" className="rec-card-fav ${isFav ? 'is-active' : ''}" aria-pressed=${String(isFav)} aria-label=${label} onClick=${() => {
                    var now = helpers.toggleFavoriteProduct({
                      id: product.id,
                      title: product.title,
                      priceText: product.priceText,
                      description: product.shortDescription || '',
                      image: product.imageUrl
                    });
                    setIsFav(now);
                  }}>${isFav ? '♥' : '♡'}</button>
                ` : null}
              </div>
            </div>
            ${showReason && product.reason ? html`<span className="rec-card-reason">${product.reason}</span>` : null}
          </div>
        </motion.article>
      `;
    };

    RecRow = function RecRow({ title, reason, products, onOpen, variant, slotId, showReason }) {
      var ref = useRef(null);
      var scrollBy = function (dir) {
        var node = ref.current;
        if (!node) return;
        node.scrollBy({ left: dir * Math.round(node.clientWidth * 0.7), behavior: 'smooth' });
      };
      var isGrid = variant === 'grid';

      return html`
        <motion.section
          className="rec-section"
          aria-labelledby=${slotId}
          initial=${{ opacity: 0, y: 24 }}
          whileInView=${{ opacity: 1, y: 0 }}
          viewport=${{ once: true, amount: 0.1 }}
          transition=${{ duration: 0.5, ease: 'easeOut' }}
        >
          <div className="rec-heading">
            <div className="rec-heading-text">
              ${reason ? html`<p className="eyebrow">${reason}</p>` : null}
              <h2 id=${slotId}>${title}</h2>
            </div>
            ${isGrid ? null : html`
              <div className="rec-controls">
                <button type="button" className="rec-arrow" onClick=${() => scrollBy(-1)} aria-label="Scroll left">‹</button>
                <button type="button" className="rec-arrow" onClick=${() => scrollBy(1)} aria-label="Scroll right">›</button>
              </div>
            `}
          </div>
          <motion.div
            className=${isGrid ? 'rec-grid' : 'rec-row'}
            ref=${ref}
            variants=${{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
            initial="hidden"
            whileInView="show"
            viewport=${{ once: true, amount: 0.1 }}
          >
            ${products.map(function (p) {
              return html`<${RecCard} key=${p.recommendKey || p.id} product=${p} onOpen=${onOpen} showReason=${showReason} />`;
            })}
          </motion.div>
        </motion.section>
      `;
    };

    function RecSkeleton({ variant, cards }) {
      var count = cards || (variant === 'grid' ? 4 : 5);
      var items = [];
      for (var i = 0; i < count; i += 1) items.push(i);
      return html`
        <section className="rec-section" aria-label="Loading recommendations" aria-busy="true">
          <div className="rec-heading">
            <div className="rec-heading-text">
              <div className="rec-skeleton-block" style=${{ width: '32%', height: 14 }}></div>
              <div className="rec-skeleton-block" style=${{ width: '46%', height: 26 }}></div>
            </div>
          </div>
          <div className=${variant === 'grid' ? 'rec-grid' : 'rec-row'}>
            ${items.map(function (i) {
              return html`<div className="rec-skeleton-card" key=${i}></div>`;
            })}
          </div>
        </section>
      `;
    }

    function RecError({ onRetry }) {
      return html`
        <section className="rec-section rec-error" role="alert">
          <span aria-hidden="true">⚠️</span>
          <div>
            <strong>Recommendations unavailable</strong>
            <p>We could not load personalized picks right now.</p>
          </div>
          <button type="button" className="button secondary" onClick=${onRetry}>Try again</button>
        </section>
      `;
    }

    function RecEmpty({ onBrowse }) {
      return html`
        <section className="rec-section rec-empty">
          <span className="rec-empty-icon" aria-hidden="true">✨</span>
          <div>
            <h2>Recommended for you</h2>
            <p>Explore the store and we will learn your taste — your picks will appear here.</p>
          </div>
          <a className="button primary" href=${'#' + (onBrowse || '/products')}>Start browsing</a>
        </section>
      `;
    }

    var refreshThrottle = new Map();
    var uid = 0;

    RecSection = function RecSection(props) {
      var slot = props.slot;
      var productId = props.productId;
      var limit = props.limit || 8;
      var variant = props.variant || 'row';
      var titleOverride = props.title;
      var children = props.children;
      var renderFn = null;
      if (children && children.length) {
        for (var i = 0; i < children.length; i += 1) {
          if (typeof children[i] === 'function') { renderFn = children[i]; break; }
        }
      }

      var _useState = useState({ status: 'loading', data: null });
      var state = _useState[0];
      var setState = _useState[1];
      var attempt = useState(0)[0];
      var setAttempt = useState(0)[1];
      var idRef = useRef(uid += 1);
      var slotId = 'rec-' + slot + '-' + idRef.current;

      var context = { page: currentRoute(), productId: productId };

      useEffect(function () {
        var cancelled = false;
        setState(function (s) { return { status: 'loading', data: s.data }; });
        fetchSection(slot, context, limit).then(function (result) {
          if (!cancelled) setState({ status: 'ready', data: result });
        }).catch(function () {
          if (!cancelled) setState({ status: 'error', data: null });
        });
        return function () { cancelled = true; };
      }, [slot, productId, attempt]);

      useEffect(function () {
        return subscribeForRefresh(slot, setState, setAttempt);
      }, [slot]);

      if (state.status === 'loading' && !state.data) {
        return html`<${RecSkeleton} variant=${variant} />`;
      }
      if (state.status === 'error') {
        return html`<${RecError} onRetry=${function () { setAttempt(function (a) { return a + 1; }); }} />`;
      }

      var data = state.data;
      var products = data && data.products ? data.products : [];
      if (!products.length) {
        if (slot === 'recommended') return html`<${RecEmpty} />`;
        return null;
      }

      if (renderFn) {
        return renderFn(data);
      }

      return html`
        <${RecRow}
          title=${titleOverride || data.title}
          reason=${data.reason}
          products=${products}
          variant=${variant}
          slotId=${slotId}
          onOpen=${props.onOpen}
          showReason=${props.showReason}
        />
      `;
    };

    function subscribeForRefresh(slot, setState, setAttempt) {
      var unsub = subscribe(function () {
        var nowMs = Date.now();
        var last = refreshThrottle.get(slot) || 0;
        if (nowMs - last < 1500) return;
        refreshThrottle.set(slot, nowMs);
        setAttempt(function (a) { return a + 1; });
      });
      return function () {
        unsub();
        refreshThrottle.delete(slot);
      };
    }

    function mountProductsRec() {
      var mounts = document.querySelectorAll('[data-recommend-slot]');
      mounts.forEach(function (mount) {
        if (!mount || mount.dataset.mounted === 'true') return;
        mount.dataset.mounted = 'true';
        var root = ReactDOM.createRoot(mount);
        root.render(html`<${RecSection} slot=${mount.dataset.recommendSlot} variant="grid" />`);
      });
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mountProductsRec);
    } else {
      mountProductsRec();
    }
  }

  /* ==================================================================
     Public API
     ================================================================== */

  function subscribe(fn) {
    listeners.add(fn);
    return function () { listeners.delete(fn); };
  }

  window.Recommendations = {
    signals: Signals,
    fetchSection: fetchSection,
    fetchFromApi: fetchFromApi,
    subscribe: subscribe,
    getSignals: Signals.get,
    clearUserData: clearUserData,
    clearCache: function () { cache.clear(); },
    apiRoot: API_ROOT
  };

  window.RecommendUI = {
    RecSection: RecSection,
    RecRow: RecRow,
    RecCard: RecCard
  };
})();
