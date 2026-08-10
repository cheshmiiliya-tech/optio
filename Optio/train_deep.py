"""Train Movio with a deep multi-layer neural network that needs no TensorFlow.

The model is an MLP (Multi-Layer Perceptron) with three hidden layers.
It learns entertainment categories from the merged catalog and writes live,
real loss and validation-accuracy measurements every epoch.
"""

from __future__ import annotations

import copy
import json
import random
import sys

import joblib
import matplotlib.pyplot as plt
import numpy as np
from scipy.sparse import save_npz
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, log_loss
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import LabelEncoder, Normalizer

from feature import MODEL_DIR, build_catalog, ensure_directories


RANDOM_STATE = 42
EPOCHS = 35
PATIENCE = 8
VOCABULARY_SIZE = 40_000
SVD_COMPONENTS = 320


def seed_everything(seed: int = RANDOM_STATE) -> None:
    random.seed(seed)
    np.random.seed(seed)


def prepare_data(force_refresh: bool = False):
    """Load the full merged catalog and keep 20% aside for an honest test."""

    catalog = build_catalog(force=force_refresh)
    counts = catalog["kind"].value_counts()
    catalog = catalog[catalog["kind"].isin(counts[counts >= 2].index)].copy()
    catalog = catalog.dropna(subset=["text", "kind"]).reset_index(drop=True)

    train_text, valid_text, train_labels, valid_labels = train_test_split(
        catalog["text"].astype(str),
        catalog["kind"].astype(str),
        test_size=0.20,
        random_state=RANDOM_STATE,
        stratify=catalog["kind"],
    )

    encoder = LabelEncoder()
    y_train = encoder.fit_transform(train_labels)
    y_valid = encoder.transform(valid_labels)
    return catalog, train_text, valid_text, y_train, y_valid, valid_labels, encoder


def make_features(train_text, valid_text):
    """Create compact inputs for the deep neural network from text."""

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.95,
        max_features=VOCABULARY_SIZE,
        sublinear_tf=True,
        dtype=np.float32,
    )
    train_tfidf = vectorizer.fit_transform(train_text)
    valid_tfidf = vectorizer.transform(valid_text)

    component_count = min(
        SVD_COMPONENTS,
        train_tfidf.shape[0] - 1,
        train_tfidf.shape[1] - 1,
    )
    if component_count < 2:
        raise RuntimeError("The catalog is too small to train a deep-learning model.")

    reducer = TruncatedSVD(
        n_components=component_count,
        n_iter=7,
        random_state=RANDOM_STATE,
    )
    x_train = reducer.fit_transform(train_tfidf)
    x_valid = reducer.transform(valid_tfidf)

    normalizer = Normalizer(norm="l2")
    x_train = normalizer.transform(x_train).astype(np.float32)
    x_valid = normalizer.transform(x_valid).astype(np.float32)
    return vectorizer, reducer, normalizer, x_train, x_valid


def make_network() -> MLPClassifier:
    """A true three-hidden-layer neural network, trained one epoch at a time."""

    return MLPClassifier(
        hidden_layer_sizes=(384, 192, 96),
        activation="relu",
        solver="adam",
        alpha=0.0008,
        batch_size=256,
        learning_rate="adaptive",
        learning_rate_init=0.001,
        max_iter=1,
        shuffle=True,
        random_state=RANDOM_STATE,
        warm_start=True,
    )


def train_network(x_train, y_train, x_valid, y_valid, class_count: int):
    """Train with early stopping and print actual validation metrics every epoch."""

    network = make_network()
    classes = np.arange(class_count)
    history = {"loss": [], "accuracy": [], "val_loss": [], "val_accuracy": []}
    best_loss = float("inf")
    best_weights = None
    wait = 0

    for epoch in range(1, EPOCHS + 1):
        if epoch == 1:
            network.partial_fit(x_train, y_train, classes=classes)
        else:
            network.partial_fit(x_train, y_train)

        train_probabilities = network.predict_proba(x_train)
        valid_probabilities = network.predict_proba(x_valid)
        train_predictions = train_probabilities.argmax(axis=1)
        valid_predictions = valid_probabilities.argmax(axis=1)

        train_loss = log_loss(y_train, train_probabilities, labels=classes)
        valid_loss = log_loss(y_valid, valid_probabilities, labels=classes)
        train_accuracy = accuracy_score(y_train, train_predictions) * 100
        valid_accuracy = accuracy_score(y_valid, valid_predictions) * 100

        history["loss"].append(float(train_loss))
        history["accuracy"].append(float(train_accuracy))
        history["val_loss"].append(float(valid_loss))
        history["val_accuracy"].append(float(valid_accuracy))

        print(
            f"Epoch {epoch:02d}/{EPOCHS} | "
            f"loss: {train_loss:.4f} | accuracy: {train_accuracy:.2f}% | "
            f"val_loss: {valid_loss:.4f} | val_accuracy: {valid_accuracy:.2f}%"
        )

        if valid_loss < best_loss - 0.0005:
            best_loss = valid_loss
            best_weights = (
                [weights.copy() for weights in network.coefs_],
                [bias.copy() for bias in network.intercepts_],
            )
            wait = 0
        else:
            wait += 1
            if wait >= PATIENCE:
                print(f"Early stopping after epoch {epoch}: validation loss stopped improving.")
                break

    if best_weights is not None:
        network.coefs_, network.intercepts_ = best_weights
    return network, history


