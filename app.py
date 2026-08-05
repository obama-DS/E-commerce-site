from pathlib import Path
from typing import List, Optional
import hashlib
import json
import os
import re
import random
import secrets
import time

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from recommend_engine import PRODUCTS, RecommendationEngine
from knowledge import KnowledgeBase

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "CAR.csv"
MODEL_FILE = BASE_DIR / "car_price_model.pkl"
STATIC_DIR = BASE_DIR

app = FastAPI(
    title="Obama Store API",
    description="Backend API for the Obama Store — car recommender powered by a local CSV dataset and ML model, plus the AI product recommendation engine."
)

# ------------------------------------------------------------------
# Auth — lightweight token-based accounts with PBKDF2 hashing.
# User data lives outside the web root (LocalAppData on Windows) so
# credentials are never exposed by the static file server.
# ------------------------------------------------------------------

AUTH_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ObamaStore"
AUTH_DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_FILE = AUTH_DATA_DIR / "users.json"


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000).hex()


def _new_token() -> str:
    return secrets.token_hex(24)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


class UserStore:
    def __init__(self) -> None:
        self.path = USERS_FILE
        self.users: List[dict] = []
        self.tokens: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.users = data.get("users", [])
                self.tokens = data.get("tokens", {})
            except Exception:
                self.users = []
                self.tokens = {}
        self.tokens = {t: uid for t, uid in self.tokens.items() if self._find_user(uid) is not None}

    def _save(self) -> None:
        payload = {"users": self.users, "tokens": self.tokens}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _find_user(self, uid: str) -> Optional[dict]:
        return next((u for u in self.users if u["id"] == uid), None)

    def _find_by_email(self, email: str) -> Optional[dict]:
        key = (email or "").strip().lower()
        return next((u for u in self.users if u["email"] == key), None)

    def create_user(self, name: str, email: str, password: str):
        if self._find_by_email(email):
            raise ValueError("email_taken")
        salt = secrets.token_bytes(16)
        user = {
            "id": secrets.token_hex(8),
            "name": (name or "").strip(),
            "email": (email or "").strip().lower(),
            "password_hash": _hash_password(password, salt),
            "salt": salt.hex(),
            "is_admin": False,
            "created_at": int(time.time()),
        }
        self.users.append(user)
        token = self._issue_token(user["id"])
        return user, token

    def verify_login(self, email: str, password: str):
        user = self._find_by_email(email)
        if not user:
            raise ValueError("bad_credentials")
        salt = bytes.fromhex(user["salt"])
        candidate = _hash_password(password or "", salt)
        if not secrets.compare_digest(user["password_hash"], candidate):
            raise ValueError("bad_credentials")
        token = self._issue_token(user["id"])
        return user, token

    def _issue_token(self, uid: str) -> str:
        token = _new_token()
        self.tokens[token] = uid
        self._save()
        return token

    def user_by_token(self, token: str) -> Optional[dict]:
        uid = self.tokens.get(token)
        return self._find_user(uid) if uid else None

    def revoke(self, token: str) -> None:
        if token in self.tokens:
            del self.tokens[token]
            self._save()


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "is_admin": bool(user.get("is_admin")),
        "created_at": user["created_at"],
    }


user_store = UserStore()

kb = KnowledgeBase()


def _ensure_admin() -> None:
    """Create/promote an admin account (env vars override, else a local default)."""
    if any(u.get("is_admin") for u in user_store.users):
        return
    email = os.environ.get("ADMIN_EMAIL", "admin@obamastore.com").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = user_store._find_by_email(email)
    if existing:
        existing["is_admin"] = True
        user_store._save()
        return
    user, _ = user_store.create_user("Store Admin", email, password)
    user["is_admin"] = True
    user_store._save()


def _require_admin(request: Request) -> dict:
    token = _bearer_token(request.headers.get("authorization"))
    user = user_store.user_by_token(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to access the Knowledge Base.")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
async def register(req: RegisterRequest) -> dict:
    name = (req.name or "").strip()
    email = (req.email or "").strip().lower()
    password = req.password or ""
    if not name or "@" not in email or len(password) < 6:
        raise HTTPException(status_code=400, detail="Enter your name, a valid email, and a password of at least 6 characters.")
    try:
        user, token = user_store.create_user(name, email, password)
    except ValueError:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    return {"token": token, "user": _public_user(user)}


@app.post("/api/auth/login")
async def login(req: LoginRequest) -> dict:
    try:
        user, token = user_store.verify_login(req.email or "", req.password or "")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"token": token, "user": _public_user(user)}


@app.get("/api/auth/me")
async def me(authorization: Optional[str] = Header(default=None)) -> dict:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token.")
    user = user_store.user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return {"user": _public_user(user)}


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None)) -> dict:
    token = _bearer_token(authorization)
    if token:
        user_store.revoke(token)
    return {"ok": True}

class RecommendationRequest(BaseModel):
    budget: Optional[float] = 0.0
    fuel: Optional[str] = "any"
    transmission: Optional[str] = "any"
    km: Optional[int] = None
    age: Optional[int] = None


class SignalEntry(BaseModel):
    id: Optional[str] = None
    q: Optional[str] = None
    qty: Optional[int] = 1
    at: Optional[float] = 0.0


class RecommendationContext(BaseModel):
    page: Optional[str] = "home"
    productId: Optional[str] = None


class RecommendationSignals(BaseModel):
    views: List[SignalEntry] = []
    searches: List[SignalEntry] = []
    wishlist: List[str] = []
    cart: List[SignalEntry] = []
    purchases: List[str] = []


class ProductRecommendationRequest(BaseModel):
    context: Optional[RecommendationContext] = None
    signals: Optional[RecommendationSignals] = None


def load_car_dataset() -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Dataset file not found at {DATA_FILE}")

    df = pd.read_csv(DATA_FILE)
    df = df.rename(columns={
        'selling_price': 'selling_price',
        'km_driven': 'km_driven',
        'fuel': 'fuel',
        'seller_type': 'seller_type',
        'transmission': 'transmission',
        'owner': 'owner',
        'name': 'name',
        'year': 'year'
    })
    return df


def prepare_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    current_year = pd.Timestamp.now().year
    df['Car_Age'] = current_year - df['year']
    return df[['km_driven', 'Car_Age', 'fuel', 'seller_type', 'transmission', 'owner']]


def build_pipeline() -> Pipeline:
    numeric_cols = ['km_driven', 'Car_Age']
    categorical_cols = ['fuel', 'seller_type', 'transmission', 'owner']

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), numeric_cols),
            ('cat', OneHotEncoder(drop='first', handle_unknown='ignore'), categorical_cols),
        ]
    )

    model = Pipeline(
        steps=[
            ('preprocessor', preprocessor),
            ('regressor', GradientBoostingRegressor(random_state=42, n_estimators=200, learning_rate=0.05, max_depth=4))
        ]
    )
    return model


def train_model() -> Pipeline:
    df = load_car_dataset()
    X = prepare_feature_matrix(df)
    y = df['selling_price']

    model = build_pipeline()
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)
    return model


def load_or_train_model() -> Pipeline:
    if MODEL_FILE.exists():
        try:
            return joblib.load(MODEL_FILE)
        except Exception:
            return train_model()

    return train_model()


