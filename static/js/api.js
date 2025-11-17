// Minimal API helper (Phase 1 stub)
// - Adds CSRF token automatically for same-origin unsafe methods
// - Provides apiGet/apiPost wrappers
(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  function getCsrfToken() {
    const fromCookie = getCookie('csrftoken');
    if (fromCookie) return fromCookie;
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    return '';
  }

  async function apiFetch(url, options = {}) {
    const opts = { ...options };
    opts.headers = {
      'Accept': 'application/json',
      ...(opts.headers || {})
    };
    const method = (opts.method || 'GET').toUpperCase();
    const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
    if (isSameOrigin) {
      // Include session cookies so DRF SessionAuthentication works
      opts.credentials = 'same-origin';
    }
    if (isSameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      opts.headers['X-CSRFToken'] = getCsrfToken();
      if (!(opts.body instanceof FormData)) {
        opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
      }
    }
    const resp = await fetch(url, opts);
    if (!resp.ok) {
      let detail = `Request failed (HTTP ${resp.status})`;
      let payload = null;
      try {
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
          payload = await resp.json();
        } else {
          payload = await resp.text();
        }
      } catch (e) {
        payload = null;
      }
      if (payload) {
        if (typeof payload === 'string' && payload.trim()) {
          detail = payload;
        } else if (payload.detail) {
          detail = payload.detail;
        }
      }
      const err = new Error(detail);
      err.status = resp.status;
      err.body = payload;
      throw err;
    }
    const hasBody = resp.status !== 204 && resp.status !== 205;
    if (!hasBody) {
      return null;
    }
    const ct = resp.headers.get('content-type') || '';
    return ct.includes('application/json') ? resp.json() : resp.text();
  }

  window.apiGet = (url) => apiFetch(url, { method: 'GET' });
  window.apiPost = (url, body) => apiFetch(url, { method: 'POST', body: JSON.stringify(body || {}) });
  window.apiPatch = (url, body) => apiFetch(url, { method: 'PATCH', body: JSON.stringify(body || {}) });
  window.apiPut = (url, body) => apiFetch(url, { method: 'PUT', body: JSON.stringify(body || {}) });
  window.apiDelete = (url) => apiFetch(url, { method: 'DELETE' });
  window.apiFetch = apiFetch;
})();
