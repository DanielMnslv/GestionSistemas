from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventario", "0050_detallecomputador_cantidad_modulos_ram_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="asignacionequipo",
            name="puesto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="asignaciones_equipo",
                to="inventario.puesto",
            ),
        ),
        migrations.AddField(
            model_name="asignacionequipo",
            name="firma_devolucion",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="asignacionequipo",
            name="inspeccion_devolucion",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="asignacionradio",
            name="firma_devolucion",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="asignacionradio",
            name="inspeccion_devolucion",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
