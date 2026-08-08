# Movio

A conversational entertainment recommender. You tell it who you are and what
you feel like; it suggests movies, games and events from an 11,541-item
catalogue and explains, in plain words, why it picked each one.

**Live preview:** <https://cheshmiiliya-tech.github.io/marquee-entertainment-ui/>

---

## Two ways to run it

### 1. Full system (the real model)

```bash
cd Movio_final_code
pip install -r requirements.txt
python train_model.py        # builds the dataset, trains the classifier
python server.py             # serves the API and the UI together
```

Then open <http://127.0.0.1:8000>.

`train_model.py` downloads five public datasets on first run and writes
`data/entertainment_dataset.csv`, then trains a LightGBM classifier into
`model/`. It takes a while — the music metadata alone is ~350 MB.

### 2. Static preview (no Python)

Open `index.html`, or visit the GitHub Pages link above.

The page detects that no server is answering and falls back to a 420-item
slice of the **same** catalogue, scored with the **same** formula
reimplemented in the browser. It says so on screen. What is missing is the
LightGBM classifier and the language model — everything else is real.

---

## How the pieces fit

```
train_model.py ──► model/          LightGBM classifier + TF-IDF vectorisers
      │                            (predicts which KIND a request is about)
      ▼
  feature.py   ──► data/           builds the catalogue from 5 public sources
      │                            movies · games · events · songs · parks
      ▼
  chatbot.py   ──► Movio           profile, conversation, recommend()
      │
      ▼
  server.py    ──► HTTP API        the only bridge to the browser
      │
      ▼
 index.html + assets/              chat, profile, picks, explanation
```

| File | What it does |
|---|---|
| `Movio_final_code/feature.py` | Downloads and merges the five datasets into one catalogue |
| `Movio_final_code/train_model.py` | Trains the LightGBM kind-classifier, saves it and the metrics |
| `Movio_final_code/chatbot.py` | The `Movio` class: profile, conversation, scoring, feedback |
| `Movio_final_code/server.py` | Wraps `Movio` in a FastAPI app and serves the UI |
| `index.html` | Markup only |
| `assets/styles.css` | Design tokens, both themes, all components |
| `assets/app.js` | Front end; talks to the API, or falls back to static mode |
| `assets/catalog-sample.json` | 420 real catalogue rows for the static build |

### The API

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Catalogue size, whether the classifier loaded, which LLM is active |
| `POST /api/chat` | One turn of conversation, plus scored picks |
| `GET /api/profile` | The six-field profile Movio has built so far |
| `POST /api/feedback` | Writes a like/dislike into `data/user_feedback.csv` |
| `GET /api/explain` | Full score breakdown for one item |
| `GET /api/docs` | Interactive Swagger UI |

---

## How a recommendation is scored

Straight from `chatbot.py`:

```
score = 0.78 · similarity      TF-IDF cosine between your request and the item
      + 0.22 · quality         how well other people rated it
      + 0.08 · audience        does it suit going alone / with friends / family
      − 0.35 · rejected        did you turn this exact title down before
```

The percentage on screen rescales the achievable `0.05 – 0.55` range onto
`0 – 100`; the score itself is untouched. `server.py` and `assets/app.js` use
the same two constants so the live and static builds agree.

Your six profile answers all feed in: **taste** and the current request go
into the query text, **companion** adds its own vocabulary and the audience
bonus, **colour** maps to a genre hint, and **city/country** pull in nearby
events.

### Why the interface says what it says

Every number has a plain-language counterpart. The radial graph shows the four
signals as a share of the score — thicker line, bigger influence. The verdict
is one of four sentences rather than a code:

| Reading | Shown as |
|---|---|
| 70 % and above | **Strong match** |
| 45 – 69 % | **Worth a look** |
| below 45 % | **Not sure — you decide** |
| you rejected it | **You said no** |

**Show details** in the header reveals the raw numbers: each signal's raw
value, its weight, its contribution and its share.

---

## Design notes

The page speaks in two deliberately separate voices so it is always clear who
asserted what.

| | **You** | **The model** |
|---|---|---|
| Colour | warm tungsten | desaturated instrument blue |
| Type | condensed caps | monospace, tabular numerals |
| Used for | your profile, your answers, your feedback | scores, shares, the graph |

When the model is unsure it hands the decision back — and switches to the
warm tungsten to say so, because at that moment the call is yours.

Both themes are designed rather than inverted; the OS preference is the
default and the header button overrides it.

---

## Known issues

- **Quality can outweigh similarity.** A TF-IDF cosine rarely exceeds `0.35`
  while `quality` reaches `1.0`, so despite the `0.78` weight the quality term
  often dominates. Normalising similarity before weighting would make the
  weights mean what they say.
- **`theme park` and `song` need a working connection.** Both loaders were
  skipped when the catalogue in this repo was built; the other three
  succeeded. Re-run `python train_model.py --refresh` to pick them up.

## Credits

MovieLens (GroupLens) · Free Music Archive metadata · Fáilte Ireland Open Data
· ThemeParks.wiki · public video-game metadata. All titles belong to their
respective sources.
