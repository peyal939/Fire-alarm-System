(function () {
  const forms = document.querySelectorAll('[data-change-password-form]');
  if (!forms.length) {
    return;
  }

  const DEFAULT_ENDPOINT = '/auth/change-password';

  forms.forEach((form) => {
    const alertBox = form.querySelector('[data-change-password-alerts]');
    const submitButton = form.querySelector('[data-change-password-submit]');
    const endpoint = form.getAttribute('data-endpoint') || DEFAULT_ENDPOINT;

    function renderAlert(message, variant) {
      if (!alertBox) {
        return;
      }
      alertBox.innerHTML = '<div class="alert alert-' + variant + '" role="alert">' + message + '</div>';
    }

    function clearAlert() {
      if (!alertBox) {
        return;
      }
      alertBox.innerHTML = '';
    }

    function setSubmitting(isSubmitting) {
      if (!submitButton) {
        return;
      }
      submitButton.disabled = isSubmitting;
      submitButton.innerText = isSubmitting ? 'Saving…' : 'Save new password';
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearAlert();

      const formData = new FormData(form);
      const payload = {
        current_password: formData.get('current_password') || '',
        new_password: formData.get('new_password') || '',
        confirm_new_password: formData.get('confirm_new_password') || ''
      };

      if (!payload.current_password || !payload.new_password || !payload.confirm_new_password) {
        renderAlert('Please complete all password fields.', 'warning');
        return;
      }

      if (payload.new_password !== payload.confirm_new_password) {
        renderAlert('New password entries do not match.', 'warning');
        return;
      }

      setSubmitting(true);

      try {
        await window.apiPost(endpoint, payload);
        renderAlert('Password updated successfully.', 'success');
        form.reset();
        const focusField = form.querySelector('input[name="current_password"]');
        if (focusField) {
          focusField.focus();
        }
      } catch (error) {
        let message = 'Unable to update password. Please try again.';
        if (error && error.body) {
          if (typeof error.body === 'string' && error.body.trim()) {
            message = error.body;
          } else if (error.body.detail) {
            message = error.body.detail;
          } else if (typeof error.body === 'object') {
            const lines = [];
            Object.entries(error.body).forEach(([_, value]) => {
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
        renderAlert(message, 'danger');
      } finally {
        setSubmitting(false);
      }
    });
  });
})();
