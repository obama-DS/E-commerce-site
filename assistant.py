"""
assistant.py — modular AI brain for the Obama Store chatbot.

The assistant sits in front of the deterministic intent engine. When a
valid OPENAI_API_KEY is configured it answers every message through an
OpenAI-compatible chat-completions API (OpenAI, Groq, OpenRouter, local
gateways...), combining:

* general knowledge  — the model answers open-domain questions directly;
* store data (RAG)   — retrieve() injects the most relevant products, KB
                       chunks and store facts into the prompt so store
                       answers always come from real data;
* tools (functions)  — the model can call store tools (product search,
                       car recommendations, knowledge search, policies,
                       add-to-cart, order help) to take actions;
* memory             — per-session message history so follow-ups like
                       "the cheaper one" resolve naturally.

Everything is modular: add a tool by appending a schema to TOOLS and a
handler with @_register('<name>'). If anything fails (no key, timeout,
bad JSON) answer() returns None and app.py falls back to the rule engine.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from recommend_engine import PRODUCTS

# ---------------------------------------------------------------------------
# Runtime wiring — injected once from app.py at startup.
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
    'gemini-3-flash-preview',
    'gemini-3.1-flash-lite',
    'gemini-flash-lite-latest',
    'gpt-4o-mini',
)


def _models() -> list:
    """Primary model plus fallbacks.

    Gemini free-tier keys are limited per model (20 requests/day per model),
    so on quota exhaustion we rotate through other models that share the same
    key, effectively multiplying the daily budget. Configure extras via
    OPENAI_FALLBACK_MODELS (comma separated).
    """
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


_STORE_HINTS = (
    'product', 'price', 'cost', 'buy', 'purchase', 'order', 'cart', 'stock',
    'car', 'vehicle', 'suv', 'sedan', 'toyota', 'recommend', 'trending',
    'deliver', 'ship', 'return', 'refund', 'pay', 'payment', 'contact',
    'phone', 'email', 'warranty', 'discount', 'deal', 'offer', 'policy',
    'sell', 'store', 'knowledge', 'faq', 'watch', 'iphone', 'macbook',
    'galaxy', 'sony', 'jbl', 'bravia', 'headphone', 'laptop', 'telebirr',
    'cbe', 'hours', 'open', 'closed', 'about', 'track', 'help', 'obama',
    'inventory', 'available', 'spec', 'feature', 'brand', 'model',
)


def _needs_tools(text: str) -> bool:
    """True when a message looks store-related and may need tool execution.

    General questions are answered by the model alone in a single request
    (no tool schema, no tool-calling round), which is fast and cheap and
    protects the per-model daily quota. Store questions get the tool set so
    the model can pull real product/policy data when retrieval misses.
    """
    lower = (text or '').lower()
    return any(hint in lower for hint in _STORE_HINTS)


def _chat_completion(messages, tools=None, attempts=2):
    timeout = float(os.environ.get('LLM_TIMEOUT', '30'))
    last_error = None
    for model in _models():
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.4,
            'max_tokens': 1000,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        body = json.dumps(payload).encode('utf-8')
        for attempt in range(attempts):
            request = urllib.request.Request(
                _base_url() + '/chat/completions',
                data=body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + _api_key(),
                },
                method='POST',
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as error:
                last_error = error
                # 429 (quota/rate) and 404 (model not available to this key):
                # move to the next model in the chain.
                if error.code in (404, 429):
                    break
                # 408 / 5xx: transient, retry this model, then move on.
                if error.code == 408 or error.code >= 500:
                    if attempt == attempts - 1:
                        break
                    time.sleep(1 + attempt * 2)
                    continue
                raise
            except (urllib.error.URLError, OSError) as error:
                last_error = error
                if attempt == attempts - 1:
                    break
                time.sleep(1 + attempt * 2)
                continue
    raise last_error  # pragma: no cover


# ---------------------------------------------------------------------------
# Formatting helpers (mirror app.py so cards look identical in the UI).
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
    }


def _car_card(car: dict) -> dict:
    price = car.get('price') or 0
    pred = car.get('predicted_price') or 0
    value_tag = ''
    if pred and price:
        ratio = price / max(pred, 1)
        value_tag = 'Great deal' if ratio < 0.95 else ('Fair price' if ratio <= 1.05 else 'Priced high')
    return {
        'type': 'car',
        'title': car.get('title', ''),
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
        return f"{title} ({kind}) {price}{stock_txt}, id={hit.get('id', '')}"
    price = _fmt_money(hit.get('price'))
    kind = hit.get('fuel', '')
    return f"{title} ({kind}) {price}"


def _search_products(query: str, limit: int = 4):
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
        if needle in haystack or any(len(w) >= 4 and w in haystack for w in words):
            key = str(product.get('title')).lower()
            if key not in seen:
                seen.add(key)
                hits.append(product)
    for car in _car_catalog():
        haystack = ' '.join((car['title'], car['tags'])).lower()
        if needle in haystack or any(len(w) >= 4 and w in haystack for w in words):
            key = car['title'].lower()
            if key not in seen:
                seen.add(key)
                hits.append(car)
        if len(hits) >= limit:
            break
    return hits[:limit]


def _recommend_cars(budget, fuel='any', transmission='any'):
    if _recommend_cars_fn is not None:
        return _recommend_cars_fn(budget, fuel, transmission) or []
    cars = _car_catalog()
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
    ranked = sorted(pool, key=rank, reverse=True)
    return ranked[:3]


def _kb_search(query: str, limit: int = 3):
    if _kb is None:
        return []
    try:
        return _kb.search(query, limit=limit) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Store facts (always exact — never invented by the model).
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
            f"{c.get('developer', '')} in {c.get('city', '')}. It sells electronics, "
            f"mobile, fashion, wearables, accessories and verified used cars, with "
            f"every car priced against an ML fair-price model. Contact: "
            f"{c.get('phones', '')} / {c.get('email', '')}"
        ),
        'payment': (
            "We accept Telebirr, CBE Pay, and cash on delivery. Mobile payments "
            "are processed securely at checkout."
        ),
        'delivery': (
            "We deliver across Ethiopia — Addis Ababa usually within 1-3 business "
            "days, and other regions in 3-7 days. Delivery is confirmed with the "
            "customer before checkout."
        ),
        'returns': (
            "Easy returns: contact us within 7 days of delivery to arrange a "
            "return or exchange. Items must be in original condition with packaging."
        ),
        'hours': (
            "Support is available 24/7. Order processing runs Monday-Saturday, "
            "9:00-18:00 (EAT)."
        ),
        'warranty': (
            "Every product includes the manufacturer warranty, and cars come with "
            "a verified-ownership guarantee. Anything defective on arrival is "
            "replaced or repaired free within 7 days."
        ),
        'orders': (
            "Orders can be tracked in My Account -> Order History, or by replying "
            "with the order number. Orders usually update within minutes of shipping."
        ),
        'security': (
            "Payments are processed securely, products are checked for "
            "authenticity before dispatch, and customer data is never shared."
        ),
        'general': (
            f"Obama Store ({c.get('city', '')}) sells electronics, mobile, fashion, "
            f"wearables, accessories and verified used cars. Phones: "
            f"{c.get('phones', '')}. Email: {c.get('email', '')}. "
            "Accepts Telebirr, CBE Pay and cash on delivery. Delivery nationwide "
            "in 1-7 business days; returns within 7 days."
        ),
    }


_POLICY_TOPICS = {
    'contact': ('contact', 'phone', 'call', 'email', 'reach', 'number', 'address', 'talk'),
    'about': ('about', 'who made', 'developer', 'history', 'what is obama', 'about the store'),
    'payment': ('pay', 'payment', 'telebirr', 'cbe', 'cash', 'mobile money', 'm-pesa', 'mpesa'),
    'delivery': ('deliver', 'ship', 'shipping', 'how long', 'arrive', 'get here'),
    'returns': ('return', 'refund', 'exchange', 'money back'),
    'hours': ('hour', 'open', 'close', 'when', 'support'),
    'warranty': ('warranty', 'guarantee', 'defect', 'broken'),
    'orders': ('order', 'track', 'status'),
    'security': ('secure', 'safe', 'trust', 'authentic', 'legit'),
}


# ---------------------------------------------------------------------------
# Tool definitions + handlers. TOOLS holds the JSON schemas sent to the LLM;
# handlers turn tool calls into real store data. Add a tool in both places.
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
        'Search the Obama Store catalogue for products or cars matching a query. '
        'Returns matching items with price, category and stock.',
        {'query': {'type': 'string', 'description': 'Product or car keywords, e.g. "iPhone 15" or "Toyota".'}},
        ['query'],
    ),
    _tool_schema(
        'get_car_recommendations',
        'Recommend cars from the store catalogue. Optionally filter by budget '
        '(in Ethiopian Birr ETB), fuel and transmission.',
        {
            'budget': {'type': 'number', 'description': 'Maximum budget in Ethiopian Birr (ETB).'},
            'fuel': {'type': 'string', 'enum': ['Petrol', 'Diesel', 'CNG', 'any']},
            'transmission': {'type': 'string', 'enum': ['Automatic', 'Manual', 'any']},
        },
    ),
    _tool_schema(
        'get_trending',
        'Get the currently trending cars in the store.',
        {},
    ),
    _tool_schema(
        'search_knowledge',
        'Search the store knowledge base (manually uploaded documents, FAQs and '
        'policies). Returns the most relevant passages.',
        {'query': {'type': 'string', 'description': 'What to look up, e.g. "return policy".'}},
        ['query'],
    ),
    _tool_schema(
        'get_store_policy',
        'Get official store information: contact, about, payment, delivery, '
        'returns, hours, warranty, order tracking, or security.',
        {'topic': {'type': 'string', 'enum': [
            'contact', 'about', 'payment', 'delivery', 'returns', 'hours',
            'warranty', 'orders', 'security', 'general',
        ]}},
    ),
    _tool_schema(
        'add_to_cart',
        "Add a product or car to the user's cart. The cart itself lives in the "
        "browser; this records the purchase intent so the app adds the item.",
        {'query': {'type': 'string', 'description': 'Name of the item to buy.'}},
        ['query'],
    ),
    _tool_schema(
        'get_order_help',
        'Help with orders: how to track, view, or manage an order.',
        {},
    ),
]

_TOOL_HANDLERS = {}


def _register(name):
    def decorator(fn):
        _TOOL_HANDLERS[name] = fn
        return fn
    return decorator


@_register('search_products')
def _h_search_products(args, session):
    hits = _search_products(str(args.get('query') or ''), limit=4)
    if not hits:
        return ('No items found matching that query.', [])
    lines = ['Matches:'] + [f"- {_product_line(h)}" for h in hits]
    cards = [_hit_card(h) for h in hits]
    return ('\n'.join(lines), cards)


@_register('get_car_recommendations')
def _h_car_recommendations(args, session):
    budget = args.get('budget')
    if budget is not None:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            budget = None
    fuel = str(args.get('fuel') or 'any')
    transmission = str(args.get('transmission') or 'any')
    cars = _recommend_cars(budget, fuel, transmission)
    if not cars:
        return ('No cars match those criteria right now.', [])
    lines = [
        f"- {c['title']} ({_fmt_money(c['price'])}) · {c.get('fuel', '')} · "
        f"{c.get('transmission', '')} · {c.get('year', '')}"
        for c in cars
    ]
    return ('\n'.join(lines), [_car_card(c) for c in cars])


@_register('get_trending')
def _h_trending(args, session):
    cars = sorted(
        _car_catalog(),
        key=lambda c: (c.get('popularity', 0), -c.get('car_age', 0), c.get('price', 0)),
        reverse=True,
    )[:3]
    if not cars:
        return ('Trending data is unavailable right now.', [])
    lines = [f"- {c['title']} ({_fmt_money(c['price'])})" for c in cars]
    return ('\n'.join(lines), [_car_card(c) for c in cars])


@_register('search_knowledge')
def _h_search_knowledge(args, session):
    query = str(args.get('query') or '').strip()
    results = _kb_search(query, limit=3)
    if not results:
        return ('No knowledge base matches.', [])
    lines = []
    for r in results:
        title = r.get('title') or 'knowledge'
        content = str(r.get('content') or '')[:600].strip()
        lines.append(f"KB: {title}\n{content}")
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
        return ('No product found to add to cart.', [])
    top = hits[0]
    card = _hit_card(top)
    title = top.get('title', '?')
    price_text = card.get('priceText') or ''
    action = {'type': 'add_to_cart', 'title': title, 'priceText': price_text}
    if top.get('priceValue') is not None:
        action['productId'] = top.get('id', '')
        action['openProduct'] = True
    session.setdefault('ai_pending_actions', []).append(action)
    return (
        f"Added {title} ({price_text}) to the cart. "
        f"productId={top.get('id', '')} openProduct={action.get('openProduct', False)}",
        [card],
    )


@_register('get_order_help')
def _h_order_help(args, session):
    return (
        'Orders can be tracked in My Account -> Order History, or by replying '
        'with the order number. Delivery is confirmed with the customer before '
        'checkout.',
        [],
    )


def _run_tool(name, arguments, session):
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return ('Unknown tool.', [])
    try:
        text, cards = handler(arguments, session)
        return (str(text), cards)
    except Exception as exc:  # keep the conversation alive
        return (f'Tool error: {exc}', [])


# ---------------------------------------------------------------------------
# RAG retrieval — pull the most relevant store data for the current message.
# ---------------------------------------------------------------------------

def _retrieve(text: str):
    context = []
    for result in _kb_search(text, limit=2):
        title = result.get('title') or 'FAQ'
        content = str(result.get('content') or '')[:500].strip()
        if content:
            context.append(f"[Knowledge] {title}: {content}")
    for hit in _search_products(text, limit=3):
        context.append(f"[Catalogue] {_product_line(hit)}")
    return context


def _system_prompt(context):
    facts = _store_facts()
    store_knowledge = '\n'.join(context) if context else '(none retrieved)'
    return (
        "You are Obama, the AI assistant for Obama Store, an Ethiopian e-commerce "
        f"platform created by {_CONTACT.get('developer', 'Obama Abraham')} in "
        f"{_CONTACT.get('city', 'Addis Ababa, Ethiopia')}. "
        "Be friendly, accurate, professional, and concise (2-5 short sentences "
        "unless the question needs more). Reply in the same language as the user.\n\n"
        "HOW TO ANSWER:\n"
        "1. Store questions (products, cars, prices, stock, policies, orders, "
        "contact, payment, delivery, returns, promotions): ALWAYS base your answer "
        "on the retrieved store records and the tools below. Never invent prices, "
        "stock, or policies. If the data is missing, say you don't have it and "
        "offer to look it up.\n"
        "2. General questions (science, world facts, how-to, casual chat): answer "
        "from your own knowledge normally.\n"
        "3. Follow-ups: use the conversation history to resolve references like "
        "'the cheaper one', 'that', or 'it'.\n\n"
        "STORE RECORDS RETRIEVED FOR THIS QUESTION:\n"
        + store_knowledge +
        "\n\nIf the user asks about the store and these records don't cover it, "
        "call the relevant tool to get real data.\n\n"
        "STORE CONTACT (always accurate, never change it):\n"
        + _contact_text()
    )


# ---------------------------------------------------------------------------
# Memory — per-session conversation history stored on the app.py session dict.
# ---------------------------------------------------------------------------

def _build_messages(session, message, client_history):
    memory = session.get('ai_messages')
    if not memory:
        memory = []
        for item in (client_history or [])[-14:]:
            role = item.get('role')
            if role in ('user', 'assistant') and item.get('content'):
                memory.append({'role': role, 'content': str(item['content'])[:4000]})
    memory = [m for m in memory if m.get('content')][-14:]
    if not memory or memory[-1].get('content') != message:
        memory.append({'role': 'user', 'content': message[:4000]})
    session['ai_messages'] = memory
    return memory


def _dedupe_cards(cards):
    seen = set()
    out = []
    for card in cards:
        key = (card.get('type'), card.get('id') or card.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def _suggestions(store_related: bool):
    if store_related:
        return ['Recommend a car', "What's trending?", 'Contact us']
    return ['Recommend a car', 'Tell me about the store', 'What can you do?']


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------

def answer(message, session, client_history):
    """Run the AI assistant for one turn.

    Returns a response dict {reply, suggestions, cards, flow, action} that is
    compatible with app.py's _response() contract, or None to fall back to the
    deterministic intent engine.
    """
    if not enabled():
        return None
    message = (message or '').strip()
    if not message:
        return None

    memory = _build_messages(session, message, client_history)
    context = _retrieve(message)
    messages = [{'role': 'system', 'content': _system_prompt(context)}] + memory
    session.setdefault('ai_pending_actions', [])

    collected_cards = []
    reply = ''
    deadline = time.monotonic() + float(os.environ.get('LLM_MAX_SECONDS', '60'))
    for _round in range(3):
        if time.monotonic() > deadline:
            break
        try:
            response = _chat_completion(
                messages, tools=TOOLS if _needs_tools(message) else None)
        except Exception:
            return None
        choice = response.get('choices') and response['choices'][0] or {}
        choice_message = choice.get('message') or {}
        tool_calls = choice_message.get('tool_calls')
        if not tool_calls:
            reply = (choice_message.get('content') or '').strip()
            break
        messages.append({
            'role': 'assistant',
            'content': choice_message.get('content') or '',
            'tool_calls': tool_calls,
        })
        for call in tool_calls:
            function = call.get('function') or {}
            name = function.get('name') or ''
            try:
                arguments = json.loads(function.get('arguments') or '{}')
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

    messages.append({'role': 'assistant', 'content': reply})
    memory = [
        m for m in messages
        if m.get('role') in ('user', 'assistant')
        and not m.get('tool_calls')
        and m.get('content')
    ]
    session['ai_messages'] = memory[-16:]

    actions = session.get('ai_pending_actions') or []
    action = actions[-1] if actions else None
    store_related = bool(context or collected_cards)
    return {
        'reply': reply,
        'suggestions': _suggestions(store_related),
        'cards': _dedupe_cards(collected_cards)[:6],
        'flow': None,
        'action': action,
    }
