let editingCard = null;
let cartTotal = 0;
let cartEntries = [];
let favoriteProducts = [];
let compareProducts = [];
let recentlyViewed = [];

function trackSignal(type, ...args) {
  const rec = window.Recommendations;
  if (!rec || !rec.signals) return;
  try {
    const fn = rec.signals['track' + type];
    if (typeof fn === 'function') fn(...args);
  } catch (e) { /* ignore signal errors */ }
}

function resolveProductId(title) {
  if (!window.ObamaCatalog || !title) return null;
  try {
    const match = window.ObamaCatalog.findByTitle(String(title));
    return match ? match.id : null;
  } catch (e) {
    return null;
  }
}

function matchCatalogProduct(card) {
  if (!window.ObamaCatalog || !card) return null;
  const title = card.querySelector('h3')?.textContent?.trim() || '';
  if (!title) return null;
  try {
    return window.ObamaCatalog.findByTitle(String(title)) || null;
  } catch (e) {
    return null;
  }
}

function setTheme(theme) {
  document.body.dataset.theme = theme;
  const toggleButton = document.getElementById('themeToggle');
  if (toggleButton) {
    toggleButton.textContent = theme === 'dark' ? '☀️' : '🌙';
    toggleButton.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  }
}

function initThemeToggle() {
  const savedTheme = localStorage.getItem('obama-store-theme') || 'light';
  setTheme(savedTheme);

  const toggleButton = document.getElementById('themeToggle');
  if (toggleButton) {
    toggleButton.addEventListener('click', () => {
      const nextTheme = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('obama-store-theme', nextTheme);
      setTheme(nextTheme);
    });
  }
}

const trendingCars = [
  {
    title: 'Toyota Corolla Altis 1.8 VL CVT',
    year: 2018,
    price: 1650000,
    km: 25000,
    fuel: 'Petrol',
    seller_type: 'Dealer',
    transmission: 'Automatic',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=900&q=80',
    description: 'Reliable sedan with strong resale value, modern comfort, and low mileage.',
    tags: 'sedan petrol automatic dealer first owner corolla altis',
    score: 92
  },
  {
    title: 'Hyundai Creta 1.6 VTVT S',
    year: 2015,
    price: 850000,
    km: 25000,
    fuel: 'Petrol',
    seller_type: 'Individual',
    transmission: 'Manual',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=900&q=80',
    description: 'Popular compact SUV with efficient driving, practical cargo space, and a bold design.',
    tags: 'suv petrol manual individual first owner creta',
    score: 88
  },
  {
    title: 'Ford EcoSport 1.5 Diesel Titanium',
    year: 2017,
    price: 925000,
    km: 35000,
    fuel: 'Diesel',
    seller_type: 'Individual',
    transmission: 'Manual',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=900&q=80',
    description: 'Compact SUV with diesel efficiency, premium trim, and city-friendly dimensions.',
    tags: 'suv diesel manual individual first owner ecosport',
    score: 87
  },
  {
    title: 'Honda Civic 1.8 V AT',
    year: 2019,
    price: 1470000,
    km: 34000,
    fuel: 'Petrol',
    seller_type: 'Dealer',
    transmission: 'Automatic',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1553440569-bcc63803a83d?auto=format&fit=crop&w=900&q=80',
    description: 'Executive sedan with low mileage, premium cabin quality, and strong reliability.',
    tags: 'sedan petrol automatic dealer first owner civic',
    score: 91
  },
  {
    title: 'Hyundai Elantra 1.6 GLS',
    year: 2017,
    price: 930000,
    km: 14500,
    fuel: 'Petrol',
    seller_type: 'Dealer',
    transmission: 'Manual',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1549399542-7e3f8b79c341?auto=format&fit=crop&w=900&q=80',
    description: 'Stylish midsize sedan with efficient fuel use and a refined cabin.',
    tags: 'sedan petrol manual dealer first owner elantra',
    score: 90
  },
  {
    title: 'Toyota Prado TX 2.8 Diesel',
    year: 2014,
    price: 2300000,
    km: 98000,
    fuel: 'Diesel',
    seller_type: 'Individual',
    transmission: 'Automatic',
    owner: 'Second Owner',
    imageUrl: 'https://images.unsplash.com/photo-1519642578650-7c8d1f1f57d0?auto=format&fit=crop&w=900&q=80',
    description: 'Strong SUV built for comfort and rough roads with excellent long-distance capability.',
    tags: 'suv diesel automatic individual second owner prado',
    score: 94
  },
  {
    title: 'Nissan X-Trail 2.5 CVT',
    year: 2018,
    price: 1500000,
    km: 62000,
    fuel: 'Petrol',
    seller_type: 'Dealer',
    transmission: 'Automatic',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1503736334956-4c8f8e92946d?auto=format&fit=crop&w=900&q=80',
    description: 'Balanced family SUV with ample cabin room and smooth highway performance.',
    tags: 'suv petrol automatic dealer first owner xtrail',
    score: 89
  },
  {
    title: 'Mazda CX-5 2.0 Sport',
    year: 2017,
    price: 1280000,
    km: 51000,
    fuel: 'Petrol',
    seller_type: 'Individual',
    transmission: 'Automatic',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1517524206127-48bbd363f3d7?auto=format&fit=crop&w=900&q=80',
    description: 'Premium crossover with refined ride quality, efficient engine, and modern styling.',
    tags: 'crossover petrol automatic individual first owner cx5',
    score: 88
  },
  {
    title: 'Toyota Innova 2.5 G Diesel 7 Seater',
    year: 2015,
    price: 1300000,
    km: 80000,
    fuel: 'Diesel',
    seller_type: 'Individual',
    transmission: 'Manual',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1519642578650-7c8d1f1f57d0?auto=format&fit=crop&w=900&q=80',
    description: 'Family MPV with excellent durability, strong resale demand, and spacious seating.',
    tags: 'mpv diesel manual individual first owner innova',
    score: 89
  },
  {
    title: 'Volkswagen Jetta 1.6 Trendline',
    year: 2016,
    price: 900000,
    km: 67000,
    fuel: 'Petrol',
    seller_type: 'Dealer',
    transmission: 'Manual',
    owner: 'First Owner',
    imageUrl: 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?auto=format&fit=crop&w=900&q=80',
    description: 'European sedan with a comfortable ride and a smart executive feel.',
    tags: 'sedan petrol manual dealer first owner jetta',
    score: 85
  }
];

