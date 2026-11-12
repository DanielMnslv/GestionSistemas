import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('inventario', '0027_puesto_coordenadas')]
    operations = [
        migrations.CreateModel(name='IntegrationOutbox', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('event_id', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
            ('event_type', models.CharField(max_length=150, db_index=True)),
            ('aggregate_type', models.CharField(max_length=100, db_index=True)),
            ('aggregate_id', models.CharField(max_length=100, db_index=True)),
            ('payload', models.JSONField(default=dict)),
            ('idempotency_key', models.CharField(max_length=200, unique=True)),
            ('estado', models.CharField(max_length=20, default='PENDIENTE', db_index=True)),
            ('intentos', models.PositiveIntegerField(default=0)),
            ('proximo_intento', models.DateTimeField(null=True, blank=True, db_index=True)),
            ('ultimo_error', models.TextField(blank=True, default='')),
            ('creado_en', models.DateTimeField(auto_now_add=True)),
            ('enviado_en', models.DateTimeField(null=True, blank=True)),
        ], options={'ordering': ['creado_en']}),
        migrations.CreateModel(name='IntegrationInbox', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('sistema_origen', models.CharField(max_length=50, db_index=True)),
            ('event_id', models.UUIDField()),
            ('event_type', models.CharField(max_length=150, db_index=True)),
            ('payload', models.JSONField(default=dict)),
            ('estado', models.CharField(max_length=20, default='RECIBIDO', db_index=True)),
            ('recibido_en', models.DateTimeField(auto_now_add=True)),
            ('procesado_en', models.DateTimeField(null=True, blank=True)),
            ('error', models.TextField(blank=True, default='')),
        ]),
        migrations.CreateModel(name='IntegrationLink', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entidad', models.CharField(max_length=100, db_index=True)),
            ('objeto_local_id', models.CharField(max_length=100, db_index=True)),
            ('sistema_remoto', models.CharField(max_length=50, default='GESTION_TIC', db_index=True)),
            ('objeto_remoto_id', models.CharField(max_length=100, blank=True, default='')),
            ('public_id_remoto', models.UUIDField(null=True, blank=True, db_index=True)),
            ('sincronizado_en', models.DateTimeField(null=True, blank=True)),
            ('estado', models.CharField(max_length=20, default='PENDIENTE', db_index=True)),
            ('metadata', models.JSONField(default=dict, blank=True)),
            ('creado_en', models.DateTimeField(auto_now_add=True)),
            ('actualizado_en', models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name='IntegrationAudit', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('sistema', models.CharField(max_length=50)),
            ('accion', models.CharField(max_length=100, db_index=True)),
            ('entidad', models.CharField(max_length=100, blank=True, default='')),
            ('referencia', models.CharField(max_length=100, blank=True, default='')),
            ('resultado', models.CharField(max_length=30, default='OK')),
            ('detalle', models.JSONField(default=dict, blank=True)),
            ('creado_en', models.DateTimeField(auto_now_add=True, db_index=True)),
        ]),
        migrations.CreateModel(name='IntegrationDelivery', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('destino', models.CharField(max_length=100)),
            ('codigo_http', models.PositiveSmallIntegerField(null=True, blank=True)),
            ('respuesta', models.JSONField(default=dict, blank=True)),
            ('exito', models.BooleanField(default=False)),
            ('duracion_ms', models.PositiveIntegerField(null=True, blank=True)),
            ('creado_en', models.DateTimeField(auto_now_add=True)),
            ('outbox', models.ForeignKey(to='api_integracion.integrationoutbox', on_delete=django.db.models.deletion.CASCADE, related_name='entregas')),
        ]),
        migrations.AddConstraint(model_name='integrationinbox', constraint=models.UniqueConstraint(fields=('sistema_origen','event_id'), name='uq_inbox_source_event')),
        migrations.AddConstraint(model_name='integrationlink', constraint=models.UniqueConstraint(fields=('entidad','objeto_local_id','sistema_remoto'), name='uq_link_local_remote')),
        migrations.AddConstraint(model_name='integrationlink', constraint=models.UniqueConstraint(fields=('entidad','public_id_remoto','sistema_remoto'), name='uq_link_public_remote')),
        migrations.AddIndex(model_name='integrationoutbox', index=models.Index(fields=['estado','proximo_intento'], name='api_int_outbox_status_idx')),
        migrations.AddIndex(model_name='integrationlink', index=models.Index(fields=['estado','actualizado_en'], name='api_int_link_status_idx')),
    ]
