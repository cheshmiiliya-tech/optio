===============================================================================

                                   O P T I O
                      AI Entertainment Decision System

===============================================================================

  Live preview   https://cheshmiiliya-tech.github.io/optio/
  Source         https://github.com/cheshmiiliya-tech/optio

  Iliya Cheshmi          Interface
  Reza Shahbazi          Interface
  Hosna Sadat Zandavi    Models
  Radin Jallab           Models


-------------------------------------------------------------------------------
  1.  WHAT IT IS
-------------------------------------------------------------------------------

  You tell Optio what you feel like. Two different machine-learning models
  answer the same question at the same time, and you say which one read you
  better. That judgement is stored against your account and changes what you
  are shown next.

  Most recommenders give you one answer and ask you to trust it. Optio gives
  you two and asks you to compare. The disagreement between the models is the
  interesting part, so it is put on screen instead of hidden.

  The catalogue is 36,016 real items - films, games, songs, events,
  restaurants, cafes, theme parks and travel places - built from five public
  datasets. Nothing in the catalogue is invented.


-------------------------------------------------------------------------------
  2.  RUNNING IT
-------------------------------------------------------------------------------

  Windows, one step:

      Double-click  START-OPTIO.bat

  That is the whole instruction. The launcher finds a suitable Python,
  installs anything missing, starts the server and opens your browser. First
  start takes a minute while it builds a search index over 36,016 items.

  If you prefer a terminal, in PowerShell:

      cd Optio
      .\run.ps1              start
      .\run.ps1 -Setup       install requirements first, then start
      .\run.ps1 -Restart     free port 8000 and start again
      .\run.ps1 -Check       report what is installed, change nothing

  Then open  http://127.0.0.1:8000  and create an account.

  NOTE ON PYTHON VERSION
  The trained models are pickles saved under Python 3.12 with NumPy 2.x. On
  an older interpreter they will not unpickle, and the site runs without its
  two classifiers - everything else still works. Run  .\run.ps1 -Setup  to
  install into 3.12, or retrain with the scripts in section 6.

  OPTIONAL - natural language replies
      ollama pull llama3.2:3b
  Without it the assistant uses scripted replies, which is a supported mode,
  not a failure.


-------------------------------------------------------------------------------
  3.  WHAT TO LOOK AT, IN ORDER
-------------------------------------------------------------------------------

  1.  Create an account. Username 3+ characters, password 6+ characters.
      A welcome panel explains the system and names the team. It can be
      reopened at any time with the About button.

  2.  Answer the six questions. Name, what you like, who you are going with,
      country, city, favourite colour. The panel at the top fills in as you
      answer, so you can see exactly what the system knows about you.

  3.  Ask for something - "a funny film for tonight", "a co-op game",
      "live music this weekend". TWO SHORTLISTS APPEAR SIDE BY SIDE, one per
      model, each in its own colour. This is the centre of the project.

  4.  Press "Which one read you better?". The winning shortlist is kept, its
      titles are added to your likes, and the running tally updates. The next
      answer is scored with that preference already applied.

  5.  Click any title to open "Why this one?". A radial graph shows the four
      signals behind the score, sized by how much each one mattered, with a
      plain-language verdict. "Show details" in the header reveals the raw
      numbers behind it.

  6.  Scroll to "Predicted for you". This is the classifier speaking without
      being asked: from your stated taste and everything you have liked, it
      predicts which KIND of thing you will want next, with a confidence.

  7.  Below that, "Your evening lineup" - eat, go out, watch, wind down.


-------------------------------------------------------------------------------
  4.  THE TWO MODELS
-------------------------------------------------------------------------------

                     OPTIO                      DEEP LEARNING
  Classifier         LightGBM gradient          Neural network, 3 hidden
                     boosting                   layers (384, 192, 96)
  Features           TF-IDF, 1-2 grams          TF-IDF -> TruncatedSVD
                                                -> L2 norm -> network
  Validation         99.90% accuracy            see model/deep/metrics.json
  Trained by         train_optio.py             train_deep.py
  Artefacts          model/optio/               model/deep/

  Both share the same retrieval core:

      score = 0.78 x similarity     text match between request and item
            + 0.22 x quality        how well other people rated it
            + 0.08 x audience       does it suit alone / friends / family
            - 0.35 x rejected       did you turn this exact title down before

  What differs is the search index each carries and how each reads the KIND
  of thing you are asking for. That changes which slice of the catalogue is
  searched, and so the shortlist. When both read a request the same way the
  shortlists are identical - and the interface says so, rather than
  pretending there is a choice to make.

  The percentage on screen rescales the achievable 0.05-0.55 score range onto
  0-100. The score itself is untouched; every build uses the same constants.


