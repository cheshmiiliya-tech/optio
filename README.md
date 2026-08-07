# Marquee

An entertainment guide interface — film, live music, comedy, stage and sport —
with an explainable AI recommendation and prediction layer sitting on top of the
published schedule.

No framework, no build step, no dependencies. Open `index.html` and it runs.

---

## Run it

**Simplest:** double-click `index.html`.

**With a local server** (recommended, matches how it will be hosted):

```bash
# Python
python -m http.server 8000

# Node
npx serve .
```

Then open <http://localhost:8000>.

---

## What's in it

### The schedule
- An 8-channel programme grid across a 9-hour window, generated **relative to the
  real clock** — "now" always lands inside the guide, whenever you open it.
- A live red playhead, a sticky channel column, horizontal scroll, and a
  **Jump to now** control.
- Genre-coded listings, a detail drawer, and a watchlist.

### The model
A small weighted recommender running entirely in the browser. Four signals:

| Signal | Weight | What it measures |
|---|---|---|
| Genre affinity | 42% | How much you watch this genre |
| Channel history | 22% | How often you land on this channel |
| Runtime fit | 14% | Distance from your average sitting length |
| Time slot | 22% | Where the start time falls in your viewing window |

Every number the interface shows is this function, and every "why" is its
decomposition — nothing is decorative.

- **Predicted for you** — top 5 upcoming, ranked, each with a match score, a
  confidence margin (`84% ±6`), a predicted rating, and the percentage
  contribution of each signal.
- **Your path** — a predicted lane inside the guide itself, on the same time
  axis as the channels. A greedy walk through tonight with softmax
  probabilities, and a confidence band that **fades as it projects further
  ahead**.
- **Your taste model** — a live readout of the vector: genre affinity bars, a
  viewing-window histogram, signal count, confidence.
- **Feedback loop** — `▲ More` / `▼ Less` write straight back to the vector.
  Scores, ranking, the predicted path and the model panel all recompute
  immediately.

### The decision system
A recommender ranks; a decision system **commits to an action** — and is allowed
to refuse. Candidates run through a deterministic, auditable pipeline:

```
candidate
  → GATES     hard constraints, pass/fail, before anything is scored
  → SCORE     the model, unchanged
  → RULES     signed adjustments applied in priority order
  → ABSTAIN   would the margin change the call? then hand it back
  → LADDER    thresholds map the final score to exactly one action
```

Six actions: `AUTOPLAY`, `PROMOTE`, `OFFER`, `ASK`, `DEMOTE`, `BLOCK`.

**`ASK` is the point of the whole layer.** The system abstains not when
uncertainty is merely *large*, but when the confidence band **straddles a
threshold boundary** — when the margin genuinely covers two different actions.
A wide margin that still points at one action is harmless and is acted on
normally. In the UI, `ASK` is the one verdict rendered in the human tungsten
rather than the machine blue: the decision has been handed back to you.

- **Signal graph** — the candidate's four signals radiating from the user node,
  edge weight proportional to each signal's share of the score, terminating in
  the verdict the engine committed to.
- **Decision trace** — the real execution log, step by step: which rule fired,
  what it added or subtracted, and the running score after it. Not a summary
  written afterwards.
- **Threshold ladder** — where the model's raw score landed, where policy moved
  it to, and which band it finished in.
- **Policy controls** — four thresholds and nine rule toggles. Every change
  re-decides all 60 upcoming listings live, and the rule list shows how many
  times each rule fired.

---

## Design notes

The page speaks in two deliberately different voices, so it is always clear
whether a human or the model asserted something. Every section carries a
provenance label.

|  | **Broadcast** (human) | **Model** (machine) |
|---|---|---|
| Colour | warm tungsten `#FFB627` | desaturated instrument blue `#6FBBD6` |
| Type | condensed poster caps | monospace, tabular numerals |
| Form | solid blocks, marquee bulbs | tick meters, contribution bars, hairline scales |

Other decisions:

- **Palette** — a darkened-auditorium aubergine ground rather than neutral grey
  or black; tungsten marquee bulbs as the accent; genre colours as a separate
  categorical set so semantic colour never collides with the brand accent.
- **Both themes are designed**, not inverted. The OS preference is the default;
  the **House lights** button overrides it and the choice is remembered.
- **Posters are generated in CSS** — layered gradients and a scanline overlay.
  No image assets, no network requests.
- **Accessibility** — visible focus rings, `Esc` closes the drawer, ARIA on
  progress and dialog roles, and `prefers-reduced-motion` is respected.
- **Honest uncertainty** — the model never states a bare number. Scores always
  carry a `±` band, and the predicted path visibly loses confidence the further
  into the evening it projects.

---

## Structure

```
index.html          markup
assets/styles.css   design tokens, both themes, all components
assets/app.js       schedule generation, the model, rendering
```

All programme titles, channels and synopses are fictional.

---

## Publish on GitHub Pages

Push the repo, then in **Settings → Pages** set the source to `main` / `/ (root)`.
`index.html` is at the root, so it is served as-is.
