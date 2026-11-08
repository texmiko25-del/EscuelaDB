import re
from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .registro_academico import LAPSOS_ESCOLARES, RegistroAcademico
from .storage import PrivateDocumentsStorage


HORARIO_JORNADA_INICIO = time(8, 0)
HORARIO_JORNADA_FIN = time(13, 0)


class ConfiguracionDashboard(models.Model):
    titulo_panel = models.CharField(max_length=150, default='Mi Panel de Control')
    mensaje_bienvenida = models.TextField(blank=True, null=True)
    mantenimiento_activo = models.BooleanField(default=False)

    imagen_portada = models.ImageField(
        upload_to='portadas/',
        null=True,
        blank=True,
        verbose_name='Imagen Principal'
    )
    color_fondo = models.CharField(
        max_length=7,
        default='#2d6cdf',
        verbose_name='Color Principal (HEX)'
    )
    horario_atencion = models.CharField(
        max_length=200,
        default='Lunes a Viernes 7:00 AM - 1:00 PM',
        verbose_name='Horario de la institución'
    )
    direccion = models.CharField(
        max_length=250,
        default='Dirección no especificada',
        verbose_name='Dirección'
    )
    telefono_email = models.CharField(
        max_length=150,
        default='- / -',
        verbose_name='Teléfono / Email'
    )
    fecha_inicio_clases = models.DateField(
        null=True,
        blank=True,
        verbose_name='Fecha de inicio de clases'
    )

    def __str__(self):
        return self.titulo_panel


