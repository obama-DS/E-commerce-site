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
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from recommend_engine import PRODUCTS

_log = logging.getLogger('assistant')

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

# Auth circuit breaker: when the provider keeps rejecting the key (401/403),
# stop hammering it for a short cooldown so chats fall back to the rule
# engine instantly instead of waiting out every retry.
_AUTH_BREAKER = {'fails': 0, 'until': 0.0}
_breaker_lock = threading.Lock()


def _report_auth_fail():
    with _breaker_lock:
        _AUTH_BREAKER['fails'] += 1
        cooldown = min(120, 4 * _AUTH_BREAKER['fails'])
        _AUTH_BREAKER['until'] = time.monotonic() + cooldown


def _report_auth_success():
    with _breaker_lock:
        _AUTH_BREAKER['fails'] = 0
        _AUTH_BREAKER['until'] = 0.0


def _llm_blocked() -> bool:
    with _breaker_lock:
        return bool(_AUTH_BREAKER['until']
                    and time.monotonic() < _AUTH_BREAKER['until'])


def _api_key() -> str:
    return (os.environ.get('OPENAI_API_KEY') or '').strip()

def _base_url() -> str:
    return (os.environ.get('OPENAI_BASE_URL')
            or 'https://api.openai.com/v1').strip().rstrip('/')

