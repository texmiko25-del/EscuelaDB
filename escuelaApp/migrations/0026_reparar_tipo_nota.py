from decimal import Decimal, InvalidOperation

from django.db import migrations


def convertir_notas_numericas(apps, schema_editor):
    RegistroAcademico = apps.get_model('escuelaApp', 'RegistroAcademico')
    equivalencias = (
        (Decimal('90'), 'A', Decimal('90')),
        (Decimal('80'), 'B', Decimal('80')),
        (Decimal('70'), 'C', Decimal('70')),
        (Decimal('60'), 'D', Decimal('60')),
        (Decimal('50'), 'E', Decimal('50')),
        (Decimal('0'), 'F', Decimal('0')),
    )

    for registro in RegistroAcademico.objects.exclude(nota__isnull=True).iterator():
        try:
            valor = Decimal(str(registro.nota))
        except (InvalidOperation, TypeError, ValueError):
            continue

        for minimo, letra, porcentaje in equivalencias:
            if valor >= minimo:
                registro.nota = letra
                registro.porcentaje = porcentaje
                registro.save(update_fields=['nota', 'porcentaje'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0025_remove_transaccionproyecto_usuario_delete_proyecto_and_more'),
    ]

    operations = [
        migrations.RunPython(convertir_notas_numericas, migrations.RunPython.noop),
    ]