# Optio — AI Entertainment Decision System

You say what you feel like. **Two different models answer at the same time**, and
you pick whichever read you better. That choice is saved to your account and
shapes what you are shown next.

The catalogue is 36,016 movies, games, songs, events and places built from five
public datasets.

**Static preview:** <https://cheshmiiliya-tech.github.io/optio/>

---

## Run it

```bash
cd Optio
pip install -r requirements.txt

python train_optio.py     # builds the catalogue, trains the LightGBM classifier
python train_deep.py      # trains the neural network on the same catalogue
python app.py             # serves the UI, both models and the database
```

Open <http://127.0.0.1:8000>. Create an account, and you are in.

Optional, for natural replies instead of the scripted fallback:

```bash
ollama pull llama3.2:3b
```

**Python 3.12 is what the models were saved with.** They are pickles, so a
different NumPy major version will refuse to load them. If you see
`numpy._core` or `MT19937 is not a known BitGenerator`, you are on the wrong
interpreter — or just retrain with the two scripts above.

---

## The two models

| | **Optio** | **Deep Learning** |
|---|---|---|
| Classifier | LightGBM gradient boosting | MLP, 3 hidden layers (384 · 192 · 96) |
| Features | TF-IDF, 1–2 grams, 60k vocabulary | TF-IDF → TruncatedSVD → L2 → network |
| Trained by | `train_optio.py` | `train_deep.py` |
| Artefacts | `model/optio/` | `model/deep/` |

Both share the same retrieval core:

```
score = 0.78 · similarity      TF-IDF cosine between your request and the item
      + 0.22 · quality         how well other people rated it
      + 0.08 · audience        does it suit going alone / with friends / family
      − 0.35 · rejected        did you turn this exact title down before
```

What differs is the **search index each one carries** and **how it reads the
kind** of thing you are asking for — which changes the slice of the catalogue
that gets searched, and so the shortlist. When both read a request the same way
the shortlists are identical, and the interface says so instead of pretending
there is a choice to make.

### The preference loop

1. You ask for something.
2. `POST /api/compare` runs it through both engines.
3. Two shortlists appear side by side, each in its own colour.
4. You choose the better one — or "neither, really".
5. `POST /api/choose` stores the verdict against your account and marks the
   winning titles as liked, so the next request is scored with that preference
   already applied.

Every judgement lands in the `choices` table; the running tally is on the page.

---

## What is stored

SQLite, at `Optio/data/optio.db` — created on first run, never committed.

| Table | Holds |
|---|---|
| `users` | account, display name, PBKDF2-hashed password, saved profile |
| `sessions` | every login and logout, with timestamps |
| `events` | register, login, logout, message, request, feedback, reset |
| `choices` | which engine won each round, and both shortlists |
| `prefs` | every like and dislike, per account |

Passwords are PBKDF2-HMAC-SHA256 with a per-user salt, 120,000 rounds. This is
a student project, not a bank, but there is no excuse for plain text.

---

## Layout

```
index.html            the app
login.html            sign in / create account
assets/
  styles.css          design tokens, both themes, every component
  app.js              front end; live against app.py, or static fallback
  auth.js             sign in / register
  catalog-sample.json 420 real catalogue rows for the static preview

Optio/
  app.py              FastAPI: auth, both engines, SQLite, serves the UI
  db.py               schema and queries
  engines.py          loads both models, runs the comparison
  chatbot.py          the Optio class: profile, conversation, scoring
  feature.py          builds the catalogue from five public sources
  train_optio.py      LightGBM training
  train_deep.py       neural-network training
  rebuild_indexes.py  refit both search indexes against the catalogue
```

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/register` · `/api/login` · `/api/logout` | accounts |
| `GET /api/me` | account, profile, preferences, session history |
| `POST /api/chat` | one conversation turn |
| `POST /api/compare` | the same request through **both** engines |
| `POST /api/choose` | record which engine won |
| `POST /api/feedback` | like / dislike one title |
| `GET /api/status` | what loaded, what did not, and why |
| `GET /api/docs` | interactive Swagger UI |

---

## Support chat

The bottom-right button is wired for [Chatbase](https://www.chatbase.co). Open
`assets/app.js`, find `CHATBASE_ID`, and paste your agent id:

```js
const CHATBASE_ID = "your-agent-id-here";
```

The real widget then loads and replaces the placeholder panel. Until an id is
set, the button opens a panel explaining exactly that rather than pretending to
be a live agent.

---

## Known issues

- **Quality can outweigh similarity.** A TF-IDF cosine rarely exceeds `0.35`
  while `quality` reaches `1.0`, so despite the `0.78` weight the quality term
  often dominates. Normalising similarity before weighting would make the
  weights mean what they say. This is the recommender's own behaviour and has
  been left for its authors.
- **Saved indexes go stale when the catalogue grows.** `chatbot.py` only reuses
  a saved index when its row count matches the catalogue exactly, and silently
  refits otherwise — which made both engines return identical shortlists.
  `rebuild_indexes.py` fixes it without a full retrain; `train_*.py` fixes it
  properly.
- **The static preview cannot do accounts.** GitHub Pages has no Python, so the
  hosted build runs on a 420-item slice with the same scoring formula and says
  so on screen. Sign-in, the trained classifiers and saved history all need
  `app.py`.

---

## Built by

| | |
|---|---|
| **Iliya Cheshmi** | UI |
| **Reza Shahbazi** | UI |
| **Hosna Zandavi** | AI |
| **Radin Jalab** | AI |

Data: MovieLens (GroupLens) · Free Music Archive · Spotify song metadata ·
Fáilte Ireland Open Data · ThemeParks.wiki. All titles belong to their sources.
