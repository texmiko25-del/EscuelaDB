# Escuela

Sistema administrativo escolar basado en Django.

En **Admin > Estudiantes**, cada ficha requiere grado y sección (A-C); el listado y el PDF se ordenan por grado, sección y apellido. Al revisar una solicitud de matrícula, Subdirección asigna la sección antes de aprobarla. Los selectores de asistencia y notas muestran el grupo de cada estudiante.

Los registros anteriores que aún no tengan sección aparecen como **Sin sección**; edítalos en **Admin > Estudiantes** para asignar el grupo correcto. El sistema no les asigna una sección automáticamente.

En **Admin > Profesores**, el botón de asignación permite filtrar por grado y sección A-C y guardar los estudiantes que estarán a cargo del profesor. La selección queda asociada al perfil del docente y aparece en su lista; los otros grupos se conservan al editar una asignación. Los horarios por grado siguen incluyendo sus estudiantes no asignados explícitamente.

## Constancias y avisos de calificaciones

Al crear o editar un registro académico, el sistema genera una constancia PDF privada y avisa automáticamente a las cuentas activas de Dirección/Subdirección y a las cuentas administradoras. Si una cuenta tiene correo, recibe el mensaje con la constancia adjunta; si tiene teléfono de contacto, también se intenta enviar un WhatsApp.

El PDF incluye estudiante, materia, período, evaluación, nota y porcentaje. Añade un informe crítico que cruza `Estudiante`, `Asistencia` y `RegistroAcademico`, con conteo de ausencias, tardanzas, notas bajo 60% y promedio. La descarga requiere inicio de sesión y rol autorizado. El estado/error de cada envío queda en Django Admin, en **Notificaciones de calificaciones**. Un fallo de correo o proveedor no cancela ni borra la calificación.

El teléfono de cada directivo se registra en **Admin > Personal**. Se acepta un número venezolano local de 11 dígitos o E.164, por ejemplo `+584121234567`.

Al aprobar una solicitud de matrícula, el sistema registra al estudiante con la sección asignada y envía al correo del representante una confirmación con el nombre, grado y sección. Si el correo no está disponible, la matrícula se conserva y el personal recibe una advertencia.

## Comunicados generales a representantes

Dirección y Subdirección pueden abrir **Admin > Representantes > Comunicado por correo**, redactar un asunto y mensaje, y seleccionar representantes, cuentas activas de docentes/profesores con correo registrado, o ambos grupos. El sistema envía un mensaje individual a cada dirección para no revelar la lista de destinatarios. Los resultados por persona quedan en el historial de comunicados dentro de Django Admin. Este flujo es independiente de las constancias: un comunicado general nunca adjunta calificaciones.

## Configuración de seguridad y despliegue

`SECRET_KEY` es obligatoria y no tiene un valor predeterminado en el código. Genérala una vez y guárdala solo en `.env` o en un gestor de secretos:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Configuración local orientativa en `.env`:

```dotenv
SECRET_KEY=PEGA_AQUI_UNA_CLAVE_ALEATORIA_GENERADA
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]
```

Para producción, configura `DJANGO_DEBUG=false` (valor predeterminado), `DJANGO_ALLOWED_HOSTS` con los dominios reales y sirve todo el sitio exclusivamente por HTTPS. En producción se habilitan por defecto la redirección HTTPS, HSTS por un año y cookies de sesión/CSRF seguras. HSTS solo debe activarse cuando HTTPS funcione correctamente para todo el dominio. Si HTTPS termina en un proxy inverso, define `DJANGO_TRUST_X_FORWARDED_PROTO=true` únicamente cuando el proxy de confianza sobrescriba esa cabecera; no la aceptes directamente desde clientes.

Los valores de `.env` son configuración local y no deben añadirse al repositorio.

```dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=escuela.example.org
```

Revisa el despliegue con `python manage.py check --deploy` después de configurar el dominio y HTTPS.

## Configurar correo

Define las variables necesarias en `.env` en la raíz. La aplicación ya no incluye una contraseña SMTP de respaldo; sin `EMAIL_HOST_PASSWORD`, el envío de correo no estará configurado. Para Gmail utiliza una clave de aplicación SMTP y no la contraseña normal. Rota cualquier clave que haya estado almacenada previamente en el código.

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu-correo@gmail.com
EMAIL_HOST_PASSWORD=CLAVE_DE_APLICACION_SMTP
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=tu-correo@gmail.com
SYSTEM_NOTIFICATION_EMAIL=notificaciones@example.org
```

## Configurar WhatsApp para avisos académicos

Los avisos de calificaciones existentes usan Twilio y requieren una plantilla aprobada y consentimiento explícito del destinatario. Configura sus variables en `.env`:

```dotenv
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=TOKEN_DE_TWILIO
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Configurar Telegram para responder mensajes de contacto

Al recibirse un contacto, Telegram avisa al personal que esté seleccionado en **Admin > Personal > Editar** y tenga configurado su chat ID. Telegram no permite enviar a un número telefónico; los representantes pueden recibir respuesta por WhatsApp si indican su número y dan su consentimiento en el formulario público.

