from django.db import migrations


MATERIAS_ADICIONALES_SEXTO = [
    ('Educación Ambiental', 'Docente', 'Ambiental', 'DOC-6TO-009', 'LU', '08:30', '09:15'),
    ('Ética y Valores', 'Docente', 'Ética', 'DOC-6TO-010', 'MA', '08:30', '09:15'),
    ('Geografía', 'Docente', 'Geografía', 'DOC-6TO-011', 'MI', '08:30', '09:15'),
    ('Historia', 'Docente', 'Historia', 'DOC-6TO-012', 'JU', '07:45', '08:30'),
    ('Valores', 'Docente', 'Valores', 'DOC-6TO-013', 'JU', '08:30', '09:15'),
    ('Orientación', 'Docente', 'Orientación', 'DOC-6TO-014', 'VI', '07:45', '08:30'),
    ('Robótica', 'Docente', 'Robótica', 'DOC-6TO-015', 'VI', '08:30', '09:15'),
]


def cargar_materias_sexto(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')

    for materia, nombre, apellido, cedula, dia, hora_inicio, hora_fin in MATERIAS_ADICIONALES_SEXTO:
        docente, _ = Docente.objects.get_or_create(
            cedula=cedula,
            defaults={
                'nombre': nombre,
                'apellido': apellido,
                'especialidad': materia,
                'carga_horaria': 1,
            },
        )
        Horario.objects.get_or_create(
            ano='6ANO',
            materia=materia,
            docente=docente,
            dia=dia,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
        )


def quitar_materias_sexto(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')
    cedulas = [cedula for _, _, _, cedula, _, _, _ in MATERIAS_ADICIONALES_SEXTO]
    Horario.objects.filter(ano='6ANO', docente__cedula__in=cedulas).delete()
    Docente.objects.filter(cedula__in=cedulas).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0022_materias_complementarias_grados'),
    ]

    operations = [
        migrations.RunPython(cargar_materias_sexto, quitar_materias_sexto),
    ]