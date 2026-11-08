from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import ComunicadoRepresentantes, EntregaComunicadoRepresentante


def enviar_comunicado_representantes(asunto, mensaje, representantes, usuario, docentes=()):
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise RuntimeError('Configura el usuario y la clave SMTP antes de enviar comunicados.')

    comunicado = ComunicadoRepresentantes.objects.create(
        asunto=asunto,
        mensaje=mensaje,
        creado_por=usuario,
    )
    destinatarios_unicos = {}
    for representante in representantes:
        correo = (representante.email or '').strip()
        if correo:
            destinatarios_unicos.setdefault(correo.casefold(), (representante, correo))
    for docente in docentes:
        correo = (docente.user.email or '').strip()
        if correo:
            destinatarios_unicos.setdefault(correo.casefold(), (None, correo))

    entregas = []
    for representante, correo in destinatarios_unicos.values():
        try:
            enviados = send_mail(
                asunto,
                mensaje,
                settings.DEFAULT_FROM_EMAIL,
                [correo],
                fail_silently=False,
            )
            if enviados != 1:
                raise RuntimeError('El servidor de correo no confirmó la entrega.')
        except Exception as error:
            estado = 'ERROR'
            error_texto = str(error)[:1000]
        else:
            estado = 'ENVIADO'
            error_texto = ''
        entregas.append(EntregaComunicadoRepresentante(
            comunicado=comunicado,
            representante=representante,
            correo=correo,
            estado=estado,
            error=error_texto,
            enviado_en=timezone.now() if estado == 'ENVIADO' else None,
        ))
    EntregaComunicadoRepresentante.objects.bulk_create(entregas)
    return comunicado, entregas