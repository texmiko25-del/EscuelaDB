from datetime import date
from functools import partial
from io import BytesIO
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import active_staff_required, role_required
from .forms_subdireccion import AsistenciaPersonalForm, RevisionSolicitudMatriculaForm
from .models import AsistenciaPersonal, Empleado, Estudiante, Representante, SolicitudMatricula
from .report_delivery import enviar_reporte_a_directora


staff_member_required = partial(django_staff_member_required, login_url='login')
logger = logging.getLogger(__name__)
MESES = [
    (1, 'Enero'),
    (2, 'Febrero'),
    (3, 'Marzo'),
    (4, 'Abril'),
    (5, 'Mayo'),
    (6, 'Junio'),
    (7, 'Julio'),
    (8, 'Agosto'),
    (9, 'Septiembre'),
    (10, 'Octubre'),
    (11, 'Noviembre'),
    (12, 'Diciembre'),
]


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_solicitudes_matricula(request):
    estado = request.GET.get('estado', 'PENDIENTE').strip().upper()
    if estado not in {'PENDIENTE', 'APROBADA', 'RECHAZADA', 'TODAS'}:
        estado = 'PENDIENTE'
    query = request.GET.get('q', '').strip()
    solicitudes = SolicitudMatricula.objects.select_related('revisada_por', 'estudiante')
    if estado != 'TODAS':
        solicitudes = solicitudes.filter(estado=estado)
    if query:
        solicitudes = solicitudes.filter(
            Q(estudiante_nombre__icontains=query) |
            Q(estudiante_apellido__icontains=query) |
            Q(representante_nombre__icontains=query) |
            Q(representante_apellido__icontains=query) |
            Q(representante_cedula__icontains=query)
        )
    return render(request, 'escuelaApp/admin_custom/subdireccion_matriculas.html', {
        'solicitudes': solicitudes,
        'estado': estado,
        'query': query,
        'pendientes': SolicitudMatricula.objects.filter(estado='PENDIENTE').count(),
        'total_solicitudes': SolicitudMatricula.objects.count(),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_revisar_matricula(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudMatricula, pk=solicitud_id)
    if request.method == 'POST' and solicitud.estado == 'PENDIENTE':
        form = RevisionSolicitudMatriculaForm(request.POST)
        accion = request.POST.get('accion')
        if form.is_valid() and accion in {'aprobar', 'rechazar'}:
            observaciones = form.cleaned_data['observaciones'].strip()
            if accion == 'rechazar' and not observaciones:
                form.add_error('observaciones', 'Indica el motivo para rechazar la solicitud.')
            else:
                with transaction.atomic():
                    if accion == 'aprobar':
                        representante, creado = Representante.objects.get_or_create(
                            cedula=solicitud.representante_cedula,
                            defaults={
                                'nombre': solicitud.representante_nombre,
                                'apellido': solicitud.representante_apellido,
                                'telefono': solicitud.representante_telefono,
                                'email': solicitud.representante_email or None,
                                'parentesco': solicitud.representante_parentesco,
                                'nacionalidad': solicitud.representante_nacionalidad,
                            },
                        )
                        estudiante = Estudiante.objects.create(
                            nombre=solicitud.estudiante_nombre,
                            apellido=solicitud.estudiante_apellido,
                            cedula='',
                            fecha_nacimiento=solicitud.estudiante_fecha_nacimiento,
                            sexo=solicitud.estudiante_sexo,
                            nacionalidad=solicitud.estudiante_nacionalidad,
                            grado=solicitud.grado,
                            seccion=form.cleaned_data['seccion'],
                            partida_nacimiento=solicitud.partida_nacimiento,
                            telefono=solicitud.estudiante_telefono,
                            ubicacion=solicitud.estudiante_ubicacion,
                            representante=representante,
                        )
                        solicitud.estudiante = estudiante
                        solicitud.estado = 'APROBADA'
                    else:
                        solicitud.estado = 'RECHAZADA'
                        messages.success(request, 'Solicitud rechazada; el motivo quedó registrado.')
                    solicitud.observaciones_revision = observaciones
                    solicitud.fecha_revision = timezone.now()
                    solicitud.revisada_por = request.user
                    solicitud.save()
                if accion == 'aprobar' and solicitud.representante_email:
                    nombre_estudiante = f'{solicitud.estudiante_nombre} {solicitud.estudiante_apellido}'
                    asunto = 'Matrícula registrada correctamente'
                    mensaje = (
                        f'Estimado/a {solicitud.representante_nombre},\n\n'
                        f'La matrícula de {nombre_estudiante} fue aprobada y quedó registrada '
                        f'correctamente en el sistema para el grado {solicitud.get_grado_display()}, '
                        f'sección {form.cleaned_data["seccion"]}.\n\n'
                        'Saludos,\nLa Dirección'
                    )
                    try:
                        enviados = send_mail(
                            asunto,
                            mensaje,
                            settings.DEFAULT_FROM_EMAIL,
                            [solicitud.representante_email],
                            fail_silently=False,
                        )
                        if enviados != 1:
                            raise RuntimeError('El servidor de correo no confirmó la entrega.')
                    except Exception:
                        logger.exception('No se pudo enviar la confirmación de matrícula %s', solicitud.pk)
                        messages.warning(
                            request,
                            'Matrícula aprobada y estudiante registrado, pero no se pudo enviar la confirmación por correo.',
                        )
                    else:
                        messages.success(
                            request,
                            'Matrícula aprobada y estudiante registrado. Se envió la confirmación por correo.',
                        )
                elif accion == 'aprobar':
                    messages.success(request, 'Matrícula aprobada y estudiante registrado.')
                return redirect('subdireccion_solicitudes_matricula')
    else:
        form = RevisionSolicitudMatriculaForm(initial={
            'observaciones': solicitud.observaciones_revision,
        })

    return render(request, 'escuelaApp/admin_custom/revisar_matricula.html', {
        'solicitud': solicitud,
        'form': form,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_descargar_documento(request, solicitud_id, tipo):
    solicitud = get_object_or_404(SolicitudMatricula, pk=solicitud_id)
    campos = {
        'representante': solicitud.documento_representante,
        'partida': solicitud.documento_partida_nacimiento,
    }
    archivo = campos.get(tipo)
    if not archivo or not archivo.name:
        raise Http404('Documento no encontrado.')
    try:
        contenido = archivo.open('rb')
    except OSError as error:
        raise Http404('Documento no encontrado.') from error
    nombre = archivo.name.rsplit('/', 1)[-1]
    tipo_contenido = 'application/pdf' if nombre.lower().endswith('.pdf') else 'image/*'
    return FileResponse(contenido, filename=nombre, content_type=tipo_contenido)


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_asistencia_personal(request):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get('anio', hoy.year))
        mes = int(request.GET.get('mes', hoy.month))
    except (TypeError, ValueError):
        return HttpResponseBadRequest('El mes y el año deben ser números válidos.')
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
        return HttpResponseBadRequest('El mes o el año seleccionado no es válido.')

    registros = AsistenciaPersonal.objects.select_related('empleado__user', 'registrado_por').filter(
        fecha__year=anio,
        fecha__month=mes,
    )
    query = request.GET.get('q', '').strip()
    if query:
        registros = registros.filter(
            Q(empleado__user__first_name__icontains=query) |
            Q(empleado__user__last_name__icontains=query) |
            Q(empleado__cedula__icontains=query)
        )
    resumen = registros.aggregate(
        total=Count('id'),
        presentes=Count('id', filter=Q(estado='PRESENTE')),
        ausentes=Count('id', filter=Q(estado='AUSENTE')),
        tardanzas=Count('id', filter=Q(estado='TARDANZA')),
        justificados=Count('id', filter=Q(estado='JUSTIFICADO')),
    )
    return render(request, 'escuelaApp/admin_custom/subdireccion_asistencia.html', {
        'registros': registros,
        'resumen': resumen,
        'query': query,
        'anio': anio,
        'mes': mes,
        'meses': MESES,
        'anios': range(hoy.year - 3, hoy.year + 1),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_registrar_asistencia(request):
    if request.method == 'POST':
        form = AsistenciaPersonalForm(request.POST)
        if form.is_valid():
            asistencia = form.save(commit=False)
            asistencia.registrado_por = request.user
            asistencia.save()
            messages.success(request, 'Asistencia del personal guardada correctamente.')
            return redirect('subdireccion_asistencia_personal')
    else:
        form = AsistenciaPersonalForm(initial={'fecha': timezone.localdate()})
    return render(request, 'escuelaApp/admin_custom/subdireccion_registrar_asistencia.html', {
        'form': form,
    })


def _datos_reporte_personal(request):
    return _datos_reporte(request, AsistenciaPersonal, 'fecha')


def _datos_reporte_matricula(request):
    return _datos_reporte(request, SolicitudMatricula, 'fecha_solicitud')


def _datos_reporte(request, modelo, campo_fecha):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get('anio', hoy.year))
        mes = int(request.GET.get('mes', hoy.month))
    except (TypeError, ValueError):
        return None, HttpResponseBadRequest('El mes y el año deben ser números válidos.')
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
        return None, HttpResponseBadRequest('El mes o el año seleccionado no es válido.')
    registros = modelo.objects.filter(**{
        f'{campo_fecha}__year': anio,
        f'{campo_fecha}__month': mes,
    })
    return (anio, mes, registros), None


def _respuesta_reporte(request, tipo, formato):
    if formato not in {'pdf', 'docx'}:
        return HttpResponseBadRequest('El formato debe ser pdf o docx.')
    if tipo == 'personal':
        datos, error = _datos_reporte_personal(request)
        titulo = 'Asistencia mensual del personal'
        cabeceras = ['Fecha', 'Empleado', 'Cargo', 'Estado', 'Observaciones']
        if error:
            return error
        anio, mes, registros = datos
        registros = registros.select_related('empleado__user')
        filas = [[
            registro.fecha.strftime('%d/%m/%Y'),
            registro.empleado.user.get_full_name() or registro.empleado.user.username,
            registro.empleado.get_cargo_display(),
            registro.get_estado_display(),
            registro.observaciones or '-',
        ] for registro in registros]
        prefijo = 'asistencia-personal'
    else:
        datos, error = _datos_reporte_matricula(request)
        titulo = 'Solicitudes mensuales de matrícula'
        cabeceras = ['Fecha', 'Estudiante', 'Grado', 'Representante', 'Parentesco', 'Estado', 'Observaciones']
        if error:
            return error
        anio, mes, registros = datos
        filas = [[
            registro.fecha_solicitud.strftime('%d/%m/%Y'),
            f'{registro.estudiante_nombre} {registro.estudiante_apellido}',
            registro.get_grado_display(),
            f'{registro.representante_nombre} {registro.representante_apellido}',
            registro.representante_parentesco,
            registro.get_estado_display(),
            registro.observaciones_revision or '-',
        ] for registro in registros]
        prefijo = 'matricula-mensual'

    nombre = f'{prefijo}-{anio}-{mes:02d}.{formato}'
    if formato == 'docx':
        from docx import Document

        documento = Document()
        documento.add_heading(titulo, level=1)
        documento.add_paragraph(f'Período: {mes:02d}/{anio}')
        tabla = documento.add_table(rows=1, cols=len(cabeceras))
        tabla.style = 'Table Grid'
        for celda, texto in zip(tabla.rows[0].cells, cabeceras):
            celda.text = texto
        for fila in filas:
            celdas = tabla.add_row().cells
            for celda, texto in zip(celdas, fila):
                celda.text = str(texto)
        buffer = BytesIO()
        documento.save(buffer)
        contenido = buffer.getvalue()
        content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    else:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        from xml.sax.saxutils import escape

        buffer = BytesIO()
        documento = SimpleDocTemplate(buffer, pagesize=landscape(letter), leftMargin=0.35 * inch, rightMargin=0.35 * inch)
        styles = getSampleStyleSheet()
        data = [[Paragraph(escape(text), styles['BodyText']) for text in cabeceras]]
        data.extend([
            [Paragraph(escape(str(text)), styles['BodyText']) for text in fila]
            for fila in filas
        ])
        tabla = Table(data, repeatRows=1)
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#174a6e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        documento.build([
            Paragraph(escape(titulo), styles['Title']),
            Paragraph(f'Período: {mes:02d}/{anio}', styles['Normal']),
            Spacer(1, 10),
            tabla,
        ])
        contenido = buffer.getvalue()
        content_type = 'application/pdf'

    response = HttpResponse(contenido, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{nombre}"'
    enviar_reporte_a_directora(nombre, contenido, content_type)
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_reporte_asistencia(request, formato):
    return _respuesta_reporte(request, 'personal', formato)


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA')
def subdireccion_reporte_matricula(request, formato):
    return _respuesta_reporte(request, 'matricula', formato)