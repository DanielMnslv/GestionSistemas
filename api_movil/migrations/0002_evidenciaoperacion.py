import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import api_movil.models


class Migration(migrations.Migration):
    dependencies = [
        ("api_movil", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="EvidenciaOperacion",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("archivo", models.FileField(upload_to=api_movil.models.ruta_evidencia_movil)),
                ("tipo", models.CharField(max_length=32, default="GENERAL")),
                ("nombre_original", models.CharField(max_length=255, blank=True)),
                ("mime_type", models.CharField(max_length=80, default="image/jpeg")),
                ("sha256", models.CharField(max_length=64)),
                ("bytes", models.PositiveBigIntegerField(default=0)),
                ("creada_en", models.DateTimeField(auto_now_add=True)),
                ("cargada_por", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
                ("operacion", models.ForeignKey(to="api_movil.operacionmovil", related_name="evidencias", on_delete=django.db.models.deletion.PROTECT)),
            ],
            options={"ordering": ["creada_en"]},
        ),
        migrations.AddConstraint(
            model_name="evidenciaoperacion",
            constraint=models.UniqueConstraint(fields=("operacion", "sha256"), name="uniq_evidencia_hash_operacion"),
        ),
    ]
