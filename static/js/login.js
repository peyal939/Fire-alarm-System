(function () {
  const registerForm = document.getElementById('registerForm');
  if (!registerForm) {
    return;
  }

  const registerAlert = document.getElementById('registerAlert');
  const registerSubmit = document.getElementById('registerSubmit');
  const loginEmailField = document.querySelector('#loginPane input[name="email"]');
  const loginTabTrigger = document.getElementById('login-tab');

  function showAlert(message, variant) {
    registerAlert.innerHTML = '<div class="alert alert-' + variant + '" role="alert">' + message + '</div>';
  }

  function clearAlert() {
    registerAlert.innerHTML = '';
  }

  function extractPayload() {
    const formData = new FormData(registerForm);
    const payload = {
      email: (formData.get('email') || '').trim().toLowerCase(),
      phone_number: (formData.get('phone_number') || '').trim(),
      password: formData.get('password') || '',
      confirm_password: formData.get('confirm_password') || ''
    };
    if (!payload.phone_number) {
      delete payload.phone_number;
    }
    return payload;
  }

  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert();

    const payload = extractPayload();

    if (!payload.email || !payload.password || !payload.confirm_password) {
      showAlert('Email and both password fields are required.', 'warning');
      return;
    }

    if (payload.password.length < 6) {
      showAlert('Password must be at least 6 characters long.', 'warning');
      return;
    }

    if (payload.password !== payload.confirm_password) {
      showAlert('Passwords do not match.', 'warning');
      return;
    }

    const requestBody = {
      email: payload.email,
      password: payload.password,
    };
    if (payload.phone_number) {
      requestBody.phone_number = payload.phone_number;
    }

    registerSubmit.disabled = true;
    registerSubmit.innerText = 'Creating account…';

    try {
      await window.apiPost('/auth/register', requestBody);
      showAlert('Account created successfully. You can now sign in.', 'success');
      registerForm.reset();
      if (loginEmailField) {
        loginEmailField.value = requestBody.email;
        loginEmailField.focus();
      }
      if (window.bootstrap && typeof window.bootstrap.Tab === 'function' && loginTabTrigger) {
        const tab = window.bootstrap.Tab.getOrCreateInstance(loginTabTrigger);
        tab.show();
      }
    } catch (error) {
      let message = 'Unable to create the account. Please review the details and try again.';
      if (error && error.body) {
        if (typeof error.body === 'string' && error.body.trim()) {
          message = error.body;
        } else if (error.body.detail) {
          message = error.body.detail;
        } else if (typeof error.body === 'object') {
          const lines = [];
          Object.entries(error.body).forEach(([key, value]) => {
            if (Array.isArray(value)) {
              lines.push(value.join(' '));
            } else if (value) {
              lines.push(String(value));
            }
          });
          if (lines.length) {
            message = lines.join(' ');
          }
        }
      }
      showAlert(message, 'danger');
    } finally {
      registerSubmit.disabled = false;
      registerSubmit.innerText = 'Create account';
    }
  });
})();
