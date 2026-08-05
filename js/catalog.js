/**
 * ObamaCatalog — data layer for the product details page.
 *
 * Owns product data (catalog, reviews, options, specs), plus pure lookup
 * and cross-sell logic (related / similar / bundles). No UI or DOM here.
 * Swap `catalog` for a fetch() to plug in a real backend API later.
 */
(function () {
  'use strict';

  const U = (id, w) => `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=${w}&q=80`;

  const IMG = {
    corolla: [U('1503376780353-7e6692767b70', 1200), U('1549399542-7e3f8b79c341', 900), U('1494976388531-d1058494cdd8', 900), U('1553440569-bcc63803a83d', 900)],
    creta: [U('1511919884226-fd3cad34687c', 1200), U('1519642578650-7c8d1f1f57d0', 900), U('1503736334956-4c8f8e92946d', 900), U('1517524206127-48bbd363f3d7', 900)],
    civic: [U('1553440569-bcc63803a83d', 1200), U('1503376780353-7e6692767b70', 900), U('1492144534655-ae79c964c9d7', 900), U('1494976388531-d1058494cdd8', 900)],
    prado: [U('1519642578650-7c8d1f1f57d0', 1200), U('1511919884226-fd3cad34687c', 900), U('1503736334956-4c8f8e92946d', 900), U('1494976388531-d1058494cdd8', 900)],
    iphone: [U('1511707171634-5f897ff02aa9', 1200), U('1592750475338-74b7b21085ab', 900), U('1574944985070-8f3ebc6b79d2', 900), U('1591337676887-a217a6970a8a', 900)],
    galaxy: [U('1610945265064-0e34e5519bbf', 1200), U('1574944985070-8f3ebc6b79d2', 900), U('1598327105666-5b89351aff97', 900), U('1591337676887-a217a6970a8a', 900)],
    macbook: [U('1517336714731-489689fd1ca8', 1200), U('1496181133206-80ce9b88a853', 900), U('1611186871348-b1ce696e52c9', 900), U('1531297484001-80022131f5a1', 900)],
    watch: [U('1546868871-7041f2a55e12', 1200), U('1523275335684-37898b6baf30', 900), U('1524805444758-089113d48a6d', 900), U('1508685096489-7aacd43bd3b1', 900)],
    nike: [U('1521572267360-ee0c2909d518', 1200), U('1515886657613-9f3515b0c78f', 900), U('1551028719-00167b16eac5', 900), U('1542291026-7eec264c27ff', 900)],
    sony: [U('1505740420928-5e560c06d30e', 1200), U('1583394838336-acd977736f90', 900), U('1546435770-a3e426bf472b', 900), U('1608043152269-423dbba4e7e1', 900)],
    bravia: [U('1461151304267-38535e780c79', 1200), U('1601944179066-29786cb9d32a', 900), U('1611162617213-7d7a39e9b1d7', 900), U('1593784991095-a205fe470a6b', 900)],
    jbl: [U('1608043152269-423dbba4e7e1', 1200), U('1583394838336-acd977736f90', 900), U('1505740420928-5e560c06d30e', 900), U('1546435770-a3e426bf472b', 900)]
  };

  const base = {
    currency: 'USD',
    priceValue: 0,
    discount: 0,
    rating: 4.6,
    reviewCount: 128,
    stock: 24,
    badge: '',
    shortDescription: '',
    detailedDescription: '',
    highlights: [],
    specs: [],
    options: {},
    tags: [],
    bundle: [],
    delivery: { eta: '2–4 business days', cost: 'Free over ETB 5,000' },
    warranty: '30-day return policy and 12-month warranty on all electronics.'
  };

  const products = [
    {
      id: 'toyota-corolla-altis-cars',
      title: 'Toyota Corolla Altis 1.8 VL CVT',
      brand: 'Toyota',
      category: 'Cars',
      currency: 'ETB',
      priceValue: 1650000,
      discount: 6,
      rating: 4.7,
      reviewCount: 214,
      stock: 3,
      badge: 'Best seller',
      images: IMG.corolla,
      shortDescription: '2018 • 25,000 km • Petrol • Automatic • First owner.',
      detailedDescription: 'A dependable executive sedan with a refined CVT gearbox, low fuel consumption and a well-appointed cabin. Regularly serviced at an authorized dealer, this Altis is a smart choice for both city commutes and long highway drives with strong resale value.',
      highlights: ['25,000 km, first owner', 'CVT automatic transmission', 'Cruise control & dual-zone AC', 'Bluetooth, reversing camera', 'Dealer-serviced history'],
      specs: [
        { label: 'Year', value: '2018' },
        { label: 'Kilometers', value: '25,000 km' },
        { label: 'Fuel type', value: 'Petrol' },
        { label: 'Transmission', value: 'Automatic (CVT)' },
        { label: 'Ownership', value: 'First owner' },
        { label: 'Seller type', value: 'Dealer' },
        { label: 'Body type', value: 'Sedan' }
      ],
      options: { color: [{ name: 'Silver', swatch: '#c7ccd4' }, { name: 'Pearl White', swatch: '#f3f4f6' }, { name: 'Attitude Black', swatch: '#1f2937' }] },
      tags: ['sedan', 'petrol', 'automatic', 'toyota', 'corolla'],
      bundle: ['honda-civic-cars', 'hyundai-creta-cars', 'sony-wh1000xm5-accessories'],
      delivery: { eta: 'Inspection + handover in 2–3 days', cost: 'Free delivery inside Addis Ababa' }
    },
    {
      id: 'toyota-prado-cars',
      title: 'Toyota Prado TX 2.8 Diesel',
      brand: 'Toyota',
      category: 'Cars',
      currency: 'ETB',
      priceValue: 2300000,
      discount: 4,
      rating: 4.9,
      reviewCount: 156,
      stock: 2,
      badge: 'Trending',
      images: IMG.prado,
      shortDescription: '2014 • 98,000 km • Diesel • Automatic • Second owner.',
      detailedDescription: 'The legendary Prado TX 2.8 diesel combines rugged off-road capability with premium comfort. Built for rough roads and long distances, it features a durable 2.8L diesel engine, spacious 7-seat cabin and advanced safety equipment.',
      highlights: ['2.8L diesel engine', '7-seater with captain comfort', 'Full-time 4WD', 'Rear AC & leather trim', 'Strong resale demand'],
      specs: [
        { label: 'Year', value: '2014' },
        { label: 'Kilometers', value: '98,000 km' },
        { label: 'Fuel type', value: 'Diesel' },
        { label: 'Transmission', value: 'Automatic' },
        { label: 'Ownership', value: 'Second owner' },
        { label: 'Drive', value: '4WD' },
        { label: 'Body type', value: 'SUV' }
      ],
      options: { color: [{ name: 'White', swatch: '#f8fafc' }, { name: 'Grey', swatch: '#94a3b8' }] },
      tags: ['suv', 'diesel', 'automatic', 'toyota', 'prado'],
      bundle: ['hyundai-creta-cars', 'macbook-air-m2-electronics', 'nike-windbreaker-fashion']
    },
    {
      id: 'honda-civic-cars',
      title: 'Honda Civic 1.8 V AT',
      brand: 'Honda',
      category: 'Cars',
      currency: 'ETB',
      priceValue: 1470000,
      discount: 3,
      rating: 4.6,
      reviewCount: 132,
      stock: 4,
      badge: 'New arrival',
      images: IMG.civic,
      shortDescription: '2019 • 34,000 km • Petrol • Automatic • First owner.',
      detailedDescription: 'A low-mileage executive sedan with a premium cabin, smooth automatic transmission and excellent reliability. The Civic V is refined, efficient and one of the most dependable cars in its class.',
      highlights: ['34,000 km, first owner', 'Automatic transmission', 'Premium cabin quality', 'Dual airbags & ABS', 'Fuel-efficient 1.8L engine'],
      specs: [
        { label: 'Year', value: '2019' },
        { label: 'Kilometers', value: '34,000 km' },
        { label: 'Fuel type', value: 'Petrol' },
        { label: 'Transmission', value: 'Automatic' },
        { label: 'Ownership', value: 'First owner' },
        { label: 'Body type', value: 'Sedan' }
      ],
      options: { color: [{ name: 'Modern Steel', swatch: '#64748b' }, { name: 'White Orchid', swatch: '#f1f5f9' }, { name: 'Crystal Black', swatch: '#0f172a' }] },
      tags: ['sedan', 'petrol', 'automatic', 'honda', 'civic'],
      bundle: ['toyota-corolla-altis-cars', 'apple-watch-series-9-wearables', 'sony-wh1000xm5-accessories']
    },
    {
      id: 'hyundai-creta-cars',
      title: 'Hyundai Creta 1.6 VTVT S',
      brand: 'Hyundai',
      category: 'Cars',
      currency: 'ETB',
      priceValue: 850000,
      discount: 8,
      rating: 4.5,
      reviewCount: 98,
      stock: 5,
      badge: 'Best value',
      images: IMG.creta,
      shortDescription: '2015 • 25,000 km • Petrol • Manual • First owner.',
      detailedDescription: 'A compact SUV that is efficient, practical and fun to drive. The Creta offers generous cargo space, a bold design and low running costs — ideal for city and family use.',
      highlights: ['25,000 km, first owner', 'Manual transmission', 'Compact SUV styling', '6 airbags', 'Touchscreen infotainment'],
      specs: [
        { label: 'Year', value: '2015' },
        { label: 'Kilometers', value: '25,000 km' },
        { label: 'Fuel type', value: 'Petrol' },
        { label: 'Transmission', value: 'Manual' },
        { label: 'Ownership', value: 'First owner' },
        { label: 'Body type', value: 'SUV' }
      ],
      options: { color: [{ name: 'Fiery Red', swatch: '#dc2626' }, { name: 'Polar White', swatch: '#f8fafc' }, { name: 'Phantom Grey', swatch: '#6b7280' }] },
      tags: ['suv', 'petrol', 'manual', 'hyundai', 'creta'],
      bundle: ['toyota-corolla-altis-cars', 'jbl-flip-6-accessories', 'nike-windbreaker-fashion']
    },
    {
      id: 'iphone-15-pro-max-mobile',
      title: 'iPhone 15 Pro Max',
      brand: 'Apple',
      category: 'Mobile',
      priceValue: 1199,
      discount: 8,
      rating: 4.8,
      reviewCount: 1243,
      stock: 18,
      badge: 'New arrival',
      images: IMG.iphone,
      shortDescription: '256GB • Titanium • 5G • Pro camera system.',
      detailedDescription: 'Apple\u2019s most advanced iPhone. The aerospace-grade titanium frame houses the lightning-fast A17 Pro chip, a powerful pro camera system with 5x telephoto, and an immersive 6.7-inch Super Retina XDR display with ProMotion. All-day battery and USB-C round out a flagship experience.',
      highlights: ['A17 Pro chip', '6.7" Super Retina XDR with ProMotion', '48MP pro camera + 5x telephoto', 'Titanium design', 'USB-C • all-day battery'],
      specs: [
        { label: 'Display', value: '6.7" Super Retina XDR, 120Hz' },
        { label: 'Chip', value: 'A17 Pro' },
        { label: 'Storage', value: '256GB' },
        { label: 'Rear camera', value: '48MP + 12MP + 12MP (5x zoom)' },
        { label: 'Front camera', value: '12MP TrueDepth' },
        { label: 'Battery', value: 'All-day, 20W fast charge' },
        { label: 'Connectivity', value: '5G, Wi-Fi 6E, Bluetooth 5.3' },
        { label: 'Water resistance', value: 'IP68' }
      ],
      options: {
        color: [{ name: 'Natural Titanium', swatch: '#c8c2b4' }, { name: 'Blue Titanium', swatch: '#4b5f8f' }, { name: 'White Titanium', swatch: '#ece9e4' }, { name: 'Black Titanium', swatch: '#23262c' }],
        storage: [{ name: '256GB', extra: 0 }, { name: '512GB', extra: 120 }, { name: '1TB', extra: 240 }]
      },
      tags: ['iphone', 'apple', 'mobile', 'titanium', '5g', 'pro'],
      bundle: ['sony-wh1000xm5-accessories', 'apple-watch-series-9-wearables', 'nike-windbreaker-fashion']
    },
    {
      id: 'samsung-galaxy-s24-ultra-mobile',
      title: 'Samsung Galaxy S24 Ultra',
      brand: 'Samsung',
      category: 'Mobile',
      priceValue: 1099,
      discount: 10,
      rating: 4.7,
      reviewCount: 876,
      stock: 15,
      badge: 'New arrival',
      images: IMG.galaxy,
      shortDescription: '256GB • Snapdragon 8 Gen 3 • 200MP camera • S Pen.',
      detailedDescription: 'The Galaxy S24 Ultra is an AI-powered powerhouse with a built-in S Pen, a stunning flat 6.8-inch QHD+ display, the most advanced 200MP camera system yet, and Galaxy AI features that translate, summarize and create in real time.',
      highlights: ['200MP quad camera', 'Built-in S Pen', 'Snapdragon 8 Gen 3', 'Galaxy AI', '5000mAh + 45W charging'],
      specs: [
        { label: 'Display', value: '6.8" QHD+ Dynamic AMOLED 2X, 120Hz' },
        { label: 'Chip', value: 'Snapdragon 8 Gen 3' },
        { label: 'Storage', value: '256GB' },
        { label: 'Rear camera', value: '200MP + 50MP + 12MP + 10MP' },
        { label: 'Front camera', value: '12MP' },
        { label: 'Battery', value: '5000mAh, 45W super fast charge' },
        { label: 'Extras', value: 'S Pen included, IP68, Gorilla Armor' }
      ],
      options: {
        color: [{ name: 'Titanium Gray', swatch: '#6b7280' }, { name: 'Titanium Violet', swatch: '#7c6f8c' }, { name: 'Titanium Black', swatch: '#1f2937' }],
        storage: [{ name: '256GB', extra: 0 }, { name: '512GB', extra: 120 }]
      },
      tags: ['samsung', 'galaxy', 'android', 's24', '5g', 'spen'],
      bundle: ['sony-wh1000xm5-accessories', 'apple-watch-series-9-wearables', 'jbl-flip-6-accessories']
    },
    {
      id: 'macbook-air-m2-electronics',
      title: 'MacBook Air M2',
      brand: 'Apple',
      category: 'Electronics',
      priceValue: 1399,
      discount: 5,
      rating: 4.9,
      reviewCount: 689,
      stock: 12,
      badge: 'Hot deal',
      images: IMG.macbook,
      shortDescription: '16GB RAM • 512GB SSD • 13.6-inch Liquid Retina display.',
      detailedDescription: 'Redesigned around the M2 chip, the MacBook Air is impossibly thin and quiet, yet delivers outstanding performance and up to 18 hours of battery life. The 13.6-inch Liquid Retina display, MagSafe charging and four speakers make it the ultimate all-rounder laptop.',
      highlights: ['Apple M2 chip (8-core CPU / 10-core GPU)', '13.6" Liquid Retina display', '16GB unified memory', '512GB SSD', '18-hour battery, MagSafe'],
      specs: [
        { label: 'Chip', value: 'Apple M2' },
        { label: 'Memory', value: '16GB unified memory' },
        { label: 'Storage', value: '512GB SSD' },
        { label: 'Display', value: '13.6" Liquid Retina (2560x1664)' },
        { label: 'Battery', value: 'Up to 18 hours' },
        { label: 'Ports', value: '2x Thunderbolt, MagSafe 3, headphone' },
        { label: 'Weight', value: '1.24 kg' }
      ],
      options: {
        color: [{ name: 'Midnight', swatch: '#23262c' }, { name: 'Starlight', swatch: '#e8e2d6' }, { name: 'Space Gray', swatch: '#4b4f57' }, { name: 'Silver', swatch: '#d7d9dd' }],
        storage: [{ name: '512GB', extra: 0 }, { name: '1TB', extra: 200 }, { name: '2TB', extra: 400 }]
      },
      tags: ['apple', 'macbook', 'laptop', 'm2', 'electronics'],
      bundle: ['sony-wh1000xm5-accessories', 'jbl-flip-6-accessories', 'iphone-15-pro-max-mobile']
    },
    {
      id: 'apple-watch-series-9-wearables',
      title: 'Apple Watch Series 9',
      brand: 'Apple',
      category: 'Wearables',
      priceValue: 249,
      discount: 12,
      rating: 4.7,
      reviewCount: 512,
      stock: 30,
      badge: 'Trending',
      images: IMG.watch,
      shortDescription: 'GPS • 45mm • Stainless steel • Health tracking.',
      detailedDescription: 'The Apple Watch Series 9 keeps you connected, active and safe. Track workouts, heart health and sleep, use the new Double Tap gesture, and enjoy the brighter Always-On Retina display with the powerful S9 SiP.',
      highlights: ['S9 SiP chip', 'Double Tap gesture', 'Blood oxygen & ECG', 'Always-On Retina, 2000 nits', 'Crash detection'],
      specs: [
        { label: 'Case size', value: '45mm' },
        { label: 'Material', value: 'Stainless steel' },
        { label: 'Display', value: 'Always-On Retina LTPO' },
        { label: 'Sensors', value: 'ECG, blood oxygen, heart rate' },
        { label: 'Water resistance', value: '50m' },
        { label: 'Battery', value: 'Up to 18 hours' }
      ],
      options: {
        color: [{ name: 'Graphite', swatch: '#374151' }, { name: 'Silver', swatch: '#d1d5db' }, { name: 'Gold', swatch: '#c9a86a' }],
        size: [{ name: '41mm' }, { name: '45mm' }]
      },
      tags: ['apple', 'watch', 'wearable', 'fitness', 'smartwatch'],
      bundle: ['iphone-15-pro-max-mobile', 'sony-wh1000xm5-accessories', 'samsung-galaxy-s24-ultra-mobile']
    },
    {
      id: 'nike-windbreaker-fashion',
      title: 'Nike Windbreaker Jacket',
      brand: 'Nike',
      category: 'Fashion',
      priceValue: 89,
      discount: 20,
      rating: 4.4,
      reviewCount: 342,
      stock: 45,
      badge: 'Style pick',
      images: IMG.nike,
      shortDescription: 'Water-resistant shell • Lightweight • Black and gray.',
      detailedDescription: 'A featherweight windbreaker that packs into its own pocket. The Dri-FIT-inspired shell sheds light rain and blocks wind while staying breathable, making it perfect for travel, commuting and race days.',
      highlights: ['Water-resistant shell', 'Packs into its own pocket', 'Adjustable hood & cuffs', 'Breathable mesh lining', 'Reflective details'],
      specs: [
        { label: 'Material', value: '100% polyester shell' },
        { label: 'Lining', value: 'Breathable mesh' },
        { label: 'Fit', value: 'Athletic, true to size' },
        { label: 'Care', value: 'Machine wash cold' },
        { label: 'Season', value: 'All seasons' }
      ],
      options: {
        color: [{ name: 'Black', swatch: '#111827' }, { name: 'Grey', swatch: '#9ca3af' }, { name: 'Olive', swatch: '#5f6b4a' }],
        size: [{ name: 'S' }, { name: 'M' }, { name: 'L' }, { name: 'XL' }, { name: 'XXL' }]
      },
      tags: ['nike', 'jacket', 'fashion', 'outdoor', 'windbreaker'],
      bundle: ['sony-wh1000xm5-accessories', 'jbl-flip-6-accessories', 'hyundai-creta-cars']
    },
    {
      id: 'sony-wh1000xm5-accessories',
      title: 'Sony WH-1000XM5',
      brand: 'Sony',
      category: 'Accessories',
      priceValue: 159,
      discount: 15,
      rating: 4.8,
      reviewCount: 957,
      stock: 40,
      badge: 'Audio favorite',
      images: IMG.sony,
      shortDescription: 'Noise cancelling • 30-hour battery • Comfort fit.',
      detailedDescription: 'Industry-leading noise cancellation meets studio-grade sound. Eight microphones and a new integrated processor deliver the best-in-class silence, while the plush soft-fit leather ear cups keep you comfortable for hours of listening.',
      highlights: ['Industry-leading ANC', '30-hour battery life', '8 microphones for calls', 'Hi-Res Audio & LDAC', 'Multipoint pairing'],
      specs: [
        { label: 'Type', value: 'Over-ear, wireless' },
        { label: 'Noise cancelling', value: 'Industry-leading (8 mics)' },
        { label: 'Battery', value: '30h (ANC on)' },
        { label: 'Charging', value: 'USB-C, 3h for 30h via 3min' },
        { label: 'Codecs', value: 'SBC, AAC, LDAC' },
        { label: 'Weight', value: '250g' }
      ],
      options: { color: [{ name: 'Black', swatch: '#1f2937' }, { name: 'Silver', swatch: '#d1d5db' }, { name: 'Midnight Blue', swatch: '#1e3a8a' }] },
      tags: ['sony', 'headphones', 'audio', 'anc', 'noise-cancelling'],
      bundle: ['jbl-flip-6-accessories', 'macbook-air-m2-electronics', 'iphone-15-pro-max-mobile']
    },
    {
      id: 'sony-bravia-55-electronics',
      title: 'Sony Bravia XR 55" 4K OLED TV',
      brand: 'Sony',
      category: 'Electronics',
      priceValue: 1699,
      discount: 18,
      rating: 4.8,
      reviewCount: 231,
      stock: 8,
      badge: 'Hot deal',
      images: IMG.bravia,
      shortDescription: '55-inch OLED • 4K HDR • Google TV • XR processor.',
      detailedDescription: 'Experience cinematic contrast with self-lit OLED pixels and the Cognitive Processor XR that analyzes and optimizes picture and sound the way you see and hear. Perfect for movies, gaming and sports on Google TV.',
      highlights: ['55" OLED, 4K HDR', 'Cognitive Processor XR', 'XR OLED Contrast Pro', 'Google TV with voice remote', '120Hz for gaming'],
      specs: [
        { label: 'Screen size', value: '55" OLED' },
        { label: 'Resolution', value: '3840 x 2160 (4K)' },
        { label: 'Processor', value: 'Cognitive Processor XR' },
        { label: 'Refresh rate', value: '120Hz' },
        { label: 'HDR', value: 'HDR10, Dolby Vision, HLG' },
        { label: 'Smart OS', value: 'Google TV' },
        { label: 'Connectivity', value: '4x HDMI 2.1, 2x USB, Wi-Fi, BT' }
      ],
      options: { size: [{ name: '55"', extra: 0 }, { name: '65"', extra: 500 }, { name: '77"', extra: 1400 }] },
      tags: ['sony', 'tv', 'oled', '4k', 'electronics', 'google tv'],
      bundle: ['jbl-flip-6-accessories', 'sony-wh1000xm5-accessories', 'macbook-air-m2-electronics']
    },
    {
      id: 'jbl-flip-6-accessories',
      title: 'JBL Flip 6 Bluetooth Speaker',
      brand: 'JBL',
      category: 'Accessories',
      priceValue: 129,
      discount: 10,
      rating: 4.6,
      reviewCount: 415,
      stock: 60,
      badge: 'Audio favorite',
      images: IMG.jbl,
      shortDescription: 'Portable waterproof speaker • 12-hour battery • Deep bass.',
      detailedDescription: 'The JBL Flip 6 delivers rich JBL Original Pro Sound with a racetrack-shaped driver for deep bass. IP67 waterproof and dustproof, with 12 hours of playtime and seamless party pairing.',
      highlights: ['JBL Original Pro Sound', 'IP67 waterproof & dustproof', '12-hour battery', 'PartyBoost pairing', 'USB-C charging'],
      specs: [
        { label: 'Power', value: '30W output' },
        { label: 'Battery', value: '12 hours' },
        { label: 'Waterproof', value: 'IP67' },
        { label: 'Bluetooth', value: '5.1' },
        { label: 'Pairing', value: 'PartyBoost (100+ speakers)' },
        { label: 'Weight', value: '550g' }
      ],
      options: { color: [{ name: 'Blue', swatch: '#2563eb' }, { name: 'Red', swatch: '#dc2626' }, { name: 'Black', swatch: '#111827' }, { name: 'Squad', swatch: '#0f766e' }] },
      tags: ['jbl', 'speaker', 'audio', 'bluetooth', 'portable'],
      bundle: ['sony-wh1000xm5-accessories', 'nike-windbreaker-fashion', 'apple-watch-series-9-wearables']
    }
  ];

  products.forEach(p => {
    Object.assign(p, base, p);
    p.imageUrl = p.images[0];
    p.alt = p.shortDescription || p.title;
    p.priceText = formatPrice(p.priceValue, p.currency);
    if (p.discount > 0) {
      p.originalPrice = Math.round(p.priceValue / (1 - p.discount / 100));
      p.originalPriceText = formatPrice(p.originalPrice, p.currency);
    }
  });

  function formatPrice(value, currency) {
    const n = Number(value || 0);
    if (currency === 'ETB') return 'ETB ' + n.toLocaleString();
    return '$' + n.toFixed(2);
  }

  const reviewPool = [
    { author: 'Samuel A.', rating: 5, title: 'Exactly as described', body: 'Packaging was premium and the product matches the photos perfectly. Very happy with the purchase and the delivery speed.' },
    { author: 'Meron T.', rating: 5, title: 'Excellent quality', body: 'I compared this with other options and this is the best value by far. Customer service confirmed my order within minutes.' },
    { author: 'Yonas K.', rating: 4, title: 'Great, minor note', body: 'Solid product, works flawlessly. Would be 5 stars if the box included a small manual, but everything else is top notch.' },
    { author: 'Selam D.', rating: 5, title: 'Fast delivery', body: 'Ordered on Monday, arrived on Wednesday. The tracking updates were clear and the item was well protected.' },
    { author: 'Biruk M.', rating: 4, title: 'Good value', body: 'Strong performance for the price. The build feels durable and it looks even better in person.' },
    { author: 'Hanna G.', rating: 5, title: 'Worth every birr', body: 'Professional storefront and friendly team. I will definitely buy from Obama Store again.' },
    { author: 'Dawit N.', rating: 3, title: 'Good but expect wait', body: 'The product is great, but delivery took slightly longer than expected. Overall satisfied.' },
    { author: 'Liya B.', rating: 5, title: 'Top tier', body: 'Authentic product, carefully checked before shipping. The guarantee gives real peace of mind.' },
    { author: 'Natnael S.', rating: 4, title: 'Recommended', body: 'Very good quality and honest description. Photos are accurate — no surprises.' },
    { author: 'Eden F.', rating: 5, title: 'Amazing experience', body: 'From ordering to delivery, everything was smooth. The team even followed up to confirm I received it.' }
  ];

  function hashString(str) {
    let h = 0;
    for (let i = 0; i < str.length; i += 1) {
      h = (h << 5) - h + str.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h);
  }

  function reviewsFor(product) {
    const seed = hashString(product.id);
    const count = 4 + (seed % 3);
    const out = [];
    for (let i = 0; i < count; i += 1) {
      const review = reviewPool[(seed + i) % reviewPool.length];
      out.push({ ...review, date: dateString(seed + i) });
    }
    return out;
  }

  function dateString(seed) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[seed % 12];
    const day = 1 + ((seed * 7) % 27);
    const year = 2026;
    return `${month} ${day}, ${year}`;
  }

  function ratingBreakdown(rating, count) {
    const seed = rating * 100 + count;
    const p5 = Math.round(60 + (seed % 30));
    const p4 = Math.round((100 - p5) * (0.5 + (seed % 30) / 100));
    const p3 = Math.round((100 - p5 - p4) * 0.5);
    const p2 = Math.max(1, Math.round((100 - p5 - p4 - p3) * 0.4));
    const p1 = Math.max(1, 100 - p5 - p4 - p3 - p2);
    return [
      { stars: 5, percent: p5 },
      { stars: 4, percent: p4 },
      { stars: 3, percent: p3 },
      { stars: 2, percent: p2 },
      { stars: 1, percent: p1 }
    ];
  }

  function getProduct(id) {
    return products.find(p => p.id === id) || null;
  }

  function findByTitle(title) {
    if (!title) return null;
    const normalized = String(title).toLowerCase();
    return products.find(p => normalized.includes(p.title.toLowerCase())) || null;
  }

  function byCategory(category, excludeId, limit) {
    return products.filter(p => p.category === category && p.id !== excludeId).slice(0, limit);
  }

  function getRelated(product) {
    const same = byCategory(product.category, product.id, 4);
    return same;
  }

  function getSimilar(product) {
    const tagSet = new Set((product.tags || []).map(t => t.toLowerCase()));
    const scored = products
      .filter(p => p.id !== product.id)
      .map(p => {
        const overlap = (p.tags || []).filter(t => tagSet.has(t.toLowerCase())).length;
        return { p, score: overlap };
      })
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score)
      .map(item => item.p);
    return scored.slice(0, 4);
  }

  function getBundle(product) {
    return (product.bundle || []).map(getProduct).filter(Boolean);
  }

  window.ObamaCatalog = {
    products,
    getProduct,
    findByTitle,
    getRelated,
    getSimilar,
    getBundle,
    reviewsFor,
    ratingBreakdown,
    formatPrice
  };
})();
