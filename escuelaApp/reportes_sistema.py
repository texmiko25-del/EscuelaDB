import os
from datetime import date, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from .constancias import _directivos_notificables, _enviar_whatsapp
from .models import (
    Asistencia,
    DestinatarioAvisoCalificacion,
    Empleado,
    EntregaReporteSistema,
    Estudiante,
    ReporteSistemaDiario,
)
from .registro_academico import RegistroAcademico


def _datos_reporte(fecha_reporte):
    periodo_inicio = fecha_reporte - timedelta(days=29)
    asistencia_periodo = Asistencia.objects.filter(
        fecha__range=(periodo_inicio, fecha_reporte)
    )
    notas_periodo = RegistroAcademico.objects.filter(
        fecha_registro__date__range=(periodo_inicio, fecha_reporte)
    )
    estudiantes = Estudiante.objects.annotate(
        ausencias_periodo=Count(
            'asistencias',
            filter=Q(
                asistencias__fecha__range=(periodo_inicio, fecha_reporte),
                asistencias__estado='AUSENTE',
            ),
            distinct=True,
        ),
        notas_bajas_periodo=Count(
            'registros_academicos',
            filter=Q(
                registros_academicos__fecha_registro__date__range=(periodo_inicio, fecha_reporte),
                registros_academicos__porcentaje__lt=60,
            ),
            distinct=True,
        ),
        promedio_periodo=Avg(
            'registros_academicos__porcentaje',
            filter=Q(registros_academicos__fecha_registro__date__range=(periodo_inicio, fecha_reporte)),
        ),
    ).filter(
        Q(ausencias_periodo__gte=3) | Q(notas_bajas_periodo__gte=1)
    ).order_by('-ausencias_periodo', '-notas_bajas_periodo', 'apellido', 'nombre')

    datos = {
        'fecha': fecha_reporte,
        'periodo_inicio': periodo_inicio,
        'periodo_fin': fecha_reporte,
        'estudiantes': Estudiante.objects.count(),
        'asistencias': asistencia_periodo.count(),
        'ausencias': asistencia_periodo.filter(estado='AUSENTE').count(),
        'tardanzas': asistencia_periodo.filter(estado='TARDANZA').count(),
        'calificaciones': notas_periodo.count(),
        'calificaciones_bajas': notas_periodo.filter(porcentaje__lt=60).count(),
        'promedio': notas_periodo.aggregate(promedio=Avg('porcentaje'))['promedio'] or 0,
        'estudiantes_criticos': list(estudiantes[:100]),
    }
    resumen = (
        f"Reporte diario del sistema, {periodo_inicio:%d/%m/%Y} al {fecha_reporte:%d/%m/%Y}. "
        f"Matrícula: {datos['estudiantes']} estudiantes. "
        f"Asistencia: {datos['asistencias']} registros, {datos['ausencias']} ausencias y "
        f"{datos['tardanzas']} tardanzas. "
        f"Calificaciones: {datos['calificaciones']} registradas, "
        f"{datos['calificaciones_bajas']} bajo 60%; promedio {datos['promedio']:.1f}%. "
        f"Estudiantes en situación crítica: {len(datos['estudiantes_criticos'])}."
    )
    datos['resumen'] = resumen
    return datos


def _consulta_registros(filtros):
    registros = RegistroAcademico.objects.select_related(
        'estudiante', 'estudiante__representante', 'docente__user'
    )
    if filtros.get('grado'):
        registros = registros.filter(estudiante__grado=filtros['grado'])
    if filtros.get('periodo'):
        registros = registros.filter(periodo=filtros['periodo'])
    if filtros.get('area'):
        registros = registros.filter(area=filtros['area'])
    if filtros.get('fecha_desde'):
        registros = registros.filter(fecha_registro__date__gte=filtros['fecha_desde'])
    if filtros.get('fecha_hasta'):
        registros = registros.filter(fecha_registro__date__lte=filtros['fecha_hasta'])
    if filtros.get('porcentaje_min') is not None:
        registros = registros.filter(porcentaje__gte=filtros['porcentaje_min'])
    if filtros.get('porcentaje_max') is not None:
        registros = registros.filter(porcentaje__lte=filtros['porcentaje_max'])
    return registros


