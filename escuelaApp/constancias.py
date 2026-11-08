import base64
import json
import os
import re
from io import BytesIO
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db.models import Avg, Count, Q
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import (
    Asistencia,
    ConstanciaCalificacion,
    DestinatarioAvisoCalificacion,
    Empleado,
    NotificacionCalificacion,
)
from .registro_academico import RegistroAcademico


def resumen_critico_estudiante(estudiante):
    asistencia = Asistencia.objects.filter(estudiante=estudiante).aggregate(
        total=Count('id'),
        ausencias=Count('id', filter=Q(estado='AUSENTE')),
        tardanzas=Count('id', filter=Q(estado='TARDANZA')),
    )
    calificaciones = RegistroAcademico.objects.filter(estudiante=estudiante).aggregate(
        total=Count('id'),
        bajas=Count('id', filter=Q(porcentaje__lt=60)),
        promedio=Avg('porcentaje'),
    )
    alertas = []
    if asistencia['ausencias'] >= 3:
        alertas.append('tres o más ausencias')
    if calificaciones['bajas']:
        alertas.append('calificaciones inferiores a 60%')
    return {
        'asistencia': asistencia,
        'calificaciones': calificaciones,
        'nivel': 'CRÍTICO' if alertas else 'SIN ALERTA CRÍTICA',
        'motivo': ', '.join(alertas) if alertas else 'No cumple los criterios críticos actuales.',
    }


def construir_pdf_constancia(registro):
    registro = RegistroAcademico.objects.select_related('estudiante__representante').get(pk=registro.pk)
    estudiante = registro.estudiante
    resumen = resumen_critico_estudiante(estudiante)
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle('ConstanciaTitulo', parent=estilos['Title'], alignment=TA_CENTER, textColor=colors.HexColor('#17324d'))
    elementos = [
        Paragraph('CONSTANCIA DE CALIFICACIÓN', titulo),
        Spacer(1, 0.2 * inch),
        Paragraph('Se deja constancia del siguiente registro académico:', estilos['BodyText']),
        Spacer(1, 0.15 * inch),
    ]
    datos = [
        ['Estudiante', f'{estudiante.nombre} {estudiante.apellido}'],
        ['Cédula', estudiante.cedula or 'No registrada'],
        ['Grado', estudiante.grado or 'No asignado'],
        ['Área o materia', registro.area],
        ['Período escolar', registro.periodo],
        ['Evaluación', registro.tipo_evaluacion or 'No especificada'],
        ['Calificación', registro.nota or 'Pendiente'],
        ['Porcentaje', f'{registro.porcentaje}%' if registro.porcentaje is not None else 'Pendiente'],
        ['Estado', registro.estado or 'Pendiente'],
        ['Fecha del registro', timezone.localtime(registro.fecha_registro).strftime('%d/%m/%Y %H:%M')],
    ]
    tabla = Table(datos, colWidths=[1.65 * inch, 5.0 * inch], hAlign='LEFT')
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eef3f7')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#17324d')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5df')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    elementos.extend([tabla, Spacer(1, 0.25 * inch)])
    elementos.append(Paragraph('INFORME CRÍTICO DEL ESTUDIANTE', estilos['Heading2']))
    elementos.append(Paragraph(
        'Cruce de matrícula, asistencia y calificaciones. '
        f"Asistencias: {resumen['asistencia']['total']} registradas; "
        f"{resumen['asistencia']['ausencias']} ausencias y {resumen['asistencia']['tardanzas']} tardanzas. "
        f"Calificaciones: {resumen['calificaciones']['total']} registradas; "
        f"{resumen['calificaciones']['bajas']} inferiores a 60%. "
        f"Promedio general: {resumen['calificaciones']['promedio'] or 0:.1f}%.",
        estilos['BodyText'],
    ))
    elementos.append(Paragraph(
        f"Resultado: <b>{escape(resumen['nivel'])}</b>. {escape(resumen['motivo'])}",
        estilos['BodyText'],
    ))
    elementos.extend([
        Spacer(1, 0.45 * inch),
        Paragraph('Documento generado automáticamente por el sistema académico.', estilos['Italic']),
        Spacer(1, 0.4 * inch),
        Paragraph('________________________________________<br/>Dirección / Administración', titulo),
    ])
    documento.build(elementos)
    return buffer.getvalue(), resumen


def _directivos_notificables():
    usuario = get_user_model()
    return usuario.objects.filter(is_active=True, is_staff=True).filter(
        Q(is_superuser=True) | Q(empleado__cargo__in=['DIRECTORA', 'SUBDIRECTORA'])
    ).distinct().select_related('empleado').order_by('pk')


