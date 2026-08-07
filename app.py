from pathlib import Path
from typing import List, Optional
import asyncio
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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from recommend_engine import PRODUCTS, RecommendationEngine
from knowledge import KnowledgeBase
import assistant

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "CAR.csv"
MODEL_FILE = BASE_DIR / "car_price_model.pkl"
STATIC_DIR = BASE_DIR

# Optional .env file for OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL etc.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

app = FastAPI(
    title="Obama Store API",
    description="Backend API for the Obama Store — car recommender powered by a local CSV dataset and ML model, plus the AI product recommendation engine."
)

# Allow the frontend to call the API from any origin (localhost, file://,
# or another machine on the network) without CORS errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Body-style classifier used to make car filters (SUV / Sedan / Hatchback /
# MUV / Luxury) actually run. Values are looked up in order; the most
# specific longer hints come first so e.g. "Swift Dzire" lands on Sedan.
_CAR_TYPE_HINTS = {
    'SUV': (
        'creta', 'brezza', 'vitara', 'venue', 'nexon', 'punch', 'harrier',
        'safari', 'scorpio', 'bolero', 'xuv', 'thar', 'compass', 'wrangler',
        'fortuner', 'prado', 'land cruiser', 'landcruiser', 'endeavour',
        'endeavor', 'captiva', 'seltos', 'sonet', 'tucson', 'sportage',
        'duster', 'kushaq', 'tiguan', 'taigun', 's-cross', 'sx4', 'ecosport',
        'eco sport', 'wr-v', 'br-v', 'brv', 'montero', 'pajero', 'kodiaq',
        'hector', 'evoque', 'discovery', 'defender', 'range rover',
        'highlander', 'outlander', 'cr-v', 'gloster', 'gurkha', 'kuv', 'tuv',
        'alcazar', 'mu-x', 'kiger', 'magnite', 'x1', 'x3', 'x5', 'x7', 'q5',
        'q7', 'gl-class', 'g-class', 'gls', 'gle', 'c3 aircross', 'suv',
    ),
    'Sedan': (
        'corolla', 'civic', 'amaze', 'aura', 'dzire', 'aspire', 'tigor',
        'vento', 'rapid', 'octavia', 'superb', 'c-class', 'c 220', 'c 200',
        'a4', 'a6', '3 series', '5 series', 'jaguar xf', 'vectra', 'astra',
        'logan', 'verito', 'sunny', 'scala', 'etios', 'yaris', 'indigo',
        'zest', 'linea', 'fiesta', 'cielo', 'accord', 'camry', 'accent',
        'slavia', 'virtue', 'xcent', 'verna', 'city', 'sedan', 'saloon',
    ),
    'Hatchback': (
        'alto', 'wagon r', 'wagonr', 'i10', 'i20', 'polo', 'swift', 'ritz',
        'celerio', 'k10', 'spark', 'tiago', 'punto', 'figo', 'micra',
        'kwid', 'ignis', 'baleno', 's-presso', 'presso', 'santro', 'eon',
        'beat', 'bolt', 'fabia', 'nano', 'redigo', 'redi-go', 'altroz',
        'elia', 'k12', 'c3', 'up', 'go+', 'go t', 'hatch', 'hatchback',
        '800',
    ),
    'MUV': (
        'innova', 'ertiga', 'eeco', 'omni', 'supro', 'marazzo', 'xylo',
        'tavera', 'enjoy', 'traveler', 'touristo', 'avanza', 'carens',
        'xl6', 'sumo', 'muv', 'mpv', 'van',
    ),
    'Luxury': (
        'mercedes', 'benz', 'bmw', 'audi', 'jaguar', 'volvo', 'lexus',
        'porsche', 'maserati', 'range rover', 'bentley', 'rolls',
        'luxury', 'premium',
    ),
}


def _car_type(title: str) -> str:
    """Best-effort body style for a car title, e.g. 'SUV', 'Sedan'."""
    normalized = (title or '').lower()
    for kind, hints in _CAR_TYPE_HINTS.items():
        for hint in hints:
            if hint in normalized:
                return kind
    return ''


_FUEL_CHOICES = ('Petrol', 'Diesel', 'CNG', 'LPG', 'Electric', 'Hybrid')


def _normalize_car_filter(value: str, choices: tuple) -> str:
    """Map a user/model filter value onto a known choice, else 'any'."""
    if not value:
        return 'any'
    cleaned = ' '.join(str(value).lower().split())
    if (cleaned in ('', 'any', 'all', 'both')
            or cleaned.startswith('any') or cleaned.startswith('all')
            or cleaned.startswith('no ') or cleaned.startswith('no-preference')
            or 'no preference' in cleaned):
        return 'any'
    for choice in choices:
        if choice.lower() in cleaned or cleaned in choice.lower():
            return choice
    # common synonyms
    synonyms = {
        'auto': 'Automatic', 'automatic': 'Automatic', 'at': 'Automatic',
        'manual': 'Manual', 'mt': 'Manual',
        'petrol': 'Petrol', 'gasoline': 'Petrol', 'gas': 'Petrol',
        'diesel': 'Diesel', 'cng': 'CNG', 'lpg': 'LPG', 'gas': 'Petrol',
        'electric': 'Electric', 'ev': 'Electric', 'hybrid': 'Hybrid',
        'suv': 'SUV', 'sedan': 'Sedan', 'hatchback': 'Hatchback',
        'hatch': 'Hatchback', 'mpv': 'MUV', 'muv': 'MUV', 'van': 'MUV',
        'luxury': 'Luxury', 'premium': 'Luxury',
    }
    return synonyms.get(cleaned, cleaned.title())


