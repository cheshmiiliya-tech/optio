/* Optio — sign in / create account.
   Talks to app.py. If no server is answering, it says so plainly rather
   than pretending to sign anyone in. */
(function(){
  "use strict";

  const $ = function(id){ return document.getElementById(id); };

  /* Paths must be relative: on GitHub Pages the site lives under /optio/,
     so a leading slash escapes to the domain root. BASE is the directory
     this page was served from, with its trailing slash. */
  const BASE = location.pathname.replace(/[^/]*$/, "");

  let mode = "login";
  let toastTimer = null;

  function toast(msg){
    const el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, 3200);
  }

  function showError(msg){
    const el = $("authError");
    if(!msg){ el.hidden = true; el.textContent = ""; return; }
    el.hidden = false;
    el.textContent = msg;
  }

  function setMode(next){
    mode = next;
    const registering = mode === "register";
    $("tabLogin").setAttribute("aria-selected", String(!registering));
    $("tabRegister").setAttribute("aria-selected", String(registering));
    $("nameField").hidden = !registering;
    $("authSubmit").textContent = registering ? "Create account" : "Sign in";
    $("password").setAttribute("autocomplete", registering ? "new-password" : "current-password");
    $("authSwitch").innerHTML = registering
      ? 'Already have an account? <button type="button" class="linkish" id="switchToRegister">Sign in</button>'
      : 'New here? <button type="button" class="linkish" id="switchToRegister">Create an account</button>';
    showError("");
  }

  $("tabLogin").addEventListener("click", function(){ setMode("login"); });
  $("tabRegister").addEventListener("click", function(){ setMode("register"); });
  $("authSwitch").addEventListener("click", function(e){
    if(e.target.id === "switchToRegister") setMode(mode === "login" ? "register" : "login");
  });

  $("authForm").addEventListener("submit", async function(e){
    e.preventDefault();
    showError("");
    const username = $("username").value.trim();
    const password = $("password").value;
    if(username.length < 3) return showError("Username needs at least 3 characters.");
    if(password.length < 6) return showError("Password needs at least 6 characters.");

    const btn = $("authSubmit");
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = mode === "register" ? "Creating…" : "Signing in…";

    try{
      const body = {username: username, password: password};
      if(mode === "register") body.display_name = $("displayName").value.trim() || username;

      const r = await fetch(BASE + "api/" + mode, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        credentials:"include",
        body: JSON.stringify(body)
      });
      const data = await r.json().catch(function(){ return {}; });

      if(!r.ok){
        showError(data.error || "That did not work. Please try again.");
        btn.disabled = false; btn.textContent = original;
        return;
      }
      if(data.first_time) sessionStorage.setItem("optio-welcome", "1");
      location.href = BASE + "index.html";
    }catch(err){
      showError(noServerMessage());
      btn.disabled = false; btn.textContent = original;
    }
  });

  /* The commonest cause of "no server" is not a stopped server - it is
     the page being opened from somewhere the server is not: a file://
     path, or a different port such as VS Code Live Server on 5500/5501.
     The API is same-origin, so it only answers when the page itself came
     from the server. Name whichever case this is. */
  function noServerMessage(){
    const p = location.protocol, host = location.host;
    if(p === "file:"){
      return "This page was opened straight from disk, so there is no server to sign in to. "
           + "Start it with  cd Optio  then  .\\run.ps1  and open http://127.0.0.1:8000 instead.";
    }
    if(host && host.indexOf("127.0.0.1:8000") < 0 && host.indexOf("localhost:8000") < 0
       && host.indexOf("github.io") < 0){
      return "This page is being served from " + host + ", but Optio's API runs on port 8000. "
           + "Open http://127.0.0.1:8000 instead — Live Server cannot run the Python side.";
    }
    return "No server is answering on port 8000. Start it with  cd Optio  then  .\\run.ps1 "
         + "and keep that window open.";
  }

  /* Already signed in? Go straight through.

     If nothing answers, this is the hosted preview: GitHub Pages serves
     files, it cannot run Python, so there is no database to hold an
     account. Rather than leave a live-looking form that can never succeed,
     the page says so and offers the way in that does work. */
  (async function(){
    try{
      const r = await fetch(BASE + "api/me", {credentials:"include"});
      const me = await r.json();
      if(me.signed_in){ location.href = BASE + "index.html"; return; }
    }catch(e){
      offlineNotice();
    }
  })();

  function offlineNotice(){
    const onPages = location.host.indexOf("github.io") >= 0;
    document.getElementById("authForm").hidden = true;
    document.querySelector(".auth-tabs").hidden = true;
    const note = document.getElementById("authNote");
    note.classList.add("auth-offline");

    if(onPages){
      note.innerHTML =
          "<b>This is the hosted preview — accounts need the server.</b>"
        + "<p>GitHub Pages can serve files but cannot run Python, so there is no database "
        + "here to keep an account in. Everything else works: the catalogue, both models, "
        + "the comparison and the explanations.</p>"
        + '<a class="btn btn-primary auth-submit" href="' + BASE + 'index.html">'
        + 'Continue to the preview</a>'
        + "<p class='auth-runit'>To get accounts, the trained classifiers and saved history, "
        + "run it locally:<br><code>cd Optio</code><br><code>.\\run.ps1 -Setup</code></p>";
      return;
    }

    note.innerHTML =
        "<b>Nothing is answering yet.</b>"
      + "<p>" + noServerMessage() + "</p>"
      + '<a class="btn btn-primary auth-submit" href="http://127.0.0.1:8000/login.html">'
      + 'Try http://127.0.0.1:8000</a>'
      + "<p class='auth-runit'>Start the server:<br><code>cd Optio</code><br>"
      + "<code>.\\run.ps1</code><br>then keep that window open.</p>";
  }
})();