-------------------------------------------------------------------------------
  5.  WHAT IS STORED, AND WHERE
-------------------------------------------------------------------------------

  SQLite, at  Optio/data/optio.db  - created on first run, never committed
  to the repository, never sent anywhere.

      users       account, display name, hashed password, saved profile
      sessions    every login and logout, with timestamps
      events      register, login, logout, message, request, feedback
      choices     which model won each round, and both shortlists
      prefs       every like and dislike, per account

  Passwords are PBKDF2-HMAC-SHA256 with a per-user salt, 120,000 rounds.
  Nothing is stored in plain text. Everything stays on the machine running
  the server.


-------------------------------------------------------------------------------
  6.  PROJECT LAYOUT
-------------------------------------------------------------------------------

  START-OPTIO.bat        double-click to run everything
  index.html             the application
  login.html             sign in / create account
  assets/
      styles.css         design tokens, both themes, every component
      app.js             front end
      auth.js            sign in / register
      catalog-sample.json  540 real catalogue rows for the static preview

  Optio/
      app.py             FastAPI: accounts, both models, database, serves UI
      db.py              schema and queries
      engines.py         loads both models, runs the comparison
      chatbot.py         conversation, profile, scoring
      feature.py         builds the catalogue from five public sources
      train_optio.py     trains the LightGBM classifier
      train_deep.py      trains the neural network
      rebuild_indexes.py refits both search indexes
      run.ps1            launcher

  HTTP API - full interactive documentation at  /api/docs

      POST /api/register  /api/login  /api/logout      accounts
      GET  /api/me                                     profile and history
      POST /api/chat                                   one conversation turn
      POST /api/compare                                BOTH models answer
      POST /api/choose                                 record the winner
      POST /api/feedback                               like / dislike
      GET  /api/predicted                              what you will want next
      GET  /api/lineup                                 an evening in four slots
      GET  /api/status                                 what loaded, and why not


-------------------------------------------------------------------------------
  7.  THE HOSTED PREVIEW
-------------------------------------------------------------------------------

  The GitHub Pages link serves files but cannot run Python. There is no
  database behind it, so accounts and saved history are not available there,
  and the two trained classifiers cannot be loaded.

  What it does have is real: 540 rows drawn from the same 36,016-item
  catalogue, scored with the same formula reimplemented in the browser, and
  both models still answer separately. The page states which mode it is in.

  For the complete system - accounts, the trained models, saved preferences -
  run it locally as described in section 2.


-------------------------------------------------------------------------------
  8.  KNOWN LIMITATIONS
-------------------------------------------------------------------------------

  We would rather state these than have you find them.

  - Quality can outweigh similarity. A text-match score rarely exceeds 0.35
    while the quality term reaches 1.0, so despite its 0.78 weight the
    similarity term does not always dominate as the formula implies.
    Normalising similarity before weighting would fix it. This is the
    recommender's own behaviour and has been left as its authors wrote it.

  - Saved search indexes go stale when the catalogue grows. The loader only
    reuses an index whose row count matches the catalogue exactly, and
    silently refits otherwise. rebuild_indexes.py corrects this without a
    full retrain.

  - The support chat in the corner is a small scripted helper covering the
    questions this site actually receives. It is not a language model and
    does not claim to be one. It is wired for Chatbase: set CHATBASE_ID in
    assets/app.js and the real agent replaces it.

  - Two of the five data sources (theme parks, music) need a working internet
    connection at catalogue build time. If a source is unreachable it is
    skipped and the catalogue is built from the rest.


-------------------------------------------------------------------------------
  9.  DATA SOURCES AND LICENCE
-------------------------------------------------------------------------------

  MovieLens (GroupLens Research)
  Free Music Archive metadata
  Spotify song metadata (public dataset)
  Failte Ireland Open Data
  ThemeParks.wiki API

  All titles, ratings and descriptions belong to their respective sources and
  are used here for a non-commercial student project. Our own code is
  released under the MIT Licence - see the LICENSE file.

===============================================================================
