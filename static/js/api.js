// Minimal API helper (Phase 1 stub)
// - Adds CSRF token automatically for same-origin unsafe methods
// - Provides apiGet/apiPost wrappers
(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  const csrftoken = getCookie('csrftoken');

  async function apiFetch(url, options = {}) {
    const opts = { ...options };
    opts.headers = {
      'Accept': 'application/json',
      ...(opts.headers || {})
    };
    const method = (opts.method || 'GET').toUpperCase();
    const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
    if (isSameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      opts.headers['X-CSRFToken'] = csrftoken || '';
      if (!(opts.body instanceof FormData)) {
        opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
      }
    }
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const ct = resp.headers.get('content-type') || '';
    return ct.includes('application/json') ? resp.json() : resp.text();
  }

  window.apiGet = (url) => apiFetch(url, { method: 'GET' });
  window.apiPost = (url, body) => apiFetch(url, { method: 'POST', body: JSON.stringify(body || {}) });
})();
