"""Recommendation engine for Obama Store.

A hybrid, ML-powered recommender used by the product catalogue:

* Content-based filtering  — TF-IDF over product tokens (title, brand,
  category, tags) with cosine similarity for "Similar products".
* Personalization          — a weighted user profile built from explicit
  activity signals (views, searches, wishlist, cart, purchases) blended with
  content similarity and recency decay. Powers "Recommended for You".
* Co-purchase ("Frequently bought together")  — symmetric bundle/co-purchase
  adjacency.
* Co-view ("Customers also viewed")           — generated browsing sessions
  ranked by co-occurrence frequency.
* Popularity ("Trending" / "Best sellers" / "New arrivals") — deterministic
  popularity, sales and recency signals.
* ML value model            — for cars the existing GradientBoosting price
  model contributes a predicted fair price and a normalized value score.

The catalogue is the single source of truth for the recommendation API and is
kept in sync with js/catalog.js (the client-side data layer).
"""

import math
import time
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

IMG = lambda pid, w: (  # noqa: E731
    f"https://images.unsplash.com/photo-{pid}?auto=format&fit=crop&w={w}&q=80"
)

IMAGES = {
    "corolla": [IMG("1503376780353-7e6692767b70", 1200), IMG("1549399542-7e3f8b79c341", 900)],
    "creta": [IMG("1511919884226-fd3cad34687c", 1200), IMG("1519642578650-7c8d1f1f57d0", 900)],
    "civic": [IMG("1553440569-bcc63803a83d", 1200), IMG("1503376780353-7e6692767b70", 900)],
    "prado": [IMG("1519642578650-7c8d1f1f57d0", 1200), IMG("1511919884226-fd3cad34687c", 900)],
    "iphone": [IMG("1511707171634-5f897ff02aa9", 1200), IMG("1592750475338-74b7b21085ab", 900)],
    "galaxy": [IMG("1610945265064-0e34e5519bbf", 1200), IMG("1574944985070-8f3ebc6b79d2", 900), IMG("1598327105666-5b89351aff97", 900), IMG("1591337676887-a217a6970a8a", 900)],
    "macbook": [IMG("1517336714731-489689fd1ca8", 1200), IMG("1496181133206-80ce9b88a853", 900)],
    "watch": [IMG("1546868871-7041f2a55e12", 1200), IMG("1523275335684-37898b6baf30", 900)],
    "nike": [IMG("1521572267360-ee0c2909d518", 1200), IMG("1515886657613-9f3515b0c78f", 900)],
    "sony": [IMG("1505740420928-5e560c06d30e", 1200), IMG("1583394838336-acd977736f90", 900)],
    "bravia": [IMG("1461151304267-38535e780c79", 1200), IMG("1601944179066-29786cb9d32a", 900)],
    "jbl": [IMG("1608043152269-423dbba4e7e1", 1200), IMG("1583394838336-acd977736f90", 900)],
}


def _price_text(value, currency):
    value = int(round(float(value)))
    if currency == "ETB":
        return f"ETB {value:,}"
    return f"${value:,}.00"


# ---------------------------------------------------------------------------
# Catalogue (mirrors js/catalog.js)
# ---------------------------------------------------------------------------

