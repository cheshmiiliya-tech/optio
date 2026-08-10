/* Optio — sign in / create account.
   Talks to app.py. If no server is answering, it says so plainly rather
   than pretending to sign anyone in. */
(function(){
  "use strict";

  const $ = function(id){ return document.getElementById(id); };
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

      const r = await fetch("/api/" + mode, {
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
      location.href = "/";
    }catch(err){
      showError("No server is answering. Start it with:  cd Optio  then  python app.py");
      btn.disabled = false; btn.textContent = original;
    }
  });

  /* already signed in? go straight through */
  (async function(){
    try{
      const r = await fetch("/api/me", {credentials:"include"});
      const me = await r.json();
      if(me.signed_in) location.href = "/";
    }catch(e){
      showError("No server is answering yet. Start it with:  cd Optio  then  python app.py");
    }
  })();
})();
