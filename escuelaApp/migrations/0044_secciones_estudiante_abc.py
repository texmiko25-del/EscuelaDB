from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0043_secciones_estudiante_abc'),
    ]

    operations = [
        migrations.AlterField(
            model_name='estudiante',
            name='seccion',
            field=models.CharField(
                blank=True,
                choices=[('A', 'A'), ('B', 'B'), ('C', 'C')],
                default='',
                max_length=20,
                verbose_name='Sección',
            ),
        ),
    ]
