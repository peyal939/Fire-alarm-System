(function () {
  const page = document.querySelector('[data-account-page]');
  if (!page) {
    return;
  }

  const PROFILE_ENDPOINT = '/auth/me';

  function getCsrfToken() {
    const value = `; ${document.cookie}`;
    const parts = value.split('; csrftoken=');
    if (parts.length === 2) {
      return parts.pop().split(';').shift();
    }
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta && meta.content ? meta.content : '';
  }

  function buildFetchFallback(url, options = {}) {
    const opts = { ...options };
    opts.method = (opts.method || 'GET').toUpperCase();
    opts.headers = {
      Accept: 'application/json',
      ...(options.headers || {})
    };
    const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
    if (isSameOrigin) {
      opts.credentials = 'same-origin';
    }
    if (isSameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(opts.method)) {
      opts.headers['X-CSRFToken'] = getCsrfToken();
      if (!(opts.body instanceof FormData)) {
        opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
      }
    }
    return fetch(url, opts).then(async (resp) => {
      if (!resp.ok) {
        let detail = `Request failed (HTTP ${resp.status})`;
        try {
          const ct = resp.headers.get('content-type') || '';
          const payload = ct.includes('application/json') ? await resp.json() : await resp.text();
          if (payload) {
            if (typeof payload === 'string') {
              detail = payload;
            } else if (payload.detail) {
              detail = payload.detail;
            }
          }
        } catch (err) {
          /* noop */
        }
        const error = new Error(detail);
        error.status = resp.status;
        throw error;
      }
      if (resp.status === 204 || resp.status === 205) {
        return null;
      }
      const ct = resp.headers.get('content-type') || '';
      return ct.includes('application/json') ? resp.json() : resp.text();
    });
  }

  const apiFetcher = typeof window.apiFetch === 'function' ? window.apiFetch : buildFetchFallback;
  const apiGetter = typeof window.apiGet === 'function' ? window.apiGet : (url) => apiFetcher(url, { method: 'GET' });
  const patchRequester =
    typeof window.apiPatch === 'function'
      ? window.apiPatch
      : (url, body) =>
          apiFetcher(url, {
            method: 'PATCH',
            body: JSON.stringify(body || {})
          });
  const heroNameEls = page.querySelectorAll('[data-profile-display-name]');
  const emailEls = page.querySelectorAll('[data-profile-email]');
  const roleEls = page.querySelectorAll('[data-profile-role]');
  const phoneEls = page.querySelectorAll('[data-profile-phone]');
  const addressEls = page.querySelectorAll('[data-profile-address]');
  const devicesEls = page.querySelectorAll('[data-profile-devices]');
  const initialsEls = page.querySelectorAll('[data-profile-initials]');
  const syncStateEl = page.querySelector('[data-profile-sync-state]');
  const generalAlertBox = page.querySelector('[data-profile-alerts]');
  const loadingOverlay = page.querySelector('[data-profile-loading]');

  const fieldControllers = Array.from(
    page.querySelectorAll('[data-profile-field-form]')
  ).map(setupFieldController);

  const state = { profile: null };

  function setupFieldController(form) {
    const field = form.getAttribute('data-profile-field-form');
    const input = form.querySelector('[data-profile-field-input]');
    const submitButton = form.querySelector('[data-profile-field-submit]');
    const resetButton = form.querySelector('[data-profile-field-reset]');
    const statusEl = form.querySelector('[data-profile-field-status]');
    const alertEl = form.querySelector('[data-profile-field-alert]');
    const alertBaseClass = alertEl ? alertEl.className : '';

    const controller = {
      form,
      field,
      input,
      submitButton,
      resetButton,
      statusEl,
      alertEl,
      alertBaseClass,
    };

    controller.setStatus = (text, state = 'synced') => {
      if (controller.statusEl) {
        controller.statusEl.dataset.state = state;
        controller.statusEl.textContent = text || 'Synced';
      }
    };

    controller.setValue = (value) => {
      if (controller.input) {
        controller.input.value = value ?? '';
      }
    };

    controller.setBusy = (isBusy) => {
      if (controller.submitButton) {
        controller.submitButton.disabled = isBusy;
        controller.submitButton.textContent = isBusy ? 'Saving…' : 'Save';
      }
      if (controller.resetButton) {
        controller.resetButton.disabled = isBusy;
      }
    };

    controller.showAlert = (message, variant = 'muted') => {
      if (!controller.alertEl) {
        return;
      }
      controller.alertEl.className = controller.alertBaseClass || 'small';
      if (message) {
        controller.alertEl.textContent = message;
        controller.alertEl.classList.add('text-' + variant);
      } else {
        controller.alertEl.textContent = '';
        controller.alertEl.classList.add('text-muted');
      }
    };

    controller.getStateValue = () => {
      if (!state.profile) {
        return '';
      }
      return state.profile[controller.field] || '';
    };

    controller.resetToState = () => {
      controller.setValue(controller.getStateValue());
      controller.setStatus('Synced');
      controller.showAlert('');
    };

    if (controller.resetButton) {
      controller.resetButton.addEventListener('click', (event) => {
        event.preventDefault();
        controller.resetToState();
      });
    }

    if (controller.input) {
      controller.input.addEventListener('input', () => {
        const base = controller.getStateValue();
        const current = controller.input.value;
        if (current !== base) {
          controller.setStatus('Unsaved changes', 'pending');
        } else {
          controller.setStatus('Synced');
        }
        controller.showAlert('');
      });
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      submitField(controller);
    });

  controller.setStatus('Loading…', 'pending');
    return controller;
  }

  function setLoading(isLoading) {
    if (!loadingOverlay) {
      return;
    }
    loadingOverlay.classList.toggle('d-none', !isLoading);
  }

  function setSyncText(text) {
    if (syncStateEl) {
      syncStateEl.textContent = text;
    }
  }

  function renderGeneralAlert(message, variant = 'info') {
    if (!generalAlertBox) {
      return;
    }
    if (!message) {
      generalAlertBox.innerHTML = '';
      return;
    }
    generalAlertBox.innerHTML =
      '<div class="alert alert-' + variant + '" role="alert">' + message + '</div>';
  }

  function setTextContent(nodes, value) {
    nodes.forEach((node) => {
      node.textContent = value;
    });
  }

  function titleCase(value) {
    if (!value) {
      return 'User';
    }
    return value
      .split(/[_\s]+/)
      .filter(Boolean)
      .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
      .join(' ');
  }

  function initialsFromName(name) {
    if (!name) {
      return '--';
    }
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) {
      return '--';
    }
    if (parts.length === 1) {
      return parts[0].substring(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function describeDevices(devices) {
    if (!Array.isArray(devices) || !devices.length) {
      return 'No devices linked yet';
    }
    if (devices.length === 1) {
      const label = devices[0].device_name || devices[0].hardware_identifier;
      return '1 device (' + (label || 'unnamed') + ')';
    }
    const labels = devices
      .map((device) => device.device_name || device.hardware_identifier)
      .filter(Boolean);
    const previewList = labels.slice(0, 2);
    const preview = previewList.join(', ') || 'Multiple locations';
    const remainder = Math.max(devices.length - previewList.length, 0);
    const suffix = remainder ? ', +' + remainder + ' more' : '';
    return devices.length + ' devices (' + preview + suffix + ')';
  }

  function parseError(error) {
    let message = 'Something went wrong. Please try again.';
    if (!error) {
      return message;
    }
    if (error.body) {
      if (typeof error.body === 'string' && error.body.trim()) {
        return error.body;
      }
      if (error.body.detail) {
        return error.body.detail;
      }
      if (typeof error.body === 'object') {
        const parts = [];
        Object.values(error.body).forEach((value) => {
          if (Array.isArray(value)) {
            parts.push(value.join(' '));
          } else if (value) {
            parts.push(String(value));
          }
        });
        if (parts.length) {
          return parts.join(' ');
        }
      }
    }
    if (error.message) {
      message = error.message;
    }
    return message;
  }

  function updateHero(profile) {
    const displayName = profile.full_name || profile.email || 'Your account';
    setTextContent(heroNameEls, displayName);
    setTextContent(emailEls, profile.email || '—');
    setTextContent(roleEls, titleCase(profile.role || 'user'));
    setTextContent(phoneEls, profile.phone_number || '—');
    setTextContent(addressEls, profile.address || '—');
    setTextContent(devicesEls, describeDevices(profile.devices || []));
    setTextContent(initialsEls, initialsFromName(displayName));
  }

  function applyProfile(profile) {
    if (!profile) {
      return;
    }
    state.profile = profile;
    updateHero(profile);
    fieldControllers.forEach((controller) => {
      controller.setValue(profile[controller.field] || '');
      controller.setStatus('Synced');
      controller.showAlert('');
    });
  }

  async function fetchProfile() {
    setLoading(true);
    renderGeneralAlert('');
    setSyncText('Loading profile…');
    try {
      const data = await apiGetter(PROFILE_ENDPOINT);
      applyProfile(data || {});
      setSyncText('Synced just now');
    } catch (error) {
      renderGeneralAlert(parseError(error), 'danger');
      setSyncText('Failed to sync');
    } finally {
      setLoading(false);
    }
  }

  async function submitField(controller) {
    if (!controller || !controller.field) {
      return;
    }
    const value = controller.input ? controller.input.value : '';
    const payload = { [controller.field]: value };
    controller.setBusy(true);
  controller.setStatus('Saving…', 'pending');
    controller.showAlert('');
    setSyncText('Saving changes…');
    try {
  const response = await patchRequester(PROFILE_ENDPOINT, payload);
      const merged = response && typeof response === 'object' ? response : {};
      const nextProfile = {
        ...(state.profile || {}),
        ...merged,
      };
      if (typeof merged[controller.field] === 'undefined') {
        nextProfile[controller.field] = value;
      }
      applyProfile(nextProfile);
      controller.setValue(nextProfile[controller.field] || '');
  controller.setStatus('Saved just now', 'success');
      controller.showAlert('Updated successfully.', 'success');
      setSyncText('Updated just now');
    } catch (error) {
  controller.setStatus('Save failed', 'error');
      controller.showAlert(parseError(error), 'danger');
      setSyncText('Save failed');
    } finally {
      controller.setBusy(false);
    }
  }

  fetchProfile();
})();
