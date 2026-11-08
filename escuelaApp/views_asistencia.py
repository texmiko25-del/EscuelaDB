from functools import partial

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import escape
from reportlab.lib.units import inch

from .decorators import active_staff_required, role_required
from .forms import EstudianteForm
from .forms_asistencia import AsistenciaForm, ResumenAsistenciaLapsoForm
from .registro_academico import LAPSOS_ESCOLARES
from .models import Asistencia, Estudiante, ResumenAsistenciaLapso
from .docente_scope import estudiantes_del_docente, perfil_docente_usuario
from .reportes_academicos_pdf import crear_reporte_academico_pdf

staff_member_required = partial(django_staff_member_required, login_url='login')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_asistencias_view(request):
    query = request.GET.get('q', '').strip()
    fecha = request.GET.get('fecha', '').strip()
    grado = request.GET.get('grado', '').strip()

    asistencias = Asistencia.objects.select_related('estudiante', 'registrado_por')
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        asistencias = asistencias.filter(
            estudiante__in=estudiantes_del_docente(docente) if docente else []
        )

    if query:
        asistencias = asistencias.filter(
            Q(estudiante__cedula__icontains=query) |
            Q(estudiante__nombre__icontains=query) |
            Q(estudiante__apellido__icontains=query) |
            Q(estudiante__grado__icontains=query)
        )

    if fecha:
        asistencias = asistencias.filter(fecha=fecha)
    if grado:
        asistencias = asistencias.filter(estudiante__grado=grado)

    asistencias = asistencias.order_by('-fecha', '-fecha_registro')
    resumen = asistencias.aggregate(
        total=Count('id'),
        presentes=Count('id', filter=Q(estado='PRESENTE')),
        ausentes=Count('id', filter=Q(estado='AUSENTE')),
        tardanzas=Count('id', filter=Q(estado='TARDANZA')),
        justificados=Count('id', filter=Q(estado='JUSTIFICADO')),
    )

    return render(request, 'escuelaApp/admin_custom/gestionar_asistencias.html', {
        'asistencias': asistencias,
        'query': query,
        'fecha': fecha,
        'grado': grado,
        'grados': EstudianteForm.GRADOS,
        'resumen': resumen,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_exportar_asistencias_pdf(request):
    asistencias = Asistencia.objects.select_related('estudiante').order_by(
        'estudiante__apellido', 'estudiante__nombre', '-fecha',
    )
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        asistencias = asistencias.filter(
            estudiante__in=estudiantes_del_docente(docente) if docente else []
        )

    query = request.GET.get('q', '').strip()
    fecha = request.GET.get('fecha', '').strip()
    grado = request.GET.get('grado', '').strip()
    cedula = request.GET.get('estudiante', '').strip()
    if query:
        asistencias = asistencias.filter(
            Q(estudiante__cedula__icontains=query) |
            Q(estudiante__nombre__icontains=query) |
            Q(estudiante__apellido__icontains=query) |
            Q(estudiante__grado__icontains=query)
        )
    if fecha:
        asistencias = asistencias.filter(fecha=fecha)
    if grado:
        asistencias = asistencias.filter(estudiante__grado=grado)

    if cedula:
        estudiantes_visibles = Estudiante.objects.all()
        if empleado:
            estudiantes_visibles = estudiantes_visibles.filter(
                pk__in=estudiantes_del_docente(docente).values('pk') if docente else []
            )
        estudiante = get_object_or_404(estudiantes_visibles, cedula=cedula)
        asistencias = asistencias.filter(estudiante=estudiante)
        titulo = 'Reporte individual de asistencia'
        subtitulo = (
            f'Estudiante: {escape(f"{estudiante.nombre} {estudiante.apellido}")} | '
            f'Cédula: {escape(estudiante.cedula or "No registrada")} | Grado: {escape(estudiante.grado or "No asignado")}'
        )
        nombre_archivo = f'asistencia-{estudiante.cedula or estudiante.pk}.pdf'
    else:
        titulo = 'Reporte grupal de asistencia'
        subtitulo = f'Registros incluidos: {asistencias.count()}'
        nombre_archivo = 'asistencia-grupal.pdf'

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    filas = [
        [
            escape(f'{asistencia.estudiante.nombre} {asistencia.estudiante.apellido}'),
            escape(asistencia.estudiante.cedula or 'No registrada'),
            escape(asistencia.estudiante.grado or 'No asignado'),
            asistencia.fecha.strftime('%d/%m/%Y'),
            escape(asistencia.get_estado_display()),
            escape(asistencia.observaciones or '-'),
        ]
        for asistencia in asistencias
    ]
    crear_reporte_academico_pdf(
        response,
        titulo,
        subtitulo,
        ['Estudiante', 'Cédula', 'Grado', 'Fecha', 'Estado', 'Observaciones'],
        filas,
        [1.8 * inch, 1.15 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch, 4.25 * inch],
    )
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def admin_crear_asistencia(request):
    if request.method == 'POST':
        form = AsistenciaForm(request.POST, actor=request.user)
        if form.is_valid():
            asistencia = form.save(commit=False)
            asistencia.registrado_por = request.user.empleado if hasattr(request.user, 'empleado') else None
            asistencia.save()
            messages.success(request, 'Asistencia registrada correctamente.')
            return redirect('admin_asistencias')
    else:
        form = AsistenciaForm(actor=request.user)
    asistencias_existentes = Asistencia.objects.all()
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        asistencias_existentes = asistencias_existentes.filter(
            estudiante__in=estudiantes_del_docente(docente) if docente else []
        )
    return render(request, 'escuelaApp/admin_custom/crear_asistencia.html', {
        'form': form,
        'dynamic_form_data': {
            'hoy': timezone.localdate().isoformat(),
            'asistencias': list(asistencias_existentes.values(
                'estudiante_id', 'fecha', 'estudiante__nombre', 'estudiante__apellido'
            )),
        },
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_resumenes_asistencia_lapso(request):
    resumenes = ResumenAsistenciaLapso.objects.select_related('estudiante', 'registrado_por')
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        resumenes = resumenes.filter(
            estudiante__in=estudiantes_del_docente(docente) if docente else []
        )
    periodo = request.GET.get('periodo', '').strip()
    lapso = request.GET.get('lapso', '').strip()
    grado = request.GET.get('grado', '').strip()
    if periodo:
        resumenes = resumenes.filter(periodo=periodo)
    if lapso:
        resumenes = resumenes.filter(lapso=lapso)
    if grado:
        resumenes = resumenes.filter(estudiante__grado=grado)
    resumenes = resumenes.order_by('-periodo', 'lapso', 'estudiante__apellido')
    return render(request, 'escuelaApp/admin_custom/gestionar_resumenes_asistencia.html', {
        'resumenes': resumenes,
        'periodo': periodo,
        'periodos': ResumenAsistenciaLapso.objects.order_by('-periodo').values_list(
            'periodo', flat=True,
        ).distinct(),
        'lapso': lapso,
        'lapsos': LAPSOS_ESCOLARES,
        'grado': grado,
        'grados': EstudianteForm.GRADOS,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_exportar_resumenes_asistencia_lapso_pdf(request):
    resumenes = ResumenAsistenciaLapso.objects.select_related('estudiante').order_by(
        'estudiante__apellido', 'estudiante__nombre', '-periodo', 'lapso',
    )
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        resumenes = resumenes.filter(
            estudiante__in=estudiantes_del_docente(docente) if docente else []
        )

    periodo = request.GET.get('periodo', '').strip()
    lapso = request.GET.get('lapso', '').strip()
    grado = request.GET.get('grado', '').strip()
    cedula = request.GET.get('estudiante', '').strip()
    if periodo:
        resumenes = resumenes.filter(periodo=periodo)
    if lapso:
        resumenes = resumenes.filter(lapso=lapso)
    if grado:
        resumenes = resumenes.filter(estudiante__grado=grado)

    if cedula:
        estudiantes_visibles = Estudiante.objects.all()
        if empleado:
            estudiantes_visibles = estudiantes_visibles.filter(
                pk__in=estudiantes_del_docente(docente).values('pk') if docente else []
            )
        estudiante = get_object_or_404(estudiantes_visibles, cedula=cedula)
        resumenes = resumenes.filter(estudiante=estudiante)
        titulo = 'Reporte individual de asistencia por lapso'
        subtitulo = (
            f'Estudiante: {escape(f"{estudiante.nombre} {estudiante.apellido}")} | '
            f'Cédula: {escape(estudiante.cedula or "No registrada")} | Grado: {escape(estudiante.grado or "No asignado")}'
        )
        nombre_archivo = f'asistencia-lapsos-{estudiante.cedula or estudiante.pk}.pdf'
    else:
        titulo = 'Reporte grupal de asistencia por lapso'
        subtitulo = f'Resúmenes incluidos: {resumenes.count()}'
        nombre_archivo = 'asistencia-lapsos-grupo.pdf'

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    filas = [
        [
            escape(f'{resumen.estudiante.nombre} {resumen.estudiante.apellido}'),
            escape(resumen.estudiante.grado or 'No asignado'),
            escape(resumen.periodo),
            escape(resumen.get_lapso_display()),
            str(resumen.presentes),
            str(resumen.ausentes),
            str(resumen.tardanzas),
            str(resumen.justificadas),
            escape(resumen.observaciones or '-'),
        ]
        for resumen in resumenes
    ]
    crear_reporte_academico_pdf(
        response,
        titulo,
        subtitulo,
        ['Estudiante', 'Grado', 'Período', 'Lapso', 'Presentes', 'Ausentes', 'Tardanzas', 'Justificadas', 'Observaciones'],
        filas,
        [1.5 * inch, 0.65 * inch, 0.8 * inch, 0.9 * inch, 0.65 * inch, 0.65 * inch, 0.7 * inch, 0.75 * inch, 3.4 * inch],
    )
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def admin_crear_resumen_asistencia_lapso(request):
    if request.method == 'POST':
        form = ResumenAsistenciaLapsoForm(request.POST, actor=request.user)
        if form.is_valid():
            resumen = form.save(commit=False)
            resumen.registrado_por = getattr(request.user, 'empleado', None)
            resumen.save()
            messages.success(request, 'Resumen de asistencia guardado correctamente.')
            return redirect('admin_resumenes_asistencia_lapso')
    else:
        form = ResumenAsistenciaLapsoForm(actor=request.user)
    return render(request, 'escuelaApp/admin_custom/formulario_resumen_asistencia.html', {
        'form': form,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def admin_editar_resumen_asistencia_lapso(request, resumen_id):
    messages.warning(
        request,
        'Los resúmenes de asistencia no se pueden editar después de guardarse. Puedes consultarlos y exportarlos.',
    )
    return redirect('admin_resumenes_asistencia_lapso')
