import hashlib
import time

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.utils import timezone


class ActiveStaffAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _build_session_token(self, request):
        if not request.user.is_authenticated:
            return None
        raw = f"{request.user.pk}:{request.session.session_key}:{request.user.last_login or ''}:{time.time()}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _has_other_active_session(self, request):
        if not request.user.is_authenticated:
            return False

        current_key = request.session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()):
            if session.session_key == current_key:
                continue
            if session.get_decoded().get('_auth_user_id') == str(request.user.pk):
                return True
        return False

    def __call__(self, request):
        request.staff_session_idle_timeout = settings.SESSION_IDLE_TIMEOUT_SECONDS
        request.staff_session_warning_seconds = settings.SESSION_WARNING_SECONDS

        if request.path.startswith('/admin/') and request.user.is_authenticated:
            empleado = getattr(request.user, 'empleado', None)
            if not request.user.is_superuser and getattr(empleado, 'cargo', None) != 'DIRECTORA':
                return redirect('admin_panel')

        protected_prefixes = ('/admin-panel', '/admin')
        if request.path.startswith(protected_prefixes) and request.path not in {'/admin/login/', '/admin/login'}:
            if not request.user.is_authenticated:
                logout(request)
                return redirect('login')

            if not request.user.is_active or not request.user.is_staff:
                logout(request)
                return redirect('login')

            now = timezone.now().timestamp()
            last_activity = request.session.get('last_staff_activity')
            idle_seconds = now - float(last_activity) if last_activity else 0
            is_session_resume = (
                request.path == '/admin-panel/sesion/continuar/'
                and request.method == 'POST'
                and idle_seconds < (
                    settings.SESSION_IDLE_TIMEOUT_SECONDS
                    + settings.SESSION_WARNING_SECONDS
                )
            )
            if (
                last_activity
                and idle_seconds >= settings.SESSION_IDLE_TIMEOUT_SECONDS
                and not is_session_resume
            ):
                logout(request)
                return redirect('portal_home')

            request.session['last_staff_activity'] = now
            request.session.set_expiry(
                settings.SESSION_IDLE_TIMEOUT_SECONDS + settings.SESSION_WARNING_SECONDS
            )
            request.session.modified = True

            token = request.session.get('staff_session_token')
            if not token:
                if self._has_other_active_session(request):
                    logout(request)
                    return redirect('login')
                token = self._build_session_token(request)
                request.session['staff_session_token'] = token
                request.session.modified = True

        response = self.get_response(request)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
