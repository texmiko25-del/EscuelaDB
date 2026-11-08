from django.db import migrations


PROFESORES_SEXTO = [
    ('Docente', 'Matemáticas', 'DOC-6TO-001', 'Matemáticas'),
    ('Docente', 'Lengua', 'DOC-6TO-002', 'Lengua y Literatura'),
    ('Docente', 'Ciencias', 'DOC-6TO-003', 'Ciencias Naturales'),
    ('Docente', 'Sociales', 'DOC-6TO-004', 'Ciencias Sociales'),
    ('Docente', 'Inglés', 'DOC-6TO-005', 'Inglés'),
    ('Docente', 'Educación Física', 'DOC-6TO-006', 'Educación Física'),
    ('Docente', 'Artística', 'DOC-6TO-007', 'Educación Artística'),
    ('Docente', 'Computación', 'DOC-6TO-008', 'Computación'),
]

HORARIOS_SEXTO = [
    ('Matemáticas', 'DOC-6TO-001', 'LU', '07:00', '07:45'),
    ('Lengua y Literatura', 'DOC-6TO-002', 'LU', '07:45', '08:30'),
    ('Ciencias Naturales', 'DOC-6TO-003', 'MA', '07:00', '07:45'),
    ('Ciencias Sociales', 'DOC-6TO-004', 'MA', '07:45', '08:30'),
    ('Inglés', 'DOC-6TO-005', 'MI', '07:00', '07:45'),
    ('Educación Física', 'DOC-6TO-006', 'MI', '07:45', '08:30'),
    ('Educación Artística', 'DOC-6TO-007', 'JU', '07:00', '07:45'),
    ('Computación', 'DOC-6TO-008', 'VI', '07:00', '07:45'),
]


def cargar_horario_sexto(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')

    docentes = {}
    for nombre, apellido, cedula, especialidad in PROFESORES_SEXTO:
        docente, _ = Docente.objects.get_or_create(
            cedula=cedula,
            defaults={
                'nombre': nombre,
                'apellido': apellido,
                'especialidad': especialidad,
                'carga_horaria': 1,
            },
        )
        docentes[cedula] = docente

    for materia, cedula, dia, hora_inicio, hora_fin in HORARIOS_SEXTO:
        Horario.objects.get_or_create(
            ano='6ANO',
            materia=materia,
            docente=docentes[cedula],
            dia=dia,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )


def quitar_horario_sexto(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')
    cedulas = [cedula for _, _, cedula, _ in PROFESORES_SEXTO]
    Horario.objects.filter(ano='6ANO', docente__cedula__in=cedulas).delete()
    Docente.objects.filter(cedula__in=cedulas).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0020_horario_sexto_grado'),
    ]

    operations = [
        migrations.RunPython(cargar_horario_sexto, quitar_horario_sexto),
    ]