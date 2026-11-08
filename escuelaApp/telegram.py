import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


class TelegramConfigurationError(Exception):
    pass


class TelegramDeliveryError(Exception):
    pass


def is_valid_telegram_chat_id(chat_id):
    value = str(chat_id or '').strip()
    return bool(re.fullmatch(r'-?[0-9]{1,20}', value)) and int(value) != 0


def send_telegram_message(chat_id, text):
    token = settings.TELEGRAM_BOT_TOKEN
    recipient = str(chat_id or '').strip()
    message = str(text or '').strip()

    if not token:
        raise TelegramConfigurationError(
            'Configura TELEGRAM_BOT_TOKEN en el archivo .env.'
        )
    if not is_valid_telegram_chat_id(recipient):
        raise TelegramDeliveryError('El chat_id de Telegram no tiene un formato válido.')
    if not message or len(message) > 4096:
        raise TelegramDeliveryError(
            'El mensaje de Telegram debe tener entre 1 y 4096 caracteres.'
        )

    payload = {
        'chat_id': recipient,
        'text': message,
    }
    request = Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        raise TelegramDeliveryError(
            f'Telegram API devolvió el estado HTTP {error.code}.'
        ) from error
    except (URLError, OSError) as error:
        raise TelegramDeliveryError(
            'No se pudo conectar con Telegram.'
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TelegramDeliveryError(
            'Telegram devolvió una respuesta que no se pudo interpretar.'
        ) from error

    if not isinstance(result, dict) or result.get('ok') is not True:
        raise TelegramDeliveryError('Telegram no confirmó el envío del mensaje.')

    return result
