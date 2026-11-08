import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


class WhatsAppConfigurationError(Exception):
    pass


class WhatsAppDeliveryError(Exception):
    pass


def _send_meta_template(payload, access_token, api_version, phone_number_id):
    request = Request(
        f'https://graph.facebook.com/{api_version}/{phone_number_id}/messages',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        raise WhatsAppDeliveryError(
            f'Meta WhatsApp API devolvió el estado HTTP {error.code}.'
        ) from error
    except (URLError, OSError) as error:
        raise WhatsAppDeliveryError(
            'No se pudo conectar con Meta WhatsApp API.'
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WhatsAppDeliveryError(
            'Meta WhatsApp API devolvió una respuesta que no se pudo interpretar.'
        ) from error

    if not isinstance(result, dict) or not result.get('messages'):
        raise WhatsAppDeliveryError(
            'Meta WhatsApp API no confirmó el envío del mensaje.'
        )

    return result


def _validate_meta_configuration(access_token, phone_number_id, api_version):
    if not all((access_token, phone_number_id)):
        raise WhatsAppConfigurationError(
            'Configura WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID en .env.'
        )
    if not re.fullmatch(r'v\d+\.\d+', api_version):
        raise WhatsAppConfigurationError('WHATSAPP_API_VERSION debe tener formato vN.N.')
    if not re.fullmatch(r'\d+', phone_number_id):
        raise WhatsAppConfigurationError('WHATSAPP_PHONE_NUMBER_ID debe contener solo dígitos.')


def _validate_template(template_name, language_code):
    if not re.fullmatch(r'[a-z0-9_]{1,512}', template_name):
        raise WhatsAppConfigurationError('El nombre de la plantilla no tiene un formato válido.')
    if not re.fullmatch(r'[a-z]{2}(?:_[A-Z]{2})?', language_code):
        raise WhatsAppConfigurationError('El idioma de la plantilla no tiene un formato válido.')


def send_contact_notification():
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    template_name = settings.WHATSAPP_TEMPLATE_NAME
    api_version = settings.WHATSAPP_API_VERSION
    recipient = re.sub(r'\D', '', settings.WHATSAPP_RECIPIENT)
    language_code = settings.WHATSAPP_TEMPLATE_LANGUAGE
    if recipient.startswith('580'):
        recipient = f'58{recipient[3:]}'

    _validate_meta_configuration(access_token, phone_number_id, api_version)
    _validate_template(template_name, language_code)
    if not 8 <= len(recipient) <= 15 or recipient.startswith('0'):
        raise WhatsAppConfigurationError(
            'WHATSAPP_RECIPIENT debe estar en formato internacional, sin el signo + ni el cero nacional.'
        )

    payload = {
        'messaging_product': 'whatsapp',
        'to': recipient,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': language_code},
        },
    }
    return _send_meta_template(payload, access_token, api_version, phone_number_id)


def send_contact_whatsapp(phone_number, text):
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    api_version = settings.WHATSAPP_API_VERSION
    template_name = settings.WHATSAPP_CONTACT_REPLY_TEMPLATE_NAME
    language_code = settings.WHATSAPP_CONTACT_REPLY_TEMPLATE_LANGUAGE
    recipient = re.sub(r'\D', '', str(phone_number or ''))
    message = str(text or '').strip()

    _validate_meta_configuration(access_token, phone_number_id, api_version)
    _validate_template(template_name, language_code)
    if len(recipient) == 11 and recipient.startswith('0'):
        recipient = f'58{recipient[1:]}'
    elif recipient.startswith('580'):
        recipient = f'58{recipient[3:]}'
    if not re.fullmatch(r'[1-9]\d{7,14}', recipient):
        raise WhatsAppDeliveryError(
            'El teléfono debe estar en formato internacional, sin el signo + ni el cero nacional.'
        )
    if not message or len(message) > 1024:
        raise WhatsAppDeliveryError(
            'La respuesta debe tener entre 1 y 1024 caracteres para la plantilla de WhatsApp.'
        )

    payload = {
        'messaging_product': 'whatsapp',
        'to': recipient,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': language_code},
            'components': [{
                'type': 'body',
                'parameters': [{
                    'type': 'text',
                    'text': message,
                }],
            }],
        },
    }
    return _send_meta_template(payload, access_token, api_version, phone_number_id)
