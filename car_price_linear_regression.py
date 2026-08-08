import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
import joblib


def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    return df


def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    current_year = 2026
    df['Car_Age'] = current_year - df['year']
    df = df.drop(columns=['name', 'year'])
    return df


def build_pipeline(numeric_features, categorical_features):
    numeric_transformer = StandardScaler()
    categorical_transformer = OneHotEncoder(drop='first', handle_unknown='ignore')

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numeric_transformer, numeric_features),
            ('cat', categorical_transformer, categorical_features),
        ]
    )

    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor', LinearRegression())
    ])
    return pipeline


def evaluate_model(model, X_train, X_test, y_train, y_test):
    train_preds = model.predict(X_train)
    test_preds = model.predict(X_test)

    def metrics(y_true, y_pred):
        return {
            'r2': r2_score(y_true, y_pred),
            'mae': mean_absolute_error(y_true, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_true, y_pred))
        }

    return {
        'train': metrics(y_train, train_preds),
        'test': metrics(y_test, test_preds)
    }


def main():
    csv_path = 'CAR.csv'
    df = load_data(csv_path)

    print('Loaded rows:', len(df))
    print('Columns:', list(df.columns))
    print(df.head(5).to_string(index=False))
    print('\nMissing values:\n', df.isnull().sum())

    df = preprocess_data(df)
    print('\nAfter preprocessing columns:', list(df.columns))

    X = df.drop(columns=['selling_price'])
    y = df['selling_price']

    numeric_features = ['km_driven', 'Car_Age']
    categorical_features = ['fuel', 'seller_type', 'transmission', 'owner']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = build_pipeline(numeric_features, categorical_features)
    model.fit(X_train, y_train)

    results = evaluate_model(model, X_train, X_test, y_train, y_test)
    print('\nModel performance:')
    print('Train R2:', results['train']['r2'])
    print('Train MAE:', results['train']['mae'])
    print('Train RMSE:', results['train']['rmse'])
    print('Test R2:', results['test']['r2'])
    print('Test MAE:', results['test']['mae'])
    print('Test RMSE:', results['test']['rmse'])

    joblib.dump(model, 'car_price_linear_regression.pkl')
    print('\nSaved trained model to car_price_linear_regression.pkl')

    sample = X_test.iloc[:5]
    sample_preds = model.predict(sample)
    print('\nSample predictions:')
    sample_eval = sample.copy()
    sample_eval['prediction'] = sample_preds
    sample_eval['actual'] = y_test.iloc[:5].values
    print(sample_eval.to_string(index=False))


if __name__ == '__main__':
    main()
#this car predictoin model shold be abandoned what is your name mym name is obama ans ans and where i live is fasfad from homwa wha ti will is knowinfn g that readlinlg nnthe bile idsi thw right thinifsn to why are
thild thid this as car presdkoiction model is mas at cuz thid 