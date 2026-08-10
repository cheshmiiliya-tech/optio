"""
Optio — storage.

One SQLite file, no ORM. Five tables:

    users        accounts
    sessions     login / logout audit trail
    events       what each account did, timestamped
    choices      which of the two engines a user preferred, per request
    prefs        per-account likes and dislikes, used to personalise scoring

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user salt. This is a
student project, not a bank, but there is no excuse for plain text.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_FILE = ROOT / "data" / "optio.db"

PBKDF2_ROUNDS = 120_000
SESSION_DAYS = 14


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    profile_json  TEXT    NOT NULL DEFAULT '{}',
    created_at    REAL    NOT NULL,
    last_seen_at  REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    login_at    REAL NOT NULL,
    logout_at   REAL,
    expires_at  REAL NOT NULL,
    user_agent  TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER REFERENCES users(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,
    detail    TEXT,
    at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, at);

CREATE TABLE IF NOT EXISTS choices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request     TEXT NOT NULL,
    winner      TEXT NOT NULL,          -- 'optio' | 'deep' | 'neither'
    optio_json  TEXT NOT NULL,
    deep_json   TEXT NOT NULL,
    at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_choices_user ON choices(user_id, at);

CREATE TABLE IF NOT EXISTS prefs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title     TEXT NOT NULL,
    kind      TEXT,
    verdict   TEXT NOT NULL,            -- 'liked' | 'disliked'
    request   TEXT,
    engine    TEXT,
    at        REAL NOT NULL,
    UNIQUE(user_id, title)
);
CREATE INDEX IF NOT EXISTS idx_prefs_user ON prefs(user_id);
"""


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def cursor():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------

def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
    )
    return digest.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return secrets.compare_digest(candidate, stored_hash)


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------

def create_user(username: str, password: str, display_name: str = "") -> dict:
    username = username.strip().lower()
    display_name = (display_name or username).strip()
    digest, salt = hash_password(password)
    with cursor() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, password_hash, salt, created_at)"
                " VALUES (?,?,?,?,?)",
                (username, display_name, digest, salt, time.time()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("That username is already taken.")
        return {"id": cur.lastrowid, "username": username, "display_name": display_name}


def find_user(username: str):
    with cursor() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None


def get_user(user_id: int):
    with cursor() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def save_profile(user_id: int, profile: dict) -> None:
    with cursor() as conn:
        conn.execute(
            "UPDATE users SET profile_json = ?, last_seen_at = ? WHERE id = ?",
            (json.dumps(profile, ensure_ascii=False), time.time(), user_id),
        )


def load_profile(user_id: int) -> dict:
    with cursor() as conn:
        row = conn.execute("SELECT profile_json FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["profile_json"] or "{}")
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------
# sessions — the login / logout record the brief asked for
# --------------------------------------------------------------------------

def open_session(user_id: int, user_agent: str = "", ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with cursor() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, login_at, expires_at, user_agent, ip)"
            " VALUES (?,?,?,?,?,?)",
            (token, user_id, now, now + SESSION_DAYS * 86400, user_agent[:300], ip[:60]),
        )
        conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now, user_id))
    log(user_id, "login", {"ip": ip})
    return token


def session_user(token: str | None):
    if not token:
        return None
    with cursor() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.logout_at IS NULL AND s.expires_at > ?",
            (token, time.time()),
        ).fetchone()
        return dict(row) if row else None


def close_session(token: str) -> None:
    with cursor() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        conn.execute(
            "UPDATE sessions SET logout_at = ? WHERE token = ? AND logout_at IS NULL",
            (time.time(), token),
        )
    if row:
        log(row["user_id"], "logout", {})


def session_history(user_id: int, limit: int = 20) -> list[dict]:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT login_at, logout_at, ip FROM sessions WHERE user_id = ?"
            " ORDER BY login_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# activity
# --------------------------------------------------------------------------

def log(user_id: int | None, kind: str, detail: dict | None = None) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO events (user_id, kind, detail, at) VALUES (?,?,?,?)",
            (user_id, kind, json.dumps(detail or {}, ensure_ascii=False), time.time()),
        )


def record_choice(user_id: int, request: str, winner: str, optio: list, deep: list) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO choices (user_id, request, winner, optio_json, deep_json, at)"
            " VALUES (?,?,?,?,?,?)",
            (
                user_id, request, winner,
                json.dumps([i.get("title") for i in optio], ensure_ascii=False),
                json.dumps([i.get("title") for i in deep], ensure_ascii=False),
                time.time(),
            ),
        )
    log(user_id, "engine_choice", {"winner": winner, "request": request[:120]})


def engine_scoreboard(user_id: int | None = None) -> dict:
    sql = "SELECT winner, COUNT(*) n FROM choices"
    args: tuple = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        args = (user_id,)
    sql += " GROUP BY winner"
    with cursor() as conn:
        rows = conn.execute(sql, args).fetchall()
    board = {"optio": 0, "deep": 0, "neither": 0}
    for r in rows:
        board[r["winner"]] = r["n"]
    return board


def set_pref(user_id: int, title: str, verdict: str, kind: str = "",
             request: str = "", engine: str = "") -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO prefs (user_id, title, kind, verdict, request, engine, at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id, title) DO UPDATE SET"
            " verdict = excluded.verdict, at = excluded.at, engine = excluded.engine",
            (user_id, title, kind, verdict, request[:200], engine, time.time()),
        )
    log(user_id, "feedback", {"title": title, "verdict": verdict, "engine": engine})


def get_prefs(user_id: int) -> dict:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT title, kind, verdict, request FROM prefs WHERE user_id = ? ORDER BY at DESC",
            (user_id,),
        ).fetchall()
    liked = [dict(r) for r in rows if r["verdict"] == "liked"]
    disliked = [dict(r) for r in rows if r["verdict"] == "disliked"]
    return {"liked": liked, "disliked": disliked}


def user_summary(user_id: int) -> dict:
    prefs = get_prefs(user_id)
    with cursor() as conn:
        logins = conn.execute(
            "SELECT COUNT(*) n FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        asked = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE user_id = ? AND kind = 'request'", (user_id,)
        ).fetchone()["n"]
    return {
        "logins": logins,
        "requests": asked,
        "liked": len(prefs["liked"]),
        "disliked": len(prefs["disliked"]),
        "scoreboard": engine_scoreboard(user_id),
    }
