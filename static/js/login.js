(function () {
  function formatDuration(seconds) {
    const remaining = Math.max(0, Math.round(seconds));
    if (remaining <= 0) {
      return '';
    }
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    return `Resend available in ${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function createCooldown(button, timerEl) {
    let timerId = null;

    function stop() {
      if (timerId) {
        clearInterval(timerId);
        timerId = null;
      }
      if (timerEl) {
        timerEl.textContent = '';
      }
      if (button) {
        button.disabled = false;
      }
    }

    function start(seconds) {
      if (!button || !timerEl) {
        return;
      }
      const total = Math.max(0, parseInt(seconds || 0, 10));
      if (total <= 0) {
        stop();
        return;
      }
      let remaining = total;
      button.disabled = true;
      timerEl.textContent = formatDuration(remaining);
      timerId = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          stop();
        } else {
          timerEl.textContent = formatDuration(remaining);
        }
      }, 1000);
    }

    return { start, stop };
  }

  function parseTimestamp(value) {
    if (!value) {
      return null;
    }
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  function parseSeconds(value, fallback = 0) {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : fallback;
    }
    if (typeof value === 'string' && value.trim() !== '') {
      const parsed = parseInt(value, 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    }
    return fallback;
  }

  function computeRemainingSeconds({ readyAt, lastSent, cooldownSeconds }) {
    const now = Date.now();
    if (typeof readyAt === 'number') {
      return Math.max(0, Math.ceil((readyAt - now) / 1000));
    }
    if (typeof lastSent === 'number' && typeof cooldownSeconds === 'number') {
      const elapsed = Math.floor((now - lastSent) / 1000);
      return Math.max(0, cooldownSeconds - elapsed);
    }
    return 0;
  }

  function startTimer(config) {
    if (!config || !config.button || !config.timerEl) {
      return null;
    }
    const timer = createCooldown(config.button, config.timerEl);
    const seconds =
      typeof config.seconds === 'number'
        ? Math.max(0, Math.round(config.seconds))
        : computeRemainingSeconds(config);
    if (seconds > 0) {
      timer.start(seconds);
    } else {
      timer.stop();
    }
    return timer;
  }

  const otpCooldown = {
    createTimer: createCooldown,
    parseTimestamp,
    parseSeconds,
    computeRemainingSeconds,
    startTimer,
  };

  if (typeof window !== 'undefined') {
    window.otpCooldown = otpCooldown;
  }

  function maskPhone(value) {
    if (!value) {
      return '';
    }
    const trimmed = value.replace(/\s+/g, '');
    if (trimmed.length <= 4) {
      return trimmed;
    }
    return `${trimmed.slice(0, 4)}…${trimmed.slice(-2)}`;
  }

  function renderAlert(container, message, variant = 'info') {
    if (!container) {
      return;
    }
    container.innerHTML = message
      ? `<div class="alert alert-${variant}" role="alert">${message}</div>`
      : '';
  }

  function handleApiError(error, fallback) {
    if (!error) {
      return fallback;
    }
    if (typeof error.body === 'string' && error.body.trim()) {
      return error.body;
    }
    if (error.body && error.body.detail) {
      return error.body.detail;
    }
    if (error.body && typeof error.body === 'object') {
      // Friendly field labels
      const fieldLabels = {
        phone_number: 'Phone number',
        email: 'Email',
        password: 'Password',
        confirm_password: 'Confirm password',
        full_name: 'Full name',
        address: 'Address',
        role: 'Account type',
        otp_code: 'OTP code'
      };
      const parts = [];
      Object.entries(error.body).forEach(([key, value]) => {
        const label = fieldLabels[key] || key;
        const errorText = Array.isArray(value) ? value.join(' ') : String(value);
        if (errorText) {
          parts.push(`${label}: ${errorText}`);
        }
      });
      if (parts.length) {
        return parts.join('\n');
      }
    }
    return fallback;
  }

  // ------------------------------ Login OTP timer ---------------------------
  const loginFlow = document.getElementById('loginFlow');
  const loginIdentifierField = document.getElementById('loginIdentifier');
  if (loginFlow) {
    const loginResendBtn = document.getElementById('loginResendBtn');
    const loginResendTimer = document.getElementById('loginResendTimer');
    const cooldownSeconds = otpCooldown.parseSeconds(
      loginFlow.dataset.resendCooldown,
      0
    );
    const lastSent = otpCooldown.parseTimestamp(loginFlow.dataset.lastSent);
    const readyAt = otpCooldown.parseTimestamp(loginFlow.dataset.resendReadyAt);
    const otpPending = loginFlow.dataset.otpPending === 'true';
    if (otpPending && loginResendBtn && loginResendTimer) {
      otpCooldown.startTimer({
        button: loginResendBtn,
        timerEl: loginResendTimer,
        readyAt,
        lastSent,
        cooldownSeconds,
      });
    }
  }

  // ----------------------------- Register OTP flow -------------------------
  const registerFlow = document.getElementById('registerFlow');
  if (registerFlow) {
    const registerForm = document.getElementById('registerForm');
    const registerAlert = document.getElementById('registerAlert');
    const registerOtpAlert = document.getElementById('registerOtpAlert');
    const registerStepCredentials = document.getElementById('registerStepCredentials');
    const registerStepOtp = document.getElementById('registerStepOtp');
    const registerSuccess = document.getElementById('registerSuccess');
    const registerOtpForm = document.getElementById('registerOtpForm');
    const registerOtpCode = document.getElementById('registerOtpCode');
    const registerMaskedPhone = document.getElementById('registerMaskedPhone');
    const registerResendBtn = document.getElementById('registerResendBtn');
    const registerResendTimer = document.getElementById('registerResendTimer');
    const registerEditInfoBtn = document.getElementById('registerEditInfoBtn');
    const registerGoToLoginBtn = document.getElementById('registerGoToLoginBtn');
    const registerSubmit = document.getElementById('registerSubmit');
    const loginTabTrigger = document.getElementById('login-tab');
    const registerRoleHelp = document.getElementById('registerRoleHelp');
    const registerRoleInputs = document.querySelectorAll('#registerRoleGroup input[name="role"]');
    const registerAddressBlock = document.getElementById('registerAddressBlock');

    const registerState = {
      payload: null,
      sessionId: null,
      cooldownSeconds: otpCooldown.parseSeconds(
        registerFlow.dataset.resendCooldown,
        60
      ),
      timer: otpCooldown.createTimer(registerResendBtn, registerResendTimer),
    };

    function switchStep(step) {
      const showCredentials = step === 'credentials';
      const showOtp = step === 'otp';
      const showSuccess = step === 'success';
      registerStepCredentials.classList.toggle('d-none', !showCredentials);
      registerStepOtp.classList.toggle('d-none', !showOtp);
      registerSuccess.classList.toggle('d-none', !showSuccess);
    }

    function extractRegisterPayload() {
      const formData = new FormData(registerForm);
      const roleRaw = (formData.get('role') || 'user').trim();
      const role = roleRaw === 'company_admin' ? 'company_admin' : 'user';
      return {
        email: (formData.get('email') || '').trim().toLowerCase(),
        phone_number: (formData.get('phone_number') || '').trim(),
        password: formData.get('password') || '',
        confirm_password: formData.get('confirm_password') || '',
        full_name: (formData.get('full_name') || '').trim(),
        address: (formData.get('address') || '').trim(),
        role,
      };
    }

    function validateRegisterPayload(payload) {
      if (!payload.email) {
        return 'Email is required.';
      }
      if (!payload.phone_number) {
        return 'Phone number is required.';
      }
      if (!payload.password || !payload.confirm_password) {
        return 'Both password fields are required.';
      }
      if (payload.password.length < 6) {
        return 'Password must be at least 6 characters long.';
      }
      if (payload.password !== payload.confirm_password) {
        return 'Passwords do not match.';
      }
      if (payload.role !== 'user' && payload.role !== 'company_admin') {
        return 'Choose a valid account type.';
      }
      return null;
    }

    function syncRoleUI(role) {
      if (registerRoleHelp) {
        const text = role === 'company_admin'
          ? registerRoleHelp.dataset.companyText || registerRoleHelp.textContent
          : registerRoleHelp.dataset.userText || registerRoleHelp.textContent;
        registerRoleHelp.textContent = text;
      }
      if (registerAddressBlock) {
        registerAddressBlock.classList.toggle('d-none', role !== 'company_admin');
      }
    }

    function applyRoleFromForm() {
      const checkedInput = document.querySelector('#registerRoleGroup input[name="role"]:checked');
      const currentRole = checkedInput ? checkedInput.value : 'user';
      syncRoleUI(currentRole === 'company_admin' ? 'company_admin' : 'user');
    }

    if (registerRoleInputs && registerRoleInputs.length) {
      registerRoleInputs.forEach((input) => {
        input.addEventListener('change', () => {
          syncRoleUI(input.value === 'company_admin' ? 'company_admin' : 'user');
        });
      });
      applyRoleFromForm();
    } else {
      applyRoleFromForm();
    }

    async function requestRegistrationOtp(payload) {
      const response = await window.apiPost('/auth/register/init', payload);
      registerState.sessionId = response.session_id;
      registerState.payload = payload;
      registerState.cooldownSeconds = otpCooldown.parseSeconds(
        response.resend_cooldown,
        registerState.cooldownSeconds
      );
      registerState.timer.start(registerState.cooldownSeconds);
      if (registerMaskedPhone) {
        registerMaskedPhone.textContent = maskPhone(payload.phone_number);
      }
    }

    registerForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      renderAlert(registerAlert, '');

      const payload = extractRegisterPayload();
      const validationError = validateRegisterPayload(payload);
      if (validationError) {
        renderAlert(registerAlert, validationError, 'warning');
        return;
      }

      registerSubmit.disabled = true;
      const originalLabel = registerSubmit.innerText;
      registerSubmit.innerText = 'Sending OTP…';

      try {
        await requestRegistrationOtp(payload);
        switchStep('otp');
        renderAlert(registerOtpAlert, 'Enter the code you received to complete registration.', 'info');
        registerOtpCode && registerOtpCode.focus();
      } catch (error) {
        const message = handleApiError(
          error,
          'Unable to send OTP. Please review the details and try again.'
        );
        renderAlert(registerAlert, message, 'danger');
      } finally {
        registerSubmit.disabled = false;
        registerSubmit.innerText = originalLabel;
      }
    });

    registerOtpForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      renderAlert(registerOtpAlert, '');
      const code = (registerOtpCode.value || '').trim();
      if (!code) {
        renderAlert(registerOtpAlert, 'OTP is required.', 'warning');
        return;
      }
      if (!registerState.sessionId) {
        renderAlert(registerOtpAlert, 'OTP session expired. Please restart registration.', 'danger');
        return;
      }

      const submitBtn = document.getElementById('registerOtpSubmit');
      const originalLabel = submitBtn.innerText;
      submitBtn.disabled = true;
      submitBtn.innerText = 'Verifying…';

      try {
        await window.apiPost('/auth/register/verify', {
          session_id: registerState.sessionId,
          code,
        });
        registerState.timer.stop();
        switchStep('success');
        if (loginIdentifierField && registerState.payload) {
          loginIdentifierField.value = registerState.payload.email;
        }
        renderAlert(registerOtpAlert, '');
      } catch (error) {
        const message = handleApiError(error, 'Invalid or expired OTP.');
        renderAlert(registerOtpAlert, message, 'danger');
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerText = originalLabel;
      }
    });

    registerResendBtn.addEventListener('click', async () => {
      if (!registerState.payload || registerResendBtn.disabled) {
        return;
      }
      registerResendBtn.disabled = true;
      const originalLabel = registerResendBtn.innerText;
      registerResendBtn.innerText = 'Resending…';
      renderAlert(registerOtpAlert, '');
      try {
        await requestRegistrationOtp(registerState.payload);
        renderAlert(registerOtpAlert, 'We sent a new OTP. Please check your phone.', 'success');
        registerOtpCode && registerOtpCode.focus();
      } catch (error) {
        const message = handleApiError(error, 'Unable to resend OTP at this time.');
        renderAlert(registerOtpAlert, message, 'danger');
        registerResendBtn.disabled = false;
      } finally {
        registerResendBtn.innerText = originalLabel;
      }
    });

    registerEditInfoBtn.addEventListener('click', () => {
      registerState.timer.stop();
      registerState.sessionId = null;
      switchStep('credentials');
      renderAlert(registerOtpAlert, '');
      renderAlert(registerAlert, 'You can update your email or phone number and request a new OTP.', 'info');
    });

    registerGoToLoginBtn.addEventListener('click', () => {
      if (window.bootstrap && typeof window.bootstrap.Tab === 'function' && loginTabTrigger) {
        const tab = window.bootstrap.Tab.getOrCreateInstance(loginTabTrigger);
        tab.show();
      }
      if (loginIdentifierField && registerState.payload) {
        loginIdentifierField.value = registerState.payload.email;
        loginIdentifierField.focus();
      }
      switchStep('credentials');
      registerForm.reset();
      registerOtpForm.reset();
      applyRoleFromForm();
      registerState.sessionId = null;
      registerState.timer.stop();
      renderAlert(registerAlert, '');
      renderAlert(registerOtpAlert, '');
    });
  }

  // ----------------------------- Forgot password flow ----------------------
  const forgotFlow = document.getElementById('forgotPasswordFlow');
  if (!forgotFlow) {
    return;
  }

  const forgotPasswordLink = document.getElementById('forgotPasswordLink');
  const forgotBackToLoginBtn = document.getElementById('forgotBackToLogin');
  const forgotStepIdentifier = document.getElementById('forgotStepIdentifier');
  const forgotStepOtp = document.getElementById('forgotStepOtp');
  const forgotStepSuccess = document.getElementById('forgotStepSuccess');
  const forgotIdentifierForm = document.getElementById('forgotIdentifierForm');
  const forgotIdentifierInput = document.getElementById('forgotIdentifier');
  const forgotIdentifierSubmit = document.getElementById('forgotIdentifierSubmit');
  const forgotAlert = document.getElementById('forgotAlert');
  const forgotOtpAlert = document.getElementById('forgotOtpAlert');
  const forgotOtpForm = document.getElementById('forgotOtpForm');
  const forgotOtpCode = document.getElementById('forgotOtpCode');
  const forgotNewPassword = document.getElementById('forgotNewPassword');
  const forgotConfirmPassword = document.getElementById('forgotConfirmPassword');
  const forgotOtpSubmit = document.getElementById('forgotOtpSubmit');
  const forgotMaskedPhone = document.getElementById('forgotMaskedPhone');
  const forgotResendBtn = document.getElementById('forgotResendBtn');
  const forgotResendTimer = document.getElementById('forgotResendTimer');
  const forgotEditIdentifierBtn = document.getElementById('forgotEditIdentifierBtn');
  const forgotGoToLoginBtn = document.getElementById('forgotGoToLoginBtn');

  const forgotState = {
    identifier: '',
    sessionId: null,
    cooldownSeconds: otpCooldown.parseSeconds(
      forgotFlow.dataset.resendCooldown,
      60
    ),
    timer: otpCooldown.createTimer(forgotResendBtn, forgotResendTimer),
  };

  function toggleForgotVisibility(show) {
    if (loginFlow) {
      loginFlow.classList.toggle('d-none', show);
    }
    forgotFlow.classList.toggle('d-none', !show);
  }

  function setForgotStep(step) {
    const showIdentifier = step === 'identifier';
    const showOtp = step === 'otp';
    const showSuccess = step === 'success';
    forgotStepIdentifier.classList.toggle('d-none', !showIdentifier);
    forgotStepOtp.classList.toggle('d-none', !showOtp);
    forgotStepSuccess.classList.toggle('d-none', !showSuccess);
  }

  function resetForgotFlow() {
    forgotState.timer.stop();
    forgotState.sessionId = null;
    forgotState.identifier = '';
    forgotIdentifierForm && forgotIdentifierForm.reset();
    forgotOtpForm && forgotOtpForm.reset();
    renderAlert(forgotAlert, '');
    renderAlert(forgotOtpAlert, '');
    setForgotStep('identifier');
  }

  async function requestForgotOtp(identifier) {
    const response = await window.apiPost('/auth/password/forgot/init', {
      identifier,
    });
    forgotState.sessionId = response.session_id;
    forgotState.identifier = identifier;
    forgotState.cooldownSeconds = otpCooldown.parseSeconds(
      response.resend_cooldown,
      forgotState.cooldownSeconds
    );
    forgotState.timer.start(forgotState.cooldownSeconds);
    if (forgotMaskedPhone) {
      forgotMaskedPhone.textContent = response.otp_sent_to || maskPhone(identifier);
    }
  }

  function openForgotFlow() {
    toggleForgotVisibility(true);
    resetForgotFlow();
    setForgotStep('identifier');
    if (forgotIdentifierInput) {
      forgotIdentifierInput.focus();
    }
  }

  function closeForgotFlow() {
    toggleForgotVisibility(false);
    resetForgotFlow();
  }

  forgotPasswordLink?.addEventListener('click', () => {
    openForgotFlow();
    if (loginIdentifierField && loginIdentifierField.value && forgotIdentifierInput) {
      forgotIdentifierInput.value = loginIdentifierField.value;
    }
    forgotIdentifierInput && forgotIdentifierInput.focus();
  });

  forgotBackToLoginBtn?.addEventListener('click', () => {
    closeForgotFlow();
    loginIdentifierField && loginIdentifierField.focus();
  });

  forgotGoToLoginBtn?.addEventListener('click', () => {
    closeForgotFlow();
    if (loginIdentifierField && forgotState.identifier) {
      loginIdentifierField.value = forgotState.identifier;
    }
    loginIdentifierField && loginIdentifierField.focus();
  });

  forgotEditIdentifierBtn?.addEventListener('click', () => {
    forgotState.timer.stop();
    forgotState.sessionId = null;
    setForgotStep('identifier');
    renderAlert(forgotOtpAlert, '');
    renderAlert(
      forgotAlert,
      'Update the email or phone number and request a new OTP.',
      'info'
    );
    forgotIdentifierInput && forgotIdentifierInput.focus();
  });

  forgotIdentifierForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    renderAlert(forgotAlert, '');
    const identifier = (forgotIdentifierInput.value || '').trim();
    if (!identifier) {
      renderAlert(forgotAlert, 'Email or phone number is required.', 'warning');
      return;
    }

    forgotIdentifierSubmit.disabled = true;
    const originalLabel = forgotIdentifierSubmit.innerText;
    forgotIdentifierSubmit.innerText = 'Sending OTP…';

    try {
      await requestForgotOtp(identifier);
      setForgotStep('otp');
      renderAlert(
        forgotOtpAlert,
        'Enter the OTP and choose a new password to finish resetting.',
        'info'
      );
      forgotOtpCode && forgotOtpCode.focus();
    } catch (error) {
      const message = handleApiError(
        error,
        'Unable to send OTP. Please check the account details and try again.'
      );
      renderAlert(forgotAlert, message, 'danger');
    } finally {
      forgotIdentifierSubmit.disabled = false;
      forgotIdentifierSubmit.innerText = originalLabel;
    }
  });

  forgotOtpForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    renderAlert(forgotOtpAlert, '');

    const code = (forgotOtpCode.value || '').trim();
    const newPassword = (forgotNewPassword.value || '').trim();
    const confirmPassword = (forgotConfirmPassword.value || '').trim();

    if (!code) {
      renderAlert(forgotOtpAlert, 'OTP is required.', 'warning');
      return;
    }
    if (!newPassword || !confirmPassword) {
      renderAlert(forgotOtpAlert, 'Please enter and confirm the new password.', 'warning');
      return;
    }
    if (newPassword !== confirmPassword) {
      renderAlert(forgotOtpAlert, 'Passwords do not match.', 'warning');
      return;
    }
    if (!forgotState.sessionId) {
      renderAlert(forgotOtpAlert, 'OTP session expired. Please request a new code.', 'danger');
      return;
    }

    forgotOtpSubmit.disabled = true;
    const originalLabel = forgotOtpSubmit.innerText;
    forgotOtpSubmit.innerText = 'Resetting…';

    try {
      await window.apiPost('/auth/password/forgot/complete', {
        session_id: forgotState.sessionId,
        code,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      forgotState.timer.stop();
      setForgotStep('success');
      if (loginIdentifierField && forgotState.identifier) {
        loginIdentifierField.value = forgotState.identifier;
      }
      renderAlert(forgotOtpAlert, '');
    } catch (error) {
      const message = handleApiError(
        error,
        'Unable to reset password. Check the OTP and try again.'
      );
      renderAlert(forgotOtpAlert, message, 'danger');
    } finally {
      forgotOtpSubmit.disabled = false;
      forgotOtpSubmit.innerText = originalLabel;
    }
  });

  forgotResendBtn?.addEventListener('click', async () => {
    if (!forgotState.identifier || forgotResendBtn.disabled) {
      return;
    }
    forgotResendBtn.disabled = true;
    const originalLabel = forgotResendBtn.innerText;
    forgotResendBtn.innerText = 'Resending…';
    renderAlert(forgotOtpAlert, '');
    try {
      await requestForgotOtp(forgotState.identifier);
      renderAlert(forgotOtpAlert, 'We sent a new OTP. Please check your phone.', 'success');
      forgotOtpCode && forgotOtpCode.focus();
    } catch (error) {
      const message = handleApiError(error, 'Unable to resend OTP at this time.');
      renderAlert(forgotOtpAlert, message, 'danger');
      forgotResendBtn.disabled = false;
    } finally {
      forgotResendBtn.innerText = originalLabel;
    }
  });
})();