def build_car_record(row: pd.Series, predicted_price: float) -> dict:
    car_age = pd.Timestamp.now().year - int(row['year'])
    tags = f"{row['name']} {row['fuel']} {row['transmission']} {row['seller_type']} {row['owner']}"
    return {
        'id': int(row.name),
        'title': str(row['name']),
        'type': _car_type(str(row['name'])),
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


def build_recommendation_score(car: dict, budget: float, fuel: str, transmission: str, km: Optional[int], age: Optional[int]) -> float:
    score = 0.0
    predicted = float(car.get('predicted_price') or 0)
    if budget and budget > 0:
        budget_gap = abs(predicted - budget) / max(budget, 1)
        score += max(0.0, 40.0 - budget_gap * 40.0)
    else:
        score += 10.0

    car_fuel = str(car.get('fuel') or '')
    if fuel != 'any' and fuel == car_fuel:
        score += 20.0
    elif fuel == 'any':
        score += 8.0

    car_transmission = str(car.get('transmission') or '')
    if transmission != 'any' and transmission == car_transmission:
        score += 16.0
    elif transmission == 'any':
        score += 6.0

    if km is not None and float(car.get('km') or 0) <= km:
        score += 10.0

    car_age = float(car.get('car_age') or 0)
    if age is not None and car_age <= age:
        score += 8.0

    if str(car.get('owner') or '').lower() == 'first owner':
        score += 5.0

    score += max(0.0, 6.0 - car_age * 0.15)
    score += min(10.0, float(car.get('popularity') or 0) * 0.1)
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
    assistant.configure(
        car_catalog_getter=lambda: car_catalog,
        kb=kb,
        contact=STORE_CONTACT,
        recommend_cars_fn=_recommend_cars,
    )
    # Predictions are baked into the catalog; drop the training model to free
    # memory on low-RAM machines (the gradient boosting pipeline can be large).
    model = None
    car_values = None
    import gc
    gc.collect()


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
# Hybrid brain: the modular assistant (assistant.py) is the default when
# an OPENAI_API_KEY is configured — it answers general questions with the
# LLM, uses RAG + tools for store data, and keeps per-session memory.
# Any failure (no key, timeout, error) falls back to the deterministic
# intent engine below, which always runs offline with the store's own
# data (PRODUCTS, car_catalog, FAQs, contact info).
# ------------------------------------------------------------------

CHAT_BACKEND = os.environ.get('CHAT_BACKEND', 'llm')

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
    cart: List[dict] = []   # optional: browser cart state for get_cart_summary


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


def _recommend_cars(budget: Optional[float] = None, fuel: str = 'any',
                    transmission: str = 'any', keyword: str = '') -> List[dict]:
    """Return the 3 best cars matching the requested criteria.

    Filters are applied strictly: a requested fuel, transmission, body type
    or keyword narrows the pool, so "a diesel SUV under 3 million" only ever
    returns diesel SUVs under budget. If a filter would empty the pool, an
    empty list is returned so callers can fall back gracefully.
    """
    if not car_catalog:
        return []
    pool = car_catalog

    fuel_norm = _normalize_car_filter(fuel, _FUEL_CHOICES)
    transmission_norm = _normalize_car_filter(transmission, ('Manual', 'Automatic'))

    keyword = (keyword or '').strip()
    if keyword:
        lowered = keyword.lower()
        words = [w for w in lowered.split() if len(w) > 2]
        type_norm = _normalize_car_filter(lowered, tuple(_CAR_TYPE_HINTS))
        kw_pool = []
        for car in pool:
            if not isinstance(car, dict):
                continue
            title = str(car.get('title') or '')
            tags = ' '.join(str(t) for t in (car.get('tags') or []))
            haystack = f"{title} {tags}".lower()
            car_type = str(car.get('type') or '').lower()
            if lowered in haystack or type_norm != 'any' and car_type == type_norm.lower():
                kw_pool.append(car)
                continue
            if any(w in haystack for w in words):
                kw_pool.append(car)
        if kw_pool:
            pool = kw_pool

    if fuel_norm != 'any':
        fuel_pool = [car for car in pool
                     if str(car.get('fuel', '')).lower() == fuel_norm.lower()]
        if fuel_pool:
            pool = fuel_pool
        else:
            return []

    if transmission_norm != 'any':
        trans_pool = [car for car in pool
                      if str(car.get('transmission', '')).lower() == transmission_norm.lower()]
        if trans_pool:
            pool = trans_pool
        else:
            return []

    if not pool:
        return []

    if budget:
        in_budget = [car for car in pool if float(car.get('price') or 0) <= budget]
        if in_budget:
            pool = in_budget

    scored = []
    for car in pool:
        score = build_recommendation_score(
            car, budget or 0.0, fuel_norm, transmission_norm, None, None)
        scored.append((score, car))
    scored.sort(key=lambda pair: (pair[0], -float(pair[1].get('popularity') or 0)), reverse=True)
    return [car for _, car in scored[:3]]


def _search_products(query: str, limit: int = 4) -> List[dict]:
    if not query:
        return []
    needle = query.lower()
    words = [w for w in needle.split() if len(w) > 1]
    hits = []
    seen = set()
    for product in PRODUCTS:
        if not isinstance(product, dict):
            continue
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
        if not isinstance(car, dict):
            continue
        title = str(car.get('title') or '')
        tags = ' '.join(str(t) for t in (car.get('tags') or []))
        haystack = ' '.join((title, tags)).lower()
        if needle in haystack or any(len(w) >= 4 and w in haystack for w in words):
            key = title.lower()
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


def _open_product_action(hits: List[dict]):
    if len(hits) == 1 and hits[0].get('priceValue') is not None and hits[0].get('id'):
        return {'type': 'open_product', 'productId': hits[0]['id']}
    return None


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
    """Hybrid AI brain — delegates to the modular assistant (assistant.py).

    Returns a _response()-compatible dict, or None to fall back to the
    deterministic intent engine (no API key, offline, or any failure).
    """
    return assistant.answer(message, session, history)


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


# ---- offline general knowledge (no LLM required) ----------------------
# Deterministic answers to common general questions so the bot can talk
# about non-store topics even while the LLM is rate-limited or unreachable.
# Anything not covered here falls through to the LLM as before.

_GENERAL_DEFS = {
    # science / space
    "gravity": "Gravity is the force that pulls objects with mass toward each other. On Earth it makes things fall at about 9.8 m/s².",
    "photosynthesis": "Photosynthesis is how plants make food — they turn sunlight, water and CO₂ into glucose and release oxygen as a byproduct.",
    "speed of light": "The speed of light in a vacuum is about 299,792 km per second — roughly 300,000 km/s. Nothing in the universe travels faster.",
    "big bang": "The Big Bang theory says the universe began expanding from an extremely hot, dense state about 13.8 billion years ago.",
    "black hole": "A black hole is a region of space where gravity is so strong that not even light can escape it.",
    "water": "Water is a molecule of two hydrogen atoms and one oxygen atom (H₂O). It covers about 71% of Earth's surface.",
    "dna": "DNA is the molecule that carries the genetic instructions for life. A single human cell holds about 2 meters of it.",
    "atom": "An atom is the smallest unit of an element — a nucleus of protons and neutrons surrounded by electrons.",
    "evolution": "Evolution is the process by which species change over generations through natural selection, first described by Charles Darwin.",
    "artificial intelligence": "Artificial intelligence (AI) is software that can learn, reason and make decisions — like me! 🤖",
    "ai": "Artificial intelligence (AI) is software that can learn, reason and make decisions — like me! 🤖",
    "internet": "The internet is a worldwide network of connected computers that lets us share information — it grew out of ARPANET in 1969.",
    "computer": "A computer is a machine that processes data by executing instructions. The first electronic computers filled entire rooms.",
    "energy": "Energy is the ability to do work. It comes in many forms — kinetic, thermal, chemical, electrical and more — but can't be created or destroyed.",
    "sound": "Sound is a vibration that travels through air (or other matter) as waves. In air it moves at about 343 m/s.",
    "thunder": "Thunder is the shockwave of air rapidly expanding when lightning heats it to about 30,000°C.",
    "electricity": "Electricity is the flow of electric charge, usually electrons. It travels through wires at nearly the speed of light.",
    "magnetism": "Magnetism is the force produced by moving electric charges. Earth itself acts like a giant magnet.",
    "planet": "A planet is a large body that orbits a star, is round from its own gravity, and has cleared its orbit of debris.",
    "sun": "The Sun is a star at the center of our solar system. It's about 4.6 billion years old and holds 99.86% of the system's mass.",
    "moon": "The Moon is Earth's natural satellite — 384,400 km away, and the only other world humans have walked on.",
    "galaxy": "A galaxy is a huge collection of stars, gas and dust bound by gravity. Our Milky Way alone has hundreds of billions of stars.",
    "universe": "The universe is everything that exists — all space, time, matter and energy. It's about 13.8 billion years old.",
    "star": "A star is a glowing ball of gas that shines by nuclear fusion in its core — like our Sun.",
    # geography
    "capital of france": "The capital of France is **Paris** 🇫🇷 — the City of Light.",
    "capital of ethiopia": "The capital of Ethiopia is **Addis Ababa** 🇪🇹.",
    "capital of japan": "The capital of Japan is **Tokyo**.",
    "capital of the united states": "The capital of the United States is **Washington, D.C.**",
    "capital of the usa": "The capital of the United States is **Washington, D.C.**",
    "capital of the uk": "The capital of the United Kingdom is **London**.",
    "capital of china": "The capital of China is **Beijing**.",
    "capital of russia": "The capital of Russia is **Moscow**.",
    "capital of egypt": "The capital of Egypt is **Cairo**.",
    "capital of germany": "The capital of Germany is **Berlin**.",
    "capital of italy": "The capital of Italy is **Rome**.",
    "capital of kenya": "The capital of Kenya is **Nairobi**.",
    "capital of nigeria": "The capital of Nigeria is **Abuja**.",
    "largest country": "Russia is the largest country by area — over 17 million km².",
    "largest ocean": "The Pacific is the largest and deepest ocean, covering about a third of Earth's surface.",
    "longest river": "The Nile is usually considered the longest river, at about 6,650 km.",
    "highest mountain": "Mount Everest is the highest peak — 8,849 m above sea level.",
    "largest continent": "Asia is the largest continent by both area and population.",
    "largest desert": "The Sahara is the largest hot desert. Antarctica is actually the largest desert overall.",
    "largest lake": "The Caspian Sea is the largest lake by area; Lake Superior is the largest freshwater lake by surface area.",
    "great wall of china": "The Great Wall of China stretches about 21,000 km across northern China.",
    "sahara desert": "The Sahara is the world's largest hot desert, covering most of North Africa — nearly as big as the United States.",
    "nile river": "The Nile is about 6,650 km long and flows through 11 countries in northeastern Africa.",
    # space facts
    "largest planet": "Jupiter is the largest planet — more than 1,300 Earths would fit inside it.",
    "smallest planet": "Mercury is the smallest planet in our solar system.",
    "hottest planet": "Venus is the hottest planet — its thick CO₂ atmosphere traps heat at around 465°C.",
    "coldest planet": "Neptune is the coldest planet, with temperatures near -220°C.",
    "red planet": "Mars is called the Red Planet because iron oxide (rust) colors its surface.",
    "distance to the moon": "The Moon is about 384,400 km from Earth — roughly 30 Earths away.",
    "distance to the sun": "The Sun is about 150 million km from Earth — one astronomical unit (AU).",
    # animals
    "fastest animal": "The peregrine falcon is the fastest animal, diving at over 380 km/h. On land, the cheetah tops out around 110 km/h.",
    "largest animal": "The blue whale is the largest animal ever — up to 30 m long and around 180 tonnes.",
    "largest land animal": "The African elephant is the largest land animal.",
    "tallest animal": "The giraffe is the tallest animal, standing up to about 5.5 m.",
    "blue whale": "The blue whale is the largest animal that has ever lived — its heart alone is the size of a small car.",
    "cheetah": "The cheetah is the fastest land animal, sprinting at up to 110 km/h in short bursts.",
    "penguin": "Penguins are flightless birds that are excellent swimmers — the emperor penguin can dive over 500 m deep.",
    "octopus": "An octopus has three hearts, eight arms, and blue blood.",
    "spider": "Spiders have eight legs and usually eight eyes — but no antennae.",
    "giraffe": "Giraffes are the tallest animals on land, and they even have 7 neck bones — the same number as humans.",
    # human body
    "bones": "An adult human has 206 bones (babies start with about 300).",
    "bone": "An adult human has 206 bones (babies start with about 300).",
    "muscles": "There are about 600 muscles in the human body.",
    "teeth": "Adults have 32 teeth; children have 20 baby teeth.",
    "heart": "The human heart is about the size of a fist and beats roughly 100,000 times a day.",
    "largest organ": "The skin is the largest organ — about 2 m² and up to 15% of body weight.",
    "blood": "An adult human has about 5 liters of blood.",
    # math
    "pi": "Pi (π) ≈ 3.14159 — the ratio of a circle's circumference to its diameter.",
    "zero": "Zero represents nothing, and it changed mathematics forever by enabling our place-value number system.",
    "infinity": "Infinity isn't a number — it's the concept of having no limit or end.",
    "prime number": "A prime number is a whole number greater than 1 divisible only by 1 and itself — like 2, 3, 5 and 7.",
    # history / people
    "lightbulb": "Thomas Edison popularized the practical lightbulb in 1879, though several inventors worked on it before him.",
    "telephone": "Alexander Graham Bell patented the telephone in 1876.",
    "mona lisa": "The Mona Lisa was painted by Leonardo da Vinci in the early 1500s and hangs in the Louvre, Paris.",
    "pyramids": "The Egyptian pyramids were built as royal tombs around 2560 BC — the Great Pyramid of Giza is the oldest of the Seven Wonders.",
    "roman empire": "The Western Roman Empire fell in 476 AD; the Eastern (Byzantine) Empire lasted until 1453.",
    "albert einstein": "Albert Einstein was a physicist who changed our view of the universe with relativity (E = mc²).",
    "shakespeare": "William Shakespeare (1564–1616) is considered the greatest writer in English — he wrote about 39 plays.",
    # culture / general
    "alphabet": "The English alphabet has 26 letters — 5 vowels and 21 consonants.",
    "rainbow": "A rainbow appears when sunlight refracts through raindrops and splits into seven colors: red, orange, yellow, green, blue, indigo, violet.",
    # life / ideas
    "meaning of life": "Philosophers have argued for millennia — but many would say the meaning of life is whatever gives *you* purpose: love, learning, helping others. What do you think it is?",
    "love": "Love is a deep bond of care and affection. Some say it's chemistry, others say it's a choice — either way, it's one of the most powerful forces we know.",
    "happiness": "Happiness isn't a destination — it's usually found in small daily moments, good relationships, and doing work that matters.",
    "success": "Success looks different for everyone. A simple definition: making progress on the things that matter most to you.",
    "friendship": "Friendship is a mutual bond of trust, support and shared experience — one of the healthiest things you can have.",
    "time": "Time is the dimension in which events unfold. We can't slow it, bank it, or rewind it — so spending it well matters.",
    "money": "Money is a tool for trading value — it can buy freedom and comfort, but it isn't happiness by itself.",
    "dream": "Dreams are the stories your brain weaves during REM sleep. Scientists still debate why, but they likely help process memories and emotions.",
    "fear": "Fear is a survival response — it sharpens our senses. Facing small fears is often the best way to shrink them.",
    "knowledge": "Knowledge is information you understand and can use. It compounds — the more you learn, the easier learning gets.",
    "purpose": "Purpose is the sense that your actions matter. It usually comes from serving something bigger than yourself.",
}

_GENERAL_PHRASES = [
    ("how many continents", "There are seven continents: Africa, Antarctica, Asia, Europe, North America, Oceania, and South America."),
    ("how many planets", "There are eight planets in our solar system: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, and Neptune."),
    ("how many bones", "An adult human has 206 bones."),
    ("how many bones are there", "An adult human has 206 bones."),
    ("how many bones does", "An adult human has 206 bones."),
    ("how many colors", "Seven — red, orange, yellow, green, blue, indigo, and violet (ROYGBIV)."),
    ("how many days in a year", "365 days (366 in a leap year)."),
    ("how many days in a week", "Seven days in a week."),
    ("how many months", "Twelve months in a year."),
    ("how many hours in a day", "24 hours in a day."),
    ("how many minutes in an hour", "60 minutes in an hour."),
    ("how many seconds in a minute", "60 seconds in a minute."),
    ("how many letters in the alphabet", "26 letters in the English alphabet."),
    ("how many zeros in a million", "A million has six zeros (1,000,000). A billion has nine, a trillion has twelve."),
    ("how many stars", "Our galaxy alone has 100–400 billion stars — and there are billions of galaxies in the universe."),
    ("how old is the earth", "Earth is about 4.54 billion years old."),
    ("how old is the universe", "The universe is about 13.8 billion years old."),
    ("how far is the moon", "The Moon is about 384,400 km from Earth."),
    ("how far is the sun", "The Sun is about 150 million km from Earth."),
    ("how big is the sun", "The Sun's diameter is about 1.39 million km — 109 times Earth's — and it holds 99.86% of the solar system's mass."),
    ("why is the sky blue", "Sunlight scatters in the atmosphere, and blue light scatters the most — so the sky looks blue."),
    ("why do we dream", "Dreams likely help your brain process memories and emotions during REM sleep."),
    ("why do we yawn", "Still debated — yawns may help cool the brain and keep you alert."),
    ("why do we blink", "We blink to keep our eyes moist, clean and protected — about 15–20 times a minute."),
    ("why is the ocean salty", "Rain erodes salts from rocks and rivers carry them to the sea, where evaporation leaves them behind."),
    ("who painted the mona lisa", "Leonardo da Vinci painted the Mona Lisa in the early 1500s."),
    ("who invented the lightbulb", "Thomas Edison popularized the practical lightbulb in 1879."),
    ("who invented the telephone", "Alexander Graham Bell patented the telephone in 1876."),
    ("who invented the internet", "No single person — the internet grew out of ARPANET in 1969 with contributions from many researchers."),
    ("who wrote romeo and juliet", "William Shakespeare wrote Romeo and Juliet."),
    ("who was the first man on the moon", "Neil Armstrong, on July 20, 1969 — \"one small step for man, one giant leap for mankind.\""),
    ("fastest animal in the world", "The peregrine falcon, diving at over 380 km/h. On land, the cheetah tops out around 110 km/h."),
    ("largest animal in the world", "The blue whale — up to 30 m long and about 180 tonnes."),
    ("biggest animal in the world", "The blue whale — up to 30 m long and about 180 tonnes."),
    ("tallest animal in the world", "The giraffe — up to about 5.5 m tall."),
    ("largest planet in the solar system", "Jupiter — more than 1,300 Earths would fit inside it."),
    ("biggest planet", "Jupiter — more than 1,300 Earths would fit inside it."),
    ("smallest planet", "Mercury is the smallest planet."),
    ("hottest planet", "Venus is the hottest planet, at around 465°C."),
    ("coldest planet", "Neptune is the coldest planet, near -220°C."),
    ("what is the largest ocean", "The Pacific Ocean is the largest and deepest."),
    ("what is the highest mountain", "Mount Everest — 8,849 m above sea level."),
    ("what is the longest river", "The Nile — about 6,650 km long."),
    ("what is the largest desert", "The Sahara is the largest hot desert; Antarctica is the largest overall."),
    ("what is the largest country", "Russia is the largest country by area."),
    ("what do bees make", "Honey! 🍯"),
    ("do penguins fly", "No — penguins can't fly, but they're brilliant swimmers."),
    ("how long do elephants live", "Wild elephants typically live 60–70 years."),
    ("how long do dogs live", "Dogs generally live 10–13 years, depending on the breed."),
    ("how long is the great wall of china", "The Great Wall of China stretches about 21,000 km."),
    ("capital of france", "Paris 🇫🇷"),
    ("capital of ethiopia", "Addis Ababa 🇪🇹"),
    ("how many legs does a spider", "Eight."),
    ("how many legs does an insect", "Six."),
    ("how many hearts does an octopus", "Three."),
    ("how many stomachs does a cow", "Four — that's why they chew cud."),
]

_RANDOM_FACTS = [
    "Did you know? Honey never spoils — archaeologists have found 3,000-year-old honey that's still edible. 🍯",
    "Did you know? Octopuses have three hearts and blue blood.",
    "Did you know? A day on Venus is longer than a year on Venus.",
    "Did you know? Bananas are berries, but strawberries aren't.",
    "Did you know? Sharks are older than trees — they've been around for over 400 million years.",
    "Did you know? The human brain generates about 20 watts of power — enough to light a small bulb. 💡",
    "Did you know? There are more possible chess games than atoms in the observable universe. ♟️",
    "Did you know? A single bolt of lightning is about five times hotter than the surface of the Sun. ⚡",
    "Did you know? Honeybees can recognize human faces.",
    "Did you know? The longest mountain range on Earth is underwater — the Mid-Ocean Ridge, about 65,000 km long.",
]

_JOKES = [
    "Why don't scientists trust atoms? Because they make up everything! 😄",
    "Why did the scarecrow win an award? Because he was outstanding in his field! 🌾",
    "Why don't skeletons fight each other? They don't have the guts. 💀",
    "I told my computer I needed a break — it said, \"no problem, go reboot yourself.\" 💻",
    "Why did the bicycle fall over? Because it was two-tired! 🚲",
    "What do you call a fish with no eyes? A fsh. 🐟",
    "Why did the math book look sad? It had too many problems. 📘",
    "What do you call a bear with no teeth? A gummy bear. 🐻",
]

_UNITS = {
    "km": ("length", 1000.0), "kilometer": ("length", 1000.0), "kilometers": ("length", 1000.0),
    "mi": ("length", 1609.344), "mile": ("length", 1609.344), "miles": ("length", 1609.344),
    "m": ("length", 1.0), "meter": ("length", 1.0), "meters": ("length", 1.0),
    "ft": ("length", 0.3048), "foot": ("length", 0.3048), "feet": ("length", 0.3048),
    "in": ("length", 0.0254), "inch": ("length", 0.0254), "inches": ("length", 0.0254),
    "cm": ("length", 0.01), "centimeter": ("length", 0.01), "centimeters": ("length", 0.01),
    "kg": ("mass", 1.0), "kilogram": ("mass", 1.0), "kilograms": ("mass", 1.0),
    "g": ("mass", 0.001), "gram": ("mass", 0.001), "grams": ("mass", 0.001),
    "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237), "pound": ("mass", 0.45359237), "pounds": ("mass", 0.45359237),
    "oz": ("mass", 0.0283495231), "ounce": ("mass", 0.0283495231), "ounces": ("mass", 0.0283495231),
    "l": ("volume", 0.001), "liter": ("volume", 0.001), "liters": ("volume", 0.001), "litres": ("volume", 0.001),
    "ml": ("volume", 0.000001), "milliliter": ("volume", 0.000001), "milliliters": ("volume", 0.000001),
    "gal": ("volume", 0.00378541178), "gallon": ("volume", 0.00378541178), "gallons": ("volume", 0.00378541178),
    "cup": ("volume", 0.000236588), "cups": ("volume", 0.000236588),
}

_MATH_ALLOWED = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.BinOp, ast.UnaryOp, ast.Constant,
)


