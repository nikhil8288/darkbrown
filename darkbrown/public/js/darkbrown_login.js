/* ════════════════════════════════════════════════════════════════
   Darkbrown Real Estate — Login Page Builder
   Injected on /login via web_include_js.
   Wraps Frappe's existing login card in the branded two-panel layout.
   Does NOT recreate or touch the auth form fields/buttons — it only
   re-parents and decorates, so all native login behaviour is intact.
   ════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  // Run only on the login route.
  function isLoginPage() {
    return location.pathname.replace(/\/$/, "") === "/login";
  }
  if (!isLoginPage()) return;

  var LOGO = "/assets/darkbrown/images/darkbrown-logo.png";

  function build() {
    // Find Frappe's native login card.
    var card = document.querySelector(".page-card");
    if (!card) return false;

    // Avoid double-building.
    if (document.querySelector(".db-login-shell")) return true;

    document.body.classList.add("darkbrown-login");

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

    // Move Frappe's real card into our slot (keeps all event handlers).
    var cardParent = card.parentNode;
    slot.appendChild(card);
    right.appendChild(slot);

    shell.appendChild(left);
    shell.appendChild(right);

    // Mount the shell where the card used to live (or on body).
    if (cardParent && cardParent.appendChild) {
      cardParent.appendChild(shell);
    } else {
      document.body.appendChild(shell);
    }

    return true;
  }

  // Frappe renders login client-side; retry until the card exists.
  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    if (build() || tries > 60) clearInterval(timer);
  }, 100);

  document.addEventListener("DOMContentLoaded", build);
})();
