from django.db import migrations, models


def marcar_importados_pendientes(apps, schema_editor):
    AccesoPlataforma = apps.get_model("inventario", "AccesoPlataforma")
    AccesoPlataforma.objects.using(schema_editor.connection.alias).update(
        fuente="CONTROL_EXCEL",
        estado="PENDIENTE",
    )


class Migration(migrations.Migration):
    dependencies = [("inventario", "0042_estado_directorio")]

    operations = [
        migrations.AddField(
            model_name="accesoplataforma",
            name="fuente",
            field=models.CharField(
                choices=[
                    ("MANUAL", "Registrado en JANO"),
                    ("CONTROL_EXCEL", "Importado del control histórico"),
                ],
                db_index=True,
                default="MANUAL",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            marcar_importados_pendientes,
            migrations.RunPython.noop,
        ),
    ]
