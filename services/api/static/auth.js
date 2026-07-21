// Shared by every dashboard page: gets the demo API key into window.API_KEY
// without it ever sitting in the address bar. A cookie carries it instead -
// the browser attaches a cookie automatically to every request on this
// origin (page loads, <img> tags, fetch calls) the same way it would a
// header, which a URL query string never did for anything but the page
// navigation itself.
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setCookie(name, value) {
    // 7 days - long enough to survive a browser restart between test runs
    // and the demo recording itself, without living forever.
    document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=604800; SameSite=Strict`;
  }

  function showKeyPrompt() {
    const overlay = document.createElement("div");
    overlay.className = "api-key-overlay";
    overlay.innerHTML = `
      <div class="card api-key-box">
        <h2>MedSyn Lab</h2>
        <p class="page-subtitle">Enter the API key for this deployment.</p>
        <form id="api-key-form">
          <input type="password" id="api-key-input" autocomplete="off" placeholder="API key" />
          <button type="submit" class="btn-primary" style="margin-top: 0.75rem;">Continue</button>
        </form>
      </div>
    `;
    document.body.appendChild(overlay);
    document.getElementById("api-key-input").focus();
    document.getElementById("api-key-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const value = document.getElementById("api-key-input").value.trim();
      if (!value) return;
      setCookie("api_key", value);
      window.location.reload();
    });
  }

  let apiKey = getCookie("api_key");

  // A ?api_key=... in the URL (an old bookmark, or a link shared before
  // this page had a cookie yet) still works once - it's promoted to a
  // cookie and stripped from the visible URL immediately.
  const params = new URLSearchParams(window.location.search);
  const urlKey = params.get("api_key");
  if (!apiKey && urlKey) {
    apiKey = urlKey;
    setCookie("api_key", apiKey);
    params.delete("api_key");
    const cleanQuery = params.toString();
    const cleanUrl = window.location.pathname + (cleanQuery ? `?${cleanQuery}` : "") + window.location.hash;
    window.history.replaceState({}, "", cleanUrl);
  }

  window.API_KEY = apiKey;

  if (!apiKey) {
    showKeyPrompt();
  }
})();
