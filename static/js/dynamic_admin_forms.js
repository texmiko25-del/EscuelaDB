(function () {
    const form = document.querySelector('[data-dynamic-form]');
    if (!form) return;

    const formKind = form.dataset.dynamicForm;
    const configElement = document.getElementById('dynamic-form-data');
    const config = (configElement ? JSON.parse(configElement.textContent || '{}') : {}) || {};
    const fieldWrappers = Array.from(form.querySelectorAll('.form-field'));
    const progressPercent = document.getElementById('progressPercent');
    const progressBarFill = document.getElementById('progressBarFill');
    const modal = document.getElementById('dynamicFormModal');
    const modalTitle = document.getElementById('dynamicFormModalTitle');
    const modalMessage = document.getElementById('dynamicFormModalMessage');
    const closeModalButton = document.getElementById('closeDynamicFormModal');
    const reviewButton = document.getElementById('reviewDynamicFormButton');
    const touchedFields = new WeakSet();
    const gradePercentages = { A: '90.00', B: '80.00', C: '70.00', D: '60.00', E: '50.00', F: '0.00' };

    function fieldOf(wrapper) {
        return wrapper.querySelector('input:not([type="hidden"]), select, textarea');
    }

    function fieldLabel(field) {
        return field.closest('.form-field')?.querySelector('label')?.textContent.trim() || 'Este campo';
    }

    function validateField(field) {
        const value = (field.value || '').trim();
        let message = '';

        if (field.required && !value) {
            message = 'Este campo es obligatorio.';
        } else if (field.dataset.rule === 'periodo' && value && !/^\d{4}-\d{4}$/.test(value)) {
            message = 'Use el formato de período YYYY-YYYY.';
        } else if (field.dataset.rule === 'fecha-no-futura' && value && value > config.hoy) {
            message = 'La fecha de asistencia no puede ser futura.';
        } else if (field.dataset.rule === 'email-split') {
            const email = document.getElementById('id_email')?.value.trim() || '';
            if (!email || !/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$/.test(email)) {
                message = 'Ingrese un correo electrónico válido.';
            }
        } else if (field.dataset.rule === 'cedula' && value) {
            const type = document.getElementById('id_tipo_identificacion')?.value || 'V';
            const digits = value.replace(/^[A-Z]-?/i, '').replace(/\D/g, '');
            if ((type === 'V' && !/^\d{7,8}$/.test(digits)) || (type === 'E' && !/^\d{6,9}$/.test(digits))) {
                message = type === 'V'
                    ? 'La cédula venezolana debe tener 7 u 8 dígitos.'
                    : 'La cédula extranjera debe tener entre 6 y 9 dígitos.';
            }
        } else if (field.dataset.rule === 'optional-password' && value) {
            if (value.length < 8 || !/[A-Z]/.test(value) || !/[a-z]/.test(value) || !/\d/.test(value)) {
                message = 'La contraseña requiere 8 caracteres, mayúscula, minúscula y número.';
            } else if (!document.getElementById('id_confirm_password')?.value) {
                message = 'Confirme la nueva contraseña.';
            }
        } else if (field.dataset.rule === 'confirm-password') {
            const password = document.getElementById('id_password')?.value || '';
            if (password && value !== password) {
                message = 'Las contraseñas no coinciden.';
            } else if (!password && value) {
                message = 'Ingrese una nueva contraseña para confirmarla.';
            }
        } else if (value && !field.checkValidity()) {
            message = field.validationMessage || 'Revise el valor ingresado.';
        }

        if (!message && formKind === 'asistencia' && field.id === 'id_fecha' && value) {
            const studentId = document.getElementById('id_estudiante_cedula').value;
            const duplicate = (config.asistencias || []).find((item) => (
                String(item.estudiante_id) === studentId && item.fecha === value
            ));
            if (duplicate) {
                const studentName = [duplicate.estudiante__nombre, duplicate.estudiante__apellido]
                    .filter(Boolean).join(' ');
                message = 'Ya existe una asistencia para este estudiante en esa fecha'
                    + (studentName ? ': ' + studentName + '.' : '.');
            }
        }

        return message;
    }

    function updateField(wrapper) {
        const field = fieldOf(wrapper);
        if (!field) return { valid: true, required: false, filled: true };

        const required = wrapper.dataset.required === 'true';
        const value = field.type === 'checkbox' ? field.checked : (field.value || '').trim();
        const filled = value !== '' && value !== false;
        const message = validateField(field);
        const valid = !message;
        const badge = wrapper.querySelector('.field-status-badge');
        const error = wrapper.querySelector('.dynamic-field-error');
        const showError = touchedFields.has(field) || wrapper.classList.contains('has-server-error');
        const hasServerError = wrapper.classList.contains('has-server-error');

        wrapper.classList.toggle('is-filled', filled && valid);
        wrapper.classList.toggle('is-empty', required && !filled);
        wrapper.classList.toggle('has-error', hasServerError || (showError && !valid));
        if (badge) {
            badge.textContent = !required && !filled ? 'Opcional' : (valid && filled ? 'Listo' : 'Pendiente');
        }
        if (error) error.textContent = showError ? message : '';
        return { valid, required, filled };
    }

    function updateProgress() {
        const states = fieldWrappers.map(updateField);
        const requiredStates = states.filter((state) => state.required);
        const total = requiredStates.length;
        const completed = requiredStates.filter((state) => state.valid && state.filled).length;
        const percent = total ? Math.round(completed / total * 100) : 100;

        if (progressPercent) progressPercent.textContent = percent + '%';
        if (progressBarFill) progressBarFill.style.width = percent + '%';

        form.querySelectorAll('.form-section').forEach(function (section) {
            const status = section.querySelector('.form-section__status');
            if (!status) return;
            const sectionStates = Array.from(section.querySelectorAll('.form-field'))
                .map((wrapper) => updateField(wrapper))
                .filter((state) => state.required);
            const sectionCompleted = sectionStates.filter((state) => state.valid && state.filled).length;
            const sectionTotal = sectionStates.length;
            const complete = sectionCompleted === sectionTotal;
            status.textContent = complete ? 'Completo' : sectionCompleted + '/' + sectionTotal;
            status.classList.toggle('is-complete', complete);
            status.classList.toggle('is-pending', !complete);
        });

        updateDerivedValues();
    }

    function updateDerivedValues() {
        if (formKind === 'calificacion') {
            const note = document.getElementById('id_nota')?.value || '';
            const preview = document.getElementById('gradePercentagePreview');
            if (preview) {
                preview.textContent = note && gradePercentages[note]
                    ? 'Equivalencia: ' + gradePercentages[note] + '%'
                    : 'Seleccione una letra para ver su equivalencia porcentual.';
            }
        }

        if (formKind === 'asistencia') {
            const student = document.getElementById('id_estudiante_cedula');
            const preview = document.getElementById('attendanceStudentPreview');
            if (student && preview) {
                preview.textContent = student.value
                    ? student.options[student.selectedIndex].text
                    : 'Seleccione un estudiante para revisar sus datos.';
            }
        }
    }

    function openModal(title, message) {
        modalTitle.textContent = title;
        modalMessage.textContent = message;
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        closeModalButton.focus();
    }

    function closeModal() {
        if (modal.contains(document.activeElement)) {
            const returnTarget = reviewButton || form.querySelector('button[type="submit"]');
            returnTarget?.focus();
        }
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
    }

    function validateAll(showSuccess = true) {
        let firstInvalid = null;
        fieldWrappers.forEach(function (wrapper) {
            const field = fieldOf(wrapper);
            if (!field) return;
            touchedFields.add(field);
            const message = validateField(field);
            if (message && !firstInvalid) firstInvalid = field;
        });
        updateProgress();

        if (firstInvalid) {
            openModal('Revisa los datos', fieldLabel(firstInvalid) + ': ' + validateField(firstInvalid));
            firstInvalid.focus();
            return false;
        }

        if (showSuccess) {
            openModal('Datos verificados', 'Los campos obligatorios y sus validaciones están correctos.');
        } else {
            closeModal();
        }
        return true;
    }

    form.querySelectorAll('input, select, textarea').forEach(function (field) {
        ['input', 'change', 'blur'].forEach((eventName) => {
            field.addEventListener(eventName, function () {
                touchedFields.add(field);
                field.closest('.form-field')?.classList.remove('has-server-error');
                updateProgress();
            });
        });
    });

    form.addEventListener('submit', function (event) {
        if (!validateAll(false)) event.preventDefault();
    });
    reviewButton?.addEventListener('click', () => validateAll());
    closeModalButton?.addEventListener('click', closeModal);
    modal?.addEventListener('click', function (event) {
        if (event.target === modal) closeModal();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal?.classList.contains('is-open')) closeModal();
    });

    updateProgress();

    const serverError = form.querySelector('.admin-form-alert');
    if (serverError && serverError.textContent.trim()) {
        openModal('Revisa los datos', serverError.textContent.trim());
    }
})();