function buildIllustratedImageDataUrl(title, subtitle, accent = '#38bdf8') {
  const label = (title || 'Featured item').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const subLabel = (subtitle || 'Reliable choice').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
          <rect width="640" height="360" rx="32" fill="#0f172a"/>
          <rect x="40" y="54" width="560" height="252" rx="28" fill="#111827"/>
          <rect x="84" y="118" width="472" height="104" rx="18" fill="#1f2937"/>
          <rect x="120" y="144" width="118" height="54" rx="16" fill="${accent}"/>
          <rect x="274" y="132" width="136" height="70" rx="18" fill="#fbbf24"/>
          <rect x="438" y="144" width="90" height="54" rx="16" fill="#f59e0b"/>
          <circle cx="170" cy="230" r="28" fill="#020617"/>
          <circle cx="470" cy="230" r="28" fill="#020617"/>
          <path d="M126 126h104" stroke="#f8fafc" stroke-width="8" stroke-linecap="round"/>
          <path d="M290 126h102" stroke="#f8fafc" stroke-width="8" stroke-linecap="round"/>
          <text x="320" y="90" text-anchor="middle" font-size="22" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif">${subLabel}</text>
          <text x="320" y="308" text-anchor="middle" font-size="28" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif">${label}</text>
      </svg>`;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function buildPlaceholderImageDataUrl(title) {
  return buildIllustratedImageDataUrl(title, 'Featured listing', '#38bdf8');
}

const CAR_PHOTO_SEDAN = 'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=900&q=80';
const CAR_PHOTO_SUV = 'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=900&q=80';
const CAR_PHOTO_PREMIUM = 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?auto=format&fit=crop&w=900&q=80';

const carImageCatalog = {
  'toyota corolla altis': CAR_PHOTO_SEDAN,
  'hyundai creta': CAR_PHOTO_SUV,
  'ford ecosport': CAR_PHOTO_SUV,
  'honda civic': CAR_PHOTO_SEDAN,
  'hyundai elantra': CAR_PHOTO_SEDAN,
  'toyota prado': CAR_PHOTO_SUV,
  'nissan x-trail': CAR_PHOTO_SUV,
  'mazda cx-5': CAR_PHOTO_SUV,
  'toyota innova': CAR_PHOTO_SUV,
  'volkswagen jetta': CAR_PHOTO_PREMIUM,
  'x1': CAR_PHOTO_SUV,
  'x3': CAR_PHOTO_SUV,
  'x5': CAR_PHOTO_SUV,
  'x7': CAR_PHOTO_SUV,
  'q5': CAR_PHOTO_SUV,
  'q7': CAR_PHOTO_SUV,
  'suv': CAR_PHOTO_SUV,
  'fortuner': CAR_PHOTO_SUV,
  'scorpio': CAR_PHOTO_SUV,
  'xuv': CAR_PHOTO_SUV,
  'thar': CAR_PHOTO_SUV,
  'compass': CAR_PHOTO_SUV,
  'pajero': CAR_PHOTO_SUV,
  'safari': CAR_PHOTO_SUV,
  'hexa': CAR_PHOTO_SUV,
  'endeavour': CAR_PHOTO_SUV,
  'innova': CAR_PHOTO_SUV,
  'crysta': CAR_PHOTO_SUV,
  'gl-class': CAR_PHOTO_SUV,
  'g-class': CAR_PHOTO_SUV,
  'gls': CAR_PHOTO_SUV,
  'gle': CAR_PHOTO_SUV,
  'range rover': CAR_PHOTO_SUV,
  'defender': CAR_PHOTO_SUV,
  'land cruiser': CAR_PHOTO_SUV,
  'land rover': CAR_PHOTO_SUV,
  'mercedes': CAR_PHOTO_PREMIUM,
  'benz': CAR_PHOTO_PREMIUM,
  'volkswagen': CAR_PHOTO_PREMIUM,
  'skoda': CAR_PHOTO_PREMIUM,
  'lexus': CAR_PHOTO_PREMIUM,
  'audi': CAR_PHOTO_SEDAN,
  'bmw': CAR_PHOTO_SUV,
  'toyota': CAR_PHOTO_SEDAN,
  'honda': CAR_PHOTO_SEDAN,
  'ford': CAR_PHOTO_SEDAN,
  'hyundai': CAR_PHOTO_SUV,
  'tata': CAR_PHOTO_SUV,
  'mahindra': CAR_PHOTO_SUV,
  'jeep': CAR_PHOTO_SUV,
  'kia': CAR_PHOTO_SUV,
  'nissan': CAR_PHOTO_SEDAN,
  'mazda': CAR_PHOTO_SEDAN,
  'chevrolet': CAR_PHOTO_SEDAN,
  'renault': CAR_PHOTO_SEDAN,
  'maruti': CAR_PHOTO_SEDAN,
  'suzuki': CAR_PHOTO_SEDAN
};

const CAR_DEFAULT_IMAGE = CAR_PHOTO_SEDAN;

function getRealCarImageUrl(title) {
  const normalized = (title || '').toLowerCase();

  for (const [key, imageUrl] of Object.entries(carImageCatalog)) {
    if (normalized.includes(key)) {
      return imageUrl;
    }
  }

  return CAR_DEFAULT_IMAGE;
}

function normalizeCarImage(car) {
  const imageUrl = getRealCarImageUrl(car.title || 'Recommended car');
  const fallbackImage = buildPlaceholderImageDataUrl(car.title || 'Recommended car');
  car.imageUrl = imageUrl;
  car.fallbackImage = fallbackImage;
  return car;
}

trendingCars.forEach(car => normalizeCarImage(car));

const carInventory = trendingCars.slice();

const TRENDING_POOL_SIZE = 40;
const TRENDING_SHOW_COUNT = 15;

function shuffleArray(array) {
  const copy = array.slice();
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    const temp = copy[i];
    copy[i] = copy[j];
    copy[j] = temp;
  }
  return copy;
}

async function fetchTrendingCars(options = {}) {
  const poolSize = options.poolSize || TRENDING_POOL_SIZE;
  try {
    const response = await fetch(`/api/trending-cars?limit=${poolSize}`);
    if (!response.ok) throw new Error(`Trending API responded ${response.status}`);

    const data = await response.json();
    if (Array.isArray(data.cars) && data.cars.length) {
      const pool = data.cars.map(car => normalizeCarImage(car));
      const picked = options.shuffle
        ? shuffleArray(pool).slice(0, TRENDING_SHOW_COUNT)
        : pool.slice(0, TRENDING_SHOW_COUNT);
      carInventory.splice(0, carInventory.length, ...picked);
      renderTrendingCars(picked);
      return true;
    }
  } catch (error) {
    console.warn('Trending API failed, falling back to local trending cars:', error);
  }

  const fallback = options.shuffle
    ? shuffleArray(trendingCars).slice(0, TRENDING_SHOW_COUNT)
    : trendingCars.slice(0, TRENDING_SHOW_COUNT);
  carInventory.splice(0, carInventory.length, ...fallback);
  renderTrendingCars(fallback);
  return false;
}

function buildCarCard(car) {
  const normalizedCar = normalizeCarImage({ ...car });
  const card = document.createElement('article');
  card.className = 'product-card recommendation-card';
  card.dataset.search = normalizedCar.tags || '';
  let hasDetails = false;
  if (window.ObamaCatalog) {
    const match = window.ObamaCatalog.findByTitle(normalizedCar.title);
    if (match) {
      card.dataset.productId = match.id;
      hasDetails = true;
    }
  }
  card.innerHTML = `
      <img src="${normalizedCar.imageUrl}" alt="${normalizedCar.title}" loading="lazy" decoding="async">
      <h3>${normalizedCar.title}</h3>
      <div class="car-meta">${normalizedCar.year} · ${normalizedCar.fuel} · ${normalizedCar.transmission} · ${Number(normalizedCar.km || 0).toLocaleString()} km</div>
      <p class="product-description">${normalizedCar.description}</p>
      <p class="price">${formatPrice(normalizedCar.price)}</p>
      ${normalizedCar.predicted_price ? `<p class="car-predicted">Predicted price: ${formatPrice(normalizedCar.predicted_price)}</p>` : ''}
      ${normalizedCar.score ? `<p class="car-score">Trending score: ${normalizedCar.score}</p>` : ''}
      <div class="product-actions">
          <button type="button" class="add-cart-btn">Add to cart</button>
          ${hasDetails ? '<button type="button" class="view-details-btn">Details</button>' : ''}
      </div>
  `;

  const imageElement = card.querySelector('img');
  if (imageElement && normalizedCar.fallbackImage) {
    imageElement.onerror = () => {
      if (imageElement.src !== normalizedCar.fallbackImage) {
        imageElement.src = normalizedCar.fallbackImage;
      }
    };
  }

  attachProductActions(card);
  return card;
}

function renderTrendingCars(cars) {
  const container = document.getElementById('trendingResults');
  if (!container) return;
  container.innerHTML = '';

  if (!cars.length) {
    container.innerHTML = '<div class="product-card"><p>No trending cars available right now.</p></div>';
    return;
  }

  cars.slice(0, TRENDING_SHOW_COUNT).forEach((car, index) => {
    const card = buildCarCard(car);
    card.classList.add('is-entering');
    card.style.animationDelay = `${Math.min(index * 55, 500)}ms`;
    container.appendChild(card);
  });
}

async function recommendCars() {
  const budget = Number(document.getElementById('budgetInput').value) || 0;
  const fuel = document.getElementById('fuelInput').value;
  const transmission = document.getElementById('transmissionInput').value;
  const kmValue = document.getElementById('kmInput').value;
  const ageValue = document.getElementById('ageInput').value;
  const km = kmValue ? Number(kmValue) : null;
  const age = ageValue ? Number(ageValue) : null;
  const results = document.getElementById('recommendationResults');

  if (results) {
    results.innerHTML = '';
    for (let index = 0; index < 3; index += 1) {
      const card = document.createElement('article');
      card.className = 'product-card skeleton-card';
      results.appendChild(card);
    }
  }

  showOwnerMessage('Loading intelligent recommendations...', '#065f46');

  try {
    const response = await fetch('/api/recommendations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        budget,
        fuel,
        transmission,
        km,
        age
      })
    });

    if (!response.ok) {
      throw new Error(`Recommendation API responded ${response.status}`);
    }

    const data = await response.json();
    const cars = Array.isArray(data.cars) ? data.cars : [];
    renderRecommendedCars(cars);
    showOwnerMessage('Personalized car recommendations updated.', '#065f46');
  } catch (error) {
    console.warn('Recommendation API failed, falling back to local scoring:', error);
    showOwnerMessage('Backend unavailable. Showing local recommendations instead.', 'orange');
    const fallback = scoreLocalCars(budget, fuel, transmission, km, age);
    renderRecommendedCars(fallback);
  }
}

function scoreLocalCars(budget, fuel, transmission, km, age) {
  const currentYear = new Date().getFullYear();

  const scoredCars = carInventory.map(car => {
    let score = 0;
    const carAge = currentYear - car.year;

    if (budget > 0) {
      const budgetGap = Math.abs(car.price - budget) / Math.max(budget, 1);
      score += Math.max(0, 30 - budgetGap * 30);
    } else {
      score += 10;
    }

    if (fuel === 'any' || car.fuel === fuel) score += 25;
    if (transmission === 'any' || car.transmission === transmission) score += 20;
    if (km === null || car.km <= km) score += 15;
    if (age === null || carAge <= age) score += 10;
    if (car.owner === 'First Owner') score += 10;

    return { ...car, score: Math.round(score) };
  });

  scoredCars.sort((a, b) => b.score - a.score || a.price - b.price);
  return scoredCars.slice(0, 6);
}

function renderRecommendedCars(cars) {
  const results = document.getElementById('recommendationResults');
  if (!results) return;
  results.innerHTML = '';

  const normalizedCars = (cars || []).map(car => normalizeCarImage({ ...car }));

  if (!normalizedCars.length) {
    results.innerHTML = '<div class="product-card"><p>No matching cars found. Try changing your preferences.</p></div>';
    return;
  }

  normalizedCars.forEach(car => results.appendChild(buildCarCard(car)));
}

function formatPrice(value) {
  return 'ETB ' + value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function initCarRecommendation() {
  const recommendBtn = document.getElementById('recommendBtn');
  const refreshTrendingBtn = document.getElementById('refreshTrendingBtn');

  if (recommendBtn) {
    recommendBtn.addEventListener('click', () => {
      recommendCars();
    });
  }

  if (refreshTrendingBtn) {
    const refreshOriginalLabel = refreshTrendingBtn.textContent.trim() || 'Refresh Trending';

    refreshTrendingBtn.addEventListener('click', async () => {
      refreshTrendingBtn.disabled = true;
      refreshTrendingBtn.classList.add('is-loading');
      refreshTrendingBtn.textContent = 'Refreshing';

      const container = document.getElementById('trendingResults');
      if (container) {
        container.querySelectorAll('.product-card').forEach(card => card.classList.add('is-leaving'));
      }

      try {
        await new Promise(resolve => setTimeout(resolve, 220));
        await fetchTrendingCars({ shuffle: true });
        refreshTrendingBtn.classList.remove('is-loading');
        refreshTrendingBtn.classList.add('is-success');
        refreshTrendingBtn.textContent = 'Refreshed ✓';
        showRecToast('Trending refreshed ✓');
      } catch (error) {
        console.warn('Trending refresh failed:', error);
        refreshTrendingBtn.classList.remove('is-loading');
        refreshTrendingBtn.textContent = refreshOriginalLabel;
        showRecToast('Could not refresh. Try again.');
      } finally {
        setTimeout(() => {
          refreshTrendingBtn.classList.remove('is-success');
          refreshTrendingBtn.disabled = false;
          refreshTrendingBtn.textContent = refreshOriginalLabel;
        }, 1400);
      }
    });
  }

  fetchTrendingCars();
}

function filterProducts() {
  const query = document.getElementById('searchInput')?.value.toLowerCase() || '';
  const category = document.getElementById('productCategoryFilter')?.value || 'all';
  const sortValue = document.getElementById('productSortSelect')?.value || 'featured';
  const productsPage = document.getElementById('productsPage');
  const products = productsPage ? Array.from(productsPage.querySelectorAll('.product-card')) : [];
  const summary = document.getElementById('productResultsSummary');

  if (query) trackSignal('Search', query);

  let visibleProducts = products.filter(product => {
    const text = (product.dataset.search || '').toLowerCase();
    const matchesQuery = text.includes(query) || query === '';
    const matchesCategory = category === 'all' || product.dataset.category === category;
    return matchesQuery && matchesCategory;
  });

  visibleProducts.sort((a, b) => {
    if (sortValue === 'price-asc') return Number(a.dataset.price || 0) - Number(b.dataset.price || 0);
    if (sortValue === 'price-desc') return Number(b.dataset.price || 0) - Number(a.dataset.price || 0);
    if (sortValue === 'name') return (a.dataset.title || '').localeCompare(b.dataset.title || '');
    return 0;
  });

  products.forEach(product => {
    product.style.display = 'none';
  });

  visibleProducts.forEach(product => {
    product.style.display = 'flex';
  });

  if (summary) {
    summary.textContent = visibleProducts.length ? `Showing ${visibleProducts.length} matching product${visibleProducts.length === 1 ? '' : 's'}.` : 'No products match your current search.';
  }
}

function updateCartCount(change = 1) {
  const cartCount = document.getElementById('cartCount');
  if (!cartCount) return;
  cartTotal += change;
  cartCount.textContent = cartTotal;
}

function parsePriceValue(priceText) {
  if (!priceText) return 0;
  const cleaned = priceText.replace(/[^0-9.]/g, '');
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatMoney(value, priceText = '') {
  const numericValue = Number(value || 0);
  if (priceText.includes('$')) {
    return `$${numericValue.toFixed(2)}`;
  }
  return `ETB ${numericValue.toLocaleString()}`;
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[char]);
}

function buildCartItemsHtml() {
  if (!cartEntries.length) {
    return '<div class="cart-empty">Your cart is empty.</div>';
  }

  return cartEntries.map(item => `
    <div class="cart-item">
        <div>
            <strong>${escapeHtml(item.title)}</strong>
            <div>${item.quantity} × ${formatMoney(item.priceValue, item.priceText)}</div>
        </div>
        <div>${formatMoney(item.priceValue * item.quantity, item.priceText)}</div>
    </div>
  `).join('');
}

function renderCart() {
  const drawerItems = document.getElementById('cartItems');
  const drawerTotal = document.getElementById('cartTotalValue');
  const pageItems = document.getElementById('cartPageItems');
  const pageTotal = document.getElementById('cartPageTotal');
  const checkoutBtn = document.getElementById('checkoutBtn');
  const clearCartBtn = document.getElementById('clearCartBtn');
  const pageCheckout = document.getElementById('cartPageCheckout');
  const pageClear = document.getElementById('cartPageClear');

  if (!drawerItems && !pageItems) return;

  const itemsHtml = buildCartItemsHtml();
  if (drawerItems) drawerItems.innerHTML = itemsHtml;
  if (pageItems) pageItems.innerHTML = itemsHtml;

  let totalText = 'ETB 0';
  if (cartEntries.length) {
    const subtotal = cartEntries.reduce((sum, item) => sum + (item.priceValue * item.quantity), 0);
    totalText = formatMoney(subtotal, cartEntries[0].priceText);
  }

  if (drawerTotal) drawerTotal.textContent = totalText;
  if (pageTotal) pageTotal.textContent = totalText;

  const empty = !cartEntries.length;
  if (checkoutBtn) checkoutBtn.disabled = empty;
  if (clearCartBtn) clearCartBtn.disabled = empty;
  if (pageCheckout) pageCheckout.disabled = empty;
  if (pageClear) pageClear.disabled = empty;
}

function openCart() {
  const drawer = document.getElementById('cartDrawer');
  const backdrop = document.getElementById('cartBackdrop');
  if (!drawer || !backdrop) return;
  drawer.classList.add('is-open');
  drawer.setAttribute('aria-hidden', 'false');
  backdrop.hidden = false;
}

function closeCart() {
  const drawer = document.getElementById('cartDrawer');
  const backdrop = document.getElementById('cartBackdrop');
  if (!drawer || !backdrop) return;
  drawer.classList.remove('is-open');
  drawer.setAttribute('aria-hidden', 'true');
  backdrop.hidden = true;
}

function addItemToCart(title, priceText, quantity = 1) {
  const count = Math.max(1, Number(quantity) || 1);
  const priceValue = parsePriceValue(priceText);
  const existingItem = cartEntries.find(item => item.title === title);

  if (existingItem) {
    existingItem.quantity += count;
  } else {
    cartEntries.push({ title, priceText, priceValue, quantity: count });
  }

  saveCart();
  updateCartCount(count);
  renderCart();
  openCart();
  trackSignal('Cart', resolveProductId(title), count);
  showOwnerMessage(`Added ${title} to cart.`, '#065f46');
}

function checkoutCart() {
  if (!cartEntries.length) return;
  const purchasedIds = cartEntries.map(entry => resolveProductId(entry.title)).filter(Boolean);
  if (purchasedIds.length) trackSignal('Purchase', purchasedIds);
  showOwnerMessage('Checkout complete. Your order is ready for confirmation.', '#065f46');
  cartEntries = [];
  cartTotal = 0;
  saveCart();
  updateCartCount(0);
  renderCart();
  closeCart();
}

function clearCart() {
  cartEntries = [];
  cartTotal = 0;
  saveCart();
  updateCartCount(0);
  renderCart();
  showOwnerMessage('Cart cleared.', 'orange');
}

function showOwnerMessage(message, color = 'green') {
  const ownerMessage = document.getElementById('ownerMessage');
  if (!ownerMessage) return;
  ownerMessage.textContent = message;
  ownerMessage.style.color = color;
}

function showRecToast(message) {
  let toast = document.getElementById('recToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'recToast';
    toast.className = 'rec-toast';
    toast.setAttribute('role', 'status');
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.remove('is-visible');
  void toast.offsetWidth;
  toast.classList.add('is-visible');
  clearTimeout(showRecToast._timer);
  showRecToast._timer = setTimeout(() => toast.classList.remove('is-visible'), 2600);
}

function buildCardIdentifier(card, fallbackTitle = '') {
  const explicitId = card.dataset.productId;
  if (explicitId) return explicitId;

  const title = (card.querySelector('h3')?.textContent || fallbackTitle || '').trim();
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  const category = (card.dataset.category || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  const generatedId = `${slug || 'product'}${category ? `-${category}` : ''}`;
  card.dataset.productId = generatedId;
  return generatedId;
}

function ensureProductActionButtons(card) {
  const actions = card.querySelector('.product-actions');
  if (!actions) return;

  if (actions.querySelector('.favorite-btn') && actions.querySelector('.compare-btn')) return;

  const favoriteButton = document.createElement('button');
  favoriteButton.type = 'button';
  favoriteButton.className = 'favorite-btn';
  favoriteButton.textContent = '♡ Favorite';

  const compareButton = document.createElement('button');
  compareButton.type = 'button';
  compareButton.className = 'compare-btn';
  compareButton.textContent = '⚖ Compare';

  actions.appendChild(favoriteButton);
  actions.appendChild(compareButton);
}

function syncCardActionButtons() {
  document.querySelectorAll('.product-card').forEach(card => {
    const productId = buildCardIdentifier(card);
    const favoriteButton = card.querySelector('.favorite-btn');
    const compareButton = card.querySelector('.compare-btn');

    if (favoriteButton) {
      const isFavorite = favoriteProducts.some(item => item.id === productId);
      favoriteButton.classList.toggle('is-active', isFavorite);
      favoriteButton.textContent = isFavorite ? '♥ Favorite' : '♡ Favorite';
      favoriteButton.setAttribute('aria-pressed', String(isFavorite));
    }

    if (compareButton) {
      const isCompared = compareProducts.some(item => item.id === productId);
      compareButton.classList.toggle('is-active', isCompared);
      compareButton.textContent = isCompared ? '✓ Compared' : '⚖ Compare';
    }
  });
}

function updateWishlistCount() {
  const badge = document.getElementById('wishlistCount');
  const menuBadge = document.getElementById('menuWishlistCount');
  if (badge) badge.textContent = String(favoriteProducts.length);
  if (menuBadge) menuBadge.textContent = `${favoriteProducts.length} saved`;
}

function isFavoriteProduct(id) {
  return favoriteProducts.some(item => item.id === id);
}

function toggleFavoriteProduct(item) {
  const existingIndex = favoriteProducts.findIndex(f => f.id === item.id);

  if (existingIndex >= 0) {
    favoriteProducts.splice(existingIndex, 1);
    showOwnerMessage(`Removed ${item.title} from favorites.`, 'orange');
  } else {
    favoriteProducts.push(item);
    trackSignal('Wishlist', item.id);
    showOwnerMessage(`Added ${item.title} to favorites.`, '#8b5cf6');
  }

  renderFavoritesPanel();
  renderWishlistPage();
  updateWishlistCount();
  saveFavorites();
  return !(existingIndex >= 0);
}

function isComparedProduct(id) {
  return compareProducts.some(item => item.id === id);
}

function toggleCompareProduct(item) {
  const existingIndex = compareProducts.findIndex(f => f.id === item.id);
  let added = true;

  if (existingIndex >= 0) {
    compareProducts.splice(existingIndex, 1);
    added = false;
    showOwnerMessage(`Removed ${item.title} from compare list.`, 'orange');
  } else if (compareProducts.length >= 3) {
    showOwnerMessage('You can compare up to 3 products at once.', 'orange');
    return false;
  } else {
    compareProducts.push(item);
    showOwnerMessage(`Added ${item.title} to compare list.`, '#0f766e');
  }

  renderCompareSummary();
  return added;
}

function loadRecentlyViewed() {
  try {
    recentlyViewed = JSON.parse(localStorage.getItem('obama-store-recent') || '[]');
  } catch (error) {
    recentlyViewed = [];
  }
}

function loadPersistedState() {
  try {
    cartEntries = JSON.parse(localStorage.getItem('obama-store-cart') || '[]');
  } catch (error) {
    cartEntries = [];
  }
  try {
    favoriteProducts = JSON.parse(localStorage.getItem('obama-store-favorites') || '[]');
  } catch (error) {
    favoriteProducts = [];
  }
}

function saveCart() {
  try {
    localStorage.setItem('obama-store-cart', JSON.stringify(cartEntries));
  } catch (error) {
    /* storage may be unavailable — ignore */
  }
}

function saveFavorites() {
  try {
    localStorage.setItem('obama-store-favorites', JSON.stringify(favoriteProducts));
  } catch (error) {
    /* storage may be unavailable — ignore */
  }
}

function trackRecentlyViewed(product) {
  const snapshot = {
    id: product.id,
    title: product.title,
    image: product.imageUrl || product.image || '',
    priceText: product.priceText || '',
    description: product.shortDescription || product.description || ''
  };
  recentlyViewed = recentlyViewed.filter(item => item.id !== snapshot.id);
  recentlyViewed.unshift(snapshot);
  recentlyViewed = recentlyViewed.slice(0, 8);
  try {
    localStorage.setItem('obama-store-recent', JSON.stringify(recentlyViewed));
  } catch (error) {
    /* storage may be unavailable — ignore */
  }
}

function getRecentlyViewed() {
  return recentlyViewed;
}

window.StoreHelpers = {
  isFavoriteProduct,
  toggleFavoriteProduct,
  isComparedProduct,
  toggleCompareProduct,
  trackRecentlyViewed,
  getRecentlyViewed,
  addItemToCart,
  openCart,
  closeCart
};

function renderFavoritesPanel() {
  const favoritesPanel = document.getElementById('favoritesPanel');
  if (!favoritesPanel) return;

  if (!favoriteProducts.length) {
    favoritesPanel.innerHTML = '<p class="panel-empty">No favorites yet. Tap a heart to save a product.</p>';
    syncCardActionButtons();
    return;
  }

  favoritesPanel.innerHTML = favoriteProducts.map(item => `
    <div class="favorite-pill">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.priceText)}</span>
    </div>
  `).join('');
  updateWishlistCount();
  syncCardActionButtons();
}

function renderWishlistPage() {
  const grid = document.getElementById('wishlistPageGrid');
  const emptyState = document.getElementById('wishlistEmpty');
  if (!grid) return;

  if (!favoriteProducts.length) {
    grid.innerHTML = '';
    if (emptyState) emptyState.hidden = false;
    updateWishlistCount();
    return;
  }

  if (emptyState) emptyState.hidden = true;

  grid.innerHTML = favoriteProducts.map(item => `
    <article class="wishlist-card">
        <img src="${escapeHtml(item.image || '')}" alt="${escapeHtml(item.title)}" loading="lazy" decoding="async">
        <div class="wishlist-card-body">
            <h3>${escapeHtml(item.title)}</h3>
            <p class="product-description">${escapeHtml(item.description)}</p>
            <p class="price">${escapeHtml(item.priceText)}</p>
            <div class="product-actions">
                <button type="button" class="add-cart-btn" data-wishlist-add="${escapeHtml(item.id)}">Add to cart</button>
                <button type="button" class="remove-btn" data-wishlist-remove="${escapeHtml(item.id)}">Remove</button>
            </div>
        </div>
    </article>
  `).join('');

  grid.querySelectorAll('[data-wishlist-remove]').forEach(button => {
    button.addEventListener('click', () => {
      const id = button.dataset.wishlistRemove;
      favoriteProducts = favoriteProducts.filter(item => item.id !== id);
      saveFavorites();
      renderFavoritesPanel();
      renderWishlistPage();
    });
  });

  grid.querySelectorAll('[data-wishlist-add]').forEach(button => {
    button.addEventListener('click', () => {
      const item = favoriteProducts.find(favorite => favorite.id === button.dataset.wishlistAdd);
      if (item) addItemToCart(item.title, item.priceText);
    });
  });

  updateWishlistCount();
  observeRevealCards(grid);
}

function renderCompareSummary() {
  const compareSummary = document.getElementById('compareSummary');
  if (!compareSummary) return;

  if (!compareProducts.length) {
    compareSummary.textContent = 'Select up to 3 products to compare.';
    syncCardActionButtons();
    return;
  }

  const compareText = compareProducts.map(item => item.title).join(' · ');
  compareSummary.innerHTML = `<span>${compareProducts.length}/3 selected: ${escapeHtml(compareText)}</span>`;
  if (compareProducts.length >= 2) {
    const compareButton = document.createElement('button');
    compareButton.type = 'button';
    compareButton.className = 'compare-summary-btn';
    compareButton.textContent = 'Open compare';
    compareButton.addEventListener('click', openCompareModal);
    compareSummary.appendChild(compareButton);
  }
  syncCardActionButtons();
}

function openCompareModal() {
  const modal = document.getElementById('compareModal');
  const body = document.getElementById('compareModalBody');
  if (!modal || !body) return;

  if (compareProducts.length < 2) {
    showOwnerMessage('Select at least two products to compare.', 'orange');
    return;
  }

  body.innerHTML = `
    <div class="compare-table-wrap">
        <table class="compare-table">
            <thead>
                <tr>
                    <th>Feature</th>
                    ${compareProducts.map(item => `<th>${escapeHtml(item.title)}</th>`).join('')}
                </tr>
            </thead>
            <tbody>
                <tr><td>Price</td>${compareProducts.map(item => `<td>${escapeHtml(item.priceText)}</td>`).join('')}</tr>
                <tr><td>Category</td>${compareProducts.map(item => `<td>${escapeHtml(item.category)}</td>`).join('')}</tr>
                <tr><td>Details</td>${compareProducts.map(item => `<td>${escapeHtml(item.description)}</td>`).join('')}</tr>
            </tbody>
        </table>
    </div>
  `;

  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
}

function openProductModal(card) {
  const modal = document.getElementById('productDetailModal');
  if (!modal) return;

  const image = card.querySelector('img')?.getAttribute('src') || '';
  const title = card.querySelector('h3')?.textContent || 'Product';
  const description = card.querySelector('.product-description')?.textContent || '';
  const price = card.querySelector('.price')?.textContent || '';
  const tags = card.dataset.search || '';
  const category = (card.dataset.category || 'Featured').replace(/\b\w/g, char => char.toUpperCase());

  document.getElementById('modalImage').src = image;
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalDescription').textContent = description;
  document.getElementById('modalPrice').textContent = price;
  document.getElementById('modalTags').textContent = tags;
  document.getElementById('modalCategory').textContent = category;
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeProductModal() {
  closeModal('productDetailModal');
}

function openProductDetails(card) {
  const catalogMatch = matchCatalogProduct(card);
  if (catalogMatch && window.AppRouter) {
    window.AppRouter.navigate('product', { id: catalogMatch.id });
    return;
  }
  if (card.dataset.productId && window.AppRouter) {
    window.AppRouter.navigate('product', { id: card.dataset.productId });
    return;
  }
  openProductModal(card);
}

function attachProductActions(card) {
  if (card.__actionsBound) return;
  card.__actionsBound = true;
  ensureProductActionButtons(card);

  const addBtn = card.querySelector('.add-cart-btn');
  const editBtn = card.querySelector('.edit-product-btn');
  const removeBtn = card.querySelector('.remove-product-btn');
  const detailsBtn = card.querySelector('.view-details-btn');
  const favoriteBtn = card.querySelector('.favorite-btn');
  const compareBtn = card.querySelector('.compare-btn');

  if (addBtn) {
    addBtn.addEventListener('click', () => {
      const title = card.querySelector('h3')?.textContent?.trim() || 'Product';
      const priceText = card.querySelector('.price')?.textContent || 'ETB 0';
      addItemToCart(title, priceText);
    });
  }

  if (editBtn) {
    editBtn.addEventListener('click', () => startEditProduct(card));
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', () => {
      card.remove();
      showOwnerMessage('Product removed.', 'orange');
      filterProducts();
    });
  }

  if (detailsBtn) {
    detailsBtn.addEventListener('click', () => openProductDetails(card));
  }

  const imageWrap = card.querySelector('.product-image-wrap');
  if (imageWrap) {
    imageWrap.addEventListener('click', event => {
      if (event.target.closest('button')) return;
      openProductDetails(card);
    });
  }

  if (favoriteBtn) {
    favoriteBtn.addEventListener('click', () => {
      const productId = buildCardIdentifier(card);
      const title = card.querySelector('h3')?.textContent?.trim() || 'Product';
      const priceText = card.querySelector('.price')?.textContent || 'ETB 0';
      const description = card.querySelector('.product-description')?.textContent || '';
      const image = card.querySelector('img')?.getAttribute('src') || '';
      const existingIndex = favoriteProducts.findIndex(item => item.id === productId);

      if (existingIndex >= 0) {
        favoriteProducts.splice(existingIndex, 1);
        showOwnerMessage(`Removed ${title} from favorites.`, 'orange');
      } else {
        favoriteProducts.push({ id: productId, title, priceText, description, image });
        showOwnerMessage(`Added ${title} to favorites.`, '#8b5cf6');
      }

      saveFavorites();
      renderFavoritesPanel();
      renderWishlistPage();
    });
  }

  if (compareBtn) {
    compareBtn.addEventListener('click', () => {
      const productId = buildCardIdentifier(card);
      const title = card.querySelector('h3')?.textContent?.trim() || 'Product';
      const priceText = card.querySelector('.price')?.textContent || 'ETB 0';
      const description = card.querySelector('.product-description')?.textContent || '';
      const category = (card.dataset.category || 'Featured').replace(/\b\w/g, char => char.toUpperCase());
      const existingIndex = compareProducts.findIndex(item => item.id === productId);

      if (existingIndex >= 0) {
        compareProducts.splice(existingIndex, 1);
        showOwnerMessage(`Removed ${title} from compare list.`, 'orange');
      } else if (compareProducts.length >= 3) {
        showOwnerMessage('You can compare up to 3 products at once.', 'orange');
        return;
      } else {
        compareProducts.push({ id: productId, title, priceText, description, category });
        showOwnerMessage(`Added ${title} to compare list.`, '#0f766e');
      }

      renderCompareSummary();
      if (compareProducts.length >= 2) {
        openCompareModal();
      }
    });
  }

  syncCardActionButtons();
}

function setProductCardValues(card, title, imageUrl, price, description, tags) {
  const titleElem = card.querySelector('h3');
  const imageElem = card.querySelector('img');
  const priceElem = card.querySelector('.price');
  const descElem = card.querySelector('.product-description');

  if (titleElem) titleElem.textContent = title;
  if (imageElem) {
    imageElem.src = imageUrl;
    imageElem.alt = title;
  }
  if (priceElem) priceElem.textContent = price;
  if (descElem) descElem.textContent = description;
  card.dataset.search = tags;
  buildCardIdentifier(card, title);
}

function resetOwnerForm() {
  const titleInput = document.getElementById('newTitle');
  const imageInput = document.getElementById('newImage');
  const priceInput = document.getElementById('newPrice');
  const descriptionInput = document.getElementById('newDescription');
  const tagsInput = document.getElementById('newTags');
  const productPreview = document.getElementById('productPreview');
  const submitButton = document.querySelector('#ownerForm button[type="submit"]');

  if (titleInput) titleInput.value = '';
  if (imageInput) imageInput.value = '';
  if (priceInput) priceInput.value = '';
  if (descriptionInput) descriptionInput.value = '';
  if (tagsInput) tagsInput.value = '';
  if (productPreview) {
    productPreview.style.display = 'none';
    productPreview.src = '';
  }
  if (submitButton) submitButton.textContent = 'Add Product';
  editingCard = null;
  showOwnerMessage('');
}

function createProductCard(title, imageUrl, price, description, tags) {
  const article = document.createElement('article');
  article.className = 'product-card';
  article.dataset.search = tags;

  article.innerHTML = `
    <img src="${imageUrl}" alt="${title}">
    <h3>${title}</h3>
    <p class="product-description">${description}</p>
    <p class="price">${price}</p>
    <div class="product-actions">
        <button type="button" class="add-cart-btn">Add to cart</button>
        <button type="button" class="view-details-btn">View details</button>
        <button type="button" class="edit-product-btn">Edit</button>
        <button type="button" class="remove-product-btn">Remove</button>
    </div>
  `;

  attachProductActions(article);
  return article;
}

function createMarketplaceCard(title, imageUrl, price, description, tags, source, link) {
  const article = document.createElement('article');
  article.className = 'product-card marketplace-card';
  article.dataset.search = `${tags} ${source.toLowerCase()}`;

  article.innerHTML = `
    <img src="${imageUrl}" alt="${title}" loading="lazy" decoding="async">
    <h3>${title}</h3>
    <p class="product-description">${description}</p>
    <p class="price">${price}</p>
    <p class="marketplace-source">Source: ${source}</p>
    <a href="${link}" target="_blank" class="marketplace-link">View on ${source}</a>
    <div class="product-actions">
        <button type="button" class="add-cart-btn">Add to cart</button>
        <button type="button" class="view-details-btn">View details</button>
        <button type="button" class="edit-product-btn">Edit</button>
        <button type="button" class="remove-product-btn">Remove</button>
    </div>
  `;

  const imageElement = article.querySelector('img');
  if (imageElement) {
    imageElement.onerror = () => {
      if (imageElement.src !== 'home1.avif') {
        imageElement.src = 'home1.avif';
      }
    };
  }

  attachProductActions(article);
  return article;
}

function sampleMarketplaceProducts() {
  return [
    {
      title: 'Toyota Corolla Altis 1.8 VL CVT',
      imageUrl: 'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=900&q=80',
      price: 'ETB 1,650,000',
      description: '2018 • 25,000 km • Petrol • Automatic • First owner',
      tags: 'toyota corolla altis sedan petrol automatic',
      source: 'Dealer',
      link: 'https://www.cars.com/'
    },
    {
      title: 'Hyundai Creta 1.6 VTVT S',
      imageUrl: 'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=900&q=80',
      price: 'ETB 850,000',
      description: '2015 • 25,000 km • Petrol • Manual • First owner',
      tags: 'hyundai creta suv petrol manual',
      source: 'Private Seller',
      link: 'https://www.cars.com/'
    },
    {
      title: 'Honda Civic 1.8 V AT',
      imageUrl: 'https://images.unsplash.com/photo-1553440569-bcc63803a83d?auto=format&fit=crop&w=900&q=80',
      price: 'ETB 1,470,000',
      description: '2019 • 34,000 km • Petrol • Automatic • First owner',
      tags: 'honda civic sedan petrol automatic',
      source: 'Dealer',
      link: 'https://www.cars.com/'
    },
    {
      title: 'Toyota Prado TX 2.8 Diesel',
      imageUrl: 'https://images.unsplash.com/photo-1519642578650-7c8d1f1f57d0?auto=format&fit=crop&w=900&q=80',
      price: 'ETB 2,300,000',
      description: '2014 • 98,000 km • Diesel • Automatic • Second owner',
      tags: 'toyota prado suv diesel automatic',
      source: 'Private Seller',
      link: 'https://www.cars.com/'
    }
  ];
}

function loadMarketplaceProducts() {
  const marketplaceGrid = document.getElementById('marketplaceGrid');
  if (!marketplaceGrid) return;
  marketplaceGrid.innerHTML = '';

  sampleMarketplaceProducts().forEach(product => {
    marketplaceGrid.appendChild(
      createMarketplaceCard(product.title, product.imageUrl, product.price, product.description, product.tags, product.source, product.link)
    );
  });
  observeRevealCards(marketplaceGrid);
}

function clearMarketplaceProducts() {
  const marketplaceGrid = document.getElementById('marketplaceGrid');
  if (!marketplaceGrid) return;
  marketplaceGrid.innerHTML = '';
}

function startEditProduct(card) {
  const title = card.querySelector('h3')?.textContent || '';
  const imageUrl = card.querySelector('img')?.src || '';
  const price = card.querySelector('.price')?.textContent || '';
  const description = card.querySelector('.product-description')?.textContent || '';
  const tags = card.dataset.search || '';
  const titleInput = document.getElementById('newTitle');
  const imageInput = document.getElementById('newImage');
  const priceInput = document.getElementById('newPrice');
  const descriptionInput = document.getElementById('newDescription');
  const tagsInput = document.getElementById('newTags');
  const submitButton = document.querySelector('#ownerForm button[type="submit"]');

  if (!titleInput || !imageInput || !priceInput || !descriptionInput || !tagsInput || !submitButton) return;

  titleInput.value = title;
  imageInput.value = imageUrl;
  priceInput.value = price;
  descriptionInput.value = description;
  tagsInput.value = tags;
  submitButton.textContent = 'Update Product';
  editingCard = card;
  showOwnerMessage('Editing product. Update the form and submit.', '#444');
}

function initStaticProductCards() {
  const scope = document.getElementById('productsPage') || document;
  scope.querySelectorAll('.product-card').forEach(card => attachProductActions(card));
}

function observeRevealCards(scope) {
  const root = scope || document;
  const cards = Array.from(root.querySelectorAll('.product-card:not(.recommendation-card):not(.is-revealed), .wishlist-card:not(.is-revealed)'));
  if (!cards.length) return;
  if (!window.RevealObserver) {
    window.RevealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-revealed');
        window.RevealObserver.unobserve(entry.target);
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -6% 0px' });
  }
  cards.forEach((card, i) => {
    card.style.setProperty('--reveal-index', i % 8);
    window.RevealObserver.observe(card);
  });
}

function renderCatalogGrid() {
  const grid = document.getElementById('productGrid');
  if (!grid || !window.ObamaCatalog) return;
  const products = window.ObamaCatalog.products;
  if (!products || !products.length) return;
  grid.innerHTML = products.map(catalogCardHtml).join('');
  grid.querySelectorAll('.product-card').forEach(card => attachProductActions(card));
  observeRevealCards(grid);
}

function catalogCardHtml(p) {
  const badge = p.badge ? `<span class="product-badge">${escapeHtml(p.badge)}</span>` : '';
  const meta = (p.tags || [])
    .slice(0, 3)
    .map(t => `<span>${escapeHtml(t.replace(/\b\w/g, c => c.toUpperCase()))}</span>`)
    .join('');
  const category = (p.category || '').toLowerCase();
  return (
    '<article class="product-card" data-product-id="' + escapeHtml(p.id) + '"' +
    ' data-search="' + escapeHtml(((p.tags || []).join(' ') + ' ' + p.title).toLowerCase()) + '"' +
    ' data-product-role="' + (category === 'cars' ? 'featured' : 'catalog') + '"' +
    ' data-category="' + escapeHtml(category) + '"' +
    ' data-price="' + Number(p.priceValue) + '"' +
    ' data-title="' + escapeHtml(p.title) + '">' +
    '<div class="product-image-wrap">' +
    '<img src="' + escapeHtml(p.imageUrl) + '" alt="' + escapeHtml(p.title) + '" loading="lazy" decoding="async">' +
    badge +
    '</div>' +
    '<div class="product-body">' +
    '<h3>' + escapeHtml(p.title) + '</h3>' +
    '<p class="product-description">' + escapeHtml(p.shortDescription) + '</p>' +
    '<div class="product-meta">' + meta + '</div>' +
    '<div class="product-footer">' +
    '<p class="price">' + escapeHtml(p.priceText) + '</p>' +
    '<div class="product-actions">' +
    '<button class="add-cart-btn" type="button">Add to cart</button>' +
    '<button class="view-details-btn" type="button">View details</button>' +
    '</div>' +
    '</div>' +
    '</div>' +
    '</article>'
  );
}

function initOwnerForm() {
  const ownerForm = document.getElementById('ownerForm');
  if (!ownerForm) return;

  const titleInput = document.getElementById('newTitle');
  const imageInput = document.getElementById('newImage');
  const priceInput = document.getElementById('newPrice');
  const descriptionInput = document.getElementById('newDescription');
  const tagsInput = document.getElementById('newTags');
  const submitButton = ownerForm.querySelector('button[type="submit"]');
  const resetButton = document.getElementById('resetOwnerForm');

  if (imageInput) {
    imageInput.addEventListener('input', () => {
      const productPreview = document.getElementById('productPreview');
      if (!productPreview) return;
      const url = imageInput.value.trim();
      if (url) {
        productPreview.src = url;
        productPreview.style.display = 'block';
      } else {
        productPreview.style.display = 'none';
      }
    });
  }

  ownerForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!titleInput || !imageInput || !priceInput || !descriptionInput) return;

    const title = titleInput.value.trim();
    const imageUrl = imageInput.value.trim();
    const price = priceInput.value.trim();
    const description = descriptionInput.value.trim();
    const tags = tagsInput.value.trim() || `${title} ${description}`;

    if (!title || !imageUrl || !price || !description) {
      showOwnerMessage('Please fill in all required fields.', 'red');
      return;
    }

    if (!submitButton) return;
    submitButton.disabled = true;
    const originalText = submitButton.textContent;
    submitButton.textContent = editingCard ? 'Updating...' : 'Adding...';
    showOwnerMessage(editingCard ? 'Updating product...' : 'Adding product, please wait...', '#333');

    setTimeout(() => {
      if (editingCard) {
        setProductCardValues(editingCard, title, imageUrl, price, description, tags);
        showOwnerMessage('Product updated successfully.', 'green');
      } else {
        const productGrid = document.getElementById('productGrid');
        if (productGrid) {
          const card = createProductCard(title, imageUrl, price, description, tags);
          productGrid.appendChild(card);
        }
        showOwnerMessage('Product added successfully.', 'green');
      }

      filterProducts();
      resetOwnerForm();
      submitButton.disabled = false;
      submitButton.textContent = originalText;
    }, 800);
  });

  if (resetButton) {
    resetButton.addEventListener('click', event => {
      event.preventDefault();
      resetOwnerForm();
    });
  }
}

function initMarketplaceButtons() {
  const loadMarketplaceBtn = document.getElementById('loadMarketplaceBtn');
  const clearMarketplaceBtn = document.getElementById('clearMarketplaceBtn');

  if (loadMarketplaceBtn) {
    loadMarketplaceBtn.addEventListener('click', () => {
      loadMarketplaceProducts();
      showOwnerMessage('Marketplace products loaded.', '#333');
    });
  }

  if (clearMarketplaceBtn) {
    clearMarketplaceBtn.addEventListener('click', () => {
      clearMarketplaceProducts();
      showOwnerMessage('Marketplace products cleared.', '#333');
    });
  }
}

function initMenuDrawer() {
  const toggle = document.getElementById('menuToggle');
  const closeBtn = document.getElementById('menuCloseBtn');
  const drawer = document.getElementById('menuDrawer');
  const backdrop = document.getElementById('menuBackdrop');
  if (!drawer) return;

  function openMenu() {
    closeCart();
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.hidden = false;
    if (toggle) toggle.setAttribute('aria-expanded', 'true');
  }

  function closeMenu() {
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    if (backdrop) backdrop.hidden = true;
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }

  window.closeMenuDrawer = closeMenu;

  if (toggle) toggle.addEventListener('click', openMenu);
  if (closeBtn) closeBtn.addEventListener('click', closeMenu);
  if (backdrop) backdrop.addEventListener('click', closeMenu);

  drawer.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', closeMenu);
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMenu();
  });
}

function initCategoryPills() {
  const pills = Array.from(document.querySelectorAll('[data-category-pill]'));
  if (!pills.length) return;
  const categoryFilter = document.getElementById('productCategoryFilter');

  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.toggle('is-active', p === pill));
      if (categoryFilter) {
        categoryFilter.value = pill.dataset.categoryPill;
        filterProducts();
      }
    });
  });
}

function initSearch() {
  const searchInput = document.getElementById('searchInput');
  const searchButton = document.getElementById('productSearchBtn');
  const categoryFilter = document.getElementById('productCategoryFilter');
  const sortSelect = document.getElementById('productSortSelect');
  const headerSearch = document.getElementById('headerSearch');
  const closeCartBtn = document.getElementById('closeCartBtn');
  const cartBackdrop = document.getElementById('cartBackdrop');
  const checkoutBtn = document.getElementById('checkoutBtn');
  const clearCartBtn = document.getElementById('clearCartBtn');
  const pageCheckout = document.getElementById('cartPageCheckout');
  const pageClear = document.getElementById('cartPageClear');

  if (searchInput) {
    searchInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        filterProducts();
      }
    });
  }

  if (searchButton) {
    searchButton.addEventListener('click', filterProducts);
  }

  [categoryFilter, sortSelect].forEach(control => {
    if (control) {
      control.addEventListener('change', filterProducts);
    }
  });

  if (headerSearch) {
    headerSearch.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (window.AppRouter) {
          window.AppRouter.navigate('products', { search: headerSearch.value.trim() });
        }
      }
    });
  }

  if (closeCartBtn) {
    closeCartBtn.addEventListener('click', closeCart);
  }

  if (cartBackdrop) {
    cartBackdrop.addEventListener('click', closeCart);
  }

  document.querySelectorAll('#cartDrawer a[href^="#/"]').forEach(link => {
    link.addEventListener('click', closeCart);
  });

  if (checkoutBtn) {
    checkoutBtn.addEventListener('click', checkoutCart);
  }

  if (clearCartBtn) {
    clearCartBtn.addEventListener('click', clearCart);
  }

  if (pageCheckout) {
    pageCheckout.addEventListener('click', checkoutCart);
  }

  if (pageClear) {
    pageClear.addEventListener('click', clearCart);
  }

  document.querySelectorAll('[data-close-modal="true"]').forEach(element => {
    element.addEventListener('click', event => {
      const modal = event.currentTarget.closest('.modal');
      if (modal) {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
      }
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      closeProductModal();
      closeModal('compareModal');
      closeCart();
    }
  });
}

function init() {
  loadPersistedState();
  cartTotal = cartEntries.reduce((sum, item) => sum + (Number(item.quantity) || 1), 0);
  updateCartCount(0);
  initThemeToggle();
  initMenuDrawer();
  renderCatalogGrid();
  initStaticProductCards();
  initOwnerForm();
  initMarketplaceButtons();
  initCategoryPills();
  initSearch();
  initCarRecommendation();
  loadRecentlyViewed();
  loadMarketplaceProducts();
  renderFavoritesPanel();
  renderCompareSummary();
  renderCart();
  renderWishlistPage();

  if (window.AppRouter) {
    window.AppRouter.render();
  }
}

document.addEventListener('DOMContentLoaded', init);
