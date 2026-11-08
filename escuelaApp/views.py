import hashlib
from html import escape
import logging
import secrets
import string
import time
from datetime import date
from functools import partial
from smtplib import SMTPException

from django.contrib import messages
from django.contrib.messages import get_messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import active_staff_required, role_required
from .forms import AdminConfiguracionForm, AdminCrearUsuarioForm, AdminEditarUsuarioForm, AdminSobreNosotrosForm, ConfirmarAccesoCuentaForm, CuentaPropiaForm, EstudianteForm, DocenteForm, DocenteEstudiantesForm, RepresentanteForm, EmpleadoForm, AsignacionForm, AsignacionNotaForm, HorarioForm
from .forms import HORARIO_JORNADA_INICIO, HORARIO_JORNADA_FIN
from .forms_login import LoginForm, RecoveryCodeForm, RecoveryEmailForm, RecoveryPasswordForm
from .models import AsistenciaPersonal, ConfiguracionDashboard, Estudiante, Docente, DocenteEstudiante, Representante, Empleado, Asignacion, Horario, SobreNosotros, Asistencia, SolicitudMatricula
from .registro_academico import RegistroAcademico
from .models import ContactoMensaje
from .estudiante_utils import ordenar_estudiantes
from .report_delivery import enviar_reporte_a_directora
from .telegram import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    send_telegram_message,
)
from .whatsapp import (
    WhatsAppConfigurationError,
    WhatsAppDeliveryError,
    send_contact_whatsapp,
)
from django.views.decorators.cache import never_cache

staff_member_required = partial(django_staff_member_required, login_url='login')
LOGIN_MAX_ATTEMPTS = 3
LOGIN_LOCK_SECONDS = 30
MI_CUENTA_SESSION_KEY = 'mi_cuenta_autorizada'
logger = logging.getLogger(__name__)
PASSWORD_RESET_SESSION_KEYS = (
    'password_reset_stage',
    'password_reset_email',
    'password_reset_user_id',
    'password_reset_code_hash',
    'password_reset_code_expires_at',
    'password_reset_code_attempts',
    'password_reset_verified_expires_at',
)


def _restringir_cargo_directora(form, user):
    if getattr(getattr(user, 'empleado', None), 'cargo', None) == 'SUBDIRECTORA':
        form.fields['cargo'].choices = [
            choice for choice in form.fields['cargo'].choices
            if choice[0] != 'DIRECTORA'
        ]


def home_view(request):
    # Mostrar el portal público como página de inicio
    try:
        from .views_portal import portal_home
        return portal_home(request)
    except Exception:
        # Fallback: renderizar la plantilla home original si algo falla
        return render(request, 'escuelaApp/home.html')


def _percentage_of_total(total, value):
    return round(value * 100 / total) if total else 0


@never_cache
def login_view(request):
    blocked_tab = request.GET.get('blocked') == '1'
    next_url = (
        request.POST.get('next', '').strip()
        if request.method == 'POST'
        else request.GET.get('next', '').strip()
    )
    if next_url and not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = ''
    timeout_message = ''
    if request.user.is_authenticated and not blocked_tab:
        if request.user.is_staff:
            return redirect('admin_panel')
        return redirect('home')

    session_message = request.GET.get('session_message', '')
    if not session_message:
        session_message = request.session.pop('session_message', '')
    if session_message:
        messages.warning(request, session_message)
        timeout_message = session_message

    for message in get_messages(request):
        text = str(message).lower()
        if 'inactividad' in text or 'cerró automáticamente' in text:
            timeout_message = str(message)
            break

    lockout_seconds = 0
    lockout_until = 0
    session_lock_until = request.session.get('login_lock_until', 0)
    if session_lock_until:
        lockout_seconds = max(0, int(session_lock_until - time.time() + 0.999))
        if lockout_seconds:
            lockout_until = int(session_lock_until * 1000)
        else:
            request.session.pop('login_lock_until', None)
            request.session.pop('login_failed_attempts', None)

    if request.method == 'POST':
        if lockout_seconds:
            form = LoginForm(request.POST)
            return render(request, 'escuelaApp/login.html', {
                'form': form,
                'next': request.POST.get('next', '').strip(),
                'blocked_tab': blocked_tab,
                'timeout_message': timeout_message,
                'lockout_seconds': lockout_seconds,
                'lockout_until': lockout_until,
            })

        submitted_username = request.POST.get('username', '').strip()
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            if user.is_staff:
                has_active_session = any(
                    session.get_decoded().get('_auth_user_id') == str(user.pk)
                    for session in Session.objects.filter(expire_date__gt=timezone.now())
                )
                if has_active_session:
                    form.add_error(None, 'Esta cuenta ya tiene una sesión activa. Cierre esa sesión antes de iniciar otra.')
                    return render(request, 'escuelaApp/login.html', {'form': form, 'next': next_url, 'blocked_tab': blocked_tab})

            request.session.pop('login_lock_until', None)
            request.session.pop('login_failed_attempts', None)
            login(request, user)
            request.session['staff_session_token'] = hashlib.sha256(f"{user.pk}:{request.session.session_key}:{user.last_login or ''}:{time.time()}".encode('utf-8')).hexdigest()
            request.session['last_staff_activity'] = timezone.now().timestamp()
            request.session.set_expiry(
                settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
            )
            request.session.modified = True
            if next_url:
                return redirect(next_url)
            return redirect('admin_panel' if user.is_staff else 'home')
        if submitted_username and request.POST.get('password'):
            attempts = request.session.get('login_failed_attempts', 0) + 1
            if attempts >= LOGIN_MAX_ATTEMPTS:
                lock_until = time.time() + LOGIN_LOCK_SECONDS
                lockout_seconds = max(0, int(lock_until - time.time() + 0.999))
                lockout_until = int(lock_until * 1000)
                request.session['login_lock_until'] = lock_until
                request.session.pop('login_failed_attempts', None)
                request.session.modified = True
            else:
                request.session['login_failed_attempts'] = attempts
                request.session.modified = True
        messages.error(request, 'Usuario o contraseña incorrectos.')
    else:
        form = LoginForm()

    return render(request, 'escuelaApp/login.html', {
        'form': form,
        'next': next_url,
        'blocked_tab': blocked_tab,
        'timeout_message': timeout_message,
        'lockout_seconds': lockout_seconds,
        'lockout_until': lockout_until,
    })


def _clear_password_reset_session(request):
    for key in PASSWORD_RESET_SESSION_KEYS:
        request.session.pop(key, None)
    request.session.set_expiry(None)


def _password_reset_code_hash(request, code):
    return hashlib.sha256(f'{request.session.session_key}:{code}'.encode('utf-8')).hexdigest()


def _new_password_reset_code():
    characters = [secrets.choice(string.ascii_uppercase), secrets.choice(string.digits)]
    alphabet = string.ascii_uppercase + string.digits
    characters.extend(secrets.choice(alphabet) for _ in range(6))
    secrets.SystemRandom().shuffle(characters)
    return ''.join(characters)


def _send_password_reset_code(email, code):
    send_mail(
        'Código para restablecer tu contraseña',
        f'Tu código de verificación es {code}. Tiene una validez de 60 segundos. Si no solicitaste este cambio, ignora este mensaje.',
        None,
        [email],
        fail_silently=False,
    )


