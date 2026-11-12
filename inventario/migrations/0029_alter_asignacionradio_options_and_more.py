import uuid

from django.db import migrations, models


def asignar_uuid_nuevos_modelos(apps, schema_editor):
    alias = schema_editor.connection.alias

    modelos = [
        "AsignacionRadio",
        "CambioGPS",
        "Cliente",
        "MantenimientoProgramado",
        "Puesto",
        "RenovacionAntivirus",
        "TransferenciaComponentesRadio",
        "VerificacionPolitica",
    ]

    for nombre_modelo in modelos:
        Modelo = apps.get_model("inventario", nombre_modelo)

        for objeto in Modelo.objects.using(alias).filter(
            public_id__isnull=True
        ).iterator(chunk_size=500):
            objeto.public_id = uuid.uuid4()
            objeto.save(update_fields=["public_id"], using=alias)

        if Modelo.objects.using(alias).filter(public_id__isnull=True).exists():
            raise RuntimeError(
                f"Existen registros sin public_id en {nombre_modelo}"
            )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("inventario", "0028_uuid_publicos_integracion"),
    ]

    operations = [
        migrations.AddField(
            model_name="asignacionradio",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="cambiogps",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="cliente",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="mantenimientoprogramado",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="puesto",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="renovacionantivirus",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="transferenciacomponentesradio",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="verificacionpolitica",
            name="public_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),

        migrations.RunPython(
            asignar_uuid_nuevos_modelos,
            migrations.RunPython.noop,
        ),

        migrations.AlterField(
            model_name="asignacionradio",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="cambiogps",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="cliente",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="mantenimientoprogramado",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="puesto",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="renovacionantivirus",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="transferenciacomponentesradio",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="verificacionpolitica",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),
        ),
    ]
