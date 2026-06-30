/* ════════════════════════════════════════════════════════════════
   Darkbrown Real Estate — Login Page Builder
   Injected on /login via web_include_js.
   Wraps Frappe's existing login card in the branded two-panel layout.
   Does NOT recreate or touch the auth form fields/buttons — it only
   re-parents and decorates, so all native login behaviour is intact.
   ════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  // Run only on the login route. Frappe may serve it as either
  // /login (path) or /#login (hash) — handle both.
  function isLoginPage() {
    var path = location.pathname.replace(/\/$/, "");
    var hash = (location.hash || "").replace(/^#/, "");
    return path === "/login" || hash === "login" ||
           // also catch the bare root that renders the login card
           !!document.querySelector(".page-card");
  }

  var LOGO = "/assets/darkbrown/images/darkbrown-logo.png";

  // Pick the correct login card. Frappe renders MULTIPLE .page-card
  // elements (login, forgot-password, email-login, signup) and toggles
  // them by route. We must grab the LOGIN one specifically — preferring
  // the one inside .for-login, else the first visible card.
  function findLoginCard() {
    // Preferred: the card inside Frappe's login wrapper.
    var forLogin = document.querySelector(".for-login .page-card, .login-content .for-login");
    if (forLogin) {
      var c = forLogin.classList && forLogin.classList.contains("page-card")
        ? forLogin
        : forLogin.querySelector(".page-card");
      if (c) return c;
    }
    // Fallback: first card that is actually visible on screen.
    var cards = document.querySelectorAll(".page-card");
    for (var i = 0; i < cards.length; i++) {
      var el = cards[i];
      if (el.offsetParent !== null) return el; // visible
    }
    return cards.length ? cards[0] : null;
  }

  function build() {
    // Fast guard: if already built, do nothing (prevents observer loop).
    if (document.querySelector(".db-login-shell")) return true;

    // Find Frappe's native (visible) login card.
    var card = findLoginCard();
    if (!card) return false;

    // Pause observing while we move DOM around, so our own changes
    // don't re-trigger the observer mid-build.
    if (window.__dbObserver) window.__dbObserver.disconnect();

    document.body.classList.add("darkbrown-login");

    // Hide Frappe's standalone splash logo + "Login to Frappe" heading.
    // These live OUTSIDE .page-card, so CSS alone can miss them depending
    // on Frappe's markup version — hide defensively here too.
    var splashSelectors = [
      ".page-card-head",
      ".login-content > .text-center",
      ".for-login .page-card-head",
      "[data-page-route='login'] img.app-logo",
    ];
    splashSelectors.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.style.display = "none";
      });
    });
    // Hide any element whose text is exactly the Frappe login heading,
    // and the bare app logo above it, if they sit outside the card.
    document.querySelectorAll("h1, h2, h3, .navbar-brand, .app-logo, img").forEach(function (el) {
      var txt = (el.textContent || "").trim();
      if (/^Login to Frappe$/i.test(txt)) {
        el.style.display = "none";
        var prev = el.previousElementSibling;
        if (prev && (prev.tagName === "IMG" || prev.querySelector && prev.querySelector("img"))) {
          prev.style.display = "none";
        }
      }
    });

    // ── Build shell ──
    var shell = document.createElement("div");
    shell.className = "db-login-shell";

    // LEFT PANEL
    var left = document.createElement("div");
    left.className = "db-left";
    left.innerHTML =
      '<img src="' + LOGO + '" class="db-watermark" alt="">' +
      '<svg class="db-arc" width="400" height="400" viewBox="0 0 400 400" fill="none">' +
        '<circle cx="200" cy="200" r="198" stroke="#C9A86A" stroke-width="1.2"/>' +
        '<circle cx="200" cy="200" r="148" stroke="#C9A86A" stroke-width=".7"/>' +
      '</svg>' +
      '<div class="db-brandmark">' +
        '<img src="' + LOGO + '" alt="Darkbrown">' +
        '<div>' +
          '<div class="db-bn1">Darkbrown</div>' +
          '<div class="db-bn2">Real Estate</div>' +
        '</div>' +
      '</div>' +
      '<div class="db-hero">' +
        '<div class="db-hero-head">Manage your<br><em>portfolio</em><br>with clarity.</div>' +
        '<div class="db-hero-rule"></div>' +
        '<div class="db-hero-tag">One platform for your entire organisation — properties, tenants, finance, and operations, all in one place.</div>' +
      '</div>' +
      '<div class="db-foot">© 2026 Darkbrown Real Estate · All rights reserved</div>';

    // RIGHT PANEL
    var right = document.createElement("div");
    right.className = "db-right";
    right.innerHTML =
      '<svg class="db-arc-tr" width="340" height="340" viewBox="0 0 340 340" fill="none">' +
        '<circle cx="170" cy="170" r="168" stroke="#C9A86A" stroke-width="1.2"/>' +
        '<circle cx="170" cy="170" r="120" stroke="#C9A86A" stroke-width=".7"/>' +
        '<circle cx="170" cy="170" r="72" stroke="#C9A86A" stroke-width=".5"/>' +
      '</svg>' +
      '<svg class="db-arc-bl" width="220" height="220" viewBox="0 0 220 220" fill="none">' +
        '<circle cx="110" cy="110" r="108" stroke="#C9A86A" stroke-width="1"/>' +
        '<circle cx="110" cy="110" r="70" stroke="#C9A86A" stroke-width=".6"/>' +
      '</svg>';

    var slot = document.createElement("div");
    slot.className = "db-form-slot";

    var heading = document.createElement("div");
    heading.className = "db-form-heading";
    heading.innerHTML =
      '<div class="db-h1">Welcome back</div>' +
      '<div class="db-h2">Sign in to your account</div>';

    slot.appendChild(heading);

    // Move Frappe's login UI into our slot. Prefer moving the whole
    // container that holds ALL the cards (login / forgot / email-link),
    // so route-toggling between those flows keeps working. Fall back to
    // moving just the login card if no container is found.
    var container =
      document.querySelector(".login-content") ||
      document.querySelector("#page-login .page-content") ||
      card.parentNode;

    var containerParent = container.parentNode;
    slot.appendChild(container);
    right.appendChild(slot);

    shell.appendChild(left);
    shell.appendChild(right);

    // Mount the shell where the container used to live (or on body).
    if (containerParent && containerParent.appendChild) {
      containerParent.appendChild(shell);
    } else {
      document.body.appendChild(shell);
    }

    // Resume observing in case Frappe re-renders later.
    if (window.__dbObserver && document.body) {
      window.__dbObserver.observe(document.body, { childList: true, subtree: true });
    }

    return true;
  }

  // ── Trigger strategy ──
  // Frappe is a SPA and injects the login card asynchronously, sometimes
  // re-rendering it. A timed retry is unreliable; instead watch the DOM
  // and build the moment the card appears (and re-build if Frappe replaces it).

  function tryBuild() {
    try { build(); } catch (e) { /* never let an error halt the observer */ }
  }

  // 1) Observe the whole document for the card being added.
  var observer = new MutationObserver(function () {
    tryBuild();
  });
  window.__dbObserver = observer;

  function startObserving() {
    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
      tryBuild();
    }
  }

  if (document.body) {
    startObserving();
  } else {
    document.addEventListener("DOMContentLoaded", startObserving);
  }

  // 2) Also rebuild on hash changes (e.g. → #login) and after full load.
  window.addEventListener("hashchange", tryBuild);
  window.addEventListener("load", tryBuild);

  // 3) Safety: a few delayed attempts in case the observer starts late.
  [200, 600, 1200, 2500].forEach(function (ms) {
    setTimeout(tryBuild, ms);
  });
})();
