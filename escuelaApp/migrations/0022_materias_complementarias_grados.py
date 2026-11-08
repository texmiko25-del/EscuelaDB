from django.db import migrations


MATERIAS_COMPLEMENTARIAS = [
    ('1ANO', 'Música', 'Docente', 'Música', 'DOC-GRADO-001', 'LU'),
    ('2ANO', 'Teatro', 'Docente', 'Teatro', 'DOC-GRADO-002', 'MA'),
    ('3ANO', 'Tecnología', 'Docente', 'Tecnología', 'DOC-GRADO-003', 'MI'),
    ('4ANO', 'Geografía', 'Docente', 'Geografía', 'DOC-GRADO-004', 'JU'),
    ('5ANO', 'Formación Ciudadana', 'Docente', 'Formación Ciudadana', 'DOC-GRADO-005', 'VI'),
]


def cargar_materias_complementarias(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')

    for grado, materia, nombre, apellido, cedula, dia in MATERIAS_COMPLEMENTARIAS:
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
            ano=grado,
            materia=materia,
            docente=docente,
            dia=dia,
            hora_inicio='07:00',
            hora_fin='07:45',
        )


def quitar_materias_complementarias(apps, schema_editor):
    Docente = apps.get_model('escuelaApp', 'Docente')
    Horario = apps.get_model('escuelaApp', 'Horario')
    cedulas = [cedula for _, _, _, _, cedula, _ in MATERIAS_COMPLEMENTARIAS]
    Horario.objects.filter(docente__cedula__in=cedulas).delete()
    Docente.objects.filter(cedula__in=cedulas).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0021_cargar_horario_sexto'),
    ]

    operations = [
        migrations.RunPython(cargar_materias_complementarias, quitar_materias_complementarias),
    ]