from pathlib import Path

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import InformacionEscuela


def crear_reporte_academico_pdf(response, titulo, subtitulo, encabezados, filas, anchos):
    informacion = InformacionEscuela.objects.first()
    nombre_institucion = (
        informacion.nombre if informacion and informacion.nombre
        else 'E.B. Elba Rosa de Acevedo'
    )
    logo_path = None
    if informacion and informacion.logo_path:
        configurado = Path(informacion.logo_path)
        if not configurado.is_absolute():
            configurado = Path(settings.BASE_DIR) / 'static' / informacion.logo_path
        if configurado.is_file():
            logo_path = configurado
    if logo_path is None:
        logo_predeterminado = Path(settings.BASE_DIR) / 'static' / 'img' / 'Logo_Escuela.png'
        if logo_predeterminado.is_file():
            logo_path = logo_predeterminado

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(letter),
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=1.35 * inch,
        bottomMargin=0.55 * inch,
        title=titulo,
        author=nombre_institucion,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='SchoolReportTitle',
        parent=styles['Title'],
        alignment=TA_CENTER,
        textColor=colors.HexColor('#174a6e'),
        fontSize=16,
        leading=20,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name='SchoolReportCell',
        parent=styles['BodyText'],
        fontSize=8,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name='SchoolReportHeader',
        parent=styles['SchoolReportCell'],
        textColor=colors.white,
    ))
    elements = [
        Paragraph(titulo, styles['SchoolReportTitle']),
        Paragraph(subtitulo, styles['Normal']),
        Spacer(1, 10),
    ]
    table_rows = [[Paragraph(f'<b>{label}</b>', styles['SchoolReportHeader']) for label in encabezados]]
    table_rows.extend(
        [Paragraph(str(value), styles['SchoolReportCell']) for value in fila]
        for fila in filas
    )
    table = Table(table_rows, colWidths=anchos, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#174a6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)

    def dibujar_membrete(canvas, doc):
        canvas.saveState()
        page_width, page_height = landscape(letter)
        if logo_path:
            canvas.drawImage(
                str(logo_path),
                0.55 * inch,
                page_height - 0.92 * inch,
                width=0.68 * inch,
                height=0.68 * inch,
                preserveAspectRatio=True,
                mask='auto',
                anchor='c',
            )
        canvas.setFillColor(colors.HexColor('#174a6e'))
        canvas.setFont('Helvetica-Bold', 11)
        canvas.drawCentredString(page_width / 2, page_height - 0.48 * inch, nombre_institucion)
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.line(0.5 * inch, page_height - 1.05 * inch, page_width - 0.5 * inch, page_height - 1.05 * inch)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.setFont('Helvetica', 8)
        canvas.drawString(0.5 * inch, 0.3 * inch, 'Documento de uso institucional')
        canvas.drawRightString(page_width - 0.5 * inch, 0.3 * inch, f'Generado: {timezone.localdate():%d/%m/%Y} | Página {doc.page}')
        canvas.restoreState()

    document.build(elements, onFirstPage=dibujar_membrete, onLaterPages=dibujar_membrete)