def _model() -> str:
    return (os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini').strip()

_DEFAULT_FALLBACK_MODELS = (
    'gemini-3-flash-preview',
    'gemini-3.1-flash-lite',
    'gemini-flash-lite-latest',
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
    'add to cart', 'show me', 'find me', 'look for', 'budget',
    'cheap', 'affordable', 'in stock', 'out of stock', 'on sale',
)

def _needs_tools(text: str) -> bool:
    """True when the message looks store-related."""
    lower = (text or '').lower()
    return any(hint in lower for hint in _STORE_HINTS)


# ---------------------------------------------------------------------------
# LLM HTTP call with model fallback chain
# ---------------------------------------------------------------------------

def _sleep(seconds: float, deadline=None):
    """Sleep without overshooting the caller's hard deadline."""
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        seconds = min(seconds, remaining)
    if seconds > 0:
        time.sleep(seconds)


def _chat_completion(messages, tools=None, attempts=3, deadline=None):
    timeout = float(os.environ.get('LLM_TIMEOUT', '30'))
    last_error = None
    for model in _models():
        if deadline is not None and time.monotonic() > deadline:
            break
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
            if deadline is not None and time.monotonic() > deadline:
                break
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
                    data = json.loads(resp.read().decode('utf-8'))
                    _report_auth_success()
                    return data
            except urllib.error.HTTPError as err:
                last_error = err
                if err.code in (401, 403):
                    # Auth rejection (e.g. flaky AQ keys at Google). One quick
                    # retry rides out transient glitches, then move on fast.
                    _report_auth_fail()
                    if attempt == 0:
                        _sleep(0.4, deadline)
                        continue
                    break
                if err.code == 429:
                    if attempt == attempts - 1:
                        break
                    _sleep(1 + attempt * 2, deadline)
                    continue
                if err.code == 404:
                    break          # model unavailable -> try next model
                if err.code == 408 or err.code >= 500:
                    if attempt == attempts - 1:
                        break
                    _sleep(1 + attempt * 2, deadline)
                    continue
                raise
            except (urllib.error.URLError, OSError) as err:
                last_error = err
                if attempt == attempts - 1:
                    break
                _sleep(1 + attempt * 2, deadline)
                continue
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError('LLM deadline exceeded')
    if last_error is not None:
        raise last_error
    raise RuntimeError('LLM call returned no result')


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
        if not isinstance(product, dict):
            continue
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
        if not isinstance(car, dict):
            continue
        title = str(car.get('title') or '')
        tags = ' '.join(str(t) for t in (car.get('tags') or []))
        haystack = ' '.join((title, tags)).lower()
        if needle in haystack or any(len(w) >= 3 and w in haystack for w in words):
            key = title.lower()
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
    cars = [c for c in cars if isinstance(c, dict)]
    if not cars:
        return []
    keyword = (keyword or '').strip().lower()
    if keyword:
        type_norm = _norm_filter(keyword, types=True)
        cars = [c for c in cars
                if keyword in f"{c.get('title', '')} {' '.join(str(t) for t in (c.get('tags') or []))}".lower()
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
        score = float(car.get('popularity', 0) or 0)
        if budget and float(car.get('price') or 0) <= budget:
            score += 5.0
        if str(car.get('fuel', '')).lower() == str(fuel).lower():
            score += 3.0
        if str(car.get('transmission', '')).lower() == str(transmission).lower():
            score += 3.0
        return score

    pool = [c for c in cars if float(c.get('price') or 0) <= budget] if budget else cars
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


# ---------------------------------------------------------------------------
# Store facts (exact — never invented by the model)
# ---------------------------------------------------------------------------

def _contact_text() -> str:
    c = _CONTACT
    return (
        f"- Phones: {c.get('phones', '')}\n"
        f"- Email: {c.get('email', '')}\n"
        f"- Developer: {c.get('developer', '')}\n"
        f"- City: {c.get('city', '')}"
    )

def _store_facts() -> dict:
    c = _CONTACT
    contact = (
        f"You can reach Obama Store at:\n- Phones: {c.get('phones', '')}\n"
        f"- Email: {c.get('email', '')}"
    )
    return {
        'contact': contact,
        'about': (
            f"Obama Store is an Ethiopian e-commerce platform created by "
            f"{c.get('developer', '')} in {c.get('city', '')}. It sells "
            f"electronics, mobile, fashion, wearables, accessories and "
            f"verified used cars, with every car priced against an ML "
            f"fair-price model. Contact: {c.get('phones', '')} / "
            f"{c.get('email', '')}"
        ),
        'payment': (
            "We accept Telebirr, CBE Pay, and cash on delivery. "
            "Mobile payments are processed securely at checkout."
        ),
        'delivery': (
            "We deliver across Ethiopia — Addis Ababa usually within "
            "1-3 business days, and other regions in 3-7 days. Delivery "
            "is confirmed with the customer before checkout."
        ),
        'returns': (
            "Easy returns: contact us within 7 days of delivery to arrange "
            "a return or exchange. Items must be in original condition with "
            "packaging."
        ),
        'hours': (
            "Support is available 24/7. Order processing runs "
            "Monday-Saturday, 9:00-18:00 (EAT)."
        ),
        'warranty': (
            "Every product includes the manufacturer warranty, and cars "
            "come with a verified-ownership guarantee. Anything defective "
            "on arrival is replaced or repaired free within 7 days."
        ),
        'orders': (
            "Orders can be tracked in My Account → Order History, or by "
            "replying with the order number. Orders usually update within "
            "minutes of shipping."
        ),
        'security': (
            "Payments are processed securely, products are checked for "
            "authenticity before dispatch, and customer data is never "
            "shared."
        ),
        'general': (
            f"Obama Store ({c.get('city', '')}) sells electronics, mobile, "
            f"fashion, wearables, accessories and verified used cars. "
            f"Phones: {c.get('phones', '')}. Email: {c.get('email', '')}. "
            "Accepts Telebirr, CBE Pay and cash on delivery. "
            "Delivery nationwide in 1-7 business days; returns within 7 days."
        ),
    }

_POLICY_TOPICS = {
    'contact':  ('contact', 'phone', 'call', 'email', 'reach', 'number', 'address', 'talk'),
    'about':    ('about', 'who made', 'developer', 'history', 'what is obama', 'about the store'),
    'payment':  ('pay', 'payment', 'telebirr', 'cbe', 'cash', 'mobile money'),
    'delivery': ('deliver', 'ship', 'shipping', 'how long', 'arrive', 'get here'),
    'returns':  ('return', 'refund', 'exchange', 'money back'),
    'hours':    ('hour', 'open', 'close', 'when', 'support'),
    'warranty': ('warranty', 'guarantee', 'defect', 'broken'),
    'orders':   ('order', 'track', 'status'),
    'security': ('secure', 'safe', 'trust', 'authentic', 'legit'),
}

# All categories in the store
_CATEGORIES = ['Cars', 'Electronics', 'Mobile', 'Fashion', 'Wearables', 'Accessories']


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

def _tool_schema(name, description, properties, required=None):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': properties,
                'required': required or [],
            },
        },
    }