PRODUCTS = [
    {
        "id": "toyota-corolla-altis-cars",
        "title": "Toyota Corolla Altis 1.8 VL CVT",
        "brand": "Toyota",
        "category": "Cars",
        "currency": "ETB",
        "priceValue": 1650000,
        "discount": 6,
        "rating": 4.7,
        "reviewCount": 214,
        "stock": 3,
        "badge": "Best seller",
        "images": IMAGES["corolla"],
        "shortDescription": "2018 • 25,000 km • Petrol • Automatic • First owner.",
        "tags": ["sedan", "petrol", "automatic", "toyota", "corolla"],
        "bundle": ["honda-civic-cars", "hyundai-creta-cars", "sony-wh1000xm5-accessories"],
        "sales": 214,
        "isNew": False,
        "addedOrder": 1,
        "year": 2018,
        "km": 25000,
        "fuel": "Petrol",
        "transmission": "Automatic",
        "owner": "First Owner",
        "sellerType": "Dealer",
    },
    {
        "id": "toyota-prado-cars",
        "title": "Toyota Prado TX 2.8 Diesel",
        "brand": "Toyota",
        "category": "Cars",
        "currency": "ETB",
        "priceValue": 2300000,
        "discount": 4,
        "rating": 4.9,
        "reviewCount": 156,
        "stock": 2,
        "badge": "Trending",
        "images": IMAGES["prado"],
        "shortDescription": "2014 • 98,000 km • Diesel • Automatic • Second owner.",
        "tags": ["suv", "diesel", "automatic", "toyota", "prado"],
        "bundle": ["hyundai-creta-cars", "macbook-air-m2-electronics", "nike-windbreaker-fashion"],
        "sales": 156,
        "isNew": False,
        "addedOrder": 2,
        "year": 2014,
        "km": 98000,
        "fuel": "Diesel",
        "transmission": "Automatic",
        "owner": "Second Owner",
        "sellerType": "Individual",
    },
    {
        "id": "honda-civic-cars",
        "title": "Honda Civic 1.8 V AT",
        "brand": "Honda",
        "category": "Cars",
        "currency": "ETB",
        "priceValue": 1470000,
        "discount": 3,
        "rating": 4.6,
        "reviewCount": 132,
        "stock": 4,
        "badge": "New arrival",
        "images": IMAGES["civic"],
        "shortDescription": "2019 • 34,000 km • Petrol • Automatic • First owner.",
        "tags": ["sedan", "petrol", "automatic", "honda", "civic"],
        "bundle": ["toyota-corolla-altis-cars", "apple-watch-series-9-wearables", "sony-wh1000xm5-accessories"],
        "sales": 132,
        "isNew": True,
        "addedOrder": 3,
        "year": 2019,
        "km": 34000,
        "fuel": "Petrol",
        "transmission": "Automatic",
        "owner": "First Owner",
        "sellerType": "Dealer",
    },
    {
        "id": "hyundai-creta-cars",
        "title": "Hyundai Creta 1.6 VTVT S",
        "brand": "Hyundai",
        "category": "Cars",
        "currency": "ETB",
        "priceValue": 850000,
        "discount": 8,
        "rating": 4.5,
        "reviewCount": 98,
        "stock": 5,
        "badge": "Best value",
        "images": IMAGES["creta"],
        "shortDescription": "2015 • 25,000 km • Petrol • Manual • First owner.",
        "tags": ["suv", "petrol", "manual", "hyundai", "creta"],
        "bundle": ["toyota-corolla-altis-cars", "jbl-flip-6-accessories", "nike-windbreaker-fashion"],
        "sales": 98,
        "isNew": False,
        "addedOrder": 4,
        "year": 2015,
        "km": 25000,
        "fuel": "Petrol",
        "transmission": "Manual",
        "owner": "First Owner",
        "sellerType": "Individual",
    },
    {
        "id": "iphone-15-pro-max-mobile",
        "title": "iPhone 15 Pro Max",
        "brand": "Apple",
        "category": "Mobile",
        "currency": "USD",
        "priceValue": 1199,
        "discount": 8,
        "rating": 4.8,
        "reviewCount": 1243,
        "stock": 18,
        "badge": "New arrival",
        "images": IMAGES["iphone"],
        "shortDescription": "256GB • Titanium • 5G • Pro camera system.",
        "tags": ["iphone", "apple", "mobile", "titanium", "5g", "pro"],
        "bundle": ["sony-wh1000xm5-accessories", "apple-watch-series-9-wearables", "nike-windbreaker-fashion"],
        "sales": 1243,
        "isNew": True,
        "addedOrder": 5,
    },
    {
        "id": "samsung-galaxy-s24-ultra-mobile",
        "title": "Samsung Galaxy S24 Ultra",
        "brand": "Samsung",
        "category": "Mobile",
        "currency": "USD",
        "priceValue": 1099,
        "discount": 10,
        "rating": 4.7,
        "reviewCount": 876,
        "stock": 15,
        "badge": "New arrival",
        "images": IMAGES["galaxy"],
        "shortDescription": "256GB • Snapdragon 8 Gen 3 • 200MP camera • S Pen.",
        "tags": ["samsung", "galaxy", "android", "s24", "5g", "spen"],
        "bundle": ["sony-wh1000xm5-accessories", "apple-watch-series-9-wearables", "jbl-flip-6-accessories"],
        "sales": 876,
        "isNew": True,
        "addedOrder": 6,
    },
    {
        "id": "macbook-air-m2-electronics",
        "title": "MacBook Air M2",
        "brand": "Apple",
        "category": "Electronics",
        "currency": "USD",
        "priceValue": 1399,
        "discount": 5,
        "rating": 4.9,
        "reviewCount": 689,
        "stock": 12,
        "badge": "Hot deal",
        "images": IMAGES["macbook"],
        "shortDescription": "16GB RAM • 512GB SSD • 13.6-inch Liquid Retina display.",
        "tags": ["apple", "macbook", "laptop", "m2", "electronics"],
        "bundle": ["sony-wh1000xm5-accessories", "jbl-flip-6-accessories", "iphone-15-pro-max-mobile"],
        "sales": 689,
        "isNew": False,
        "addedOrder": 7,
    },
    {
        "id": "apple-watch-series-9-wearables",
        "title": "Apple Watch Series 9",
        "brand": "Apple",
        "category": "Wearables",
        "currency": "USD",
        "priceValue": 249,
        "discount": 12,
        "rating": 4.7,
        "reviewCount": 512,
        "stock": 30,
        "badge": "Trending",
        "images": IMAGES["watch"],
        "shortDescription": "GPS • 45mm • Stainless steel • Health tracking.",
        "tags": ["apple", "watch", "wearable", "fitness", "smartwatch"],
        "bundle": ["iphone-15-pro-max-mobile", "sony-wh1000xm5-accessories", "samsung-galaxy-s24-ultra-mobile"],
        "sales": 512,
        "isNew": False,
        "addedOrder": 8,
    },
    {
        "id": "nike-windbreaker-fashion",
        "title": "Nike Windbreaker Jacket",
        "brand": "Nike",
        "category": "Fashion",
        "currency": "USD",
        "priceValue": 89,
        "discount": 20,
        "rating": 4.4,
        "reviewCount": 342,
        "stock": 45,
        "badge": "Style pick",
        "images": IMAGES["nike"],
        "shortDescription": "Water-resistant shell • Lightweight • Black and gray.",
        "tags": ["nike", "jacket", "fashion", "outdoor", "windbreaker"],
        "bundle": ["sony-wh1000xm5-accessories", "jbl-flip-6-accessories", "hyundai-creta-cars"],
        "sales": 342,
        "isNew": False,
        "addedOrder": 9,
    },
    {
        "id": "sony-wh1000xm5-accessories",
        "title": "Sony WH-1000XM5",
        "brand": "Sony",
        "category": "Accessories",
        "currency": "USD",
        "priceValue": 159,
        "discount": 15,
        "rating": 4.8,
        "reviewCount": 957,
        "stock": 40,
        "badge": "Audio favorite",
        "images": IMAGES["sony"],
        "shortDescription": "Noise cancelling • 30-hour battery • Comfort fit.",
        "tags": ["sony", "headphones", "audio", "anc", "noise-cancelling"],
        "bundle": ["jbl-flip-6-accessories", "macbook-air-m2-electronics", "iphone-15-pro-max-mobile"],
        "sales": 957,
        "isNew": False,
        "addedOrder": 10,
    },
    {
        "id": "sony-bravia-55-electronics",
        "title": 'Sony Bravia XR 55" 4K OLED TV',
        "brand": "Sony",
        "category": "Electronics",
        "currency": "USD",
        "priceValue": 1699,
        "discount": 18,
        "rating": 4.8,
        "reviewCount": 231,
        "stock": 8,
        "badge": "Hot deal",
        "images": IMAGES["bravia"],
        "shortDescription": "55-inch OLED • 4K HDR • Google TV • XR processor.",
        "tags": ["sony", "tv", "oled", "4k", "electronics", "google tv"],
        "bundle": ["jbl-flip-6-accessories", "sony-wh1000xm5-accessories", "macbook-air-m2-electronics"],
        "sales": 231,
        "isNew": False,
        "addedOrder": 11,
    },
    {
        "id": "jbl-flip-6-accessories",
        "title": "JBL Flip 6 Bluetooth Speaker",
        "brand": "JBL",
        "category": "Accessories",
        "currency": "USD",
        "priceValue": 129,
        "discount": 10,
        "rating": 4.6,
        "reviewCount": 415,
        "stock": 60,
        "badge": "Audio favorite",
        "images": IMAGES["jbl"],
        "shortDescription": "Portable waterproof speaker • 12-hour battery • Deep bass.",
        "tags": ["jbl", "speaker", "audio", "bluetooth", "portable"],
        "bundle": ["sony-wh1000xm5-accessories", "nike-windbreaker-fashion", "apple-watch-series-9-wearables"],
        "sales": 415,
        "isNew": False,
        "addedOrder": 12,
    },
]

