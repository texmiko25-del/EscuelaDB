from functools import partial
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.conf import settings
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo

from .decorators import active_staff_required, role_required
from .forms_reportes import FiltrosReporteSistemaForm
from .models import InformacionEscuela, ReporteSistemaDiario
from .reportes_sistema import datos_reporte_interactivo, enviar_reporte_diario
from .report_delivery import enviar_reporte_a_directora

staff_member_required = partial(django_staff_member_required, login_url='login')
REPORT_ROLES = ('DIRECTORA', 'SUBDIRECTORA')
TIPOS_REPORTE = (
    {'id': 'detalle', 'nombre': 'Detalle', 'descripcion': 'Registros académicos individualizados por estudiante.'},
    {'id': 'resumen', 'nombre': 'Resumen', 'descripcion': 'Indicadores generales de matrícula, asistencia y notas.'},
    {'id': 'filtros', 'nombre': 'Filtros múltiples', 'descripcion': 'Cruza grado, período, área, fechas y porcentaje.'},
    {'id': 'historico', 'nombre': 'Histórico', 'descripcion': 'Evolución mensual de registros y asistencia.'},
    {'id': 'estadistico', 'nombre': 'Estadístico / gráfico', 'descripcion': 'Distribución de calificaciones de A a F.'},
)


def _filas_reporte_excel(tipo, datos):
    if tipo == 'detalle':
        encabezados = ['Estudiante', 'Matrícula', 'Grado', 'Representante', 'Correo representante', 'Registros académicos', 'Promedio', 'Ausencias']
        filas = []
        for item in datos['estudiantes']:
            estudiante = item['estudiante']
            representante = estudiante.representante
            filas.append([
                f'{estudiante.nombre} {estudiante.apellido}',
                estudiante.matricula,
                estudiante.grado,
                f'{representante.nombre} {representante.apellido}' if representante else '',
                representante.email if representante else '',
                item['registros'],
                item['promedio'],
                item['ausencias'],
            ])
    elif tipo == 'filtros':
        encabezados = ['Estudiante', 'Matrícula', 'Grado', 'Área', 'Período', 'Evaluación', 'Nota', 'Porcentaje', 'Estado', 'Docente', 'Fecha']
        filas = []
        for registro in datos['registros']:
            docente = registro.docente.user.get_full_name() if registro.docente and registro.docente.user else ''
            filas.append([
                f'{registro.estudiante.nombre} {registro.estudiante.apellido}',
                registro.estudiante.matricula,
                registro.estudiante.grado,
                registro.area,
                registro.periodo,
                registro.tipo_evaluacion,
                registro.nota,
                registro.porcentaje,
                registro.estado,
                docente,
                registro.fecha_registro.strftime('%Y-%m-%d'),
            ])
    elif tipo == 'resumen':
        encabezados = ['Indicador', 'Resultado']
        filas = [[item['etiqueta'], item['valor']] for item in datos['indicadores']]
    elif tipo == 'historico':
        encabezados = ['Mes', 'Registros académicos', 'Promedio', 'Asistencias', 'Ausencias']
        filas = [
            [item['etiqueta'], item['registros'], item['promedio'], item['asistencias'], item['ausencias']]
            for item in datos['meses']
        ]
    else:
        encabezados = ['Calificación', 'Cantidad', 'Porcentaje del total']
        filas = [
            [item['etiqueta'], item['cantidad'], item['ancho'] / 100]
            for item in datos['distribucion']
        ]
    return encabezados, filas


def _celda_segura(valor):
    if isinstance(valor, str) and valor.startswith(('=', '+', '-', '@')):
        return f"'{valor}"
    return valor


