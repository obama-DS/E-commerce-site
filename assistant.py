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

