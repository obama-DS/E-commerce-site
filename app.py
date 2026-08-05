from pathlib import Path
from typing import List, Optional
import hashlib
import json
import os
import re
import secrets
import time

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from recommend_engine import PRODUCTS, RecommendationEngine

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
        "created_at": user["created_at"],
    }


user_store = UserStore()


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
# Chat assistant — intent-based responses over the store's own data
# (catalog, car recommender, trending + store FAQs). Phase 1 of the
# roadmap: deterministic, zero-dependency. Phase 2 can swap the reply
# builder for an LLM while keeping this endpoint contract.
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []


def _fmt_money(value) -> str:
    try:
        return f"ETB {int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value or 0)


def _has(text: str, words) -> bool:
    return any(word in text for word in words)


def _parse_budget(text: str) -> Optional[float]:
    for token in re.findall(r"\b\d[\d,.]*\b", text):
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
    if _has(text, ('automatic', 'auto gear', 'auto')):
        return 'Automatic'
    return 'any'


def _extract_query(text: str) -> str:
    cleaned = text.lower()
    for prefix in (
        'do you have', 'have you got', 'are you selling', 'is there any',
        'looking for', 'search for', 'find me', 'show me', 'in stock',
        'price of', 'cost of', 'how much is', 'what is the price of',
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


def _search_products(query: str) -> List[dict]:
    if not query:
        return []
    needle = query.lower()
    hits = []
    seen = set()
    products = rec_engine.all_products(200) if rec_engine else []
    for product in products:
        haystack = ' '.join(
            str(x) for x in (
                product.get('title'), product.get('category'),
                product.get('tags'), product.get('shortDescription'),
                product.get('brand'),
            )
        ).lower()
        if needle in haystack:
            key = str(product.get('title')).lower()
            if key not in seen:
                seen.add(key)
                hits.append(product)
    for car in (car_catalog or []):
        haystack = ' '.join((car['title'], car['tags'])).lower()
        if needle in haystack:
            key = car['title'].lower()
            if key not in seen:
                seen.add(key)
                hits.append(car)
        if len(hits) >= 4:
            break
    return hits[:4]


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


def _chat_reply(message: str):
    text = message.lower()
    suggestions: List[str] = []

    if _has(text, ('bye', 'goodbye', 'see you', 'ttyl', 'good night')):
        return "Goodbye! Come back anytime — I'll be here if you need help. 👋", []

    if _has(text, ('thank',)):
        return "You're welcome! Is there anything else I can help you with?", ['What can you do?', 'Recommend a car', 'Contact support']

    if _has(text, ('hi', 'hello', 'hey', 'selam', 'salam', 'hola', 'good morning', 'good afternoon', 'good evening')):
        return (
            "Hello! I'm the Obama Store assistant. 🤖 I can help you find products, "
            "recommend cars based on your budget, show you what's trending, or answer "
            "questions about delivery, payment and returns. What would you like to do?"
        ), ['What can you do?', 'Recommend a car', "What's trending?"]

    if _has(text, ('what can you do', 'capabilities', 'help menu', 'options', 'how do you work')):
        return (
            "Here's what I can help with:\n\n"
            "🛍️  Find products — try \"do you have a MacBook?\"\n"
            "🚗  Car recommendations — \"recommend a diesel car under 50,000\"\n"
            "📈  Trending — \"what's trending?\"\n"
            "📦  Delivery — \"how long is delivery?\"\n"
            "💳  Payment — \"how do I pay?\"\n"
            "↩️  Returns — \"what's your return policy?\"\n"
            "📞  Support — \"how do I contact support?\""
        ), ['Recommend a car', "What's trending?", 'How do I pay?']

    wants_car = _has(text, ('car', 'suv', 'sedan', 'pickup', 'vehicle')) and (
        _has(text, ('recommend', 'budget', 'under', 'afford', 'cheap'))
        or any(char.isdigit() for char in text)
    )
    if wants_car or _has(text, ('recommend',)) and _has(text, ('fuel', 'diesel', 'petrol', 'automatic', 'manual', 'transmission')):
        budget = _parse_budget(text)
        fuel = _extract_fuel(text)
        transmission = _extract_transmission(text)
        cars = _recommend_cars(budget, fuel, transmission)
        if not cars:
            return "I couldn't pull up car recommendations right now. Please try again in a moment.", []
        lines = ["Here are the best car matches for you:" if not budget else f"Here are the best car matches under about {_fmt_money(budget)}:"]
        for i, car in enumerate(cars, 1):
            lines.append(
                f"{i}. {car['title']} ({car['year']}) — {_fmt_money(car['price'])} · "
                f"{car['fuel']} · {car['transmission']} · {car['km']:,} km"
            )
        if budget and all(car['price'] > budget for car in cars):
            lines[0] = (
                f"Nothing in the catalog fits under about {_fmt_money(budget)} right now. "
                f"The closest match is the {cars[0]['title']} at {_fmt_money(cars[0]['price'])}:"
            )
        lines.append("\nTip: tell me your budget, fuel type or transmission for tighter matches.")
        return "\n".join(lines), ['Under 30,000', 'Diesel automatic', 'Budget 60,000']

    if _has(text, ('trending', 'popular', 'best seller', 'best-selling', 'top selling', 'what sells')):
        trending = []
        if car_catalog:
            trending = sorted(car_catalog, key=lambda c: (c['popularity'], -c['car_age'], c['price']), reverse=True)[:3]
        if not trending:
            return "Trending data is unavailable right now.", []
        lines = ["Here are the currently trending cars:"]
        for i, car in enumerate(trending, 1):
            lines.append(
                f"{i}. {car['title']} ({car['year']}) — {_fmt_money(car['price'])} · "
                f"{car['fuel']} · {car['transmission']}"
            )
        lines.append("\nOpen the Recommendations page and hit \"Refresh Trending\" for the full list.")
        return "\n".join(lines), ['Recommend a car', 'Under 30,000']

    if _has(text, ('payment', 'pay', 'telebirr', 'cbe pay', 'how do i pay')):
        return (
            "We accept Telebirr, CBE Pay, and cash on delivery. Mobile payments are "
            "processed securely at checkout. Want details on a specific option?"
        ), ['Return policy', 'Contact support']

    if _has(text, ('ship', 'deliver', 'delivery', 'how long')):
        return (
            "We deliver across Ethiopia — Addis Ababa usually within 1–3 business days, "
            "and other regions in 3–7 days. Delivery is confirmed with you before checkout."
        ), ['How do I pay?', 'Return policy']

    if _has(text, ('return', 'refund', 'exchange', 'money back')):
        return (
            "Easy returns: contact us via the Contact page within 7 days of delivery and "
            "we'll arrange a return or exchange. Items must be in original condition with packaging."
        ), ['Contact support', 'How do I pay?']

    if _has(text, ('contact', 'support', 'phone', 'call', 'telegram', 'email', 'reach', 'agent', 'human')):
        return (
            "You can reach us 24/7:\n\n"
            "📞 Telegram / Phone: +251 9XX XXX XXX\n"
            "✉️ Email: support@obamastore.example\n"
            "📍 Addis Ababa, Ethiopia\n\n"
            "The Contact page has the quickest route to our team."
        ), ['Return policy', 'What can you do?']

    if _has(text, ('hour', 'open', 'close', 'opening', 'when')):
        return (
            "Our support team is available 24/7. Order processing runs Monday–Saturday, "
            "9:00–18:00 (EAT)."
        ), ['Contact support']

    if _has(text, ('login', 'log in', 'sign in', 'sign up', 'account', 'register')):
        return (
            "Use the \"Sign in\" button in the top bar — or open My Account — to sign in "
            "or create an account. Accounts sync your cart, wishlist and profile across devices."
        ), ['My Account', 'What can you do?']

    if _has(text, ('cart', 'wishlist', 'favorite', 'favourite', 'saved items')):
        return (
            "Your cart and wishlist are saved automatically and survive a page refresh. "
            "Open the 🛒 Cart or ♥ Wishlist icons in the top bar to review them."
        ), ['Checkout', 'My Account']

    if _has(text, ('good deal', 'fair price', 'overpriced', 'value', 'negotiat', 'worth it')):
        if car_catalog:
            best = min(car_catalog[:40], key=lambda c: (c['price'] / max(c['predicted_price'], 1), -c['popularity']))
            return (
                f"Every car is checked against an ML fair-price model. Right now the best "
                f"value pick looks like {best['title']} — listed at {_fmt_money(best['price'])} "
                f"vs a predicted fair price of {_fmt_money(best['predicted_price'])}."
            ), ['Recommend a car', "What's trending?"]
        return "I can't check values right now, but ask me to recommend a car and I'll pick by price.", ['Recommend a car']

    query = _extract_query(message)
    if _has(text, (
        'have you', 'do you have', 'search', 'find', 'looking for', 'product',
        'sell', 'in stock', 'price of', 'cost of', 'how much is', 'i want', 'i need',
    )):
        if not query:
            return "Sure — tell me the product name, like \"do you have a MacBook?\" or \"iPhone 15\".", ['Recommend a car', "What's trending?"]
        hits = _search_products(query)
        if not hits:
            return (
                f"I couldn't find \"{query}\" in the store. Try a different name, or ask me to "
                "search by category — cars, electronics, phones, wearables or fashion."
            ), ['Cars', 'Electronics', 'Recommend a car']
        lines = [f"I found these matches for \"{query}\":"]
        for i, hit in enumerate(hits, 1):
            lines.append(f"{i}. {_format_hit(hit)}")
        return "\n".join(lines), ['Recommend a car', "What's trending?"]

    if _has(text, ('help', 'assist')):
        return "I'm here to help! Ask me about products, car recommendations, delivery, payment or returns.", ['What can you do?', 'Recommend a car']

    return (
        "I'm not sure I caught that. 🤔 Try asking about products, car recommendations, "
        "delivery, payment or returns — or pick a suggestion below."
    ), ['What can you do?', 'Recommend a car', "What's trending?"]


@app.post('/api/chat')
async def chat(req: ChatRequest) -> dict:
    message = (req.message or '').strip()
    if not message:
        raise HTTPException(status_code=400, detail='Message cannot be empty.')
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail='Message is too long.')
    reply, suggestions = _chat_reply(message)
    return {'reply': reply, 'suggestions': suggestions}


# Mount static files last so API routes above are matched first.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
