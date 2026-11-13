import uuid
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("api_integracion", "0001_infraestructura_integracion")]

    operations = [
        migrations.AddField(
            model_name="integrationinbox",
            name="aggregate_type",
            field=models.CharField(max_length=100, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="integrationinbox",
            name="aggregate_id",
            field=models.CharField(max_length=100, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="integrationinbox",
            name="ocurrido_en",
            field=models.DateTimeField(default=django.utils.timezone.now, db_index=True),
        ),
        migrations.CreateModel(
            name="RegistroRemotoIntegrado",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("sistema_origen", models.CharField(max_length=50, db_index=True)),
                ("entidad_origen", models.CharField(max_length=100, db_index=True)),
                ("public_id_origen", models.UUIDField()),
                ("aggregate_id_origen", models.CharField(max_length=100, blank=True, default="")),
                ("ultimo_event_id", models.UUIDField()),
                ("ocurrido_en", models.DateTimeField(db_index=True)),
                ("datos", models.JSONField(default=dict)),
                ("recibido_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("sistema_origen", "entidad_origen", "public_id_origen"),
                        name="uq_jano_remote_entity_public",
                    )
                ],
                "indexes": [
                    models.Index(fields=["sistema_origen", "entidad_origen"], name="jano_remote_type_idx")
                ],
            },
        ),
    ]
