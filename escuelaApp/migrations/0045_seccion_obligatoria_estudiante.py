from django.db import migrations, models


def asignar_seccion_predeterminada(apps, schema_editor):
    Estudiante = apps.get_model('escuelaApp', 'Estudiante')
    Estudiante.objects.using(schema_editor.connection.alias).filter(
        seccion='',
    ).update(seccion='A')


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0044_secciones_estudiante_abc'),
    ]

    operations = [
        migrations.RunPython(
            asignar_seccion_predeterminada,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='estudiante',
            name='seccion',
            field=models.CharField(
                choices=[('A', 'A'), ('B', 'B'), ('C', 'C')],
                max_length=20,
                verbose_name='Sección',
            ),
        ),
    ]