def _telefono_whatsapp(telefono):
    telefono = (telefono or '').strip()
    if telefono.startswith('+'):
        return telefono
    digitos = re.sub(r'\D', '', telefono)
    if len(digitos) == 11 and digitos.startswith('0'):
        return f'+58{digitos[1:]}'
    return f'+{digitos}'


def _cuerpo_aviso(registro):
    estudiante = registro.estudiante
    return (
        f'Calificación registrada para {estudiante.nombre} {estudiante.apellido}: '
        f'{registro.area}, período {registro.periodo}, nota {registro.nota or "Pendiente"}, '
        f'{registro.porcentaje}%.'
    )


def _enviar_correo(destinatario, asunto, cuerpo, constancia):
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise RuntimeError('Correo SMTP no configurado en el servidor.')
    correo = EmailMessage(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])
    with constancia.archivo.open('rb') as archivo:
        correo.attach(constancia.archivo.name.rsplit('/', 1)[-1], archivo.read(), 'application/pdf')
    if correo.send(fail_silently=False) != 1:
        raise RuntimeError('El servidor SMTP no confirmó la entrega.')


def _enviar_whatsapp(destinatario, cuerpo):
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    sender = os.environ.get('TWILIO_WHATSAPP_FROM', '').strip()
    content_sid = os.environ.get('TWILIO_WHATSAPP_CONTENT_SID', '').strip()
    if not all((account_sid, auth_token, sender, content_sid)):
        raise RuntimeError('WhatsApp requiere credenciales Twilio y una plantilla aprobada.')
    if not sender.startswith('whatsapp:'):
        sender = f'whatsapp:{sender}'
    payload = urlencode({
        'From': sender,
        'To': f'whatsapp:{destinatario}',
        'ContentSid': content_sid,
        'ContentVariables': json.dumps({'1': cuerpo}, ensure_ascii=False),
    }).encode('utf-8')
    request = Request(
        f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json',
        data=payload,
        headers={
            'Authorization': 'Basic ' + base64.b64encode(
                    f'{account_sid}:{auth_token}'.encode('utf-8')
                ).decode('ascii'),
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    with urlopen(request, timeout=15) as response:
        resultado = json.loads(response.read().decode('utf-8'))
    if not resultado.get('sid'):
        raise RuntimeError('Twilio no confirmó el envío de WhatsApp.')


def generar_constancia_y_notificar(registro):
    contenido_pdf, resumen = construir_pdf_constancia(registro)
    constancia, creada = ConstanciaCalificacion.objects.get_or_create(registro=registro)
    if not creada:
        if constancia.archivo:
            constancia.archivo.delete(save=False)
        constancia.revision += 1
    nombre_archivo = f'constancia-calificacion-{registro.pk}-r{constancia.revision}.pdf'
    constancia.archivo.save(nombre_archivo, ContentFile(contenido_pdf), save=False)
    constancia.save()

    cuerpo = _cuerpo_aviso(registro)
    asunto = f'Calificación registrada: {registro.estudiante.nombre} {registro.estudiante.apellido}'
    resultados = []
    directivos = list(_directivos_notificables())
    destinatarios = []
    for directivo in directivos:
        if directivo.email:
            destinatarios.append((directivo, 'EMAIL', directivo.email))
        empleado = getattr(directivo, 'empleado', None)
        if empleado and empleado.telefono and empleado.acepta_notificaciones_whatsapp:
            destinatarios.append((directivo, 'WHATSAPP', _telefono_whatsapp(empleado.telefono)))
    representante = registro.estudiante.representante
    if representante and representante.email:
        destinatarios.append((representante, 'EMAIL', representante.email))
    destinatarios.extend(
        (None, 'EMAIL', destino.correo)
        for destino in DestinatarioAvisoCalificacion.objects.filter(activo=True)
    )
    correo_institucional = settings.SYSTEM_NOTIFICATION_EMAIL.strip()
    if correo_institucional:
        destinatarios.append((None, 'EMAIL', correo_institucional))
    enviados = set()
    for directivo, canal, destino in destinatarios:
        clave_destino = (canal, destino.casefold())
        if clave_destino in enviados:
            continue
        enviados.add(clave_destino)
        try:
            if canal == 'EMAIL':
                _enviar_correo(destino, asunto, cuerpo, constancia)
            else:
                _enviar_whatsapp(destino, cuerpo)
        except Exception as error:
            estado = 'ERROR'
            ultimo_error = str(error)[:1000]
        else:
            estado = 'ENVIADO'
            ultimo_error = ''
        NotificacionCalificacion.objects.create(
            constancia=constancia,
            revision=constancia.revision,
            canal=canal,
            destinatario=destino,
            estado=estado,
            ultimo_error=ultimo_error,
            enviado_en=timezone.now() if estado == 'ENVIADO' else None,
        )
        resultados.append((directivo, canal, destino, estado, ultimo_error))
    return constancia, resultados, resumen