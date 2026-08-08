"""
Movio bridge server.

Puts the real recommender behind a small HTTP API so the browser UI can
talk to it. Everything the UI shows - the catalogue, the profile, the
scores, the decision - comes from this process. Nothing is invented in
the front end.

    python server.py            then open http://127.0.0.1:8000

Endpoints
    GET  /api/status            model + catalogue health, what is loaded
    POST /api/chat              {message} -> Movio.reply(), plus scored picks
    GET  /api/profile           the profile Movio has built so far
    POST /api/feedback          {title, verdict} -> writes user_feedback.csv
    POST /api/reset             start the conversation over
    GET  /api/explain?item_id=  full score breakdown + decision for one item
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT.parent  # index.html + assets/ live one level up

sys.path.insert(0, str(ROOT))

from feature import COLOR_TERMS, COMPANION_TERMS, DATA_DIR, MODEL_DIR  # noqa: E402


# --------------------------------------------------------------------------
# boot
# --------------------------------------------------------------------------

BOOT_ERROR = None
bot = None

try:
    from chatbot import Movio

    bot = Movio()
except Exception:  # the UI still loads and reports why
    BOOT_ERROR = traceback.format_exc()


app = FastAPI(title="Movio", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _clean(value, default=""):
    """pandas/NumPy scalars are not JSON-serialisable. Make them so."""
    if value is None:
        return default
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return default if math.isnan(value) else round(value, 6)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    text = str(value)
    return default if text in {"nan", "None", "<NA>"} else text


# --------------------------------------------------------------------------
# scoring - mirrors Movio.recommend so the UI can show the same numbers
# --------------------------------------------------------------------------

WEIGHTS = {"similarity": 0.78, "quality": 0.22, "audience": 0.08, "rejected": -0.35}

# The raw score lives in roughly 0.05 - 0.55, because a TF-IDF cosine rarely
# clears 0.35. Showing score/1.0 as a percentage squashes every result into
# the 30s and the UI would read "not sure" about everything. Rescale the
# achievable range onto 0-100 for display only. assets/app.js uses the same
# two constants so the static build and the live build agree.
MATCH_LO, MATCH_HI = 0.05, 0.55


def to_match(score):
    ratio = (float(score) - MATCH_LO) / (MATCH_HI - MATCH_LO)
    return int(round(max(0.0, min(1.0, ratio)) * 100))


def score_frame(request: str):
    """Return the catalogue scored for this request, with the parts kept."""
    companion = bot.profile.get("companion") or "alone"
    color = bot.profile.get("color") or ""
    learned_taste, rejected = bot._memory()

    query = " ".join([
        bot.profile.get("taste") or "",
        request,
        COMPANION_TERMS[companion],
        COLOR_TERMS.get(color, ""),
        learned_taste,
    ])

    vector = bot.search_vectorizer.transform([query])
    similarity = cosine_similarity(vector, bot.item_vectors).ravel()

    frame = bot.catalog.copy().reset_index(drop=True)
    frame["similarity"] = similarity
    frame["audience_bonus"] = frame["audience"].fillna("").str.contains(companion, regex=False).astype(float)
    frame["rejected"] = frame["title"].fillna("").str.lower().isin(rejected).astype(float)
    frame["score"] = (
        WEIGHTS["similarity"] * frame["similarity"]
        + WEIGHTS["quality"] * frame["quality"]
        + WEIGHTS["audience"] * frame["audience_bonus"]
        + WEIGHTS["rejected"] * frame["rejected"]
    )
    return frame


def parts_for(row):
    """The four contributions behind one score, as the UI graph draws them."""
    raw = [
        ("similarity", "Matches what you asked for", WEIGHTS["similarity"] * float(row["similarity"])),
        ("quality", "Rated well by other people", WEIGHTS["quality"] * float(row["quality"])),
        ("audience", "Suits going %s" % (bot.profile.get("companion") or "alone"),
         WEIGHTS["audience"] * float(row["audience_bonus"])),
        ("rejected", "You turned this down before",
         WEIGHTS["rejected"] * float(row["rejected"])),
    ]
    total = sum(abs(v) for _, _, v in raw) or 1.0
    return [
        {"key": k, "label": label, "value": round(v, 5), "share": round(abs(v) / total, 5)}
        for k, label, v in raw
    ]


def item_payload(row, rank=None):
    parts = parts_for(row)
    return {
        "item_id": _clean(row.get("item_id")),
        "title": _clean(row.get("title"), "Untitled"),
        "kind": _clean(row.get("kind"), "movie"),
        "tags": _clean(row.get("tags")),
        "description": _clean(row.get("description")),
        "location": _clean(row.get("location")),
        "source": _clean(row.get("source")),
        "quality": _clean(row.get("quality"), 0.0),
        "similarity": _clean(row.get("similarity"), 0.0),
        "score": _clean(row.get("score"), 0.0),
        "match": to_match(row.get("score", 0)),
        "parts": parts,
        "rank": rank,
    }


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

class ChatIn(BaseModel):
    message: str


class FeedbackIn(BaseModel):
    verdict: str
    title: Optional[str] = None


@app.get("/api/status")
def status():
    if bot is None:
        return JSONResponse(
            {"ready": False, "error": BOOT_ERROR, "hint": "Run: python train_model.py"}
        )
    metrics_file = MODEL_DIR / "metrics.json"
    metrics = {}
    if metrics_file.exists():
        import json
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))

    return {
        "ready": True,
        "catalog_rows": int(len(bot.catalog)),
        "kinds": {k: int(v) for k, v in bot.catalog["kind"].value_counts().items()},
        "sources": sorted({_clean(s) for s in bot.catalog["source"].dropna().unique()}),
        "classifier_loaded": bot.category_model is not None,
        "classes": list(bot.label_encoder.classes_) if bot.category_model is not None else [],
        "llm": "ollama" if _ollama_available() else "scripted fallback",
        "metrics": metrics,
        "feedback_rows": _feedback_rows(),
        "weights": WEIGHTS,
    }


def _ollama_available():
    try:
        import chatbot as cb
        return cb.ollama_chat is not None
    except Exception:
        return False


def _feedback_rows():
    path = DATA_DIR / "user_feedback.csv"
    if not path.exists():
        return 0
    try:
        return int(len(pd.read_csv(path)))
    except Exception:
        return 0


@app.get("/api/profile")
def profile():
    if bot is None:
        return {"ready": False}
    return {
        "ready": True,
        "profile": {k: _clean(v, None) for k, v in bot.profile.items()},
        "next_field": bot._next_field(),
        "next_question": bot._next_question(),
        "language": bot.language,
        "complete": bot._next_field() is None,
        "awaiting_feedback": bot.waiting_for_feedback,
    }


@app.post("/api/chat")
def chat(payload: ChatIn):
    if bot is None:
        return {"ready": False, "text": "The model is not loaded. Run train_model.py first.", "items": []}

    result = bot.reply(payload.message)

    items = []
    titles = [r["title"] for r in result.get("recommendations", [])]
    if titles:
        frame = score_frame(payload.message)
        chosen = frame[frame["title"].isin(titles)].sort_values("score", ascending=False)
        items = [item_payload(row, i + 1) for i, (_, row) in enumerate(chosen.iterrows())]

    return {
        "ready": True,
        "text": result.get("text", ""),
        "items": items,
        "detected_kind": result.get("detected_kind"),
        "profile_complete": result.get("profile_complete", False),
        "profile": {k: _clean(v, None) for k, v in bot.profile.items()},
        "next_question": bot._next_question(),
        "language": bot.language,
        "awaiting_feedback": bot.waiting_for_feedback,
    }


@app.get("/api/greeting")
def greeting():
    if bot is None:
        return {"ready": False, "text": "Model not loaded."}
    return {"ready": True, "text": bot.greeting(), "next_question": bot._next_question()}


@app.post("/api/feedback")
def feedback(payload: FeedbackIn):
    if bot is None:
        return {"ready": False}
    verdict = "liked" if payload.verdict.lower().startswith("l") else "disliked"
    if payload.title:
        bot.last_titles = [payload.title]
    bot._save_feedback(verdict)
    bot.waiting_for_feedback = False
    return {"ready": True, "saved": verdict, "feedback_rows": _feedback_rows()}


@app.post("/api/reset")
def reset():
    if bot is None:
        return {"ready": False}
    bot.reset()
    return {"ready": True, "text": bot.greeting()}


@app.get("/api/explain")
def explain(item_id: str, request: str = ""):
    if bot is None:
        return {"ready": False}
    frame = score_frame(request or bot.last_request or "")
    match = frame[frame["item_id"] == item_id]
    if match.empty:
        return {"ready": False, "error": "unknown item_id"}
    return {"ready": True, "item": item_payload(match.iloc[0])}


# serve the UI itself, so one command runs everything
if (UI_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    if BOOT_ERROR:
        print("Movio failed to start:\n", BOOT_ERROR)
        print("Most likely the dataset or model is missing. Run:  python train_model.py")
    uvicorn.run(app, host="127.0.0.1", port=8000)