# Explicit co-purchase relationships beyond the bundle lists above.
EXTRA_CO_PURCHASES = {
    "iphone-15-pro-max-mobile": [
        {"id": "apple-watch-series-9-wearables", "weight": 0.9},
        {"id": "sony-wh1000xm5-accessories", "weight": 0.8},
        {"id": "samsung-galaxy-s24-ultra-mobile", "weight": 0.3},
    ],
    "samsung-galaxy-s24-ultra-mobile": [
        {"id": "sony-wh1000xm5-accessories", "weight": 0.8},
        {"id": "jbl-flip-6-accessories", "weight": 0.6},
        {"id": "iphone-15-pro-max-mobile", "weight": 0.3},
    ],
    "macbook-air-m2-electronics": [
        {"id": "sony-wh1000xm5-accessories", "weight": 0.85},
        {"id": "sony-bravia-55-electronics", "weight": 0.4},
        {"id": "jbl-flip-6-accessories", "weight": 0.4},
    ],
    "sony-bravia-55-electronics": [
        {"id": "jbl-flip-6-accessories", "weight": 0.9},
        {"id": "sony-wh1000xm5-accessories", "weight": 0.6},
        {"id": "macbook-air-m2-electronics", "weight": 0.4},
    ],
    "toyota-corolla-altis-cars": [
        {"id": "honda-civic-cars", "weight": 0.7},
        {"id": "hyundai-creta-cars", "weight": 0.6},
    ],
    "toyota-prado-cars": [
        {"id": "hyundai-creta-cars", "weight": 0.6},
        {"id": "toyota-corolla-altis-cars", "weight": 0.4},
    ],
}


