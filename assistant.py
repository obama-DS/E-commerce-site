"""
assistant.py — hybrid AI brain for the Obama Store chatbot.

Combines:
* LLM (OpenAI-compatible)  — main brain for general + store questions
* Conversation memory       — per-session history with slot tracking so
                              follow-ups like "the cheaper one" resolve
* RAG retrieval             — products, KB chunks and store facts injected
                              into every store-related prompt automatically
* Tool / function calling   — model can invoke real store actions:
                              search_products, get_product_details,
                              compare_products, get_car_recommendations,
                              get_trending, search_knowledge,
                              get_store_policy, get_categories,
                              add_to_cart, get_cart_summary,
                              track_order, get_order_help

Add a new tool: append a schema to TOOLS and a handler with @_register.
Falls back to None on any error so app.py can use the rule engine.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from recommend_engine import PRODUCTS

# ---------------------------------------------------------------------------
# Runtime wiring (injected from app.py at startup)
# ---------------------------------------------------------------------------
_car_catalog_getter = lambda: []  # noqa: E731
_kb = None
_CONTACT = {}
_recommend_cars_fn = None


def configure(car_catalog_getter=None, kb=None, contact=None,
              recommend_cars_fn=None):
    """Inject store runtime objects. Called once from app.py startup."""
    global _car_catalog_getter, _kb, _CONTACT, _recommend_cars_fn
    _car_catalog_getter = car_catalog_getter or (lambda: [])
    _kb = kb
    _CONTACT = contact or {}
    _recommend_cars_fn = recommend_cars_fn


def _car_catalog():
    try:
        return _car_catalog_getter() or []
    except Exception:
        return []

    
# ---------------------------------------------------------------------------
# LLM configuration (env vars)
# ---------------------------------------------------------------------------

def _api_key() -> str:
    return (os.environ.get('OPENAI_API_KEY') or '').strip()

def _base_url() -> str:
    return (os.environ.get('OPENAI_BASE_URL')
            or 'https://api.openai.com/v1').strip().rstrip('/')

def _model() -> str:
    return (os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini').strip()

_DEFAULT_FALLBACK_MODELS = (
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
    'gemini-1.5-flash',
    'gpt-4o-mini',
)

def _models() -> list:
    """Primary model plus fallbacks for quota rotation."""
    chain = [_model()]
    chain += [m.strip() for m in
              (os.environ.get('OPENAI_FALLBACK_MODELS') or '').split(',')
              if m.strip()]
    chain += list(_DEFAULT_FALLBACK_MODELS)
    seen = set()
    out = []
    for model in chain:
        if model and model not in seen:
            seen.add(model)
            out.append(model)
    return out

def enabled() -> bool:
    return bool(_api_key())

# ---------------------------------------------------------------------------
# Store-related keyword routing
# ---------------------------------------------------------------------------

_STORE_HINTS = (
    'product', 'price', 'cost', 'buy', 'purchase', 'order', 'cart', 'stock',
    'car', 'vehicle', 'suv', 'sedan', 'toyota', 'recommend', 'trending',
    'deliver', 'ship', 'return', 'refund', 'pay', 'payment', 'contact',
    'phone', 'email', 'warranty', 'discount', 'deal', 'offer', 'policy',
    'sell', 'store', 'knowledge', 'faq', 'watch', 'iphone', 'macbook',
    'galaxy', 'sony', 'jbl', 'bravia', 'headphone', 'laptop', 'telebirr',
    'cbe', 'hours', 'open', 'closed', 'about', 'track', 'help', 'obama',
    'inventory', 'available', 'spec', 'feature', 'brand', 'model',
    'category', 'categories', 'compare', 'checkout', 'wishlist', 'samsung',
    'apple', 'nike', 'fashion', 'electronic', 'accessories', 'wearable',
    'add to cart', 'show me', 'find me', 'search', 'look for', 'budget',
    'cheap', 'expensive', 'affordable', 'best', 'top', 'latest', 'new',
)

def _needs_tools(text: str) -> bool:
    """True when the message looks store-related."""
    lower = (text or '').lower()
    return any(hint in lower for hint in _STORE_HINTS)


# ---------------------------------------------------------------------------
# LLM HTTP call with model fallback chain
# ---------------------------------------------------------------------------

def _chat_completion(messages, tools=None, attempts=2):
    timeout = float(os.environ.get('LLM_TIMEOUT', '30'))
    last_error = None
    for model in _models():
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.45,
            'max_tokens': 1200,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        body = json.dumps(payload).encode('utf-8')
        for attempt in range(attempts):
            req = urllib.request.Request(
                _base_url() + '/chat/completions',
                data=body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + _api_key(),
                },
                method='POST',
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as err:
                last_error = err
                if err.code in (404, 429):
                    break          # try next model
                if err.code == 408 or err.code >= 500:
                    if attempt == attempts - 1:
                        break
                    time.sleep(1 + attempt * 2)
                    continue
                raise
            except (urllib.error.URLError, OSError) as err:
                last_error = err
                if attempt == attempts - 1:
                    break
                time.sleep(1 + attempt * 2)
                continue
    raise last_error  # pragma: no cover


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_money(value) -> str:
    try:
        return f"ETB {int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value or 0)

def _product_price(product: dict) -> str:
    currency = product.get('currency', 'ETB')
    value = product.get('priceValue')
    if value is None:
        return _fmt_money(product.get('price'))
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 'ETB 0'
    if currency == 'ETB':
        return f"ETB {int(round(numeric)):,}"
    return f"${numeric:,.2f}"

def _product_card(product: dict) -> dict:
    images = product.get('images') or []
    return {
        'type': 'product',
        'id': product.get('id', ''),
        'title': product.get('title', ''),
        'category': product.get('category', ''),
        'badge': product.get('badge', ''),
        'priceText': _product_price(product),
        'currency': product.get('currency', 'ETB'),
        'rating': product.get('rating'),
        'reviewCount': product.get('reviewCount'),
        'discount': product.get('discount', 0),
        'stock': product.get('stock'),
        'image': images[0] if images else '',
        'shortDescription': product.get('shortDescription', ''),
    }

def _car_card(car: dict) -> dict:
    price = car.get('price') or 0
    pred = car.get('predicted_price') or 0
    value_tag = ''
    if pred and price:
        ratio = price / max(pred, 1)
        value_tag = ('Great deal' if ratio < 0.95
                     else 'Fair price' if ratio <= 1.05
                     else 'Priced high')
    return {
        'type': 'car',
        'title': car.get('title', ''),
        'carType': car.get('type', ''),
        'year': car.get('year'),
        'priceText': _fmt_money(price),
        'fuel': car.get('fuel', ''),
        'transmission': car.get('transmission', ''),
        'km': car.get('km'),
        'valueTag': value_tag,
        'predictedText': _fmt_money(pred),
        'owner': car.get('owner', ''),
        'sellerType': car.get('seller_type', ''),
        'image': car.get('imageUrl') or car.get('fallbackImage') or '',
    }

def _hit_card(hit: dict) -> dict:
    if hit.get('priceValue') is not None:
        return _product_card(hit)
    return _car_card(hit)

def _product_line(hit: dict) -> str:
    title = hit.get('title', '?')
    if hit.get('priceValue') is not None:
        price = _product_price(hit)
        kind = hit.get('category', '')
        stock = hit.get('stock')
        stock_txt = f", stock {stock}" if stock is not None else ''
        desc = hit.get('shortDescription', '')
        desc_txt = f", {desc}" if desc else ''
        return f"{title} ({kind}) {price}{stock_txt}{desc_txt}, id={hit.get('id', '')}"
    price = _fmt_money(hit.get('price'))
    kind = hit.get('fuel', '')
    return f"{title} ({kind}) {price}"


# ---------------------------------------------------------------------------
# Product / car search helpers
# ---------------------------------------------------------------------------

def _search_products(query: str, limit: int = 5):
    if not query:
        return []
    needle = query.lower()
    words = [w for w in needle.split() if len(w) > 1]
    hits = []
    seen = set()
    for product in PRODUCTS:
        haystack = ' '.join(str(x) for x in (
            product.get('title'), product.get('category'),
            product.get('tags'), product.get('shortDescription'),
            product.get('brand'),
        )).lower()
        if needle in haystack or any(len(w) >= 3 and w in haystack for w in words):
            key = str(product.get('title')).lower()
            if key not in seen:
                seen.add(key)
                hits.append(product)
    for car in _car_catalog():
        haystack = ' '.join((car['title'], car['tags'])).lower()
        if needle in haystack or any(len(w) >= 3 and w in haystack for w in words):
            key = car['title'].lower()
            if key not in seen:
                seen.add(key)
                hits.append(car)
        if len(hits) >= limit:
            break
    return hits[:limit]

def _get_product_by_id(product_id: str):
    """Return a single product by its id."""
    pid = (product_id or '').lower().strip()
    for p in PRODUCTS:
        if (p.get('id') or '').lower() == pid:
            return p
    return None

def _recommend_cars(budget, fuel='any', transmission='any', keyword=''):
    if _recommend_cars_fn is not None:
        try:
            return _recommend_cars_fn(budget, fuel, transmission, keyword) or []
        except TypeError:
            return _recommend_cars_fn(budget, fuel, transmission) or []
    cars = _car_catalog()
    if not cars:
        return []
    keyword = (keyword or '').strip().lower()
    if keyword:
        type_norm = _norm_filter(keyword, types=True)
        cars = [c for c in cars
                if keyword in f"{c['title']} {c['tags']}".lower()
                or (type_norm != 'any'
                    and str(c.get('type') or '').lower() == type_norm.lower())]
        if not cars:
            return []
    if fuel != 'any':
        cars = [c for c in cars if str(c.get('fuel', '')).lower() == fuel.lower()]
        if not cars:
            return []
    if transmission != 'any':
        cars = [c for c in cars
                if str(c.get('transmission', '')).lower() == transmission.lower()]
        if not cars:
            return []

    def rank(car):
        score = float(car.get('popularity', 0))
        if budget and car['price'] <= budget:
            score += 5.0
        if str(car.get('fuel', '')).lower() == str(fuel).lower():
            score += 3.0
        if str(car.get('transmission', '')).lower() == str(transmission).lower():
            score += 3.0
        return score

    pool = [c for c in cars if c['price'] <= budget] if budget else cars
    pool = pool or cars
    return sorted(pool, key=rank, reverse=True)[:3]

_FILTER_CHOICES = (
    'Petrol', 'Diesel', 'CNG', 'LPG', 'Electric', 'Hybrid',
    'Manual', 'Automatic', 'SUV', 'Sedan', 'Hatchback', 'MUV', 'Luxury',
)

def _norm_filter(value, types=False):
    if not value:
        return 'any'
    cleaned = ' '.join(str(value).lower().split())
    if (cleaned in ('', 'any', 'all', 'both')
            or cleaned.startswith('any') or cleaned.startswith('all')
            or cleaned.startswith('no ') or 'no preference' in cleaned):
        return 'any'
    for choice in _FILTER_CHOICES:
        if choice.lower() in cleaned or cleaned in choice.lower():
            return choice
    synonyms = {
        'auto': 'Automatic', 'at': 'Automatic', 'cvt': 'Automatic',
        'manual': 'Manual', 'mt': 'Manual',
        'gasoline': 'Petrol', 'gas': 'Petrol',
        'ev': 'Electric', 'evs': 'Electric',
        'suv': 'SUV', 'suvs': 'SUV', '4x4': 'SUV', 'off-road': 'SUV',
        'sedan': 'Sedan', 'sedans': 'Sedan', 'saloon': 'Sedan',
        'hatch': 'Hatchback', 'hatchback': 'Hatchback',
        'mpv': 'MUV', 'muv': 'MUV', 'van': 'MUV', 'minivan': 'MUV',
        'luxury': 'Luxury', 'premium': 'Luxury',
    }
    return synonyms.get(cleaned, cleaned.title() if types else 'any')

def _kb_search(query: str, limit: int = 3):
    if _kb is None:
        return []
    try:
        return _kb.search(query, limit=limit) or []
    except Exception:
        return []

