/**
 * HomePage — React landing page for Obama Store.
 *
 * Uses React 18 + ReactDOM 18 (UMD builds) plus htm (tagged-template JSX),
 * loaded via CDN with no build step. Mounted into #homeMount inside the
 * `home` route section. Reuses store.js helpers for cart / wishlist.
 */
(function () {
  'use strict';

  if (!window.React || !window.ReactDOM || !window.htm) {
    console.warn('React (or htm) not loaded — homepage fallback content stays visible.');
    return;
  }

  const { useState } = React;
  const html = (window.MotionHtm || htm.bind)(React.createElement);

  const RecSection = (window.RecommendUI && window.RecommendUI.RecSection) ? window.RecommendUI.RecSection : null;
  const Rec = RecSection || function RecSlot() { return null; };

  /* ------------------------------------------------------------------
     Catalog data
     ------------------------------------------------------------------ */

  const categories = [
    { name: 'Cars', icon: '🚗', blurb: 'Sedans, SUVs & more', slug: 'cars' },
    { name: 'Electronics', icon: '💻', blurb: 'Laptops & gadgets', slug: 'electronics' },
    { name: 'Mobile', icon: '📱', blurb: 'Phones & tablets', slug: 'mobile' },
    { name: 'Wearables', icon: '⌚', blurb: 'Smartwatches & bands', slug: 'wearables' },
    { name: 'Fashion', icon: '👕', blurb: 'Apparel & style', slug: 'fashion' },
    { name: 'Accessories', icon: '🎧', blurb: 'Headphones & extras', slug: 'accessories' }
  ];

  const testimonials = [
    {
      quote: 'The car recommendation engine matched me with a Corolla that fit my budget perfectly. Fast delivery and great service.',
      name: 'Abel Tesfaye',
      role: 'Bought a Toyota Corolla',
      initials: 'AT'
    },
    {
      quote: 'Ordered a MacBook on Monday and it arrived in two days. Secure payment with Telebirr made everything easy.',
      name: 'Hanna Girma',
      role: 'Regular shopper',
      initials: 'HG'
    },
    {
      quote: 'Professional storefront and friendly support. My smartwatch was exactly as described — premium quality.',
      name: 'Dawit Mekonnen',
      role: 'Smartwatch buyer',
      initials: 'DM'
    }
  ];

  const features = [
    { icon: '🚚', title: 'Fast delivery', blurb: 'Inside Addis Ababa and nearby areas.' },
    { icon: '💳', title: 'Secure payment', blurb: 'Telebirr & CBE Pay accepted.' },
    { icon: '🎧', title: '24/7 support', blurb: 'We reply fast on Telegram & email.' },
    { icon: '↩️', title: 'Easy returns', blurb: 'Simple returns through our contact page.' }
  ];

  /* ------------------------------------------------------------------
     Reusable components
     ------------------------------------------------------------------ */

  const REVEAL_STARTS = {
    up: { opacity: 0, y: 26 },
    down: { opacity: 0, y: -26 },
    left: { opacity: 0, x: -34 },
    right: { opacity: 0, x: 34 }
  };

  function Reveal({ children, className = '', delay = 0, from = 'up' }) {
    const start = REVEAL_STARTS[from] || REVEAL_STARTS.up;
    return html`
      <motion.div
        className=${className}
        initial=${start}
        whileInView=${{ opacity: 1, x: 0, y: 0 }}
        viewport=${{ once: true, amount: 0.18 }}
        transition=${{ duration: 0.5, delay: delay / 1000, ease: 'easeOut' }}
      >${children}</motion.div>
    `;
  }

  function SectionHeading({ eyebrow, title, link, linkLabel }) {
    return html`
      <div className="home-section-heading">
        <div>
          <p className="eyebrow">${eyebrow}</p>
          <h2>${title}</h2>
        </div>
        ${link && linkLabel ? html`<a className="button secondary" href=${link}>${linkLabel}</a>` : null}
      </div>
    `;
  }

  function HeroSection() {
    return html`
      <motion.section
        className="home-hero"
        aria-labelledby="home-title"
        initial=${{ opacity: 0 }}
        animate=${{ opacity: 1 }}
        transition=${{ duration: 0.4 }}
      >
        <motion.div
          className="home-hero-copy"
          initial=${{ opacity: 0, x: -36 }}
          animate=${{ opacity: 1, x: 0 }}
          transition=${{ duration: 0.55, delay: 0.05, ease: 'easeOut' }}
        >
          <motion.p
            className="home-hero-badge"
            initial=${{ opacity: 0, y: 14 }}
            animate=${{ opacity: 1, y: 0 }}
            transition=${{ duration: 0.45, delay: 0.15, ease: 'easeOut' }}
          >New season • Fast delivery • Smart recommendations</motion.p>
          <motion.h1
            id="home-title"
            initial=${{ opacity: 0, x: -24 }}
            animate=${{ opacity: 1, x: 0 }}
            transition=${{ duration: 0.55, delay: 0.22, ease: 'easeOut' }}
          >Shop smarter with a modern storefront.</motion.h1>
          <motion.p
            initial=${{ opacity: 0, y: 16 }}
            animate=${{ opacity: 1, y: 0 }}
            transition=${{ duration: 0.5, delay: 0.32, ease: 'easeOut' }}
          >Explore curated electronics, discover valuable car suggestions, and enjoy a smoother browsing experience designed for comfort and speed.</motion.p>
          <motion.div
            className="home-hero-actions"
            initial=${{ opacity: 0, y: 16 }}
            animate=${{ opacity: 1, y: 0 }}
            transition=${{ duration: 0.5, delay: 0.42, ease: 'easeOut' }}
          >
            <a className="button primary" href="#/products">Explore products</a>
            <a className="button secondary" href="#/recommendations">Try recommendations</a>
          </motion.div>
          <motion.div
            className="home-hero-metrics"
            initial=${{ opacity: 0, y: 16 }}
            animate=${{ opacity: 1, y: 0 }}
            transition=${{ duration: 0.5, delay: 0.52, ease: 'easeOut' }}
          >
            <div><strong>24/7</strong><span>Support</span></div>
            <div><strong>100%</strong><span>Reliable</span></div>
            <div><strong>3x</strong><span>Faster browsing</span></div>
          </motion.div>
        </motion.div>
        <motion.div
          className="home-hero-media"
          initial=${{ opacity: 0, scale: 0.94, x: 28 }}
          animate=${{ opacity: 1, scale: 1, x: 0 }}
          transition=${{ duration: 0.6, delay: 0.2, ease: 'easeOut' }}
        >
          <img src="home1.avif" alt="Aerial view of Merkato, Addis Ababa" />
          <div className="home-hero-card">
            <p>Best seller</p>
            <h3>Smart devices that feel premium</h3>
            <span>From laptops to smart watches — curated picks for daily life.</span>
          </div>
        </motion.div>
      </motion.section>
    `;
  }

  function FeaturesBar() {
    return html`
      <section className="home-features" aria-label="Store benefits">
        ${features.map((feature, index) => html`
          <motion.div
            className="home-feature"
            initial=${{ opacity: 0, y: 18 }}
            whileInView=${{ opacity: 1, y: 0 }}
            viewport=${{ once: true, amount: 0.4 }}
            transition=${{ duration: 0.4, delay: index * 0.07, ease: 'easeOut' }}
          >
            <span className="home-feature-icon" aria-hidden="true">${feature.icon}</span>
            <div>
              <strong>${feature.title}</strong>
              <span>${feature.blurb}</span>
            </div>
          </motion.div>
        `)}
      </section>
    `;
  }

  function FeaturedCategories() {
    return html`
      <${Reveal}>
        <section className="home-categories section-card" aria-labelledby="home-categories-title">
          <${SectionHeading} eyebrow="Shop by category" title="What are you looking for?" link="#/categories" linkLabel="View all categories" />
          <div className="category-grid home-category-grid">
            ${categories.map((cat, index) => html`
              <motion.a
                className="category-card"
                href=${`#/products?category=${cat.slug}`}
                initial=${{ opacity: 0, y: 24 }}
                whileInView=${{ opacity: 1, y: 0 }}
                viewport=${{ once: true, amount: 0.2 }}
                transition=${{ duration: 0.45, delay: index * 0.06, ease: 'easeOut' }}
                whileHover=${{ y: -4 }}
                whileTap=${{ scale: 0.98 }}
              >
                <span className="category-icon" aria-hidden="true">${cat.icon}</span>
                <strong>${cat.name}</strong>
                <span>${cat.blurb}</span>
              </motion.a>
            `)}
          </div>
        </section>
      </${Reveal}>
    `;
  }

  function OfferSection() {
    const [copied, setCopied] = useState(false);
    const code = 'OBAMA15';

    const copyCode = () => {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }).catch(() => setCopied(true));
      } else {
        setCopied(true);
      }
    };

    return html`
      <${Reveal}>
        <section className="home-offers" aria-labelledby="home-offers-title">
          <div className="home-offer-card home-offer-primary">
            <p className="eyebrow">Limited time offer</p>
            <h2 id="home-offers-title">Save up to 30% on electronics</h2>
            <p>Season deals on laptops, phones and wearables. Apply the code at checkout.</p>
            <div className="home-offer-code">
              <code>${code}</code>
              <button type="button" className="button secondary" onClick=${copyCode}>${copied ? 'Copied!' : 'Copy code'}</button>
            </div>
            <a className="button primary" href="#/products?category=electronics">Shop the sale</a>
          </div>
          <div className="home-offer-card home-offer-secondary">
            <p className="eyebrow">Trade-in</p>
            <h2>Old phone? Turn it into cash</h2>
            <p>Get instant value for your used device and upgrade to a new one.</p>
            <a className="button secondary" href="#/products?category=mobile">Trade in now</a>
          </div>
          <div className="home-offer-card home-offer-secondary">
            <p className="eyebrow">Car finder</p>
            <h2>Let AI pick your next car</h2>
            <p>Budget, fuel, transmission — our engine recommends the best matches.</p>
            <a className="button secondary" href="#/recommendations">Get recommendations</a>
          </div>
        </section>
      </${Reveal}>
    `;
  }

  function Testimonials() {
    return html`
      <${Reveal}>
        <section className="home-testimonials section-card" aria-labelledby="home-testimonials-title">
          <${SectionHeading} eyebrow="Customer stories" title="Trusted by shoppers in Addis Ababa" />
          <div className="home-testimonial-grid">
            ${testimonials.map((item, index) => html`
              <motion.figure
                className="home-testimonial"
                initial=${{ opacity: 0, y: 24 }}
                whileInView=${{ opacity: 1, y: 0 }}
                viewport=${{ once: true, amount: 0.25 }}
                transition=${{ duration: 0.5, delay: index * 0.1, ease: 'easeOut' }}
              >
                <blockquote>“${item.quote}”</blockquote>
                <figcaption>
                  <span className="home-testimonial-avatar" aria-hidden="true">${item.initials}</span>
                  <div>
                    <strong>${item.name}</strong>
                    <span>${item.role}</span>
                  </div>
                </figcaption>
              </motion.figure>
            `)}
          </div>
        </section>
      </${Reveal}>
    `;
  }

  function NewsletterSection() {
    const [email, setEmail] = useState('');
    const [status, setStatus] = useState('idle');

    const onSubmit = event => {
      event.preventDefault();
      const value = email.trim();
      if (!value || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
        setStatus('error');
        return;
      }
      setStatus('success');
      setEmail('');
    };

    return html`
      <section className="home-newsletter" aria-labelledby="home-newsletter-title">
        <div>
          <h2 id="home-newsletter-title">Get the best deals first</h2>
          <p>Join our newsletter for new arrivals, exclusive offers and car price drops.</p>
        </div>
        <form className="home-newsletter-form" onSubmit=${onSubmit} noValidate>
          <label className="sr-only" htmlFor="homeNewsletterEmail">Email address</label>
          <input type="email" id="homeNewsletterEmail" placeholder="you@example.com" value=${email} onChange=${event => setEmail(event.target.value)} aria-invalid=${status === 'error' ? 'true' : 'false'} />
          <button type="submit" className="button primary">Subscribe</button>
        </form>
        <p className="home-newsletter-status" role="status" aria-live="polite">
          ${status === 'success' ? 'Thanks! You are on the list.' : status === 'error' ? 'Please enter a valid email address.' : ''}
        </p>
      </section>
    `;
  }

  function HomePage() {
    return html`
      <motionconfig reducedMotion="user">
        <div className="home-page">
          <${HeroSection} />
          <${FeaturesBar} />
          <${FeaturedCategories} />
          <${Rec} slot="recommended" />
          <${OfferSection} />
          <${Rec} slot="trending" />
          <${Rec} slot="best-sellers" />
          <${Rec} slot="new-arrivals" />
          <${Testimonials} />
          <${NewsletterSection} />
        </div>
      </motionconfig>
    `;
  }

  /* ------------------------------------------------------------------
     Mount
     ------------------------------------------------------------------ */

  function mountHome() {
    const mount = document.getElementById('homeMount');
    if (!mount || mount.dataset.mounted === 'true') return;
    mount.dataset.mounted = 'true';

    try {
      const root = ReactDOM.createRoot(mount);
      root.render(html`<${HomePage} />`);
    } catch (error) {
      console.error('Homepage render failed:', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountHome);
  } else {
    mountHome();
  }
})();
