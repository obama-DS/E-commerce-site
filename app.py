from pathlib import Path
from typing import List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
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


# Mount static files last so API routes above are matched first.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
