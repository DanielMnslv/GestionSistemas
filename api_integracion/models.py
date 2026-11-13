import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class IntegrationLink(models.Model):
    """Vincula registros locales con su identificador en la plataforma remota."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entidad = models.CharField(max_length=100, db_index=True)
    objeto_local_id = models.CharField(max_length=100, db_index=True)
    sistema_remoto = models.CharField(max_length=50, default="GESTION_TIC", db_index=True)
    objeto_remoto_id = models.CharField(max_length=100, blank=True, default="")
    public_id_remoto = models.UUIDField(null=True, blank=True, db_index=True)
    sincronizado_en = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=20, default="PENDIENTE", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["entidad", "objeto_local_id", "sistema_remoto"], name="uq_link_local_remote"),
            models.UniqueConstraint(fields=["entidad", "public_id_remoto", "sistema_remoto"], name="uq_link_public_remote"),
        ]
        indexes = [models.Index(fields=["estado", "actualizado_en"], name="api_int_link_status_idx")]


class IntegrationOutbox(models.Model):
    """Evento pendiente de entregar; se guarda en la misma transacción del cambio."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    event_type = models.CharField(max_length=150, db_index=True)
    aggregate_type = models.CharField(max_length=100, db_index=True)
    aggregate_id = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=200, unique=True)
    estado = models.CharField(max_length=20, default="PENDIENTE", db_index=True)
    intentos = models.PositiveIntegerField(default=0)
    proximo_intento = models.DateTimeField(null=True, blank=True, db_index=True)
    ultimo_error = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True)
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["creado_en"]
        indexes = [models.Index(fields=["estado", "proximo_intento"], name="api_int_outbox_status_idx")]


class IntegrationInbox(models.Model):
    """Registro de eventos recibidos para garantizar procesamiento idempotente."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sistema_origen = models.CharField(max_length=50, db_index=True)
    event_id = models.UUIDField()
    event_type = models.CharField(max_length=150, db_index=True)
    aggregate_type = models.CharField(max_length=100, blank=True, default="")
    aggregate_id = models.CharField(max_length=100, blank=True, default="")
    payload = models.JSONField(default=dict)
    estado = models.CharField(max_length=20, default="RECIBIDO", db_index=True)
    ocurrido_en = models.DateTimeField(default=timezone.now, db_index=True)
    recibido_en = models.DateTimeField(auto_now_add=True)
    procesado_en = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sistema_origen", "event_id"], name="uq_inbox_source_event")]


class IntegrationDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    outbox = models.ForeignKey(IntegrationOutbox, on_delete=models.CASCADE, related_name="entregas")
    destino = models.CharField(max_length=100)
    codigo_http = models.PositiveSmallIntegerField(null=True, blank=True)
    respuesta = models.JSONField(default=dict, blank=True)
    exito = models.BooleanField(default=False)
    duracion_ms = models.PositiveIntegerField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)


class IntegrationAudit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sistema = models.CharField(max_length=50)
    accion = models.CharField(max_length=100, db_index=True)
    entidad = models.CharField(max_length=100, blank=True, default="")
    referencia = models.CharField(max_length=100, blank=True, default="")
    resultado = models.CharField(max_length=30, default="OK")
    detalle = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)


class RegistroRemotoIntegrado(models.Model):
    """Proyección de solo lectura de un registro propiedad de otra plataforma."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sistema_origen = models.CharField(max_length=50, db_index=True)
    entidad_origen = models.CharField(max_length=100, db_index=True)
    public_id_origen = models.UUIDField()
    aggregate_id_origen = models.CharField(max_length=100, blank=True, default="")
    ultimo_event_id = models.UUIDField()
    ocurrido_en = models.DateTimeField(db_index=True)
    datos = models.JSONField(default=dict)
    recibido_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sistema_origen", "entidad_origen", "public_id_origen"],
                name="uq_jano_remote_entity_public",
            )
        ]
        indexes = [
            models.Index(fields=["sistema_origen", "entidad_origen"], name="jano_remote_type_idx"),
        ]


class EquivalenciaRegistro(models.Model):
    """Relación explícita entre registros equivalentes de ambas plataformas.

    No transfiere propiedad ni crea claves foráneas entre bases de datos.
    """
    ESTADOS = [
        ("PENDIENTE", "Pendiente de validación"),
        ("ACTIVA", "Activa"),
        ("REVISION", "Requiere revisión"),
        ("INACTIVA", "Inactiva"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sistema_remoto = models.CharField(max_length=50, db_index=True)
    entidad_local = models.CharField(max_length=100, db_index=True)
    public_id_local = models.UUIDField(db_index=True)
    entidad_remota = models.CharField(max_length=100, db_index=True)
    public_id_remoto = models.UUIDField(db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="PENDIENTE", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sistema_remoto", "entidad_local", "public_id_local",
                    "entidad_remota", "public_id_remoto",
                ],
                name="uq_equiv_registro_pair",
            )
        ]
        indexes = [
            models.Index(fields=["entidad_local", "public_id_local"], name="equiv_local_lookup_idx"),
            models.Index(fields=["entidad_remota", "public_id_remoto"], name="equiv_remote_lookup_idx"),
        ]
