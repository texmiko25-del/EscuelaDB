import logging

from .models import Empleado
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

logger = logging.getLogger(__name__)


def notify_new_contact(contact):
    staff = list(
        Empleado.objects.filter(
            notificar_contactos_telegram=True,
            user__is_active=True,
            user__is_staff=True,
        ).exclude(telegram_chat_id='').select_related('user')
    )
    failures = 0
    staff_text = (
        f'Nuevo mensaje de contacto de {contact.nombre}\n'
        f'Asunto: {contact.asunto or "Sin asunto"}\n'
        f'Correo: {contact.email}\n'
        f'Teléfono: {contact.telefono or "No indicado"}\n\n'
        f'{contact.mensaje}'
    )[:4096]

    for recipient in staff:
        try:
            send_telegram_message(recipient.telegram_chat_id, staff_text)
        except (TelegramConfigurationError, TelegramDeliveryError):
            failures += 1
            logger.exception(
                'No se pudo notificar por Telegram al empleado %s sobre el contacto %s.',
                recipient.pk,
                contact.pk,
            )

    if contact.telefono and contact.acepta_whatsapp:
        try:
            send_contact_whatsapp(
                contact.telefono,
                'Recibimos tu mensaje de contacto. Gracias por escribirnos; '
                'la escuela te responderá pronto.',
            )
        except (WhatsAppConfigurationError, WhatsAppDeliveryError):
            failures += 1
            logger.exception(
                'No se pudo confirmar por WhatsApp el contacto %s.',
                contact.pk,
            )

    return {
        'staff_count': len(staff),
        'failures': failures,
    }
