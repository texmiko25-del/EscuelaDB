from django.db import migrations, models


def convertir_cargo_admin_a_directora(apps, schema_editor):
    Empleado = apps.get_model('escuelaApp', 'Empleado')
    Empleado.objects.filter(cargo='ADMIN').update(cargo='DIRECTORA')


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0026_reparar_tipo_nota'),
    ]

    operations = [
        migrations.RunPython(
            convertir_cargo_admin_a_directora,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='empleado',
            name='cargo',
            field=models.CharField(
                choices=[
                    ('DIRECTORA', 'Directora'),
                    ('SUBDIRECTORA', 'Subdirectora'),
                    ('COORD', 'Coordinador Pedagógico'),
                    ('DOCENTE', 'Docente'),
                    ('PROFESOR', 'Profesor'),
                    ('ASISTENTE', 'Asistente'),
                ],
                max_length=20,
            ),
        ),
    ]