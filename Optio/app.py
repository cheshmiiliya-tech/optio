"""
Optio — AI Entertainment Decision System.

One command runs the whole thing:

    python app.py           then open http://127.0.0.1:8000

It serves the UI, both recommenders, and a SQLite database holding
accounts, login/logout history, and every preference a user expresses.

Auth
    POST /api/register      create an account
    POST /api/login         start a session (sets an httpOnly cookie)
    POST /api/logout        end it, stamping logout_at
    GET  /api/me            current account, profile and stats

Recommending
    POST /api/chat          one conversation turn (house engine)
    POST /api/compare       the same request through BOTH engines
    POST /api/choose        record which engine the user preferred
    POST /api/feedback      like / dislike one title
    GET  /api/status        what loaded, what did not, and why
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from typing import Optional

from fastapi import Cookie, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402

db.init()

BOOT_ERROR = None
dual = None
try:
    from engines import Dual

    dual = Dual()
except Exception:
    import traceback

    BOOT_ERROR = traceback.format_exc()

app = FastAPI(title="Optio — AI Entertainment Decision System", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE = "optio_session"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def current_user(token):
    return db.session_user(token) if token else None


def need_user(token):
    user = current_user(token)
    if user is None:
        return None, JSONResponse({"error": "Please sign in first."}, status_code=401)
    return user, None


def disliked_titles(user_id):
    prefs = db.get_prefs(user_id)
    return {p["title"].lower() for p in prefs["disliked"]}


PROFILE_FIELDS = ["name", "taste", "companion", "country", "city", "color"]


def apply_user_context(user: dict) -> None:
    """Load this account's profile into both bots, and nothing else.

    Both engines are process-wide singletons shared by every request, so a
    profile left behind by the previous caller would otherwise still be
    sitting there. Every field is cleared and then repopulated from this
    account, so one person's answers can never leak into another's session.

    Both bots get the same profile, which keeps the A/B comparison fair: a
    difference in the two shortlists is a difference in the classifiers, not
    one engine knowing more about the user than the other.
    """
    stored = db.load_profile(user["id"]) or {}
    for engine in dual.engines():
        if not engine.ready:
            continue
        for key in PROFILE_FIELDS:
            engine.bot.profile[key] = stored.get(key) or None
        # conversational latches belong to whoever was last talking
        engine.bot.waiting_for_feedback = False
        engine.bot.waiting_to_explore = False


def next_missing_field(profile: dict):
    for key in PROFILE_FIELDS:
        if not profile.get(key):
            return key
    return None


PROFILE_QUESTIONS = {
    "name": "What name should I call you?",
    "taste": "What movies, songs, games, events, or places do you enjoy?",
    "companion": "Will you go Alone, with Friends, or with Family?",
    "country": "Which country do you live in?",
    "city": "Which city do you live in?",
    "color": "What is your favourite colour?",
}


def capture_field(bot, field: str, text: str):
    """Read one answer. Returns the value, or None if it did not parse.

    chatbot.py routes any message that merely looks like a content request
    into its direct-answer path, which abandons the questionnaire: answering
    "comedy films" to "what do you enjoy?" was being swallowed, and the next
    answer landed in the wrong field. While the profile is still being
    collected, the six answers are read here instead, so a question that was
    asked is always the question that gets answered.
    """
    text = (text or "").strip()
    if not text:
        return None
    if field == "name":
        return bot._name_from_text(text) or (text.split()[0].title() if len(text.split()) <= 2 else None)
    if field == "companion":
        return bot._companion_from_text(text)
    if field == "color":
        return bot._color_from_text(text)
    return text          # taste, country, city are free text


def sync_profile_to_db(user_id: int) -> dict:
    engine = dual.primary
    if not engine.ready:
        return {}
    profile = dict(engine.bot.profile)
    db.save_profile(user_id, profile)
    # keep the other engine in step
    for other in dual.engines():
        if other.ready and other is not engine:
            other.bot.profile.update(profile)
    return profile


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------

class Credentials(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class Message(BaseModel):
    message: str


class Choice(BaseModel):
    request: str
    winner: str                      # 'optio' | 'deep' | 'neither'


class Feedback(BaseModel):
    title: str
    verdict: str                     # 'liked' | 'disliked'
    kind: Optional[str] = ""
    engine: Optional[str] = ""
    request: Optional[str] = ""


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------

@app.post("/api/register")
def register(body: Credentials, request: Request, response: Response):
    username = (body.username or "").strip()
    if len(username) < 3:
        return JSONResponse({"error": "Username needs at least 3 characters."}, status_code=400)
    if len(body.password or "") < 6:
        return JSONResponse({"error": "Password needs at least 6 characters."}, status_code=400)
    try:
        user = db.create_user(username, body.password, body.display_name or username)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)

    token = db.open_session(
        user["id"],
        request.headers.get("user-agent", ""),
        request.client.host if request.client else "",
    )
    db.log(user["id"], "register", {})
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        max_age=db.SESSION_DAYS * 86400)
    return {"ok": True, "user": {"username": user["username"], "display_name": user["display_name"]},
            "first_time": True}


@app.post("/api/login")
def login(body: Credentials, request: Request, response: Response):
    record = db.find_user(body.username or "")
    if not record or not db.verify_password(body.password or "", record["password_hash"], record["salt"]):
        return JSONResponse({"error": "Wrong username or password."}, status_code=401)

    token = db.open_session(
        record["id"],
        request.headers.get("user-agent", ""),
        request.client.host if request.client else "",
    )
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        max_age=db.SESSION_DAYS * 86400)
    summary = db.user_summary(record["id"])
    return {
        "ok": True,
        "user": {"username": record["username"], "display_name": record["display_name"]},
        "first_time": summary["logins"] <= 1,
        "summary": summary,
    }


@app.post("/api/logout")
def logout(response: Response, optio_session: Optional[str] = Cookie(default=None)):
    if optio_session:
        db.close_session(optio_session)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(optio_session: Optional[str] = Cookie(default=None)):
    user = current_user(optio_session)
    if not user:
        return {"signed_in": False}
    return {
        "signed_in": True,
        "user": {"username": user["username"], "display_name": user["display_name"]},
        "profile": db.load_profile(user["id"]),
        "prefs": db.get_prefs(user["id"]),
        "summary": db.user_summary(user["id"]),
        "sessions": db.session_history(user["id"], 10),
    }


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

@app.get("/api/status")
def status():
    if dual is None:
        return {"ready": False, "error": BOOT_ERROR,
                "hint": "Install the requirements, then run: python train_optio.py"}
    primary = dual.primary
    return {
        "ready": dual.any_ready,
        "engines": [e.describe() for e in dual.engines()],
        "catalog_rows": int(len(primary.bot.catalog)) if primary.ready else 0,
        "kinds": (
            {k: int(v) for k, v in primary.bot.catalog["kind"].value_counts().items()}
            if primary.ready else {}
        ),
        "llm": "ollama" if _ollama() else "scripted fallback",
        "scoreboard": db.engine_scoreboard(),
        "weights": {"similarity": 0.78, "quality": 0.22, "audience": 0.08, "rejected": -0.35},
    }


def _ollama():
    try:
        import chatbot as cb
        return cb.ollama_chat is not None
    except Exception:
        return False


# --------------------------------------------------------------------------
# conversation + the two engines
# --------------------------------------------------------------------------

@app.post("/api/chat")
def chat(body: Message, optio_session: Optional[str] = Cookie(default=None)):
    user, error = need_user(optio_session)
    if error:
        return error
    if dual is None or not dual.any_ready:
        return JSONResponse({"error": "No recommender is loaded."}, status_code=503)

    apply_user_context(user)
    engine = dual.primary
    db.log(user["id"], "message", {"text": body.message[:200]})

    stored = db.load_profile(user["id"]) or {}
    field = next_missing_field(stored)

    # --- still collecting the six answers: drive it here, deterministically
    if field:
        value = capture_field(engine.bot, field, body.message)
        if value is None:
            return {
                "text": "Sorry, I did not catch that. " + PROFILE_QUESTIONS[field],
                "profile": stored,
                "profile_complete": False,
                "next_question": PROFILE_QUESTIONS[field],
                "compare": None,
            }

        stored[field] = value
        db.save_profile(user["id"], stored)
        for e in dual.engines():
            if e.ready:
                e.bot.profile[field] = value

        nxt = next_missing_field(stored)
        lead = {
            "name": f"Nice to meet you, {value}.",
            "taste": "Good to know.",
            "companion": f"Got it - {value}.",
            "country": "Thanks.",
            "city": "That helps with nearby ideas.",
            "color": f"{str(value).title()} it is.",
        }[field]
        return {
            "text": lead + " " + (PROFILE_QUESTIONS[nxt] if nxt
                                  else "That is everything. What are you in the mood for?"),
            "profile": stored,
            "profile_complete": nxt is None,
            "next_question": PROFILE_QUESTIONS[nxt] if nxt else None,
            "compare": None,
        }

    # --- profile complete: it is a real request, so both engines answer
    result = engine.bot.reply(body.message)
    profile = sync_profile_to_db(user["id"])
    db.log(user["id"], "request", {"text": body.message[:200]})

    return {
        "text": result.get("text", ""),
        "profile": profile,
        "profile_complete": True,
        "next_question": None,
        "detected_kind": result.get("detected_kind"),
        "request": body.message,
        "compare": dual.compare(body.message, count=4, disliked=disliked_titles(user["id"])),
    }


@app.post("/api/compare")
def compare(body: Message, optio_session: Optional[str] = Cookie(default=None)):
    user, error = need_user(optio_session)
    if error:
        return error
    if dual is None or not dual.any_ready:
        return JSONResponse({"error": "No recommender is loaded."}, status_code=503)

    apply_user_context(user)
    db.log(user["id"], "request", {"text": body.message[:200]})
    return {
        "request": body.message,
        "compare": dual.compare(body.message, count=4, disliked=disliked_titles(user["id"])),
    }


@app.post("/api/choose")
def choose(body: Choice, optio_session: Optional[str] = Cookie(default=None)):
    """Record which engine read the request better.

    This is the signal the brief asked for: the two shortlists go out, the
    person says which one landed, and that judgement is stored against their
    account. Liking a shortlist also marks its titles as liked, so the next
    query is scored with that preference already applied.
    """
    user, error = need_user(optio_session)
    if error:
        return error
    if body.winner not in {"optio", "deep", "neither"}:
        return JSONResponse({"error": "winner must be optio, deep or neither."}, status_code=400)

    result = dual.compare(body.request, count=4, disliked=disliked_titles(user["id"]))
    optio_items = result.get("optio", {}).get("items", [])
    deep_items = result.get("deep", {}).get("items", [])
    db.record_choice(user["id"], body.request, body.winner, optio_items, deep_items)

    if body.winner in {"optio", "deep"}:
        chosen = optio_items if body.winner == "optio" else deep_items
        for item in chosen[:2]:
            db.set_pref(user["id"], item["title"], "liked", item.get("kind", ""),
                        body.request, body.winner)

    return {"ok": True, "scoreboard": db.engine_scoreboard(user["id"]),
            "overall": db.engine_scoreboard()}


@app.post("/api/feedback")
def feedback(body: Feedback, optio_session: Optional[str] = Cookie(default=None)):
    user, error = need_user(optio_session)
    if error:
        return error
    verdict = "liked" if body.verdict.lower().startswith("l") else "disliked"
    db.set_pref(user["id"], body.title, verdict, body.kind or "",
                body.request or "", body.engine or "")
    return {"ok": True, "prefs": db.get_prefs(user["id"])}


@app.get("/api/predicted")
def predicted(optio_session: Optional[str] = Cookie(default=None)):
    """What Optio thinks you will want next, without being asked.

    This is the one place the LightGBM classifier is used for its own sake
    rather than to route a request. It reads everything the account has told
    us - the stated taste, plus the titles and tags of everything liked so
    far - and predicts which KIND of thing is wanted next. The shortlist is
    then the best of that kind.

    The prediction and its confidence are both returned, because a 41% guess
    and a 96% guess should not look the same on screen.
    """
    user, error = need_user(optio_session)
    if error:
        return error
    if dual is None or not dual.any_ready:
        return JSONResponse({"error": "No recommender is loaded."}, status_code=503)

    apply_user_context(user)
    engine = dual.optio if dual.optio.ready else dual.primary
    bot = engine.bot
    prefs = db.get_prefs(user["id"])

    signal = " ".join(filter(None, [
        bot.profile.get("taste") or "",
        " ".join(p["title"] for p in prefs["liked"][:12]),
        " ".join(p.get("request") or "" for p in prefs["liked"][:12]),
    ])).strip()

    predicted_kind, confidence, source = None, None, "not enough signal yet"
    if signal:
        if engine.classifier_loaded:
            try:
                vector = bot.classifier_vectorizer.transform([signal])
                probabilities = bot.category_model.predict_proba(vector)[0]
                index = int(probabilities.argmax())
                predicted_kind = str(bot.label_encoder.inverse_transform([index])[0])
                confidence = round(float(probabilities[index]), 4)
                source = "LightGBM classifier"
            except Exception:
                predicted_kind = None
        if predicted_kind is None:
            predicted_kind = bot._detect_kind(signal)
            source = "keyword rules (classifier unavailable)"

        # Keyword rules return nothing when two kinds tie - "funny movies and
        # co-op games" names both. Fall back to the majority kind of what the
        # account has actually liked, which is a weaker signal but an honest
        # one, and label it as such rather than leaving the panel blank.
        if predicted_kind is None and prefs["liked"]:
            counts = {}
            for pref in prefs["liked"]:
                kind = (pref.get("kind") or "").strip()
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
            if counts:
                predicted_kind = max(counts, key=counts.get)
                confidence = round(counts[predicted_kind] / sum(counts.values()), 4)
                source = "majority of what you liked"

    items = dual.score_items(engine, signal or "something to do", count=12,
                             disliked=disliked_titles(user["id"]))
    if predicted_kind:
        of_kind = [i for i in items if i["kind"] == predicted_kind]
        if of_kind:
            items = of_kind
    items = items[:5]

    db.log(user["id"], "predicted", {"kind": predicted_kind, "confidence": confidence})
    return {
        "predicted_kind": predicted_kind,
        "confidence": confidence,
        "source": source,
        "signal_used": signal[:220],
        "liked_count": len(prefs["liked"]),
        "items": items,
    }


@app.get("/api/lineup")
def lineup(optio_session: Optional[str] = Cookie(default=None)):
    """An evening in order: eat, then do, then watch, then wind down.

    The catalogue carries no broadcast times - nothing here has a start or a
    duration - so this is a running order rather than a schedule. Each slot
    takes the best-scoring item of its kinds that has not already been used.
    """
    user, error = need_user(optio_session)
    if error:
        return error
    if dual is None or not dual.any_ready:
        return JSONResponse({"error": "No recommender is loaded."}, status_code=503)

    apply_user_context(user)
    engine = dual.primary
    taste = engine.bot.profile.get("taste") or "something enjoyable"

    slots = [
        {"slot": "First", "when": "early evening", "kinds": ["restaurant", "cafe"],
         "note": "Somewhere to eat"},
        {"slot": "Then", "when": "out and about", "kinds": ["event", "theme park", "travel place"],
         "note": "Something happening"},
        {"slot": "After", "when": "back home", "kinds": ["movie"], "note": "Something to watch"},
        {"slot": "Last", "when": "winding down", "kinds": ["song", "game"],
         "note": "Something to end on"},
    ]

    pool = dual.score_items(engine, taste, count=250,
                            disliked=disliked_titles(user["id"]))
    used, out = set(), []
    for slot in slots:
        pick = next((i for i in pool
                     if i["kind"] in slot["kinds"] and i["item_id"] not in used), None)
        if pick:
            used.add(pick["item_id"])
        out.append({**slot, "item": pick})

    db.log(user["id"], "lineup", {})
    return {"lineup": out, "based_on": taste}


@app.post("/api/reset")
def reset(optio_session: Optional[str] = Cookie(default=None)):
    user, error = need_user(optio_session)
    if error:
        return error
    for engine in dual.engines():
        if engine.ready:
            engine.bot.reset()
    db.save_profile(user["id"], {})
    db.log(user["id"], "reset", {})
    text = dual.primary.bot.greeting() if dual.primary.ready else "Let's start again."
    return {"ok": True, "text": text}


@app.get("/api/greeting")
def greeting(optio_session: Optional[str] = Cookie(default=None)):
    user = current_user(optio_session)
    if dual is None or not dual.any_ready:
        return {"text": "The recommender is not loaded yet."}
    if user:
        apply_user_context(user)
    return {"text": dual.primary.bot.greeting()}


# --------------------------------------------------------------------------
# the UI
# --------------------------------------------------------------------------

# The front end uses relative paths, because on GitHub Pages the site is
# served from /optio/ and a leading slash escapes to the domain root. That
# means it asks for "index.html" and "login.html" - real filenames, which
# Pages serves directly. Here they have to be routed explicitly, and the
# extensionless spellings kept working too, so the same links resolve
# whether the page came from this server or from Pages.

@app.get("/")
@app.get("/index.html")
def home():
    return FileResponse(UI_DIR / "index.html")


@app.get("/login")
@app.get("/login.html")
def login_page():
    return FileResponse(UI_DIR / "login.html")


if (UI_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="assets")


if __name__ == "__main__":
    import uvicorn

    if BOOT_ERROR:
        print("Optio could not load its engines:\n", BOOT_ERROR)
        print("The site will still start; /api/status explains what is missing.")
    print("\n  Optio — AI Entertainment Decision System")
    print("  http://127.0.0.1:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