_CAR_PHOTO_SEDAN = (
    'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=900&q=80'
)
_CAR_PHOTO_SUV = (
    'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=900&q=80'
)
_CAR_PHOTO_PREMIUM = (
    'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?auto=format&fit=crop&w=900&q=80'
)

_CAR_SUV_KEYWORDS = (
    'x1', 'x3', 'x5', 'x7', 'q5', 'q7', 'suv', 'creta', 'ecosport',
    'fortuner', 'scorpio', 'xuv', 'thar', 'compass', 'pajero', 'safari',
    'hexa', 'endeavour', 'innova', 'crysta', 'gl-class', 'g-class',
    'gls', 'gle', 'range rover', 'defender', 'land cruiser',
)

_CAR_BRAND_IMAGES = {
    'land rover': _CAR_PHOTO_SUV,
    'range rover': _CAR_PHOTO_SUV,
    'bmw': _CAR_PHOTO_SUV,
    'hyundai': _CAR_PHOTO_SUV,
    'tata': _CAR_PHOTO_SUV,
    'mahindra': _CAR_PHOTO_SUV,
    'jeep': _CAR_PHOTO_SUV,
    'kia': _CAR_PHOTO_SUV,
    'mercedes': _CAR_PHOTO_PREMIUM,
    'benz': _CAR_PHOTO_PREMIUM,
    'volkswagen': _CAR_PHOTO_PREMIUM,
    'skoda': _CAR_PHOTO_PREMIUM,
    'lexus': _CAR_PHOTO_PREMIUM,
    'audi': _CAR_PHOTO_SEDAN,
    'toyota': _CAR_PHOTO_SEDAN,
    'honda': _CAR_PHOTO_SEDAN,
    'ford': _CAR_PHOTO_SEDAN,
    'nissan': _CAR_PHOTO_SEDAN,
    'mazda': _CAR_PHOTO_SEDAN,
    'chevrolet': _CAR_PHOTO_SEDAN,
    'renault': _CAR_PHOTO_SEDAN,
    'maruti': _CAR_PHOTO_SEDAN,
    'suzuki': _CAR_PHOTO_SEDAN,
}

_CAR_DEFAULT_IMAGE = _CAR_PHOTO_SEDAN


def choose_image(name: str) -> str:
    """Pick a real car photo for a listing — never a network placeholder."""
    normalized = (name or '').lower()
    for keyword in _CAR_SUV_KEYWORDS:
        if keyword in normalized:
            return _CAR_PHOTO_SUV
    for brand, photo in _CAR_BRAND_IMAGES.items():
        if brand in normalized:
            return photo
    return _CAR_DEFAULT_IMAGE


def build_car_record(row: pd.Series, predicted_price: float) -> dict:
    car_age = pd.Timestamp.now().year - int(row['year'])
    tags = f"{row['name']} {row['fuel']} {row['transmission']} {row['seller_type']} {row['owner']}"
    return {
        'id': int(row.name),
        'title': str(row['name']),
        'year': int(row['year']),
        'price': int(row['selling_price']),
        'predicted_price': float(round(predicted_price, 0)),
        'km': int(row['km_driven']),
        'fuel': str(row['fuel']),
        'transmission': str(row['transmission']),
        'owner': str(row['owner']),
        'seller_type': str(row['seller_type']),
        'car_age': int(car_age),
        'description': f"{row['name']} with {row['fuel']} fuel, {row['transmission']} transmission, and {row['km_driven']} km.",
        'imageUrl': choose_image(str(row['name'])),
        'fallbackImage': choose_image(str(row['name'])),
        'popularity': float(round(predicted_price / max(car_age, 1), 1)),
        'tags': tags
    }
#hey
def build_recommendation_score(car: dict, budget: float, fuel: str, transmission: str, km: Optional[int], age: Optional[int]) -> float:
    score = 0.0
    if budget and budget > 0:
        budget_gap = abs(car['predicted_price'] - budget) / max(budget, 1)
        score += max(0.0, 40.0 - budget_gap * 40.0)
    else:
        score += 10.0

    if fuel != 'any' and fuel == car['fuel']:
        score += 20.0
    elif fuel == 'any':
        score += 8.0

    if transmission != 'any' and transmission == car['transmission']:
        score += 16.0
    elif transmission == 'any':
        score += 6.0

    if km is not None and car['km'] <= km:
        score += 10.0

    if age is not None and car['car_age'] <= age:
        score += 8.0

    if car['owner'].lower() == 'first owner':
        score += 5.0

    score += max(0.0, 6.0 - car['car_age'] * 0.15)
    score += min(10.0, car['popularity'] * 0.1)
    return score


def build_car_catalog(model: Pipeline) -> List[dict]:
    df = load_car_dataset()
    feature_matrix = prepare_feature_matrix(df)
    predictions = model.predict(feature_matrix)
    cars = []
    seen = set()
    for (idx, row), pred in zip(df.iterrows(), predictions):
        title = str(row['name']).strip().lower()
        if title in seen:
            continue
        seen.add(title)
        cars.append(build_car_record(row, pred))
    return cars


def build_car_value_scores(model: Pipeline) -> dict:
    """Use the trained price model to score catalogue cars on value.

    Runs each catalogue car through the ML price predictor, then computes a
    normalized value score = deviation of listed price from the predicted fair
    price, clipped to [-0.3, 0.3].
    """
    rows = []
    ids = []
    for product in PRODUCTS:
        if product.get('category') != 'Cars':
            continue
        ids.append(product['id'])
        rows.append({
            'km_driven': product.get('km', 0),
            'year': product.get('year', 2018),
            'fuel': product.get('fuel', 'Petrol'),
            'seller_type': product.get('sellerType', 'Dealer'),
            'transmission': product.get('transmission', 'Automatic'),
            'owner': product.get('owner', 'First Owner'),
        })

    if not rows:
        return {}

    df = pd.DataFrame(rows)
    current_year = pd.Timestamp.now().year
    df['Car_Age'] = current_year - df['year']
    feature_matrix = df[['km_driven', 'Car_Age', 'fuel', 'seller_type', 'transmission', 'owner']]
    predictions = model.predict(feature_matrix)

    values = {}
    for pid, price, pred in zip(ids, [p['priceValue'] for p in PRODUCTS if p.get('category') == 'Cars'], predictions):
        deviation = (float(pred) - float(price)) / max(float(price), 1.0)
        values[pid] = {
            'predicted': int(round(float(pred))),
            'value_score': round(float(np.clip(deviation, -0.3, 0.3)), 4),
        }
    return values


@app.on_event('startup')
async def startup_event() -> None:
    global model, car_catalog, rec_engine
    model = load_or_train_model()
    car_catalog = build_car_catalog(model)
    car_values = build_car_value_scores(model)
    rec_engine = RecommendationEngine(PRODUCTS, car_values=car_values)
    kb._init_db()
    _ensure_admin()


@app.get('/api/trending-cars')
async def get_trending_cars(limit: int = 15) -> dict:
    if not car_catalog:
        raise HTTPException(status_code=500, detail='Car catalog is unavailable.')

    trending = sorted(
        car_catalog,
        key=lambda car: (car['popularity'], -car['car_age'], car['price']),
        reverse=True
    )
    count = max(1, min(limit, len(trending)))
    return {'cars': trending[:count]}


