"""
Optio — the two recommenders, side by side.

The team trained two classifiers on the same catalogue:

    optio   LightGBM gradient boosting        model/optio/
    deep    3-layer neural network (MLP)      model/deep/
            TF-IDF -> TruncatedSVD -> L2 norm -> MLP(384, 192, 96)

Both share the same retrieval core: a TF-IDF cosine over the catalogue,
plus quality, audience fit and the user's own past rejections. Where they
differ is how they read the *kind* of thing a request is asking for, and
that changes which slice of the catalogue gets searched. Two classifiers,
two shortlists, and the user says which one read them better.

Each engine is loaded independently. If one fails to load - a missing
artefact, a NumPy built by a different major version - the other still
serves, and /api/status says exactly what happened.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import chatbot  # noqa: E402
import feature  # noqa: E402
from chatbot import Optio  # noqa: E402


def _point_at(model_dir: Path) -> None:
    """Aim the loaders at one model folder.

    chatbot.py does `from feature import MODEL_DIR`, which copies the value
    into the chatbot module's own namespace. Rebinding feature.MODEL_DIR is
    therefore not enough - the name the methods actually read is
    chatbot.MODEL_DIR, so both have to move together.
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    feature.MODEL_DIR = model_dir
    chatbot.MODEL_DIR = model_dir


MODEL_ROOT = ROOT / "model"

# The raw score sits in roughly 0.05 - 0.55, because a TF-IDF cosine rarely
# clears 0.35. Showing score/1.0 as a percentage squashes everything into the
# 30s. Rescale the achievable range onto 0-100 for display only. assets/app.js
# carries the same two constants so every build agrees.
MATCH_LO, MATCH_HI = 0.05, 0.55


def to_match(score: float) -> int:
    ratio = (float(score) - MATCH_LO) / (MATCH_HI - MATCH_LO)
    return int(round(max(0.0, min(1.0, ratio)) * 100))


class DeepOptio(Optio):
    """Optio's conversation and retrieval, with the neural network deciding kind.

    Only the classifier is swapped. Everything else - the profile questions,
    the query construction, the scoring weights - is inherited, so a
    difference in the two shortlists is a difference in the classifiers and
    nothing else.
    """

    def _load_category_model(self):
        """Load the network, or carry on without it.

        A classifier that will not unpickle - a NumPy major-version gap is the
        usual cause - must not take the whole engine down with it. Optio's own
        loader already swallows this; the deep one has to match, otherwise one
        side of the comparison disappears instead of degrading.
        """
        folder = MODEL_ROOT / "deep"
        needed = {
            "category_model": folder / "deep_category_model.joblib",
            "label_encoder": folder / "label_encoder.joblib",
            "classifier_vectorizer": folder / "classifier_vectorizer.joblib",
            "category_reducer": folder / "category_reducer.joblib",
            "category_normalizer": folder / "category_normalizer.joblib",
        }
        self.category_model = None
        self.classifier_error = None
        if not all(p.exists() for p in needed.values()):
            self.classifier_error = "artefacts missing - run: python train_deep.py"
            return
        try:
            import joblib
            loaded = {name: joblib.load(path) for name, path in needed.items()}
        except Exception as error:
            self.classifier_error = f"{type(error).__name__}: {error}"
            self.category_model = None
            return
        for attribute, value in loaded.items():
            setattr(self, attribute, value)

    def _category_probabilities(self, text):
        vector = self.classifier_vectorizer.transform([str(text)])
        compact = self.category_reducer.transform(vector)
        compact = self.category_normalizer.transform(compact)
        return self.category_model.predict_proba(compact)[0]

    def _predicted_kind(self, text):
        if self.category_model is None:
            return None
        probability = self._category_probabilities(text)
        if probability.max() < 0.45:
            return None
        return self.label_encoder.inverse_transform([probability.argmax()])[0]

    def _detect_kind(self, text):
        """Keyword rules first, then the network when it is confident."""
        keyword_kind = feature.find_kind(str(text).lower())
        if keyword_kind:
            return keyword_kind
        if self.category_model is None:
            return None
        probability = self._category_probabilities(text)
        if len(probability) < 2:
            return None
        top_two = np.sort(probability)[-2:]
        confidence = float(top_two[-1])
        margin = confidence - float(top_two[-2])
        if confidence >= 0.65 and margin >= 0.12:
            return self.label_encoder.inverse_transform([probability.argmax()])[0]
        return None


