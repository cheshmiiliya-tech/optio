/* ============================================================
   MARQUEE — entertainment guide + explainable recommender
   No build step, no dependencies. Everything runs on-device.
   ============================================================ */
(function(){
  "use strict";

  /* ============================================================
     0. THEME — "house lights". The OS preference is the default;
        an explicit choice is remembered.
     ============================================================ */
  (function(){
    const KEY = "marquee-theme";
    const root = document.documentElement;
    const btn = document.getElementById("themeBtn");
    const stored = localStorage.getItem(KEY);

    function label(){
      const dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      btn.textContent = dark ? "House lights up" : "House lights down";
      btn.setAttribute("aria-pressed", String(dark));
    }
    if(stored === "dark" || stored === "light") root.dataset.theme = stored;
    label();

    btn.addEventListener("click", function(){
      const dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      localStorage.setItem(KEY, root.dataset.theme);
      label();
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function(){
      if(!root.dataset.theme) label();
    });
  })();

  /* ============================================================
     1. SCHEDULE
     The guide window is generated relative to the real clock, so
     "now" always lands inside it whenever the page is opened.
     ============================================================ */
  const PPM = 4, HOURS = 9, MIN = HOURS * 60, TRACK_W = MIN * PPM;

  const START = new Date();
  START.setMinutes(0, 0, 0);
  START.setHours(START.getHours() - 1);
  const END = new Date(START.getTime() + MIN * 60000);

  const GENRES = {
    film:{label:"Film",v:"--g-film"}, live:{label:"Live",v:"--g-live"},
    comedy:{label:"Comedy",v:"--g-comedy"}, stage:{label:"Stage",v:"--g-stage"},
    sport:{label:"Sport",v:"--g-sport"}, series:{label:"Series",v:"--g-series"},
    doc:{label:"Doc",v:"--g-doc"}
  };

  const CHANNELS = [
    {no:"01", name:"Marquee One", kind:"New cinema", pool:[
      {t:"The Salt Road", d:115, g:"film", r:"15", s:"A cartographer retraces her father's smuggling routes across the Atacama, and finds the maps were never about the desert."},
      {t:"Pale Horses", d:98, g:"film", r:"12", s:"Two rival stunt riders share one last season on the county circuit. Neither of them can afford to stop."},
      {t:"Nine Kinds of Rain", d:104, g:"film", r:"15", s:"A regional weather presenter begins forecasting things she has no way of knowing."},
      {t:"Harbourlight", d:108, g:"film", r:"12", s:"A lighthouse keeper's daughter returns to sell the tower and inherits the argument that built it."},
      {t:"The Understudy", d:92, g:"film", r:"15", s:"Opening night is in four hours and the lead has vanished. A backstage thriller in one continuous take."}
    ]},
    {no:"02", name:"Amp", kind:"Live music", pool:[
      {t:"Sonora: Live from the Fillmore", d:75, g:"live", r:"PG", s:"The full headline set, mixed from the desk, plus three songs the band have never played live before."},
      {t:"Basement Tapes — Kestrel", d:45, g:"live", r:"PG", s:"Four musicians, one room, no overdubs. Recorded below a laundrette in Leeds."},
      {t:"Night Bloom Festival: Main Stage", d:120, g:"live", r:"12", s:"Six hours of the festival compressed into two, with the sunset set intact and uncut."},
      {t:"Four on the Floor", d:60, g:"live", r:"PG", s:"A drummer's showcase — four kits, four decades, one very patient sound engineer."},
      {t:"The Acoustic Room: Ada Vance", d:45, g:"live", r:"PG", s:"Ada Vance plays the record that nearly didn't happen, alone, on a borrowed guitar."}
    ]},
    {no:"03", name:"The Pit", kind:"Comedy", pool:[
      {t:"Open Mic Roulette", d:45, g:"comedy", r:"15", s:"Twelve comics. Five minutes each. The audience holds the buzzer and they are not merciful."},
      {t:"Marcus Reyes: Loud Enough", d:60, g:"comedy", r:"18", s:"A special about volume, inheritance, and a father who never once raised his voice."},
      {t:"Deadpan — Series 3", d:30, g:"series", r:"15", s:"The sketch show that refuses to explain the joke. Episode 4: the wedding."},
      {t:"The Heckler's Ball", d:90, g:"comedy", r:"18", s:"An annual roast where the hecklers get the microphone and the comedians sit in the dark."},
      {t:"Panel Beaters", d:45, g:"comedy", r:"12", s:"Two teams, one impossible quiz, and a scoring system nobody has ever successfully explained."}
    ]},
    {no:"04", name:"Stage Door", kind:"Theatre & arts", pool:[
      {t:"Antigone, Rewired", d:135, g:"stage", r:"12", s:"The Alhambra's sold-out staging, filmed live. A modern-dress production set entirely in a records office."},
      {t:"Curtain Call", d:45, g:"doc", r:"PG", s:"Backstage on closing night: the crew who strike a set in ninety minutes and never take a bow."},
      {t:"The Chairs — Live from Studio 9", d:105, g:"stage", r:"12", s:"Ionesco's absurdist two-hander, performed to an audience of empty seats and one camera."},
      {t:"Movement No. 4", d:60, g:"stage", r:"PG", s:"A contemporary dance company builds a piece in public over four weeks. This is week four."}
    ]},
    {no:"05", name:"Reel Classic", kind:"Repertory", pool:[
      {t:"The Long Afternoon (1961)", d:110, g:"film", r:"PG", s:"A restored print of the film that emptied cinemas on release and filled them again a decade later."},
      {t:"Riverboat Blues (1957)", d:96, g:"film", r:"PG", s:"Gambling, a stolen cornet, and the last commercial paddle steamer on the Ohio."},
      {t:"Cinema Notes: The Widescreen Years", d:45, g:"doc", r:"PG", s:"How a panic about television reshaped the aspect ratio of everything you have ever watched."},
      {t:"Silverpoint (1948)", d:88, g:"film", r:"PG", s:"A forger, a curator, and a portrait that is either priceless or worthless depending on the light."}
    ]},
    {no:"06", name:"Nocturne", kind:"Talk & late night", pool:[
      {t:"Nocturne with Priya Raman", d:60, g:"series", r:"12", s:"Tonight: a cellist, a bank robber turned locksmith, and the studio band playing a request from 1974."},
      {t:"The Green Room", d:45, g:"series", r:"12", s:"Interviews conducted in the twenty minutes before a performer walks on stage. Nerves included."},
      {t:"Last Orders", d:30, g:"series", r:"15", s:"A closing-time conversation, filmed in a different bar each week, until the lights come up."},
      {t:"After Hours Sessions", d:60, g:"live", r:"12", s:"Three acts, one piano, and a studio audience of about forty people who all know each other."}
    ]},
    {no:"07", name:"Arena", kind:"Sport & esports", pool:[
      {t:"Continental Cup — Semi-Final", d:120, g:"sport", r:"PG", s:"Second leg, one goal in it, and a stadium that has not sat down since the warm-up."},
      {t:"Velodrome: Night Racing", d:75, g:"sport", r:"PG", s:"Keirin and madison finals under the lights, where the tactics matter more than the legs."},
      {t:"Circuit Open — Grand Final", d:90, g:"sport", r:"PG", s:"The esports final that ran to five maps last year. Both rosters are unchanged."},
      {t:"The Round-Up", d:30, g:"sport", r:"PG", s:"Everything that happened tonight, in order, with the arguments left in."}
    ]},
    {no:"08", name:"Loophole", kind:"Animation & drama", pool:[
      {t:"Tin Kettle Kids", d:30, g:"series", r:"PG", s:"Hand-drawn, wordless, and quietly devastating. A short series about a scrapyard and the children who run it."},
      {t:"Orbital Drift", d:45, g:"series", r:"12", s:"A maintenance crew on a decommissioned station discovers the decommissioning was a lie."},
      {t:"The Fold — Season 2", d:50, g:"series", r:"15", s:"The paper factory reopens. So does the case nobody wanted reopened."},
      {t:"Paper Cranes", d:25, g:"series", r:"PG", s:"A stop-motion fable told entirely in folded paper, at one frame per fold."},
      {t:"Midnight Cartoons", d:60, g:"series", r:"15", s:"A curated block of animated shorts for people who should have gone to bed."}
    ]}
  ];

  const POSTERS = [
    {p1:"#B2354F",p2:"#5B2C7A",p3:"#1A0E22"}, {p1:"#1E6E7A",p2:"#8A3F6B",p3:"#0F1424"},
    {p1:"#C46A1E",p2:"#7A2340",p3:"#1C1016"}, {p1:"#3F4FA8",p2:"#A2417C",p3:"#100D22"},
    {p1:"#7A8C2A",p2:"#2C5F6B",p3:"#101A18"}, {p1:"#A83C2C",p2:"#4A2A78",p3:"#1A0D14"}
  ];

  const listings = [];
  const byIdMap = Object.create(null);
  let uid = 0;
  CHANNELS.forEach(function(ch, ci){
    const stagger = [0,22,41,13,34,8,47,26][ci % 8];
    let cursor = START.getTime() - stagger * 60000, i = 0;
    while(cursor < END.getTime()){
      const p = ch.pool[i % ch.pool.length];
      const s = cursor, e = cursor + p.d * 60000;
      if(e > START.getTime()){
        const item = {
          id:"p" + (uid++), ch:ch, chIndex:ci, title:p.t, genre:p.g,
          rating:p.r, synopsis:p.s, dur:p.d, start:s, end:e,
          poster:POSTERS[(ci * 3 + i) % POSTERS.length]
        };
        listings.push(item);
        byIdMap[item.id] = item;
      }
      cursor = e; i++;
    }
  });

  /* ============================================================
     2. THE MODEL
     A small, honest recommender: a weighted taste vector over
     genre / channel / runtime / time-of-day. Every score the UI
     shows is this function, and every "why" is its decomposition.
     ============================================================ */
  const W = { genre:.42, channel:.22, runtime:.14, slot:.22 };

  const SEED = {
    genre:{film:.81, live:.54, comedy:.66, stage:.33, sport:.16, series:.60, doc:.42},
    channel:[.84,.57,.62,.34,.68,.51,.14,.47],
    runtime:98,
    slot:.58,           // 0 = early evening, 1 = the small hours
    signals:1284
  };
  let model = clone(SEED);
  let lastUpdate = Date.now();

  function clone(m){
    return {
      genre:Object.assign({}, m.genre),
      channel:m.channel.slice(),
      runtime:m.runtime,
      slot:m.slot,
      signals:m.signals
    };
  }
  const clamp01 = function(x){ return Math.max(0.02, Math.min(1, x)); };

  /* where a start time falls in the 17:00 -> 02:00 window, 0..1 */
  function slotOf(ms){
    const d = new Date(ms);
    let h = d.getHours() + d.getMinutes() / 60;
    if(h < 6) h += 24;
    return Math.max(0, Math.min(1, (h - 17) / 9));
  }

  function score(p){
    const g = model.genre[p.genre];
    const c = model.channel[p.chIndex];
    const r = 1 - Math.min(1, Math.abs(p.dur - model.runtime) / 95);
    const t = 1 - Math.abs(slotOf(p.start) - model.slot);

    const parts = [
      {k:"genre",   raw:g, w:W.genre},
      {k:"channel", raw:c, w:W.channel},
      {k:"runtime", raw:r, w:W.runtime},
      {k:"slot",    raw:t, w:W.slot}
    ];
    let total = 0;
    parts.forEach(function(pt){ pt.val = pt.raw * pt.w; total += pt.val; });

    /* map 0..1 onto a believable 31..98 band */
    const match = Math.round(31 + total * 67);

    /* certainty rises with signal volume and with how decided the
       genre weight is; shown to the user as an honest +/- margin */
    const decided = Math.abs(g - .5) * 2;
    const vol = Math.min(1, (model.signals - 900) / 1400);
    const pm = Math.max(2, Math.round(13 - decided * 5 - vol * 5));

    parts.forEach(function(pt){ pt.share = total > 0 ? pt.val / total : 0; });
    parts.sort(function(a,b){ return b.share - a.share; });

    return {match:match, pm:pm, parts:parts, total:total};
  }

  const WHY_TEXT = {
    genre:  function(p){ return "Matches your " + GENRES[p.genre].label.toLowerCase() + " history"; },
    channel:function(p){ return "You watch " + p.ch.name + " often"; },
    runtime:function(p){ return "Close to your usual " + runtime(model.runtime) + " sitting"; },
    slot:   function(p){ return "Lands in your " + (model.slot > .6 ? "late-night" : "early-evening") + " window"; }
  };

  function predictedRating(p, sc){ return (2.6 + sc.total * 2.3).toFixed(1); }

  /* feedback writes straight back into the vector */
  function learn(id, dir){
    const p = byIdMap[id];
    const step = dir * 0.075;
    model.genre[p.genre]     = clamp01(model.genre[p.genre] + step);
    model.channel[p.chIndex] = clamp01(model.channel[p.chIndex] + step * .8);
    model.runtime  = Math.round(model.runtime + (p.dur - model.runtime) * (dir > 0 ? .16 : -.09));
    model.runtime  = Math.max(28, Math.min(140, model.runtime));
    model.slot     = clamp01(model.slot + (slotOf(p.start) - model.slot) * (dir > 0 ? .18 : -.10));
    model.signals += dir > 0 ? 3 : 2;
    lastUpdate = Date.now();

    toast((dir > 0 ? "Learned: more like " : "Learned: less like ") + p.title
      + " — " + GENRES[p.genre].label + " weight now " + Math.round(model.genre[p.genre] * 100) + "%");
    recompute();
  }

  /* ============================================================
     3. PREDICTED PATH — a greedy walk through tonight
     ============================================================ */
  function buildPath(){
    const t0 = Math.max(Date.now(), START.getTime());
    const path = [];
    let cursor = t0, lastCh = null, guard = 0;

    while(cursor < END.getTime() && guard++ < 40){
      const options = listings.filter(function(p){ return p.start <= cursor && cursor < p.end; });
      if(!options.length){ cursor += 15 * 60000; continue; }

      const scored = options.map(function(p){
        const sc = score(p);
        return {p:p, sc:sc, s:sc.total + (p.chIndex === lastCh ? .045 : 0)};
      }).sort(function(a,b){ return b.s - a.s; });

      /* softmax over the concurrent options gives a real probability */
      const K = 9;
      let sum = 0;
      scored.forEach(function(o){ o.e = Math.exp(o.s * K); sum += o.e; });
      const top = scored[0];
      const prob = Math.round(top.e / sum * 100);

      const hoursAhead = (cursor - t0) / 3600000;
      const conf = Math.round(94 * Math.exp(-hoursAhead / 4.2));

      path.push({
        p:top.p, sc:top.sc, from:cursor, to:Math.min(top.p.end, END.getTime()),
        prob:prob, conf:conf, alt:scored[1] ? scored[1].p : null
      });
      lastCh = top.p.chIndex;
      cursor = top.p.end;
    }
    return path;
  }

  /* ============================================================
     4. HELPERS + STATE
     ============================================================ */
  const $ = function(id){ return document.getElementById(id); };
  const pad = function(n){ return n < 10 ? "0" + n : "" + n; };
  const hhmm = function(ms){ const d = new Date(ms); return pad(d.getHours()) + ":" + pad(d.getMinutes()); };
  function runtime(m){ return m >= 60 ? Math.floor(m/60) + "h " + pad(m%60) + "m" : m + "m"; }
  const gcolor = function(g){ return "var(" + GENRES[g].v + ")"; };
  const isNow = function(p, t){ return p.start <= t && t < p.end; };
  const esc = function(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); };

  const saved = new Set();
  let filter = "all", openId = null, heroId = null;
  let toastTimer = null;

  function toast(msg){
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, 3200);
  }

  /* ---------- marquee bulbs ---------- */
  (function(){
    let html = "";
    for(let i = 0; i < 28; i++) html += '<i class="bulb" style="animation-delay:' + (i*0.09).toFixed(2) + 's"></i>';
    $("bulbs").innerHTML = html;
  })();

  /* ---------- filter chips ---------- */
  (function(){
    const host = $("chips");
    let html = '<button class="chip" data-g="all" aria-pressed="true">All listings</button>'
             + '<button class="chip chip-ai" data-g="__ai" aria-pressed="false"><span class="swatch"></span>Model picks · 70%+</button>';
    Object.keys(GENRES).forEach(function(k){
      html += '<button class="chip" data-g="' + k + '" aria-pressed="false">'
            + '<span class="swatch" style="--sw:' + gcolor(k) + '"></span>' + GENRES[k].label + '</button>';
    });
    host.innerHTML = html;
    host.addEventListener("click", function(e){
      const btn = e.target.closest(".chip");
      if(!btn) return;
      filter = btn.dataset.g;
      host.querySelectorAll(".chip").forEach(function(c){
        c.setAttribute("aria-pressed", String(c.dataset.g === filter));
      });
      applyFilter();
    });
  })();

  /* ============================================================
     5. EPG
     ============================================================ */
  function buildGuide(){
    const inner = $("epgInner");
    let html = "";

    html += '<div class="ruler"><div class="corner">Channel</div><div class="ticks" style="width:' + TRACK_W + 'px">';
    for(let m = 0; m <= MIN; m += 30){
      const t = START.getTime() + m * 60000;
      html += '<div class="tick ' + (m % 60 === 0 ? "hour" : "half") + '" style="left:' + (m*PPM) + 'px"><span>' + hhmm(t) + '</span></div>';
    }
    html += '<div class="now-flag" id="nowFlag"><span id="nowFlagT">--:--</span></div></div></div>';

    /* the model's own lane, sitting above the published schedule */
    html += '<div class="path-row">'
      + '<div class="path-head"><b>Your path</b><span>Predicted · live</span></div>'
      + '<div class="path-track" id="pathTrack" style="width:' + TRACK_W + 'px"></div>'
      + '</div>';

    CHANNELS.forEach(function(ch, ci){
      html += '<div class="row"><div class="chan"><span class="chan-no">' + ch.no + '</span>'
        + '<span><span class="chan-name">' + esc(ch.name) + '</span>'
        + '<span class="chan-kind">' + esc(ch.kind) + '</span></span></div>'
        + '<div class="track" style="width:' + TRACK_W + 'px">';

      listings.filter(function(p){ return p.chIndex === ci; }).forEach(function(p){
        const l = Math.max(0, (p.start - START.getTime()) / 60000 * PPM);
        const r = Math.min(TRACK_W, (p.end - START.getTime()) / 60000 * PPM);
        const w = Math.max(38, r - l);
        html += '<button class="prog" data-id="' + p.id + '" style="left:' + l + 'px;width:' + (w-4) + 'px;--gc:' + gcolor(p.genre) + '">'
          + '<span class="prog-t">' + esc(p.title) + '</span>'
          + '<span class="prog-m">' + hhmm(p.start) + '–' + hhmm(p.end)
          + '<b class="prog-score" data-score="' + p.id + '"></b></span></button>';
      });
      html += '</div></div>';
    });

    html += '<div class="playhead" id="playhead"></div>';
    inner.innerHTML = html;

    inner.addEventListener("click", function(e){
      const seg = e.target.closest(".path-seg");
      if(seg){ openDrawer(seg.dataset.id); return; }
      const btn = e.target.closest(".prog");
      if(btn) openDrawer(btn.dataset.id);
    });
  }

  function renderPath(){
    const track = $("pathTrack");
    if(!track) return;
    track.innerHTML = buildPath().map(function(seg){
      const l = Math.max(0, (seg.from - START.getTime()) / 60000 * PPM);
      const r = Math.min(TRACK_W, (seg.to - START.getTime()) / 60000 * PPM);
      const w = Math.max(52, r - l);
      return '<button class="path-seg" data-id="' + seg.p.id + '" style="left:' + l + 'px;width:' + (w-4) + 'px;opacity:' + (0.42 + seg.conf/100*0.58).toFixed(2) + '">'
        + '<span class="path-seg-t">' + esc(seg.p.title) + '</span>'
        + '<span class="path-seg-p">' + seg.prob + '% <em>likely · ±' + Math.max(3, 100-seg.conf) + '</em></span>'
        + '<span class="conf-band" style="opacity:' + (seg.conf/100).toFixed(2) + '"></span>'
        + '</button>';
    }).join("");
  }

  function applyFilter(){
    let shown = 0;
    const t = Date.now();
    document.querySelectorAll(".prog").forEach(function(el){
      const p = byIdMap[el.dataset.id];
      const sc = score(p);
      const match = filter === "all" ? true
                  : filter === "__ai" ? sc.match >= 70
                  : p.genre === filter;
      el.classList.toggle("dim", !match);
      el.classList.toggle("past", p.end <= t);
      el.classList.toggle("now", isNow(p, t));
      el.classList.toggle("pick", sc.match >= 78);
      el.classList.toggle("saved", saved.has(p.id));
      const sEl = el.querySelector(".prog-score");
      if(sEl) sEl.textContent = sc.match + "%";
      if(match) shown++;
    });
    $("guideCount").textContent = shown + " of " + listings.length + " listings · "
      + hhmm(START.getTime()) + "–" + hhmm(END.getTime()) + " · " + CHANNELS.length + " channels";
  }

  /* ============================================================
     6. RECOMMENDATION LIST
     ============================================================ */
  function renderRecos(){
    const t = Date.now();
    const seen = Object.create(null);
    const ranked = listings
      .filter(function(p){ return p.end > t + 60000; })
      .map(function(p){ return {p:p, sc:score(p)}; })
      .sort(function(a,b){ return b.sc.match - a.sc.match || a.p.start - b.p.start; })
      .filter(function(o){
        if(seen[o.p.title]) return false;
        seen[o.p.title] = 1; return true;
      })
      .slice(0, 5);

    $("recoList").innerHTML = ranked.map(function(o, i){
      const p = o.p, sc = o.sc;
      const whys = sc.parts.slice(0, 3).map(function(pt){
        return '<span class="why-chip"><b>' + Math.round(pt.share*100) + '%</b>' + esc(WHY_TEXT[pt.k](p)) + '</span>';
      }).join("");
      return '<article class="reco" data-id="' + p.id + '">'
        + '<div class="reco-rank">' + pad(i+1) + '</div>'
        + '<div class="reco-main">'
          + '<div class="reco-t"><button data-open="' + p.id + '"><h3>' + esc(p.title) + '</h3></button></div>'
          + '<div class="reco-meta">'
            + '<i class="gdot" style="--gc:' + gcolor(p.genre) + '"></i>' + GENRES[p.genre].label
            + ' · ' + esc(p.ch.name) + ' · ' + hhmm(p.start) + ' · ' + runtime(p.dur)
            + ' · predicts ' + predictedRating(p, sc) + '/5'
          + '</div>'
          + '<div class="whys">' + whys + '</div>'
        + '</div>'
        + '<div class="reco-right">'
          + '<div class="match"><span class="match-n">' + sc.match + '<small>%</small></span>'
          + '<span class="meter" aria-label="' + sc.match + ' percent match"><i style="--w:' + sc.match + '%"></i></span>'
          + '<span class="match-pm">±' + sc.pm + '</span></div>'
          + '<div class="feedback">'
            + '<button class="fb" data-fb="up" data-id="' + p.id + '" aria-label="More like ' + esc(p.title) + '">▲ More</button>'
            + '<button class="fb down" data-fb="down" data-id="' + p.id + '" aria-label="Less like ' + esc(p.title) + '">▼ Less</button>'
          + '</div>'
        + '</div></article>';
    }).join("");

    const avg = ranked.length ? Math.round(ranked.reduce(function(a,o){ return a + o.sc.match; }, 0) / ranked.length) : 0;
    $("recoSub").textContent = "Top 5 of " + listings.filter(function(p){ return p.end > t; }).length
      + " upcoming · mean match " + avg + "% · recomputed " + hhmm(lastUpdate);
  }

  $("recoList").addEventListener("click", function(e){
    const fb = e.target.closest("[data-fb]");
    if(fb){ learn(fb.dataset.id, fb.dataset.fb === "up" ? 1 : -1); return; }
    const op = e.target.closest("[data-open]");
    if(op) openDrawer(op.dataset.open);
  });

  /* ============================================================
     7. MODEL PANEL
     ============================================================ */
  function renderModelPanel(){
    const rows = Object.keys(GENRES)
      .map(function(k){ return {k:k, v:model.genre[k]}; })
      .sort(function(a,b){ return b.v - a.v; });

    $("affBars").innerHTML = rows.map(function(r){
      return '<div class="aff-row">'
        + '<span class="aff-name">' + GENRES[r.k].label + '</span>'
        + '<span class="aff-track"><i class="aff-fill" style="width:' + (r.v*100).toFixed(0) + '%;--gc:' + gcolor(r.k) + '"></i></span>'
        + '<span class="aff-val">' + (r.v*100).toFixed(0) + '</span></div>';
    }).join("");

    /* viewing-window histogram, peaked on the learned slot */
    let sparkHtml = "";
    const peakI = Math.round(model.slot * 17);
    for(let i = 0; i < 18; i++){
      const dist = Math.abs(i - peakI) / 6;
      const h = Math.max(9, Math.round(100 * Math.exp(-dist*dist*1.5)));
      sparkHtml += '<i class="' + (i === peakI ? "peak" : "") + '" style="height:' + h + '%"></i>';
    }
    $("spark").innerHTML = sparkHtml;

    const topCh = model.channel.indexOf(Math.max.apply(null, model.channel));
    const conf = Math.min(97, Math.round(58 + (model.signals - 1200) / 22));

    $("mpConf").textContent = "confidence " + conf + "%";
    $("mpSignals").textContent = model.signals.toLocaleString("en-US");
    $("mpRuntime").textContent = runtime(model.runtime);
    $("mpChannel").textContent = CHANNELS[topCh].name;
    $("mpUpdated").textContent = hhmm(lastUpdate);
    $("mcSig").textContent = model.signals.toLocaleString("en-US");
  }

  /* ============================================================
     8. HERO
     ============================================================ */
  function currentOn(ci, t){
    const list = listings.filter(function(p){ return p.chIndex === ci; });
    for(let i = 0; i < list.length; i++){ if(isNow(list[i], t)) return list[i]; }
    return list[0];
  }

  function renderHero(t){
    const p = currentOn(0, t);
    if(!p) return;
    if(p.id !== heroId){
      heroId = p.id;
      $("heroTitle").textContent = p.title;
      $("heroDesc").textContent = p.synopsis;
      $("heroChan").textContent = p.ch.no + " · " + p.ch.name.toUpperCase();
      $("heroFacts").innerHTML =
          '<span style="color:' + gcolor(p.genre) + ';font-weight:700;letter-spacing:.1em;text-transform:uppercase;font-size:11px">' + GENRES[p.genre].label + '</span>'
        + '<span class="sep">/</span><span class="mono">' + runtime(p.dur) + '</span>'
        + '<span class="sep">/</span><span class="mono">Rated ' + p.rating + '</span>'
        + '<span class="sep">/</span><span>' + esc(p.ch.kind) + '</span>';
      const poster = $("heroPoster");
      poster.style.setProperty("--p1", p.poster.p1);
      poster.style.setProperty("--p2", p.poster.p2);
      poster.style.setProperty("--p3", p.poster.p3);
      $("heroPosterKicker").textContent = p.ch.name;
      $("heroPosterTitle").textContent = p.title;
      $("heroPosterA").textContent = runtime(p.dur);
      $("heroPosterB").textContent = hhmm(p.start);
      $("heroStart").textContent = hhmm(p.start);
      $("heroEnd").textContent = hhmm(p.end);
    }
    const sc = score(p);
    $("heroMatchN").innerHTML = sc.match + "<small>%</small>";
    $("heroMeter").style.setProperty("--w", sc.match + "%");
    $("heroMatchPm").textContent = "±" + sc.pm;
    $("heroWhy").textContent = WHY_TEXT[sc.parts[0].k](p) + " ("
      + Math.round(sc.parts[0].share*100) + "% of the score) · predicts "
      + predictedRating(p, sc) + "/5";

    const pct = Math.max(0, Math.min(100, (t - p.start) / (p.end - p.start) * 100));
    $("heroFill").style.width = pct.toFixed(1) + "%";
    $("heroBarWrap").setAttribute("aria-valuenow", Math.round(pct));
    const left = Math.max(0, Math.round((p.end - t) / 60000));
    $("heroLeft").textContent = left > 0 ? left + " min left" : "ending";
    syncSaveButtons();
  }

  /* ============================================================
     9. DRAWER + EXPLAINABILITY
     ============================================================ */
  function openDrawer(id){
    const p = byIdMap[id];
    if(!p) return;
    openId = id;
    renderDrawer();
    $("drawer").classList.add("open");
    $("drawer").setAttribute("aria-hidden", "false");
    $("scrim").classList.add("open");
    $("dClose").focus();
  }

  function renderDrawer(){
    const p = byIdMap[openId];
    if(!p) return;
    const sc = score(p);

    $("dTitle").textContent = p.title;
    $("dDesc").textContent = p.synopsis;
    $("dChannel").textContent = p.ch.no + " · " + p.ch.name;
    const tag = $("dTag");
    tag.textContent = GENRES[p.genre].label;
    tag.style.setProperty("--gc", gcolor(p.genre));
    $("dStart").textContent = hhmm(p.start);
    $("dEnd").textContent = hhmm(p.end);
    $("dRun").textContent = runtime(p.dur);
    $("dChan").textContent = p.ch.name;
    $("dRate").textContent = p.rating;
    $("dPred").textContent = predictedRating(p, sc) + " / 5";

    $("dMatchN").innerHTML = sc.match + "<small>%</small>";
    $("dMeter").style.setProperty("--w", sc.match + "%");
    $("dMatchPm").textContent = "±" + sc.pm;

    $("dContribs").innerHTML = sc.parts.map(function(pt){
      return '<div class="contrib"><div><div class="contrib-l">' + esc(WHY_TEXT[pt.k](p)) + '</div>'
        + '<div class="contrib-bar"><i style="width:' + (pt.share*100).toFixed(0) + '%"></i></div></div>'
        + '<div class="contrib-v">' + Math.round(pt.share*100) + '%</div></div>';
    }).join("");

    $("dNote").textContent = "Confidence band ±" + sc.pm + " points, from "
      + model.signals.toLocaleString("en-US") + " logged signals. The model is wrong sometimes — "
      + "tell it so and this score changes immediately.";

    syncSaveButtons();
  }

  function closeDrawer(){
    openId = null;
    $("drawer").classList.remove("open");
    $("drawer").setAttribute("aria-hidden", "true");
    $("scrim").classList.remove("open");
  }

  /* ============================================================
     10. WATCHLIST + PICKS RAIL
     ============================================================ */
  function toggleSave(id){
    const p = byIdMap[id];
    if(saved.has(id)){ saved.delete(id); toast("Removed " + p.title + " from your watchlist"); }
    else { saved.add(id); model.signals += 1; toast("Added " + p.title + " to your watchlist — logged as a signal"); }
    const c = $("watchCount");
    c.textContent = saved.size;
    c.setAttribute("data-empty", saved.size === 0 ? "1" : "0");
    lastUpdate = Date.now();
    recompute();
  }

  function syncSaveButtons(){
    $("heroSave").textContent = saved.has(heroId) ? "In your watchlist" : "Add to watchlist";
    if(openId) $("dSave").textContent = saved.has(openId) ? "In your watchlist" : "Add to watchlist";
  }

  function renderRail(){
    const t = Date.now();
    const seen = Object.create(null);
    const picks = listings
      .filter(function(p){ return p.end > t; })
      .sort(function(a,b){ return a.start - b.start; })
      .filter(function(p){ if(seen[p.title]) return false; seen[p.title] = 1; return true; })
      .slice(0, 6);

    $("rail").innerHTML = picks.map(function(p){
      return '<button class="card" data-id="' + p.id + '">'
        + '<div class="poster" style="--p1:' + p.poster.p1 + ';--p2:' + p.poster.p2 + ';--p3:' + p.poster.p3 + '">'
          + '<p class="poster-kicker">' + esc(p.ch.name) + '</p>'
          + '<h3 class="poster-title">' + esc(p.title) + '</h3>'
          + '<div class="poster-foot"><span>' + hhmm(p.start) + '</span><span>' + runtime(p.dur) + '</span></div>'
        + '</div>'
        + '<div class="card-meta"><span class="card-title">' + esc(p.title) + (saved.has(p.id) ? ' ●' : '') + '</span>'
        + '<span class="card-sub"><i class="gdot" style="--gc:' + gcolor(p.genre) + '"></i>'
        + GENRES[p.genre].label + ' · ' + hhmm(p.start) + '</span></div></button>';
    }).join("");
  }

  $("rail").addEventListener("click", function(e){
    const c = e.target.closest(".card");
    if(c) openDrawer(c.dataset.id);
  });

  /* ============================================================
     11. TIME
     ============================================================ */
  function jumpToNow(smooth){
    const epg = $("epg");
    const chw = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--chw"));
    const mins = Math.max(0, Math.min(MIN, (Date.now() - START.getTime()) / 60000));
    epg.scrollTo({ left: Math.max(0, chw + mins*PPM - epg.clientWidth*0.28), behavior: smooth ? "smooth" : "auto" });
  }

  function tick(){
    const t = Date.now(), d = new Date(t);
    const days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
    $("clock").innerHTML = days[d.getDay()] + " <b>" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + "</b>";
    $("footStamp").textContent = "Guide " + hhmm(t) + " · model v4.2.1 · all inference on-device";

    const mins = Math.max(0, Math.min(MIN, (t - START.getTime()) / 60000));
    const chw = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--chw"));
    const ph = $("playhead"), flag = $("nowFlag");
    if(ph) ph.style.left = (chw + mins*PPM) + "px";
    if(flag){ flag.style.left = (mins*PPM) + "px"; $("nowFlagT").textContent = hhmm(t); }

    renderHero(t);
    recompute();
  }

  /* one place that re-derives every model-dependent view */
  function recompute(){
    applyFilter();
    renderRecos();
    renderModelPanel();
    renderPath();
    renderRail();
    if(openId) renderDrawer();
    syncSaveButtons();
  }

  /* ============================================================
     12. WIRING
     ============================================================ */
  $("jumpNow").addEventListener("click", function(){ jumpToNow(true); });
  $("modelChip").addEventListener("click", function(){
    $("modelPanel").scrollIntoView({behavior:"smooth", block:"center"});
  });
  $("retrain").addEventListener("click", function(){
    model = clone(SEED);
    lastUpdate = Date.now();
    toast("Model reset to the baseline profile — 1,284 seed signals");
    recompute();
  });
  $("tuneBtn").addEventListener("click", function(){
    const p = byIdMap[heroId];
    toast("Tuning to " + p.ch.name + " — " + p.title);
  });
  $("heroSave").addEventListener("click", function(){ toggleSave(heroId); });
  $("heroMore").addEventListener("click", function(){ openDrawer(heroId); });
  $("dSave").addEventListener("click", function(){ if(openId) toggleSave(openId); });
  $("dMore").addEventListener("click", function(){ if(openId) learn(openId, 1); });
  $("dLess").addEventListener("click", function(){ if(openId) learn(openId, -1); });
  $("dRemind").addEventListener("click", function(){
    toast("We'll alert you 10 minutes before " + byIdMap[openId].title + " starts");
  });
  $("dClose").addEventListener("click", closeDrawer);
  $("scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function(e){ if(e.key === "Escape" && openId) closeDrawer(); });
  $("watchBtn").addEventListener("click", function(){
    if(saved.size === 0){ toast("Your watchlist is empty — add something from the guide"); return; }
    const names = Array.from(saved).map(function(id){ return byIdMap[id].title; });
    toast(saved.size + " saved: " + names.slice(0,2).join(", ") + (names.length > 2 ? " +" + (names.length-2) + " more" : ""));
  });

  /* ---------- go ---------- */
  buildGuide();
  tick();
  jumpToNow(false);
  setInterval(tick, 20000);
})();
