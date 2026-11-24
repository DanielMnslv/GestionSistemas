import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="OperacionMovil",
            fields=[
                ("uuid", models.UUIDField(primary_key=True, serialize=False, editable=False)),
                ("tipo", models.CharField(max_length=24)),
                ("placa", models.CharField(max_length=50, blank=True)),
                ("payload", models.JSONField(default=dict)),
                ("resultado", models.JSONField(default=dict)),
                ("estado", models.CharField(max_length=16, default="RECIBIDA")),
                ("creada_en", models.DateTimeField(auto_now_add=True)),
                ("procesada_en", models.DateTimeField(null=True, blank=True)),
                ("usuario", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
            ],
            options={"ordering": ["-creada_en"]},
        ),
    ]
