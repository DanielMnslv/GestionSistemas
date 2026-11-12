import django.db.models.deletion
from django.db import migrations, models


# Los mantenimientos, programaciones y alertas pasan de apuntar al radio a
# apuntar a su Equipo (la 0012 ya copió la relación), y MantenimientoRadio
# pasa a llamarse MantenimientoEquipo.
class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0012_equipo"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="mantenimientoradio",
            name="mant_radio_fecha_idx",
        ),
        migrations.RemoveConstraint(
            model_name="alertamantenimiento",
            name="uniq_alerta_radio_vencimiento",
        ),
        migrations.RemoveField(model_name="mantenimientoradio", name="radio"),
        migrations.RemoveField(
            model_name="mantenimientoprogramado", name="radio"
        ),
        migrations.RemoveField(model_name="alertamantenimiento", name="radio"),
        migrations.AlterField(
            model_name="mantenimientoradio",
            name="equipo",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mantenimientos",
                to="inventario.equipo",
                verbose_name="Equipo",
            ),
        ),
        migrations.AlterField(
            model_name="mantenimientoprogramado",
            name="equipo",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mantenimientos_programados",
                to="inventario.equipo",
                verbose_name="Equipo",
            ),
        ),
        migrations.AlterField(
            model_name="alertamantenimiento",
            name="equipo",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="alertas_mantenimiento",
                to="inventario.equipo",
                verbose_name="Equipo",
            ),
        ),
        migrations.RenameModel(
            old_name="MantenimientoRadio",
            new_name="MantenimientoEquipo",
        ),
        migrations.AlterModelOptions(
            name="mantenimientoequipo",
            options={
                "ordering": ["-fecha_intervencion", "-id"],
                "verbose_name": "Intervención de mantenimiento",
                "verbose_name_plural": "Historial de intervenciones",
            },
        ),
        migrations.AlterModelOptions(
            name="alertamantenimiento",
            options={
                "ordering": ["fecha_vencimiento", "equipo__placa"],
                "verbose_name": "Alerta de mantenimiento",
                "verbose_name_plural": "Alertas de mantenimiento",
            },
        ),
        migrations.AddIndex(
            model_name="mantenimientoequipo",
            index=models.Index(
                fields=["equipo", "-fecha_intervencion"],
                name="mant_equipo_fecha_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="alertamantenimiento",
            constraint=models.UniqueConstraint(
                fields=("equipo", "fecha_vencimiento"),
                name="uniq_alerta_equipo_vencimiento",
            ),
        ),
    ]
