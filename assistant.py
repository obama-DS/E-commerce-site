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

