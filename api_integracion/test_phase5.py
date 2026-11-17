"""Pruebas del procesador de eventos que llegan de Gestión TIC (fase 5 de la integración)."""

import uuid
from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api_integracion.models import IntegrationInbox, RegistroRemotoIntegrado


class ProcesadorEventosGestionTICTests(TestCase):
    """Los eventos de Gestión TIC se proyectan como copias de solo lectura."""

    def test_proyecta_evento_sin_crear_equipo_local(self):
        public_id = uuid.uuid4()
        IntegrationInbox.objects.create(
            sistema_origen="GESTION_TIC",
            event_id=uuid.uuid4(),
            event_type="gestion_tic.activo_critico.upserted",
            payload={
                "public_id": str(public_id),
                "data": {"servicio": "Servicio de prueba", "criticidad": "Alta"},
            },
            ocurrido_en=timezone.now(),
            aggregate_type="activo_critico",
            aggregate_id="123",
        )
        salida = StringIO()
        call_command("procesar_eventos_gestion_tic", stdout=salida)
        registro = RegistroRemotoIntegrado.objects.get(public_id_origen=public_id)
        self.assertEqual(registro.datos["servicio"], "Servicio de prueba")
        self.assertEqual(registro.sistema_origen, "GESTION_TIC")
        self.assertFalse(registro.datos.get("crear_equipo_local", False))

    def test_evento_sin_public_id_queda_en_error(self):
        evento = IntegrationInbox.objects.create(
            sistema_origen="GESTION_TIC",
            event_id=uuid.uuid4(),
            event_type="gestion_tic.riesgo.upserted",
            payload={"data": {"nombre": "Sin UUID"}},
            ocurrido_en=timezone.now(),
        )
        call_command("procesar_eventos_gestion_tic")
        evento.refresh_from_db()
        self.assertEqual(evento.estado, "ERROR")
        self.assertTrue(evento.error)
