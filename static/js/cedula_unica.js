(function () {
    const cedulaField = document.getElementById('id_cedula');
    const form = cedulaField?.form;
    if (!cedulaField || !form) return;

    const tipoField = document.getElementById('id_tipo_identificacion');
    const scope = form.id === 'docenteForm' ? '&scope=docente' : '';
    const originalCedula = (cedulaField.value || '').trim().toUpperCase();
    const warning = document.createElement('small');
    warning.className = 'cedula-unique-warning';
    warning.setAttribute('role', 'alert');
    cedulaField.insertAdjacentElement('afterend', warning);

    let timer;
    let requestNumber = 0;

    function normalizedCedula() {
        let value = (cedulaField.value || '').trim().toUpperCase().replace(/\s/g, '');
        if (!value || value.startsWith('V-') || value.startsWith('E-')) return value;
        const tipo = tipoField?.value || 'V';
        return /^\d+$/.test(value) ? tipo + '-' + value : value;
    }

    function normalizeInput() {
        if (!tipoField) return;
        const value = (cedulaField.value || '').trim().toUpperCase().replace(/\s/g, '');
        if (/^\d+$/.test(value)) cedulaField.value = tipoField.value + '-' + value;
    }

    async function checkCedula() {
        const cedula = normalizedCedula();
        if (!cedula || !/^(?:V-\d{7,8}|E-\d{6,9})$/.test(cedula)) return;
        if (cedula === originalCedula) {
            warning.textContent = 'Cédula propia del registro.';
            warning.classList.remove('is-visible');
            cedulaField.dataset.cedulaOcupada = 'false';
            return;
        }
        const currentRequest = ++requestNumber;
        const response = await fetch('/admin-panel/validar-cedula/?cedula=' + encodeURIComponent(cedula) + scope);
        if (currentRequest !== requestNumber || !response.ok) return;
        const result = await response.json();
        warning.textContent = result.mensaje || '';
        warning.classList.toggle('is-visible', Boolean(result.ocupada));
        cedulaField.dataset.cedulaOcupada = result.ocupada ? 'true' : 'false';
    }

    function scheduleCheck() {
        clearTimeout(timer);
        cedulaField.dataset.cedulaOcupada = 'false';
        warning.classList.remove('is-visible');
        timer = setTimeout(checkCedula, 350);
    }

    cedulaField.addEventListener('input', () => {
        normalizeInput();
        scheduleCheck();
    });
    tipoField?.addEventListener('change', () => {
        normalizeInput();
        scheduleCheck();
    });
    cedulaField.addEventListener('blur', checkCedula);
    form.addEventListener('submit', function (event) {
        if (cedulaField.dataset.cedulaOcupada === 'true') {
            event.preventDefault();
            warning.classList.add('is-visible');
            cedulaField.focus();
        }
    });

    checkCedula();
})();
