from django.db import models


LAPSOS_ESCOLARES = [
    ('LAPSO_1', 'Primer lapso'),
    ('LAPSO_2', 'Segundo lapso'),
    ('LAPSO_3', 'Tercer lapso'),
]


class RegistroAcademico(models.Model):
    CALIFICACIONES = [
        ('A', 'A'),
        ('B', 'B'),
        ('C', 'C'),
        ('D', 'D'),
        ('E', 'E'),
        ('F', 'F'),
    ]

    estudiante = models.ForeignKey(
        'escuelaApp.Estudiante',
        on_delete=models.CASCADE,
        related_name='registros_academicos'
    )
    asignacion = models.ForeignKey(
        'escuelaApp.Asignacion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_academicos'
    )
    docente = models.ForeignKey(
        'escuelaApp.Empleado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_academicos'
    )
    area = models.CharField(max_length=100)
    periodo = models.CharField(max_length=20, default='2026-2027')
    lapso = models.CharField(
        max_length=10,
        choices=LAPSOS_ESCOLARES,
        blank=True,
        null=True,
        default=None,
    )
    tipo_evaluacion = models.CharField(max_length=100, blank=True, null=True)
    nota = models.CharField(max_length=1, choices=CALIFICACIONES, blank=True, null=True)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    estado = models.CharField(max_length=50, blank=True, null=True, default='Pendiente')
    comentarios = models.TextField(blank=True, null=True)
    seguimiento = models.TextField(blank=True, null=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_registro']
        constraints = [
            models.UniqueConstraint(
                fields=['estudiante', 'area', 'periodo', 'lapso'],
                name='unique_nota_estudiante_materia_lapso',
            ),
        ]
        verbose_name = 'Registro académico'
        verbose_name_plural = 'Registros académicos'

    def __str__(self):
        return f"{self.estudiante.cedula or 'Sin cédula'} - {self.area} ({self.periodo}) - {self.nota or 'Sin nota'}"