def _mes_desplazado(fecha, desplazamiento):
    indice = fecha.year * 12 + fecha.month - 1 + desplazamiento
    return date(indice // 12, indice % 12 + 1, 1)


def _fecha_inicio_mes(fecha):
    if hasattr(fecha, 'date'):
        fecha = fecha.date()
    return fecha.replace(day=1)


def datos_reporte_interactivo(tipo, filtros, completo=False):
    registros = _consulta_registros(filtros)
    estudiantes = Estudiante.objects.all()
    if filtros.get('grado'):
        estudiantes = estudiantes.filter(grado=filtros['grado'])

    asistencias = Asistencia.objects.all()
    if filtros.get('grado'):
        asistencias = asistencias.filter(estudiante__grado=filtros['grado'])
    if filtros.get('fecha_desde'):
        asistencias = asistencias.filter(fecha__gte=filtros['fecha_desde'])
    if filtros.get('fecha_hasta'):
        asistencias = asistencias.filter(fecha__lte=filtros['fecha_hasta'])

    if tipo == 'resumen':
        totales = registros.aggregate(
            cantidad=Count('pk'),
            promedio=Avg('porcentaje'),
            bajas=Count('pk', filter=Q(porcentaje__lt=60)),
        )
        return {
            'indicadores': [
                {'etiqueta': 'Estudiantes', 'valor': estudiantes.count()},
                {'etiqueta': 'Representantes vinculados', 'valor': estudiantes.filter(
                    representante__isnull=False
                ).values('representante_id').distinct().count()},
                {'etiqueta': 'Registros académicos', 'valor': totales['cantidad']},
                {'etiqueta': 'Promedio académico', 'valor': f"{totales['promedio'] or 0:.1f}%"},
                {'etiqueta': 'Calificaciones bajo 60%', 'valor': totales['bajas']},
                {'etiqueta': 'Asistencias', 'valor': asistencias.count()},
                {'etiqueta': 'Ausencias', 'valor': asistencias.filter(estado='AUSENTE').count()},
            ],
            'total_resultados': totales['cantidad'],
        }

    if tipo == 'detalle':
        estudiantes_detalle = Estudiante.objects.select_related('representante').all()
        if filtros.get('grado'):
            estudiantes_detalle = estudiantes_detalle.filter(grado=filtros['grado'])
        hay_filtros_academicos = any(
            filtros.get(campo) is not None and filtros.get(campo) != ''
            for campo in ('periodo', 'area', 'fecha_desde', 'fecha_hasta', 'porcentaje_min', 'porcentaje_max')
        )
        if hay_filtros_academicos:
            estudiantes_detalle = estudiantes_detalle.filter(
                pk__in=registros.values_list('estudiante_id', flat=True)
            )
        total_resultados = estudiantes_detalle.count()
        estudiantes_detalle = list(estudiantes_detalle.order_by('apellido', 'nombre')[:None if completo else 500])
        ids_estudiantes = [estudiante.pk for estudiante in estudiantes_detalle]
        registros_por_estudiante = {
            item['estudiante_id']: item
            for item in registros.filter(estudiante_id__in=ids_estudiantes).values('estudiante_id').annotate(
                cantidad=Count('pk'),
                promedio=Avg('porcentaje'),
            )
        }
        asistencias_por_estudiante = {
            item['estudiante_id']: item['ausencias']
            for item in asistencias.filter(estudiante_id__in=ids_estudiantes).values('estudiante_id').annotate(
                ausencias=Count('pk', filter=Q(estado='AUSENTE')),
            )
        }
        return {
            'estudiantes': [
                {
                    'estudiante': estudiante,
                    'registros': registros_por_estudiante.get(estudiante.pk, {}).get('cantidad', 0),
                    'promedio': registros_por_estudiante.get(estudiante.pk, {}).get('promedio'),
                    'ausencias': asistencias_por_estudiante.get(estudiante.pk, 0),
                }
                for estudiante in estudiantes_detalle
            ],
            'total_resultados': total_resultados,
            'limite_alcanzado': not completo and total_resultados > 500,
        }

    if tipo == 'historico':
        fecha_hasta = filtros.get('fecha_hasta') or timezone.localdate()
        fecha_desde = filtros.get('fecha_desde') or _mes_desplazado(fecha_hasta, -11)
        registros_mes = registros.filter(
            fecha_registro__date__range=(fecha_desde, fecha_hasta)
        ).annotate(mes=TruncMonth('fecha_registro')).values('mes').annotate(
            cantidad=Count('pk'),
            promedio=Avg('porcentaje'),
        ).order_by('mes')
        asistencias_mes = asistencias.filter(
            fecha__range=(fecha_desde, fecha_hasta)
        ).annotate(mes=TruncMonth('fecha')).values('mes').annotate(
            cantidad=Count('pk'),
            ausencias=Count('pk', filter=Q(estado='AUSENTE')),
        ).order_by('mes')
        registros_por_mes = {
            _fecha_inicio_mes(item['mes']): item for item in registros_mes if item['mes']
        }
        asistencias_por_mes = {
            _fecha_inicio_mes(item['mes']): item for item in asistencias_mes if item['mes']
        }
        primer_mes = date(fecha_desde.year, fecha_desde.month, 1)
        ultimo_mes = date(fecha_hasta.year, fecha_hasta.month, 1)
        meses = []
        actual = primer_mes
        while actual <= ultimo_mes:
            registro_mes = registros_por_mes.get(actual, {})
            asistencia_mes = asistencias_por_mes.get(actual, {})
            meses.append({
                'etiqueta': actual.strftime('%m/%Y'),
                'registros': registro_mes.get('cantidad', 0),
                'promedio': registro_mes.get('promedio') or 0,
                'asistencias': asistencia_mes.get('cantidad', 0),
                'ausencias': asistencia_mes.get('ausencias', 0),
            })
            actual = _mes_desplazado(actual, 1)
        maximo = max((max(mes['registros'], mes['asistencias']) for mes in meses), default=0)
        for mes in meses:
            mes['registros_ancho'] = round(mes['registros'] * 100 / maximo) if maximo else 0
            mes['asistencias_ancho'] = round(mes['asistencias'] * 100 / maximo) if maximo else 0
        return {'meses': meses, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}

    if tipo == 'estadistico':
        conteos = {
            item['nota']: item['cantidad']
            for item in registros.exclude(nota__isnull=True).exclude(nota='').values('nota').annotate(
                cantidad=Count('pk')
            )
        }
        total = sum(conteos.values())
        distribucion = [
            {
                'etiqueta': nota,
                'cantidad': conteos.get(nota, 0),
                'ancho': round(conteos.get(nota, 0) * 100 / total) if total else 0,
            }
            for nota in ('A', 'B', 'C', 'D', 'E', 'F')
        ]
        return {'distribucion': distribucion, 'total_resultados': total}

    resultados = registros.order_by('-fecha_registro')
    total_resultados = resultados.count()
    return {
        'registros': list(resultados if completo else resultados[:500]),
        'total_resultados': total_resultados,
        'limite_alcanzado': total_resultados > 500,
    }


def _crear_pdf(datos):
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch,
    )
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph('REPORTE DIARIO DEL SISTEMA ESCOLAR', estilos['Title']),
        Paragraph(
            f"Período: {datos['periodo_inicio']:%d/%m/%Y} al {datos['periodo_fin']:%d/%m/%Y}",
            estilos['Normal'],
        ),
        Spacer(1, 0.18 * inch),
    ]
    indicadores = [
        ['Estudiantes', 'Asistencias', 'Ausencias', 'Tardanzas', 'Calificaciones', 'Bajo 60%', 'Promedio'],
        [
            str(datos['estudiantes']),
            str(datos['asistencias']),
            str(datos['ausencias']),
            str(datos['tardanzas']),
            str(datos['calificaciones']),
            str(datos['calificaciones_bajas']),
            f"{datos['promedio']:.1f}%",
        ],
    ]
    resumen_tabla = Table(indicadores, repeatRows=1)
    resumen_tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17324d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#eef3f7')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5df')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elementos.extend([
        resumen_tabla,
        Spacer(1, 0.18 * inch),
        Paragraph('INFORME CRÍTICO: ESTUDIANTE + ASISTENCIA + REGISTRO ACADÉMICO', estilos['Heading2']),
        Paragraph('Criterios del período: 3 o más ausencias o alguna calificación inferior a 60%.', estilos['Normal']),
        Spacer(1, 0.1 * inch),
    ])
    filas = [['Estudiante', 'Grado', 'Ausencias', 'Notas bajo 60%', 'Promedio del período']]
    for estudiante in datos['estudiantes_criticos']:
        promedio = f'{estudiante.promedio_periodo:.1f}%' if estudiante.promedio_periodo is not None else 'Sin notas'
        filas.append([
            Paragraph(escape(f'{estudiante.nombre} {estudiante.apellido}'), estilos['BodyText']),
            escape(estudiante.grado),
            str(estudiante.ausencias_periodo),
            str(estudiante.notas_bajas_periodo),
            promedio,
        ])
    if len(filas) == 1:
        filas.append(['Sin casos críticos en el período', '', '', '', ''])
    criticos = Table(filas, colWidths=[3.0 * inch, 1.1 * inch, 1.2 * inch, 1.35 * inch, 1.5 * inch], repeatRows=1)
    criticos.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9b2c2c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5df')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elementos.extend([
        criticos,
        Spacer(1, 0.12 * inch),
        Paragraph('Reporte confidencial para Dirección y Administración.', estilos['Italic']),
    ])
    documento.build(elementos)
    return buffer.getvalue()


