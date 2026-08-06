/**
 * AppRouter — lightweight hash-based router.
 *
 * Each navigation item maps to its own route (e.g. #/products, #/categories).
 * Routes are declared below; every page is a <section data-page="..."> in
 * index.html. The router toggles visibility, highlights the active nav link,
 * updates the document title, applies query params, and scrolls to top —
 * instead of the old "anchor link scrolls to a section" behaviour.
 */
(function () {
  'use strict';

  const ROUTES = {
    home: { label: 'Home' },
    products: { label: 'Products' },
    product: { label: 'Product' },
    categories: { label: 'Categories' },
    about: { label: 'About' },
    contact: { label: 'Contact' },
    cart: { label: 'Cart' },
    wishlist: { label: 'Wishlist' },
    profile: { label: 'My Account' },
    admin: { label: 'Admin Dashboard' },
    recommendations: { label: 'Car Recommender' },
    kb: { label:'Knowledge Base' }
  };

  function parseLocation() {
    const raw = window.location.hash.replace(/^#/, '').trim();
    const [pathPart, queryPart] = raw.split('?');
    const path = pathPart.replace(/^\/+/, '').replace(/\/+$/, '');
    const params = new URLSearchParams(queryPart || '');
    const name = Object.prototype.hasOwnProperty.call(ROUTES, path) ? path : 'home';
    return { name, params };
  }

  function buildHash(path, params) {
    let hash = `#/${path}`;
    if (params) {
      const search = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          search.set(key, value);
        }
      });
      const query = search.toString();
      if (query) hash += `?${query}`;
    }
    return hash;
  }

  function navigate(path, params) {
    const hash = buildHash(path, params);
    if (window.location.hash === hash) {
      render();
    } else {
      window.location.hash = hash;
    }
  }

  function applyParams(name, params) {
    if (name !== 'products') return;
    if (typeof window.filterProducts !== 'function') return;

    const categoryFilter = document.getElementById('productCategoryFilter');
    const searchInput = document.getElementById('searchInput');
    let changed = false;

    if (params.has('category') && categoryFilter) {
      categoryFilter.value = params.get('category');
      changed = true;
    }
    if (params.has('search') && searchInput) {
      searchInput.value = params.get('search');
      changed = true;
    }
    if (changed) {
      window.filterProducts();
    }
  }

  function render() {
    let { name, params } = parseLocation();

    if (name === 'admin') {
      const user = window.ObamaAuth && window.ObamaAuth.getUser ? window.ObamaAuth.getUser() : null;
      if (!(user && user.is_admin)) {
        name = 'home';
        params = new URLSearchParams();
        window.location.hash = '#/home';
      }
    }

    document.querySelectorAll('[data-page]').forEach((section) => {
      const active = section.dataset.page === name;
      section.hidden = !active;
      section.classList.toggle('is-active-page', active);
      section.classList.remove('page-enter');
      if (active) {
        void section.offsetWidth;
        section.classList.add('page-enter');
      }
    });

    document.querySelectorAll('[data-route]').forEach((link) => {
      link.classList.toggle('is-active', link.getAttribute('href') === `#/${name}`);
    });

    const meta = ROUTES[name] || ROUTES.home;
    document.title = `${meta.label} · Obama Store`;

    applyParams(name, params);

    if (window.ProductDetails) {
      window.ProductDetails.render();
    }

    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }

  function init() {
    window.AppRouter = { navigate, render };

    if (!window.location.hash) {
      window.history.replaceState(null, '', '#/home');
    }

    render();
    window.addEventListener('hashchange', render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
