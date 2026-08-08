/* ============================================================
   MOVIO — front end
   Two ways to run:

   LIVE   server.py is up. Every reply, score and profile field
          comes from the real Movio object in Python.
   STATIC no server (e.g. GitHub Pages). The page falls back to a
          420-item slice of the SAME catalogue the model was built
          from, and reimplements the SAME scoring formula in the
          browser. It says so on screen — nothing is invented.
   ============================================================ */
(function(){
  "use strict";

  const $ = function(id){ return document.getElementById(id); };
  const esc = function(s){ return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); };

  /* ---------- theme ---------- */
  (function(){
    const KEY = "movio-theme", root = document.documentElement, btn = $("themeBtn");
    const isDark = function(){
      return root.dataset.theme ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
    };
    const label = function(){ btn.textContent = isDark() ? "Light" : "Dark"; };
    const stored = localStorage.getItem(KEY);
    if(stored === "dark" || stored === "light") root.dataset.theme = stored;
    label();
    btn.addEventListener("click", function(){
      root.dataset.theme = isDark() ? "light" : "dark";
      localStorage.setItem(KEY, root.dataset.theme);
      label();
    });
  })();

  let toastTimer = null;
  function toast(msg){
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, 3000);
  }

  /* ============================================================
     STATE
     ============================================================ */
  const KIND_COLOR = {
    "movie":"var(--k-movie)", "game":"var(--k-game)", "event":"var(--k-event)",
    "song":"var(--k-song)", "theme park":"var(--k-park)"
  };
  const FIELDS = [
    {k:"name",      label:"Name",         ask:"What name should I call you?"},
    {k:"taste",     label:"What you like", ask:"What movies, songs, games, events, or parks do you enjoy?"},
    {k:"companion", label:"Going with",   ask:"Will you go Alone, with Friends, or with Family?"},
    {k:"country",   label:"Country",      ask:"Which country do you live in?"},
    {k:"city",      label:"City",         ask:"Which city do you live in?"},
    {k:"color",     label:"Favourite colour", ask:"What is your favourite colour?"}
  ];

  let LIVE = false;              // is server.py answering?
  let API  = "";                 // base url when live
  let data = null;               // static catalogue slice
  let profile = {name:null, taste:null, companion:null, country:null, city:null, color:null};
  let picks = [];
  let selected = null;
  let lastRequest = "";
  let rejected = new Set();
  let liked = new Set();
  let showTech = false;
  let status = {};

  /* ============================================================
     TRANSPORT
     ============================================================ */
  async function tryLive(){
    const bases = [location.origin, "http://127.0.0.1:8000"];
    for(const base of bases){
      if(!/^https?:/.test(base)) continue;
      try{
        const ctl = new AbortController();
        const t = setTimeout(function(){ ctl.abort(); }, 2500);
        const r = await fetch(base + "/api/status", {signal:ctl.signal});
        clearTimeout(t);
        if(!r.ok) continue;
        const s = await r.json();
        if(s && s.ready){ API = base; status = s; return true; }
      }catch(e){ /* try the next base */ }
    }
    return false;
  }

  async function post(path, body){
    const r = await fetch(API + path, {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)
    });
    return r.json();
  }

  /* ============================================================
     STATIC ENGINE — the same formula as chatbot.py recommend()
        score = .78*similarity + .22*quality + .08*audience - .35*rejected
     ============================================================ */
  const W = {similarity:0.78, quality:0.22, audience:0.08, rejected:-0.35};

  /* The raw score lives in roughly 0.05 - 0.55: TF-IDF cosine rarely clears
     0.35, so dividing by 1.0 squashes every result into the 30s and the page
     would read "not sure" about everything. Map the achievable range onto
     0-100 instead. Presentation only - the score itself is untouched, and
     server.py uses the identical mapping. */
  const MATCH_LO = 0.05, MATCH_HI = 0.55;
  function toMatch(score){
    return Math.round(Math.max(0, Math.min(1, (score - MATCH_LO) / (MATCH_HI - MATCH_LO))) * 100);
  }

  function tokenise(text){
    return String(text || "").toLowerCase()
      .replace(/[^a-z0-9؀-ۿ\s]/g," ").split(/\s+/)
      .filter(function(t){ return t.length > 2; });
  }

  function tfidfVector(tokens){
    const N = data.sample_total, tf = {};
    tokens.forEach(function(t){ tf[t] = (tf[t] || 0) + 1; });
    const vec = {};
    let norm = 0;
    Object.keys(tf).forEach(function(t){
      const df = data.df[t];
      if(!df) return;                                  // out of vocabulary
      const w = (1 + Math.log(tf[t])) * Math.log((1 + N) / (1 + df)) + 1;
      vec[t] = w; norm += w * w;
    });
    norm = Math.sqrt(norm) || 1;
    Object.keys(vec).forEach(function(t){ vec[t] /= norm; });
    return vec;
  }

  const itemVectors = new Map();
  function itemVector(it){
    if(!itemVectors.has(it.item_id)) itemVectors.set(it.item_id, tfidfVector(it.tok));
    return itemVectors.get(it.item_id);
  }

  function cosine(a, b){
    let s = 0;
    const keys = Object.keys(a).length < Object.keys(b).length ? a : b;
    for(const t in keys){ if(a[t] && b[t]) s += a[t] * b[t]; }
    return s;
  }

  function staticRecommend(request, count){
    const companion = profile.companion || "alone";
    const query = [
      profile.taste || "", request,
      data.companion_terms[companion] || "",
      data.color_terms[profile.color] || "",
      Array.from(liked).join(" ")
    ].join(" ");
    const qv = tfidfVector(tokenise(query));

    const kind = detectKind(request);
    const scored = data.items.map(function(it){
      const similarity = cosine(qv, itemVector(it));
      const audience = (it.audience || "").indexOf(companion) >= 0 ? 1 : 0;
      const rej = rejected.has(it.title.toLowerCase()) ? 1 : 0;
      const score = W.similarity*similarity + W.quality*it.quality
                  + W.audience*audience + W.rejected*rej;
      return {
        item_id:it.item_id, title:it.title, kind:it.kind, tags:it.tags,
        description:it.description, location:it.location, source:it.source,
        quality:it.quality, similarity:similarity, score:score,
        match: toMatch(score),
        parts: buildParts(similarity, it.quality, audience, rej, companion)
      };
    });

    let pool = scored;
    if(kind){
      const sub = scored.filter(function(o){ return o.kind === kind; });
      if(sub.length) pool = sub;
    }
    return pool.sort(function(a,b){ return b.score - a.score; }).slice(0, count || 5);
  }

  function buildParts(similarity, quality, audience, rej, companion){
    const raw = [
      ["similarity", "Matches what you asked for",      W.similarity * similarity],
      ["quality",    "Rated well by other people",      W.quality * quality],
      ["audience",   "Suits going " + companion,        W.audience * audience],
      ["rejected",   "You turned this down before",     W.rejected * rej]
    ];
    let total = 0;
    raw.forEach(function(r){ total += Math.abs(r[2]); });
    total = total || 1;
    return raw.map(function(r){
      return {key:r[0], label:r[1], value:r[2], share:Math.abs(r[2]) / total};
    });
  }

  const KIND_WORDS = {
    "movie":["movie","film","cinema","watch","فیلم"],
    "game":["game","gaming","playstation","xbox","nintendo","steam","play","بازی"],
    "song":["song","music","playlist","listen","album","آهنگ","موسیقی"],
    "theme park":["theme park","amusement park","roller coaster","ride","پارک"],
    "event":["event","concert","festival","gig","show","live","کنسرت","جشنواره"]
  };
  function detectKind(text){
    const t = " " + String(text || "").toLowerCase() + " ";
    let best = null, bestN = 0, tie = false;
    Object.keys(KIND_WORDS).forEach(function(k){
      let n = 0;
      KIND_WORDS[k].forEach(function(w){
        if(w.indexOf(" ") >= 0 ? t.indexOf(w) >= 0 : new RegExp("(?:^|\\W)" + w + "(?:\\W|$)").test(t)) n++;
      });
      if(n > bestN){ best = k; bestN = n; tie = false; }
      else if(n === bestN && n > 0){ tie = true; }
    });
    return bestN > 0 && !tie ? best : null;
  }

  /* ---------- static conversation: same field order as Movio ---------- */
  function nextField(){
    for(const f of FIELDS){ if(!profile[f.k]) return f; }
    return null;
  }
  function parseCompanion(t){
    const s = t.toLowerCase();
    if(/alone|solo|myself|تنها/.test(s)) return "alone";
    if(/friend|mates|دوست/.test(s)) return "friends";
    if(/family|kids|خانواده/.test(s)) return "family";
    return null;
  }
  function parseColour(t){
    const s = t.toLowerCase();
    for(const c of Object.keys(data.color_terms)){ if(s.indexOf(c) >= 0) return c; }
    return null;
  }
  function parseName(t){
    const m = t.match(/(?:my name is|call me|i am|i'm)\s+([\p{L}-]+)/iu);
    if(m) return m[1][0].toUpperCase() + m[1].slice(1);
    const words = t.match(/[\p{L}-]+/gu) || [];
    return words.length === 1 ? words[0][0].toUpperCase() + words[0].slice(1) : null;
  }

  function staticReply(text){
    const f = nextField();
    if(f){
      let value = text.trim(), ok = true;
      if(f.k === "name"){ value = parseName(text); ok = !!value; }
      if(f.k === "companion"){ value = parseCompanion(text); ok = !!value; }
      if(f.k === "color"){ value = parseColour(text); ok = !!value; }
      if(!ok) return {text:"I didn't quite catch that. " + f.ask, items:[]};
      profile[f.k] = value;
      const next = nextField();
      const lead = f.k === "name" ? "Nice to meet you, " + value + "."
                 : f.k === "companion" ? "Got it — " + value + "."
                 : f.k === "color" ? value[0].toUpperCase() + value.slice(1) + " it is."
                 : "Thanks.";
      return {text: next ? lead + " " + next.ask
                         : lead + " What are you in the mood for right now?", items:[]};
    }
    lastRequest = text;
    const items = staticRecommend(text, 5);
    return {
      text: items.length
        ? "Here are five that fit. Tell me what you think of them with the buttons."
        : "I couldn't find a good fit for that. Try describing a mood or a genre.",
      items: items
    };
  }

  /* ============================================================
     CHAT VIEW
     ============================================================ */
  function addMsg(who, text){
    const log = $("chatLog");
    const el = document.createElement("div");
    el.className = "msg msg-" + who;
    el.innerHTML = '<span class="msg-av">' + (who === "bot" ? "M" : "Y") + '</span>'
                 + '<span class="msg-b">' + esc(text) + '</span>';
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function addThinking(){
    const log = $("chatLog");
    const el = document.createElement("div");
    el.className = "msg msg-bot thinking";
    el.innerHTML = '<span class="msg-av">M</span>'
                 + '<span class="msg-b dots"><i></i><i></i><i></i></span>';
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  async function send(text){
    if(!text.trim()) return;
    addMsg("you", text);
    $("chatInput").value = "";
    $("chatSend").disabled = true;
    const think = addThinking();

    let reply;
    try{
      if(LIVE){
        const r = await post("/api/chat", {message:text});
        reply = {text:r.text, items:r.items || []};
        if(r.profile) profile = r.profile;
        lastRequest = text;
      }else{
        await new Promise(function(res){ setTimeout(res, 260); });
        reply = staticReply(text);
      }
    }catch(e){
      reply = {text:"I lost contact with the model. Is server.py still running?", items:[]};
    }

    think.remove();
    addMsg("bot", reply.text);
    $("chatSend").disabled = false;
    $("chatInput").focus();

    if(reply.items && reply.items.length){
      picks = reply.items;
      selected = picks[0];
      renderPicks();
      renderWhy();
      $("picksTitle").scrollIntoView({behavior:"smooth", block:"start"});
    }
    renderProfile();
    renderHints();
  }

  /* ============================================================
     PROFILE VIEW
     ============================================================ */
  function renderProfile(){
    const next = nextField();
    $("profGrid").innerHTML = FIELDS.map(function(f){
      const v = profile[f.k];
      const isNext = next && next.k === f.k;
      return '<div class="prof-card' + (v ? " filled" : "") + (isNext ? " next" : "") + '">'
        + '<span class="prof-k">' + esc(f.label) + '</span>'
        + '<span class="prof-v">' + esc(v || (isNext ? "asking next…" : "not yet")) + '</span>'
        + '</div>';
    }).join("");

    const done = FIELDS.filter(function(f){ return profile[f.k]; }).length;
    $("profProgress").innerHTML = FIELDS.map(function(f){
      return '<i class="' + (profile[f.k] ? "on" : "") + '"></i>';
    }).join("");
    $("profSub").textContent = done === FIELDS.length
      ? "All six answered — recommendations use every one of them."
      : done + " of " + FIELDS.length + " answered. Movio asks for the rest as you chat.";
  }

  function renderHints(){
    const f = nextField();
    let hints;
    if(f && f.k === "companion") hints = ["Alone", "With friends", "With family"];
    else if(f && f.k === "color") hints = ["Blue", "Red", "Green", "Purple"];
    else if(f) hints = [];
    else hints = ["Something funny to watch", "A game for two players",
                  "Live music this weekend", "Something relaxing"];
    $("chatHints").innerHTML = hints.map(function(h){
      return '<button class="hint" type="button">' + esc(h) + '</button>';
    }).join("");
  }
  $("chatHints").addEventListener("click", function(e){
    const b = e.target.closest(".hint");
    if(b) send(b.textContent);
  });

  /* ============================================================
     PICKS VIEW
     ============================================================ */
  function renderPicks(){
    if(!picks.length){
      $("picks").innerHTML = '<div class="empty">Nothing yet — tell Movio what you feel like above, '
        + 'and five suggestions will appear here.</div>';
      $("picksSub").textContent = "—";
      $("kindLegend").innerHTML = "";
      return;
    }
    $("picks").innerHTML = picks.map(function(p){
      const kc = KIND_COLOR[p.kind] || "var(--text-3)";
      const yes = liked.has(p.title.toLowerCase());
      const no  = rejected.has(p.title.toLowerCase());
      return '<article class="pick" data-id="' + esc(p.item_id) + '" style="--kc:' + kc + '"'
        + ' aria-current="' + (selected && selected.item_id === p.item_id) + '" tabindex="0">'
        + '<div class="pick-top"><span class="pick-t">' + esc(p.title) + '</span>'
        + '<span class="pick-k">' + esc(p.kind) + '</span></div>'
        + '<div class="pick-tags">' + esc(p.tags || p.description || "").slice(0, 96) + '</div>'
        + '<div class="pick-foot">'
          + '<span class="pick-score"><span class="pick-n">' + p.match + '<small>%</small></span>'
          + '<span class="meter" aria-label="' + p.match + ' percent"><i style="--w:' + p.match + '%"></i></span></span>'
          + '<span class="fbrow">'
            + '<button class="fb' + (yes ? " done" : "") + '" data-fb="like" type="button">Like</button>'
            + '<button class="fb no' + (no ? " done" : "") + '" data-fb="dislike" type="button">No</button>'
          + '</span>'
        + '</div></article>';
    }).join("");

    const kinds = {};
    picks.forEach(function(p){ kinds[p.kind] = (kinds[p.kind] || 0) + 1; });
    $("kindLegend").innerHTML = Object.keys(kinds).map(function(k){
      return '<span class="kind" style="--kc:' + (KIND_COLOR[k] || "var(--text-3)") + '"><i></i>'
           + esc(k) + ' ' + kinds[k] + '</span>';
    }).join("");
    $("picksSub").textContent = 'For "' + lastRequest + '" · pick one to see why';
  }

  $("picks").addEventListener("click", function(e){
    const fb = e.target.closest("[data-fb]");
    const card = e.target.closest(".pick");
    if(!card) return;
    const p = picks.filter(function(x){ return x.item_id === card.dataset.id; })[0];
    if(!p) return;

    if(fb){
      e.stopPropagation();
      const key = p.title.toLowerCase();
      if(fb.dataset.fb === "like"){ liked.add(key); rejected.delete(key); }
      else { rejected.add(key); liked.delete(key); }
      if(LIVE){
        post("/api/feedback", {verdict:fb.dataset.fb, title:p.title})
          .then(function(){ toast("Saved to user_feedback.csv — Movio remembers this."); })
          .catch(function(){ toast("Could not reach the server to save that."); });
      }else{
        toast(fb.dataset.fb === "like"
          ? "Noted. Similar things will score higher."
          : "Noted. This drops the score by 0.35 next time.");
      }
      renderPicks(); renderWhy();
      return;
    }
    selected = p;
    renderPicks(); renderWhy();
  });

  /* ============================================================
     WHY — the friendly view
     ============================================================ */
  const ANGLES = [-90, 0, 90, 180];   /* top, right, bottom, left */

  function renderWhy(){
    if(!selected){
      $("graphFor").textContent = "Pick something above";
      $("graphNote").textContent = "—";
      $("graphEdges").innerHTML = "";
      $("graphNodes").innerHTML = "";
      $("callBadge").textContent = "—";
      $("callSays").textContent = "Choose one of the suggestions to see how it was scored.";
      $("reasons").innerHTML = "";
      $("whyActions").innerHTML = "";
      $("whySub").textContent = "—";
      $("techBody").innerHTML = "";
      return;
    }
    const p = selected;
    const parts = {};
    p.parts.forEach(function(x){ parts[x.key] = x; });

    /* ---- graph: four plain-language nodes around you ---- */
    const nodes = [
      {k:"similarity", label:"Matches what<br>you asked for", pct:Math.round(parts.similarity.share*100), c:"var(--signal)"},
      {k:"quality",    label:"Other people<br>rate it well",  pct:Math.round(parts.quality.share*100),    c:"var(--signal)"},
      {k:"audience",   label:"Good for going<br>" + esc(profile.companion || "alone"), pct:Math.round(parts.audience.share*100), c:"var(--signal)"},
      {k:"rejected",   label:"Things you<br>said no to",      pct:Math.round(parts.rejected.share*100),   c:"var(--live)"}
    ];

    let edges = "", divs = "";
    nodes.forEach(function(n, i){
      const a = ANGLES[i] * Math.PI / 180;
      const x = 50 + 32 * Math.cos(a), y = 50 + 33 * Math.sin(a);
      const w = 0.6 + (n.pct / 100) * 6;
      edges += '<line x1="50" y1="50" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '"'
             + ' stroke="' + n.c + '" stroke-width="' + w.toFixed(2) + '"'
             + ' stroke-opacity="' + Math.min(1, .2 + n.pct/70).toFixed(2) + '"'
             + ' vector-effect="non-scaling-stroke" />';
      divs += '<div class="gnode' + (n.pct < 5 ? " faint" : "") + '"'
            + ' style="left:' + x.toFixed(1) + '%;top:' + y.toFixed(1) + '%;--nc:' + n.c + '">'
            + '<span class="gnode-l">' + n.label + '</span>'
            + '<span class="gnode-v">' + n.pct + '%</span></div>';
    });
    $("graphEdges").innerHTML = edges;
    $("graphNodes").innerHTML = divs
      + '<div class="gnode gnode-core" style="left:50%;top:50%">'
      + '<span class="gnode-l">Overall</span><span class="gnode-v">' + p.match + '%</span></div>';

    $("graphFor").textContent = p.title.length > 34 ? p.title.slice(0, 34) + "…" : p.title;
    $("graphNote").textContent = p.kind;

    /* ---- the call, in words ---- */
    const top = p.parts.slice().sort(function(a,b){ return b.share - a.share; })[0];
    let call, says, cc;
    if(rejected.has(p.title.toLowerCase())){
      call = "You said no"; cc = "var(--live)";
      says = "I've dropped this one. It won't come back near the top.";
    }else if(p.match >= 70){
      call = "Strong match"; cc = "var(--v-go)";
      says = "This is the kind of thing you've told me you like. I'd start here.";
    }else if(p.match >= 45){
      call = "Worth a look"; cc = "var(--signal)";
      says = "A reasonable fit — good, but not a perfect read on your taste.";
    }else{
      call = "Not sure — you decide"; cc = "var(--accent)";
      says = "I don't have enough to go on for this one. Your call, and tell me either way.";
    }
    const badge = $("callBadge");
    badge.textContent = call;
    badge.style.setProperty("--cc", cc);
    $("callSays").textContent = says;
    $("whenDecided").textContent = p.match + "% overall";

    $("reasons").innerHTML = p.parts.map(function(x){
      const strong = x.share >= 0.30, none = Math.abs(x.value) < 1e-9;
      const dir = x.value < 0 ? "down" : (none ? "flat" : "up");
      const mark = x.value < 0 ? "−" : (none ? "·" : "+");
      let phrase;
      if(x.key === "similarity") phrase = none ? "Nothing in it lines up with your words"
        : (strong ? "Closely matches <em>" + esc(lastRequest) + "</em>" : "Some overlap with what you asked for");
      else if(x.key === "quality") phrase = strong ? "People rate this <em>highly</em>" : "Middling ratings from other people";
      else if(x.key === "audience") phrase = none ? "Not especially suited to going <em>" + esc(profile.companion || "alone") + "</em>"
        : "Suits going <em>" + esc(profile.companion || "alone") + "</em>";
      else phrase = none ? "You've never turned this down" : "You turned this down before";
      return '<li class="reason ' + dir + '"><b>' + mark + '</b><span>' + phrase + '</span></li>';
    }).join("");

    $("whyActions").innerHTML =
        '<button class="btn btn-sm" data-act="like">Yes, more like this</button>'
      + '<button class="btn btn-sm" data-act="dislike">Not for me</button>';

    $("whySub").textContent = "Showing " + p.title;
    renderTech(p);
  }

  $("whyActions").addEventListener("click", function(e){
    const b = e.target.closest("[data-act]");
    if(!b || !selected) return;
    const key = selected.title.toLowerCase();
    if(b.dataset.act === "like"){ liked.add(key); rejected.delete(key); }
    else { rejected.add(key); liked.delete(key); }
    if(LIVE) post("/api/feedback", {verdict:b.dataset.act, title:selected.title})
      .then(function(){ toast("Saved to user_feedback.csv."); }).catch(function(){});
    else toast("Noted.");
    renderPicks(); renderWhy();
  });

  /* ---- technical view, behind the toggle ---- */
  function renderTech(p){
    const parts = {};
    p.parts.forEach(function(x){ parts[x.key] = x; });
    const raws = {
      similarity: p.similarity, quality: p.quality,
      audience: parts.audience.value !== 0 ? 1 : 0,
      rejected: parts.rejected.value !== 0 ? 1 : 0
    };
    $("techBody").innerHTML = p.parts.map(function(x){
      const cls = x.value > 0 ? "pos" : (x.value < 0 ? "neg" : "");
      return "<tr><td>" + esc(x.key) + "</td>"
        + '<td class="r num">' + Number(raws[x.key] || 0).toFixed(4) + "</td>"
        + '<td class="r num">' + W[x.key].toFixed(2) + "</td>"
        + '<td class="r num ' + cls + '">' + (x.value >= 0 ? "+" : "") + Number(x.value).toFixed(4) + "</td>"
        + '<td class="r num">' + Math.round(x.share*100) + "%</td></tr>";
    }).join("")
    + '<tr class="total"><td>score</td><td class="r"></td><td class="r"></td>'
      + '<td class="r num">' + Number(p.score).toFixed(4) + "</td>"
      + '<td class="r num">' + p.match + "%</td></tr>";
    $("techNote").textContent = LIVE ? "computed in Python" : "computed in the browser";
    $("techFormula").textContent =
      "score = 0.78·similarity + 0.22·quality + 0.08·audience − 0.35·rejected   "
      + "· match% rescales the achievable 0.05–0.55 range onto 0–100. "
      + (LIVE ? "similarity is scikit-learn TF-IDF cosine over the full catalogue."
              : "similarity is a TF-IDF cosine over the 420-item sample.");
  }

  $("detailBtn").addEventListener("click", function(){
    showTech = !showTech;
    $("tech").hidden = !showTech;
    $("detailBtn").setAttribute("aria-pressed", String(showTech));
    $("detailBtn").textContent = showTech ? "Hide details" : "Show details";
  });

  /* ============================================================
     BOOT
     ============================================================ */
  $("chatForm").addEventListener("submit", function(e){
    e.preventDefault();
    send($("chatInput").value);
  });

  $("resetBtn").addEventListener("click", async function(){
    profile = {name:null, taste:null, companion:null, country:null, city:null, color:null};
    picks = []; selected = null; liked.clear(); rejected.clear(); lastRequest = "";
    $("chatLog").innerHTML = "";
    if(LIVE){
      try{
        const r = await post("/api/reset", {});
        addMsg("bot", r.text || "Let's start again. What name should I call you?");
      }catch(e){ addMsg("bot", "Let's start again. What name should I call you?"); }
    }else{
      addMsg("bot", "Let's start again. What name should I call you?");
    }
    renderProfile(); renderPicks(); renderWhy(); renderHints();
  });

  $("statusChip").addEventListener("click", function(){
    if(LIVE){
      toast(status.catalog_rows.toLocaleString() + " items · classifier "
        + (status.classifier_loaded ? "loaded" : "not trained") + " · " + status.llm);
    }else{
      toast("Static mode: " + data.sample_total + " real items from the "
        + data.catalog_total.toLocaleString() + "-item catalogue. Run server.py for the full model.");
    }
  });

  function setStatus(){
    const chip = $("statusChip");
    if(LIVE){
      chip.classList.add("live");
      $("statusText").textContent = "live · " + status.catalog_rows.toLocaleString() + " items"
        + (status.classifier_loaded ? " · classifier on" : "");
      $("footRight").textContent = "server.py · " + status.llm
        + " · classifier " + (status.classifier_loaded ? "loaded" : "not trained");
      $("footLeft").textContent = "Movio — every number on this page came from the Python model.";
    }else{
      chip.classList.add("demo");
      $("statusText").textContent = "static · " + data.sample_total + " items";
      $("footRight").textContent = "static build · no Python running";
      $("footLeft").textContent = "Movio — static preview built from the real catalogue.";
      const banner = document.createElement("div");
      banner.className = "banner";
      banner.innerHTML = "<div><b>You are seeing the static preview.</b>"
        + "These " + data.sample_total + " items are real rows from the "
        + data.catalog_total.toLocaleString() + "-item catalogue the model was built from, and the scoring "
        + "formula is the same one. What is missing is the LightGBM classifier and the "
        + "language model. To run the whole thing: <code>cd Movio_final_code</code> then "
        + "<code>python server.py</code>.</div>";
      document.querySelector(".shell").appendChild(banner);
    }
  }

  (async function boot(){
    LIVE = await tryLive();
    if(!LIVE){
      try{
        const r = await fetch("assets/catalog-sample.json");
        data = await r.json();
      }catch(e){
        $("chatLog").innerHTML = '<div class="empty">Could not load the catalogue sample.</div>';
        return;
      }
    }
    setStatus();
    renderProfile(); renderPicks(); renderWhy(); renderHints();

    if(LIVE){
      try{
        const g = await fetch(API + "/api/greeting").then(function(r){ return r.json(); });
        addMsg("bot", g.text || "Hi, I'm Movio. What name should I call you?");
        const pr = await fetch(API + "/api/profile").then(function(r){ return r.json(); });
        if(pr.profile){ profile = pr.profile; renderProfile(); renderHints(); }
      }catch(e){ addMsg("bot", "Hi, I'm Movio. What name should I call you?"); }
    }else{
      addMsg("bot", "Hi, I'm Movio. I help you pick something to watch, play, or go to. "
        + "What name should I call you?");
    }
  })();
})();