def _prep(catalog):
    """Derive stable fields shared by all products."""
    for p in catalog:
        p["imageUrl"] = p["images"][0]
        p["priceText"] = _price_text(p["priceValue"], p["currency"])
        p["originalPriceText"] = ""
        if p.get("discount", 0) > 0:
            original = int(round(p["priceValue"] / (1 - p["discount"] / 100.0)))
            p["originalPriceText"] = _price_text(original, p["currency"])
        p["popularity"] = round(p["rating"] * math.log1p(p["reviewCount"]), 4)
        p["trendingScore"] = round(p["popularity"] * (1.15 if p.get("isNew") else 1.0), 4)
        p["tokenized"] = (
            f"{p['title']} {p['brand']} {p['category']} {' '.join(p['tags'])}"
        ).lower()
    return catalog


class RecommendationEngine:
    """Hybrid recommender. Thread-safe for reads after __init__."""

    def __init__(self, catalog, car_values=None):
        self.catalog = _prep([dict(p) for p in catalog])
        self.by_id = {p["id"]: p for p in self.catalog}
        self.car_values = car_values or {}
        self._build_co_purchase()
        self._build_tfidf()
        self._build_co_view()

    # -- model construction -------------------------------------------------

    def _build_tfidf(self):
        corpus = [p["tokenized"] for p in self.catalog]
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform(corpus)
        self.sim = cosine_similarity(self.matrix)

    def _build_co_purchase(self):
        self.co_purchase = defaultdict(dict)
        for p in self.catalog:
            for other_id in p.get("bundle", []):
                if other_id in self.by_id:
                    self.co_purchase[p["id"]][other_id] = max(
                        self.co_purchase[p["id"]].get(other_id, 0.0), 1.0
                    )
        for pid, partners in EXTRA_CO_PURCHASES.items():
            for partner in partners:
                if partner["id"] in self.by_id:
                    self.co_purchase[pid][partner["id"]] = max(
                        self.co_purchase[pid].get(partner["id"], 0.0), partner["weight"]
                    )

    def _build_co_view(self):
        """Generate deterministic 'browsing sessions' and count co-views."""
        sessions = []
        for p in self.catalog:
            basket = [p["id"]]
            partners = list(self.co_purchase.get(p["id"], {}).items())
            if partners:
                basket.append(partners[0][0])
            category_mates = [q["id"] for q in self.catalog if q["category"] == p["category"] and q["id"] != p["id"]]
            if category_mates:
                basket.append(category_mates[len(p["id"]) % len(category_mates)])
            accessory = [q["id"] for q in self.catalog if q["category"] == "Accessories" and q["id"] != p["id"]]
            if accessory:
                basket.append(accessory[len(p["id"]) % len(accessory)])
            sessions.append(list(dict.fromkeys(basket)))

        co_view = defaultdict(lambda: defaultdict(int))
        for session in sessions:
            for i in range(len(session)):
                for j in range(len(session)):
                    if i != j:
                        co_view[session[i]][session[j]] += 1
        self.co_view = co_view

    # -- ranking helpers -----------------------------------------------------

    def _popularity(self, product_id):
        return self.by_id.get(product_id, {}).get("popularity", 0.0)

    def _value_score(self, product):
        if product["category"] == "Cars":
            return self.car_values.get(product["id"], {}).get("value_score", 0.0)
        return 0.0

    def _decay(self, timestamp, half_life_days=7.0):
        try:
            age_days = max(0.0, (time.time() - float(timestamp)) / 86400.0)
        except (TypeError, ValueError):
            age_days = 0.0
        return 0.5 ** (age_days / half_life_days)

    # -- section builders ----------------------------------------------------

    def similar(self, product_id, limit=6):
        idx = self.by_id.get(product_id)
        if idx is None:
            return []
        pos = self.catalog.index(idx)
        ranked = []
        for other_pos, other in enumerate(self.catalog):
            if other["id"] == product_id:
                continue
            score = float(self.sim[pos][other_pos])
            if score > 0.01:
                ranked.append((score, other))
        ranked.sort(key=lambda pair: (pair[0], pair[1]["trendingScore"]), reverse=True)
        return [other for _, other in ranked[:limit]]

    def frequently_bought(self, product_id, limit=4):
        partners = self.co_purchase.get(product_id, {})
        ranked = sorted(partners.items(), key=lambda pair: pair[1], reverse=True)
        return [self.by_id[pid] for pid, _ in ranked[:limit]]

    def also_viewed(self, product_id, limit=6):
        viewed = self.co_view.get(product_id, {})
        ranked = sorted(
            viewed.items(),
            key=lambda pair: (pair[1], self._popularity(pair[0])),
            reverse=True,
        )
        seen = {product_id}
        out = []
        for other_id, _count in ranked:
            other = self.by_id.get(other_id)
            if other and other["id"] not in seen:
                seen.add(other["id"])
                out.append(other)
            if len(out) >= limit:
                break

        if len(out) < limit:
            current = self.by_id.get(product_id)
            padding = []
            if current is not None:
                padding = [q for q in self.catalog if q["category"] == current["category"] and q["id"] != product_id]
            padding += [q for q in self.trending(12)]
            for extra in padding:
                if len(out) >= limit:
                    break
                if extra["id"] not in seen:
                    seen.add(extra["id"])
                    out.append(extra)
        return out[:limit]

    def trending(self, limit=8):
        ranked = sorted(
            self.catalog,
            key=lambda p: (p["trendingScore"], p["sales"]),
            reverse=True,
        )
        return ranked[:limit]

    def best_sellers(self, limit=8):
        ranked = sorted(
            self.catalog,
            key=lambda p: (p["sales"], p["rating"]),
            reverse=True,
        )
        return ranked[:limit]

    def new_arrivals(self, limit=8):
        arrivals = [p for p in self.catalog if p.get("isNew")]
        arrivals.sort(key=lambda p: (p["addedOrder"], p["trendingScore"]), reverse=True)
        return arrivals[:limit]

    # -- personalization -----------------------------------------------------

    def _profile_weights(self, signals):
        """Map signal events to per-product preference weights."""
        weights = defaultdict(float)
        signals = signals or {}

        for view in signals.get("views", [])[:50]:
            pid = view.get("id")
            if pid in self.by_id:
                weights[pid] += 0.6 * self._decay(view.get("at", 0))

        for wid in signals.get("wishlist", [])[:30]:
            if wid in self.by_id:
                weights[wid] += 1.0

        for cart in signals.get("cart", [])[:20]:
            pid = cart.get("id")
            if pid in self.by_id:
                weights[pid] += 1.2 * max(1, int(cart.get("qty", 1)))

        for pid in signals.get("purchases", [])[:50]:
            if pid in self.by_id:
                weights[pid] += 2.0

        for search in signals.get("searches", [])[:30]:
            query = str(search.get("q", "")).lower()
            decay = self._decay(search.get("at", 0))
            tokens = {t for t in query.split() if len(t) > 2}
            if not tokens:
                continue
            for p in self.catalog:
                haystack = set(p["tokenized"].split())
                if tokens & haystack:
                    weights[p["id"]] += 0.35 * decay

        return {pid: w for pid, w in weights.items() if pid in self.by_id}

    def personal(self, signals, limit=8, exclude=None):
        """Rank products against the user's profile with content similarity."""
        exclude = set(exclude or [])
        weights = self._profile_weights(signals)
        pos_index = {p["id"]: i for i, p in enumerate(self.catalog)}

        if not weights:
            return {
                "personalized": False,
                "reason": "Popular picks for you",
                "products": self.trending(limit),
            }

        weighted_sims = np.zeros(len(self.catalog))
        for pid, weight in weights.items():
            weighted_sims += weight * self.sim[pos_index[pid]]

        ranked = []
        for product in self.catalog:
            if product["id"] in exclude:
                continue
            pos = pos_index[product["id"]]
            content = float(weighted_sims[pos])
            popularity = 0.3 * product["popularity"] / max(
                max(p["popularity"] for p in self.catalog), 1e-9
            )
            value = 0.15 * max(0.0, min(1.0, (self._value_score(product) + 0.3) / 0.6))
            ranked.append((content + popularity + value, product))

        ranked.sort(key=lambda pair: (pair[0], pair[1]["trendingScore"]), reverse=True)
        top = [p for _, p in ranked[:limit]]

        reason = self._personal_reason(weights, top, pos_index)
        return {"personalized": True, "reason": reason, "products": top}

    def _personal_reason(self, weights, top, pos_index):
        if not top:
            return "Hand-picked for you"
        first = top[0]
        best_source = max(weights.items(), key=lambda pair: pair[1])[0]
        src = self.by_id.get(best_source)
        if src and src["id"] != first["id"]:
            return f"Because you were interested in {src['title']}"
        category = first["category"]
        return f"Because you like {category.lower()}"

    # -- serialization -------------------------------------------------------

    def serialize(self, product, reason=None, source=None):
        payload = {
            "id": product["id"],
            "title": product["title"],
            "brand": product["brand"],
            "category": product["category"],
            "currency": product["currency"],
            "priceValue": product["priceValue"],
            "priceText": product["priceText"],
            "originalPriceText": product["originalPriceText"],
            "discount": product["discount"],
            "rating": product["rating"],
            "reviewCount": product["reviewCount"],
            "stock": product["stock"],
            "badge": product["badge"],
            "imageUrl": product["imageUrl"],
            "images": product["images"],
            "shortDescription": product["shortDescription"],
            "tags": product["tags"],
            "popularity": product["popularity"],
            "sales": product.get("sales", 0),
            "isNew": product.get("isNew", False),
        }
        car_value = self.car_values.get(product["id"])
        if car_value is not None:
            payload["predictedPrice"] = car_value.get("predicted")
            payload["valueScore"] = round(car_value.get("value_score", 0.0), 4)
        if reason:
            payload["reason"] = reason
        if source:
            payload["source"] = source
        return payload

    def build_sections(self, context, signals, limit=8):
        """Assemble context-aware recommendation sections for one request."""
        ctx = context or {}
        product_id = ctx.get("productId")
        current = self.by_id.get(product_id) if product_id else None

        sections = {}

        personal = self.personal(signals, limit=limit, exclude=[product_id] if product_id else None)
        sections["recommended"] = {
            "title": "Recommended for You",
            "reason": personal["reason"],
            "personalized": personal["personalized"],
            "products": [self.serialize(p, source="personalized") for p in personal["products"]],
        }

        if current is not None:
            sections["similar"] = {
                "title": "Similar Products",
                "reason": "Products most similar to what you are viewing",
                "products": [
                    self.serialize(p, source="similar")
                    for p in self.similar(product_id, limit)
                ],
            }
            sections["also_viewed"] = {
                "title": "Customers Also Viewed",
                "reason": "Shoppers who viewed this item also looked at",
                "products": [
                    self.serialize(p, source="also_viewed")
                    for p in self.also_viewed(product_id, limit)
                ],
            }
            sections["frequently_bought"] = {
                "title": "Frequently Bought Together",
                "reason": "Customers who bought this item also bought",
                "products": [
                    self.serialize(p, source="frequently_bought")
                    for p in self.frequently_bought(product_id, 4)
                ],
            }

        if ctx.get("page") in (None, "", "home", "products"):
            sections["trending"] = {
                "title": "Trending Products",
                "reason": "What shoppers are buying right now",
                "products": [self.serialize(p, source="trending") for p in self.trending(limit)],
            }
            sections["best_sellers"] = {
                "title": "Best Sellers",
                "reason": "Our most popular products",
                "products": [self.serialize(p, source="best_seller") for p in self.best_sellers(limit)],
            }
            sections["new_arrivals"] = {
                "title": "New Arrivals",
                "reason": "Just added to the store",
                "products": [self.serialize(p, source="new_arrival") for p in self.new_arrivals(limit)],
            }

        return sections

    def all_products(self, limit=200):
        return [self.serialize(p) for p in self.catalog[:limit]]