def save_search_index(catalog) -> None:
    """Save the separate content index used to rank individual entertainment items."""

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    vectors = vectorizer.fit_transform(catalog["text"])
    joblib.dump(vectorizer, MODEL_DIR / "search_vectorizer.joblib")
    save_npz(MODEL_DIR / "item_vectors.npz", vectors)


def save_curve(history) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(history["loss"], label="Train loss")
    axes[0].plot(history["val_loss"], label="Validation loss")
    axes[0].set(title="Loss by epoch", xlabel="Epoch", ylabel="Log loss")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    axes[1].plot(history["accuracy"], label="Train accuracy")
    axes[1].plot(history["val_accuracy"], label="Validation accuracy")
    axes[1].set(title="Accuracy by epoch", xlabel="Epoch", ylabel="Accuracy (%)", ylim=(0, 100))
    axes[1].legend()
    axes[1].grid(alpha=0.25)

    figure.tight_layout()
    figure.savefig(MODEL_DIR / "training_curve.png", dpi=150)
    plt.show()
    plt.close(figure)


def train(force_refresh: bool = False) -> None:
    seed_everything()
    ensure_directories()
    catalog, train_text, valid_text, y_train, y_valid, valid_labels, encoder = prepare_data(force_refresh)
    vectorizer, reducer, normalizer, x_train, x_valid = make_features(train_text, valid_text)
    network, history = train_network(x_train, y_train, x_valid, y_valid, len(encoder.classes_))

    probabilities = network.predict_proba(x_valid)
    predicted_labels = encoder.inverse_transform(probabilities.argmax(axis=1))
    accuracy = accuracy_score(valid_labels, predicted_labels) * 100
    report = classification_report(valid_labels, predicted_labels, output_dict=True, zero_division=0)
    category_scores = {
        label: {
            "precision": round(float(values["precision"]), 4),
            "recall": round(float(values["recall"]), 4),
            "f1_score": round(float(values["f1-score"]), 4),
            "support": int(values["support"]),
        }
        for label, values in report.items()
        if label in set(encoder.classes_)
    }

    joblib.dump(network, MODEL_DIR / "deep_category_model.joblib")
    joblib.dump(encoder, MODEL_DIR / "label_encoder.joblib")
    joblib.dump(vectorizer, MODEL_DIR / "classifier_vectorizer.joblib")
    joblib.dump(reducer, MODEL_DIR / "category_reducer.joblib")
    joblib.dump(normalizer, MODEL_DIR / "category_normalizer.joblib")
    save_search_index(catalog)
    save_curve(history)

    metrics = {
        "model_type": "Scikit-learn deep MLP neural network (384 → 192 → 96)",
        "validation_accuracy": round(float(accuracy), 4),
        "validation_loss": round(float(min(history["val_loss"])), 6),
        "epochs_completed": len(history["loss"]),
        "catalog_items": int(len(catalog)),
        "classes": encoder.classes_.tolist(),
        "category_scores": category_scores,
    }
    (MODEL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("\nDeep neural-network training complete")
    print(f"Real held-out validation accuracy: {accuracy:.2f}%")
    print(f"Saved model: {MODEL_DIR / 'deep_category_model.joblib'}")
    if accuracy < 99:
        print("The real score is below 99%; do not report 99% unless this run prints it.")


if __name__ == "__main__":
    train(force_refresh="--refresh" in sys.argv)