def _crear_o_recuperar_reporte(fecha_reporte):
    reporte_existente = ReporteSistemaDiario.objects.filter(fecha_reporte=fecha_reporte).first()
    if reporte_existente:
        return reporte_existente

    datos = _datos_reporte(fecha_reporte)
    pdf = _crear_pdf(datos)
    reporte = ReporteSistemaDiario(
        fecha_reporte=fecha_reporte,
        periodo_inicio=datos['periodo_inicio'],
        periodo_fin=datos['periodo_fin'],
        resumen=datos['resumen'],
        estudiantes_criticos=len(datos['estudiantes_criticos']),
    )
    reporte.archivo.save(
        f'reporte-sistema-{fecha_reporte:%Y-%m-%d}.pdf',
        ContentFile(pdf),
        save=False,
    )
    reporte.save()
    return reporte


def _destinatarios_reporte():
    destinatarios = []
    correo_institucional = settings.SYSTEM_NOTIFICATION_EMAIL.strip()
    if correo_institucional:
        destinatarios.append(('EMAIL', correo_institucional))
    for directivo in _directivos_notificables():
        if directivo.email:
            destinatarios.append(('EMAIL', directivo.email))
        empleado = getattr(directivo, 'empleado', None)
        if empleado and empleado.telefono and empleado.acepta_notificaciones_whatsapp:
            from .constancias import _telefono_whatsapp

            destinatarios.append(('WHATSAPP', _telefono_whatsapp(empleado.telefono)))
    destinatarios.extend(
        ('EMAIL', correo)
        for correo in DestinatarioAvisoCalificacion.objects.filter(activo=True).values_list('correo', flat=True)
    )
    destinos_unicos = {}
    for canal, correo in destinatarios:
        destinos_unicos.setdefault((canal, correo.casefold()), (canal, correo))
    return list(destinos_unicos.values())


