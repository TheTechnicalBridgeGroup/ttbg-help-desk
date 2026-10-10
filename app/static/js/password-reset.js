"use strict";
(() => {
    const field = document.getElementById("reset-token");
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) field.value = token;
    // Keep the credential out of browser history, referrers and subsequent URLs.
    if (window.location.hash) history.replaceState(null, "", window.location.pathname);
})();
