from django.db import migrations, models


def convertir_notas_historicas(apps, schema_editor):
    RegistroAcademico = apps.get_model('escuelaApp', 'RegistroAcademico')
    equivalencias = (
        (90, 'A', 90),
        (80, 'B', 80),
        (70, 'C', 70),
        (60, 'D', 60),
        (50, 'E', 50),
        (0, 'F', 0),
    )

    for registro in RegistroAcademico.objects.exclude(nota__isnull=True):
        try:
            valor = float(registro.nota)
        except (TypeError, ValueError):
            continue
        for minimo, letra, porcentaje in equivalencias:
            if valor >= minimo:
                registro.nota = letra
                registro.porcentaje = porcentaje
                registro.save(update_fields=['nota', 'porcentaje'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0018_horario_unique_grado_dia_horas'),
    ]

    operations = [
        migrations.AlterField(
            model_name='registroacademico',
            name='nota',
            field=models.CharField(blank=True, choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D'), ('E', 'E'), ('F', 'F')], max_length=1, null=True),
        ),
        migrations.AddField(
            model_name='registroacademico',
            name='porcentaje',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.RunPython(convertir_notas_historicas, migrations.RunPython.noop),
    ]