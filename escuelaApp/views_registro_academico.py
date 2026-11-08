from functools import partial

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Exists, OuterRef, Q
from django.http import FileResponse
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from reportlab.lib.units import inch

from .constancias import generar_constancia_y_notificar
from .decorators import active_staff_required, role_required
from .forms_registro_academico import RegistroAcademicoForm
from .forms import EstudianteForm
from .models import ConstanciaCalificacion
from .models import Estudiante
from .registro_academico import RegistroAcademico
from .docente_scope import filtrar_registros_docente, perfil_docente_usuario
from .reportes_academicos_pdf import crear_reporte_academico_pdf

staff_member_required = partial(django_staff_member_required, login_url='login')


def _notificar_resultado_constancia(request, resultados):
    if not resultados:
        messages.warning(
            request,
            'La constancia fue creada, pero ninguna cuenta directiva tiene correo o teléfono configurado.',
        )
        return
    enviados = sum(resultado[3] == 'ENVIADO' for resultado in resultados)
    errores = len(resultados) - enviados
    if errores:
        messages.warning(
            request,
            f'Constancia creada. Avisos entregados: {enviados}; con error: {errores}. Revisa el historial de notificaciones.',
        )
    else:
        messages.success(request, f'Constancia creada y enviada por {enviados} canal(es) directivo(s).')


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_registro_academico_view(request):
    query = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '').strip()
    periodo = request.GET.get('periodo', '').strip()
    grado = request.GET.get('grado', '').strip()

    registros = RegistroAcademico.objects.select_related('estudiante', 'docente').annotate(
        tiene_constancia=Exists(
            ConstanciaCalificacion.objects.filter(registro_id=OuterRef('pk'))
        )
    )
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        registros = filtrar_registros_docente(registros, docente) if docente else registros.none()
    registros_disponibles = registros

    if query:
        registros = registros.filter(
            Q(estudiante__cedula__icontains=query) |
            Q(estudiante__nombre__icontains=query) |
            Q(estudiante__apellido__icontains=query) |
            Q(estudiante__grado__icontains=query) |
            Q(area__icontains=query) |
            Q(tipo_evaluacion__icontains=query)
        )

    if estado:
        registros = registros.filter(estado__icontains=estado)

    if periodo:
        registros = registros.filter(periodo__icontains=periodo)
    if grado:
        registros = registros.filter(estudiante__grado=grado)

    registros = registros.order_by('-fecha_registro')

    periodos = registros_disponibles.order_by('periodo').values_list(
        'periodo', flat=True
    ).distinct()
    estados = registros_disponibles.order_by('estado').values_list(
        'estado', flat=True
    ).distinct()
    page_obj = Paginator(registros, 10).get_page(request.GET.get('page'))

    totales = registros.aggregate(
        total=Count('id'),
        con_nota=Count('id', filter=~Q(nota=None)),
        promedio_porcentaje=Avg('porcentaje')
    )

    return render(request, 'escuelaApp/admin_custom/gestionar_registro_academico.html', {
        'registros': page_obj,
        'page_obj': page_obj,
        'query': query,
        'estado': estado,
        'periodo': periodo,
        'grado': grado,
        'grados': EstudianteForm.GRADOS,
        'periodos': periodos,
        'estados': estados,
        'total_registros': totales['total'] or 0,
        'total_con_nota': totales['con_nota'] or 0,
        'promedio_nota': round(totales['promedio_porcentaje'] or 0, 2),
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'ASISTENTE', 'DOCENTE', 'PROFESOR')
def admin_exportar_registros_academicos_pdf(request):
    registros = RegistroAcademico.objects.select_related(
        'estudiante', 'docente',
    ).order_by('estudiante__apellido', 'estudiante__nombre', 'periodo', 'lapso', 'area')
    empleado, docente = perfil_docente_usuario(request.user)
    if empleado:
        registros = filtrar_registros_docente(registros, docente) if docente else registros.none()

    query = request.GET.get('q', '').strip()
    periodo = request.GET.get('periodo', '').strip()
    grado = request.GET.get('grado', '').strip()
    estado = request.GET.get('estado', '').strip()
    cedula = request.GET.get('estudiante', '').strip()
    if query:
        registros = registros.filter(
            Q(estudiante__cedula__icontains=query) |
            Q(estudiante__nombre__icontains=query) |
            Q(estudiante__apellido__icontains=query) |
            Q(estudiante__grado__icontains=query) |
            Q(area__icontains=query) |
            Q(tipo_evaluacion__icontains=query)
        )
    if periodo:
        registros = registros.filter(periodo__icontains=periodo)
    if grado:
        registros = registros.filter(estudiante__grado=grado)
    if estado:
        registros = registros.filter(estado__icontains=estado)

    if cedula:
        estudiantes_visibles = Estudiante.objects.all()
        if empleado:
            estudiantes_visibles = estudiantes_visibles.filter(
                pk__in=filtrar_registros_docente(
                    RegistroAcademico.objects.all(),
                    docente,
                ).values('estudiante_id') if docente else []
            )
        estudiante = get_object_or_404(estudiantes_visibles, cedula=cedula)
        registros = registros.filter(estudiante=estudiante)
        titulo = 'Reporte individual de calificaciones'
        subtitulo = (
            f'Estudiante: {escape(f"{estudiante.nombre} {estudiante.apellido}")} | '
            f'Cédula: {escape(estudiante.cedula or "No registrada")} | Grado: {escape(estudiante.grado or "No asignado")}'
        )
        nombre_archivo = f'calificaciones-{estudiante.cedula or estudiante.pk}.pdf'
    else:
        titulo = 'Reporte grupal de calificaciones'
        subtitulo = f'Registros incluidos: {registros.count()}'
        nombre_archivo = 'calificaciones-grupo.pdf'

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    filas = [
        [
            escape(f'{registro.estudiante.nombre} {registro.estudiante.apellido}'),
            escape(registro.estudiante.grado),
            escape(registro.area),
            escape(registro.periodo),
            escape(registro.get_lapso_display() if registro.lapso else 'Histórico'),
            escape(registro.tipo_evaluacion or '-'),
            escape(registro.nota or 'Pendiente'),
            f'{registro.porcentaje}%' if registro.porcentaje is not None else '-',
            escape(registro.estado or 'Pendiente'),
        ]
        for registro in registros
    ]
    crear_reporte_academico_pdf(
        response,
        titulo,
        subtitulo,
        ['Estudiante', 'Grado', 'Área', 'Período', 'Lapso', 'Evaluación', 'Nota', 'Porcentaje', 'Estado'],
        filas,
        [1.6 * inch, 0.65 * inch, 1.2 * inch, 0.8 * inch, 0.8 * inch, 1.25 * inch, 0.45 * inch, 0.7 * inch, 0.8 * inch],
    )
    return response


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def admin_crear_registro_academico(request):
    if request.method == 'POST':
        form = RegistroAcademicoForm(request.POST, actor=request.user)
        if form.is_valid():
            registro = form.save()
            _, resultados, _ = generar_constancia_y_notificar(registro)
            _notificar_resultado_constancia(request, resultados)
            return redirect('admin_registro_academico')
    else:
        form = RegistroAcademicoForm(actor=request.user)
    return render(request, 'escuelaApp/admin_custom/crear_registro_academico.html', {
        'form': form,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def admin_editar_registro_academico(request, registro_id):
    empleado, docente = perfil_docente_usuario(request.user)
    registros = RegistroAcademico.objects.all()
    if empleado:
        registros = filtrar_registros_docente(registros, docente) if docente else registros.none()
    registro = get_object_or_404(registros, pk=registro_id)
    if request.method == 'POST':
        form = RegistroAcademicoForm(request.POST, instance=registro, actor=request.user)
        if form.is_valid():
            registro = form.save()
            _, resultados, _ = generar_constancia_y_notificar(registro)
            _notificar_resultado_constancia(request, resultados)
            return redirect('admin_registro_academico')
    else:
        form = RegistroAcademicoForm(instance=registro, actor=request.user)

    return render(request, 'escuelaApp/admin_custom/editar_registro_academico.html', {
        'form': form,
        'registro': registro,
    })


@active_staff_required
@staff_member_required
@role_required('DIRECTORA', 'SUBDIRECTORA', 'COORD', 'DOCENTE', 'PROFESOR')
def descargar_constancia_calificacion(request, registro_id):
    empleado, docente = perfil_docente_usuario(request.user)
    registros = RegistroAcademico.objects.all()
    if empleado:
        registros = filtrar_registros_docente(registros, docente) if docente else registros.none()
    constancia = get_object_or_404(
        ConstanciaCalificacion.objects.select_related('registro__estudiante').filter(
            registro__in=registros
        ),
        registro_id=registro_id,
    )
    return FileResponse(
        constancia.archivo.open('rb'),
        as_attachment=True,
        filename=f'constancia-calificacion-{registro_id}.pdf',
        content_type='application/pdf',
    )