@app.post('/api/recommendations')
async def get_recommendations(request: RecommendationRequest) -> dict:
    if not car_catalog:
        raise HTTPException(status_code=500, detail='Car catalog is unavailable.')

    budget = request.budget or 0.0
    km = request.km
    age = request.age

    scored = []
    for car in car_catalog:
        score = build_recommendation_score(car, budget, request.fuel, request.transmission, km, age)
        scored.append({**car, 'score': float(round(score, 1))})

    recommended = sorted(scored, key=lambda item: (item['score'], -item['popularity']), reverse=True)
    return {'cars': recommended[:8]}


def _signals_dict(signals: Optional[RecommendationSignals]) -> dict:
    if signals is None:
        return {}
    return {
        'views': [{'id': v.id, 'at': v.at} for v in signals.views if v.id],
        'searches': [{'q': s.q, 'at': s.at} for s in signals.searches if s.q],
        'wishlist': [w for w in signals.wishlist],
        'cart': [{'id': c.id, 'qty': c.qty, 'at': c.at} for c in signals.cart if c.id],
        'purchases': [p for p in signals.purchases],
    }


@app.get('/api/v1/products')
async def get_catalog_products(limit: int = 200) -> dict:
    if rec_engine is None:
        raise HTTPException(status_code=503, detail='Recommendation engine is not ready.')
    return {'products': rec_engine.all_products(limit)}


@app.get('/api/v1/recommendations/trending')
async def get_trending_recommendations() -> dict:
    if rec_engine is None:
        raise HTTPException(status_code=503, detail='Recommendation engine is not ready.')
    section = {
        'title': 'Trending Products',
        'reason': 'What shoppers are buying right now',
        'products': [rec_engine.serialize(p, source='trending') for p in rec_engine.trending(8)],
    }
    return {'personalized': False, 'sections': {'trending': section}}


@app.get('/api/v1/recommendations/best-sellers')
async def get_best_sellers_recommendations() -> dict:
    if rec_engine is None:
        raise HTTPException(status_code=503, detail='Recommendation engine is not ready.')
    section = {
        'title': 'Best Sellers',
        'reason': 'Our most popular products',
        'products': [rec_engine.serialize(p, source='best_seller') for p in rec_engine.best_sellers(8)],
    }
    return {'personalized': False, 'sections': {'best_sellers': section}}


@app.get('/api/v1/recommendations/new-arrivals')
async def get_new_arrivals_recommendations() -> dict:
    if rec_engine is None:
        raise HTTPException(status_code=503, detail='Recommendation engine is not ready.')
    section = {
        'title': 'New Arrivals',
        'reason': 'Just added to the store',
        'products': [rec_engine.serialize(p, source='new_arrival') for p in rec_engine.new_arrivals(8)],
    }
    return {'personalized': False, 'sections': {'new_arrivals': section}}


@app.post('/api/v1/recommendations')
async def get_ai_recommendations(request: ProductRecommendationRequest) -> dict:
    if rec_engine is None:
        raise HTTPException(status_code=503, detail='Recommendation engine is not ready.')

    context = request.context.model_dump() if request.context else {'page': 'home'}
    signals = _signals_dict(request.signals)

    sections = rec_engine.build_sections(context, signals, limit=8)
    return {
        'personalized': any(s.get('personalized') for s in sections.values()),
        'generated_at': int(np.floor(pd.Timestamp.now().timestamp())),
        'context': context,
        'sections': sections,
    }


@app.get('/api/v1/recommendations/health')
async def recommendation_health() -> dict:
    return {
        'ok': rec_engine is not None,
        'products': len(rec_engine.catalog) if rec_engine else 0,
        'model': MODEL_FILE.exists(),
    }


# ------------------------------------------------------------------
# Chat assistant — "Obama", the store's AI assistant.
#
# Phase 1 (active): a deterministic intent engine. Every reply is built
# from the store's own data (PRODUCTS, car_catalog, FAQs, contact info),
# so it never hangs, needs no external key, and never errors out — any
# input gets a helpful answer.
# Phase 2 (ready): set CHAT_BACKEND=llm and implement _llm_reply() to
# delegate to an LLM adapter. The /api/chat contract stays identical.
# ------------------------------------------------------------------

CHAT_BACKEND = os.environ.get('CHAT_BACKEND', 'rules')

# ------------------------------------------------------------------
# Knowledge Base — admin API. Every endpoint requires an admin token.
# ------------------------------------------------------------------

class KBItemRequest(BaseModel):
    title: str
    content: str
    category: str = "General"
    tags: List[str] = []
    content_type: str = "text"
    source: str = ""


class KBUrlRequest(BaseModel):
    url: str
    title: str = ""
    category: str = "General"
    tags: List[str] = []


class KBTestRequest(BaseModel):
    message: str