class Representante(models.Model):
    ESTADO_CIVIL_CHOICES = [
        ('SOLTERO', 'Soltero(a)'),
        ('CASADO', 'Casado(a)'),
        ('UNION_LIBRE', 'Unión libre'),
        ('DIVORCIADO', 'Divorciado(a)'),
        ('VIUDO', 'Viudo(a)'),
    ]

    nombre = models.CharField(max_length=100, blank=True)
    apellido = models.CharField(max_length=100, blank=True)
    cedula = models.CharField(max_length=20, unique=True, db_index=True, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    ocupacion = models.CharField(max_length=100, blank=True, null=True)
    parentesco = models.CharField(max_length=50, blank=True, null=True)
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True)
    nacionalidad = models.CharField(max_length=50, blank=True, null=True)
    partida_nacimiento = models.CharField(max_length=50, blank=True, null=True)
    ubicacion = models.CharField(max_length=200, blank=True, null=True)
    es_tutor_legal = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class Estudiante(models.Model):
    SECCIONES = [(letra, letra) for letra in 'ABC']

    SEXO_CHOICES = [
        ('F', 'Femenino'),
        ('M', 'Masculino'),
        ('O', 'Otro / No especificado'),
    ]

    nombre = models.CharField(max_length=100, blank=True)
    apellido = models.CharField(max_length=100, blank=True)
    cedula = models.CharField(max_length=20, unique=True, db_index=True, blank=True, null=True)
    fecha_nacimiento = models.DateField(blank=True, null=True, verbose_name='Fecha de nacimiento')
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, default='O')
    nacionalidad = models.CharField(max_length=50, default='No especificada')
    grado = models.CharField(max_length=50, blank=True)
    seccion = models.CharField(
        max_length=20,
        choices=SECCIONES,
        blank=True,
        verbose_name='Sección',
    )
    partida_nacimiento = models.CharField(max_length=50, blank=True, null=True)
    matricula = models.CharField(max_length=20, unique=True, blank=True, null=True, db_index=True, verbose_name='Matrícula')
    telefono = models.CharField(max_length=20, blank=True, null=True)
    ubicacion = models.CharField(max_length=200, blank=True, null=True)
    representante = models.ForeignKey(
        Representante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estudiantes'
    )

    def generar_cedula_escolar(self):
        if not self.representante:
            return None

        base_representante = re.sub(r'\D', '', str(self.representante.cedula or ''))
        if not base_representante:
            return None

        contador = Estudiante.objects.filter(
            representante=self.representante
        ).exclude(pk=self.pk).count() + 1
        return f'{base_representante}{contador:03d}'

    def generar_matricula(self):
        contador = Estudiante.objects.exclude(pk=self.pk).count() + 1
        return f'MAT-{contador:03d}'

    def save(self, *args, **kwargs):
        if self.representante_id and not self.cedula:
            identificacion_escolar = self.generar_cedula_escolar()
            if identificacion_escolar:
                self.cedula = identificacion_escolar
        if not self.matricula:
            self.matricula = self.generar_matricula()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class Asistencia(models.Model):
    ESTADOS_ASISTENCIA = [
        ('PRESENTE', 'Presente'),
        ('AUSENTE', 'Ausente'),
        ('TARDANZA', 'Tardanza'),
        ('JUSTIFICADO', 'Justificado'),
    ]

    estudiante = models.ForeignKey(
        Estudiante,
        on_delete=models.CASCADE,
        related_name='asistencias'
    )
    fecha = models.DateField(default=timezone.now)
    estado = models.CharField(max_length=20, choices=ESTADOS_ASISTENCIA, default='PRESENTE')
    observaciones = models.TextField(blank=True, null=True)
    registrado_por = models.ForeignKey(
        'escuelaApp.Empleado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asistencias_registradas'
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('estudiante', 'fecha')
        ordering = ['-fecha', '-fecha_registro']
        verbose_name = 'Asistencia'
        verbose_name_plural = 'Asistencias'

    def __str__(self):
        return f"{self.estudiante} - {self.get_estado_display()} ({self.fecha})"


class ResumenAsistenciaLapso(models.Model):
    estudiante = models.ForeignKey(
        'escuelaApp.Estudiante',
        on_delete=models.CASCADE,
        related_name='resumenes_asistencia_lapso',
    )
    registrado_por = models.ForeignKey(
        'escuelaApp.Empleado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resumenes_asistencia_registrados',
    )
    periodo = models.CharField(max_length=9)
    lapso = models.CharField(max_length=10, choices=LAPSOS_ESCOLARES)
    presentes = models.PositiveIntegerField(default=0)
    ausentes = models.PositiveIntegerField(default=0)
    tardanzas = models.PositiveIntegerField(default=0)
    justificadas = models.PositiveIntegerField(default=0)
    observaciones = models.TextField(blank=True)
    seguimiento = models.TextField(blank=True)
    fecha_registro = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-periodo', 'lapso', 'estudiante__apellido', 'estudiante__nombre']
        constraints = [
            models.UniqueConstraint(
                fields=['estudiante', 'periodo', 'lapso'],
                name='unique_resumen_asistencia_estudiante_lapso',
            ),
        ]
        verbose_name = 'Resumen de asistencia por lapso'
        verbose_name_plural = 'Resúmenes de asistencia por lapso'

    def __str__(self):
        return f'{self.estudiante} - {self.periodo} - {self.get_lapso_display()}'


class SolicitudMatricula(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('APROBADA', 'Aprobada'),
        ('RECHAZADA', 'Rechazada'),
    ]
    GRADOS = [
        ('1RO', 'Primero'),
        ('2DO', 'Segundo'),
        ('3RO', 'Tercero'),
        ('4TO', 'Cuarto'),
        ('5TO', 'Quinto'),
        ('6TO', 'Sexto'),
    ]
    VALIDAR_DOCUMENTO = FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png'])

    estudiante_nombre = models.CharField(max_length=100)
    estudiante_apellido = models.CharField(max_length=100)
    estudiante_fecha_nacimiento = models.DateField()
    estudiante_sexo = models.CharField(max_length=1, choices=Estudiante.SEXO_CHOICES)
    estudiante_nacionalidad = models.CharField(max_length=50, default='Venezolana')
    grado = models.CharField(max_length=3, choices=GRADOS)
    partida_nacimiento = models.CharField(max_length=50)
    estudiante_telefono = models.CharField(max_length=20, blank=True)
    estudiante_ubicacion = models.CharField(max_length=200, blank=True)
    representante_nombre = models.CharField(max_length=100)
    representante_apellido = models.CharField(max_length=100)
    representante_cedula = models.CharField(max_length=20)
    representante_telefono = models.CharField(max_length=20)
    representante_email = models.EmailField(blank=True)
    representante_parentesco = models.CharField(max_length=50)
    representante_nacionalidad = models.CharField(max_length=50, default='Venezolana')
    documento_representante = models.FileField(
        upload_to='matriculas/%Y/%m/',
        storage=PrivateDocumentsStorage(),
        validators=[VALIDAR_DOCUMENTO],
    )
    documento_partida_nacimiento = models.FileField(
        upload_to='matriculas/%Y/%m/',
        storage=PrivateDocumentsStorage(),
        validators=[VALIDAR_DOCUMENTO],
    )
    observaciones_representante = models.TextField(blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='PENDIENTE')
    observaciones_revision = models.TextField(blank=True)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    revisada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_matricula_revisadas',
    )
    estudiante = models.OneToOneField(
        Estudiante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitud_matricula',
    )

    class Meta:
        ordering = ['-fecha_solicitud']
        verbose_name = 'Solicitud de matrícula'
        verbose_name_plural = 'Solicitudes de matrícula'

    def __str__(self):
        return f'{self.estudiante_nombre} {self.estudiante_apellido} - {self.get_estado_display()}'


