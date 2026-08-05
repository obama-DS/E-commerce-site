/**
 * ProductDetails — premium product page built with React 18 + htm (no build step).
 *
 * UI components are separated from data logic (js/catalog.js) and shared app
 * state (js/store.js). Rendering is driven by the hash router: when the route
 * is `#/product?id=<id>`, router calls window.ProductDetails.render().
 */
(function () {
  'use strict';

  if (!window.React || !window.ReactDOM || !window.htm) {
    console.warn('React (or htm) not loaded — product page unavailable.');
    return;
  }
  if (!window.ObamaCatalog) {
    console.warn('ObamaCatalog missing — product page unavailable.');
    return;
  }

  const { useState, useEffect, useRef, useMemo } = React;
  const html = (window.MotionHtm || htm.bind)(React.createElement);
  const catalog = window.ObamaCatalog;

  const RecSection = (window.RecommendUI && window.RecommendUI.RecSection) ? window.RecommendUI.RecSection : null;
  const Rec = RecSection || function RecSlot() { return null; };

  /* ==================================================================
     Pure helpers (data logic)
     ================================================================== */

  function variantParts(product, variant) {
    return Object.keys(variant || {}).filter(key => variant[key]).map(key => variant[key]);
  }

  function variantLabel(product, variant) {
    const parts = variantParts(product, variant);
    return parts.length ? parts.join(' · ') : '';
  }

  function cartTitle(product, variant) {
    const label = variantLabel(product, variant);
    return label ? `${product.title} — ${label}` : product.title;
  }

  function optionExtra(product, variant) {
    let extra = 0;
    (product.options.storage || []).forEach(opt => { if (opt.name === variant.storage) extra += opt.extra || 0; });
    (product.options.size || []).forEach(opt => { if (opt.name === variant.size) extra += opt.extra || 0; });
    (product.options.capacity || []).forEach(opt => { if (opt.name === variant.capacity) extra += opt.extra || 0; });
    return extra;
  }

  function effectivePrice(product, variant) {
    return product.priceValue + optionExtra(product, variant);
  }

  function stockState(product) {
    if (product.stock <= 0) return { label: 'Out of stock', tone: 'out' };
    if (product.stock <= 5) return { label: `Low stock — only ${product.stock} left`, tone: 'low' };
    return { label: 'In stock', tone: 'in' };
  }

  function navigate(path, params) {
    if (window.AppRouter) window.AppRouter.navigate(path, params);
  }

  /* ==================================================================
     Small atoms
     ================================================================== */

  function Stars({ rating, size = 'md', count }) {
    const full = Math.round(rating);
    const stars = [];
    for (let i = 1; i <= 5; i += 1) {
      stars.push(html`<span key=${i} className="pdp-star ${i <= full ? 'is-full' : ''}" aria-hidden="true">★</span>`);
    }
    return html`
      <span className="pdp-stars pdp-stars-${size}" role="img" aria-label=${`Rated ${rating} out of 5`}>
        ${stars}
        ${count !== undefined ? html`<span className="pdp-stars-count">${count} reviews</span>` : null}
      </span>
    `;
  }

  function SectionHeading({ eyebrow, title, action }) {
    return html`
      <div className="pdp-section-heading">
        <div>
          ${eyebrow ? html`<p className="eyebrow">${eyebrow}</p>` : null}
          <h2>${title}</h2>
        </div>
        ${action || null}
      </div>
    `;
  }

  /* ==================================================================
     Product gallery (thumbnails, zoom, fullscreen)
     ================================================================== */

  function Gallery({ product, images, index, onIndex, zoomLevel, onZoomLevel, onOpenFullscreen }) {
    const mainRef = useRef(null);
    const count = images.length;
    const zoomed = zoomLevel > 1;
    const [hovering, setHovering] = useState(false);
    const effectiveZoom = (hovering && !zoomed) ? 2 : zoomLevel;

    const positionZoom = event => {
      const node = mainRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 100;
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      node.style.setProperty('--zoom-x', `${x}%`);
      node.style.setProperty('--zoom-y', `${y}%`);
    };

    const handleMove = event => {
      if (!hovering && !zoomed) return;
      positionZoom(event);
    };

    const stepZoom = delta => {
      const current = Number(zoomLevel) || 1;
      const next = Math.round(Math.min(2, Math.max(1, current + delta)) * 10) / 10;
      onZoomLevel(next);
    };

    const prev = () => onIndex((index - 1 + count) % count);
    const next = () => onIndex((index + 1) % count);

    const fallback = event => {
      const img = event.currentTarget;
      if (img.dataset.fbDone) return;
      const idx = Number(img.dataset.idx) || index;
      const candidate = images[(idx + 1) % count];
      if (candidate && candidate !== img.getAttribute('src')) {
        img.dataset.fbDone = '1';
        img.src = candidate;
      }
    };

    return html`
      <div className="pdp-gallery">
        <div
          ref=${mainRef}
          className="pdp-main-image ${zoomed ? 'is-zoomed' : ''}"
          style=${{ '--zoom-level': String(effectiveZoom) }}
          onMouseMove=${handleMove}
          onMouseEnter=${event => { setHovering(true); positionZoom(event); }}
          onMouseLeave=${() => setHovering(false)}
        >
          <img src=${images[index]} alt=${product.alt} onError=${fallback} onClick=${onOpenFullscreen} loading="eager" />
          ${product.badge ? html`<span className="pdp-badge">${product.badge}</span>` : null}
          ${count > 1 ? html`
            <button type="button" className="pdp-arrow prev" onClick=${prev} aria-label="Previous image">‹</button>
            <button type="button" className="pdp-arrow next" onClick=${next} aria-label="Next image">›</button>
          ` : null}
          <button type="button" className="pdp-expand-btn" onClick=${onOpenFullscreen} aria-label="Open fullscreen preview">
            <span aria-hidden="true">⤢</span> Expand
          </button>
        </div>

        <div className="pdp-zoom-bar" role="group" aria-label="Zoom controls">
          <button type="button" className="pdp-zoom-btn" onClick=${() => stepZoom(-0.5)} disabled=${!zoomed} aria-label="Zoom out">−</button>
          <output className="pdp-zoom-value" aria-live="polite">${Math.round(zoomLevel * 100)}%</output>
          <button type="button" className="pdp-zoom-btn" onClick=${() => stepZoom(0.5)} disabled=${zoomLevel >= 2} aria-label="Zoom in">+</button>
          <button type="button" className="pdp-zoom-reset" onClick=${() => onZoomLevel(1)} disabled=${!zoomed}>Reset</button>
        </div>

        <div className="pdp-thumbs" role="tablist" aria-label="Product images">
          ${images.map((img, i) => html`
            <button
              type="button"
              key=${i}
              role="tab"
              aria-selected=${String(i === index)}
              className="pdp-thumb ${i === index ? 'is-active' : ''}"
              onClick=${() => onIndex(i)}
              aria-label=${`View image ${i + 1}`}
            >
              <img src=${img} alt="" data-idx=${i} loading="lazy" onError=${fallback} />
            </button>
          `)}
        </div>
      </div>
    `;
  }

  function FullscreenModal({ images, index, onIndex, onClose }) {
    const [modalZoom, setModalZoom] = useState(1);
    const [hovering, setHovering] = useState(false);
    const stageRef = useRef(null);

    useEffect(() => {
      setModalZoom(1);
    }, [index]);

    useEffect(() => {
      const prev = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      const onKey = event => {
        if (event.key === 'Escape') onClose();
        if (event.key === 'ArrowRight') onIndex((index + 1) % images.length);
        if (event.key === 'ArrowLeft') onIndex((index - 1 + images.length) % images.length);
        if (event.key === '+' || event.key === '=') setModalZoom(z => Math.min(2, Math.round((z + 0.5) * 10) / 10));
        if (event.key === '-') setModalZoom(z => Math.max(1, Math.round((z - 0.5) * 10) / 10));
      };
      window.addEventListener('keydown', onKey);
      return () => {
        document.body.style.overflow = prev;
        window.removeEventListener('keydown', onKey);
      };
    }, [images, index, onIndex, onClose]);

    const zoomed = modalZoom > 1;
    const effectiveZoom = (hovering && !zoomed) ? 2 : modalZoom;

    const positionZoom = event => {
      const node = stageRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 100;
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      node.style.setProperty('--zoom-x', `${x}%`);
      node.style.setProperty('--zoom-y', `${y}%`);
    };

    const handleMove = event => {
      if (!hovering && !zoomed) return;
      positionZoom(event);
    };

    return html`
      <div className="pdp-modal" role="dialog" aria-modal="true" aria-label="Fullscreen image preview" onClick=${onClose}>
        <div
          ref=${stageRef}
          className="pdp-modal-stage ${zoomed ? 'is-zoomed' : ''}"
          style=${{ '--zoom-level': String(effectiveZoom) }}
          onMouseMove=${handleMove}
          onMouseEnter=${event => { setHovering(true); positionZoom(event); }}
          onMouseLeave=${() => setHovering(false)}
          onClick=${event => event.stopPropagation()}
        >
          <img src=${images[index]} alt="" />
          <button type="button" className="pdp-modal-close" onClick=${onClose} aria-label="Close preview">✕</button>
          <button type="button" className="pdp-modal-arrow prev" onClick=${() => onIndex((index - 1 + images.length) % images.length)} aria-label="Previous image">‹</button>
          <button type="button" className="pdp-modal-arrow next" onClick=${() => onIndex((index + 1) % images.length)} aria-label="Next image">›</button>
          <span className="pdp-modal-counter">${index + 1} / ${images.length}</span>
        </div>
        <div className="pdp-modal-zoombar" role="group" aria-label="Zoom controls" onClick=${event => event.stopPropagation()}>
          <button type="button" className="pdp-zoom-btn" onClick=${() => setModalZoom(z => Math.max(1, Math.round((z - 0.5) * 10) / 10))} disabled=${!zoomed} aria-label="Zoom out">−</button>
          <output className="pdp-zoom-value">${Math.round(modalZoom * 100)}%</output>
          <button type="button" className="pdp-zoom-btn" onClick=${() => setModalZoom(z => Math.min(2, Math.round((z + 0.5) * 10) / 10))} disabled=${modalZoom >= 2} aria-label="Zoom in">+</button>
          <button type="button" className="pdp-zoom-reset" onClick=${() => setModalZoom(1)} disabled=${!zoomed}>Reset</button>
        </div>
      </div>
    `;
  }

  /* ==================================================================
     Product info (variants, quantity, actions)
     ================================================================== */

  function OptionGroup({ product, groupKey, label, variant, onSelect }) {
    const options = product.options[groupKey];
    if (!options || !options.length) return null;
    const isColor = groupKey === 'color';

    return html`
      <fieldset className="pdp-option">
        <legend>
          <span>${label}</span>
          <strong>${variant[groupKey]}</strong>
        </legend>
        <div className="pdp-option-values">
          ${options.map(opt => isColor ? html`
            <button
              type="button"
              key=${opt.name}
              className="pdp-swatch ${variant[groupKey] === opt.name ? 'is-active' : ''}"
              onClick=${() => onSelect(groupKey, opt.name)}
              title=${opt.name}
              aria-label=${`Color: ${opt.name}`}
              aria-pressed=${String(variant[groupKey] === opt.name)}
              style=${{ background: opt.swatch }}
            >
              ${variant[groupKey] === opt.name ? html`<span aria-hidden="true">✓</span>` : null}
            </button>
          ` : html`
            <button
              type="button"
              key=${opt.name}
              className="pdp-option-chip ${variant[groupKey] === opt.name ? 'is-active' : ''}"
              onClick=${() => onSelect(groupKey, opt.name)}
              aria-pressed=${String(variant[groupKey] === opt.name)}
            >
              ${opt.name}
              ${opt.extra ? html`<em>+$${opt.extra}</em>` : null}
            </button>
          `)}
        </div>
      </fieldset>
    `;
  }

  function QuantityStepper({ qty, setQty, max }) {
    const clamp = value => Math.max(1, Math.min(max, Number(value) || 1));
    return html`
      <div className="pdp-qty" aria-label="Quantity">
        <button type="button" onClick=${() => setQty(q => clamp(q - 1))} aria-label="Decrease quantity" disabled=${qty <= 1}>−</button>
        <input
          type="number"
          min="1"
          max=${max}
          value=${qty}
          aria-label="Quantity"
          onChange=${event => setQty(clamp(parseInt(event.target.value, 10)))}
        />
        <button type="button" onClick=${() => setQty(q => clamp(q + 1))} aria-label="Increase quantity" disabled=${qty >= max}>+</button>
      </div>
    `;
  }

  function InfoPanel({ product, variant, setVariant, qty, setQty, actions }) {
    const stock = stockState(product);
    const out = stock.tone === 'out';

    return html`
      <div className="pdp-info">
        <div className="pdp-brandline">
          <span className="pdp-brand">${product.brand}</span>
          <span className="pdp-category-link" onClick=${() => navigate('products', { category: product.category.toLowerCase() })}>${product.category}</span>
        </div>

        <h1 className="pdp-title">${product.title}</h1>

        <div className="pdp-rating-row">
          <${Stars} rating=${product.rating} count=${product.reviewCount} />
          <button type="button" className="pdp-review-anchor" onClick=${() => actions.scrollTo('pdp-reviews')}>Read reviews</button>
        </div>

        <div className="pdp-price-row">
          <span className="pdp-price">${catalog.formatPrice(effectivePrice(product, variant), product.currency)}</span>
          ${product.discount ? html`
            <span className="pdp-original-price">${product.originalPriceText}</span>
            <span className="pdp-discount">Save ${product.discount}%</span>
          ` : null}
        </div>

        <div className="pdp-stock">
          <span className="pdp-stock-dot pdp-stock-${stock.tone}" aria-hidden="true"></span>
          <span>${stock.label}</span>
          ${product.sku ? html`<span className="pdp-sku">SKU: ${product.sku}</span>` : null}
        </div>

        <p className="pdp-short-desc">${product.shortDescription}</p>

        <div className="pdp-options">
          <${OptionGroup} product=${product} groupKey="color" label="Color" variant=${variant} onSelect=${actions.setOption} />
          <${OptionGroup} product=${product} groupKey="size" label="Size" variant=${variant} onSelect=${actions.setOption} />
          <${OptionGroup} product=${product} groupKey="storage" label="Storage" variant=${variant} onSelect=${actions.setOption} />
          <${OptionGroup} product=${product} groupKey="capacity" label="Capacity" variant=${variant} onSelect=${actions.setOption} />
        </div>

        <div className="pdp-buy-row">
          <div className="pdp-qty-block">
            <span className="pdp-qty-label">Quantity</span>
            <${QuantityStepper} qty=${qty} setQty=${setQty} max=${Math.max(1, Math.min(10, product.stock))} />
          </div>
          <div className="pdp-cta-stack">
            <button type="button" className="pdp-add-cart" onClick=${() => actions.addToCart()} disabled=${out}>Add to cart</button>
            <button type="button" className="pdp-buy-now" onClick=${() => actions.buyNow()} disabled=${out}>Buy now</button>
          </div>
        </div>

        <div className="pdp-secondary-actions">
          <button type="button" className="pdp-icon-action ${actions.isFav ? 'is-active' : ''}" onClick=${actions.toggleFav} aria-pressed=${String(actions.isFav)}>
            <span aria-hidden="true">${actions.isFav ? '♥' : '♡'}</span> ${actions.isFav ? 'Saved' : 'Wishlist'}
          </button>
          <button type="button" className="pdp-icon-action ${actions.isCompared ? 'is-active' : ''}" onClick=${actions.toggleCompare} aria-pressed=${String(actions.isCompared)}>
            <span aria-hidden="true">⚖</span> ${actions.isCompared ? 'Compared' : 'Compare'}
          </button>
          <button type="button" className="pdp-icon-action" onClick=${actions.share}>
            <span aria-hidden="true">↗</span> Share
          </button>
        </div>

        <dl className="pdp-meta">
          <div><dt>Brand</dt><dd>${product.brand}</dd></div>
          <div><dt>Category</dt><dd>${product.category}</dd></div>
          <div><dt>Product ID</dt><dd>${product.id}</dd></div>
          <div><dt>Tags</dt><dd>${(product.tags || []).join(', ')}</dd></div>
        </dl>

        <div className="pdp-delivery">
          <span className="pdp-delivery-icon" aria-hidden="true">🚚</span>
          <div>
            <strong>${product.delivery.eta}</strong>
            <span>${product.delivery.cost} • Order confirmation by phone or email</span>
          </div>
        </div>
      </div>
    `;
  }

  /* ==================================================================
     Description / highlights / specifications (tabs)
     ================================================================== */

  function DetailTabs({ product }) {
    const [tab, setTab] = useState('description');
    const tabs = [
      { key: 'description', label: 'Description' },
      { key: 'highlights', label: 'Highlights' },
      { key: 'specs', label: 'Specifications' }
    ];

    return html`
      <section className="pdp-section pdp-detail-tabs" aria-label="Product details">
        <div className="pdp-tablist" role="tablist">
          ${tabs.map(t => html`
            <button type="button" key=${t.key} role="tab" aria-selected=${String(tab === t.key)} className="pdp-tab ${tab === t.key ? 'is-active' : ''}" onClick=${() => setTab(t.key)}>
              ${t.label}
            </button>
          `)}
        </div>

        <div className="pdp-tabpanel" role="tabpanel">
          ${tab === 'description' ? html`
            <div className="pdp-description">
              <p>${product.shortDescription}</p>
              <p>${product.detailedDescription}</p>
            </div>
          ` : null}
          ${tab === 'highlights' ? html`
            <ul className="pdp-highlights">
              ${product.highlights.map((h, i) => html`<li key=${i}><span aria-hidden="true">✓</span>${h}</li>`)}
            </ul>
          ` : null}
          ${tab === 'specs' ? html`
            <table className="pdp-spec-table">
              <tbody>
                ${product.specs.map((spec, i) => html`
                  <tr key=${i}><th>${spec.label}</th><td>${spec.value}</td></tr>
                `)}
              </tbody>
            </table>
          ` : null}
        </div>
      </section>
    `;
  }

  /* ==================================================================
     Reviews
     ================================================================== */

  function RatingBar({ percent }) {
    return html`
      <div className="pdp-bar" role="img" aria-label=${`${percent}%`}>
        <span style=${{ width: `${percent}%` }}></span>
      </div>
    `;
  }

  function Reviews({ product }) {
    const reviews = useMemo(() => catalog.reviewsFor(product), [product]);
    const breakdown = useMemo(() => catalog.ratingBreakdown(product.rating, product.reviewCount), [product]);
    const [showAll, setShowAll] = useState(false);
    const visible = showAll ? reviews : reviews.slice(0, 3);

    return html`
      <section className="pdp-section pdp-reviews" id="pdp-reviews" aria-labelledby="pdp-reviews-title">
        <${SectionHeading} eyebrow="Customer reviews" title="What buyers think" action=${html`<span className="section-pill">${product.reviewCount} verified reviews</span>`} />

        <div className="pdp-reviews-layout">
          <div className="pdp-rating-summary">
            <div className="pdp-score">
              <strong>${product.rating.toFixed(1)}</strong>
              <${Stars} rating=${product.rating} />
              <span>Based on ${product.reviewCount} reviews</span>
            </div>
            <div className="pdp-breakdown">
              ${breakdown.map(b => html`
                <div className="pdp-breakdown-row" key=${b.stars}>
                  <span>${b.stars} ★</span>
                  <${RatingBar} percent=${b.percent} />
                  <span className="pdp-breakdown-pct">${b.percent}%</span>
                </div>
              `)}
            </div>
          </div>

          <div className="pdp-review-list">
            ${visible.map((review, i) => html`
              <article className="pdp-review" key=${i}>
                <div className="pdp-review-head">
                  <span className="pdp-review-avatar" aria-hidden="true">${review.author.charAt(0)}</span>
                  <div>
                    <strong>${review.author}</strong>
                    <${Stars} rating=${review.rating} />
                  </div>
                  <time>${review.date}</time>
                </div>
                <h3>${review.title}</h3>
                <p>${review.body}</p>
                <span className="pdp-verified">✓ Verified purchase</span>
              </article>
            `)}
            ${reviews.length > 3 ? html`
              <button type="button" className="pdp-text-btn" onClick=${() => setShowAll(s => !s)}>
                ${showAll ? 'Show fewer reviews' : `Show all ${reviews.length} reviews`}
              </button>
            ` : null}
          </div>
        </div>
      </section>
    `;
  }

  /* ==================================================================
     Cross-sell rows
     ================================================================== */

  function MiniCard({ product, onOpen, trailing }) {
    return html`
      <article className="pdp-mini-card">
        <button type="button" className="pdp-mini-img" onClick=${() => onOpen(product.id)} aria-label=${`View ${product.title}`}>
          <img src=${product.imageUrl} alt=${product.alt} loading="lazy" />
        </button>
        <div className="pdp-mini-body">
          <h3><button type="button" onClick=${() => onOpen(product.id)}>${product.title}</button></h3>
          <${Stars} rating=${product.rating} />
          <span className="pdp-mini-price">${product.priceText}</span>
        </div>
        ${trailing || null}
      </article>
    `;
  }

  function BundleSection({ product, onOpen, onAddBundle }) {
    const bundle = useMemo(() => catalog.getBundle(product), [product]);
    const [checked, setChecked] = useState({});
    const [added, setAdded] = useState(false);

    if (!bundle.length) return null;

    const toggle = id => setChecked(c => ({ ...c, [id]: !c[id] }));
    const isChecked = id => checked[id] !== false;
    const selected = bundle.filter(p => isChecked(p.id));
    const total = product.priceValue + selected.reduce((sum, p) => sum + p.priceValue, 0);
    const totalText = catalog.formatPrice(total, product.currency);

    const addBundle = () => {
      onAddBundle([product, ...selected]);
      setAdded(true);
      setTimeout(() => setAdded(false), 2600);
    };

    return html`
      <section className="pdp-section pdp-bundle" aria-labelledby="pdp-bundle-title">
        <${SectionHeading} eyebrow="Bundle & save" title="Frequently bought together" />
        <div className="pdp-bundle-grid">
          <div className="pdp-bundle-items">
            ${[product, ...bundle].map((p, i) => html`
              <div className="pdp-bundle-item" key=${p.id}>
                ${i === 0 ? null : html`
                  <label className="pdp-bundle-check">
                    <input type="checkbox" checked=${isChecked(p.id)} onChange=${() => toggle(p.id)} aria-label=${`Add ${p.title}`} />
                    <span aria-hidden="true"></span>
                  </label>
                `}
                ${i > 0 ? html`<span className="pdp-bundle-plus" aria-hidden="true">+</span>` : null}
                <button type="button" className="pdp-bundle-img" onClick=${() => onOpen(p.id)}>
                  <img src=${p.imageUrl} alt=${p.alt} loading="lazy" />
                </button>
                <div className="pdp-bundle-info">
                  <button type="button" className="pdp-bundle-name" onClick=${() => onOpen(p.id)}>${p.title}</button>
                  <span className="pdp-bundle-price">${p.priceText}</span>
                </div>
              </div>
            `)}
          </div>

          <div className="pdp-bundle-total">
            <p>Bundle total</p>
            <strong>${totalText}</strong>
            <span className="pdp-bundle-note">Save more when you buy together</span>
            <button type="button" className="pdp-add-cart" onClick=${addBundle} disabled=${added}>
              ${added ? 'Added to cart ✓' : 'Add bundle to cart'}
            </button>
          </div>
        </div>
      </section>
    `;
  }

  function RecentlyViewed({ onOpen }) {
    const items = window.StoreHelpers ? window.StoreHelpers.getRecentlyViewed() : [];
    const products = items.map(item => catalog.getProduct(item.id)).filter(Boolean).filter(p => p.id !== currentIdShown());
    if (!products.length) return null;

    return html`
      <section className="pdp-section pdp-crossell" aria-label="Recently viewed">
        <${SectionHeading} eyebrow="Keep browsing" title="Recently viewed" />
        <div className="pdp-scroll-row">
          ${products.map(p => html`<${MiniCard} key=${p.id} product=${p} onOpen=${onOpen} />`)}
        </div>
      </section>
    `;
  }

  function currentIdShown() {
    const m = String(window.location.hash).match(/product\?id=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  /* ==================================================================
     Policies & FAQ
     ================================================================== */

  function PoliciesSection() {
    const cards = [
      { icon: '🚚', title: 'Delivery & shipping', points: ['Delivery inside Addis Ababa in 2–4 business days', 'Free delivery on orders over ETB 5,000', 'Orders confirmed by phone or email', 'Nationwide shipping on request'] },
      { icon: '↩️', title: 'Returns & refunds', points: ['30-day return window on unused items', 'Full refund for damaged or wrong items', 'Return shipping covered on defects', 'Easy process via the contact page'] },
      { icon: '🛡️', title: 'Warranty & support', points: ['12-month warranty on electronics', 'Verified products checked before shipping', 'Phone & Telegram support 24/7', 'Genuine accessories included'] }
    ];
    return html`
      <section className="pdp-section" aria-label="Delivery, returns and warranty">
        <${SectionHeading} eyebrow="Good to know" title="Delivery, returns & warranty" />
        <div className="pdp-policies">
          ${cards.map(card => html`
            <div className="pdp-policy" key=${card.title}>
              <span className="pdp-policy-icon" aria-hidden="true">${card.icon}</span>
              <h3>${card.title}</h3>
              <ul>
                ${card.points.map((p, i) => html`<li key=${i}>${p}</li>`)}
              </ul>
            </div>
          `)}
        </div>
      </section>
    `;
  }

  function FaqSection({ product }) {
    const faqs = [
      { q: 'Is this product authentic and guaranteed?', a: 'Yes. Every item is sourced from verified suppliers, inspected before shipping, and covered by our 12-month warranty on electronics.' },
      { q: 'How long does delivery take?', a: `${product.delivery.eta}. Orders are confirmed by phone or email, and you receive updates until handover.` },
      { q: 'How do I pay?', a: 'We accept Telebirr and CBE Pay. After payment, share the transaction ID on the payment page so we can confirm your order.' },
      { q: 'Can I return or exchange this item?', a: 'You have 30 days to return unused items in their original packaging. Damaged or incorrect items qualify for a full refund, including return shipping.' },
      { q: 'Is there a warranty?', a: product.warranty }
    ];
    const [open, setOpen] = useState(0);

    return html`
      <section className="pdp-section" aria-labelledby="pdp-faq-title">
        <${SectionHeading} eyebrow="Support" title="Frequently asked questions" />
        <div className="pdp-faq">
          ${faqs.map((item, i) => html`
            <div className="pdp-faq-item ${open === i ? 'is-open' : ''}" key=${i}>
              <button type="button" className="pdp-faq-q" onClick=${() => setOpen(open === i ? -1 : i)} aria-expanded=${String(open === i)}>
                <span>${item.q}</span>
                <span className="pdp-faq-toggle" aria-hidden="true">${open === i ? '−' : '+'}</span>
              </button>
              ${open === i ? html`<div className="pdp-faq-a"><p>${item.a}</p></div>` : null}
            </div>
          `)}
        </div>
      </section>
    `;
  }

  /* ==================================================================
     States: skeleton / not found
     ================================================================== */

  function ProductSkeleton() {
    return html`
      <div className="pdp-skeleton" aria-label="Loading product" aria-busy="true">
        <div className="pdp-skeleton-grid">
          <div className="pdp-skeleton-block" style=${{ height: 460 }}></div>
          <div className="pdp-skeleton-info">
            <div className="pdp-skeleton-block" style=${{ width: '38%', height: 20 }}></div>
            <div className="pdp-skeleton-block" style=${{ width: '80%', height: 34 }}></div>
            <div className="pdp-skeleton-block" style=${{ width: '55%', height: 18 }}></div>
            <div className="pdp-skeleton-block" style=${{ width: '45%', height: 44 }}></div>
            <div className="pdp-skeleton-block" style=${{ width: '100%', height: 120 }}></div>
            <div className="pdp-skeleton-block" style=${{ width: '100%', height: 92 }}></div>
          </div>
        </div>
      </div>
    `;
  }

  function NotFound() {
    return html`
      <div className="pdp-empty">
        <span className="pdp-empty-icon" aria-hidden="true">🔍</span>
        <h1>Product not found</h1>
        <p>This product may have sold out or the link is incorrect.</p>
        <button type="button" className="pdp-add-cart" onClick=${() => navigate('products')}>Continue shopping</button>
      </div>
    `;
  }

  /* ==================================================================
     Top-level page
     ================================================================== */

  function ProductPage({ product }) {
    const [variant, setVariant] = useState(() => {
      const init = {};
      Object.keys(product.options || {}).forEach(key => {
        if (product.options[key] && product.options[key].length) init[key] = product.options[key][0].name;
      });
      return init;
    });
    const [qty, setQty] = useState(1);
    const [imageIndex, setImageIndex] = useState(0);
    const [zoomLevel, setZoomLevel] = useState(1);
    const [fullscreen, setFullscreen] = useState(false);
    const [toast, setToast] = useState(null);

    const helpers = window.StoreHelpers;
    const isFav = helpers ? helpers.isFavoriteProduct(product.id) : false;
    const isCompared = helpers ? helpers.isComparedProduct(product.id) : false;

    useEffect(() => {
      setImageIndex(0);
      setQty(1);
      setZoomLevel(1);
      setFullscreen(false);
    }, [product.id]);

    useEffect(() => {
      if (!toast) return undefined;
      const t = setTimeout(() => setToast(null), 2600);
      return () => clearTimeout(t);
    }, [toast]);

    const notify = message => setToast(message);

    const setOption = (groupKey, name) => setVariant(v => ({ ...v, [groupKey]: name }));

    const priceText = catalog.formatPrice(effectivePrice(product, variant), product.currency);

    const addToCart = () => {
      window.addItemToCart(cartTitle(product, variant), priceText, qty);
      notify(`${qty} × ${cartTitle(product, variant)} added to cart`);
    };

    const buyNow = () => {
      window.addItemToCart(cartTitle(product, variant), priceText, qty);
      navigate('cart');
    };

    const toggleFav = () => {
      if (!helpers) return;
      const nowFav = helpers.toggleFavoriteProduct({
        id: product.id,
        title: product.title,
        priceText: product.priceText,
        description: product.shortDescription,
        image: product.imageUrl
      });
      notify(nowFav ? 'Added to wishlist' : 'Removed from wishlist');
    };

    const toggleCompare = () => {
      if (!helpers) return;
      const nowCompared = helpers.toggleCompareProduct({
        id: product.id,
        title: product.title,
        priceText: product.priceText,
        description: product.shortDescription,
        category: product.category
      });
      notify(nowCompared ? 'Added to compare' : 'Removed from compare');
    };

    const share = async () => {
      const url = `${window.location.origin}${window.location.pathname}#/product?id=${product.id}`;
      if (navigator.share) {
        try {
          await navigator.share({ title: product.title, text: product.shortDescription, url });
          return;
        } catch (error) {
          return;
        }
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          await navigator.clipboard.writeText(url);
          notify('Product link copied to clipboard');
          return;
        } catch (error) { /* fall through */ }
      }
      notify(url);
    };

    const scrollTo = id => {
      const node = document.getElementById(id);
      if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const onOpen = id => navigate('product', { id });

    const addBundle = list => {
      list.forEach(p => window.addItemToCart(p.title, p.priceText, 1));
      notify(`Added ${list.length} items to cart`);
    };

    return html`
      <motion.div
        className="pdp"
        initial=${{ opacity: 0, y: 16 }}
        animate=${{ opacity: 1, y: 0 }}
        transition=${{ duration: 0.4, ease: 'easeOut' }}
      >
        <nav className="pdp-breadcrumbs" aria-label="Breadcrumb">
          <button type="button" onClick=${() => navigate('home')}>Home</button>
          <span aria-hidden="true">/</span>
          <button type="button" onClick=${() => navigate('products', { category: product.category.toLowerCase() })}>${product.category}</button>
          <span aria-hidden="true">/</span>
          <span className="pdp-breadcrumb-current">${product.title}</span>
        </nav>

        <div className="pdp-main">
          <${Gallery}
            product=${product}
            images=${product.images}
            index=${imageIndex}
            onIndex=${setImageIndex}
            zoomLevel=${zoomLevel}
            onZoomLevel=${setZoomLevel}
            onOpenFullscreen=${() => setFullscreen(true)}
          />
          <${InfoPanel}
            product=${product}
            variant=${variant}
            setVariant=${setVariant}
            qty=${qty}
            setQty=${setQty}
            actions=${{ setOption, addToCart, buyNow, toggleFav, toggleCompare, share, scrollTo, isFav, isCompared }}
          />
        </div>

        <${DetailTabs} product=${product} />
        <${PoliciesSection} />
        <${Reviews} product=${product} />
        <${BundleSection} product=${product} onOpen=${onOpen} onAddBundle=${addBundle} />
        <${Rec} slot="recommended" productId=${product.id} onOpen=${onOpen} />
        <${Rec} slot="similar" productId=${product.id} onOpen=${onOpen} />
        <${Rec} slot="also-viewed" productId=${product.id} onOpen=${onOpen} />
        <${RecentlyViewed} onOpen=${onOpen} />
        <${FaqSection} product=${product} />

        <motion.animatepresence>
          ${fullscreen ? html`<${FullscreenModal} key="pdp-fullscreen" images=${product.images} index=${imageIndex} onIndex=${setImageIndex} onClose=${() => setFullscreen(false)} />` : null}
        </motion.animatepresence>

        ${toast ? html`<div className="pdp-toast" role="status" aria-live="polite"><span aria-hidden="true">✓</span>${toast}</div>` : null}
      </motion.div>
    `;
  }

  function ProductShell({ id }) {
    const [state, setState] = useState({ loading: true, product: null });

    useEffect(() => {
      let cancelled = false;
      setState({ loading: true, product: null });

      const timer = setTimeout(() => {
        if (cancelled) return;
        const product = id ? catalog.getProduct(id) : null;
        if (product && window.StoreHelpers) {
          window.StoreHelpers.trackRecentlyViewed(product);
        }
        if (product && window.Recommendations && window.Recommendations.signals) {
          window.Recommendations.signals.trackView(product.id);
        }
        setState({ loading: false, product });
      }, 320);

      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }, [id]);

    if (state.loading) return html`<${ProductSkeleton} />`;
    if (!state.product) return html`<${NotFound} />`;
    return html`<${ProductPage} product=${state.product} />`;
  }

  /* ==================================================================
     Mount / routing integration
     ================================================================== */

  let root = null;

  function parseId() {
    const m = String(window.location.hash).match(/product\?id=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function render() {
    const mount = document.getElementById('productMount');
    if (!mount) return;
    if (!root) root = ReactDOM.createRoot(mount);

    const id = parseId();
    if (!id) {
      root.render(null);
      return;
    }
    root.render(html`<${ProductShell} key=${id} id=${id} />`);
  }

  window.ProductDetails = { render, getActiveId: parseId };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render);
  } else {
    render();
  }
})();
