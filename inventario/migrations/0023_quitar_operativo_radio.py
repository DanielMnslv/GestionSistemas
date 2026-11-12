from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0022_estado_unico_radio_datos"),
    ]

    operations = [
        migrations.RemoveField(model_name="radio", name="operativo"),
    ]