class Docente(models.Model):
    nombre = models.CharField(max_length=100, blank=True)
    apellido = models.CharField(max_length=100, blank=True)
    cedula = models.CharField(max_length=20, unique=True, db_index=True, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    especialidad = models.CharField(max_length=100, blank=True)
    carga_horaria = models.PositiveIntegerField(default=0)
    estudiantes_asignados = models.ManyToManyField(
        Estudiante,
        through='DocenteEstudiante',
        related_name='docentes_asignados',
        blank=True,
    )

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class DocenteEstudiante(models.Model):
    docente = models.ForeignKey(
        Docente,
        on_delete=models.CASCADE,
        related_name='asignaciones_estudiantes',
    )
    estudiante = models.ForeignKey(
        Estudiante,
        on_delete=models.CASCADE,
        related_name='asignaciones_docentes',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['docente', 'estudiante'],
                name='unique_docente_estudiante',
            ),
        ]
        verbose_name = 'Estudiante asignado a docente'
        verbose_name_plural = 'Estudiantes asignados a docentes'

    def __str__(self):
        return f'{self.estudiante} asignado a {self.docente}'


class Empleado(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    cedula = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text='Cédula de identidad (ID único)'
    )
    telefono = models.CharField(max_length=20, blank=True)
    acepta_notificaciones_whatsapp = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    notificar_contactos_telegram = models.BooleanField(default=False)

    CARGOS = [
        ('DIRECTORA', 'Director/a'),
        ('SUBDIRECTORA', 'Subdirector/a'),
        ('COORD', 'Coordinador/a Pedagógico/a'),
        ('DOCENTE', 'Docente'),
        ('PROFESOR', 'Profesor/a'),
        ('ASISTENTE', 'Asistente'),
    ]

    cargo = models.CharField(max_length=20, choices=CARGOS)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.cedula}) - {self.get_cargo_display()}"


class AsistenciaPersonal(models.Model):
    ESTADOS = [
        ('PRESENTE', 'Presente'),
        ('AUSENTE', 'Ausente'),
        ('TARDANZA', 'Tardanza'),
        ('JUSTIFICADO', 'Justificado'),
    ]

    empleado = models.ForeignKey(
        Empleado,
        on_delete=models.CASCADE,
        related_name='asistencias_personal',
    )
    fecha = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PRESENTE')
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asistencias_personal_registradas',
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', 'empleado__user__last_name', 'empleado__user__first_name']
        constraints = [
            models.UniqueConstraint(fields=['empleado', 'fecha'], name='unique_asistencia_personal_empleado_fecha'),
        ]
        verbose_name = 'Asistencia de personal'
        verbose_name_plural = 'Asistencias de personal'

    def __str__(self):
        return f'{self.empleado} - {self.get_estado_display()} ({self.fecha})'


