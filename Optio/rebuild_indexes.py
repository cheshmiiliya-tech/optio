"""
Rebuild both search indexes against the current catalogue.

Why this exists
---------------
Each engine ships a saved TF-IDF index (search_vectorizer.joblib +
item_vectors.npz). chatbot.py only uses a saved index when its row count
matches the catalogue exactly:

    if self.item_vectors.shape[0] == len(self.catalog): return

The catalogue has since grown. At the time of writing:

    catalog                    36,016 rows
    model/optio/item_vectors   35,996   -> discarded
    model/deep/item_vectors    11,694   -> discarded

So both engines silently throw their index away and refit an identical
TF-IDF at start-up. They then return identical shortlists, which makes the
side-by-side comparison meaningless - not because the models are the same,
but because neither is using the index it was trained with.

Running this rebuilds each index over the current catalogue, using each
engine's own vectorizer settings, so the saved indexes load again.

    python rebuild_indexes.py

This does not retrain the classifiers. For that, run train_optio.py and
train_deep.py, which is the better fix if you have the time and the
dependencies - it retrains everything against one dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from feature import build_catalog  # noqa: E402

# Settings taken from each project's own training script, so a rebuilt index
# is the one that engine would have produced itself.
SETTINGS = {
    "optio": dict(stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True),
    "deep": dict(stop_words="english", ngram_range=(1, 2), min_df=2, max_df=0.95,
                 sublinear_tf=True, max_features=60000),
}


def main() -> None:
    catalog = build_catalog()
    text = catalog["text"].fillna("").astype(str)
    print(f"catalogue: {len(catalog):,} rows\n")

    for name, options in SETTINGS.items():
        folder = ROOT / "model" / name
        folder.mkdir(parents=True, exist_ok=True)

        vectorizer = TfidfVectorizer(**options)
        vectors = vectorizer.fit_transform(text)

        joblib.dump(vectorizer, folder / "search_vectorizer.joblib")
        save_npz(folder / "item_vectors.npz", vectors)
        print(f"  {name:<6} {vectors.shape[0]:,} x {vectors.shape[1]:,}  -> {folder}")

    print("\nDone. Restart app.py; both engines will now load their own index.")


if __name__ == "__main__":
    main()
