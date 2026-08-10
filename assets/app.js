/* ============================================================
   OPTIO — AI Entertainment Decision System

   LIVE    app.py is answering. Accounts, both recommenders and the
           SQLite record are all real.
   STATIC  no server (e.g. GitHub Pages). Falls back to a 420-item
           slice of the SAME catalogue and reimplements the SAME
           scoring formula in the browser. Two engines are simulated
           by using the two kind-detection strategies the real models
           differ on. The page says which mode it is in; nothing is
           passed off as something it is not.
   ============================================================ */
(function(){
  "use strict";

  const $ = function(id){ return document.getElementById(id); };
  const esc = function(s){ return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); };

  /* ---------- theme ---------- */
  (function(){
    const KEY = "optio-theme", root = document.documentElement, btn = $("themeBtn");
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
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, 3200);
  }

  /* ============================================================
     STATE
     ============================================================ */
  const KIND_COLOR = {
    "movie":"var(--k-movie)", "game":"var(--k-game)", "event":"var(--k-event)",
    "song":"var(--k-song)", "theme park":"var(--k-park)", "restaurant":"var(--k-event)",
    "cafe":"var(--k-event)", "travel place":"var(--k-park)",
    "shopping center":"var(--k-song)", "bazaar":"var(--k-song)"
  };
  const FIELDS = [
    {k:"name",      label:"Name",             ask:"What name should I call you?"},
    {k:"taste",     label:"What you like",    ask:"What movies, songs, games, events, or places do you enjoy?"},
    {k:"companion", label:"Going with",       ask:"Will you go Alone, with Friends, or with Family?"},
    {k:"country",   label:"Country",          ask:"Which country do you live in?"},
    {k:"city",      label:"City",             ask:"Which city do you live in?"},
    {k:"color",     label:"Favourite colour", ask:"What is your favourite colour?"}
  ];
  const ENGINES = [
    {key:"optio", label:"Optio",         blurb:"Gradient boosting (LightGBM). Sharp on clear wording."},
    {key:"deep",  label:"Deep Learning", blurb:"Three-layer neural network. Better on vague phrasing."}
  ];

  let LIVE = false, data = null, status = {};
  let me = null;                       // signed-in account
  let profile = {name:null, taste:null, companion:null, country:null, city:null, color:null};
  let duel = null;                     // {optio:{items}, deep:{items}}
  let lastRequest = "";
  let selected = null;
  let liked = new Set(), rejected = new Set();
  let scoreboard = {optio:0, deep:0, neither:0};
  let showTech = false;

  /* ============================================================
     TRANSPORT
     ============================================================ */
  async function api(path, options){
    const r = await fetch(path, Object.assign({credentials:"include"}, options || {}));
    const body = await r.json().catch(function(){ return {}; });
    if(!r.ok) throw Object.assign(new Error(body.error || r.statusText), {status:r.status, body:body});
    return body;
  }
  function post(path, payload){
    return api(path, {method:"POST", headers:{"Content-Type":"application/json"},
                      body:JSON.stringify(payload || {})});
  }

  /* ============================================================
     STATIC ENGINE — same formula as chatbot.py _recommend_core()
       score = .78*similarity + .22*quality + .08*audience - .35*rejected
     ============================================================ */
  const W = {similarity:0.78, quality:0.22, audience:0.08, rejected:-0.35};
  const MATCH_LO = 0.05, MATCH_HI = 0.55;
  const toMatch = function(s){
    return Math.round(Math.max(0, Math.min(1, (s - MATCH_LO) / (MATCH_HI - MATCH_LO))) * 100);
  };

  function tokenise(t){
    return String(t||"").toLowerCase().replace(/[^a-z0-9؀-ۿ\s]/g," ")
      .split(/\s+/).filter(function(x){ return x.length > 2; });
  }
  function tfidf(tokens){
    const N = data.sample_total, tf = {};
    tokens.forEach(function(t){ tf[t] = (tf[t]||0) + 1; });
    const v = {}; let norm = 0;
    Object.keys(tf).forEach(function(t){
      const df = data.df[t];
      if(!df) return;
      const w = (1 + Math.log(tf[t])) * Math.log((1 + N) / (1 + df)) + 1;
      v[t] = w; norm += w*w;
    });
    norm = Math.sqrt(norm) || 1;
    Object.keys(v).forEach(function(t){ v[t] /= norm; });
    return v;
  }
  const vecCache = new Map();
  function itemVec(it){
    if(!vecCache.has(it.item_id)) vecCache.set(it.item_id, tfidf(it.tok));
    return vecCache.get(it.item_id);
  }
  function cosine(a,b){
    let s = 0;
    const small = Object.keys(a).length < Object.keys(b).length ? a : b;
    for(const t in small){ if(a[t] && b[t]) s += a[t]*b[t]; }
    return s;
  }

  const KIND_WORDS = {
    "movie":["movie","film","cinema","watch"],
    "game":["game","gaming","playstation","xbox","nintendo","steam"],
    "song":["song","music","playlist","listen","album"],
    "theme park":["theme park","amusement park","roller coaster","ride"],
    "event":["event","concert","festival","gig","show"]
  };
  /* The real difference between the two models is how strictly they
     commit to a kind. Optio's LightGBM path takes the single unambiguous
     keyword winner; the network is happier to guess from a partial match.
     The static build mirrors that split rather than inventing one. */
  function detectKind(text, strict){
    const t = " " + String(text||"").toLowerCase() + " ";
    let best = null, bestN = 0, tie = false;
    Object.keys(KIND_WORDS).forEach(function(k){
      let n = 0;
      KIND_WORDS[k].forEach(function(w){
        if(w.indexOf(" ") >= 0 ? t.indexOf(w) >= 0
           : new RegExp("(?:^|\\W)" + w + "(?:\\W|$)").test(t)) n++;
      });
      if(n > bestN){ best = k; bestN = n; tie = false; }
      else if(n === bestN && n > 0){ tie = true; }
    });
    if(bestN > 0 && !tie) return best;
    if(strict) return null;
    return bestN > 0 ? best : null;      // the looser reading
  }

  function staticEngine(request, engineKey, count){
    const companion = profile.companion || "alone";
    const query = [profile.taste||"", request,
      data.companion_terms[companion]||"", data.color_terms[profile.color]||"",
      Array.from(liked).join(" ")].join(" ");
    const qv = tfidf(tokenise(query));
    const kind = detectKind(request, engineKey === "optio");

    const scored = data.items.map(function(it){
      const similarity = cosine(qv, itemVec(it));
      const audience = (it.audience||"").indexOf(companion) >= 0 ? 1 : 0;
      const rej = rejected.has(it.title.toLowerCase()) ? 1 : 0;
      const score = W.similarity*similarity + W.quality*it.quality
                  + W.audience*audience + W.rejected*rej;
      return {item_id:it.item_id, title:it.title, kind:it.kind, tags:it.tags,
              description:it.description, location:it.location, source:it.source,
              quality:it.quality, similarity:similarity, score:score,
              match:toMatch(score), engine:engineKey,
              parts:parts(similarity, it.quality, audience, rej, companion)};
    });
    let pool = scored;
    if(kind){
      const sub = scored.filter(function(o){ return o.kind === kind; });
      if(sub.length) pool = sub;
    }
    const out = pool.sort(function(a,b){ return b.score - a.score; }).slice(0, count||4);
    out.forEach(function(o,i){ o.rank = i+1; });
    return {items:out, detected_kind:kind};
  }

  function parts(similarity, quality, audience, rej, companion){
    const raw = [
      ["similarity","Matches what you asked for", W.similarity*similarity],
      ["quality","Rated well by other people",    W.quality*quality],
      ["audience","Suits going " + companion,     W.audience*audience],
      ["rejected","You turned this down before",  W.rejected*rej]
    ];
    let total = 0;
    raw.forEach(function(r){ total += Math.abs(r[2]); });
    total = total || 1;
    return raw.map(function(r){ return {key:r[0], label:r[1], value:r[2], share:Math.abs(r[2])/total}; });
  }

  /* ---------- static conversation ---------- */
  function nextField(){ for(const f of FIELDS){ if(!profile[f.k]) return f; } return null; }
  function parseCompanion(t){
    const s = t.toLowerCase();
    if(/alone|solo|myself/.test(s)) return "alone";
    if(/friend|mates/.test(s)) return "friends";
    if(/family|kids/.test(s)) return "family";
    return null;
  }
  function parseColour(t){
    const s = t.toLowerCase();
    for(const c of Object.keys(data.color_terms)) if(s.indexOf(c) >= 0) return c;
    return null;
  }
  function parseName(t){
    const m = t.match(/(?:my name is|call me|i am|i'm)\s+([\p{L}-]+)/iu);
    if(m) return m[1][0].toUpperCase() + m[1].slice(1);
    const w = t.match(/[\p{L}-]+/gu) || [];
    return w.length === 1 ? w[0][0].toUpperCase() + w[0].slice(1) : null;
  }

  function staticTurn(text){
    const f = nextField();
    if(f){
      let value = text.trim(), ok = true;
      if(f.k === "name"){ value = parseName(text); ok = !!value; }
      if(f.k === "companion"){ value = parseCompanion(text); ok = !!value; }
      if(f.k === "color"){ value = parseColour(text); ok = !!value; }
      if(!ok) return {text:"I didn't quite catch that. " + f.ask};
      profile[f.k] = value;
      const next = nextField();
      const lead = f.k === "name" ? "Nice to meet you, " + value + "."
                 : f.k === "companion" ? "Got it — " + value + "."
                 : f.k === "color" ? value[0].toUpperCase() + value.slice(1) + " it is."
                 : "Thanks.";
      return {text: next ? lead + " " + next.ask
                         : lead + " Now — what are you in the mood for?"};
    }
    lastRequest = text;
    return {
      text:"Both models had a go. Have a look and tell me which shortlist suits you better.",
      compare:{
        optio: Object.assign({label:"Optio", ready:true}, staticEngine(text, "optio", 4)),
        deep:  Object.assign({label:"Deep Learning", ready:true}, staticEngine(text, "deep", 4))
      }
    };
  }

  /* ============================================================
     CHAT
     ============================================================ */
  function addMsg(who, text){
    const log = $("chatLog");
    const el = document.createElement("div");
    el.className = "msg msg-" + who;
    el.innerHTML = '<span class="msg-av">' + (who === "bot" ? "O" : "Y") + '</span>'
                 + '<span class="msg-b">' + esc(text) + '</span>';
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function addThinking(){
    const log = $("chatLog");
    const el = document.createElement("div");
    el.className = "msg msg-bot thinking";
    el.innerHTML = '<span class="msg-av">O</span>'
                 + '<span class="msg-b dots"><i></i><i></i><i></i></span>';
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  async function send(text){
    if(!text.trim()) return;
    if(LIVE && !me){
      toast("Please sign in first.");
      location.href = "/login";
      return;
    }
    addMsg("you", text);
    $("chatInput").value = "";
    $("chatSend").disabled = true;
    const think = addThinking();

    let reply;
    try{
      if(LIVE){
        reply = await post("/api/chat", {message:text});
        if(reply.profile) profile = Object.assign(profile, reply.profile);
        if(reply.request) lastRequest = reply.request;
      }else{
        await new Promise(function(r){ setTimeout(r, 240); });
        reply = staticTurn(text);
      }
    }catch(err){
      if(err.status === 401){ location.href = "/login"; return; }
      reply = {text:"I lost contact with the model. Is app.py still running?"};
    }

    think.remove();
    addMsg("bot", reply.text || "…");
    $("chatSend").disabled = false;
    $("chatInput").focus();

    if(reply.compare){
      duel = reply.compare;
      selected = firstItem();
      renderDuel();
      renderWhy();
      $("duelTitle").scrollIntoView({behavior:"smooth", block:"start"});
    }
    renderProfile();
    renderHints();
  }

  function firstItem(){
    for(const e of ENGINES){
      const side = duel && duel[e.key];
      if(side && side.items && side.items.length) return side.items[0];
    }
    return null;
  }

  /* ============================================================
     PROFILE
     ============================================================ */
  function renderProfile(){
    const next = nextField();
    $("profGrid").innerHTML = FIELDS.map(function(f){
      const v = profile[f.k];
      const isNext = next && next.k === f.k;
      return '<div class="prof-card' + (v ? " filled" : "") + (isNext ? " next" : "") + '">'
        + '<span class="prof-k">' + esc(f.label) + '</span>'
        + '<span class="prof-v">' + esc(v || (isNext ? "asking next…" : "not yet")) + '</span></div>';
    }).join("");
    $("profProgress").innerHTML = FIELDS.map(function(f){
      return '<i class="' + (profile[f.k] ? "on" : "") + '"></i>';
    }).join("");
    const done = FIELDS.filter(function(f){ return profile[f.k]; }).length;
    $("profSub").textContent = done === FIELDS.length
      ? "All six answered — both models score with every one of them."
      : done + " of " + FIELDS.length + " answered. Optio asks for the rest as you chat.";
  }

  function renderHints(){
    const f = nextField();
    let hints;
    if(f && f.k === "companion") hints = ["Alone","With friends","With family"];
    else if(f && f.k === "color") hints = ["Blue","Red","Green","Purple"];
    else if(f) hints = [];
    else hints = ["Something funny to watch","A game for two players",
                  "Live music this weekend","Somewhere to eat nearby"];
    $("chatHints").innerHTML = hints.map(function(h){
      return '<button class="hint" type="button">' + esc(h) + '</button>';
    }).join("");
  }
  $("chatHints").addEventListener("click", function(e){
    const b = e.target.closest(".hint");
    if(b) send(b.textContent);
  });

  /* ============================================================
     THE DUEL
     ============================================================ */
  /* Do the two engines actually disagree? They share a retrieval core and
     differ only in how they read the *kind* of a request, so when both
     classifiers reach the same conclusion the shortlists are identical.
     That is a real result, not a bug, and it gets said rather than dressed
     up as a choice between two things that are the same. */
  function enginesAgree(){
    if(!duel) return false;
    const a = ((duel.optio || {}).items || []).map(function(i){ return i.item_id; }).join("|");
    const b = ((duel.deep  || {}).items || []).map(function(i){ return i.item_id; }).join("|");
    return a.length > 0 && a === b;
  }

  function renderDuel(){
    if(!duel){
      $("duel").innerHTML = '<div class="empty" style="grid-column:1/-1">'
        + 'Ask for something above and both models will answer here, side by side.</div>';
      $("duelSub").textContent = "—";
      $("verdictBar").hidden = true;
      renderScoreboard();
      return;
    }

    if(enginesAgree()){
      const items = duel.optio.items;
      $("duel").innerHTML =
          '<section class="side agreed" style="grid-column:1/-1;--ec:var(--v-go)">'
        + '<header class="side-head"><span class="side-name">Both models agree'
        + '<span class="side-blurb">Gradient boosting and the neural network read this request '
        + 'the same way, so they returned the same shortlist. Nothing to choose between.</span></span>'
        + '<span class="side-kind">' + (duel.optio.detected_kind
            ? "both read: " + esc(duel.optio.detected_kind) : "no kind lock") + '</span></header>'
        + '<div class="side-list">' + items.map(function(it, i){
            const kc = KIND_COLOR[it.kind] || "var(--text-3)";
            return '<button class="row-item" data-engine="optio" data-id="' + esc(it.item_id) + '"'
              + ' aria-current="' + (selected && selected.item_id === it.item_id) + '">'
              + '<span class="row-n">' + (i+1) + '</span>'
              + '<span class="row-main"><span class="row-t">' + esc(it.title) + '</span>'
              + '<span class="row-m"><i class="kd" style="--kc:' + kc + '"></i>' + esc(it.kind)
              + (it.location ? ' · ' + esc(it.location) : '') + '</span></span>'
              + '<span class="row-pct">' + it.match + '%</span></button>';
          }).join("") + '</div></section>';
      $("duelSub").textContent = 'Both answered "' + lastRequest + '" identically — '
        + 'pick a title to see why it scored.';
      $("verdictBar").hidden = true;
      renderScoreboard();
      return;
    }
    $("duel").innerHTML = ENGINES.map(function(e){
      const side = duel[e.key] || {};
      const items = side.items || [];
      const rows = items.length
        ? items.map(function(it, i){
            const kc = KIND_COLOR[it.kind] || "var(--text-3)";
            return '<button class="row-item" data-engine="' + e.key + '" data-id="' + esc(it.item_id) + '"'
              + ' aria-current="' + (selected && selected.item_id === it.item_id && selected.engine === e.key) + '">'
              + '<span class="row-n">' + (i+1) + '</span>'
              + '<span class="row-main"><span class="row-t">' + esc(it.title) + '</span>'
              + '<span class="row-m"><i class="kd" style="--kc:' + kc + '"></i>' + esc(it.kind)
              + (it.location ? ' · ' + esc(it.location) : '') + '</span></span>'
              + '<span class="row-pct">' + it.match + '%</span></button>';
          }).join("")
        : '<div class="side-empty">' + (side.ready === false
            ? 'This engine did not load.<br><span class="mono" style="font-size:11px">See the status chip for why.</span>'
            : 'Nothing came back for that.') + '</div>';

      return '<section class="side" data-engine="' + e.key + '" style="--ec:var(--e-' + e.key + ')">'
        + '<header class="side-head"><span class="side-name">' + esc(side.label || e.label)
        + '<span class="side-blurb">' + esc(side.blurb || e.blurb) + '</span></span>'
        + '<span class="side-kind">' + (side.detected_kind ? "reads: " + esc(side.detected_kind) : "no kind lock")
        + '</span></header>'
        + '<div class="side-list">' + rows + '</div></section>';
    }).join("");

    $("duelSub").textContent = 'Both answered "' + lastRequest + '" — pick a title to see why, '
      + 'then tell me which side won.';
    $("verdictBar").hidden = false;
    renderScoreboard();
  }

  function renderScoreboard(){
    const total = scoreboard.optio + scoreboard.deep + scoreboard.neither;
    $("scoreboard").innerHTML = ENGINES.map(function(e){
      return '<span class="sb" style="--ec:var(--e-' + e.key + ')">' + esc(e.label)
        + ' <b>' + (scoreboard[e.key] || 0) + '</b></span>';
    }).join("") + (total ? '<span class="sb">of <b>' + total + '</b> picks</span>' : "");
  }

  $("duel").addEventListener("click", function(e){
    const row = e.target.closest(".row-item");
    if(!row) return;
    const side = duel[row.dataset.engine];
    const item = (side.items || []).filter(function(x){ return x.item_id === row.dataset.id; })[0];
    if(!item) return;
    selected = item;
    renderDuel();
    renderWhy();
    $("whyTitle").scrollIntoView({behavior:"smooth", block:"start"});
  });

  $("verdictBar").addEventListener("click", async function(e){
    const b = e.target.closest("[data-pick]");
    if(!b || !duel) return;
    const winner = b.dataset.pick;

    document.querySelectorAll(".side").forEach(function(el){
      el.classList.toggle("won", winner !== "neither" && el.dataset.engine === winner);
      el.classList.toggle("lost", winner !== "neither" && el.dataset.engine !== winner);
    });

    if(LIVE){
      try{
        const r = await post("/api/choose", {request:lastRequest, winner:winner});
        scoreboard = r.scoreboard || scoreboard;
        toast(winner === "neither"
          ? "Noted — neither shortlist landed. Saved to your account."
          : "Saved. " + (winner === "optio" ? "Optio" : "Deep Learning")
            + " wins this round, and its picks are now in your likes.");
      }catch(err){
        if(err.status === 401){ location.href = "/login"; return; }
        toast("Could not save that choice.");
      }
    }else{
      scoreboard[winner] = (scoreboard[winner] || 0) + 1;
      if(winner !== "neither"){
        (duel[winner].items || []).slice(0,2).forEach(function(it){ liked.add(it.title.toLowerCase()); });
      }
      toast(winner === "neither" ? "Noted." : "Saved in this browser session.");
    }
    renderScoreboard();
  });

  /* ============================================================
     WHY
     ============================================================ */
  const ANGLES = [-90, 0, 90, 180];

  function renderWhy(){
    if(!selected){
      $("graphFor").textContent = "Pick something above";
      $("graphNote").textContent = "—";
      $("graphEdges").innerHTML = ""; $("graphNodes").innerHTML = "";
      $("callBadge").textContent = "—";
      $("callSays").textContent = "Choose one of the two shortlists to see how it was scored.";
      $("reasons").innerHTML = ""; $("whyActions").innerHTML = "";
      $("whySub").textContent = "—"; $("techBody").innerHTML = "";
      return;
    }
    const p = selected;
    const by = {};
    (p.parts || []).forEach(function(x){ by[x.key] = x; });
    if(!by.similarity) return;

    const nodes = [
      {label:"Matches what<br>you asked for", pct:Math.round(by.similarity.share*100), c:"var(--signal)"},
      {label:"Other people<br>rate it well",  pct:Math.round(by.quality.share*100),    c:"var(--signal)"},
      {label:"Good for going<br>" + esc(profile.companion || "alone"), pct:Math.round(by.audience.share*100), c:"var(--signal)"},
      {label:"Things you<br>said no to",      pct:Math.round(by.rejected.share*100),   c:"var(--live)"}
    ];
    let edges = "", divs = "";
    nodes.forEach(function(n, i){
      const a = ANGLES[i] * Math.PI/180;
      const x = 50 + 32*Math.cos(a), y = 50 + 33*Math.sin(a);
      edges += '<line x1="50" y1="50" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '"'
             + ' stroke="' + n.c + '" stroke-width="' + (0.6 + n.pct/100*6).toFixed(2) + '"'
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

    $("graphFor").textContent = p.title.length > 32 ? p.title.slice(0,32) + "…" : p.title;
    $("graphNote").textContent = (p.engine === "deep" ? "Deep Learning" : "Optio") + " · " + p.kind;

    let call, says, cc;
    if(rejected.has(p.title.toLowerCase())){
      call = "You said no"; cc = "var(--live)";
      says = "Dropped. It won't come back near the top.";
    }else if(p.match >= 70){
      call = "Strong match"; cc = "var(--v-go)";
      says = "This is the kind of thing you've told Optio you like.";
    }else if(p.match >= 45){
      call = "Worth a look"; cc = "var(--signal)";
      says = "A reasonable fit — good, but not a perfect read on your taste.";
    }else{
      call = "Not sure — you decide"; cc = "var(--accent)";
      says = "Not enough to go on for this one. Your call, and tell Optio either way.";
    }
    const badge = $("callBadge");
    badge.textContent = call;
    badge.style.setProperty("--cc", cc);
    $("callSays").textContent = says;
    $("whenDecided").textContent = p.match + "% overall";

    $("reasons").innerHTML = (p.parts || []).map(function(x){
      const strong = x.share >= 0.30, none = Math.abs(x.value) < 1e-9;
      const dir = x.value < 0 ? "down" : (none ? "flat" : "up");
      const mark = x.value < 0 ? "−" : (none ? "·" : "+");
      let phrase;
      if(x.key === "similarity") phrase = none ? "Nothing in it lines up with your words"
        : (strong ? "Closely matches <em>" + esc(lastRequest) + "</em>" : "Some overlap with what you asked for");
      else if(x.key === "quality") phrase = strong ? "People rate this <em>highly</em>" : "Middling ratings from other people";
      else if(x.key === "audience") phrase = none
        ? "Not especially suited to going <em>" + esc(profile.companion || "alone") + "</em>"
        : "Suits going <em>" + esc(profile.companion || "alone") + "</em>";
      else phrase = none ? "You've never turned this down" : "You turned this down before";
      return '<li class="reason ' + dir + '"><b>' + mark + '</b><span>' + phrase + '</span></li>';
    }).join("");

    $("whyActions").innerHTML =
        '<button class="btn btn-sm" data-act="liked">Yes, more like this</button>'
      + '<button class="btn btn-sm" data-act="disliked">Not for me</button>';

    $("whySub").textContent = "Showing " + p.title;
    renderTech(p);
  }

  $("whyActions").addEventListener("click", async function(e){
    const b = e.target.closest("[data-act]");
    if(!b || !selected) return;
    const key = selected.title.toLowerCase();
    const verdict = b.dataset.act;
    if(verdict === "liked"){ liked.add(key); rejected.delete(key); }
    else { rejected.add(key); liked.delete(key); }

    if(LIVE){
      try{
        await post("/api/feedback", {title:selected.title, verdict:verdict,
                                     kind:selected.kind, engine:selected.engine, request:lastRequest});
        toast("Saved to your account. It changes what you're shown next time.");
      }catch(err){
        if(err.status === 401){ location.href = "/login"; return; }
        toast("Could not save that.");
      }
    }else{
      toast(verdict === "liked" ? "Noted — similar things will score higher."
                                : "Noted — that drops the score by 0.35 next time.");
    }
    renderWhy();
  });

  function renderTech(p){
    const by = {};
    (p.parts||[]).forEach(function(x){ by[x.key] = x; });
    const raws = {similarity:p.similarity, quality:p.quality,
                  audience: by.audience.value !== 0 ? 1 : 0,
                  rejected: by.rejected.value !== 0 ? 1 : 0};
    $("techBody").innerHTML = (p.parts||[]).map(function(x){
      const cls = x.value > 0 ? "pos" : (x.value < 0 ? "neg" : "");
      return "<tr><td>" + esc(x.key) + "</td>"
        + '<td class="r num">' + Number(raws[x.key]||0).toFixed(4) + "</td>"
        + '<td class="r num">' + W[x.key].toFixed(2) + "</td>"
        + '<td class="r num ' + cls + '">' + (x.value >= 0 ? "+" : "") + Number(x.value).toFixed(4) + "</td>"
        + '<td class="r num">' + Math.round(x.share*100) + "%</td></tr>";
    }).join("")
      + '<tr class="total"><td>score</td><td class="r"></td><td class="r"></td>'
      + '<td class="r num">' + Number(p.score).toFixed(4) + "</td>"
      + '<td class="r num">' + p.match + "%</td></tr>";
    $("techNote").textContent = (LIVE ? "computed in Python · " : "computed in the browser · ")
      + (p.engine === "deep" ? "neural network" : "gradient boosting");
    $("techFormula").textContent =
      "score = 0.78·similarity + 0.22·quality + 0.08·audience − 0.35·rejected  ·  "
      + "match% rescales the achievable 0.05–0.55 range onto 0–100. "
      + "Both engines share this formula; they differ only in which slice of the catalogue they search.";
  }

  $("detailBtn").addEventListener("click", function(){
    showTech = !showTech;
    $("tech").hidden = !showTech;
    $("detailBtn").setAttribute("aria-pressed", String(showTech));
    $("detailBtn").textContent = showTech ? "Hide details" : "Show details";
  });

  /* ============================================================
     WELCOME POPUP
     ============================================================ */
  function openWelcome(){
    $("welcomeScrim").hidden = false;
    $("welcome").hidden = false;
    $("welcomeGo").focus();
  }
  function closeWelcome(){
    $("welcomeScrim").hidden = true;
    $("welcome").hidden = true;
    try{ sessionStorage.removeItem("optio-welcome"); }catch(e){}
    try{ localStorage.setItem("optio-seen-tour", "1"); }catch(e){}
  }
  $("welcomeClose").addEventListener("click", closeWelcome);
  $("welcomeGo").addEventListener("click", closeWelcome);
  $("welcomeScrim").addEventListener("click", closeWelcome);
  $("aboutBtn").addEventListener("click", openWelcome);
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !$("welcome").hidden) closeWelcome();
  });

  /* ============================================================
     SUPPORT CHAT — Chatbase
     Set CHATBASE_ID to the agent id from your Chatbase dashboard and
     the real widget loads. Until then the button opens a panel that
     says exactly that, rather than pretending to be a support agent.
     ============================================================ */
  const CHATBASE_ID = "";     // <-- paste your Chatbase agent id here

  function mountChatbase(id){
    window.embeddedChatbotConfig = {chatbotId:id, domain:"www.chatbase.co"};
    const s = document.createElement("script");
    s.src = "https://www.chatbase.co/embed.min.js";
    s.setAttribute("chatbotId", id);
    s.setAttribute("domain", "www.chatbase.co");
    s.defer = true;
    s.onload = function(){ $("supportFab").classList.add("hidden"); };
    s.onerror = function(){ toast("The support chat could not load — check the connection."); };
    document.body.appendChild(s);
  }

  function setupSupport(){
    if(CHATBASE_ID){ mountChatbase(CHATBASE_ID); return; }
    $("supportBody").innerHTML =
        "<p><b>Hi — how can we help?</b></p>"
      + "<p>The live support agent is not connected yet. To switch it on:</p>"
      + "<ol><li>Create an agent at <code>chatbase.co</code></li>"
      + "<li>Copy its agent id</li>"
      + "<li>Paste it into <code>CHATBASE_ID</code> near the bottom of "
      + "<code>assets/app.js</code></li></ol>"
      + "<p>The real widget replaces this panel automatically once the id is set.</p>";
  }

  $("supportFab").addEventListener("click", function(){
    const panel = $("supportPanel");
    panel.hidden = !panel.hidden;
    $("supportBadge").hidden = true;
  });
  $("supportClose").addEventListener("click", function(){ $("supportPanel").hidden = true; });

  /* ============================================================
     BOOT
     ============================================================ */
  $("chatForm").addEventListener("submit", function(e){
    e.preventDefault();
    send($("chatInput").value);
  });

  $("authBtn").addEventListener("click", async function(){
    if(!LIVE){ toast("Accounts need the server. Run:  cd Optio  then  python app.py"); return; }
    if(me){
      await post("/api/logout", {}).catch(function(){});
      location.href = "/login";
    }else{
      location.href = "/login";
    }
  });

  $("statusChip").addEventListener("click", function(){
    if(LIVE){
      const parts = (status.engines || []).map(function(e){
        return e.label + ": " + (e.classifier_loaded ? "classifier loaded"
               : e.ready ? "running without its classifier" : "failed to load");
      });
      toast(status.catalog_rows.toLocaleString() + " items · " + parts.join(" · "));
    }else{
      toast("Static preview: " + data.sample_total + " real items from the "
        + data.catalog_total.toLocaleString() + "-item catalogue. Run app.py for both real models.");
    }
  });

  function setStatus(){
    const chip = $("statusChip");
    if(LIVE){
      const loaded = (status.engines || []).filter(function(e){ return e.ready; }).length;
      chip.classList.add("live");
      $("statusText").textContent = "live · " + loaded + "/2 engines · "
        + (status.catalog_rows || 0).toLocaleString() + " items";
      $("footRight").textContent = "app.py · " + (status.llm || "") + " · SQLite";
      $("footLeft").textContent = "Optio — every number came from the Python models.";
      scoreboard = status.scoreboard || scoreboard;
    }else{
      chip.classList.add("demo");
      $("statusText").textContent = "static · " + data.sample_total + " items";
      $("footRight").textContent = "static build · no Python running";
      $("footLeft").textContent = "Optio — static preview built from the real catalogue.";
      $("authBtn").textContent = "Accounts need the server";
      const banner = document.createElement("div");
      banner.className = "banner";
      banner.innerHTML = "<div><b>You are seeing the static preview.</b>"
        + "These " + data.sample_total + " items are real rows from the "
        + data.catalog_total.toLocaleString() + "-item catalogue, scored with the same formula. "
        + "Accounts, the trained classifiers and the saved history all need the server. "
        + "To run everything: <code>cd Optio</code> then <code>python app.py</code>.</div>";
      document.querySelector(".shell").appendChild(banner);
    }
  }

  (async function boot(){
    try{
      status = await api("/api/status");
      LIVE = !!status.ready;
    }catch(e){ LIVE = false; }

    if(LIVE){
      try{
        const info = await api("/api/me");
        if(info.signed_in){
          me = info.user;
          profile = Object.assign(profile, info.profile || {});
          (info.prefs.liked || []).forEach(function(p){ liked.add(p.title.toLowerCase()); });
          (info.prefs.disliked || []).forEach(function(p){ rejected.add(p.title.toLowerCase()); });
          scoreboard = (info.summary && info.summary.scoreboard) || scoreboard;
          $("who").hidden = false;
          $("who").textContent = me.display_name;
          $("authBtn").textContent = "Sign out";
        }else{
          location.href = "/login";
          return;
        }
      }catch(e){ location.href = "/login"; return; }
    }else{
      try{
        data = await (await fetch("assets/catalog-sample.json")).json();
      }catch(e){
        document.querySelector(".shell").innerHTML =
          '<div class="empty" style="margin-top:40px">Could not load the catalogue sample.</div>';
        return;
      }
    }

    setStatus();
    setupSupport();
    renderProfile(); renderDuel(); renderWhy(); renderHints();

    let showTour = false;
    try{
      showTour = sessionStorage.getItem("optio-welcome") === "1"
              || !localStorage.getItem("optio-seen-tour");
    }catch(e){ showTour = true; }
    if(showTour) setTimeout(openWelcome, 420);

    if(LIVE){
      try{
        const g = await api("/api/greeting");
        addMsg("bot", g.text || "Hi, I'm Optio. What should I call you?");
      }catch(e){ addMsg("bot", "Hi, I'm Optio. What should I call you?"); }
    }else{
      addMsg("bot", "Hi, I'm Optio. I help you decide what to watch, play, or go to — "
        + "two models answer and you pick the better one. What should I call you?");
    }
  })();
})();
