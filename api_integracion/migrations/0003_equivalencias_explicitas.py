import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api_integracion", "0002_proyecciones_remotas_y_ocurrido_en")]

    operations = [
        migrations.CreateModel(
            name="EquivalenciaRegistro",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("sistema_remoto", models.CharField(max_length=50, db_index=True)),
                ("entidad_local", models.CharField(max_length=100, db_index=True)),
                ("public_id_local", models.UUIDField(db_index=True)),
                ("entidad_remota", models.CharField(max_length=100, db_index=True)),
                ("public_id_remoto", models.UUIDField(db_index=True)),
                ("estado", models.CharField(
                    max_length=20, default="PENDIENTE", db_index=True,
                    choices=[
                        ("PENDIENTE", "Pendiente de validación"),
                        ("ACTIVA", "Activa"),
                        ("REVISION", "Requiere revisión"),
                        ("INACTIVA", "Inactiva"),
                    ],
                )),
                ("metadata", models.JSONField(default=dict, blank=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("sistema_remoto", "entidad_local", "public_id_local",
                                "entidad_remota", "public_id_remoto"),
                        name="uq_equiv_registro_pair",
                    )
                ],
                "indexes": [
                    models.Index(fields=["entidad_local", "public_id_local"], name="equiv_local_lookup_idx"),
                    models.Index(fields=["entidad_remota", "public_id_remoto"], name="equiv_remote_lookup_idx"),
                ],
            },
        ),
    ]