TOOLS = [
    _tool_schema(
        'search_products',
        'Search the Obama Store catalogue for products or cars matching a '
        'keyword query. Returns items with title, price, category, stock, '
        'rating and a short description. Use this for any "do you have X" or '
        '"show me Y" question.',
        {'query': {'type': 'string',
                   'description': 'Keywords, e.g. "iPhone 15" or "Toyota SUV".'},
         'limit': {'type': 'integer',
                   'description': 'Max results to return (default 4, max 6).'}},
        ['query'],
    ),
    _tool_schema(
        'get_product_details',
        'Get full details for a specific product by its ID. Use after '
        'search_products to show more info about a particular item.',
        {'product_id': {'type': 'string',
                        'description': 'The product id from search_products, '
                                       'e.g. "iphone-15-pro-max-mobile".'}},
        ['product_id'],
    ),
    _tool_schema(
        'compare_products',
        'Compare two or three products side-by-side on price, rating, stock '
        'and key specs. Use when the user says "compare X and Y" or asks '
        '"which is better".',
        {'queries': {'type': 'array',
                     'items': {'type': 'string'},
                     'description': 'List of 2-3 product names or IDs to compare.'}},
        ['queries'],
    ),
    _tool_schema(
        'get_categories',
        'List all product categories available in the store, optionally with '
        'a product count per category. Use when the user asks "what do you sell" '
        'or "show me categories".',
        {},
    ),
    _tool_schema(
        'get_car_recommendations',
        'Recommend cars from the catalogue. Pass every filter the user '
        'mentioned: budget in ETB, body type (SUV/Sedan/Hatchback/MUV/Luxury), '
        'fuel (Petrol/Diesel/CNG/LPG/Electric/Hybrid), transmission '
        '(Manual/Automatic). Use "any" only for unspecified filters.',
        {
            'budget':       {'type': 'number',
                             'description': 'Max budget in ETB, e.g. 1500000.'},
            'type':         {'type': 'string',
                             'description': 'Body style: SUV, Sedan, Hatchback, MUV, Luxury, or any.'},
            'fuel':         {'type': 'string',
                             'description': 'Fuel: Petrol, Diesel, CNG, LPG, Electric, Hybrid, or any.'},
            'transmission': {'type': 'string',
                             'description': 'Transmission: Automatic, Manual, or any.'},
        },
    ),
    _tool_schema(
        'get_trending',
        'Get the currently trending / most popular products and cars.',
        {'category': {'type': 'string',
                      'description': 'Optional category filter, e.g. "Electronics".'}},
    ),
    _tool_schema(
        'search_knowledge',
        'Search the store knowledge base (uploaded FAQs, policies, documents). '
        'Returns the most relevant passages. Use for policy, support, or any '
        'question the other tools don\'t cover.',
        {'query': {'type': 'string',
                   'description': 'What to look up, e.g. "return policy".'}},
        ['query'],
    ),
    _tool_schema(
        'get_store_policy',
        'Get official store facts: contact, about, payment methods, delivery '
        'times, returns policy, business hours, warranty, order tracking, or '
        'security/trust info.',
        {'topic': {'type': 'string',
                   'enum': ['contact', 'about', 'payment', 'delivery', 'returns',
                            'hours', 'warranty', 'orders', 'security', 'general']}},
        ['topic'],
    ),
    _tool_schema(
        'add_to_cart',
        'Add a product to the user\'s cart by name. Searches the catalogue, '
        'finds the best match, and triggers the browser cart action.',
        {'query': {'type': 'string',
                   'description': 'Name of the item to add, e.g. "MacBook Air M2".'}},
        ['query'],
    ),
    _tool_schema(
        'get_cart_summary',
        'Return a summary of the items currently in the user\'s cart. '
        'Only works if the user has shared their cart contents in this session.',
        {},
    ),
    _tool_schema(
        'track_order',
        'Look up order status or tracking information for the user. '
        'Ask for an order number if the user hasn\'t provided one.',
        {'order_id': {'type': 'string',
                      'description': 'Order number provided by the user (optional).'}},
    ),
    _tool_schema(
        'get_order_help',
        'Provide help about how to place, track, cancel, or return an order. '
        'Use when the user asks general order questions without a specific ID.',
        {},
    ),
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {}

def _register(name):
    def decorator(fn):
        _TOOL_HANDLERS[name] = fn
        return fn
    return decorator


@_register('search_products')
def _h_search_products(args, session):
    limit = min(int(args.get('limit') or 4), 6)
    hits = _search_products(str(args.get('query') or ''), limit=limit)
    if not hits:
        return ('No items found matching that query.', [])
    lines = ['Search results:'] + [f"- {_product_line(h)}" for h in hits]
    # remember last search context for follow-ups
    session['last_search_results'] = [h.get('id') or h.get('title') for h in hits]
    return ('\n'.join(lines), [_hit_card(h) for h in hits])


@_register('get_product_details')
def _h_product_details(args, session):
    pid = str(args.get('product_id') or '').strip()
    product = _get_product_by_id(pid)
    if not product:
        # try fuzzy search as fallback
        hits = _search_products(pid, limit=1)
        if hits:
            product = hits[0] if hits[0].get('priceValue') is not None else None
    if not product:
        return (f'No product found with id "{pid}".', [])
    tags = ', '.join(product.get('tags') or [])
    bundle = product.get('bundle') or []
    bundle_titles = []
    for bid in bundle[:3]:
        bp = _get_product_by_id(bid)
        if bp:
            bundle_titles.append(bp.get('title', bid))
    detail = (
        f"**{product.get('title')}**\n"
        f"Category: {product.get('category')}\n"
        f"Price: {_product_price(product)}"
        + (f" ({product.get('discount')}% off)" if product.get('discount') else '') + "\n"
        f"Rating: {product.get('rating', 'N/A')} ({product.get('reviewCount', 0)} reviews)\n"
        f"Stock: {product.get('stock', 'N/A')} units\n"
        f"Description: {product.get('shortDescription', '')}\n"
        f"Tags: {tags}\n"
        + (f"Often bought with: {', '.join(bundle_titles)}" if bundle_titles else '')
    )
    return (detail.strip(), [_product_card(product)])


@_register('compare_products')
def _h_compare_products(args, session):
    queries = args.get('queries') or []
    if not queries or len(queries) < 2:
        return ('Please provide at least 2 products to compare.', [])
    products = []
    for q in queries[:3]:
        hits = _search_products(str(q), limit=1)
        if hits and hits[0].get('priceValue') is not None:
            products.append(hits[0])
    if len(products) < 2:
        return ('Could not find enough products to compare.', [])

    # build comparison table data
    fields = ['title', 'category', 'priceText', 'rating', 'reviewCount',
              'discount', 'stock', 'shortDescription']
    rows = []
    for p in products:
        rows.append({
            'title': p.get('title', ''),
            'category': p.get('category', ''),
            'priceText': _product_price(p),
            'rating': str(p.get('rating', 'N/A')),
            'reviewCount': str(p.get('reviewCount', 0)),
            'discount': f"{p.get('discount', 0)}%",
            'stock': str(p.get('stock', 'N/A')),
            'shortDescription': p.get('shortDescription', ''),
        })

    # text summary for the LLM
    lines = ['**Product Comparison**']
    label_map = {
        'priceText': 'Price', 'rating': 'Rating', 'reviewCount': 'Reviews',
        'discount': 'Discount', 'stock': 'Stock', 'shortDescription': 'Description',
    }
    for field in ['priceText', 'rating', 'reviewCount', 'discount', 'stock', 'shortDescription']:
        label = label_map.get(field, field)
        vals = ' | '.join(r[field] for r in rows)
        lines.append(f"- **{label}:** {vals}")

    cards = [_product_card(p) for p in products]
    compare_card = {
        'type': 'compare',
        'products': [
            {
                'id': p.get('id', ''),
                'title': p.get('title', ''),
                'priceText': _product_price(p),
                'rating': p.get('rating'),
                'reviewCount': p.get('reviewCount'),
                'discount': p.get('discount', 0),
                'stock': p.get('stock'),
                'image': (p.get('images') or [''])[0],
                'shortDescription': p.get('shortDescription', ''),
                'badge': p.get('badge', ''),
            }
            for p in products
        ],
    }
    # return both individual cards AND a compare card
    return ('\n'.join(lines), [compare_card] + cards)


@_register('get_categories')
def _h_get_categories(args, session):
    counts = {}
    for p in PRODUCTS:
        cat = p.get('category', 'Other')
        counts[cat] = counts.get(cat, 0) + 1
    lines = ['**Store Categories:**']
    cat_cards = []
    for cat in _CATEGORIES:
        count = counts.get(cat, 0)
        lines.append(f"- **{cat}** ({count} items)" if count else f"- {cat}")
        cat_cards.append({'name': cat, 'count': count})
    categories_card = {'type': 'categories', 'categories': cat_cards}
    return ('\n'.join(lines), [categories_card])


@_register('get_car_recommendations')
def _h_car_recommendations(args, session):
    budget = args.get('budget')
    if budget is not None:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            budget = None
    if budget and 0 < budget < 100_000:
        budget = None  # ETB amounts under 100k are probably USD confusion
    fuel = str(args.get('fuel') or 'any')
    transmission = str(args.get('transmission') or 'any')
    car_type = str(args.get('type') or 'any')
    keyword = str(args.get('keyword') or car_type).strip()

    fuel_norm = _norm_filter(fuel)
    trans_norm = _norm_filter(transmission)
    type_norm = _norm_filter(car_type, types=True)

    cars = _recommend_cars(budget, fuel_norm, trans_norm, keyword or type_norm)
    if cars:
        lines = [
            f"- {c.get('title')} ({_fmt_money(c.get('price'))}) · {c.get('fuel', '')} · "
            f"{c.get('transmission', '')} · {c.get('year', '')}"
            for c in cars
        ]
        session['last_car_results'] = [c.get('title') for c in cars]
        return ('\n'.join(lines), [_car_card(c) for c in cars])

    # Graceful fallback: relax filters one at a time
    relaxed = _recommend_cars(budget, 'any', trans_norm, keyword or type_norm)
    if not relaxed:
        relaxed = _recommend_cars(budget, 'any', 'any', keyword or type_norm)
    if not relaxed:
        relaxed = _recommend_cars(None, 'any', 'any')
    if not relaxed:
        return ('No cars match those criteria right now.', [])
    labels = []
    if fuel_norm != 'any':
        labels.append(f"in {fuel_norm}")
    if trans_norm != 'any':
        labels.append(f"with {trans_norm} transmission")
    if (keyword or type_norm) not in ('', 'any'):
        labels.append(f"of type {keyword or type_norm}")
    label_str = 'for ' + ' '.join(labels) if labels else ''
    lines = [
        f"- {c.get('title')} ({_fmt_money(c.get('price'))}) · {c.get('fuel', '')} · "
        f"{c.get('transmission', '')} · {c.get('year', '')}"
        for c in relaxed
    ]
    session['last_car_results'] = [c.get('title') for c in relaxed]
    return (
        f"Couldn't find an exact match {label_str} right now. "
        f"Here are the closest options:\n" + '\n'.join(lines),
        [_car_card(c) for c in relaxed],
    )


@_register('get_trending')
def _h_trending(args, session):
    category = str(args.get('category') or '').strip().lower()
    # Trending products from PRODUCTS
    product_pool = sorted(
        PRODUCTS,
        key=lambda p: float(p.get('rating', 0)) * (p.get('reviewCount', 0) ** 0.5),
        reverse=True,
    )
    if category:
        product_pool = [p for p in product_pool
                        if p.get('category', '').lower() == category]
    top_products = product_pool[:3]
    # Trending cars from catalog
    top_cars = sorted(
        _car_catalog(),
        key=lambda c: (c.get('popularity', 0), -c.get('car_age', 0)),
        reverse=True,
    )[:2]
    cards = [_product_card(p) for p in top_products] + [_car_card(c) for c in top_cars]
    if not cards:
        return ('Trending data is unavailable right now.', [])
    lines = (
        ['**Trending Products:**']
        + [f"- {p.get('title')} — {_product_price(p)}" for p in top_products]
        + (['**Trending Cars:**']
           + [f"- {c.get('title')} ({_fmt_money(c.get('price'))})" for c in top_cars]
           if top_cars else [])
    )
    return ('\n'.join(lines), cards)


@_register('search_knowledge')
def _h_search_knowledge(args, session):
    query = str(args.get('query') or '').strip()
    results = _kb_search(query, limit=3)
    if not results:
        return ('No knowledge base matches found.', [])
    lines = []
    for r in results:
        title = r.get('title') or 'FAQ'
        content = str(r.get('content') or '')[:600].strip()
        lines.append(f"**{title}**\n{content}")
    return ('\n\n'.join(lines), [])


@_register('get_store_policy')
def _h_store_policy(args, session):
    topic = str(args.get('topic') or '').lower()
    facts = _store_facts()
    key = None
    for name, words in _POLICY_TOPICS.items():
        if any(w in topic for w in words):
            key = name
            break
    return (facts.get(key) or facts['general'], [])


@_register('add_to_cart')
def _h_add_to_cart(args, session):
    query = str(args.get('query') or '').strip()
    hits = _search_products(query, limit=1)
    if not hits:
        return (f'No product found matching "{query}".', [])
    top = hits[0]
    # Only add actual products (not cars) to cart
    if top.get('priceValue') is None:
        return ('Cars are not added to a cart — please contact us to inquire about a car.', [])
    card = _product_card(top)
    title = top.get('title', '?')
    price_text = card.get('priceText') or ''
    action = {
        'type': 'add_to_cart',
        'title': title,
        'priceText': price_text,
        'productId': top.get('id', ''),
        'openProduct': True,
    }
    session.setdefault('cart_items', [])
    # Track cart in session for get_cart_summary
    existing = next((i for i in session['cart_items']
                     if i['id'] == top.get('id')), None)
    if existing:
        existing['qty'] = existing.get('qty', 1) + 1
    else:
        session['cart_items'].append({
            'id': top.get('id', ''),
            'title': title,
            'priceText': price_text,
            'qty': 1,
        })
    session.setdefault('ai_pending_actions', []).append(action)
    return (
        f"Added **{title}** ({price_text}) to your cart. ✅",
        [card],
    )


@_register('get_cart_summary')
def _h_cart_summary(args, session):
    items = session.get('cart_items') or []
    if not items:
        return (
            "Your cart appears to be empty — or you haven't added anything "
            "through our chat yet. Browse products and say \"add X to cart\"!",
            [],
        )
    lines = ['**Your cart:**']
    for item in items:
        qty = item.get('qty', 1)
        lines.append(f"- {item['title']} × {qty}  ({item['priceText']})")
    return ('\n'.join(lines), [])


@_register('track_order')
def _h_track_order(args, session):
    order_id = str(args.get('order_id') or '').strip()
    if not order_id:
        return (
            "Please share your order number (e.g. ORD-12345) and I'll look "
            "it up for you. You can also find all orders in "
            "**My Account → Order History**.",
            [],
        )
    # No real order DB — give a helpful response with instructions
    return (
        f"I don't have live order data access yet, but here's how to track "
        f"order **{order_id}**:\n"
        "1. Go to **My Account → Order History**\n"
        "2. Find the order and click **Track**\n"
        "3. Or contact us directly:\n"
        + _contact_text(),
        [],
    )


@_register('get_order_help')
def _h_order_help(args, session):
    return (
        "Here's everything about orders at Obama Store:\n\n"
        "**Placing an order:** Add items to cart, go to checkout, choose "
        "Telebirr / CBE Pay / Cash on Delivery.\n\n"
        "**Tracking:** My Account → Order History, or share your order "
        "number here.\n\n"
        "**Cancellation:** Contact us within 24 hours of placing the order.\n\n"
        "**Returns:** Within 7 days of delivery — item must be in original "
        "condition.\n\n"
        "**Contact:** " + _contact_text(),
        [],
    )


def _run_tool(name, arguments, session):
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return ('Unknown tool.', [])
    try:
        text, cards = handler(arguments, session)
        return (str(text), cards)
    except Exception as exc:
        return (f'Tool error: {exc}', [])


# ---------------------------------------------------------------------------
# RAG retrieval — injects relevant store data into every prompt
# ---------------------------------------------------------------------------

def _retrieve(text: str) -> list:
    """Pull relevant KB chunks + catalogue hits — only for store-related messages."""
    # Skip retrieval entirely for pure general-knowledge questions
    if not _needs_tools(text):
        return []
    context = []
    # KB search (documents, FAQs, uploaded content)
    for result in _kb_search(text, limit=2):
        title = result.get('title') or 'FAQ'
        content = str(result.get('content') or '')[:500].strip()
        if content:
            context.append(f"[Knowledge] {title}: {content}")
    # Catalogue search (products + cars)
    for hit in _search_products(text, limit=4):
        context.append(f"[Catalogue] {_product_line(hit)}")
    # Store policy topics — auto-inject relevant policy text
    lower = text.lower()
    facts = _store_facts()
    for key, words in _POLICY_TOPICS.items():
        if any(w in lower for w in words):
            context.append(f"[Policy/{key.title()}] {facts[key]}")
            break  # one policy section is enough
    return context


# ---------------------------------------------------------------------------
# System prompt — rich, grounded, action-oriented
# ---------------------------------------------------------------------------

def _system_prompt(context: list) -> str:
    store_knowledge = '\n'.join(context) if context else '(none retrieved)'
    facts = _store_facts()
    categories = ', '.join(_CATEGORIES)
    return (
        "You are **Obama**, the AI-powered assistant for Obama Store — an Ethiopian "
        f"e-commerce platform built by {_CONTACT.get('developer', 'Obama Abraham')} "
        f"in {_CONTACT.get('city', 'Addis Ababa, Ethiopia')}.\n\n"

        "## Your personality\n"
        "Friendly, knowledgeable, and concise. Warm like a helpful shop assistant. "
        "Respond in the same language the user writes in (Amharic, English, etc.). "
        "Use markdown formatting (bold, bullet lists) to structure longer answers.\n\n"

        "## How to answer\n"
        "1. **Store questions** (products, prices, stock, cars, policies, cart, orders, "
        "contact, payment, delivery): ALWAYS use the tools to get real data. "
        "Never invent prices, stock levels, or policies.\n"
        "2. **General questions** (science, history, how-to, coding, casual chat): "
        "answer from your own knowledge normally — no need for tools.\n"
        "3. **Follow-ups**: use the conversation history to resolve references like "
        "'the cheaper one', 'that phone', or 'it'. The context window contains "
        "recent turns — use them.\n"
        "4. **Comparisons**: when asked to compare products, call compare_products.\n"
        "5. **Car recommendations**: always call get_car_recommendations and fill "
        "every filter the user mentioned (budget in ETB, type, fuel, transmission). "
        "Use 'any' only for filters not mentioned.\n"
        "6. **Adding to cart**: call add_to_cart; the browser will handle the UI.\n"
        "7. **Orders**: use track_order if the user gives an order number, otherwise "
        "get_order_help.\n\n"

        f"## Store categories\n{categories}\n\n"

        "## Retrieved store records (use these — don't contradict them)\n"
        + store_knowledge +

        "\n\n## Store contact (always accurate — never change)\n"
        + _contact_text() +

        "\n\n## General store policy\n"
        + facts['general'] +

        "\n\n## Response length\n"
        "2-5 sentences for simple questions. Use bullet lists for specs or multiple "
        "items. Only be verbose when the user explicitly asks for details."
    )


# ---------------------------------------------------------------------------
# Conversation memory — per-session with slot tracking
# ---------------------------------------------------------------------------

def _summarize_if_long(memory: list) -> list:
    """Keep memory manageable. Trim to last 18 turns (9 pairs)."""
    # Only keep user/assistant turns (no tool calls) for long-term memory
    clean = [m for m in memory
             if m.get('role') in ('user', 'assistant')
             and not m.get('tool_calls')
             and m.get('content')]
    # Drop any trailing user turn that never got an assistant reply, so the
    # LLM never sees consecutive unbalanced user messages.
    while clean and clean[-1].get('role') == 'user':
        clean.pop()
    return clean[-18:]


def _build_messages(session, message: str, client_history: list) -> list:
    """Build the message list for this turn, merging server memory + client history.

    Returns a new list; does NOT mutate the session. The caller (answer)
    persists `session['ai_messages']` only on a successful LLM turn so a
    failed/fallback turn never pollutes memory.
    """
    memory = session.get('ai_messages')
    if not memory:
        # First turn in this session — bootstrap from client-side history
        memory = []
        for item in (client_history or [])[-16:]:
            role = item.get('role')
            if role in ('user', 'assistant') and item.get('content'):
                memory.append({'role': role,
                                'content': str(item['content'])[:3000]})
    memory = _summarize_if_long(memory)
    # Avoid duplicating the last message
    if not memory or memory[-1].get('content') != message:
        memory.append({'role': 'user', 'content': message[:4000]})
    return memory


# ---------------------------------------------------------------------------
# Smart suggestions based on response context
# ---------------------------------------------------------------------------

def _suggestions(store_related: bool, cards: list) -> list:
    has_cars = any(c.get('type') == 'car' for c in cards)
    has_products = any(c.get('type') == 'product' for c in cards)
    if has_cars:
        return ['Show me more cars', 'What are your best deals?', 'Contact us']
    if has_products:
        return ['Add to cart', 'Compare products', 'What else do you sell?']
    if store_related:
        return ['Recommend a car', "What's trending?", 'Contact us']
    return ['Recommend a car', 'Tell me about the store', 'What can you do?']


def _dedupe_cards(cards: list) -> list:
    seen = set()
    out = []
    for card in cards:
        key = (card.get('type'), card.get('id') or card.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def answer(message, session, client_history):
    """Run one AI turn. Returns response dict or None (fallback to rule engine)."""
    if not enabled():
        return None
    message = (message or '').strip()
    if not message:
        return None

    deadline = time.monotonic() + float(os.environ.get('LLM_MAX_SECONDS', '60'))
    try:
        memory = _build_messages(session, message, client_history)
        context = _retrieve(message)
    except Exception as exc:
        _log.warning('assistant pre-turn failed: %r', exc)
        return None
    messages = [{'role': 'system', 'content': _system_prompt(context)}] + memory
    session.setdefault('ai_pending_actions', [])

    collected_cards = []
    reply = ''

    # Agentic loop: up to 4 rounds of tool-calling
    for _round in range(4):
        if time.monotonic() > deadline:
            break
        try:
            tools = TOOLS if _needs_tools(message) else None
            response = _chat_completion(messages, tools=tools, deadline=deadline)
        except Exception as exc:
            _log.warning('LLM call failed (round %d): %r', _round, exc)
            return None
        choice = (response.get('choices') or [{}])[0]
        choice_msg = choice.get('message') or {}
        tool_calls = choice_msg.get('tool_calls')

        if not tool_calls:
            reply = (choice_msg.get('content') or '').strip()
            break

        # Execute all tool calls in this round
        messages.append({
            'role': 'assistant',
            'content': choice_msg.get('content') or '',
            'tool_calls': tool_calls,
        })
        for call in tool_calls:
            fn = call.get('function') or {}
            name = fn.get('name') or ''
            try:
                arguments = json.loads(fn.get('arguments') or '{}')
            except ValueError:
                arguments = {}
            text, cards = _run_tool(name, arguments, session)
            collected_cards.extend(cards)
            messages.append({
                'role': 'tool',
                'tool_call_id': call.get('id', ''),
                'content': text[:3000],
            })
    else:
        return None

    if not reply:
        return None

    # Persist memory: only user+assistant turns, no tool plumbing
    messages.append({'role': 'assistant', 'content': reply})
    session['ai_messages'] = _summarize_if_long(messages)

    actions = session.pop('ai_pending_actions', []) or []
    action = actions[-1] if actions else None
    store_related = bool(context or collected_cards)
    deduped = _dedupe_cards(collected_cards)[:8]

    return {
        'reply': reply,
        'suggestions': _suggestions(store_related, deduped),
        'cards': deduped,
        'flow': None,
        'action': action,
    }