def _enviar_reporte(canal, destinatario, reporte):
    if canal == 'WHATSAPP':
        from .constancias import _enviar_whatsapp

        _enviar_whatsapp(destinatario, reporte.resumen)
        return
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise RuntimeError('Correo SMTP no configurado en el servidor.')
    mensaje = EmailMessage(
        f'Reporte diario del sistema: {reporte.fecha_reporte:%d/%m/%Y}',
        reporte.resumen,
        settings.DEFAULT_FROM_EMAIL,
        [destinatario],
    )
    with reporte.archivo.open('rb') as archivo:
        mensaje.attach(reporte.archivo.name.rsplit('/', 1)[-1], archivo.read(), 'application/pdf')
    if mensaje.send(fail_silently=False) != 1:
        raise RuntimeError('El servidor SMTP no confirmó la entrega del reporte.')


def enviar_reporte_diario(fecha_reporte=None):
    zona = ZoneInfo(settings.REPORT_TIME_ZONE)
    fecha_reporte = fecha_reporte or timezone.localtime(timezone.now(), zona).date()
    reporte = _crear_o_recuperar_reporte(fecha_reporte)
    destinos = _destinatarios_reporte()
    resumen = {'reporte_id': reporte.pk, 'destinos': len(destinos), 'enviados': 0, 'errores': 0}

    for canal, destinatario in destinos:
        entrega, _ = EntregaReporteSistema.objects.get_or_create(
            reporte=reporte,
            canal=canal,
            destinatario=destinatario,
            defaults={'estado': 'ERROR', 'error': 'Pendiente de envío.'},
        )
        if entrega.estado == 'ENVIADO':
            continue
        entrega.intentos += 1
        try:
            _enviar_reporte(canal, destinatario, reporte)
        except Exception as error:
            entrega.estado = 'ERROR'
            entrega.error = str(error)[:1000]
            resumen['errores'] += 1
        else:
            entrega.estado = 'ENVIADO'
            entrega.error = ''
            entrega.enviado_en = timezone.now()
            resumen['enviados'] += 1
        entrega.save(update_fields=[
            'estado', 'intentos', 'error', 'enviado_en', 'actualizado_en',
        ])
    return reporte, resumen