def _kb_tags(raw: str) -> List[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


@app.get('/api/kb/stats')
async def kb_stats(request: Request) -> dict:
    _require_admin(request)
    return kb.stats()


@app.get('/api/kb/meta')
async def kb_meta(request: Request) -> dict:
    _require_admin(request)
    return {
        'categories': kb.categories(),
        'tags': kb.tags(),
        'stats': kb.stats(),
    }


@app.get('/api/kb/items')
async def kb_list(request: Request, q: str = "", category: str = "",
                  tag: str = "", status: str = "", page: int = 1,
                  page_size: int = 20) -> dict:
    _require_admin(request)
    return kb.list(
        q=q.strip() or None,
        category=category.strip() or None,
        tag=tag.strip() or None,
        status=status.strip() or None,
        page=page,
        page_size=page_size,
    )


@app.get('/api/kb/items/{item_id}')
async def kb_get(request: Request, item_id: str) -> dict:
    _require_admin(request)
    item = kb.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found.")
    return item


@app.post('/api/kb/items')
async def kb_create(request: Request, req: KBItemRequest) -> dict:
    _require_admin(request)
    try:
        return kb.create(
            title=req.title,
            content=req.content,
            category=req.category,
            tags=req.tags,
            content_type=req.content_type or 'text',
            source=req.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put('/api/kb/items/{item_id}')
async def kb_update(request: Request, item_id: str, req: KBItemRequest) -> dict:
    _require_admin(request)
    try:
        return kb.update(
            item_id,
            title=req.title,
            content=req.content,
            category=req.category,
            tags=req.tags,
            content_type=req.content_type or 'text',
            source=req.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete('/api/kb/items/{item_id}')
async def kb_delete(request: Request, item_id: str) -> dict:
    _require_admin(request)
    item = kb.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found.")
    kb.delete(item_id)
    return {'ok': True}


@app.post('/api/kb/items/{item_id}/reindex')
async def kb_reindex(request: Request, item_id: str) -> dict:
    _require_admin(request)
    item = kb.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found.")
    kb.index_item(item_id)
    return kb.get(item_id)


@app.post('/api/kb/upload')
async def kb_upload(request: Request, file: UploadFile = File(...),
                    title: str = Form(''), category: str = Form('General'),
                    tags: str = Form('')) -> dict:
    _require_admin(request)
    filename = file.filename or 'upload.bin'
    data = await file.read()
    try:
        return kb.import_file(
            filename=filename,
            data=data,
            category=category or 'General',
            tags=_kb_tags(tags),
            title=title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post('/api/kb/url')
async def kb_url(request: Request, req: KBUrlRequest) -> dict:
    _require_admin(request)
    try:
        return kb.import_url(
            url=req.url,
            category=req.category or 'General',
            tags=req.tags,
            title=req.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post('/api/kb/test')
async def kb_test(request: Request, req: KBTestRequest) -> dict:
    _require_admin(request)
    return kb.test(req.message or '', limit=6)


STORE_CONTACT = {
    'phones': '+251 963 126 602, +251 799 494 063',
    'email': 'obamaabrahamassefa@gmail.com',
    'developer': 'Obama Abraham',
    'city': 'Addis Ababa, Ethiopia',
}

# Multi-step car-recommendation flow: steps + the picker options shown
# to the user. Picked options come back as ordinary chat messages.
_FLOW_OPTIONS = {
    'budget': ['Under 30,000', 'Under 60,000', 'Under 150,000', 'No limit'],
    'fuel': ['Petrol', 'Diesel', 'CNG', 'Any fuel'],
    'transmission': ['Automatic', 'Manual', 'Any transmission'],
}

class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    session_id: str = ''


def _fmt_money(value) -> str:
    try:
        return f"ETB {int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value or 0)


def _has(text: str, words) -> bool:
    return any(word in text for word in words)


def _has_word(text: str, words) -> bool:
    """Whole-word match — avoids substrings like 'hi' inside 'this'."""
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _parse_budget(text: str) -> Optional[float]:
    cleaned = text.lower()
    million = re.search(r"\b(\d[\d.]*)\s*(?:million)\b", cleaned)
    if million:
        try:
            return float(million.group(1)) * 1_000_000
        except ValueError:
            pass
    thousand = re.search(r"\b(\d[\d.]*)\s*k\b", cleaned)
    if thousand:
        try:
            value = float(thousand.group(1)) * 1000
            if value >= 1000:
                return value
        except ValueError:
            pass
    low = re.search(r"\b(\d[\d,.]*)\s*(?:-|\u2013|\u2014|to)\s*(\d[\d,.]*)\b", cleaned)
    if low:
        try:
            return max(
                float(low.group(1).replace(",", "")),
                float(low.group(2).replace(",", "")),
            )
        except ValueError:
            pass
    if re.search(r"\b(?:over|above|more than|at least)\b", cleaned):
        nums = []
        for token in re.findall(r"\b\d[\d,.]*\b", cleaned):
            try:
                nums.append(float(token.replace(",", "")))
            except ValueError:
                continue
        nums = [n for n in nums if n >= 1000]
        if nums:
            return max(nums) * 2
    for token in re.findall(r"\b\d[\d,.]*\b", cleaned):
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        if value >= 1000:
            return value
    return None


def _extract_fuel(text: str) -> str:
    if _has(text, ('diesel',)):
        return 'Diesel'
    if _has(text, ('petrol', 'gasoline', 'benzine')):
        return 'Petrol'
    if _has(text, ('cng',)):
        return 'CNG'
    return 'any'


def _extract_transmission(text: str) -> str:
    if _has(text, ('manual',)):
        return 'Manual'
    if _has(text, ('automatic', 'auto gear', 'auto', 'cvt')):
        return 'Automatic'
    return 'any'


def _extract_query(text: str) -> str:
    cleaned = text.lower()
    for prefix in (
        'do you have', 'have you got', 'are you selling', 'is there any',
        'looking for', 'search for', 'find me', 'show me', 'in stock',
        'price of', 'cost of', 'how much is', 'what is the price of',
        'i want to buy', 'i want to order', 'buy me', 'get me',
        'what about', 'i want', 'i need',
    ):
        index = cleaned.find(prefix)
        if index != -1:
            cleaned = cleaned[index + len(prefix):]
            break
    cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned.strip())
    return cleaned.strip(" ?!.,:;-")


def _recommend_cars(budget: Optional[float], fuel: str, transmission: str) -> List[dict]:
    if not car_catalog:
        return []
    pool = car_catalog
    if budget:
        in_budget = [car for car in pool if car['price'] <= budget]
        if not in_budget:
            return [min(pool, key=lambda c: c['price'])]
        pool = in_budget
    scored = []
    for car in pool:
        score = build_recommendation_score(car, budget or 0.0, fuel, transmission, None, None)
        scored.append((score, car))
    scored.sort(key=lambda pair: (pair[0], -pair[1]['popularity']), reverse=True)
    return [car for _, car in scored[:3]]


def _search_products(query: str, limit: int = 4) -> List[dict]:
    if not query:
        return []
    needle = query.lower()
    words = [w for w in needle.split() if len(w) > 1]
    hits = []
    seen = set()
    for product in PRODUCTS:
        haystack = ' '.join(
            str(x) for x in (
                product.get('title'), product.get('category'),
                product.get('tags'), product.get('shortDescription'),
                product.get('brand'),
            )
        ).lower()
        if needle in haystack or any(len(w) >= 4 and w in haystack for w in words):
            key = str(product.get('title')).lower()
            if key not in seen:
                seen.add(key)
                hits.append(product)
    for car in (car_catalog or []):
        haystack = ' '.join((car['title'], car['tags'])).lower()
        if needle in haystack or any(len(w) >= 4 and w in haystack for w in words):
            key = car['title'].lower()
            if key not in seen:
                seen.add(key)
                hits.append(car)
        if len(hits) >= limit:
            break
    return hits[:limit]


def _format_currency(value, currency: str = 'ETB') -> str:
    try:
        numeric = float(value or 0)
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
        'priceText': _format_currency(product.get('priceValue'), product.get('currency', 'ETB')),
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


_CATEGORY_ALIASES = {
    'phone': 'Mobile', 'phones': 'Mobile', 'smartphone': 'Mobile', 'smartphones': 'Mobile',
    'laptop': 'Electronics', 'laptops': 'Electronics', 'computer': 'Electronics',
    'computers': 'Electronics', 'electronics': 'Electronics', 'tech': 'Electronics', 'pc': 'Electronics',
    'headphone': 'Accessories', 'headphones': 'Accessories', 'accessory': 'Accessories',
    'accessories': 'Accessories',
    'watch': 'Wearables', 'watches': 'Wearables', 'wearable': 'Wearables', 'wearables': 'Wearables',
    'fashion': 'Fashion', 'clothes': 'Fashion', 'clothing': 'Fashion', 'jacket': 'Fashion',
    'jackets': 'Fashion', 'shoe': 'Fashion', 'shoes': 'Fashion',
    'car': 'Cars', 'cars': 'Cars', 'vehicle': 'Cars', 'vehicles': 'Cars',
    'suv': 'Cars', 'suvs': 'Cars', 'sedan': 'Cars', 'sedans': 'Cars', 'pickup': 'Cars',
}


def _category_for(text: str) -> Optional[str]:
    for key, category in _CATEGORY_ALIASES.items():
        if re.search(rf"\b{re.escape(key)}\b", text.lower()):
            return category
    return None


def _extract_product_like(text: str) -> str:
    cleaned = text.lower().strip()
    for prefix in (
        'do you have', 'is there any', 'is the', 'is a', 'are the', 'are there any',
        'do you sell', 'can i get', 'show me', 'view', 'i want a', 'i need a', 'i want',
        'i need', 'looking for', 'search for', 'find me', 'give me', 'price of',
        'cost of', 'how much is', 'is', 'are',
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    cleaned = cleaned.replace(' in stock', '').replace(' available', '').replace(' stock', '')
    cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned.strip())
    return cleaned.strip(" ?!.,:;-")


def _strip_buy_verbs(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = re.sub(r"\b(add (it )?to (the )?(cart|basket|bag))\b", " ", cleaned)
    cleaned = re.sub(r"^(i (want|would like|need|am going|will|wanna)\s+(to\s+)?|i'll )", "", cleaned)
    cleaned = re.sub(
        r"^(to\s+)?((buy|purchase|get|order|take|grab|add|pick\s+up)(\s+(me|it)\b)?)\s+",
        "", cleaned,
    )
    cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned.strip())
    return cleaned.strip(" ?!.,:;-")


def _find_by_words(words: List[str], limit: int = 4) -> List[dict]:
    hits = []
    seen = set()
    for product in PRODUCTS:
        haystack = ' '.join(str(x) for x in (
            product.get('title'), product.get('category'),
            product.get('tags'), product.get('brand'),
        )).lower()
        matched = [w for w in words if w in haystack]
        if matched:
            key = product['title'].lower()
            if key not in seen:
                seen.add(key)
                hits.append((len(matched), product))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [p for _, p in hits[:limit]]


def _format_hit(hit: dict) -> str:
    title = hit.get('title', '?')
    if hit.get('priceText'):
        price = str(hit['priceText'])
    elif hit.get('priceValue') is not None:
        price = _fmt_money(hit['priceValue'])
    else:
        price = _fmt_money(hit.get('price'))
    kind = hit.get('category') or hit.get('fuel') or ''
    return f"{title} — {price} · {kind}".rstrip(' ·')


# ---- response envelope ----------------------------------------------
# Every turn returns {reply, suggestions, cards, flow} (+ session_id at
# the endpoint). 'cards' are rich product/car cards the frontend renders
# inline; 'flow' drives the multi-step pickers.

def _response(reply, suggestions=None, cards=None, flow=None, action=None) -> dict:
    return {
        'reply': reply,
        'suggestions': suggestions or [],
        'cards': cards or [],
        'flow': flow,
        'action': action,
    }


def _text_reply(reply, suggestions=None, flow=None) -> dict:
    return _response(reply, suggestions=suggestions, flow=flow)


def _rich_reply(reply, cards, suggestions=None, flow=None, action=None) -> dict:
    return _response(reply, suggestions=suggestions, cards=cards, flow=flow, action=action)


# ---- sessions (multi-turn state) ------------------------------------

_sessions: Dict[str, dict] = {}
_SESSION_TTL = 60 * 20
_MAX_SESSIONS = 200


def _get_or_create_session(session_id: str):
    now = time.time()
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        if now - session.get('last', 0) > _SESSION_TTL:
            _sessions.pop(session_id, None)
            session = None
        else:
            session['last'] = now
            return session, session_id
    for key in [k for k, s in _sessions.items() if now - s.get('last', 0) > _SESSION_TTL]:
        _sessions.pop(key, None)
    if len(_sessions) >= _MAX_SESSIONS:
        oldest = min(_sessions, key=lambda k: _sessions[k].get('last', 0))
        _sessions.pop(oldest, None)
    session_id = secrets.token_hex(8)
    session = {
        'flow': None,
        'flow_step': None,
        'budget': None,
        'budget_done': False,
        'fuel': None,
        'fuel_done': False,
        'transmission': None,
        'transmission_done': False,
        'created': now,
        'last': now,
    }
    _sessions[session_id] = session
    return session, session_id


# ---- car recommendation flow ----------------------------------------

def _car_flow_prompt(session):
    step = session.get('flow_step')
    if step == 'budget':
        return (
            'budget',
            "Let's find your perfect car. 🚗 First — what's your budget?\n\n"
            "Pick an option below or type your own, like \"under 100,000\".",
            _FLOW_OPTIONS['budget'],
        )
    if step == 'fuel':
        return ('fuel', "Nice! Which fuel type do you prefer?", _FLOW_OPTIONS['fuel'])
    if step == 'transmission':
        return ('transmission', "Almost there — Manual or Automatic?", _FLOW_OPTIONS['transmission'])
    return None


def _car_results(session) -> dict:
    budget = session.get('budget')
    fuel = session.get('fuel') or 'any'
    transmission = session.get('transmission') or 'any'
    cars = _recommend_cars(budget, fuel, transmission)
    if not cars:
        return _text_reply(
            "I couldn't pull up car recommendations right now. Please try again in a moment.",
            ['What can you do?', "What's trending?"],
        )
    bits = []
    if budget:
        bits.append(f"budget up to {_fmt_money(budget)}")
    if fuel != 'any':
        bits.append(fuel)
    if transmission != 'any':
        bits.append(transmission)
    label = ', '.join(bits) if bits else 'for you'
    cards = [_car_card(c) for c in cars]
    if budget and all(c['price'] > budget for c in cars):
        reply = (
            f"Nothing in the catalog fits under about {_fmt_money(budget)} right now. "
            f"The closest match is the {cars[0]['title']} at {_fmt_money(cars[0]['price'])}:"
        )
    else:
        reply = f"Here are the best car matches ({label}):"
    reply += "\nTap a card to open it, or tell me to narrow it down."
    return _rich_reply(reply, cards, ['Under 100,000', 'Diesel automatic', "What's trending?"])


def _start_car_flow(message: str, session: dict) -> dict:
    budget = _parse_budget(message)
    fuel = _extract_fuel(message)
    transmission = _extract_transmission(message)
    session['budget'] = budget
    session['budget_done'] = budget is not None
    session['fuel'] = fuel
    session['fuel_done'] = fuel != 'any'
    session['transmission'] = transmission
    session['transmission_done'] = transmission != 'any'
    if session['budget_done'] and session['fuel_done'] and session['transmission_done']:
        session['flow'] = None
        session['flow_step'] = None
        return _car_results(session)
    session['flow'] = 'car'
    missing = []
    if not session['budget_done']:
        missing.append('budget')
    if not session['fuel_done']:
        missing.append('fuel')
    if not session['transmission_done']:
        missing.append('transmission')
    session['flow_step'] = missing[0]
    step, reply, options = _car_flow_prompt(session)
    return _text_reply(reply, options, flow={'step': step, 'options': options})


def _handle_car_flow(message: str, session: dict):
    text = message.lower()
    if _has(text, ('cancel', 'stop', 'never mind', 'forget it', 'quit', 'restart', 'start over', 'reset')):
        session['flow'] = None
        session['flow_step'] = None
        session['budget'] = None
        session['budget_done'] = False
        session['fuel'] = None
        session['fuel_done'] = False
        session['transmission'] = None
        session['transmission_done'] = False
        return _text_reply(
            "No problem — I've reset the search. What would you like to do next?",
            ['Recommend a car', 'What can you do?', "What's trending?"],
        )
    if _has_word(text, ('hi', 'hello', 'hey', 'selam', 'salam', 'hola')) or _has(
        text, ('what can you do', 'help', 'contact', 'support', 'thank', 'joke')
    ):
        return None

    step = session.get('flow_step')
    if step == 'budget':
        budget = _parse_budget(message)
        if budget is not None:
            session['budget'] = budget
            session['budget_done'] = True
        elif _has(text, ('no limit', 'any budget', 'dont care', "don't care", 'whatever', 'any')):
            session['budget'] = None
            session['budget_done'] = True
        else:
            return _text_reply(
                "Sorry, I didn't catch a budget there. Try something like \"under 100,000\", or pick one below:",
                _FLOW_OPTIONS['budget'],
                flow={'step': 'budget', 'options': _FLOW_OPTIONS['budget']},
            )
    elif step == 'fuel':
        fuel = _extract_fuel(message)
        if fuel != 'any':
            session['fuel'] = fuel
            session['fuel_done'] = True
        elif _has(text, ('any fuel', 'dont care', "don't care", 'whatever', 'no preference', 'any')):
            session['fuel'] = 'any'
            session['fuel_done'] = True
        else:
            return _text_reply(
                "Which fuel type do you prefer — Petrol, Diesel, or CNG? (or \"any fuel\")",
                _FLOW_OPTIONS['fuel'],
                flow={'step': 'fuel', 'options': _FLOW_OPTIONS['fuel']},
            )
    elif step == 'transmission':
        transmission = _extract_transmission(message)
        if transmission != 'any':
            session['transmission'] = transmission
            session['transmission_done'] = True
        elif _has(text, ('any transmission', 'any', 'dont care', "don't care", 'whatever', 'no preference')):
            session['transmission'] = 'any'
            session['transmission_done'] = True
        else:
            return _text_reply(
                "Manual or Automatic? (or \"any transmission\")",
                _FLOW_OPTIONS['transmission'],
                flow={'step': 'transmission', 'options': _FLOW_OPTIONS['transmission']},
            )
    else:
        return None

    missing = []
    if not session['budget_done']:
        missing.append('budget')
    if not session['fuel_done']:
        missing.append('fuel')
    if not session['transmission_done']:
        missing.append('transmission')
    if missing:
        session['flow_step'] = missing[0]
        step, reply, options = _car_flow_prompt(session)
        return _text_reply(reply, options, flow={'step': step, 'options': options})

    session['flow'] = None
    session['flow_step'] = None
    return _car_results(session)


def _llm_reply(message: str, session: dict, history: List[dict]):
    """Phase 2 hook — swap in an LLM adapter (OpenAI / Gemini / local) here.

    Return a _response() dict, or None to fall back to the deterministic
    intent engine. The /api/chat contract must stay identical.
    """
    return None


def _kb_reply(message: str, session: dict, history: List[dict]):
    """Answer from uploaded knowledge BEFORE falling back to rule intents.

    Returns None when the knowledge base has no confident match, so the
    caller falls through to the deterministic intents / catalog lookup.
    """
    if not message.strip():
        return None
    threshold = float(os.environ.get('KB_MIN_SCORE', '1.6'))
    results = kb.search(message, limit=4)
    if not results:
        return None
    top = results[0]
    if top.get('score', 0) < threshold:
        return None
    title = (top.get('title') or '').strip()
    body = (top.get('content') or '').strip()
    if not body:
        return None
    if len(body) > 700:
        body = body[:700].rstrip() + '…'
    header = f"📚 **{title}**" if title else "📚 From your knowledge base:"
    import datetime as _dt
    updated = ''
    if top.get('updated_at'):
        updated = ' · updated ' + _dt.datetime.fromtimestamp(
            top['updated_at']).strftime('%Y-%m-%d')
    source = top.get('source')
    attribution = f"\n\n— source: {source}{updated}" if (source or updated) else ''
    return _text_reply(
        header + "\n\n" + body + attribution,
        ['What can you do?', 'Recommend a car', 'Contact us'],
    )


def _chat_reply(message: str, session: dict, history: List[dict]) -> dict:
    if CHAT_BACKEND == 'llm':
        llm_result = _llm_reply(message, session, history)
        if llm_result is not None:
            return llm_result

    text = message.lower().strip()

    # Active multi-step flow takes priority.
    if session.get('flow') == 'car':
        flow_result = _handle_car_flow(message, session)
        if flow_result is not None:
            return flow_result

    # Knowledge Base first: answer from the latest uploaded knowledge before
    # any rule-based (general) knowledge.
    kb_result = _kb_reply(message, session, history)
    if kb_result is not None:
        return kb_result

    # ---- intents -----------------------------------------------------

    if _has(text, ('cancel', 'start over', 'forget it', 'never mind', 'reset')):
        session['flow'] = None
        session['flow_step'] = None
        session['budget'] = None
        session['budget_done'] = False
        session['fuel'] = None
        session['fuel_done'] = False
        session['transmission'] = None
        session['transmission_done'] = False
        return _text_reply(
            "Okay — I've cleared the current search. What would you like to do?",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )

    if _has(text, ('bye', 'goodbye', 'see you', 'ttyl', 'good night', 'adios', 'ciao')):
        session['flow'] = None
        return _text_reply("Goodbye! Come back anytime — I'll be here if you need help. 👋", [])

    if _has(text, ('thank', 'thx', 'appreciate', 'nice work', 'good job', 'you are the best', 'thanks')):
        return _text_reply(
            "You're welcome! 😊 Is there anything else I can help you with?",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )

    if _has(text, ('how are you', 'how r u', "how's it going", 'how is it going', 'you ok', 'you okay', 'whats up', 'what up', 'wassup', 'how are you doing')):
        return _text_reply(
            "I'm doing great — busy browsing the catalog! 😄 How can I help you today?",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )

    if _has(text, ('who are you', 'your name', 'what is your name', "what's your name", 'whats your name')):
        return _text_reply(
            "I'm Obama — the AI assistant of Obama Store. 🤖 I help shoppers find products, "
            "pick cars within a budget, and get answers about the store.",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )

    if _has(text, ('who made you', 'who built you', 'who created you', 'your developer', 'your creator',
                   'who is your boss', 'obama abraham', 'who owns the store', 'who runs this', 'developer')):
        return _text_reply(
            f"Obama Store was created by {STORE_CONTACT['developer']}. 🧑‍💻\n\n"
            f"📞 Phone: {STORE_CONTACT['phones']}\n"
            f"✉️ Email: {STORE_CONTACT['email']}\n\n"
            "You can also open the Contact page for the quickest response.",
            ['Contact us', 'What can you do?', 'Recommend a car'],
        )

    if _has_word(text, ('phone', 'call', 'email', 'telegram', 'agent', 'human', 'support', 'contact', 'reach')) or _has(
        text, ('customer service', 'get in touch', 'how do i contact', 'contact us', 'talk to')
    ):
        return _text_reply(
            f"Here's how to reach us:\n\n"
            f"📞 Phone / Telegram: {STORE_CONTACT['phones']}\n"
            f"✉️ Email: {STORE_CONTACT['email']}\n"
            f"📍 {STORE_CONTACT['city']}\n\n"
            "We reply 24/7 — or use the Contact page for the quickest route.",
            ['Return policy', 'What can you do?', 'Recommend a car'],
        )

    if _has(text, ('what can you do', 'capabilities', 'help menu', 'help me', 'how do you work',
                   'what do you do', 'your features', 'options')):
        return _text_reply(
            "Here's what I can help with:\n\n"
            "🛍️  Find products — \"do you have a MacBook?\"\n"
            "🚗  Car recommendations — \"recommend a diesel car under 100,000\"\n"
            "📈  Trending — \"what's trending?\"\n"
            "🏷️  Deals — \"any discounts?\"\n"
            "📦  Delivery — \"how long is delivery?\"\n"
            "💳  Payment — \"how do I pay?\"\n"
            "↩️  Returns — \"what's your return policy?\"\n"
            "📞  Support — \"how do I contact you?\"",
            ['Recommend a car', "What's trending?", 'Show me phones'],
        )

    if _has_word(text, ('hi', 'hello', 'hey', 'selam', 'salam', 'hola', 'good morning', 'good afternoon', 'good evening')):
        return _text_reply(
            "Hello! I'm Obama, your store assistant. 🤖 I can find products, recommend cars within "
            "your budget, show what's trending, and answer questions about delivery, payment and "
            "returns. What would you like to do?",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )

    if _has(text, ('recommend a car', 'car recommendation', 'which car', 'what car', 'suggest a car',
                   'help me choose a car', 'best car', 'car for me', 'car under', 'cars under')):
        return _start_car_flow(message, session)

    budget = _parse_budget(text)
    fuel = _extract_fuel(text)
    transmission = _extract_transmission(text)
    wants_car = _has(text, ('car', 'suv', 'sedan', 'pickup', 'vehicle', 'hatchback')) and (
        _has(text, ('recommend', 'budget', 'under', 'afford', 'cheap', 'suggest', 'which', 'within'))
        or budget is not None
    )
    car_refine = budget is not None or fuel != 'any' or transmission != 'any'
    if wants_car or (car_refine and _has(text, (
        'car', 'recommend', 'budget', 'under', 'fuel', 'diesel', 'petrol', 'cng',
        'transmission', 'automatic', 'manual', 'auto', 'suv', 'sedan',
    ))):
        return _start_car_flow(message, session)

    if _has(text, ('trending', 'popular', 'best seller', 'best-selling', 'top selling', 'what sells', 'top rated', 'best rated')):
        trending = []
        if car_catalog:
            trending = sorted(car_catalog, key=lambda c: (c['popularity'], -c['car_age'], c['price']), reverse=True)[:3]
        if not trending:
            return _text_reply("Trending data is unavailable right now — try asking about products instead.", ['Show me phones', 'Recommend a car'])
        cards = [_car_card(c) for c in trending]
        return _rich_reply(
            "Here are the currently trending cars 🔥:\nTap a card to view it.",
            cards,
            ['Recommend a car', 'Under 100,000'],
        )

    if _has(text, ('good deal', 'fair price', 'overpriced', 'value', 'negotiat', 'worth it', 'best value', 'best bang', 'value pick')):
        if car_catalog:
            ranked = sorted(car_catalog[:40], key=lambda c: (c['price'] / max(c['predicted_price'], 1), -c['popularity']))[:3]
            best = ranked[0]
            reply = (
                f"Every car is checked against an ML fair-price model. Right now the best value pick is "
                f"**{best['title']}** — listed at {_fmt_money(best['price'])} vs a predicted fair price of "
                f"{_fmt_money(best['predicted_price'])}.\n\nHere are the top value picks:"
            )
            return _rich_reply(reply, [_car_card(c) for c in ranked], ['Recommend a car', "What's trending?"])
        return _text_reply("I can't check values right now — ask me to recommend a car instead.", ['Recommend a car'])

    if _has(text, ('deal', 'discount', 'offer', 'promo', 'sale', 'on sale')):
        deals = [p for p in PRODUCTS if (p.get('discount') or 0) > 0]
        if deals:
            deals.sort(key=lambda p: p.get('discount', 0), reverse=True)
            lines = ["Here are the best active deals 🏷️:"]
            for d in deals[:4]:
                lines.append(f"{d['title']} — {d['discount']}% off ({_format_currency(d['priceValue'], d.get('currency', 'ETB'))})")
            return _rich_reply('\n'.join(lines), [_product_card(p) for p in deals[:4]], ['Show me phones', 'Recommend a car'])
        return _text_reply("No special offers right now, but check the catalog for fresh drops!", ['Show me phones', 'Recommend a car'])

    if _has(text, ('payment', 'pay', 'telebirr', 'cbe pay', 'cbebirr', 'how do i pay', 'payment method', 'mobile money', 'm-pesa')):
        return _text_reply(
            "We accept Telebirr, CBE Pay, and cash on delivery. 💳 Mobile payments are processed "
            "securely at checkout. Want details on a specific option?",
            ['Return policy', 'Contact us'],
        )

    if _has(text, ('ship', 'deliver', 'delivery', 'how long')):
        return _text_reply(
            "We deliver across Ethiopia — Addis Ababa usually within 1–3 business days, and other "
            "regions in 3–7 days. Delivery is confirmed with you before checkout.",
            ['How do I pay?', 'Return policy'],
        )

    if _has(text, ('return', 'refund', 'exchange', 'money back')):
        return _text_reply(
            "Easy returns: contact us within 7 days of delivery and we'll arrange a return or exchange. "
            "Items must be in original condition with packaging.",
            ['Contact us', 'How do I pay?'],
        )

    if _has(text, ('hour', 'hours', 'what time', 'when do you open', 'when are you open',
                   'are you open', 'open now', 'closed', 'closing time', 'working time')):
        return _text_reply(
            "Our support team is available 24/7. Order processing runs Monday–Saturday, 9:00–18:00 (EAT).",
            ['Contact us'],
        )

    if _has(text, ('login', 'log in', 'sign in', 'sign up', 'account', 'register', 'create account', 'profile')):
        return _text_reply(
            "Use the \"Sign in\" button in the top bar — or open My Account — to sign in or create an "
            "account. Accounts sync your cart, wishlist and profile across devices.",
            ['My Account', 'What can you do?'],
        )

    if _has(text, ('cart', 'wishlist', 'favorite', 'favourite', 'saved items')):
        return _text_reply(
            "Your cart and wishlist are saved automatically and survive a page refresh. Open the 🛒 Cart "
            "or ♥ Wishlist icons in the top bar to review them.",
            ['Checkout', 'My Account'],
        )

    if _has(text, ('track my order', 'order status', 'where is my order', 'my order', 'order number', 'track')):
        return _text_reply(
            "To track an order, open My Account → Order History — or reply with your order number and "
            "I'll look it up. Orders usually update within minutes of shipping.",
            ['My Account', 'Contact us'],
        )

    if _has(text, ('warranty', 'guarantee', 'guaranteed', 'defect', 'broken')):
        return _text_reply(
            "Every product includes the manufacturer warranty, and cars come with a verified-ownership "
            "guarantee. If anything is defective on arrival, we'll replace or repair it free within 7 days.",
            ['Return policy', 'Contact us'],
        )

    if _has(text, ('secure', 'security', 'safe', 'trust', 'authentic', 'legit', 'trustworthy')):
        return _text_reply(
            "Good question! 🔒 Payments are processed securely, products are checked for authenticity "
            "before dispatch, and your data is never shared. We're transparent about every car's history too.",
            ['Payment options', 'Return policy', 'Contact us'],
        )

    if _has(text, ('negotiat', 'price match', 'bargain', 'lower price', 'flexible price', 'discount on cars')):
        return _text_reply(
            f"Every car is priced against an ML fair-price model, but we're open to reasonable offers. "
            f"📞 Call us at {STORE_CONTACT['phones']} to discuss a deal on any listing.",
            ['Recommend a car', 'Contact us'],
        )

    if _has(text, ('about the store', 'about us', 'what is obama store', 'about obama store', 'tell me about the store', 'your store', 'this store', 'what is this')):
        return _text_reply(
            f"Obama Store is an Ethiopian e-commerce platform created by {STORE_CONTACT['developer']}. 🇪🇹\n"
            "We sell electronics, mobile, fashion, wearables, accessories and verified used cars — every "
            "car checked against an ML fair-price model.\n\n"
            f"📞 {STORE_CONTACT['phones']}\n✉️ {STORE_CONTACT['email']}",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )

    if _has(text, ('joke', 'funny', 'laugh', 'make me laugh', 'entertain')):
        jokes = [
            "Why did the car go to therapy? It had too many breakdowns! 🚗💨",
            "I asked for a cheap, reliable car — the salesman handed me a cat and said \"it always lands on its feet\". 🐱",
            "Why don't phones ever get cold? They always have their cases on. 📱",
            "My laptop asked for a raise — I said no, you've been blue-screening too much. 💻",
        ]
        return _text_reply(random.choice(jokes), ['Another joke 😄', 'What can you do?', 'Recommend a car'])

    if _has(text, ('compare', ' vs ', 'versus', 'difference between', 'which is better', 'which is best', 'better buy')):
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]
        stop = {
            'the', 'and', 'for', 'with', 'between', 'which', 'better', 'best', 'compare', 'versus',
            'difference', 'what', 'about', 'show', 'me', 'how', 'much', 'is', 'are', 'a', 'an', 'than',
            'on', 'of', 'to', 'or', 'you', 'buy', 'vs',
        }
        words = [w for w in words if w not in stop]
        hits = _find_by_words(words)
        if len(hits) >= 2:
            return _rich_reply(
                f"Here's a quick comparison of **{hits[0]['title']}** vs **{hits[1]['title']}**:",
                [_product_card(h) for h in hits[:2]],
                ['Recommend a car', 'What can you do?'],
            )
        if len(hits) == 1:
            return _rich_reply(
                f"I could match **{hits[0]['title']}** — name the second product to compare, e.g. \"vs iPhone 15 Pro Max\".",
                [_product_card(hits[0])],
                ['Show me phones', 'Recommend a car'],
            )
        return _text_reply(
            "I can compare two products — try \"compare iPhone 15 Pro Max vs Samsung Galaxy\".",
            ['Show me phones', 'Recommend a car'],
        )

    category = _category_for(text)
    if category and (
        _has(text, ('show', 'browse', 'list', 'category', 'all', 'any', 'i want', 'i need', 'give me', 'looking for'))
        or _category_for(_extract_product_like(text)) == category
    ):
        products = [p for p in PRODUCTS if p.get('category') == category]
        if products:
            return _rich_reply(
                f"Here's what we have in **{category}**:",
                [_product_card(p) for p in products[:6]],
                ['Recommend a car', "What's trending?"],
            )

    if _has(text, ('stock', 'available', 'availability', 'in stock', 'out of stock', 'do you have it')):
        query = _extract_product_like(message)
        hits = _search_products(query) if query else []
        if hits:
            lines = []
            cards = []
            for h in hits[:3]:
                if h.get('priceValue') is not None:
                    stock = h.get('stock')
                    if stock is None:
                        state = 'in stock'
                    elif stock > 0:
                        state = f'in stock ({stock} left)'
                    else:
                        state = 'currently out of stock'
                    lines.append(f"{h['title']}: {state}.")
                    cards.append(_product_card(h))
                else:
                    lines.append(f"{h['title']}: in stock.")
            return _rich_reply('\n'.join(lines), cards, ['Show me more', 'Recommend a car'])
        return _text_reply(
            "Everything shown in the catalog is available to order. Want me to check a specific product?",
            ['Recommend a car', 'What can you do?'],
        )

    query = _extract_query(message) or _extract_product_like(text)
    if _has(text, ('have you', 'do you have', 'search', 'find', 'looking for', 'product', 'sell',
                   'in stock', 'price of', 'cost of', 'how much is', 'i want', 'i need', 'show', 'price')):
        if not query:
            return _text_reply(
                "Sure — tell me the product name, like \"do you have a MacBook?\" or \"iPhone 15\".",
                ['Show me phones', 'Show me laptops', 'Recommend a car'],
            )
        hits = _search_products(query)
        if not hits:
            return _text_reply(
                f"I couldn't find \"{query}\" — but I can look by category. Try \"show me phones\" or \"show me laptops\".",
                ['Show me phones', 'Show me laptops', 'Recommend a car'],
            )
        return _rich_reply(
            f"I found these matches for \"{query}\":",
            [_hit_card(h) for h in hits],
            ['Recommend a car', "What's trending?"],
        )

    if _has(text, ('help', 'assist')):
        return _text_reply(
            "I'm here to help! Ask me about products, car recommendations, delivery, payment, returns, or contact info.",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )

    # Last chance before the generic fallback: treat the message as a
    # product search ("iphone 15", "corolla", "sony headphones"…).
    query = _extract_product_like(text)
    hits = _search_products(query) if query else []
    if hits:
        return _rich_reply(
            f"I found these matches for \"{query}\":",
            [_hit_card(h) for h in hits],
            ['Recommend a car', "What's trending?"],
        )

    return _text_reply(
        "I'm not sure I caught that. 🤔 But here's what I'm great at — try one of these:\n"
        "• \"do you have a MacBook?\"\n"
        "• \"recommend a diesel car under 100,000\"\n"
        "• \"how do I pay?\"\n"
        "• \"how do I contact you?\"",
        ['What can you do?', 'Recommend a car', "What's trending?"],
    )


@app.post('/api/chat')
async def chat(req: ChatRequest) -> dict:
    message = (req.message or '').strip()
    session, session_id = _get_or_create_session(req.session_id or '')
    if not message:
        return {
            'session_id': session_id,
            'reply': "Hi! I'm Obama. 👋 What would you like to do?",
            'suggestions': ['What can you do?', 'Recommend a car', "What's trending?"],
            'cards': [],
            'flow': None,
        }
    if len(message) > 2000:
        message = message[:2000]
    try:
        result = _chat_reply(message, session, req.history or [])
    except Exception:
        result = _response(
            "I ran into a tiny hiccup — but I'm still here! 🤖 Ask me about products, cars, delivery or payment.",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )
    result['session_id'] = session_id
    return result


# Mount static files last so API routes above are matched first.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
