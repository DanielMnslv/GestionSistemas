import uuid
from django.conf import settings
from django.db import models


class OperacionMovil(models.Model):
    """Idempotencia y trazabilidad de cada operación enviada por Android."""
    uuid = models.UUIDField(primary_key=True, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo = models.CharField(max_length=24)
    placa = models.CharField(max_length=50, blank=True)
    payload = models.JSONField(default=dict)
    resultado = models.JSONField(default=dict)
    estado = models.CharField(max_length=16, default="RECIBIDA")
    creada_en = models.DateTimeField(auto_now_add=True)
    procesada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creada_en"]


def ruta_evidencia_movil(instance, filename):
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(instance.mime_type, "jpg")
    return f"jano_movil/{instance.operacion_id}/{instance.pk}.{extension}"


class EvidenciaOperacion(models.Model):
    """Archivo fotográfico ligado a una operación móvil ya confirmada."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operacion = models.ForeignKey(OperacionMovil, on_delete=models.PROTECT, related_name="evidencias")
    archivo = models.FileField(upload_to=ruta_evidencia_movil)
    tipo = models.CharField(max_length=32, default="GENERAL")
    nombre_original = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=80, default="image/jpeg")
    sha256 = models.CharField(max_length=64)
    bytes = models.PositiveBigIntegerField(default=0)
    cargada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creada_en"]
        constraints = [
            models.UniqueConstraint(fields=["operacion", "sha256"], name="uniq_evidencia_hash_operacion"),
        ]
