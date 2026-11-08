import logging

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Empleado


logger = logging.getLogger(__name__)


def enviar_reporte_a_directora(nombre_archivo, contenido, content_type):
    directora = Empleado.objects.filter(
        cargo='DIRECTORA',
        user__is_active=True,
        user__is_staff=True,
    ).exclude(user__email='').select_related('user').order_by('user_id').first()
    if not directora:
        logger.warning('No se envió %s: no hay una Directora activa con correo registrado.', nombre_archivo)
        return False
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        logger.warning('No se envió %s: SMTP no está configurado.', nombre_archivo)
        return False

    correo = EmailMessage(
        f'Reporte generado: {nombre_archivo}',
        'Se adjunta el reporte generado desde el sistema escolar.',
        settings.DEFAULT_FROM_EMAIL,
        [directora.user.email],
    )
    correo.attach(nombre_archivo, contenido, content_type)
    try:
        enviados = correo.send(fail_silently=False)
    except Exception:
        logger.exception('No se pudo enviar %s al correo de la Directora.', nombre_archivo)
        return False
    if enviados != 1:
        logger.error('El servidor SMTP no confirmó el envío de %s a la Directora.', nombre_archivo)
        return False
    return True