class Engine:
    """One loaded recommender plus the story of whether it loaded."""

    def __init__(self, key: str, label: str, blurb: str, factory, model_dir: Path):
        self.key = key
        self.label = label
        self.blurb = blurb
        self.model_dir = model_dir
        self.bot = None
        self.error = None
        try:
            _point_at(model_dir)
            self.bot = factory()
        except Exception:
            self.error = traceback.format_exc(limit=4)

    @property
    def ready(self) -> bool:
        return self.bot is not None

    @property
    def classifier_loaded(self) -> bool:
        return bool(self.bot is not None and getattr(self.bot, "category_model", None) is not None)

    def metrics(self) -> dict:
        path = self.model_dir / "metrics.json"
        if not path.exists():
            return {}
        import json
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def describe(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "blurb": self.blurb,
            "ready": self.ready,
            "classifier_loaded": self.classifier_loaded,
            "classifier_error": getattr(self.bot, "classifier_error", None) if self.bot else None,
            "error": self.error,
            "metrics": self.metrics(),
        }


class Dual:
    """Holds both engines and asks them the same question."""

    def __init__(self):
        feature.ensure_directories()
        self.optio = Engine(
            "optio", "Optio",
            "Gradient boosting (LightGBM). Fast, sharp on clear wording.",
            lambda: Optio(), MODEL_ROOT / "optio",
        )
        self.deep = Engine(
            "deep", "Deep Learning",
            "Three-layer neural network. Better on vague or unusual phrasing.",
            lambda: DeepOptio(), MODEL_ROOT / "deep",
        )

    @property
    def any_ready(self) -> bool:
        return self.optio.ready or self.deep.ready

    @property
    def primary(self):
        """Whichever engine can actually answer; Optio is the house model."""
        return self.optio if self.optio.ready else self.deep

    def engines(self) -> list[Engine]:
        return [self.optio, self.deep]

    def get(self, key: str):
        return self.optio if key == "optio" else self.deep

    # ---- shared scoring surface -------------------------------------

    def score_items(self, engine: Engine, request: str, count: int = 5,
                    disliked: set[str] | None = None) -> list[dict]:
        """Run one engine and return its picks with the score decomposed."""
        if not engine.ready:
            return []
        bot = engine.bot
        frame = bot._recommend_core(request, count=count)
        if frame is None or len(frame) == 0:
            return []

        companion = bot.profile.get("companion") or "alone"
        disliked = disliked or set()
        items = []
        for rank, (_, row) in enumerate(frame.iterrows(), start=1):
            quality = _number(row.get("quality"))
            audience = 1.0 if companion in str(row.get("audience", "")) else 0.0
            rejected = 1.0 if str(row.get("title", "")).lower() in disliked else 0.0
            score = _number(row.get("score"))

            # _recommend_core only returns the final score, so recover the
            # similarity term by undoing the other three. Rows merged in from
            # local_items have score replaced by quality and no similarity at
            # all, which is why this is clamped rather than trusted blindly.
            similarity = (score - W["quality"] * quality
                          - W["audience"] * audience
                          - W["rejected"] * rejected) / W["similarity"]
            similarity = max(0.0, min(1.0, similarity))
            items.append({
                "item_id": _text(row.get("item_id")),
                "title": _text(row.get("title"), "Untitled"),
                "kind": _text(row.get("kind"), "movie"),
                "tags": _text(row.get("tags")),
                "description": _text(row.get("description")),
                "location": _text(row.get("location")),
                "source": _text(row.get("source")),
                "quality": round(quality, 4),
                "similarity": round(similarity, 4),
                "score": round(score, 5),
                "match": to_match(score),
                "rank": rank,
                "engine": engine.key,
                "parts": _parts(similarity, quality, audience, rejected, companion),
            })
        return items

    def compare(self, request: str, count: int = 4,
                disliked: set[str] | None = None) -> dict:
        """The same request through both engines, for the user to judge."""
        out = {}
        for engine in self.engines():
            out[engine.key] = {
                "label": engine.label,
                "blurb": engine.blurb,
                "ready": engine.ready,
                "detected_kind": None,
                "items": [],
                "error": engine.error,
            }
            if not engine.ready:
                continue
            try:
                out[engine.key]["detected_kind"] = engine.bot._detect_kind(request)
            except Exception:
                pass
            out[engine.key]["items"] = self.score_items(engine, request, count, disliked)
        return out


W = {"similarity": 0.78, "quality": 0.22, "audience": 0.08, "rejected": -0.35}


def _parts(similarity, quality, audience, rejected, companion):
    raw = [
        ("similarity", "Matches what you asked for", W["similarity"] * similarity),
        ("quality", "Rated well by other people", W["quality"] * quality),
        ("audience", f"Suits going {companion}", W["audience"] * audience),
        ("rejected", "You turned this down before", W["rejected"] * rejected),
    ]
    total = sum(abs(v) for _, _, v in raw) or 1.0
    return [
        {"key": k, "label": lab, "value": round(v, 5), "share": round(abs(v) / total, 5)}
        for k, lab, v in raw
    ]


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(number) else number


def _text(value, default=""):
    if value is None:
        return default
    try:
        if isinstance(value, float) and np.isnan(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return default if text in {"nan", "None", "<NA>"} else text
