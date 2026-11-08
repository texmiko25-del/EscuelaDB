from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import (
    ComunicadoRepresentantes,
    ConfiguracionDashboard,
    ContactoMensaje,
    ConstanciaCalificacion,
    DestinatarioAvisoCalificacion,
    EntregaComunicadoRepresentante,
    InformacionEscuela,
    NotificacionCalificacion,
    EntregaReporteSistema,
    ReporteSistemaDiario,
)
from .models import Horario


@admin.register(ConfiguracionDashboard)
class ConfiguracionDashboardAdmin(admin.ModelAdmin):
    list_display = ('titulo_panel', 'mantenimiento_activo')
    search_fields = ('titulo_panel',)


@admin.register(InformacionEscuela)
class InformacionEscuelaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'email')
    search_fields = ('nombre', 'direccion')


@admin.register(ContactoMensaje)
class ContactoMensajeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'asunto', 'email', 'fecha_enviado', 'leido')
    list_filter = ('leido',)
    search_fields = ('nombre', 'email', 'asunto')
    readonly_fields = ('fecha_enviado',)


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ('ano', 'materia', 'docente', 'dia', 'hora_inicio', 'hora_fin')
    list_filter = ('ano', 'dia', 'docente')
    search_fields = ('materia',)


@admin.register(ConstanciaCalificacion)
class ConstanciaCalificacionAdmin(admin.ModelAdmin):
    list_display = ('registro', 'revision', 'descargar_pdf', 'creada_en', 'actualizada_en')
    search_fields = ('registro__estudiante__nombre', 'registro__estudiante__apellido', 'registro__area')
    fields = ('registro', 'descargar_pdf', 'revision', 'creada_en', 'actualizada_en')
    readonly_fields = fields

    @admin.display(description='Constancia privada')
    def descargar_pdf(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = reverse('descargar_constancia_calificacion', args=[obj.registro_id])
        return format_html('<a href="{}">Descargar PDF</a>', url)


@admin.register(NotificacionCalificacion)
class NotificacionCalificacionAdmin(admin.ModelAdmin):
    list_display = ('constancia', 'revision', 'canal', 'destinatario', 'estado', 'enviado_en')
    list_filter = ('canal', 'estado')
    search_fields = ('destinatario', 'constancia__registro__estudiante__nombre')
    readonly_fields = ('constancia', 'revision', 'canal', 'destinatario', 'estado', 'ultimo_error', 'enviado_en', 'creado_en')


@admin.register(DestinatarioAvisoCalificacion)
class DestinatarioAvisoCalificacionAdmin(admin.ModelAdmin):
    list_display = ('correo', 'activo', 'creado_en')
    list_filter = ('activo',)
    search_fields = ('correo',)
    readonly_fields = ('creado_en',)


@admin.register(ComunicadoRepresentantes)
class ComunicadoRepresentantesAdmin(admin.ModelAdmin):
    list_display = ('asunto', 'creado_por', 'creado_en')
    search_fields = ('asunto', 'mensaje')
    readonly_fields = ('asunto', 'mensaje', 'creado_por', 'creado_en')


@admin.register(EntregaComunicadoRepresentante)
class EntregaComunicadoRepresentanteAdmin(admin.ModelAdmin):
    list_display = ('comunicado', 'representante', 'correo', 'estado', 'enviado_en')
    list_filter = ('estado',)
    search_fields = ('correo', 'representante__nombre', 'representante__apellido', 'comunicado__asunto')
    readonly_fields = ('comunicado', 'representante', 'correo', 'estado', 'error', 'enviado_en')


@admin.register(ReporteSistemaDiario)
class ReporteSistemaDiarioAdmin(admin.ModelAdmin):
    list_display = ('fecha_reporte', 'periodo_inicio', 'periodo_fin', 'estudiantes_criticos', 'generado_en')
    readonly_fields = ('fecha_reporte', 'periodo_inicio', 'periodo_fin', 'archivo', 'resumen', 'estudiantes_criticos', 'generado_en')


@admin.register(EntregaReporteSistema)
class EntregaReporteSistemaAdmin(admin.ModelAdmin):
    list_display = ('reporte', 'canal', 'destinatario', 'estado', 'intentos', 'enviado_en')
    list_filter = ('canal', 'estado')
    search_fields = ('destinatario',)
    readonly_fields = ('reporte', 'canal', 'destinatario', 'estado', 'intentos', 'error', 'enviado_en')
