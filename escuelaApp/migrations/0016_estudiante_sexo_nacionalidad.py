from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0015_estudiante_fecha_nacimiento_estudiante_matricula_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='estudiante',
            name='nacionalidad',
            field=models.CharField(default='No especificada', max_length=50),
        ),
        migrations.AddField(
            model_name='estudiante',
            name='sexo',
            field=models.CharField(
                choices=[
                    ('F', 'Femenino'),
                    ('M', 'Masculino'),
                    ('O', 'Otro / No especificado'),
                ],
                default='O',
                max_length=1,
            ),
        ),
    ]
