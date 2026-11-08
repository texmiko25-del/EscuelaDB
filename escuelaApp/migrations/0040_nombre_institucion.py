from django.db import migrations, models


NOMBRE_INSTITUCION = 'E.B. Elba Rosa de Acevedo'


def actualizar_nombre_institucion(apps, schema_editor):
    informacion_escuela = apps.get_model('escuelaApp', 'InformacionEscuela')
    informacion_escuela.objects.using(schema_editor.connection.alias).update(
        nombre=NOMBRE_INSTITUCION,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0039_contactomensaje_acepta_whatsapp_and_more'),
    ]

    operations = [
        migrations.RunPython(actualizar_nombre_institucion, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='informacionescuela',
            name='nombre',
            field=models.CharField(
                default=NOMBRE_INSTITUCION,
                max_length=200,
            ),
        ),
    ]
