from django.db import migrations, models


def placas_provisionales(apps, schema_editor):
    """Los radios sin placa conservan su registro general con una placa
    provisional (SIN-RJ-<n>) hasta que se les asigne la RJ real."""
    Radio = apps.get_model("inventario", "Radio")
    Equipo = apps.get_model("inventario", "Equipo")

    vistas = {}
    for radio in Radio.objects.all():
        placa = (radio.placa or "").strip()
        if placa != radio.placa:
            Radio.objects.filter(pk=radio.pk).update(placa=placa)
        if placa:
            vistas.setdefault(placa.upper(), []).append(radio.pk)
        elif radio.equipo_id:
            Equipo.objects.filter(pk=radio.equipo_id).update(
                placa=f"SIN-RJ-{radio.pk}"
            )
    repetidas = {p: ids for p, ids in vistas.items() if len(ids) > 1}
    if repetidas:
        raise RuntimeError(
            "Hay placas repetidas entre radios; corrígelas antes de migrar: "
            + ", ".join(sorted(repetidas))
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0020_clientes_puestos_antivirus"),
    ]

    operations = [
        migrations.RunPython(placas_provisionales, migrations.RunPython.noop),
        migrations.RemoveField(model_name="radio", name="id_inventario"),
        migrations.AlterModelOptions(
            name="radio",
            options={
                "ordering": ["placa", "id"],
                "verbose_name": "Radio",
                "verbose_name_plural": "Radios",
            },
        ),
        migrations.AddConstraint(
            model_name="radio",
            constraint=models.UniqueConstraint(
                condition=models.Q(("placa", ""), _negated=True),
                fields=("placa",),
                name="radio_placa_unica",
            ),
        ),
    ]
