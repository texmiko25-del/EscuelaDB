from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0016_estudiante_sexo_nacionalidad'),
    ]

    operations = [
        migrations.AddField(
            model_name='docente',
            name='telefono',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
