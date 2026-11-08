(function () {
    const modal = document.getElementById('session-timeout-modal');
    if (!modal) return;

    const idleTimeoutMs = Number(modal.dataset.idleTimeout) * 1000;
    const warningMs = Number(modal.dataset.warningSeconds) * 1000;
    const portalUrl = modal.dataset.portalUrl;
    const logoutUrl = modal.dataset.logoutUrl;
    const keepaliveUrl = modal.dataset.keepaliveUrl;
    const countdown = document.getElementById('session-timeout-seconds');
    const continueButton = document.getElementById('session-continue-button');
    const errorMessage = document.getElementById('session-timeout-error');
    const csrfToken = modal.querySelector('[name="csrfmiddlewaretoken"]').value;
    let lastActivityAt = Date.now();
    let lastHeartbeatAt = lastActivityAt;
    let idleDeadline = lastActivityAt + idleTimeoutMs;
    let heartbeatFailed = false;
    let heartbeatPromise = null;
    let resumeInFlight = false;
    let inertSiblings = [];
    let trailingHeartbeatTimer;

    function redirectToPortal() {
        window.location.replace(logoutUrl || portalUrl);
    }

    function showModal() {
        if (modal.getAttribute('aria-hidden') === 'false') return;
        inertSiblings = Array.from(document.body.children)
            .filter(function (element) { return element !== modal; })
            .map(function (element) {
                const wasInert = element.inert;
                element.inert = true;
                return {element: element, wasInert: wasInert};
            });
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        continueButton.focus();
        if (heartbeatFailed) {
            errorMessage.textContent = 'No se pudo comprobar la conexión. Pulsa el botón para intentar continuar.';
            errorMessage.hidden = false;
        }
    }

    function hideModal() {
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open');
        inertSiblings.forEach(function (sibling) {
            sibling.element.inert = sibling.wasInert;
        });
        inertSiblings = [];
        errorMessage.hidden = true;
        errorMessage.textContent = '';
    }

    function sendHeartbeat() {
        if (heartbeatPromise) return heartbeatPromise;
        lastHeartbeatAt = Date.now();
        const controller = new AbortController();
        const requestTimeout = window.setTimeout(function () {
            controller.abort();
        }, Math.max(warningMs, 30000));
        heartbeatPromise = (async function () {
            try {
                const response = await fetch(keepaliveUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    cache: 'no-store',
                    signal: controller.signal,
                });
                if (response.redirected) {
                    window.location.replace(response.url);
                    return false;
                }
                if (!response.ok) throw new Error('No se pudo renovar la sesión.');
                const result = await response.json();
                if (!result.ok) throw new Error('No se pudo renovar la sesión.');
                heartbeatFailed = false;
                return true;
            } catch (error) {
                heartbeatFailed = true;
                return false;
            } finally {
                window.clearTimeout(requestTimeout);
                heartbeatPromise = null;
            }
        })();
        return heartbeatPromise;
    }

    async function continueSession() {
        if (Date.now() >= idleDeadline || resumeInFlight) {
            if (Date.now() >= idleDeadline) redirectToPortal();
            return;
        }
        resumeInFlight = true;
        continueButton.disabled = true;
        errorMessage.hidden = true;
        const renewed = await sendHeartbeat();
        if (!renewed) {
            resumeInFlight = false;
            if (Date.now() >= idleDeadline) {
                redirectToPortal();
                return;
            }
            if (modal.getAttribute('aria-hidden') === 'false') {
                errorMessage.textContent = 'No se pudo continuar la sesión. Revisa tu conexión e inténtalo de nuevo.';
                errorMessage.hidden = false;
                continueButton.disabled = false;
            }
            return;
        }
        lastActivityAt = Date.now();
        idleDeadline = lastActivityAt + idleTimeoutMs;
        resumeInFlight = false;
        hideModal();
        continueButton.disabled = false;
    }

    function recordActivity(event) {
        if (event.target instanceof Element && event.target.closest('#session-timeout-modal')) return;
        if (modal.getAttribute('aria-hidden') === 'false') return;
        lastActivityAt = Date.now();
        idleDeadline = lastActivityAt + idleTimeoutMs;
        window.clearTimeout(trailingHeartbeatTimer);
        trailingHeartbeatTimer = window.setTimeout(sendHeartbeat, 1000);
        if (lastActivityAt - lastHeartbeatAt >= 10000) sendHeartbeat();
    }

    function updateTimer() {
        const remainingMs = idleDeadline - Date.now();
        if (remainingMs <= 0) {
            if (resumeInFlight) {
                countdown.textContent = '0';
                return;
            }
            redirectToPortal();
            return;
        }
        if (remainingMs <= warningMs) {
            showModal();
            countdown.textContent = String(Math.ceil(remainingMs / 1000));
        }
    }

    continueButton.addEventListener('click', continueSession);
    ['click', 'keydown', 'pointerdown', 'pointermove', 'scroll', 'touchstart', 'input', 'change'].forEach(function (eventName) {
        document.addEventListener(eventName, recordActivity, {passive: true});
    });
    window.setInterval(updateTimer, 250);
})();