@never_cache
def forgot_password_view(request):
    if request.method == 'GET':
        _clear_password_reset_session(request)
        return render(request, 'escuelaApp/forgot_password.html', {
            'stage': 'email',
            'email_form': RecoveryEmailForm(),
        })

    stage = request.session.get('password_reset_stage', 'email')
    action = request.POST.get('action')
    now = time.time()

    if stage == 'email' and action == 'send_code':
        email_form = RecoveryEmailForm(request.POST)
        if email_form.is_valid():
            email = email_form.cleaned_data['email']
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if not request.session.session_key:
                request.session.create()
            code = _new_password_reset_code()
            request.session['password_reset_stage'] = 'code'
            request.session['password_reset_email'] = email
            request.session['password_reset_user_id'] = user.pk if user else None
            request.session['password_reset_code_hash'] = _password_reset_code_hash(request, code)
            request.session['password_reset_code_attempts'] = 0
            request.session.set_expiry(180)
            if user:
                try:
                    _send_password_reset_code(email, code)
                except Exception:
                    _clear_password_reset_session(request)
                    return render(request, 'escuelaApp/forgot_password.html', {
                        'stage': 'email',
                        'email_form': email_form,
                        'email_error': 'No se pudo enviar el correo. Verifica la configuración e inténtalo de nuevo.',
                    })
            expires_at = time.time() + 60
            request.session['password_reset_code_expires_at'] = expires_at
            return render(request, 'escuelaApp/forgot_password.html', {
                'stage': 'code',
                'code_form': RecoveryCodeForm(),
                'email_hint': email,
                'code_expires_at_ms': int(expires_at * 1000),
                'notice': 'Si el correo corresponde a una cuenta activa, recibirás un código de verificación.',
            })
        return render(request, 'escuelaApp/forgot_password.html', {
            'stage': 'email',
            'email_form': email_form,
        })

    if stage == 'code':
        email = request.session.get('password_reset_email', '')
        expires_at = request.session.get('password_reset_code_expires_at', 0)
        expired = now >= expires_at

        if action == 'resend_code' and expired:
            user_id = request.session.get('password_reset_user_id')
            user = User.objects.filter(
                pk=user_id,
                email__iexact=email,
                is_active=True,
            ).first() if user_id else None
            code = _new_password_reset_code()
            if user:
                try:
                    _send_password_reset_code(email, code)
                except Exception:
                    return render(request, 'escuelaApp/forgot_password.html', {
                        'stage': 'code',
                        'code_form': RecoveryCodeForm(),
                        'email_hint': email,
                        'code_expires_at_ms': int(now * 1000),
                        'code_expired': True,
                        'email_error': 'No se pudo reenviar el correo. Inténtalo de nuevo.',
                    })
            expires_at = time.time() + 60
            request.session['password_reset_code_hash'] = _password_reset_code_hash(request, code)
            request.session['password_reset_code_expires_at'] = expires_at
            request.session['password_reset_code_attempts'] = 0
            return render(request, 'escuelaApp/forgot_password.html', {
                'stage': 'code',
                'code_form': RecoveryCodeForm(),
                'email_hint': email,
                'code_expires_at_ms': int(expires_at * 1000),
                'notice': 'Se envió un nuevo código si el correo pertenece a una cuenta activa.',
            })

        if action == 'verify_code':
            if expired:
                return render(request, 'escuelaApp/forgot_password.html', {
                    'stage': 'code',
                    'code_form': RecoveryCodeForm(),
                    'email_hint': email,
                    'code_expires_at_ms': int(expires_at * 1000),
                    'code_expired': True,
                    'email_error': 'El código venció. Puedes solicitar uno nuevo.',
                })
            code_form = RecoveryCodeForm(request.POST)
            if code_form.is_valid():
                submitted_hash = _password_reset_code_hash(request, code_form.cleaned_data['code'])
                saved_hash = request.session.get('password_reset_code_hash', '')
                user_id = request.session.get('password_reset_user_id')
                user = User.objects.filter(
                    pk=user_id,
                    email__iexact=email,
                    is_active=True,
                ).first() if user_id else None
                if user and secrets.compare_digest(submitted_hash, saved_hash):
                    verified_expires_at = now + 60
                    request.session['password_reset_stage'] = 'password'
                    request.session['password_reset_verified_expires_at'] = verified_expires_at
                    request.session.pop('password_reset_code_hash', None)
                    return render(request, 'escuelaApp/forgot_password.html', {
                        'stage': 'password',
                        'password_form': RecoveryPasswordForm(),
                        'password_expires_at_ms': int(verified_expires_at * 1000),
                        'email_hint': email,
                    })
                attempts = request.session.get('password_reset_code_attempts', 0) + 1
                request.session['password_reset_code_attempts'] = attempts
                if attempts >= 5:
                    _clear_password_reset_session(request)
                    return render(request, 'escuelaApp/forgot_password.html', {
                        'stage': 'email',
                        'email_form': RecoveryEmailForm(),
                        'email_error': 'Se alcanzó el máximo de intentos. Comienza de nuevo.',
                    })
                code_form.add_error('code', 'El código no es correcto.')
            return render(request, 'escuelaApp/forgot_password.html', {
                'stage': 'code',
                'code_form': code_form,
                'email_hint': email,
                'code_expires_at_ms': int(expires_at * 1000),
            })

        return render(request, 'escuelaApp/forgot_password.html', {
            'stage': 'code',
            'code_form': RecoveryCodeForm(),
            'email_hint': email,
            'code_expires_at_ms': int(expires_at * 1000),
            'code_expired': expired,
        })

    if stage == 'password':
        email = request.session.get('password_reset_email', '')
        expires_at = request.session.get('password_reset_verified_expires_at', 0)
        user_id = request.session.get('password_reset_user_id')
        user = User.objects.filter(
            pk=user_id,
            email__iexact=email,
            is_active=True,
        ).first() if user_id else None
        if not user or now >= expires_at:
            _clear_password_reset_session(request)
            return render(request, 'escuelaApp/forgot_password.html', {
                'stage': 'email',
                'email_form': RecoveryEmailForm(),
                'email_error': 'El tiempo para cambiar la contraseña terminó. Ingresa tu correo para comenzar de nuevo.',
            })

        if action == 'reset_password':
            password_form = RecoveryPasswordForm(request.POST)
            if password_form.is_valid():
                if time.time() >= expires_at:
                    _clear_password_reset_session(request)
                    return render(request, 'escuelaApp/forgot_password.html', {
                        'stage': 'email',
                        'email_form': RecoveryEmailForm(),
                        'email_error': 'El tiempo para cambiar la contraseña terminó. Ingresa tu correo para comenzar de nuevo.',
                    })
                user.set_password(password_form.cleaned_data['password'])
                user.save(update_fields=['password'])
                _clear_password_reset_session(request)
                return render(request, 'escuelaApp/forgot_password.html', {'stage': 'done'})
        else:
            password_form = RecoveryPasswordForm()

        return render(request, 'escuelaApp/forgot_password.html', {
            'stage': 'password',
            'password_form': password_form,
            'password_expires_at_ms': int(expires_at * 1000),
            'email_hint': email,
        })

    _clear_password_reset_session(request)
    return render(request, 'escuelaApp/forgot_password.html', {
        'stage': 'email',
        'email_form': RecoveryEmailForm(),
    })


def logout_view(request):
    logout(request)
    response = redirect('portal_home')
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


def not_found_view(request, *args, **kwargs):
    return render(request, '404.html', status=404)