def _exportar_reporte_excel(tipo, datos, filtros):
    reporte = next(item for item in TIPOS_REPORTE if item['id'] == tipo)
    institucion = InformacionEscuela.objects.first()
    nombre_institucion = (institucion.nombre if institucion else '') or 'E.B. Elba Rosa de Acevedo'
    encabezados, filas = _filas_reporte_excel(tipo, datos)
    columnas = max(len(encabezados), 8)
    ultima_columna = __import__('openpyxl').utils.get_column_letter(columnas)

    libro = Workbook()
    hoja = libro.active
    hoja.title = 'Reporte'
    hoja.sheet_view.showGridLines = False
    hoja.freeze_panes = 'A11'
    hoja.merge_cells(start_row=1, start_column=2, end_row=1, end_column=columnas)
    hoja.merge_cells(start_row=2, start_column=2, end_row=2, end_column=columnas)
    hoja.cell(1, 2, nombre_institucion)
    hoja.cell(2, 2, reporte['nombre'].upper())
    hoja.row_dimensions[1].height = 42
    hoja.row_dimensions[2].height = 28
    color_verde = '174E43'
    color_verde_claro = 'E7F1ED'
    color_dorado = 'D8A441'
    relleno_titulo = PatternFill('solid', fgColor=color_verde)
    for fila in (1, 2):
        celda = hoja.cell(fila, 2)
        celda.fill = relleno_titulo
        celda.font = Font(name='Calibri', size=18 if fila == 1 else 12, bold=True, color='FFFFFF')
        celda.alignment = Alignment(vertical='center', horizontal='left')

    ruta_logo = Path(settings.BASE_DIR) / 'static' / 'img' / 'Logo_Escuela.png'
    if institucion and institucion.logo_path:
        logo_configurado = Path(institucion.logo_path)
        if not logo_configurado.is_absolute():
            logo_configurado = Path(settings.BASE_DIR) / 'static' / institucion.logo_path
        if logo_configurado.is_file():
            ruta_logo = logo_configurado
    if ruta_logo.is_file():
        emblema = ExcelImage(str(ruta_logo))
        emblema.width = 58
        emblema.height = 64
        hoja.add_image(emblema, 'A1')

    hoja.merge_cells(start_row=4, start_column=1, end_row=4, end_column=columnas)
    hoja.cell(4, 1, 'FICHA DEL REPORTE')
    hoja.cell(4, 1).fill = PatternFill('solid', fgColor=color_dorado)
    hoja.cell(4, 1).font = Font(bold=True, color='FFFFFF')
    hoja.cell(4, 1).alignment = Alignment(vertical='center')
    hoja.row_dimensions[4].height = 23

    periodo = filtros.get('periodo') or 'Todos'
    grado = filtros.get('grado') or 'Todos'
    area = filtros.get('area') or 'Todas'
    fecha_desde = filtros.get('fecha_desde')
    fecha_hasta = filtros.get('fecha_hasta')
    minimo = filtros.get('porcentaje_min')
    maximo = filtros.get('porcentaje_max')
    campos_ficha = [
        ('Tipo', reporte['nombre'], 'Generado', timezone.localtime().strftime('%d/%m/%Y %H:%M')),
        ('Grado', grado, 'Período', periodo),
        ('Área', area, 'Fechas', f"{fecha_desde or 'Sin inicio'} a {fecha_hasta or 'Hoy'}"),
        ('Porcentaje', f"{minimo if minimo is not None else 0}% a {maximo if maximo is not None else 100}%", 'Resultados', len(filas)),
    ]
    borde_fino = Side(style='thin', color='C8D8D2')
    for numero, (etiqueta_a, valor_a, etiqueta_b, valor_b) in enumerate(campos_ficha, start=5):
        for columna, valor, es_etiqueta in (
            (1, etiqueta_a, True), (2, valor_a, False),
            (4, etiqueta_b, True), (5, valor_b, False),
        ):
            celda = hoja.cell(numero, columna, valor)
            celda.fill = PatternFill('solid', fgColor=color_verde_claro if es_etiqueta else 'FFFFFF')
            celda.font = Font(bold=es_etiqueta, color=color_verde if es_etiqueta else '263238')
            celda.alignment = Alignment(vertical='center', wrap_text=True)
            celda.border = Border(bottom=borde_fino)
        hoja.row_dimensions[numero].height = 23

    fila_seccion = 10
    hoja.merge_cells(start_row=fila_seccion, start_column=1, end_row=fila_seccion, end_column=columnas)
    hoja.cell(fila_seccion, 1, 'RESULTADOS')
    hoja.cell(fila_seccion, 1).fill = PatternFill('solid', fgColor=color_verde)
    hoja.cell(fila_seccion, 1).font = Font(bold=True, color='FFFFFF')
    fila_encabezados = fila_seccion + 1
    for columna, titulo in enumerate(encabezados, start=1):
        celda = hoja.cell(fila_encabezados, columna, titulo)
        celda.fill = PatternFill('solid', fgColor='2C7162')
        celda.font = Font(bold=True, color='FFFFFF')
        celda.alignment = Alignment(vertical='center', wrap_text=True)
    for fila_numero, fila_datos in enumerate(filas, start=fila_encabezados + 1):
        for columna, valor in enumerate(fila_datos, start=1):
            celda = hoja.cell(fila_numero, columna, _celda_segura(valor))
            celda.alignment = Alignment(vertical='top', wrap_text=True)
        hoja.row_dimensions[fila_numero].height = 22

    if filas:
        referencia_tabla = f'A{fila_encabezados}:{__import__("openpyxl").utils.get_column_letter(len(encabezados))}{fila_encabezados + len(filas)}'
        tabla = Table(displayName=f'Reporte{tipo.capitalize()}', ref=referencia_tabla)
        tabla.tableStyleInfo = TableStyleInfo(
            name='TableStyleMedium4',
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        hoja.add_table(tabla)

    for columna in range(1, columnas + 1):
        letra = __import__('openpyxl').utils.get_column_letter(columna)
        ancho = max(
            (len(str(hoja.cell(fila, columna).value or '')) for fila in range(fila_encabezados, fila_encabezados + len(filas) + 1)),
            default=12,
        )
        hoja.column_dimensions[letra].width = min(max(ancho + 3, 14), 38)
    hoja.column_dimensions['A'].width = max(hoja.column_dimensions['A'].width, 22)
    hoja.column_dimensions['B'].width = max(hoja.column_dimensions['B'].width, 18)

    if tipo == 'estadistico':
        grafico = BarChart()
        grafico.type = 'bar'
        grafico.style = 10
        grafico.title = 'Distribución de calificaciones'
        grafico.x_axis.title = 'Proporción del total'
        grafico.y_axis.title = 'Calificación'
        grafico.add_data(Reference(hoja, min_col=3, min_row=fila_encabezados, max_row=fila_encabezados + len(filas)), titles_from_data=True)
        grafico.set_categories(Reference(hoja, min_col=1, min_row=fila_encabezados + 1, max_row=fila_encabezados + len(filas)))
        grafico.height = 7
        grafico.width = 13
        grafico.legend = None
        hoja.add_chart(grafico, 'E10')

    fila_pie = fila_encabezados + len(filas) + 3
    hoja.merge_cells(start_row=fila_pie, start_column=1, end_row=fila_pie, end_column=columnas)
    pie = hoja.cell(fila_pie, 1, f'{nombre_institucion} | Documento de uso institucional')
    pie.font = Font(italic=True, size=9, color='52645F')
    pie.alignment = Alignment(horizontal='center')
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.page_setup.orientation = 'landscape'
    hoja.page_setup.fitToWidth = 1
    hoja.page_setup.fitToHeight = 0
    hoja.print_title_rows = f'1:{fila_encabezados}'

    buffer = BytesIO()
    libro.save(buffer)
    respuesta = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    respuesta['Content-Disposition'] = f'attachment; filename="reporte-{tipo}.xlsx"'
    enviar_reporte_a_directora(
        f'reporte-{tipo}.xlsx',
        respuesta.content,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    return respuesta


@active_staff_required
@staff_member_required
@role_required(*REPORT_ROLES)
def historial_reportes_sistema(request):
    tipo = request.GET.get('tipo', 'resumen')
    ids_validos = {reporte['id'] for reporte in TIPOS_REPORTE}
    if tipo not in ids_validos:
        tipo = 'resumen'
    filtros_form = FiltrosReporteSistemaForm(request.GET if request.GET else {})
    datos_reporte = {}
    if filtros_form.is_valid():
        exportar = request.GET.get('exportar') == 'xlsx'
        datos_reporte = datos_reporte_interactivo(tipo, filtros_form.cleaned_data, completo=exportar)
        if exportar:
            return _exportar_reporte_excel(tipo, datos_reporte, filtros_form.cleaned_data)

    reportes = ReporteSistemaDiario.objects.annotate(
        envios_ok=Count('entregas', filter=Q(entregas__estado='ENVIADO')),
        envios_error=Count('entregas', filter=Q(entregas__estado='ERROR')),
    )[:30]
    return render(request, 'escuelaApp/admin_custom/reportes_sistema.html', {
        'reportes': reportes,
        'tipos_reporte': TIPOS_REPORTE,
        'tipo_reporte': tipo,
        'filtros_form': filtros_form,
        'datos_reporte': datos_reporte,
    })


@active_staff_required
@staff_member_required
@role_required(*REPORT_ROLES)
@require_POST
def generar_reporte_sistema_ahora(request):
    reporte, resumen = enviar_reporte_diario()
    if resumen['errores']:
        messages.warning(
            request,
            f"Reporte {reporte.fecha_reporte:%d/%m/%Y}: {resumen['enviados']} enviados y "
            f"{resumen['errores']} errores. Revisa el historial.",
        )
    elif not resumen['destinos']:
        messages.warning(request, 'Reporte generado, pero no hay destinatarios configurados.')
    else:
        messages.success(
            request,
            f"Reporte {reporte.fecha_reporte:%d/%m/%Y} enviado a {resumen['enviados']} destino(s).",
        )
    return redirect('historial_reportes_sistema')


@active_staff_required
@staff_member_required
@role_required(*REPORT_ROLES)
def descargar_reporte_sistema(request, reporte_id):
    reporte = get_object_or_404(ReporteSistemaDiario, pk=reporte_id)
    return FileResponse(
        reporte.archivo.open('rb'),
        as_attachment=True,
        filename=f'reporte-sistema-{reporte.fecha_reporte:%Y-%m-%d}.pdf',
        content_type='application/pdf',
    )