```dotenv
TELEGRAM_BOT_TOKEN=TOKEN_DEL_BOT
```

Crea el bot con BotFather y guarda el token únicamente en `.env`; no lo compartas ni lo incluyas en formularios. Cada persona interna que recibirá avisos debe iniciar el bot; luego se registra su chat ID en **Admin > Personal** y se activa **Recibir avisos de nuevos contactos por Telegram**. El formulario público no solicita información técnica de Telegram.

Referencia oficial: [Telegram Bot API](https://core.telegram.org/bots/api).

## Configurar WhatsApp para responder contactos

El formulario público permite indicar un teléfono y aceptar explícitamente una respuesta por WhatsApp. Las respuestas usan Meta WhatsApp Cloud API y una plantilla de mensaje aprobada que incluya una variable `{{1}}` en el cuerpo, por ejemplo `Mensaje de la E.B. Elba Rosa de Acevedo: {{1}}`. Configura el nombre de esa plantilla y el idioma junto a las credenciales de Meta:

```dotenv
WHATSAPP_ACCESS_TOKEN=TOKEN_DE_META
WHATSAPP_PHONE_NUMBER_ID=ID_DEL_NUMERO_DE_WHATSAPP
WHATSAPP_API_VERSION=v23.0
WHATSAPP_CONTACT_REPLY_TEMPLATE_NAME=escuela_respuesta_contacto
WHATSAPP_CONTACT_REPLY_TEMPLATE_LANGUAGE=es
```

El nombre debe coincidir con una plantilla aprobada en Meta cuyo cuerpo tenga exactamente una variable de texto. Dirección o Subdirección puede responder desde **Admin > Mensajes de Contacto**, únicamente a contactos que autorizaron WhatsApp. Las respuestas tienen un límite de 1024 caracteres para la variable de plantilla. Si falta configurar Meta, la plantilla o el consentimiento, el mensaje del formulario se conserva y el error se registra; no se envía al contacto sin autorización.

En **Admin > Mensajes de Contacto**, cada detalle permite responder por correo o por WhatsApp cuando el contacto dio su consentimiento. Los estudiantes asociados solo se muestran si el correo del contacto coincide con el registrado para su representante; verifica el destinatario y redacta manualmente únicamente la información pertinente antes de enviar. La lista muestra un resumen paginado y el detalle se abre en una ventana emergente.

## Reportes automáticos del sistema

En **Admin > Reportes del sistema** hay cinco consultas con propósitos distintos:

- **Detalle:** por estudiante, matrícula, representante, promedio, asistencias y ausencias.
- **Resumen:** indicadores de matrícula, representantes, notas y asistencia.
- **Filtros múltiples:** registros académicos filtrables por grado, período, área, fechas y porcentaje; permite descargar Excel con formato institucional.
- **Histórico:** evolución mensual de registros académicos, promedios, asistencias y ausencias.
- **Estadístico / gráfico:** distribución visual de calificaciones de A a F.

El sistema ya incluye el comando de gestión `python manage.py enviar_reporte_sistema`, que genera un PDF con el consolidado del último mes, lo guarda en el historial de reportes y lo entrega a los directivos y correos adicionales configurados.

Las exportaciones de reportes Excel, listas de estudiantes, horarios y reportes mensuales de matrícula/asistencia también se envían como adjunto al correo de la cuenta activa con cargo **Directora**. Si el correo no está configurado o falla SMTP, la descarga se conserva y el error queda registrado en el log del servidor.

Para automatizarlo cada día en Windows, crea un script en `scripts/enviar_reporte_diario.ps1` (o usa el incluido en el proyecto) y agenda la tarea en Programador de tareas:

```powershell
$root = 'C:\ruta\al\proyecto'
Set-Location $root
& "$root\.venv\Scripts\python.exe" manage.py enviar_reporte_sistema
```

Configuración recomendada en Programador de tareas:

- Trigger: Diariamente
- Hora: 08:00
- Acción: Iniciar un programa
- Programa/script: `powershell.exe`
- Argumentos: `-ExecutionPolicy Bypass -File "C:\ruta\al\proyecto\scripts\enviar_reporte_diario.ps1"`

Esto deja la tarea ejecutándose sin depender de un navegador ni de una sesión abierta del usuario. El archivo `.env` debe seguir siendo la única fuente de credenciales SMTP.

## Migraciones y pruebas

Aplica los cambios de esquema con `python manage.py migrate`. Para ejecutar las pruebas relacionadas usando una base SQLite temporal y no borrar una base MySQL de pruebas existente:

```powershell
$env:DB_ENGINE = 'sqlite'
python manage.py test escuelaApp.tests.ReportesSistemaTests --noinput
Remove-Item Env:DB_ENGINE
```

En una base de desarrollo con `DJANGO_DEBUG=true` se pueden crear estudiantes ficticios claramente marcados como DEMO, con representantes de correo no entregable. El comando requiere confirmación explícita y crea 10 registros repartidos entre 1RO–6TO y las secciones A–C; no debe ejecutarse en producción:

```powershell
python manage.py crear_estudiantes_demo --confirmar-demo
```
