import json
import sys

import joblib
import numpy as np
from lightgbm import LGBMClassifier, early_stopping, record_evaluation
from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight

from feature import MODEL_DIR, build_catalog, ensure_directories


RANDOM_STATE = 42


def live_metrics(environment):
    if environment.iteration == 0 or (environment.iteration + 1) % 10 == 0:
        scores = {
            metric: value
            for dataset, metric, value, _ in environment.evaluation_result_list
            if dataset == 'validation'
        }
        loss = scores.get('multi_logloss')
        error = scores.get('multi_error')
        if loss is not None and error is not None:
            print(
                f'Round {environment.iteration + 1:03d} | '
                f'validation loss: {loss:.4f} | '
                f'validation accuracy: {(1 - error) * 100:.2f}%'
            )


live_metrics.order = 30


def train(force_refresh=False):
    ensure_directories()
    catalog = build_catalog(force=force_refresh)
    class_sizes = catalog['kind'].value_counts()
    catalog = catalog[catalog['kind'].isin(class_sizes[class_sizes >= 2].index)].reset_index(drop=True)

    train_text, valid_text, train_labels, valid_labels = train_test_split(
        catalog['text'],
        catalog['kind'],
        test_size=0.20,
        random_state=RANDOM_STATE,
        stratify=catalog['kind'],
    )

    classifier_vectorizer = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.95,
        sublinear_tf=True,
        max_features=60000,
    )
    x_train = classifier_vectorizer.fit_transform(train_text)
    x_valid = classifier_vectorizer.transform(valid_text)

    encoder = LabelEncoder()
    y_train = encoder.fit_transform(train_labels)
    y_valid = encoder.transform(valid_labels)
    weights = compute_sample_weight(class_weight='balanced', y=y_train)

    history = {}
    model = LGBMClassifier(
        objective='multiclass',
        num_class=len(encoder.classes_),
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=12,
        subsample=0.90,
        subsample_freq=1,
        colsample_bytree=0.90,
        reg_alpha=0.05,
        reg_lambda=0.20,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbosity=-1,
    )

    model.fit(
        x_train,
        y_train,
        sample_weight=weights,
        eval_set=[(x_valid, y_valid)],
        eval_names=['validation'],
        eval_metric=['multi_logloss', 'multi_error'],
        callbacks=[
            record_evaluation(history),
            early_stopping(stopping_rounds=30, verbose=False),
            live_metrics,
        ],
    )

    predictions = encoder.inverse_transform(model.predict(x_valid))
    accuracy = accuracy_score(valid_labels, predictions) * 100
    report = classification_report(valid_labels, predictions, output_dict=True, zero_division=0)
    category_scores = {
        label: {
            'precision': round(values['precision'], 4),
            'recall': round(values['recall'], 4),
            'f1_score': round(values['f1-score'], 4),
            'support': int(values['support']),
        }
        for label, values in report.items()
        if label in set(encoder.classes_)
    }

    print(f'\nFinal LightGBM validation accuracy: {accuracy:.2f}%')
    print(json.dumps(category_scores, indent=2))

    joblib.dump(model, MODEL_DIR / 'category_model.joblib')
    joblib.dump(encoder, MODEL_DIR / 'label_encoder.joblib')
    joblib.dump(classifier_vectorizer, MODEL_DIR / 'classifier_vectorizer.joblib')

    search_vectorizer = TfidfVectorizer(
        stop_words='english', ngram_range=(1, 2), min_df=1, sublinear_tf=True
    )
    item_vectors = search_vectorizer.fit_transform(catalog['text'])
    joblib.dump(search_vectorizer, MODEL_DIR / 'search_vectorizer.joblib')
    save_npz(MODEL_DIR / 'item_vectors.npz', item_vectors)

    metrics = {
        'validation_accuracy': round(float(accuracy), 4),
        'validation_loss': round(float(history['validation']['multi_logloss'][-1]), 6),
        'best_iteration': int(model.best_iteration_ or model.n_estimators),
        'category_scores': category_scores,
    }
    (MODEL_DIR / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(f'\nSaved model files in: {MODEL_DIR}')


if __name__ == '__main__':
    train(force_refresh='--refresh' in sys.argv)