@active_staff_required
@staff_member_required
def admin_panel_view(request):
    empleado = getattr(request.user, 'empleado', None)
    user_cargo = empleado.cargo if empleado else None
    if user_cargo in ['DOCENTE', 'PROFESOR']:
        return redirect('docente_mis_estudiantes')

    usuarios = User.objects.all().order_by('username')
    admin_count = usuarios.filter(is_staff=True).count()
    if not request.user.is_superuser:
        usuarios = usuarios.filter(pk=request.user.pk)
    total_estudiantes = Estudiante.objects.count()
    total_docentes = Docente.objects.count()
    total_representantes = Representante.objects.count()
    total_empleados = Empleado.objects.count()
    total_asignaciones = Asignacion.objects.count()
    total_registros_academicos = RegistroAcademico.objects.count()
    total_horarios = Horario.objects.count()
    total_mensajes = ContactoMensaje.objects.count()
    total_asistencias = Asistencia.objects.count()
    config, _ = ConfiguracionDashboard.objects.get_or_create(pk=1)
    user_cargo_display = empleado.get_cargo_display() if empleado else 'Director/a'
    is_directora = user_cargo == 'DIRECTORA' or request.user.is_superuser
    is_subdirectora = user_cargo == 'SUBDIRECTORA'
    is_coordinador = user_cargo == 'COORD'
    is_docente = user_cargo in ['DOCENTE', 'PROFESOR']
    solicitudes_matricula_pendientes = 0
    asistencias_personal_mes = 0
    if is_subdirectora:
        hoy = timezone.localdate()
        solicitudes_matricula_pendientes = SolicitudMatricula.objects.filter(estado='PENDIENTE').count()
        asistencias_personal_mes = AsistenciaPersonal.objects.filter(
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        ).count()

    return render(request, 'escuelaApp/admin_custom/panel_principal.html', {
        'usuarios': usuarios,
        'admin_count': admin_count,
        'total_estudiantes': total_estudiantes,
        'total_docentes': total_docentes,
        'total_representantes': total_representantes,
        'total_empleados': total_empleados,
        'total_asignaciones': total_asignaciones,
        'total_registros_academicos': total_registros_academicos,
        'total_horarios': total_horarios,
        'total_mensajes': total_mensajes,
        'total_asistencias': total_asistencias,
        'config': config,
        'user_cargo': user_cargo,
        'user_cargo_display': user_cargo_display,
        'is_directora': is_directora,
        'is_subdirectora': is_subdirectora,
        'is_coordinador': is_coordinador,
        'is_docente': is_docente,
        'solicitudes_matricula_pendientes': solicitudes_matricula_pendientes,
        'asistencias_personal_mes': asistencias_personal_mes,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def dashboard_pedagogico(request):
    porcentajes_por_nota = {
        'A': 90,
        'B': 80,
        'C': 70,
        'D': 60,
        'E': 50,
        'F': 0,
    }
    grados_disponibles = EstudianteForm.GRADOS
    periodos_disponibles = list(
        RegistroAcademico.objects.order_by('periodo')
        .values_list('periodo', flat=True)
        .distinct()
    )
    periodo_solicitado = request.GET.get('periodo', '')
    periodo_seleccionado = (
        periodo_solicitado if periodo_solicitado in periodos_disponibles
        else (periodos_disponibles[-1] if periodos_disponibles else '')
    )
    codigos_grado = {codigo for codigo, _ in grados_disponibles}
    grado_solicitado = request.GET.get('grado', '')
    grado_seleccionado = grado_solicitado if grado_solicitado in codigos_grado else ''

    estudiantes = Estudiante.objects.all()
    registros = RegistroAcademico.objects.select_related(
        'estudiante', 'docente', 'asignacion', 'asignacion__docente'
    )
    asignaciones = Asignacion.objects.select_related('estudiante', 'docente')
    if grado_seleccionado:
        estudiantes = estudiantes.filter(grado=grado_seleccionado)
        registros = registros.filter(estudiante__grado=grado_seleccionado)
        asignaciones = asignaciones.filter(estudiante__grado=grado_seleccionado)
    if periodo_seleccionado:
        registros = registros.filter(periodo=periodo_seleccionado)
        asignaciones = asignaciones.filter(periodo=periodo_seleccionado)

    registros = list(registros)
    evaluaciones_por_estudiante = {}
    registros_inconsistentes = []
    registros_por_estudiante = {}
    evaluaciones = []
    for registro in registros:
        registros_por_estudiante.setdefault(registro.estudiante_id, []).append(registro)
        porcentaje_esperado = porcentajes_por_nota.get(registro.nota)
        porcentaje_actual = registro.porcentaje
        porcentaje = porcentaje_actual if porcentaje_actual is not None else porcentaje_esperado
        if porcentaje is not None:
            evaluaciones.append(float(porcentaje))
            evaluaciones_por_estudiante.setdefault(registro.estudiante_id, []).append(float(porcentaje))
        if porcentaje_esperado is not None and porcentaje_actual != porcentaje_esperado:
            registros_inconsistentes.append({
                'estudiante': registro.estudiante,
                'grado': dict(grados_disponibles).get(registro.estudiante.grado, registro.estudiante.grado),
                'area': registro.area,
                'docente': registro.docente,
                'nota': registro.nota,
                'porcentaje_actual': porcentaje_actual,
                'porcentaje_esperado': porcentaje_esperado,
                'fecha': registro.fecha_registro,
            })

    alumnos_en_riesgo = []
    for alumno_id, alumno_registros in registros_por_estudiante.items():
        notas = evaluaciones_por_estudiante.get(alumno_id, [])
        promedio = sum(notas) / len(notas) if notas else None
        estados_riesgo = [registro.estado for registro in alumno_registros if registro.estado in ('Reprobado', 'Recuperación')]
        if (promedio is not None and promedio <= 60) or estados_riesgo:
            estudiante = alumno_registros[0].estudiante
            alumnos_en_riesgo.append({
                'estudiante': estudiante,
                'grado': dict(grados_disponibles).get(estudiante.grado, estudiante.grado),
                'promedio': promedio,
                'evaluaciones': len(notas),
                'motivo': ', '.join(estados_riesgo) if estados_riesgo else 'Promedio igual o inferior a 60%',
            })
    alumnos_en_riesgo_ids = {alerta['estudiante'].pk for alerta in alumnos_en_riesgo}

    resumen_por_grado = []
    grados_a_resumir = [grado_seleccionado] if grado_seleccionado else [codigo for codigo, _ in grados_disponibles]
    etiquetas_grado = dict(grados_disponibles)
    for codigo in grados_a_resumir:
        alumnos_grado = estudiantes.filter(grado=codigo)
        ids_alumnos = list(alumnos_grado.values_list('id', flat=True))
        notas_grado = [nota for alumno_id in ids_alumnos for nota in evaluaciones_por_estudiante.get(alumno_id, [])]
        riesgo_grado = sum(
            1 for alumno_id in ids_alumnos if alumno_id in alumnos_en_riesgo_ids
        )
        resumen_por_grado.append({
            'nombre': etiquetas_grado[codigo],
            'estudiantes': len(ids_alumnos),
            'promedio': sum(notas_grado) / len(notas_grado) if notas_grado else None,
            'en_riesgo': riesgo_grado,
            'evaluaciones': len(notas_grado),
        })

    asignaciones_registradas_ids = {registro.asignacion_id for registro in registros if registro.asignacion_id}
    asignaciones_registradas = len(asignaciones_registradas_ids)
    asignaciones_total = asignaciones.count()
    asignaciones_pendientes = list(
        asignaciones.exclude(pk__in=asignaciones_registradas_ids)
    ) if periodo_seleccionado else []

    return render(request, 'escuelaApp/admin_custom/dashboard_pedagogico.html', {
        'periodos_disponibles': periodos_disponibles,
        'periodo_seleccionado': periodo_seleccionado,
        'grados_disponibles': grados_disponibles,
        'grado_seleccionado': grado_seleccionado,
        'promedio_general': sum(evaluaciones) / len(evaluaciones) if evaluaciones else None,
        'total_evaluaciones': len(evaluaciones),
        'total_alumnos_en_riesgo': len(alumnos_en_riesgo),
        'alumnos_en_riesgo': alumnos_en_riesgo,
        'avance_registro': round(asignaciones_registradas * 100 / asignaciones_total) if asignaciones_total else 0,
        'asignaciones_registradas': asignaciones_registradas,
        'asignaciones_total': asignaciones_total,
        'total_inconsistentes': len(registros_inconsistentes),
        'registros_inconsistentes': registros_inconsistentes,
        'resumen_por_grado': resumen_por_grado,
        'asignaciones_pendientes': asignaciones_pendientes,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA')
def sistema_administrativo_view(request):
    # Vista de demostración que muestra la plantilla administrativa principal
    return render(request, 'escuelaApp/sistema_administrativo.html')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def validar_cedula_view(request):
    cedula = (request.GET.get('cedula') or '').strip().upper().replace(' ', '')
    tipo = (request.GET.get('tipo') or 'V').strip().upper()
    if cedula and not cedula.startswith(('V-', 'E-')) and cedula.isdigit():
        cedula = f'{tipo}-{cedula}'

    if not cedula:
        return JsonResponse({'valida': False, 'ocupada': False, 'mensaje': ''})

    coincidencias = []
    if request.GET.get('scope') == 'docente':
        if Docente.objects.filter(cedula__iexact=cedula).exists():
            coincidencias.append('otro docente')
    else:
        if Representante.objects.filter(cedula__iexact=cedula).exists():
            coincidencias.append('un representante')
        if Docente.objects.filter(cedula__iexact=cedula).exists():
            coincidencias.append('un docente')
        if Empleado.objects.filter(cedula__iexact=cedula).exists() or User.objects.filter(username__iexact=cedula).exists():
            coincidencias.append('una cuenta o empleado')
        if Estudiante.objects.filter(cedula__iexact=cedula).exists():
            coincidencias.append('un estudiante')

    if coincidencias:
        return JsonResponse({
            'valida': True,
            'ocupada': True,
            'mensaje': f'Esta cédula ya está registrada en {" y ".join(coincidencias)}.',
        })
    return JsonResponse({'valida': True, 'ocupada': False, 'mensaje': 'Cédula disponible.'})


def _registro_por_cedula_o_id(queryset, cedula=None, registro_id=None):
    if registro_id is not None:
        return get_object_or_404(queryset, pk=registro_id)
    return get_object_or_404(queryset, cedula=cedula)


def _datos_estudiantes_docente(docente):
    horarios = list(
        Horario.objects.filter(docente=docente).order_by('ano', 'dia', 'hora_inicio')
    )
    grados_estudiantes = {
        '1ANO': '1RO',
        '2ANO': '2DO',
        '3ANO': '3RO',
        '4ANO': '4TO',
        '5ANO': '5TO',
        '6ANO': '6TO',
    }
    horarios_por_grado = {}
    for horario in horarios:
        horarios_por_grado.setdefault(horario.ano, []).append(horario)

    grados_asignados = list(horarios_por_grado)
    grados_validos = [grados_estudiantes.get(grado, grado) for grado in grados_asignados]
    grados_programados = grados_validos
    alcance_horario = Q(pk__in=[])
    grupos_asignados = set(
        docente.estudiantes_asignados.values_list('grado', 'seccion')
    )
    for grado in grados_programados:
        alcance_grado = Q(grado=grado)
        for grado_asignado, seccion_asignada in grupos_asignados:
            if grado_asignado == grado:
                alcance_grado &= ~Q(grado=grado, seccion=seccion_asignada)
        alcance_horario |= alcance_grado
    estudiantes = list(ordenar_estudiantes(
        (Estudiante.objects.filter(alcance_horario) | docente.estudiantes_asignados.all())
        .distinct()
        .select_related('representante')
    ))
    grado_horario_por_estudiante = {
        grado_estudiante: grado_horario
        for grado_horario, grado_estudiante in grados_estudiantes.items()
    }
    for estudiante in estudiantes:
        grado_horario = grado_horario_por_estudiante.get(estudiante.grado, estudiante.grado)
        horarios_por_grado.setdefault(grado_horario, [])

    materias_asignadas_por_grado = {}
    asignaciones = Asignacion.objects.filter(
        docente__cedula__iexact=docente.cedula
    ).select_related('estudiante').order_by('estudiante__grado', 'area')
    for asignacion in asignaciones:
        estudiante = asignacion.estudiante
        grado = grado_horario_por_estudiante.get(estudiante.grado, estudiante.grado)
        if all(estudiante.pk != existente.pk for existente in estudiantes):
            estudiantes.append(estudiante)
        if grado not in horarios_por_grado:
            horarios_por_grado[grado] = []
        materias_asignadas_por_grado.setdefault(grado, []).append(asignacion.area)

    estudiantes_por_grupo = {}
    for estudiante in estudiantes:
        grado = grado_horario_por_estudiante.get(estudiante.grado, estudiante.grado)
        horarios_por_grado.setdefault(grado, [])
        estudiantes_por_grupo.setdefault((grado, estudiante.seccion), []).append(estudiante)

    grupos_clave = set(estudiantes_por_grupo)
    for grado in horarios_por_grado:
        if not any(grado_estudiante == grado for grado_estudiante, _ in grupos_clave):
            grupos_clave.add((grado, ''))

    grupos_grado = []
    orden_grados = {
        codigo: indice for indice, (codigo, _) in enumerate(EstudianteForm.GRADOS)
    }
    for grado, seccion in sorted(
        grupos_clave,
        key=lambda clave: (
            orden_grados.get(
                next(
                    (codigo for codigo, grado_horario in grado_horario_por_estudiante.items()
                     if grado_horario == clave[0]),
                    clave[0],
                ),
                len(orden_grados),
            ),
            clave[1],
        ),
    ):
        horarios_grado = horarios_por_grado.get(grado, [])
        codigo_grado = next(
            (codigo for codigo, codigo_horario in grado_horario_por_estudiante.items()
             if codigo_horario == grado),
            grado,
        )
        nombre_grado = (
            horarios_grado[0].get_ano_display()
            if horarios_grado
            else dict(EstudianteForm.GRADOS).get(codigo_grado, codigo_grado)
        )
        grupos_grado.append({
            'nombre': f'{nombre_grado} - Sección {seccion}' if seccion else nombre_grado,
            'materias': list(dict.fromkeys(
                [horario.materia for horario in horarios_grado]
                + materias_asignadas_por_grado.get(grado, [])
            )),
            'estudiantes': estudiantes_por_grupo.get((grado, seccion), []),
        })

    return horarios, grupos_grado


@active_staff_required
@staff_member_required
@role_required('DOCENTE', 'PROFESOR')
def docente_mis_estudiantes_view(request):
    empleado = getattr(request.user, 'empleado', None)
    if not empleado or empleado.cargo not in ['DOCENTE', 'PROFESOR']:
        messages.error(request, 'Esta vista solo está disponible para docentes.')
        return redirect('admin_panel')

    docente = Docente.objects.filter(cedula__iexact=empleado.cedula).first()
    if not docente:
        messages.error(request, 'No se encontró el docente asociado a tu cuenta.')
        return redirect('admin_panel')

    horarios, grupos_grado = _datos_estudiantes_docente(docente)
    return render(request, 'escuelaApp/admin_custom/mis_estudiantes_docente.html', {
        'docente': docente,
        'horarios': horarios,
        'grupos_grado': grupos_grado,
        'total_estudiantes': sum(len(grupo['estudiantes']) for grupo in grupos_grado),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_docente_estudiantes_view(request, cedula=None, docente_id=None):
    docente = _registro_por_cedula_o_id(Docente.objects.all(), cedula, docente_id)
    horarios, grupos_grado = _datos_estudiantes_docente(docente)
    return render(request, 'escuelaApp/admin_custom/mis_estudiantes_docente.html', {
        'docente': docente,
        'horarios': horarios,
        'grupos_grado': grupos_grado,
        'total_estudiantes': sum(len(grupo['estudiantes']) for grupo in grupos_grado),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_asignar_estudiantes_docente(request, cedula=None, docente_id=None):
    docente = _registro_por_cedula_o_id(Docente.objects.all(), cedula, docente_id)
    grados = EstudianteForm.GRADOS
    grado = request.POST.get('grado') if request.method == 'POST' else request.GET.get('grado')
    if not grado:
        grado = grados[0][0]
    seccion = (
        request.POST.get('seccion', '')
        if request.method == 'POST'
        else request.GET.get('seccion', '')
    )
    form_data = request.POST if request.method == 'POST' else None
    form = DocenteEstudiantesForm(
        form_data,
        docente=docente,
        initial={'grado': grado, 'seccion': seccion},
    )
    if request.method == 'POST' and form.is_valid():
        asignar_grupo_completo = request.POST.get('asignar_grupo_completo') == '1'
        estudiantes = (
            form.fields['estudiantes'].queryset
            if asignar_grupo_completo
            else form.cleaned_data['estudiantes']
        )
        if not estudiantes:
            form.add_error(None, 'No hay estudiantes en el grado y sección seleccionados.')
        else:
            with transaction.atomic():
                DocenteEstudiante.objects.filter(
                    docente=docente,
                    estudiante__grado=form.cleaned_data['grado'],
                    estudiante__seccion=form.cleaned_data['seccion'],
                ).delete()
                DocenteEstudiante.objects.bulk_create([
                    DocenteEstudiante(docente=docente, estudiante=estudiante)
                    for estudiante in estudiantes
                ])
            messages.success(
                request,
                (
                    f'Todo el grupo fue asignado correctamente a {docente.nombre} {docente.apellido}.'
                    if asignar_grupo_completo
                    else f'Estudiantes asignados correctamente a {docente.nombre} {docente.apellido}.'
                ),
            )
            return redirect(
                f'{request.path}?grado={form.cleaned_data["grado"]}'
                f'&seccion={form.cleaned_data["seccion"]}'
            )

    return render(request, 'escuelaApp/admin_custom/asignar_estudiantes_docente.html', {
        'docente': docente,
        'form': form,
        'grado_actual': grado,
        'seccion_actual': seccion,
        'grados': grados,
        'hay_estudiantes': form.fields['estudiantes'].queryset.exists(),
        'total_estudiantes_grupo': form.fields['estudiantes'].queryset.count(),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE')
def admin_estudiantes_view(request):
    query = request.GET.get('q', '').strip()
    estudiantes = ordenar_estudiantes(
        Estudiante.objects.select_related('representante').all()
    )
    total_registrados = estudiantes.count()
    if query:
        estudiantes = estudiantes.filter(
            Q(nombre__icontains=query) |
            Q(apellido__icontains=query) |
            Q(cedula__icontains=query) |
            Q(grado__icontains=query) |
            Q(seccion__icontains=query)
        )
    total_en_lista = estudiantes.count()
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'total': total_en_lista,
            'estudiantes': [
                {
                    'nombre': f'{estudiante.nombre} {estudiante.apellido}',
                    'cedula': estudiante.cedula or '',
                    'matricula': estudiante.matricula or 'No asignada',
                    'grado_seccion': (
                        f'{estudiante.grado or ""} - '
                        f'{estudiante.seccion or "Sin sección"}'
                    ),
                    'representante': (
                        str(estudiante.representante)
                        if estudiante.representante else 'Sin representante'
                    ),
                }
                for estudiante in estudiantes
            ],
        })
    page_obj = Paginator(estudiantes, 5).get_page(request.GET.get('page'))
    return render(request, 'escuelaApp/admin_custom/gestionar_estudiantes.html', {
        'estudiantes': page_obj,
        'page_obj': page_obj,
        'query': query,
        'grados_disponibles': EstudianteForm.GRADOS,
        'periodos_disponibles': RegistroAcademico.objects.order_by('-periodo').values_list('periodo', flat=True).distinct(),
        'total_registrados': total_registrados,
        'total_en_lista': total_en_lista,
        'porcentaje_en_lista': _percentage_of_total(total_registrados, total_en_lista),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_exportar_estudiantes_pdf(request):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    grados = EstudianteForm.GRADOS
    codigos_grado = [codigo for codigo, _ in grados]
    grado_desde = request.GET.get('desde_grado', codigos_grado[0])
    grado_hasta = request.GET.get('hasta_grado', codigos_grado[-1])
    periodo = request.GET.get('periodo', '')
    periodos_disponibles = set(
        RegistroAcademico.objects.order_by().values_list('periodo', flat=True).distinct()
    )

    if grado_desde not in codigos_grado or grado_hasta not in codigos_grado:
        return HttpResponseBadRequest('El rango de grados seleccionado no es válido.')
    if codigos_grado.index(grado_desde) > codigos_grado.index(grado_hasta):
        return HttpResponseBadRequest('El grado inicial no puede ser mayor que el grado final.')
    if periodo and periodo not in periodos_disponibles:
        return HttpResponseBadRequest('El período escolar seleccionado no es válido.')

    codigos_seleccionados = codigos_grado[
        codigos_grado.index(grado_desde):codigos_grado.index(grado_hasta) + 1
    ]
    filtro_grados = Q()
    for codigo in codigos_seleccionados:
        filtro_grados |= Q(grado__iexact=codigo)

    estudiantes = Estudiante.objects.filter(filtro_grados).select_related('representante')
    if periodo:
        estudiantes = estudiantes.filter(registros_academicos__periodo=periodo).distinct()
    estudiantes = ordenar_estudiantes(estudiantes)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="lista_estudiantes.pdf"'
    document = SimpleDocTemplate(
        response,
        pagesize=landscape(letter),
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    nombres_grados = dict(grados)
    etiqueta_rango = f"{nombres_grados[grado_desde]} a {nombres_grados[grado_hasta]}"
    etiqueta_periodo = periodo or 'Todos los años escolares'
    elementos = [
        Paragraph('Lista de estudiantes', styles['Title']),
        Paragraph(
            f"Período escolar: {escape(etiqueta_periodo)} | Grados: {escape(etiqueta_rango)} | Total: {estudiantes.count()}",
            styles['Normal'],
        ),
        Spacer(1, 14),
    ]
    filas = [[
        Paragraph('<b>Estudiante</b>', styles['BodyText']),
        Paragraph('<b>Cédula</b>', styles['BodyText']),
        Paragraph('<b>Matrícula</b>', styles['BodyText']),
        Paragraph('<b>Grado</b>', styles['BodyText']),
        Paragraph('<b>Sección</b>', styles['BodyText']),
        Paragraph('<b>Representante</b>', styles['BodyText']),
    ]]
    filas.extend([
        [
            Paragraph(escape(f'{estudiante.nombre} {estudiante.apellido}'), styles['BodyText']),
            Paragraph(escape(estudiante.cedula or ''), styles['BodyText']),
            Paragraph(escape(estudiante.matricula or 'No asignada'), styles['BodyText']),
            Paragraph(escape(estudiante.grado or ''), styles['BodyText']),
            Paragraph(escape(estudiante.seccion or 'Sin sección'), styles['BodyText']),
            Paragraph(escape(str(estudiante.representante) if estudiante.representante else 'Sin representante'), styles['BodyText']),
        ]
        for estudiante in estudiantes
    ])
    tabla = Table(filas, colWidths=[2.1 * inch, 1.1 * inch, 1.1 * inch, 1.0 * inch, 0.9 * inch, 3.3 * inch], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#174a6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    elementos.append(tabla)
    document.build(elementos)
    enviar_reporte_a_directora('lista_estudiantes.pdf', response.content, 'application/pdf')
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE')
def admin_expediente_estudiante(request, cedula=None, estudiante_id=None):
    estudiante = _registro_por_cedula_o_id(
        Estudiante.objects.select_related('representante').prefetch_related(
            'registros_academicos',
            'asistencias',
        ),
        cedula,
        estudiante_id,
    )
    edad = None
    if estudiante.fecha_nacimiento:
        hoy = date.today()
        edad = hoy.year - estudiante.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (
                estudiante.fecha_nacimiento.month,
                estudiante.fecha_nacimiento.day,
            )
        )
    notas = estudiante.registros_academicos.all()
    asistencias = estudiante.asistencias.all()
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'nombre': f'{estudiante.nombre} {estudiante.apellido}',
            'cedula': estudiante.cedula,
            'matricula': estudiante.matricula or 'No asignada',
            'fecha_nacimiento': estudiante.fecha_nacimiento.isoformat() if estudiante.fecha_nacimiento else 'No especificada',
            'edad': f'{edad} años' if edad is not None else 'No especificada',
            'sexo': estudiante.get_sexo_display() or 'No especificado',
            'nacionalidad': estudiante.nacionalidad or 'No especificada',
            'grado': estudiante.grado,
            'seccion': estudiante.seccion or 'No asignada',
            'telefono': estudiante.telefono or 'No especificado',
            'ubicacion': estudiante.ubicacion or 'No especificada',
            'representante': str(estudiante.representante) if estudiante.representante else 'Sin representante',
            'notas': [
                {
                    'area': nota.area,
                    'periodo': nota.periodo,
                    'evaluacion': nota.tipo_evaluacion or 'No especificada',
                    'nota': nota.nota or 'Pendiente',
                    'porcentaje': str(nota.porcentaje) if nota.porcentaje is not None else 'Pendiente',
                    'estado': nota.estado or 'Pendiente',
                    'comentarios': nota.comentarios or '-',
                }
                for nota in notas
            ],
            'asistencias': [
                {
                    'fecha': asistencia.fecha.isoformat(),
                    'estado': asistencia.get_estado_display(),
                    'observaciones': asistencia.observaciones or '-',
                    'registrada_por': str(asistencia.registrado_por) if asistencia.registrado_por else 'Sistema',
                }
                for asistencia in asistencias
            ],
        })
    return render(request, 'escuelaApp/admin_custom/expediente_estudiante.html', {
        'estudiante': estudiante,
        'edad': edad,
        'notas': notas,
        'asistencias': asistencias,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_crear_estudiante(request):
    if request.method == 'POST':
        form = EstudianteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Estudiante creado correctamente.')
            return redirect('admin_estudiantes')
    else:
        form = EstudianteForm()
    return render(request, 'escuelaApp/admin_custom/formulario_estudiante.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_editar_estudiante(request, cedula=None, estudiante_id=None):
    estudiante = _registro_por_cedula_o_id(Estudiante.objects.all(), cedula, estudiante_id)
    if request.method == 'POST':
        form = EstudianteForm(request.POST, instance=estudiante)
        if form.is_valid():
            form.save()
            messages.success(request, 'Estudiante actualizado correctamente.')
            return redirect('admin_estudiantes')
    else:
        form = EstudianteForm(instance=estudiante)
    return render(request, 'escuelaApp/admin_custom/formulario_estudiante.html', {'form': form, 'estudiante': estudiante})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_eliminar_estudiante(request, cedula=None, estudiante_id=None):
    estudiante = _registro_por_cedula_o_id(Estudiante.objects.all(), cedula, estudiante_id)
    if request.method == 'POST':
        estudiante.delete()
        messages.success(request, 'Estudiante eliminado correctamente.')
    return redirect('admin_estudiantes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_docentes_view(request):
    query = request.GET.get('q', '').strip()
    docentes = Docente.objects.all().order_by('apellido', 'nombre')
    total_registrados = docentes.count()
    if query:
        docentes = docentes.filter(
            Q(nombre__icontains=query) |
            Q(apellido__icontains=query) |
            Q(cedula__icontains=query)
        )
    total_en_lista = docentes.count()
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'total': total_en_lista,
            'docentes': [
                {
                    'nombre': f'{docente.nombre} {docente.apellido}',
                    'cedula': docente.cedula or '',
                    'especialidad': docente.especialidad or 'No especificado',
                    'carga_horaria': str(docente.carga_horaria),
                }
                for docente in docentes
            ],
        })
    page_obj = Paginator(docentes, 5).get_page(request.GET.get('page'))
    return render(request, 'escuelaApp/admin_custom/gestionar_docentes.html', {
        'docentes': page_obj,
        'page_obj': page_obj,
        'query': query,
        'total_registrados': total_registrados,
        'total_en_lista': total_en_lista,
        'porcentaje_en_lista': _percentage_of_total(total_registrados, total_en_lista),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_expediente_docente(request, cedula=None, docente_id=None):
    docente = _registro_por_cedula_o_id(Docente.objects.all(), cedula, docente_id)
    horarios = Horario.objects.filter(docente=docente).order_by('ano', 'dia', 'hora_inicio')
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'nombre': f'{docente.nombre} {docente.apellido}',
            'cedula': docente.cedula,
            'telefono': docente.telefono or 'No especificado',
            'carga_horaria': f'{docente.carga_horaria} horas',
            'horarios': [
                {
                    'grado': horario.get_ano_display(),
                    'materia': horario.materia,
                    'dia': horario.get_dia_display(),
                    'hora_inicio': horario.hora_inicio.strftime('%H:%M'),
                    'hora_fin': horario.hora_fin.strftime('%H:%M'),
                }
                for horario in horarios
            ],
        })
    return redirect('admin_docentes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_crear_docente(request):
    if request.method == 'POST':
        form = DocenteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Docente creado correctamente.')
            return redirect('admin_docentes')
    else:
        form = DocenteForm()
    return render(request, 'escuelaApp/admin_custom/formulario_docente.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_editar_docente(request, cedula=None, docente_id=None):
    docente = _registro_por_cedula_o_id(Docente.objects.all(), cedula, docente_id)
    if request.method == 'POST':
        form = DocenteForm(request.POST, instance=docente)
        if form.is_valid():
            form.save()
            messages.success(request, 'Docente actualizado correctamente.')
            return redirect('admin_docentes')
    else:
        form = DocenteForm(instance=docente)
    return render(request, 'escuelaApp/admin_custom/formulario_docente.html', {'form': form, 'docente': docente})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD')
def admin_eliminar_docente(request, cedula=None, docente_id=None):
    docente = _registro_por_cedula_o_id(Docente.objects.all(), cedula, docente_id)
    if request.method == 'POST':
        docente.delete()
        messages.success(request, 'Docente eliminado correctamente.')
    return redirect('admin_docentes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_personal_view(request):
    query = request.GET.get('q', '').strip()
    cargo = request.GET.get('cargo', '')
    empleados = Empleado.objects.select_related('user').exclude(
        Q(cargo='DIRECTORA') | Q(user__is_superuser=True)
    ).order_by('user__last_name', 'user__first_name')
    if query:
        empleados = empleados.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(cedula__icontains=query)
        )
    if cargo:
        empleados = empleados.filter(cargo=cargo)
    page_obj = Paginator(empleados, 10).get_page(request.GET.get('page'))
    return render(request, 'escuelaApp/admin_custom/gestionar_empleados.html', {
        'empleados': page_obj,
        'page_obj': page_obj,
        'query': query,
        'cargo': cargo,
        'cargos': Empleado.CARGOS,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_crear_empleado(request):
    if request.method == 'POST':
        form = EmpleadoForm(request.POST)
        _restringir_cargo_directora(form, request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empleado creado correctamente.')
            return redirect('admin_personal')
    else:
        form = EmpleadoForm()
        _restringir_cargo_directora(form, request.user)
    return render(request, 'escuelaApp/admin_custom/formulario_empleado.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_editar_empleado(request, cedula):
    empleado = get_object_or_404(Empleado, cedula=cedula)
    if getattr(getattr(request.user, 'empleado', None), 'cargo', None) == 'SUBDIRECTORA' and empleado.cargo == 'DIRECTORA':
        raise PermissionDenied
    if request.method == 'POST':
        form = EmpleadoForm(request.POST, instance=empleado)
        _restringir_cargo_directora(form, request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empleado actualizado correctamente.')
            return redirect('admin_personal')
    else:
        form = EmpleadoForm(instance=empleado)
        _restringir_cargo_directora(form, request.user)
    return render(request, 'escuelaApp/admin_custom/formulario_empleado.html', {'form': form, 'empleado': empleado})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_eliminar_empleado(request, cedula):
    empleado = get_object_or_404(Empleado, cedula=cedula)
    if getattr(getattr(request.user, 'empleado', None), 'cargo', None) == 'SUBDIRECTORA' and empleado.cargo == 'DIRECTORA':
        raise PermissionDenied
    if request.method == 'POST':
        empleado.delete()
        messages.success(request, 'Empleado eliminado correctamente.')
        return redirect('admin_personal')
    return render(request, 'escuelaApp/admin_custom/confirmar_borrado.html', {'empleado': empleado})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_representantes_view(request):
    query = request.GET.get('q', '').strip()
    representantes = Representante.objects.all().order_by('apellido', 'nombre')
    total_registrados = representantes.count()
    if query:
        representantes = representantes.filter(
            Q(nombre__icontains=query) |
            Q(apellido__icontains=query) |
            Q(cedula__icontains=query)
        )
    total_en_lista = representantes.count()
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'total': total_en_lista,
            'representantes': [
                {
                    'nombre': f'{representante.nombre} {representante.apellido}',
                    'cedula': representante.cedula or '',
                    'email': representante.email or 'No especificado',
                    'telefono': representante.telefono or 'No especificado',
                    'parentesco': representante.parentesco or 'No especificado',
                }
                for representante in representantes
            ],
        })
    page_obj = Paginator(representantes, 5).get_page(request.GET.get('page'))
    return render(request, 'escuelaApp/admin_custom/gestionar_representantes.html', {
        'representantes': page_obj,
        'page_obj': page_obj,
        'query': query,
        'total_registrados': total_registrados,
        'total_en_lista': total_en_lista,
        'porcentaje_en_lista': _percentage_of_total(total_registrados, total_en_lista),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_expediente_representante(request, cedula=None, representante_id=None):
    representante = _registro_por_cedula_o_id(
        Representante.objects.prefetch_related('estudiantes'),
        cedula,
        representante_id,
    )
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'nombre': f'{representante.nombre} {representante.apellido}',
            'cedula': representante.cedula,
            'telefono': representante.telefono or 'No especificado',
            'email': representante.email or 'No especificado',
            'ocupacion': representante.ocupacion or 'No especificada',
            'parentesco': representante.parentesco or 'No especificado',
            'estado_civil': representante.get_estado_civil_display() or 'No especificado',
            'nacionalidad': representante.nacionalidad or 'No especificada',
            'partida_nacimiento': representante.partida_nacimiento or 'No especificada',
            'ubicacion': representante.ubicacion or 'No especificada',
            'tutor_legal': 'Sí' if representante.es_tutor_legal else 'No',
            'estudiantes': [
                {
                    'nombre': f'{estudiante.nombre} {estudiante.apellido}',
                    'cedula': estudiante.cedula,
                    'grado': estudiante.grado,
                }
                for estudiante in representante.estudiantes.all()
            ],
        })
    return redirect('admin_representantes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_crear_representante(request):
    if request.method == 'POST':
        form = RepresentanteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Representante creado correctamente.')
            return redirect('admin_representantes')
    else:
        form = RepresentanteForm()
    return render(request, 'escuelaApp/admin_custom/formulario_representante.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_editar_representante(request, cedula=None, representante_id=None):
    representante = _registro_por_cedula_o_id(Representante.objects.all(), cedula, representante_id)
    if request.method == 'POST':
        form = RepresentanteForm(request.POST, instance=representante)
        if form.is_valid():
            form.save()
            messages.success(request, 'Representante actualizado correctamente.')
            return redirect('admin_representantes')
    else:
        form = RepresentanteForm(instance=representante)
    return render(request, 'escuelaApp/admin_custom/formulario_representante.html', {'form': form, 'representante': representante})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_eliminar_representante(request, cedula=None, representante_id=None):
    representante = _registro_por_cedula_o_id(Representante.objects.all(), cedula, representante_id)
    if request.method == 'POST':
        representante.delete()
        messages.success(request, 'Representante eliminado correctamente.')
    return redirect('admin_representantes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_mensajes_view(request):
    paginator = Paginator(
        ContactoMensaje.objects.only(
            'id', 'nombre', 'email', 'telefono', 'acepta_whatsapp',
            'telegram_chat_id', 'asunto', 'mensaje', 'fecha_enviado', 'leido',
        ).order_by('-fecha_enviado'),
        15,
    )
    page_obj = paginator.get_page(request.GET.get('page'))
    mensajes = list(page_obj.object_list)
    correos = {mensaje.email.strip().lower() for mensaje in mensajes if mensaje.email}
    estudiantes_por_correo = {}
    if correos:
        consulta = Q()
        for correo in correos:
            consulta |= Q(representante__email__iexact=correo)
        estudiantes = Estudiante.objects.filter(consulta).select_related('representante').only(
            'nombre', 'apellido', 'grado', 'matricula', 'representante__email',
        )
        for estudiante in estudiantes:
            correo = (estudiante.representante.email or '').strip().lower()
            estudiantes_por_correo.setdefault(correo, []).append(estudiante)
    for mensaje in mensajes:
        mensaje.estudiantes_relacionados = estudiantes_por_correo.get(
            mensaje.email.strip().lower(), []
        )

    return render(request, 'escuelaApp/admin_custom/gestionar_mensajes.html', {
        'mensajes': mensajes,
        'page_obj': page_obj,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_marcar_mensaje_leido(request, mensaje_id):
    mensaje = get_object_or_404(ContactoMensaje, pk=mensaje_id)
    if request.method == 'POST':
        if not mensaje.leido:
            mensaje.leido = True
            mensaje.save()
            messages.success(request, 'Mensaje marcado como leído.')
        else:
            messages.info(request, 'El mensaje ya estaba marcado como leído.')
    return redirect('admin_mensajes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_responder_mensaje_telegram(request, mensaje_id):
    mensaje = get_object_or_404(ContactoMensaje, pk=mensaje_id)
    if request.method == 'POST':
        texto = request.POST.get('respuesta', '').strip()
        if not mensaje.telegram_chat_id:
            messages.error(request, 'Este contacto no indicó un chat_id de Telegram.')
        elif not texto:
            messages.error(request, 'Escribe el mensaje que deseas enviar por Telegram.')
        else:
            try:
                send_telegram_message(mensaje.telegram_chat_id, texto)
            except (TelegramConfigurationError, TelegramDeliveryError) as error:
                messages.error(request, f'No se pudo enviar la respuesta por Telegram: {error}')
            else:
                messages.success(request, 'Respuesta enviada por Telegram.')
    return redirect('admin_mensajes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_responder_mensaje_whatsapp(request, mensaje_id):
    mensaje = get_object_or_404(ContactoMensaje, pk=mensaje_id)
    if request.method == 'POST':
        texto = request.POST.get('respuesta', '').strip()
        if not mensaje.telefono:
            messages.error(request, 'Este contacto no indicó un teléfono.')
        elif not mensaje.acepta_whatsapp:
            messages.error(request, 'El contacto no autorizó recibir mensajes por WhatsApp.')
        elif not texto:
            messages.error(request, 'Escribe el mensaje que deseas enviar por WhatsApp.')
        else:
            try:
                send_contact_whatsapp(mensaje.telefono, texto)
            except (WhatsAppConfigurationError, WhatsAppDeliveryError) as error:
                messages.error(request, f'No se pudo enviar la respuesta por WhatsApp: {error}')
            else:
                messages.success(request, 'Respuesta enviada por WhatsApp.')
    return redirect('admin_mensajes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_responder_mensaje(request, mensaje_id):
    mensaje = get_object_or_404(ContactoMensaje, pk=mensaje_id)
    if request.method == 'POST':
        texto = request.POST.get('respuesta', '').strip()
        canal = request.POST.get('canal', '').strip()
        if not texto:
            messages.error(request, 'Escribe la información que deseas enviar.')
        elif request.POST.get('confirmar_destinatario') != 'on':
            messages.error(request, 'Confirma que verificaste el destinatario antes de enviar.')
        elif canal == 'correo':
            if len(texto) > 5000:
                messages.error(request, 'La respuesta por correo no puede superar 5000 caracteres.')
                return redirect('admin_mensajes')
            try:
                enviados = send_mail(
                    subject=f'Respuesta: {mensaje.asunto or "Mensaje de contacto"}',
                    message=texto,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[mensaje.email],
                    fail_silently=False,
                )
            except (SMTPException, OSError):
                logger.exception('No se pudo enviar correo para el mensaje de contacto %s.', mensaje.pk)
                messages.error(request, 'No se pudo enviar la respuesta por correo.')
            else:
                if enviados:
                    messages.success(request, 'Respuesta enviada por correo.')
                else:
                    messages.error(request, 'El servicio de correo no confirmó el envío.')
        elif canal == 'whatsapp':
            if not mensaje.telefono:
                messages.error(request, 'Este contacto no indicó un teléfono.')
            elif not mensaje.acepta_whatsapp:
                messages.error(request, 'El contacto no autorizó recibir mensajes por WhatsApp.')
            else:
                try:
                    send_contact_whatsapp(mensaje.telefono, texto)
                except (WhatsAppConfigurationError, WhatsAppDeliveryError) as error:
                    messages.error(request, f'No se pudo enviar la respuesta por WhatsApp: {error}')
                else:
                    messages.success(request, 'Respuesta enviada por WhatsApp.')
        elif canal == 'telegram':
            if not mensaje.telegram_chat_id:
                messages.error(request, 'Este contacto no indicó un chat de Telegram.')
            else:
                try:
                    send_telegram_message(mensaje.telegram_chat_id, texto)
                except (TelegramConfigurationError, TelegramDeliveryError) as error:
                    messages.error(request, f'No se pudo enviar la respuesta por Telegram: {error}')
                else:
                    messages.success(request, 'Respuesta enviada por Telegram.')
        else:
            messages.error(request, 'Selecciona un canal de envío válido.')
    return redirect('admin_mensajes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_eliminar_mensaje(request, mensaje_id):
    mensaje = get_object_or_404(ContactoMensaje, pk=mensaje_id)
    if request.method == 'POST':
        mensaje.delete()
        messages.success(request, 'Mensaje eliminado correctamente.')
    return redirect('admin_mensajes')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_cuentas_view(request):
    query = request.GET.get('q', '').strip()
    usuarios = User.objects.all().order_by('username')
    cargo = getattr(getattr(request.user, 'empleado', None), 'cargo', None)
    if cargo == 'SUBDIRECTORA' and not request.user.is_superuser:
        usuarios = usuarios.exclude(is_superuser=True).exclude(empleado__cargo='DIRECTORA')
    elif not request.user.is_superuser:
        usuarios = usuarios.filter(pk=request.user.pk)
    total_cuentas = usuarios.count()
    admin_count = usuarios.filter(is_staff=True).count()
    if query:
        usuarios = usuarios.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )
    return render(request, 'escuelaApp/admin_custom/gestionar_cuentas.html', {
        'usuarios': usuarios,
        'query': query,
        'total_cuentas': total_cuentas,
        'admin_count': admin_count,
        'resultados': usuarios.count(),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_crear_usuario(request):
    if request.method == 'POST':
        form = AdminCrearUsuarioForm(request.POST)
        _restringir_cargo_directora(form, request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Usuario creado correctamente.')
            return redirect('admin_panel')
    else:
        form = AdminCrearUsuarioForm()
        _restringir_cargo_directora(form, request.user)
    return render(request, 'escuelaApp/admin_custom/crear_usuario.html', {'form': form})


@active_staff_required
@staff_member_required
def admin_editar_usuario(request, user_id):
    usuario = get_object_or_404(User, pk=user_id)
    if usuario.is_superuser:
        raise PermissionDenied
    cargo_actor = getattr(getattr(request.user, 'empleado', None), 'cargo', None)
    cargo_objetivo = getattr(getattr(usuario, 'empleado', None), 'cargo', None)
    if not request.user.is_superuser and cargo_actor not in ('DIRECTORA', 'SUBDIRECTORA'):
        raise PermissionDenied
    if usuario != request.user and not request.user.is_superuser and cargo_actor != 'SUBDIRECTORA':
        raise PermissionDenied
    if cargo_actor == 'SUBDIRECTORA' and (usuario.is_superuser or cargo_objetivo == 'DIRECTORA'):
        raise PermissionDenied
    session_key = 'cuenta_edicion_autorizada'

    if request.method == 'GET' and request.GET.get('confirm') == '1':
        request.session.pop(session_key, None)
    autorizacion = request.session.get(session_key, {})
    segundos_desde_autorizacion = time.time() - autorizacion.get('authorized_at', 0)
    autorizado = (
        autorizacion.get('actor_id') == request.user.pk
        and autorizacion.get('target_user_id') == usuario.pk
        and 0 <= segundos_desde_autorizacion < 600
    )
    if not autorizado:
        request.session.pop(session_key, None)
        if request.method == 'POST':
            confirmacion = ConfirmarAccesoCuentaForm(request.POST, user=request.user)
            if confirmacion.is_valid():
                request.session[session_key] = {
                    'actor_id': request.user.pk,
                    'target_user_id': usuario.pk,
                    'authorized_at': time.time(),
                }
                return redirect('admin_editar_usuario', user_id=usuario.pk)
        else:
            confirmacion = ConfirmarAccesoCuentaForm(user=request.user)
        return render(request, 'escuelaApp/admin_custom/confirmar_acceso_cuenta.html', {
            'form': confirmacion,
            'usuario': usuario,
        })

    if request.method == 'POST':
        form = AdminEditarUsuarioForm(request.POST, instance=usuario, actor=request.user)
        if cargo_actor == 'SUBDIRECTORA':
            form.fields['cargo'].choices = [choice for choice in form.fields['cargo'].choices if choice[0] != 'DIRECTORA']
        if form.is_valid():
            form.save()
            request.session.pop(session_key, None)
            messages.success(request, 'Datos del usuario actualizados correctamente.')
            return redirect('admin_panel')
    else:
        form = AdminEditarUsuarioForm(instance=usuario, actor=request.user)
        if cargo_actor == 'SUBDIRECTORA':
            form.fields['cargo'].choices = [choice for choice in form.fields['cargo'].choices if choice[0] != 'DIRECTORA']
    return render(request, 'escuelaApp/admin_custom/editar_usuario.html', {
        'form': form,
        'usuario': usuario,
    })


@active_staff_required
@staff_member_required
def mi_cuenta_view(request):
    if request.method == 'POST':
        form = ConfirmarAccesoCuentaForm(request.POST, user=request.user)
        if form.is_valid():
            request.session[MI_CUENTA_SESSION_KEY] = {
                'user_id': request.user.pk,
                'authorized_at': time.time(),
            }
            return redirect('mi_cuenta_editar')
    else:
        request.session.pop(MI_CUENTA_SESSION_KEY, None)
        form = ConfirmarAccesoCuentaForm(user=request.user)

    return render(request, 'escuelaApp/admin_custom/confirmar_acceso_cuenta.html', {
        'form': form,
        'usuario': request.user,
    })


@active_staff_required
@staff_member_required
def mi_cuenta_editar_view(request):
    autorizacion = request.session.get(MI_CUENTA_SESSION_KEY, {})
    tiempo_autorizacion = time.time() - autorizacion.get('authorized_at', 0)
    autorizado = (
        autorizacion.get('user_id') == request.user.pk
        and 0 <= tiempo_autorizacion < 600
    )
    if not autorizado:
        request.session.pop(MI_CUENTA_SESSION_KEY, None)
        return redirect('mi_cuenta')

    if request.method == 'POST':
        form = CuentaPropiaForm(request.POST, instance=request.user, actor=request.user)
        if form.is_valid():
            cambio_contrasena = bool(form.cleaned_data.get('password'))
            usuario = form.save()
            request.session.pop(MI_CUENTA_SESSION_KEY, None)
            if cambio_contrasena:
                logout(request)
                request.session['session_message'] = 'La contraseña se actualizó. Inicia sesión con tu nueva contraseña.'
                return redirect('login')
            messages.success(request, 'Los datos de tu cuenta se actualizaron correctamente.')
            return redirect('mi_cuenta')
    else:
        form = CuentaPropiaForm(instance=request.user, actor=request.user)

    return render(request, 'escuelaApp/admin_custom/mi_cuenta.html', {
        'form': form,
        'usuario': request.user,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def registrar_asignacion(request):
    if request.method == 'POST':
        form = AsignacionForm(request.POST)
        if form.is_valid():
            Asignacion.objects.create(
                estudiante=form.cleaned_data['estudiante'],
                docente=form.cleaned_data['docente'],
                area=form.cleaned_data['area'],
                periodo=form.cleaned_data['periodo']
            )
            messages.success(request, 'Asignación creada correctamente.')
            return redirect('admin_panel')
    else:
        form = AsignacionForm()
    return render(request, 'escuelaApp/admin_custom/registrar_asignacion.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_asignaciones_view(request):
    asignaciones = Asignacion.objects.select_related('estudiante', 'docente__user').order_by('periodo', 'area')
    page_obj = Paginator(asignaciones, 10).get_page(request.GET.get('page'))
    return render(request, 'escuelaApp/admin_custom/gestionar_asignaciones.html', {
        'asignaciones': page_obj,
        'page_obj': page_obj,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_editar_asignacion(request, asignacion_id):
    asignacion = get_object_or_404(Asignacion, pk=asignacion_id)
    if request.method == 'POST':
        form = AsignacionNotaForm(request.POST, instance=asignacion)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notas y evaluación guardadas correctamente.')
            return redirect('admin_asignaciones')
    else:
        form = AsignacionNotaForm(instance=asignacion)
    docente_relacionado = Docente.objects.filter(cedula=asignacion.docente.cedula).first()
    especialidad_docente = docente_relacionado.especialidad if docente_relacionado else ''
    return render(request, 'escuelaApp/admin_custom/formulario_asignacion_nota.html', {
        'form': form,
        'asignacion': asignacion,
        'especialidad_docente': especialidad_docente,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'DOCENTE', 'PROFESOR')
def gestionar_horarios(request):
    ano_seleccionado = request.GET.get('ano', 'TODOS')
    todos_los_anos = [('TODOS', 'Todos los grados')] + list(Horario.ANOS_ESCOLARES)
    if ano_seleccionado == 'TODOS':
        horarios = Horario.objects.all().select_related('docente').order_by('dia', 'hora_inicio')
    else:
        horarios = Horario.objects.filter(ano=ano_seleccionado).select_related('docente').order_by('dia', 'hora_inicio')
    grupos_por_ano = {}
    for code, label in Horario.ANOS_ESCOLARES:
        if ano_seleccionado not in {'TODOS', code}:
            continue
        grupos_por_ano[code] = {
            'code': code,
            'name': label,
            'dias': [],
        }
        for dia_code, dia_label in Horario.DIAS_SEMANA:
            grupos_por_ano[code]['dias'].append({
                'code': dia_code,
                'name': dia_label,
                'items': [],
            })

    dia_lookup = {
        (grupo_code, dia['code']): dia
        for grupo_code, grupo in grupos_por_ano.items()
        for dia in grupo['dias']
    }
    for horario in horarios:
        dia_lookup[(horario.ano, horario.dia)]['items'].append(horario)

    context = {
        'horarios': horarios,
        'grupos_horarios': grupos_por_ano.values(),
        'ano_seleccionado': ano_seleccionado,
        'anos_disponibles': todos_los_anos,
    }
    return render(request, 'escuelaApp/admin_custom/gestionar_horarios.html', context)


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'DOCENTE', 'PROFESOR')
def exportar_horarios_pdf(request):
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph

    ano = request.GET.get('ano', 'TODOS')
    anos_validos = {codigo for codigo, _ in Horario.ANOS_ESCOLARES}
    if ano != 'TODOS' and ano not in anos_validos:
        return HttpResponseBadRequest('El grado seleccionado no es válido.')

    horarios = Horario.objects.select_related('docente').order_by('ano', 'dia', 'hora_inicio')
    if ano != 'TODOS':
        horarios = horarios.filter(ano=ano)

    etiquetas_dia = dict(Horario.DIAS_SEMANA)
    etiquetas_grado = dict(Horario.ANOS_ESCOLARES)
    filas = [['Grado', 'Día', 'Horario', 'Materia', 'Docente']]
    filas.extend([
        [
            etiquetas_grado.get(horario.ano, horario.ano),
            etiquetas_dia.get(horario.dia, horario.dia),
            f'{horario.hora_inicio:%H:%M} - {horario.hora_fin:%H:%M}',
            horario.materia,
            str(horario.docente),
        ]
        for horario in horarios
    ])

    buffer = BytesIO()
    documento = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    estilos = getSampleStyleSheet()
    contenido = [
        Paragraph(f'Horario escolar: {etiquetas_grado.get(ano, "Todos los grados")}', estilos['Title']),
        Spacer(1, 12),
        Table(filas, repeatRows=1),
    ]
    contenido[-1].setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#174a6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 7),
    ]))
    documento.build(contenido)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="horarios.pdf"'
    if getattr(getattr(request.user, 'empleado', None), 'cargo', None) not in (
        'DOCENTE', 'PROFESOR'
    ):
        enviar_reporte_a_directora('horarios.pdf', response.content, 'application/pdf')
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def crear_horario(request):
    if request.method == 'POST':
        form = HorarioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bloque de horario creado correctamente.')
            return redirect('gestionar_horarios')
    else:
        form = HorarioForm()
    return render(request, 'escuelaApp/admin_custom/formulario_horario.html', {
        **_horario_form_context(),
        'form': form,
        'title': 'Crear Bloque de Horario',
    })


def _horario_form_context(exclude_horario_id=None):
    horarios = Horario.objects.all()
    if exclude_horario_id is not None:
        horarios = horarios.exclude(pk=exclude_horario_id)
    return {
        'existing_schedules': list(horarios.values(
            'ano', 'dia', 'hora_inicio', 'hora_fin', 'docente_id', 'materia',
            'docente__nombre', 'docente__apellido',
        )),
        'horario_jornada_inicio': HORARIO_JORNADA_INICIO.strftime('%H:%M'),
        'horario_jornada_fin': HORARIO_JORNADA_FIN.strftime('%H:%M'),
        'teacher_subjects': {
            str(docente_id): especialidad
            for docente_id, especialidad in Docente.objects.values_list('pk', 'especialidad')
        },
    }


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def editar_horario(request, horario_id):
    horario = get_object_or_404(Horario, pk=horario_id)
    if request.method == 'POST':
        form = HorarioForm(request.POST, instance=horario)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bloque de horario actualizado correctamente.')
            return redirect('gestionar_horarios')
    else:
        form = HorarioForm(instance=horario)
    return render(request, 'escuelaApp/admin_custom/formulario_horario.html', {
        **_horario_form_context(exclude_horario_id=horario.pk),
        'form': form,
        'title': 'Editar Bloque de Horario',
    })


@require_POST
@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def eliminar_horario(request, horario_id):
    horario = get_object_or_404(Horario, pk=horario_id)
    horario.delete()
    messages.success(request, 'Bloque de horario eliminado; el espacio quedó disponible.')
    return redirect('gestionar_horarios')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA')
def admin_modificar_dashboard(request):
    config, _ = ConfiguracionDashboard.objects.get_or_create(pk=1)
    if request.method == 'POST':
        form = AdminConfiguracionForm(request.POST, request.FILES, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Configuración del dashboard actualizada.')
            return redirect('admin_panel')
    else:
        form = AdminConfiguracionForm(instance=config)
    return render(request, 'escuelaApp/admin_custom/modificar_dashboard.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA')
def admin_modificar_sobre_nosotros(request):
    info, _ = SobreNosotros.objects.get_or_create(pk=1)
    if request.method == 'POST':
        form = AdminSobreNosotrosForm(request.POST, request.FILES, instance=info)
        if form.is_valid():
            form.save()
            messages.success(request, 'Información de "Sobre nosotros" actualizada.')
            return redirect('admin_panel')
    else:
        form = AdminSobreNosotrosForm(instance=info)
    return render(request, 'escuelaApp/admin_custom/modificar_sobre_nosotros.html', {'form': form})


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def admin_eliminar_usuario(request, user_id):
    if request.method == 'POST':
        usuario = get_object_or_404(User, pk=user_id)
        if usuario == request.user:
            messages.error(request, 'No puedes eliminar tu propia cuenta desde este panel.')
        elif usuario.is_superuser or (
            getattr(getattr(request.user, 'empleado', None), 'cargo', None) == 'SUBDIRECTORA'
            and getattr(getattr(usuario, 'empleado', None), 'cargo', None) == 'DIRECTORA'
        ):
            messages.error(request, 'No se puede eliminar una cuenta Director/a desde este panel.')
        else:
            usuario.delete()
            messages.success(request, 'Usuario eliminado correctamente.')
    return redirect('admin_panel')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
@require_POST
def admin_toggle_usuario(request, user_id):
    usuario = get_object_or_404(User, pk=user_id)
    cargo_actor = getattr(getattr(request.user, 'empleado', None), 'cargo', None)
    cargo_objetivo = getattr(getattr(usuario, 'empleado', None), 'cargo', None)

    if usuario == request.user:
        messages.error(request, 'No puedes restringir tu propia cuenta.')
    elif usuario.is_superuser or cargo_objetivo == 'DIRECTORA':
        messages.error(request, 'La cuenta principal de Dirección está protegida.')
    elif cargo_actor == 'SUBDIRECTORA' and cargo_objetivo == 'DIRECTORA':
        messages.error(request, 'No tienes permiso para cambiar el estado de la cuenta Director/a.')
    else:
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=['is_active'])
        estado = 'habilitada' if usuario.is_active else 'restringida'
        messages.success(request, f'La cuenta de {usuario.username} quedó {estado}.')

    return redirect('admin_cuentas')


@active_staff_required
@staff_member_required
@require_POST
def refresh_staff_session(request):
    request.session['last_staff_activity'] = timezone.now().timestamp()
    request.session.set_expiry(
        settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
    )
    request.session.modified = True
    return JsonResponse({'ok': True})
