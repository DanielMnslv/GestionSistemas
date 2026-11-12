import uuid
from django.db import migrations, models


def asignar_uuid_publicos(apps, schema_editor):
    alias = schema_editor.connection.alias
    Modelo = apps.get_model("inventario", "Equipo")
    for objeto in Modelo.objects.using(alias).filter(public_id__isnull=True).iterator(chunk_size=500):
        objeto.public_id = uuid.uuid4()
        objeto.save(update_fields=["public_id"], using=alias)
    Modelo = apps.get_model("inventario", "Radio")
    for objeto in Modelo.objects.using(alias).filter(public_id__isnull=True).iterator(chunk_size=500):
        objeto.public_id = uuid.uuid4()
        objeto.save(update_fields=["public_id"], using=alias)
    Modelo = apps.get_model("inventario", "MantenimientoEquipo")
    for objeto in Modelo.objects.using(alias).filter(public_id__isnull=True).iterator(chunk_size=500):
        objeto.public_id = uuid.uuid4()
        objeto.save(update_fields=["public_id"], using=alias)
    Modelo = apps.get_model("inventario", "AsignacionEquipo")
    for objeto in Modelo.objects.using(alias).filter(public_id__isnull=True).iterator(chunk_size=500):
        objeto.public_id = uuid.uuid4()
        objeto.save(update_fields=["public_id"], using=alias)
    Modelo = apps.get_model("inventario", "Funcionario")
    for objeto in Modelo.objects.using(alias).filter(public_id__isnull=True).iterator(chunk_size=500):
        objeto.public_id = uuid.uuid4()
        objeto.save(update_fields=["public_id"], using=alias)

class Migration(migrations.Migration):
    atomic = False
    dependencies = [("inventario", "0027_puesto_coordenadas")]
    operations = [
        migrations.AddField(model_name="equipo", name="public_id", field=models.UUIDField(null=True, blank=True, editable=False)),
        migrations.AddField(model_name="radio", name="public_id", field=models.UUIDField(null=True, blank=True, editable=False)),
        migrations.AddField(model_name="mantenimientoequipo", name="public_id", field=models.UUIDField(null=True, blank=True, editable=False)),
        migrations.AddField(model_name="asignacionequipo", name="public_id", field=models.UUIDField(null=True, blank=True, editable=False)),
        migrations.AddField(model_name="funcionario", name="public_id", field=models.UUIDField(null=True, blank=True, editable=False)),
        migrations.RunPython(asignar_uuid_publicos, migrations.RunPython.noop),
        migrations.AlterField(model_name="equipo", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AlterField(model_name="radio", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AlterField(model_name="mantenimientoequipo", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AlterField(model_name="asignacionequipo", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AlterField(model_name="funcionario", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
    ]
