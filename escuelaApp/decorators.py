import hashlib
import time
from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.utils import timezone


def get_user_cargo(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    empleado = getattr(user, 'empleado', None)
    return getattr(empleado, 'cargo', None)


def active_staff_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            logout(request)
            return redirect('login')

        if not request.user.is_active or not request.user.is_staff:
            logout(request)
            return redirect('login')

        token = request.session.get('staff_session_token')
        if not token:
            current_key = request.session.session_key
            other_session_exists = any(
                session.session_key != current_key
                and session.get_decoded().get('_auth_user_id') == str(request.user.pk)
                for session in Session.objects.filter(expire_date__gt=timezone.now())
            )
            if other_session_exists:
                logout(request)
                return redirect('login')
            token = hashlib.sha256(f"{request.user.pk}:{request.session.session_key}:{request.user.last_login or ''}:{time.time()}".encode('utf-8')).hexdigest()
            request.session['staff_session_token'] = token
            request.session.modified = True

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def role_required(*allowed_cargos):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            cargo = get_user_cargo(request.user)
            if cargo in allowed_cargos:
                return view_func(request, *args, **kwargs)

            messages.error(request, 'No tienes permisos para acceder a esta sección.')
            return redirect('admin_panel')

        return _wrapped_view

    return decorator