class Asignacion(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    docente = models.ForeignKey(Empleado, on_delete=models.CASCADE)
    area = models.CharField(max_length=100)
    periodo = models.CharField(max_length=20, default='2026-2027')
    nota = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    evaluacion = models.CharField(max_length=100, blank=True, null=True)
    comentarios = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('estudiante', 'docente', 'area', 'periodo')

    def __str__(self):
        return f"{self.estudiante.cedula} asignado a {self.docente.cedula} en {self.area} ({self.periodo})"


class Horario(models.Model):
    DIAS_SEMANA = [
        ('LU', 'Lunes'),
        ('MA', 'Martes'),
        ('MI', 'Miércoles'),
        ('JU', 'Jueves'),
        ('VI', 'Viernes'),
    ]
    
    ANOS_ESCOLARES = [
        ('1ANO', '1er Grado'),
        ('2ANO', '2do Grado'),
        ('3ANO', '3er Grado'),
        ('4ANO', '4to Grado'),
        ('5ANO', '5to Grado'),
        ('6ANO', '6to Grado'),
    ]

    ano = models.CharField(max_length=10, choices=ANOS_ESCOLARES, verbose_name='Grado')
    materia = models.CharField(max_length=100)
    docente = models.ForeignKey(Docente, on_delete=models.CASCADE)
    dia = models.CharField(max_length=2, choices=DIAS_SEMANA)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    class Meta:
        verbose_name = 'Horario'
        verbose_name_plural = 'Horarios'
        ordering = ['ano', 'dia', 'hora_inicio']
        constraints = [
            models.UniqueConstraint(
                fields=['ano', 'dia', 'hora_inicio', 'hora_fin'],
                name='unique_horario_grado_dia_horas',
            ),
        ]

    def clean(self):
        super().clean()

        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError('La hora de inicio debe ser anterior a la hora de fin.')

        if (
            (self.hora_inicio and self.hora_inicio < HORARIO_JORNADA_INICIO)
            or (self.hora_fin and self.hora_fin > HORARIO_JORNADA_FIN)
        ):
            raise ValidationError(
                'Verifique el horario. Solo se permiten horas desde las 8:00 a. m. hasta la 1:00 p. m.'
            )

        if not self.ano or not self.dia or not self.hora_inicio or not self.hora_fin:
            return

        horarios = Horario.objects.filter(dia=self.dia).exclude(pk=self.pk)

        grado_solapado = horarios.filter(
            ano=self.ano,
            hora_inicio__lt=self.hora_fin,
            hora_fin__gt=self.hora_inicio,
        ).exists()
        if grado_solapado:
            raise ValidationError(
                'No se puede crear este horario porque el grado ya tiene una clase ocupando esa hora. Elige otra franja.'
            )

        if self.docente_id:
            docente_solapado = horarios.filter(
                docente_id=self.docente_id,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio,
            ).exists()
            if docente_solapado:
                raise ValidationError(
                    'No se puede crear este horario porque el profesor ya tiene una clase ocupando esa hora. Elige otra franja o un profesor distinto.'
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_ano_display()} - {self.materia} ({self.get_dia_display()})"


class InformacionEscuela(models.Model):
    nombre = models.CharField(max_length=200, default='E.B. Elba Rosa de Acevedo')
    direccion = models.CharField(max_length=250, blank=True, null=True)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    horario = models.CharField(max_length=150, blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    mision = models.TextField(blank=True, null=True)
    vision = models.TextField(blank=True, null=True)
    logo_path = models.CharField(max_length=250, blank=True, null=True, help_text='Ruta estática al logo, p.ej. img/logo.png')

    class Meta:
        verbose_name = 'Información de la escuela'
        verbose_name_plural = 'Información de la escuela'

    def __str__(self):
        return self.nombre


class SobreNosotros(models.Model):
    titulo = models.CharField(max_length=200, default='Sobre la escuela', verbose_name='Título Principal')
    contenido = models.TextField(default='Escribe aquí la historia y detalles de la institución...', verbose_name='Contenido / Historia')
    imagen = models.ImageField(upload_to='institucion/', null=True, blank=True, verbose_name='Imagen de la Institución')

    class Meta:
        verbose_name = 'Sobre Nosotros'
        verbose_name_plural = 'Sobre Nosotros'

    def __str__(self):
        return 'Configuración de Sobre Nosotros'


class ContactoMensaje(models.Model):
    nombre = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    acepta_whatsapp = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    asunto = models.CharField(max_length=200, blank=True)
    mensaje = models.TextField()
    fecha_enviado = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    class Meta:
        ordering = ['-fecha_enviado']
        verbose_name = 'Mensaje de contacto'
        verbose_name_plural = 'Mensajes de contacto'

    def __str__(self):
        return f"{self.nombre} - {self.asunto or 'Sin asunto'} ({self.fecha_enviado:%Y-%m-%d})"


class ConstanciaCalificacion(models.Model):
    registro = models.OneToOneField(
        RegistroAcademico,
        on_delete=models.CASCADE,
        related_name='constancia',
    )
    archivo = models.FileField(
        storage=PrivateDocumentsStorage(),
        upload_to='constancias/calificaciones/%Y/%m/',
    )
    revision = models.PositiveIntegerField(default=1)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Constancia de calificación'
        verbose_name_plural = 'Constancias de calificaciones'

    def __str__(self):
        return f'Constancia de {self.registro.estudiante} - {self.registro.area}'


class DestinatarioAvisoCalificacion(models.Model):
    correo = models.EmailField(unique=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['correo']
        verbose_name = 'Destinatario adicional de calificaciones'
        verbose_name_plural = 'Destinatarios adicionales de calificaciones'

    def __str__(self):
        return self.correo


class ComunicadoRepresentantes(models.Model):
    asunto = models.CharField(max_length=200)
    mensaje = models.TextField()
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='comunicados_representantes',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Comunicado a representantes'
        verbose_name_plural = 'Comunicados a representantes'

    def __str__(self):
        return self.asunto


class EntregaComunicadoRepresentante(models.Model):
    ESTADOS = [('ENVIADO', 'Enviado'), ('ERROR', 'Error')]

    comunicado = models.ForeignKey(
        ComunicadoRepresentantes,
        on_delete=models.CASCADE,
        related_name='entregas',
    )
    representante = models.ForeignKey(
        Representante,
        on_delete=models.SET_NULL,
        null=True,
        related_name='entregas_comunicados',
    )
    correo = models.EmailField()
    estado = models.CharField(max_length=10, choices=ESTADOS)
    error = models.TextField(blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['correo']
        verbose_name = 'Entrega de comunicado'
        verbose_name_plural = 'Entregas de comunicados'

    def __str__(self):
        return f'{self.correo} - {self.get_estado_display()}'


class NotificacionCalificacion(models.Model):
    CANALES = [('EMAIL', 'Correo'), ('WHATSAPP', 'WhatsApp')]
    ESTADOS = [('ENVIADO', 'Enviado'), ('ERROR', 'Error')]

    constancia = models.ForeignKey(
        ConstanciaCalificacion,
        on_delete=models.CASCADE,
        related_name='notificaciones',
    )
    revision = models.PositiveIntegerField()
    canal = models.CharField(max_length=10, choices=CANALES)
    destinatario = models.CharField(max_length=254)
    estado = models.CharField(max_length=10, choices=ESTADOS)
    ultimo_error = models.TextField(blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Notificación de calificación'
        verbose_name_plural = 'Notificaciones de calificaciones'

    def __str__(self):
        return f'{self.get_canal_display()} a {self.destinatario}: {self.get_estado_display()}'


class ReporteSistemaDiario(models.Model):
    fecha_reporte = models.DateField(unique=True)
    periodo_inicio = models.DateField()
    periodo_fin = models.DateField()
    archivo = models.FileField(
        storage=PrivateDocumentsStorage(),
        upload_to='reportes/sistema/%Y/%m/',
    )
    resumen = models.TextField()
    estudiantes_criticos = models.PositiveIntegerField(default=0)
    generado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_reporte']
        verbose_name = 'Reporte diario del sistema'
        verbose_name_plural = 'Reportes diarios del sistema'

    def __str__(self):
        return f'Reporte diario {self.fecha_reporte:%Y-%m-%d}'


class EntregaReporteSistema(models.Model):
    CANALES = [('EMAIL', 'Correo'), ('WHATSAPP', 'WhatsApp')]
    ESTADOS = [('ENVIADO', 'Enviado'), ('ERROR', 'Error')]

    reporte = models.ForeignKey(
        ReporteSistemaDiario,
        on_delete=models.CASCADE,
        related_name='entregas',
    )
    canal = models.CharField(max_length=10, choices=CANALES)
    destinatario = models.CharField(max_length=254)
    estado = models.CharField(max_length=10, choices=ESTADOS)
    intentos = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['canal', 'destinatario']
        constraints = [
            models.UniqueConstraint(
                fields=['reporte', 'canal', 'destinatario'],
                name='unique_entrega_reporte_sistema_destino',
            ),
        ]
        verbose_name = 'Entrega de reporte del sistema'
        verbose_name_plural = 'Entregas de reportes del sistema'

    def __str__(self):
        return f'{self.get_canal_display()} {self.destinatario}: {self.get_estado_display()}'