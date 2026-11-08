from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0017_docente_telefono'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='horario',
            constraint=models.UniqueConstraint(
                fields=('ano', 'dia', 'hora_inicio', 'hora_fin'),
                name='unique_horario_grado_dia_horas',
            ),
        ),
    ]