def _safe_eval_math(expr: str):
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _MATH_ALLOWED):
            return None
    try:
        value = eval(compile(tree, '<math>', 'eval'), {'__builtins__': {}}, {})
    except Exception:
        return None
    if isinstance(value, (int, float)) and abs(value) < 1e15:
        return value
    return None


def _definition_topic(text: str) -> Optional[str]:
    patterns = [
        r'(?:what|which)\s+(?:is|are|was|were)\s+(?:the\s+|a\s+|an\s+|some\s+)?(.{1,40})$',
        r'define\s+(?:the\s+|a\s+|an\s+)?(.{1,40})$',
        r'(?:the\s+)?(?:meaning|definition)\s+of\s+(.{1,40})$',
        r'(?:tell me about|what do you know about|facts about|info about|information about)\s+(?:the\s+|a\s+|an\s+)?(.{1,40})$',
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            topic = match.group(1).strip().rstrip('?.!,;').strip()
            topic = re.sub(r'^(the|a|an|some)\s+', '', topic)
            return topic.lower()
    return None


def _try_smalltalk(text: str):
    if _has(text, ('i love you', 'love you obama', 'i like you', 'you are the best', 'you are great')):
        return _text_reply(
            "Aww, I like you too! ❤️ Now tell me — what are we finding for you today?",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )
    if _has(text, ('i hate you', 'you are stupid', 'you are dumb', 'you suck', 'bad bot', 'useless')):
        return _text_reply(
            "Ouch! 😅 I'm still learning. Point me at what you need and I'll make it right — try \"show me phones\" or \"recommend a car\".",
            ['Show me phones', 'Recommend a car', 'What can you do?'],
        )
    if _has(text, ('are you a robot', 'are you a machine', 'are you human', 'are you real',
                   'are you alive', 'are you an ai', 'are you a bot', 'are you an ai')):
        return _text_reply(
            "I'm an AI assistant powered by machine learning — not a person, but I'm here 24/7 to help you shop and chat. 🤖",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )
    if _has(text, ('are you smart', 'are you intelligent', 'you are smart', 'you are clever')):
        return _text_reply(
            "I try my best! I know the store inside out and I enjoy a good general question too. 🧠",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )
    if _has(text, ('can you think', 'do you think', 'are you conscious', 'do you have feelings', 'do you feel')):
        return _text_reply(
            "I process language and patterns — I can't feel emotions the way people do, but I'll always do my best to help. 😊",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )
    if _has(text, ('your purpose', 'why do you exist', 'what do you do here')):
        return _text_reply(
            "My job is simple: help you find products, pick cars, and get fast answers about Obama Store — plus chat about whatever's on your mind.",
            ['What can you do?', 'Recommend a car', "What's trending?"],
        )
    if _has(text, ('are you bored', 'are you tired', 'are you sleeping')):
        return _text_reply(
            "Never bored when there's a whole catalog to explore — and I don't sleep! 😄",
            ['Show me phones', 'Recommend a car', 'What can you do?'],
        )
    if _has(text, ('sing', 'sing a song', 'dance', 'do a backflip')):
        return _text_reply(
            "I'd love to, but my vocal cords are 1s and 0s. 🎶 Best I can do is recommend a trending car while you dance!",
            ['Recommend a car', "What's trending?", 'Tell me a joke'],
        )
    return None


def _try_joke(text: str):
    if _has(text, ('joke', 'make me laugh', 'something funny', 'funny story')):
        return _text_reply(random.choice(_JOKES), ['Tell me another', 'What can you do?'])
    return None


def _try_time(text: str):
    import datetime as _dt
    now = _dt.datetime.now()
    if _has(text, ('what time', 'time is it', 'current time', 'whats the time', "what's the time", 'what is the time')):
        return _text_reply(f"It's **{now.strftime('%I:%M %p')}** right now.", ['What can you do?', 'Recommend a car'])
    if _has(text, ('what day', 'day is it', 'whats today', "what's today", 'what is today', 'today is what')):
        return _text_reply(f"Today is **{now.strftime('%A')}**.", ['What can you do?', 'Recommend a car'])
    if _has(text, ('what date', 'date is it', "what's the date", 'whats the date', 'todays date', "today's date", 'what is the date')):
        return _text_reply(f"Today's date is **{now.strftime('%B %d, %Y')}**.", ['What can you do?', 'Recommend a car'])
    if _has(text, ('what year', 'year is it', 'what is the year')):
        return _text_reply(f"We're in **{now.year}**.", ['What can you do?', 'Recommend a car'])
    return None


def _try_math(text: str):
    if not _has(text, ('what is', 'whats', 'what are', 'calculate', 'compute', 'how much is',
                       'how much are', 'solve', 'math', 'equals', '="')):
        return None
    percent = re.search(r'(\d+(?:\.\d+)?)\s*%\s+of\s+(\d+(?:\.\d+)?)', text)
    if percent:
        part, whole = float(percent.group(1)), float(percent.group(2))
        return _text_reply(
            f"{part:g}% of {whole:g} is **{part / 100.0 * whole:,.2f}**.",
            ['What can you do?', 'Recommend a car'],
        )
    expr = text.replace('^', '**').replace('×', '*').replace('÷', '/')
    expr = re.sub(r'\bplus\b', '+', expr)
    expr = re.sub(r'\bminus\b', '-', expr)
    expr = re.sub(r'\btimes\b', '*', expr)
    expr = re.sub(r'\bdivided by\b', '/', expr)
    match = re.search(r'[-+*/().\d][-+*/().\d ]{2,60}[-+*/().\d]', expr)
    if not match:
        return None
    value = _safe_eval_math(match.group(0))
    if value is None:
        return None
    if float(value).is_integer():
        return _text_reply(f"That works out to **{int(value):,}**.", ['What can you do?', 'Recommend a car'])
    return _text_reply(f"That works out to **{value:,.2f}**.", ['What can you do?', 'Recommend a car'])


def _try_convert(text: str):
    if not _has(text, ('convert', 'how many', ' to ', ' in ', ' into ')):
        return None
    temp = re.search(r'(-?\d+(?:\.\d+)?)\s*(?:°?\s*(c|celsius))\s*(?:to|in|into)\s*(?:°?\s*(f|fahrenheit))', text)
    if temp:
        celsius = float(temp.group(1))
        return _text_reply(f"{celsius:g}°C is **{celsius * 9.0 / 5.0 + 32:,.1f}°F**.", ['What can you do?', 'Recommend a car'])
    temp = re.search(r'(-?\d+(?:\.\d+)?)\s*(?:°?\s*(f|fahrenheit))\s*(?:to|in|into)\s*(?:°?\s*(c|celsius))', text)
    if temp:
        fahrenheit = float(temp.group(1))
        return _text_reply(f"{fahrenheit:g}°F is **{(fahrenheit - 32) * 5.0 / 9.0:,.1f}°C**.", ['What can you do?', 'Recommend a car'])
    match = re.search(r'(-?\d+(?:\.\d+)?)\s*([a-z]+)\s+(?:to|in|into)\s+([a-z]+)', text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    from_unit = match.group(2).lower()
    to_unit = match.group(3).lower()
    if from_unit not in _UNITS or to_unit not in _UNITS:
        return None
    from_info = _UNITS[from_unit]
    to_info = _UNITS[to_unit]
    if from_info[0] != to_info[0]:
        return None
    result = value * from_info[1] / to_info[1]
    return _text_reply(f"**{value:g} {from_unit}** is about **{result:,.2f} {to_unit}**.", ['What can you do?', 'Recommend a car'])


def _try_definition(text: str):
    topic = _definition_topic(text)
    if not topic:
        return None
    answer = _GENERAL_DEFS.get(topic)
    if not answer:
        return None
    return _text_reply(answer, ['What can you do?', 'Recommend a car', 'Tell me a fact'])


def _try_phrase(text: str):
    for needle, answer in _GENERAL_PHRASES:
        if needle in text:
            return _text_reply(answer, ['What can you do?', 'Recommend a car', 'Tell me a fact'])
    return None


def _try_random_fact(text: str):
    if _has(text, ('tell me a fact', 'did you know', 'interesting fact', 'random fact',
                   'trivia', 'surprise me', 'blow my mind', 'something interesting',
                   'give me a fact')):
        return _text_reply(random.choice(_RANDOM_FACTS), ['Tell me another', 'What can you do?'])
    return None


def _general_reply(message: str, session: dict, history: List[dict]):
    """Offline general-knowledge responder — deterministic, no LLM needed.

    Runs after the store rules miss, so general questions (facts, definitions,
    math, units, small talk, jokes…) get a real answer instantly even while the
    LLM is rate-limited or unreachable. Returns None to fall through to the LLM.
    """
    text = (message or '').lower().strip()
    if not text:
        return None
    for handler in (_try_smalltalk, _try_joke, _try_time, _try_math,
                    _try_convert, _try_definition, _try_phrase, _try_random_fact):
        result = handler(text)
        if result is not None:
            return result
    return None


def _chat_reply(message: str, session: dict, history: List[dict]) -> dict:
    """Deterministic-first, LLM-for-free-form routing.

    Order:
      1. Active multi-step car flow  -> consistent flow UX
      2. Knowledge base              -> uploaded knowledge, offline-capable
      3. Rule intents                -> deterministic store answers (same
                                        answer every time, no LLM needed)
      4. LLM (best-effort)           -> only free-form chat rules missed
      5. Graceful fallback           -> never an empty/broken reply

    Store questions therefore get identical answers whether or not the LLM
    is reachable — the LLM only handles open-ended chat on top.
    """
    # Active multi-step flow takes priority (consistent flow UX).
    if session.get('flow') == 'car':
        flow_result = _handle_car_flow(message, session)
        if flow_result is not None:
            return flow_result

    # Knowledge Base first: answer from the latest uploaded knowledge before
    # any rule-based (general) knowledge.
    kb_result = _kb_reply(message, session, history)
    if kb_result is not None:
        return kb_result

    # Deterministic rule engine — returns None only when nothing matched.
    rule_result = _rule_intents(message, session, history)
    if rule_result is not None:
        return rule_result

    # LLM only for what the rules couldn't answer (free-form chat).
    if CHAT_BACKEND == 'llm':
        try:
            llm_result = _llm_reply(message, session, history)
            if llm_result is not None:
                return llm_result
        except Exception as exc:
            import sys
            print('LLM path error: %r' % (exc,), file=sys.stderr)

    # Last-resort graceful fallback — never an empty/broken reply.
    return _text_reply(
        "I'm not sure I caught that. 🤔 But here's what I'm great at — try one of these:\n"
        "• \"do you have a MacBook?\"\n"
        "• \"recommend a diesel car under 100,000\"\n"
        "• \"how do I pay?\"\n"
        "• \"how do I contact you?\"",
        ['What can you do?', 'Recommend a car', "What's trending?"],
    )


def _rule_intents(message: str, session: dict, history: List[dict]):
    """Deterministic intent engine. Returns a response dict, or None when no
    rule confidently matched (so the caller may try the LLM)."""
    text = message.lower().strip()

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
        _has(text, ('recommend', 'budget', 'under', 'afford', 'cheap', 'suggest', 'which', 'within',
                    'buy', 'purchase', 'order', 'want', 'get'))
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
            trending = sorted(
                [c for c in car_catalog if isinstance(c, dict)],
                key=lambda c: (float(c.get('popularity') or 0), -float(c.get('car_age') or 0), float(c.get('price') or 0)),
                reverse=True,
            )[:3]
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
            ranked = sorted(
                [c for c in car_catalog[:40] if isinstance(c, dict)],
                key=lambda c: (float(c.get('price') or 0) / max(float(c.get('predicted_price') or 0), 1),
                               -float(c.get('popularity') or 0)),
            )[:3]
            best = ranked[0]
            reply = (
                f"Every car is checked against an ML fair-price model. Right now the best value pick is "
                f"**{best.get('title')}** — listed at {_fmt_money(best.get('price'))} vs a predicted fair price of "
                f"{_fmt_money(best.get('predicted_price'))}.\n\nHere are the top value picks:"
            )
            return _rich_reply(reply, [_car_card(c) for c in ranked], ['Recommend a car', "What's trending?"])
        return _text_reply("I can't check values right now — ask me to recommend a car instead.", ['Recommend a car'])

    if _has(text, ('deal', 'discount', 'offer', 'promo', 'sale', 'on sale')):
        deals = [p for p in PRODUCTS if (p.get('discount') or 0) > 0]
        if deals:
            deals.sort(key=lambda p: p.get('discount', 0), reverse=True)
            lines = ["Here are the best active deals 🏷️:"]
            for d in deals[:4]:
                lines.append(f"{d.get('title')} — {d.get('discount')}% off ({_format_currency(d.get('priceValue'), d.get('currency', 'ETB'))})")
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

    if _has(text, ('buy', 'purchase', 'add to cart', 'add to basket', 'add to bag',
                   'i want to order', 'order me', 'order one', 'order the', 'order a',
                   'get me', "i'll take", 'i will take', 'take it', 'get it', 'grab',
                   'checkout this', 'checkout the', 'ship it to me', 'send it to me')):
        query = _strip_buy_verbs(message)
        if not query:
            query = _extract_product_like(text)
        if not query:
            query = _extract_query(message)
        hits = _search_products(query, limit=3)
        if hits:
            top = hits[0]
            card = _hit_card(top)
            price_text = card.get('priceText') or ''
            title = top.get('title', '?')
            reply = (
                f"Done! 🛒 I've added **{title}** ({price_text}) to your cart. "
                f"Tap the card to view it, or open the 🛒 Cart to review and checkout."
            )
            action = {'type': 'add_to_cart', 'title': title, 'priceText': price_text}
            if top.get('priceValue') is not None:
                action['productId'] = top.get('id', '')
                action['openProduct'] = True
            return _rich_reply(
                reply, [card],
                ['View cart', 'Checkout', 'Recommend a car'],
                action=action,
            )
        category = _category_for(text)
        if category:
            products = [p for p in PRODUCTS if p.get('category') == category]
            if products:
                return _rich_reply(
                    f"What would you like from **{category}**? Here's what we have:",
                    [_product_card(p) for p in products[:6]],
                    ['Show me phones', 'Recommend a car'],
                )
        return _text_reply(
            "What would you like to buy? Tell me the product — e.g. \"buy an iPhone 15\" "
            "or \"add a MacBook Air to cart\".",
            ['Show me phones', 'Show me laptops', 'Recommend a car'],
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
        _has(text, ('show', 'browse', 'list', 'category', 'all', 'any', 'i want', 'i need', 'give me', 'looking for', 'view', 'see'))
        or _category_for(_extract_product_like(text)) == category
    ):
        products = [p for p in PRODUCTS if p.get('category') == category]
        if products:
            return _rich_reply(
                f"Here's what we have in **{category}**:",
                [_product_card(p) for p in products[:6]],
                ['Recommend a car', "What's trending?"],
                action={'type': 'open_products', 'category': category},
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
                    lines.append(f"{h.get('title')}: {state}.")
                    cards.append(_product_card(h))
                else:
                    lines.append(f"{h.get('title')}: in stock.")
            return _rich_reply('\n'.join(lines), cards, ['Show me more', 'Recommend a car'])
        return _text_reply(
            "Everything shown in the catalog is available to order. Want me to check a specific product?",
            ['Recommend a car', 'What can you do?'],
        )

    query = _extract_query(message) or _extract_product_like(text)
    if _has(text, ('have you', 'do you have', 'search', 'find', 'looking for', 'product', 'sell',
                   'in stock', 'price of', 'cost of', 'how much is', 'i want', 'i need', 'show', 'view', 'price')):
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
            action=_open_product_action(hits),
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
            action=_open_product_action(hits),
        )

    # No rule confidently matched -> hand off to the caller (LLM / fallback).
    return None


@app.post('/api/chat')
async def chat(req: ChatRequest) -> dict:
    message = (req.message or '').strip()
    session, session_id = _get_or_create_session(req.session_id or '')

    # Sync browser cart into session so get_cart_summary tool can read it.
    if req.cart:
        browser_cart = []
        for item in req.cart[:30]:
            if item.get('title'):
                browser_cart.append({
                    'id': str(item.get('id') or item.get('title') or ''),
                    'title': str(item.get('title', ''))[:120],
                    'priceText': str(item.get('priceText') or item.get('price') or ''),
                    'qty': int(item.get('qty') or item.get('quantity') or 1),
                })
        session['cart_items'] = browser_cart

    if not message:
        return {
            'session_id': session_id,
            'reply': "Hi! I'm Obama — your store assistant. 🤖 Ask me anything about products, cars, delivery, payment, or just chat!",
            'suggestions': ["What's trending?", 'Recommend a car', 'What can you do?'],
            'cards': [],
            'flow': None,
        }
    if len(message) > 2000:
        message = message[:2000]
    try:
        # _chat_reply performs blocking LLM HTTP + retries; run it off the
        # event loop so one slow chat can't freeze health checks / other users.
        result = await asyncio.to_thread(_chat_reply, message, session, req.history or [])
    except Exception:
        result = _response(
            "I ran into a tiny hiccup — but I'm still here! 🤖 Ask me about products, cars, delivery or payment.",
            ['What can you do?', 'Recommend a car', 'Contact us'],
        )
    result['session_id'] = session_id
    return result


# Mount static files last so API routes above are matched first.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
