from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0024_quitar_tickets"),
    ]

    operations = [
        migrations.AddField(
            model_name="radio",
            name="estado_perilla_encendido",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="radio",
            name="estado_perilla_frecuencia",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="radio",
            name="estado_clip",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
