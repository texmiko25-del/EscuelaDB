from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0019_registroacademico_calificacion_porcentaje'),
    ]

    operations = [
        migrations.AlterField(
            model_name='horario',
            name='ano',
            field=models.CharField(
                choices=[
                    ('1ANO', '1er Grado'),
                    ('2ANO', '2do Grado'),
                    ('3ANO', '3er Grado'),
                    ('4ANO', '4to Grado'),
                    ('5ANO', '5to Grado'),
                    ('6ANO', '6to Grado'),
                ],
                max_length=10,
                verbose_name='Grado',
            ),
        ),
    ]