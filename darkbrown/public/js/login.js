/* Darkbrown Real Estate — Login Page Logic
   Place at: darkbrown/public/js/login.js
   Served at: /assets/darkbrown/js/login.js

   Talks to Frappe's built-in login endpoint directly — no custom
   backend method needed. On success, redirects to /app (Desk) or
   the `redirect-to` query param if one is present.
*/

(function () {
  "use strict";

  const form        = document.getElementById("db-login-form");
  const emailInput  = document.getElementById("db-email");
  const passInput   = document.getElementById("db-password");
  const rememberBox = document.getElementById("db-remember");
  const toggleBtn   = document.getElementById("db-toggle-pass");
  const submitBtn   = document.getElementById("db-submit");
  const btnLabel    = submitBtn.querySelector(".db-btn-label");
  const btnSpinner  = submitBtn.querySelector(".db-btn-spinner");
  const errorBox    = document.getElementById("db-error");

  // ---- Password visibility toggle ----
  toggleBtn.addEventListener("click", function () {
    const isPassword = passInput.type === "password";
    passInput.type = isPassword ? "text" : "password";
    toggleBtn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
  });

  // ---- Helpers ----
  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }
  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }
  function setLoading(isLoading) {
    submitBtn.disabled = isLoading;
    btnLabel.hidden = isLoading;
    btnSpinner.hidden = !isLoading;
  }
  function getRedirectTarget() {
    const params = new URLSearchParams(window.location.search);
    return params.get("redirect-to") || "/app";
  }

  // ---- Submit ----
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    clearError();

    const usr = emailInput.value.trim();
    const pwd = passInput.value;

    if (!usr || !pwd) {
      showError("Please enter both your email and password.");
      return;
    }

    setLoading(true);

    // Persist "remember me" the same way Frappe's stock login page does
    try {
      if (rememberBox.checked) {
        localStorage.setItem("remember_me_email", usr);
      } else {
        localStorage.removeItem("remember_me_email");
      }
    } catch (err) {
      /* localStorage unavailable — non-fatal */
    }

    const formData = new FormData();
    formData.append("usr", usr);
    formData.append("pwd", pwd);

    fetch("/api/method/login", {
      method: "POST",
      headers: {
        "X-Frappe-CSRF-Token": window.csrf_token || ""
      },
      body: formData,
      credentials: "same-origin"
    })
      .then(function (response) {
        if (response.ok) {
          window.location.href = getRedirectTarget();
          return;
        }
        return response.json().then(function (data) {
          const message =
            (data && (data.message || (data._server_messages && JSON.parse(data._server_messages)[0]))) ||
            "Invalid email or password. Please try again.";
          throw new Error(typeof message === "string" ? message.replace(/^"|"$/g, "") : "Invalid email or password. Please try again.");
        });
      })
      .catch(function (err) {
        setLoading(false);
        showError(err.message || "Something went wrong. Please try again.");
      });
  });

  // ---- Pre-fill remembered email ----
  try {
    const remembered = localStorage.getItem("remember_me_email");
    if (remembered) {
      emailInput.value = remembered;
      rememberBox.checked = true;
    }
  } catch (err) {
    /* localStorage unavailable — non-fatal */
  }

  // "Forgot password?" links straight to Frappe's built-in reset flow
  // via the href="/login#forgot" set in the HTML — no JS needed here.
})();
