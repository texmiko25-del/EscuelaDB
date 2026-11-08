from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escuelaApp', '0037_alter_empleado_cargo'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactomensaje',
            name='telegram_chat_id',
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
