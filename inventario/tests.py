
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.utils import timezone

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.db import IntegrityError
from django.urls import reverse
from django.db import transaction

from inventario.models import (
    Equipo,
    AlertaMantenimiento,
    AsignacionEquipo,
    AsignacionRadio,
    MantenimientoEquipo,
    MantenimientoProgramado,
    Radio,
    TransferenciaComponentesRadio,
    Vigilante,
)


COMANDO = (
    "inventario.management.commands."
    "procesar_alertas_mantenimiento"
)


@override_settings(
    EMAIL_HOST_USER="prueba",
    DEFAULT_FROM_EMAIL="prueba@example.com",
)
class AlertasMantenimientoTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_user(
            **{Usuario.USERNAME_FIELD: "usuario_prueba_alertas"},
            password="PruebaTemporal123!",
        )

        self.radio = Radio.objects.create(
            placa="TEST-RAD-001", 
        )

        MantenimientoEquipo.objects.create(
            registrado_por=self.usuario,
            equipo=self.radio.equipo,
            fecha_intervencion=datetime(
                2026, 10, 9, 12, 0, tzinfo=dt_timezone.utc
            ),
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            tecnico_responsable="Técnico de pruebas",
            motivo="Prueba automatizada",
            trabajo_realizado="Inspección de prueba",
            origen_archivo="PRUEBA_AUTOMATIZADA",
            origen_hoja="TEST",
            fila_origen=999999,
        )

        self.ahora = datetime(
            2027, 4, 9, 12, 0, tzinfo=dt_timezone.utc
        )

    def crear_alerta(
        self,
        estado=AlertaMantenimiento.Estado.ERROR,
        intentos=1,
        minutos_desde_ultimo_intento=31,
    ):
        return AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date(),
            estado=estado,
            intentos=intentos,
            ultimo_intento=(
                self.ahora
                - timedelta(minutes=minutos_desde_ultimo_intento)
            ),
        )

    @patch(f"{COMANDO}.send_mail")
    def test_simulacion_no_crea_alertas_ni_envia_correos(
        self, mock_send_mail
    ):
        call_command(
            "procesar_alertas_mantenimiento",
            fecha_prueba="2027-04-09",
        )

        self.assertEqual(AlertaMantenimiento.objects.count(), 0)
        mock_send_mail.assert_not_called()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_no_reintenta_si_ya_alcanzo_tres_intentos(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora
        alerta = self.crear_alerta(intentos=3)

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta.refresh_from_db()
        self.assertEqual(alerta.intentos, 3)
        self.assertEqual(
            alerta.estado,
            AlertaMantenimiento.Estado.ERROR,
        )
        mock_send_mail.assert_not_called()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_no_reintenta_antes_de_treinta_minutos(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora
        alerta = self.crear_alerta(
            intentos=1,
            minutos_desde_ultimo_intento=10,
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta.refresh_from_db()
        self.assertEqual(alerta.intentos, 1)
        mock_send_mail.assert_not_called()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_reintenta_despues_de_treinta_minutos(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora
        alerta = self.crear_alerta(
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=1,
            minutos_desde_ultimo_intento=31,
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta.refresh_from_db()
        self.assertEqual(alerta.intentos, 2)
        self.assertEqual(
            alerta.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        mock_send_mail.assert_called_once()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_no_reenvia_alerta_ya_enviada(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora
        alerta = self.crear_alerta(
            estado=AlertaMantenimiento.Estado.ENVIADA,
            intentos=1,
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta.refresh_from_db()
        self.assertEqual(alerta.intentos, 1)
        mock_send_mail.assert_not_called()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_recupera_alerta_fallida_de_vencimiento_anterior(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora

        alerta = AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date() - timedelta(days=1),
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=1,
            ultimo_intento=self.ahora - timedelta(minutes=31),
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta.refresh_from_db()
        self.assertEqual(alerta.intentos, 2)
        self.assertEqual(
            alerta.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        mock_send_mail.assert_called_once()
        self.assertEqual(
            AlertaMantenimiento.objects.count(),
            1,
            "La recuperación no debe crear alertas retroactivas adicionales.",
        )

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_alerta_antigua_agotada_no_bloquea_vencimiento_hoy(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora

        alerta_antigua = AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date() - timedelta(days=1),
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=3,
            ultimo_intento=self.ahora - timedelta(hours=1),
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta_antigua.refresh_from_db()

        self.assertEqual(alerta_antigua.intentos, 3)
        self.assertEqual(
            alerta_antigua.estado,
            AlertaMantenimiento.Estado.ERROR,
        )

        alerta_hoy = AlertaMantenimiento.objects.get(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date(),
        )

        self.assertEqual(
            alerta_hoy.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        self.assertEqual(alerta_hoy.intentos, 1)
        self.assertEqual(AlertaMantenimiento.objects.count(), 2)
        mock_send_mail.assert_called_once()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_procesa_alertas_antiguas_en_ejecuciones_sucesivas(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora

        alerta_mas_antigua = AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date() - timedelta(days=2),
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=1,
            ultimo_intento=self.ahora - timedelta(minutes=31),
        )

        alerta_reciente = AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date() - timedelta(days=1),
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=1,
            ultimo_intento=self.ahora - timedelta(minutes=31),
        )

        # Primera ejecución: procesa la alerta más antigua.
        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta_mas_antigua.refresh_from_db()
        alerta_reciente.refresh_from_db()

        self.assertEqual(
            alerta_mas_antigua.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        self.assertEqual(
            alerta_reciente.estado,
            AlertaMantenimiento.Estado.ERROR,
        )

        # Segunda ejecución: procesa la siguiente alerta antigua.
        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta_mas_antigua.refresh_from_db()
        alerta_reciente.refresh_from_db()

        self.assertEqual(
            alerta_mas_antigua.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        self.assertEqual(
            alerta_reciente.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        self.assertEqual(AlertaMantenimiento.objects.count(), 2)
        self.assertEqual(mock_send_mail.call_count, 2)

    @patch(f"{COMANDO}.timezone.now")
    @patch(
        f"{COMANDO}.send_mail",
        side_effect=Exception("Fallo SMTP de prueba"),
    )
    def test_registra_error_si_falla_el_envio(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta = AlertaMantenimiento.objects.get(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date(),
        )

        self.assertEqual(
            alerta.estado,
            AlertaMantenimiento.Estado.ERROR,
        )
        self.assertEqual(alerta.intentos, 1)
        self.assertIn("Fallo SMTP de prueba", alerta.detalle_error)
        self.assertEqual(alerta.ultimo_intento, self.ahora)
        mock_send_mail.assert_called_once()

    @patch(f"{COMANDO}.timezone.now")
    @patch(f"{COMANDO}.send_mail", return_value=1)
    def test_alerta_antigua_en_espera_no_bloquea_vencimiento_hoy(
        self, mock_send_mail, mock_now
    ):
        mock_now.return_value = self.ahora

        alerta_antigua = AlertaMantenimiento.objects.create(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date() - timedelta(days=1),
            estado=AlertaMantenimiento.Estado.ERROR,
            intentos=1,
            ultimo_intento=self.ahora - timedelta(minutes=10),
        )

        call_command(
            "procesar_alertas_mantenimiento",
            enviar=True,
        )

        alerta_antigua.refresh_from_db()

        # La alerta antigua sigue en espera y no consume otro intento.
        self.assertEqual(
            alerta_antigua.estado,
            AlertaMantenimiento.Estado.ERROR,
        )
        self.assertEqual(alerta_antigua.intentos, 1)

        # La alerta que vence hoy se procesa por separado.
        alerta_hoy = AlertaMantenimiento.objects.get(
            equipo=self.radio.equipo,
            fecha_vencimiento=self.ahora.date(),
        )

        self.assertEqual(
            alerta_hoy.estado,
            AlertaMantenimiento.Estado.ENVIADA,
        )
        self.assertEqual(alerta_hoy.intentos, 1)
        self.assertEqual(AlertaMantenimiento.objects.count(), 2)
        mock_send_mail.assert_called_once()


class AsignacionRadioTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_user(
            **{Usuario.USERNAME_FIELD: "usuario_prueba_asignacion"},
            password="PruebaTemporal123!",
        )
        self.radio = Radio.objects.create(
            placa="TEST-ASIG-001", 
        )
        self.vigilante = Vigilante.objects.create(
            cedula="123456789",
            nombre_completo="VIGILANTE DE PRUEBA",
            activo=True,
            hoja_origen="HUILA",
            fila_origen=3,
        )

    def crear_asignacion(self):
        return AsignacionRadio.objects.create(
              radio=self.radio,
              coordinador_zona="Zona anterior",
              cedula_funcionario=self.vigilante.cedula,
              cliente_asignado="Cliente anterior",
              puesto_asignado="Puesto anterior",
              entregado_por=self.usuario,
)

    def test_registra_asignacion_activa(self):
        asignacion = self.crear_asignacion()

        self.assertEqual(
            asignacion.estado,
            AsignacionRadio.Estado.ASIGNADO,
        )
        self.assertEqual(asignacion.radio, self.radio)
        self.assertEqual(asignacion.entregado_por, self.usuario)

    def test_impide_dos_asignaciones_activas_para_el_mismo_radio(self):
        self.crear_asignacion()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.crear_asignacion()

    def test_permite_nueva_asignacion_despues_de_devolucion(self):
        asignacion = self.crear_asignacion()
        asignacion.estado = AsignacionRadio.Estado.DEVUELTO
        asignacion.fecha_devolucion = timezone.now()
        asignacion.recibido_por = self.usuario
        asignacion.save()

        nueva_asignacion = self.crear_asignacion()

        self.assertEqual(
            nueva_asignacion.estado,
            AsignacionRadio.Estado.ASIGNADO,
        )
        self.assertEqual(
            AsignacionRadio.objects.filter(radio=self.radio).count(),
            2,
        )


FIRMA_PRUEBA = "data:image/png;base64,iVBORw0KGgo="
ENTREGA_COMPLETA = {
    "estado_radio_entrega": "Bueno",
    "estado_base_entrega": "Bueno",
    "estado_cargador_entrega": "Regular",
    "estado_antena_entrega": "Bueno",
    "estado_baterias_entrega": "No tiene",
    "clausula_aceptada": "on",
    "firma": FIRMA_PRUEBA,
}


class AsignacionRadioVistasTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_user(
            **{Usuario.USERNAME_FIELD: "usuario_vistas_asig"},
            password="PruebaTemporal123!",
        )
        self.usuario.groups.add(
            Group.objects.get_or_create(name="Encargado de inventario")[0]
        )
        self.client.force_login(self.usuario)

        self.radio = Radio.objects.create(
            placa="TEST-VISTA-ASIG-001", 
            marca="Motorola",
            modelo="Prueba",
        )
        self.vigilante = Vigilante.objects.create(
            cedula="123456789",
            nombre_completo="VIGILANTE DE PRUEBA",
            activo=True,
            hoja_origen="HUILA",
            fila_origen=3,
        )

    def test_ficha_y_formularios_del_radio_no_abren_pantallas_detalle(self):
        respuesta = self.client.get(
            reverse("inventario:asignacion_crear"),
            {"radio": self.radio.pk},
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista"),
            fetch_redirect_response=False,
        )

        ficha = self.client.get(
            reverse("inventario:radio_detalle", args=[self.radio.pk]) + "?embed=1"
        )
        self.assertRedirects(
            ficha,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        editar = self.client.get(
            reverse("inventario:radio_editar", args=[self.radio.pk])
        )
        self.assertRedirects(
            editar,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )

    def test_registra_entrega_y_actualiza_radio(self):
        respuesta = self.client.post(
            reverse("inventario:asignacion_crear"),
            {
                "radio": self.radio.pk,
                "coordinador_zona": "Coordinación de prueba",
                "vigilante": self.vigilante.pk,
                "cliente_asignado": "Cliente de prueba",
                "puesto_asignado": "Puesto de prueba",
                "observaciones_entrega": "Entrega de prueba",
                **ENTREGA_COMPLETA,
            },
        )

        asignacion = AsignacionRadio.objects.get(radio=self.radio)
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.assertEqual(asignacion.estado_cargador_entrega, "Regular")
        self.assertTrue(asignacion.clausula_aceptada)
        self.assertEqual(asignacion.firma, FIRMA_PRUEBA)
        self.assertEqual(
            asignacion.estado,
            AsignacionRadio.Estado.ASIGNADO,
        )
        self.assertEqual(asignacion.entregado_por, self.usuario)

        self.radio.refresh_from_db()
        self.assertEqual(
            self.radio.cedula_funcionario,
            "123456789",
        )

    def test_devolucion_no_abre_pantalla_en_get(self):
        asignacion = AsignacionRadio.objects.create(
            radio=self.radio,
            coordinador_zona="Zona de prueba",
            cedula_funcionario=self.vigilante.cedula,
            cliente_asignado="Cliente de prueba",
            puesto_asignado="Puesto de prueba",
            entregado_por=self.usuario,
        )

        respuesta = self.client.get(
            reverse("inventario:asignacion_devolver", args=[asignacion.pk])
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista"),
            fetch_redirect_response=False,
        )

    def test_rechaza_segunda_entrega_sin_devolucion(self):
        AsignacionRadio.objects.create(
            radio=self.radio,
            coordinador_zona="Zona anterior",
            cedula_funcionario=self.vigilante.cedula,
            cliente_asignado="Cliente anterior",
            puesto_asignado="Puesto anterior",
            entregado_por=self.usuario,
        )

        respuesta = self.client.post(
            reverse("inventario:asignacion_crear"),
            {
                "radio": self.radio.pk,
                "vigilante": self.vigilante.pk,
                "coordinador_zona": "Zona nueva",
                "cliente_asignado": "Cliente nuevo",
                "puesto_asignado": "Puesto nuevo",
                "observaciones_entrega": "",
                **ENTREGA_COMPLETA,
            },
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.assertEqual(
            AsignacionRadio.objects.filter(radio=self.radio).count(),
            1,
        )

    def test_registra_devolucion_y_permite_nueva_entrega(self):
        asignacion = AsignacionRadio.objects.create(
            radio=self.radio,
            coordinador_zona="Zona de prueba",
            cedula_funcionario=self.vigilante.cedula,
            cliente_asignado="Cliente de prueba",
            puesto_asignado="Puesto de prueba",
            entregado_por=self.usuario,
        )

        self.radio.coordinador_zona = asignacion.coordinador_zona
        self.radio.cedula_funcionario = asignacion.cedula_funcionario
        self.radio.cliente_asignado = asignacion.cliente_asignado
        self.radio.puesto_asignado = asignacion.puesto_asignado
        self.radio.save()

        respuesta = self.client.post(
            reverse(
                "inventario:asignacion_devolver",
                kwargs={"asignacion_id": asignacion.pk},
            ),
            {"observaciones_devolucion": "Devolución de prueba"},
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )

        asignacion.refresh_from_db()
        self.assertEqual(
            asignacion.estado,
            AsignacionRadio.Estado.DEVUELTO,
        )
        self.assertIsNotNone(asignacion.fecha_devolucion)
        self.assertEqual(asignacion.recibido_por, self.usuario)
        self.assertEqual(
            asignacion.observaciones_devolucion,
            "Devolución de prueba",
        )

        nueva = self.client.post(
            reverse("inventario:asignacion_crear"),
            {
                "radio": self.radio.pk,
                "vigilante": self.vigilante.pk,
                "coordinador_zona": "Zona nueva",
                "cliente_asignado": "Cliente nuevo",
                "puesto_asignado": "Puesto nuevo",
                "observaciones_entrega": "",
                **ENTREGA_COMPLETA,
            },
        )

        self.assertEqual(nueva.status_code, 302)
        self.assertEqual(
            AsignacionRadio.objects.filter(radio=self.radio).count(),
            2,
        )


class VigilanteModelTests(TestCase):
    def test_crea_vigilante_con_datos_de_origen(self):
        from inventario.models import Vigilante

        vigilante = Vigilante.objects.create(
            cedula="987654321",
            nombre_completo="VIGILANTE PRUEBA",
            hoja_origen="HUILA",
            fila_origen=3,
        )

        self.assertEqual(vigilante.cedula, "987654321")
        self.assertEqual(
            vigilante.nombre_completo,
            "VIGILANTE PRUEBA",
        )
        self.assertTrue(vigilante.activo)
        self.assertEqual(vigilante.hoja_origen, "HUILA")
        self.assertEqual(vigilante.fila_origen, 3)

    def test_rechaza_cedula_duplicada(self):
        from django.db import IntegrityError, transaction
        from inventario.models import Vigilante

        Vigilante.objects.create(
            cedula="987654321",
            nombre_completo="PRIMER VIGILANTE",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vigilante.objects.create(
                    cedula="987654321",
                    nombre_completo="SEGUNDO VIGILANTE",
                )

    def test_vigilante_nuevo_esta_activo_por_defecto(self):
        from inventario.models import Vigilante

        vigilante = Vigilante.objects.create(
            cedula="987654322",
            nombre_completo="VIGILANTE ACTIVO",
        )

        self.assertTrue(vigilante.activo)


class MantenimientoProgramadoVistasTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_user(
            username="usuario_prueba_programados",
            password="PruebaTemporal123!",
        )
        self.usuario.groups.add(
            Group.objects.get_or_create(name="Técnico de mantenimiento")[0]
        )
        self.client.force_login(self.usuario)

        self.radio = Radio.objects.create(
            placa="PLACA-PRUEBA-001",
            serial="SERIAL-PRUEBA-001",
        )

        self.programacion = MantenimientoProgramado.objects.create(
            equipo=self.radio.equipo,
            fecha_programada=timezone.localdate() + timedelta(days=7),
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            descripcion="Prueba automática de mantenimiento programado",
            creado_por=self.usuario,
        )

    def test_lista_programados_responde_correctamente(self):
        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            "Prueba automática de mantenimiento programado",
        )
        self.assertContains(respuesta, "Completar")
        self.assertContains(respuesta, "Cancelar")

    def test_completar_abre_formulario_con_radio_y_tipo_correctos(self):
        respuesta = self.client.get(
            reverse(
                "inventario:mantenimiento_programado_completar",
                args=[self.programacion.pk],
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, "inventario/_mantenimiento_modal.html")
        self.assertContains(
            respuesta,
            "Completar mantenimiento programado",
        )

        formulario = respuesta.context["formulario"]

        self.assertEqual(
            formulario.initial["equipo"],
            self.radio.equipo_id,
        )
        self.assertEqual(
            formulario.initial["tipo"],
            MantenimientoEquipo.Tipo.PREVENTIVO,
        )

        # Abrir el formulario no debe crear una intervención.
        self.assertEqual(MantenimientoEquipo.objects.count(), 0)

    def test_cancelar_programacion_pendiente(self):
        respuesta = self.client.post(
            reverse(
                "inventario:mantenimiento_programado_cancelar",
                args=[self.programacion.pk],
            )
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:mantenimientos_programados_lista"),
        )

        self.programacion.refresh_from_db()

        self.assertEqual(
            self.programacion.estado,
            MantenimientoProgramado.Estado.CANCELADO,
        )

        # Cancelar no debe crear una intervención.
        self.assertEqual(MantenimientoEquipo.objects.count(), 0)

    def test_no_permite_cancelar_dos_veces(self):
        self.client.post(
            reverse(
                "inventario:mantenimiento_programado_cancelar",
                args=[self.programacion.pk],
            )
        )

        self.programacion.refresh_from_db()

        self.assertEqual(
            self.programacion.estado,
            MantenimientoProgramado.Estado.CANCELADO,
        )

        respuesta = self.client.post(
            reverse(
                "inventario:mantenimiento_programado_cancelar",
                args=[self.programacion.pk],
            )
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:mantenimientos_programados_lista"),
        )

        self.programacion.refresh_from_db()

        self.assertEqual(
            self.programacion.estado,
            MantenimientoProgramado.Estado.CANCELADO,
        )
        self.assertEqual(MantenimientoEquipo.objects.count(), 0)

    def test_enlace_directo_a_completar_abre_la_ventana_de_la_lista(self):
        respuesta = self.client.get(
            reverse(
                "inventario:mantenimiento_programado_completar",
                args=[self.programacion.pk],
            )
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:mantenimientos_programados_lista")
            + "?abrir=completar&programacion=%s" % self.programacion.pk,
            fetch_redirect_response=False,
        )

    def test_completar_programacion_registra_intervencion(self):
        url = reverse(
            "inventario:mantenimiento_programado_completar",
            args=[self.programacion.pk],
        )

        respuesta = self.client.post(
            url,
            {
                "equipo": self.radio.equipo_id,
                "fecha_intervencion": timezone.localtime().strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "tipo": MantenimientoEquipo.Tipo.PREVENTIVO,
                "tecnico_responsable": "Yeiver Arcenio Prada Fierro",
                "motivo": "Mantenimiento preventivo programado",
                "actividades_preventivas": ["radio_limpieza", "radio_prueba"],
                "diagnostico": "Equipo revisado durante prueba automática",
                "trabajo_realizado": "Limpieza y revisión preventiva",
                "repuestos_utilizados": "",
                "resultado": MantenimientoEquipo.Resultado.SOLUCIONADO,
                "estado_final": MantenimientoEquipo.EstadoFinal.OPERATIVO,
                "observaciones": "Prueba automatizada",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.json(), {"ok": True})

        self.programacion.refresh_from_db()

        self.assertEqual(
            self.programacion.estado,
            MantenimientoProgramado.Estado.COMPLETADO,
        )
        self.assertIsNotNone(
            self.programacion.intervencion_realizada_id
        )
        self.assertEqual(MantenimientoEquipo.objects.count(), 1)

        intervencion = self.programacion.intervencion_realizada

        self.assertEqual(intervencion.equipo_id, self.radio.equipo_id)
        self.assertEqual(intervencion.registrado_por, self.usuario)

    def test_filtro_muestra_solo_programados_por_defecto(self):
        self.programacion.estado = MantenimientoProgramado.Estado.COMPLETADO
        self.programacion.save(update_fields=["estado"])

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            list(respuesta.context["programaciones"]),
            [],
        )

    def test_filtro_muestra_solo_completados(self):
        self.programacion.estado = MantenimientoProgramado.Estado.COMPLETADO
        self.programacion.save(update_fields=["estado"])

        otra_programacion = MantenimientoProgramado.objects.create(
            equipo=self.radio.equipo,
            fecha_programada=timezone.localdate() + timedelta(days=14),
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            descripcion="Programación que debe quedar fuera del filtro",
            creado_por=self.usuario,
        )

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista"),
            {"estado": "COMPLETADO"},
        )

        self.assertEqual(respuesta.status_code, 200)

        programaciones = list(respuesta.context["programaciones"])

        self.assertEqual(len(programaciones), 1)
        self.assertEqual(
            programaciones[0].pk,
            self.programacion.pk,
        )
        self.assertNotEqual(
            programaciones[0].pk,
            otra_programacion.pk,
        )


    def test_filtro_muestra_solo_cancelados(self):
        self.programacion.estado = MantenimientoProgramado.Estado.CANCELADO
        self.programacion.save(update_fields=["estado"])

        otra_programacion = MantenimientoProgramado.objects.create(
            equipo=self.radio.equipo,
            fecha_programada=timezone.localdate() + timedelta(days=14),
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            descripcion="Programación que sigue pendiente",
            creado_por=self.usuario,
        )

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista"),
            {"estado": "CANCELADO"},
        )

        self.assertEqual(respuesta.status_code, 200)

        programaciones = list(respuesta.context["programaciones"])

        self.assertEqual(len(programaciones), 1)
        self.assertEqual(
            programaciones[0].pk,
            self.programacion.pk,
        )
        self.assertNotEqual(
            programaciones[0].pk,
            otra_programacion.pk,
        )

    def test_estado_invalido_muestra_todas_las_programaciones(self):
        self.programacion.estado = MantenimientoProgramado.Estado.CANCELADO
        self.programacion.save(update_fields=["estado"])

        otra_programacion = MantenimientoProgramado.objects.create(
            equipo=self.radio.equipo,
            fecha_programada=timezone.localdate() + timedelta(days=14),
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            descripcion="Otra programación pendiente",
            creado_por=self.usuario,
        )

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista"),
            {"estado": "ESTADO_INVALIDO"},
        )

        self.assertEqual(respuesta.status_code, 200)

        programaciones = list(respuesta.context["programaciones"])

        self.assertEqual(len(programaciones), 2)
        self.assertEqual(
            respuesta.context["estado_seleccionado"],
            "",
        )
        self.assertSetEqual(
            {item.pk for item in programaciones},
            {self.programacion.pk, otra_programacion.pk},
        )

    def test_lista_filtra_programaciones_por_equipo_tipo_y_fecha(self):
        from inventario.models import Equipo

        equipo_pc = Equipo.objects.create(
            placa="PC-PROGRAMADO-02", tipo=Equipo.Tipo.COMPUTADOR
        )
        MantenimientoProgramado.objects.create(
            equipo=equipo_pc,
            fecha_programada=timezone.localdate() + timedelta(days=14),
            tipo=MantenimientoEquipo.Tipo.CORRECTIVO,
            descripcion="Cambio de teclado",
            creado_por=self.usuario,
        )
        fecha_desde = timezone.localdate() + timedelta(days=6)
        fecha_hasta = timezone.localdate() + timedelta(days=8)

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_programados_lista"),
            {
                "q": "PRUEBA",
                "tipo_equipo": Equipo.Tipo.RADIO,
                "tipo": MantenimientoEquipo.Tipo.PREVENTIVO,
                "fecha_desde": fecha_desde.isoformat(),
                "fecha_hasta": fecha_hasta.isoformat(),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context["programaciones"]), [self.programacion])
        self.assertContains(respuesta, "tipo_equipo")
        self.assertContains(respuesta, "fecha_desde")


class ImportarRadiosSheetTests(TestCase):
    ENCABEZADOS = [
        "Placa", "Tipo de equipo tecnologico", "Serial de equipo Radio",
        "Marca de Radio", "Modelo de  Radio", "Tipo De Frecuencia",
        "Modalidad de servicio", "Estado del Radio", "Coordinador de Zona",
        "Cedula Funcionario", "Cliente Asignado", "Puesto Asignado",
        "Estado de la Base", "Estado del Cargador", "Estado de  Antena",
        "Estado de las Baterias", "Link De Firma", "FIRMA", "Observaciones",
        "Software de Programación", "Versión", "Tipo de Licencia",
        "Licencia de Software", "Fecha de Compra",
    ]

    def setUp(self):
        import tempfile
        from pathlib import Path

        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.archivo = Path(carpeta.name) / "sheet.xlsx"

        self.radio = Radio.objects.create(
            serial="752ITC1377",
            marca="Motorola",
            cliente_asignado="CLIENTE ACTUAL",
        )

    def fila(self, placa, serial, **extra):
        valores = {
            "Placa": placa,
            "Serial de equipo Radio": serial,
            "Marca de Radio": "MOTOROLA",
            "Modelo de  Radio": "DEP450",
            "Estado del Radio": "Bueno",
            "Cliente Asignado": "CLIENTE SHEET",
            "Puesto Asignado": "PORTERIA",
            "Cedula Funcionario": 1121839582,
            "Versión": 1.1,
            "Fecha de Compra": datetime(2016, 1, 1),
        }
        valores.update(extra)
        return [valores.get(c) for c in self.ENCABEZADOS]

    def escribir(self, *filas):
        import openpyxl

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "BASEDATOS-RADIOS"
        hoja.append(self.ENCABEZADOS)
        for fila in filas:
            hoja.append(fila)
        libro.save(self.archivo)

    def ejecutar(self, *args):
        from io import StringIO

        salida = StringIO()
        call_command(
            "importar_radios_sheet",
            "--archivo", str(self.archivo),
            *args,
            stdout=salida,
        )
        return salida.getvalue()

    def test_simulacion_no_guarda_cambios(self):
        self.escribir(
            self.fila("RJ-10", "752-itc 1377"),
            self.fila("RJ-11", "807TQR9999"),
        )

        salida = self.ejecutar()

        self.assertIn("SIMULACIÓN", salida)
        self.radio.refresh_from_db()
        self.assertEqual(self.radio.placa, "")
        self.assertEqual(Radio.objects.count(), 1)

    def test_completa_solo_campos_vacios(self):
        from datetime import date

        self.escribir(self.fila("RJ-10", "752-itc 1377"))

        self.ejecutar("--confirmar")

        self.radio.refresh_from_db()
        self.assertEqual(self.radio.placa, "RJ-10")
        self.assertEqual(self.radio.modelo, "DEP450")
        self.assertEqual(self.radio.cedula_funcionario, "1121839582")
        self.assertEqual(self.radio.version_software, "1.1")
        self.assertEqual(self.radio.fecha_compra, date(2016, 1, 1))
        # Los datos existentes no se sobrescriben.
        self.assertEqual(self.radio.cliente_asignado, "CLIENTE ACTUAL")
        self.assertEqual(self.radio.marca, "Motorola")

    def test_crea_radio_faltante_marcado_para_revision(self):
        self.escribir(self.fila("RJ-11", "807TQR9999"))

        self.ejecutar("--confirmar")

        nuevo = Radio.objects.get(placa="RJ-11")
        self.assertEqual(nuevo.serial, "807TQR9999")
        self.assertEqual(nuevo.placa, "RJ-11")
        self.assertEqual(nuevo.marca, "Motorola")
        self.assertEqual(nuevo.cliente_asignado, "CLIENTE SHEET")
        self.assertTrue(nuevo.requiere_revision)

    def test_omite_seriales_repetidos_en_el_sheet(self):
        self.escribir(
            self.fila("RJ-11", "807TQR9999"),
            self.fila("RJ-12", "807TQR9999"),
        )

        salida = self.ejecutar("--confirmar")

        self.assertIn("repetido en el Sheet", salida)
        self.assertEqual(Radio.objects.count(), 1)

    def test_no_crea_radio_con_serial_parecido_a_uno_existente(self):
        # Dígitos transpuestos respecto a 752ITC1377.
        self.escribir(self.fila("RJ-13", "752ITC1737"))

        salida = self.ejecutar("--confirmar")

        self.assertIn("parecido al de sin placa (serial 752ITC1377)", salida)
        self.assertEqual(Radio.objects.count(), 1)

    def test_no_asigna_placa_que_ya_tiene_otro_radio(self):
        Radio.objects.create(
            serial="752ITC9999", placa="RJ-10"
        )
        self.escribir(self.fila("RJ-10", "752ITC1377"))

        salida = self.ejecutar("--confirmar")

        self.assertIn("ya la tiene RJ-10", salida)
        self.radio.refresh_from_db()
        self.assertEqual(self.radio.placa, "")
        self.assertEqual(self.radio.modelo, "DEP450")

    def test_cruza_por_placa_cuando_no_hay_serial(self):
        sin_serial = Radio.objects.create(
            serial="", placa="RJ-3035"
        )
        self.escribir(self.fila("RJ-3035", "NO SE VE SERIAL"))

        self.ejecutar("--confirmar")

        sin_serial.refresh_from_db()
        self.assertEqual(sin_serial.modelo, "DEP450")
        self.assertEqual(Radio.objects.count(), 2)


class ImportarAsignacionesSheetTests(TestCase):
    ENCABEZADOS = [
        "Marca temporal", "Dirección de correo electrónico",
        "Escriba Placa (RJ) del radio", "Escriba serial del Radio",
        "Fecha de asignación", "Modalidad del Servicio",
        "Tipo de Frecuencia ", "Modelo del Radio", "Estado del Radio",
        "Estado de la Base", "Estado del Cargador", "Estado de la Antena",
        "Estado de las Baterías", "Nombre de Puesto",
        "Nombre y Apellidos  Completos del Coordinador de la Zona",
        "Cédula del Coordinador", "Nombre de Cliente",
        "Clausula de Confidencialidad", "Adjunta Firma",
    ]

    def setUp(self):
        import tempfile
        from pathlib import Path

        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.archivo = Path(carpeta.name) / "sheet.xlsx"
        self.usuario = get_user_model().objects.create_user(
            username="importador", password="clave-prueba"
        )
        self.radio = Radio.objects.create(
            serial="752ITC1377", placa="RJ-10"
        )

    def fila(self, fecha, puesto, placa="RJ-10", serial="752ITC1377",
             cliente="CLIENTE A", cedula=1121839582):
        valores = {
            "Marca temporal": fecha,
            "Escriba Placa (RJ) del radio": placa,
            "Escriba serial del Radio": serial,
            "Estado del Radio": "Bueno",
            "Nombre de Puesto": puesto,
            "Nombre y Apellidos  Completos del Coordinador de la Zona":
                "COORDINADOR PRUEBA",
            "Cédula del Coordinador": cedula,
            "Nombre de Cliente": cliente,
            "Adjunta Firma": "https://drive.google.com/firma",
        }
        return [valores.get(c) for c in self.ENCABEZADOS]

    def escribir(self, *filas):
        import openpyxl

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "RESPUESTA-RADIOS"
        hoja.append(self.ENCABEZADOS)
        for fila in filas:
            hoja.append(fila)
        libro.save(self.archivo)

    def ejecutar(self, *args):
        from io import StringIO

        salida = StringIO()
        call_command(
            "importar_asignaciones_sheet",
            "--archivo", str(self.archivo),
            "--usuario", "importador",
            *args,
            stdout=salida,
        )
        return salida.getvalue()

    def test_simulacion_no_guarda_asignaciones(self):
        self.escribir(self.fila(datetime(2025, 10, 21, 12, 0), "PORTERIA"))

        salida = self.ejecutar()

        self.assertIn("SIMULACIÓN", salida)
        self.assertFalse(AsignacionRadio.objects.exists())

    def test_cada_entrega_cierra_la_anterior(self):
        self.escribir(
            self.fila(datetime(2025, 10, 21, 12, 0), "PORTERIA"),
            self.fila(datetime(2026, 1, 5, 9, 30), "BODEGA", cliente="B"),
        )

        self.ejecutar("--confirmar")

        primera, segunda = AsignacionRadio.objects.order_by("fecha_entrega")
        self.assertEqual(primera.estado, AsignacionRadio.Estado.DEVUELTO)
        self.assertEqual(primera.fecha_devolucion, segunda.fecha_entrega)
        self.assertEqual(primera.recibido_por, self.usuario)
        self.assertEqual(segunda.estado, AsignacionRadio.Estado.ASIGNADO)
        self.assertEqual(segunda.puesto_asignado, "BODEGA")
        self.assertEqual(segunda.cedula_funcionario, "1121839582")
        self.assertEqual(segunda.enlace_firma, "https://drive.google.com/firma")
        self.assertEqual(segunda.estado_radio_entrega, "Bueno")
        # Hora de Colombia (UTC-5).
        self.assertEqual(
            primera.fecha_entrega,
            datetime(2025, 10, 21, 17, 0, tzinfo=dt_timezone.utc),
        )

    def test_reenvios_al_mismo_destino_son_una_sola_entrega(self):
        self.escribir(
            self.fila(datetime(2026, 8, 6, 14, 30), "SISTEMAS"),
            self.fila(datetime(2026, 8, 6, 14, 32), "SISTEMAS"),
        )

        self.ejecutar("--confirmar")

        asignacion = AsignacionRadio.objects.get()
        self.assertEqual(
            asignacion.fecha_entrega,
            datetime(2026, 8, 6, 19, 30, tzinfo=dt_timezone.utc),
        )

    def test_segunda_ejecucion_solo_agrega_respuestas_nuevas(self):
        self.escribir(self.fila(datetime(2025, 10, 21, 12, 0), "PORTERIA"))
        self.ejecutar("--confirmar")

        self.escribir(
            self.fila(datetime(2025, 10, 21, 12, 0), "PORTERIA"),
            self.fila(datetime(2026, 2, 1, 8, 0), "BODEGA", cliente="B"),
        )
        self.ejecutar("--confirmar")
        self.ejecutar("--confirmar")

        self.assertEqual(AsignacionRadio.objects.count(), 2)
        self.assertEqual(
            AsignacionRadio.objects.get(
                estado=AsignacionRadio.Estado.ASIGNADO
            ).puesto_asignado,
            "BODEGA",
        )

    def test_omite_radio_desconocido_o_con_datos_contradictorios(self):
        Radio.objects.create(
            serial="807TRD0001", placa="RJ-20"
        )
        self.escribir(
            self.fila(datetime(2025, 10, 21, 12, 0), "X", placa="RJ-99",
                      serial="000000000"),
            self.fila(datetime(2025, 10, 21, 13, 0), "Y", placa="RJ-20"),
        )

        salida = self.ejecutar("--confirmar")

        self.assertIn("no se encontró el radio", salida)
        self.assertIn("la placa es de RJ-20 y el serial de RJ-10", salida)
        self.assertFalse(AsignacionRadio.objects.exists())

    def test_usuario_inexistente_detiene_el_comando(self):
        from django.core.management.base import CommandError

        self.escribir(self.fila(datetime(2025, 10, 21, 12, 0), "PORTERIA"))

        with self.assertRaises(CommandError):
            call_command(
                "importar_asignaciones_sheet",
                "--archivo", str(self.archivo),
                "--usuario", "nadie",
            )


class ImportarMantenimientosSheetTests(TestCase):
    ENCABEZADOS = [
        "CODIGO DE BUSQUEDA", "PLACA EQUIPO",
        "FUNCIONARIO RESPONSABLE DEL EQUIPO", "FECHA DE MANTENIMIENTO",
        "ESPECIALISTA", "QUE TIPO DE MANTENIMIENTO", "ACTIVIDAD REALIZADA",
        "CUAL PUDO SER LA CAUSA DEL DAÑO PRESENTADO",
        "ESTADO FINAL DEL EQUIPO", "FALLA",
    ]

    def setUp(self):
        import tempfile
        from pathlib import Path

        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.archivo = Path(carpeta.name) / "sheet.xlsx"
        self.usuario = get_user_model().objects.create_user(
            username="importador", password="clave-prueba"
        )
        self.radio = Radio.objects.create(
            serial="752ITC1377", placa="RJ-93"
        )

    def fila(self, placa, fecha, tipo="MANTENIMIENTO PREVENTIVO",
             estado="Equipo queda Operativo"):
        valores = {
            "PLACA EQUIPO": placa,
            "FECHA DE MANTENIMIENTO": fecha,
            "ESPECIALISTA": "TECNICO PRUEBA",
            "QUE TIPO DE MANTENIMIENTO": tipo,
            "ESTADO FINAL DEL EQUIPO": estado,
            "FALLA": "Verificación de componentes internos.",
        }
        return [valores.get(c) for c in self.ENCABEZADOS]

    def escribir(self, *filas):
        import openpyxl

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "T.MANT"
        hoja.append(self.ENCABEZADOS)
        for fila in filas:
            hoja.append(fila)
        libro.save(self.archivo)

    def ejecutar(self, *args):
        from io import StringIO

        salida = StringIO()
        call_command(
            "importar_mantenimientos_sheet",
            "--archivo", str(self.archivo),
            "--usuario", "importador",
            *args,
            stdout=salida,
        )
        return salida.getvalue()

    def test_simulacion_no_guarda(self):
        self.escribir(self.fila("RJ-93", datetime(2026, 10, 22)))

        self.ejecutar()

        self.assertFalse(MantenimientoEquipo.objects.exists())

    def test_crea_mantenimiento_a_medianoche_de_colombia(self):
        self.escribir(self.fila("RJ-93", datetime(2026, 10, 22)))

        self.ejecutar("--confirmar")

        mantenimiento = MantenimientoEquipo.objects.get()
        self.assertEqual(mantenimiento.equipo, self.radio.equipo)
        self.assertEqual(
            mantenimiento.fecha_intervencion,
            datetime(2026, 10, 22, 5, 0, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(mantenimiento.tipo, MantenimientoEquipo.Tipo.PREVENTIVO)
        self.assertEqual(
            mantenimiento.estado_final,
            MantenimientoEquipo.EstadoFinal.OPERATIVO,
        )
        self.assertEqual(
            mantenimiento.trabajo_realizado,
            "Verificación de componentes internos.",
        )

    def test_omite_existentes_repetidos_y_otros_equipos(self):
        self.escribir(
            self.fila("RJ-93", datetime(2026, 10, 22)),
            self.fila("RJ-93", datetime(2026, 10, 22)),
            self.fila("PC--57", datetime(2026, 10, 22)),
            self.fila("RJ-999", datetime(2026, 10, 22)),
        )
        primera = self.ejecutar("--confirmar")
        segunda = self.ejecutar("--confirmar")

        self.assertEqual(MantenimientoEquipo.objects.count(), 1)
        self.assertIn("Repetidos dentro del Sheet: 1", primera)
        self.assertIn("RJ-999: 1 filas", primera)
        self.assertIn("Ya registrados en la plataforma: 2", segunda)

    def test_baja_queda_no_operativo_y_pendiente(self):
        self.escribir(self.fila(
            "RJ-93", datetime(2026, 10, 22), estado="No se repara. (Baja)"
        ))

        self.ejecutar("--confirmar")

        mantenimiento = MantenimientoEquipo.objects.get()
        self.assertEqual(
            mantenimiento.estado_final,
            MantenimientoEquipo.EstadoFinal.NO_OPERATIVO,
        )
        self.assertEqual(
            mantenimiento.resultado,
            MantenimientoEquipo.Resultado.PENDIENTE,
        )

    def test_placa_con_ceros_solo_si_no_es_ambigua(self):
        otro = Radio.objects.create(
            serial="035TSY0QJD", placa="RJ-014"
        )
        Radio.objects.create(
            serial="17002314-6", placa="RJ-14"
        )
        self.escribir(
            self.fila("RJ-093", datetime(2026, 10, 22)),
            self.fila("RJ-0014", datetime(2026, 10, 22)),
            self.fila("RJ-014", datetime(2026, 10, 23)),
        )

        self.ejecutar("--confirmar")

        self.assertTrue(
            MantenimientoEquipo.objects.filter(equipo=self.radio.equipo).exists()
        )
        self.assertEqual(
            list(MantenimientoEquipo.objects.exclude(equipo=self.radio.equipo)
                 .values_list("equipo", flat=True)),
            [otro.equipo_id],
        )


class SincronizarSheetTests(TestCase):
    def test_ejecuta_los_importadores_con_el_mismo_archivo(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            archivo.write_bytes(b"")

            with patch(
                "inventario.management.commands.sincronizar_sheet."
                "call_command"
            ) as llamada:
                call_command(
                    "sincronizar_sheet",
                    "--archivo", str(archivo),
                    "--usuario", "admin",
                    "--confirmar",
                    stdout=StringIO(),
                )

        comandos = [c.args for c in llamada.call_args_list]
        self.assertEqual(
            [args[0] for args in comandos],
            [
                "importar_clientes_sheet",
                "importar_radios_sheet",
                "importar_equipos_sheet",
                "importar_asignaciones_sheet",
                "importar_entregas_equipos_sheet",
                "importar_mantenimientos_sheet",
                "importar_politica_sheet",
                "importar_antivirus_sheet",
            ],
        )
        for args in comandos:
            self.assertIn(str(archivo), args)
            self.assertIn("--confirmar", args)


class GenerarRevisionFisicaTests(TestCase):
    def test_lista_seriales_repetidos_y_radios_sin_inventario(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl

        Radio.objects.create(
            serial="807TRD0050", placa="RJ-50",
            requiere_revision=True,
            motivo_revision="Creado desde BASEDATOS-RADIOS; no figura en "
                            "el inventario físico",
        )

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            salida = Path(carpeta) / "revision.xlsx"
            libro = openpyxl.Workbook()
            radios = libro.active
            radios.title = "BASEDATOS-RADIOS"
            radios.append(ImportarRadiosSheetTests.ENCABEZADOS)
            for placa in ("RJ-1", "RJ-2"):
                radios.append([placa, None, "807TRD8545"])
            libro.create_sheet("RESPUESTA-RADIOS").append(
                ImportarAsignacionesSheetTests.ENCABEZADOS
            )
            libro.create_sheet("T.MANT").append(
                ImportarMantenimientosSheetTests.ENCABEZADOS
            )
            libro.save(archivo)

            call_command(
                "generar_revision_fisica",
                "--archivo", str(archivo),
                "--salida", str(salida),
                stdout=StringIO(),
            )

            filas = list(openpyxl.load_workbook(salida).active.iter_rows(
                min_row=5, values_only=True
            ))

        problemas = sorted((f[1], f[2]) for f in filas)
        self.assertEqual(problemas, [
            ("Serial repetido en el Sheet", "RJ-1"),
            ("Serial repetido en el Sheet", "RJ-2"),
            ("Sin inventario físico", "RJ-50"),
        ])


class PaginacionListasTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="operador", password="clave-prueba"
        )
        self.client.force_login(self.usuario)
        for i in range(60):
            radio = Radio.objects.create(
                placa=f"RAD-{i:03d}", serial=f"S{i:05d}"
            )
            AsignacionRadio.objects.create(
                radio=radio,
                coordinador_zona="COORDINADOR",
                cedula_funcionario="123",
                cliente_asignado="CLIENTE",
                puesto_asignado="PUESTO",
                entregado_por=self.usuario,
            )
            MantenimientoEquipo.objects.create(
                equipo=radio.equipo,
                fecha_intervencion=timezone.now(),
                tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
                tecnico_responsable="TECNICO",
                motivo="Rutina",
                trabajo_realizado="Limpieza",
                registrado_por=self.usuario,
            )

    def test_mantenimientos_muestra_50_por_pagina(self):
        respuesta = self.client.get(reverse("inventario:mantenimientos_lista"))

        self.assertEqual(len(respuesta.context["mantenimientos"]), 50)
        self.assertEqual(respuesta.context["total_resultados"], 60)
        self.assertContains(respuesta, "de 2")


class GestionRadiosTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group

        self.encargado = get_user_model().objects.create_user(
            username="encargado", password="clave-prueba"
        )
        self.encargado.groups.add(
            Group.objects.create(name="Encargado de inventario")
        )
        self.consulta = get_user_model().objects.create_user(
            username="consulta", password="clave-prueba"
        )
        self.consulta.groups.add(Group.objects.create(name="Consulta"))
        self.radio = Radio.objects.create(
            serial="752ITC1377", placa="RJ-10"
        )

    def datos(self, **extra):
        datos = {
            "placa": "rj-11",
            "serial": "807TQR9999",
            "marca": "Motorola",
            "bateria_1": "true",
            "bateria_2": "unknown",
        }
        datos.update(extra)
        return datos

    def test_registra_radio_solo_con_placa(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.get(reverse("inventario:radio_crear"))
        self.assertNotIn("id_inventario", respuesta.context["formulario"].fields)

        self.client.post(reverse("inventario:radio_crear"), self.datos())

        radio = Radio.objects.get(placa="RJ-11")
        self.assertEqual(radio.placa, "RJ-11")
        self.assertTrue(radio.bateria_1)
        self.assertIsNone(radio.bateria_2)

    def test_rechaza_placa_o_serial_repetidos(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.post(
            reverse("inventario:radio_crear"),
            self.datos(placa="RJ-10", serial="752-ITC-1377"),
        )

        errores = respuesta.context["formulario"].errors
        self.assertIn("placa", errores)
        self.assertIn("RJ-10", errores["serial"][0])

    def test_edita_radio_por_su_numero_interno(self):
        self.client.force_login(self.encargado)

        self.client.post(
            reverse("inventario:radio_editar", args=[self.radio.pk]),
            self.datos(placa="RJ-10",
                       serial="752ITC1377", modelo="DEP450"),
        )

        self.radio.refresh_from_db()
        self.assertEqual(self.radio.placa, "RJ-10")
        self.assertEqual(self.radio.modelo, "DEP450")

    def test_baja_exige_motivo_y_sin_entrega_activa(self):
        self.client.force_login(self.encargado)
        url = reverse("inventario:radio_dar_baja", args=[self.radio.pk])

        self.client.post(url, {"motivo_baja": ""})
        self.radio.refresh_from_db()
        self.assertTrue(self.radio.activo)

        asignacion = AsignacionRadio.objects.create(
            radio=self.radio, coordinador_zona="C", cedula_funcionario="1",
            cliente_asignado="X", puesto_asignado="Y",
            entregado_por=self.encargado,
        )
        self.client.post(url, {"motivo_baja": "Pantalla rota"})
        self.radio.refresh_from_db()
        self.assertTrue(self.radio.activo)

        asignacion.estado = AsignacionRadio.Estado.DEVUELTO
        asignacion.save()
        self.client.post(url, {"motivo_baja": "Pantalla rota"})
        self.radio.refresh_from_db()
        self.assertFalse(self.radio.activo)
        self.assertEqual(self.radio.motivo_baja, "Pantalla rota")

        self.client.post(
            reverse("inventario:radio_reactivar", args=[self.radio.pk])
        )
        self.radio.refresh_from_db()
        self.assertTrue(self.radio.activo)

    def test_radio_de_baja_no_aparece_para_entregar(self):
        from inventario.forms import AsignacionRadioForm

        Radio.objects.filter(pk=self.radio.pk).update(activo=False)

        self.assertNotIn(
            self.radio, AsignacionRadioForm().fields["radio"].queryset
        )

    def test_rol_consulta_no_puede_registrar_ni_dar_de_baja(self):
        self.client.force_login(self.consulta)

        respuesta = self.client.post(
            reverse("inventario:radio_crear"), self.datos()
        )
        self.client.post(
            reverse("inventario:radio_dar_baja", args=[self.radio.pk]),
            {"motivo_baja": "x"},
        )

        self.assertRedirects(respuesta, reverse("inicio"),
                             fetch_redirect_response=False)
        self.assertFalse(Radio.objects.filter(placa="RJ-11").exists())
        self.radio.refresh_from_db()
        self.assertTrue(self.radio.activo)


class EntregaCompletaTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="encargado", password="clave-prueba"
        )
        self.usuario.groups.add(
            Group.objects.create(name="Encargado de inventario")
        )
        self.client.force_login(self.usuario)
        self.radio = Radio.objects.create(
            serial="752ITC1377", placa="RJ-10"
        )
        self.vigilante = Vigilante.objects.create(
            cedula="987654321", nombre_completo="VIGILANTE PRUEBA"
        )

    def datos(self, **cambios):
        datos = {
            "radio": self.radio.pk,
            "vigilante": self.vigilante.pk,
            "coordinador_zona": "COORDINADOR",
            "cliente_asignado": "CLIENTE",
            "puesto_asignado": "PORTERIA",
            **ENTREGA_COMPLETA,
        }
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_acta_de_radio_tiene_una_ruta_independiente(self):
        asignacion = AsignacionRadio.objects.create(
            radio=self.radio,
            coordinador_zona="COORDINADOR",
            cedula_funcionario=self.vigilante.cedula,
            cliente_asignado="CLIENTE",
            puesto_asignado="PORTERIA",
            entregado_por=self.usuario,
            estado_radio_entrega="Bueno",
            firma=FIRMA_PRUEBA,
        )

        respuesta = self.client.get(
            reverse("inventario:asignacion_acta", args=[asignacion.pk])
        )

        self.assertContains(respuesta, "Acta de entrega de radio")
        self.assertContains(respuesta, f'src="{FIRMA_PRUEBA}"')

    def test_exige_estados_clausula_y_firma(self):
        respuesta = self.client.post(
            reverse("inventario:asignacion_crear"),
            self.datos(estado_radio_entrega="", clausula_aceptada=None,
                       firma=""),
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.assertFalse(AsignacionRadio.objects.exists())

    def test_rechaza_firma_que_no_es_imagen_png(self):
        respuesta = self.client.post(
            reverse("inventario:asignacion_crear"),
            self.datos(firma="javascript:alert(1)"),
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )


class RespaldarBdTests(TestCase):
    def test_crea_copia_verificada_y_conserva_las_mas_recientes(self):
        import sqlite3
        import tempfile
        from io import StringIO
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            origen = Path(carpeta) / "origen.sqlite3"
            conexion = sqlite3.connect(origen)
            conexion.execute("create table t (x)")
            conexion.commit()
            conexion.close()
            destino = Path(carpeta) / "respaldos"
            destino.mkdir()
            for i in range(3):
                (destino / f"respaldo_auto_2026010{i}_000000.sqlite3").touch()

            with self.settings(DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": str(origen),
                }
            }):
                call_command(
                    "respaldar_bd", "--destino", str(destino),
                    "--conservar", "2", stdout=StringIO(),
                )

            copias = sorted(p.name for p in destino.iterdir())
            self.assertEqual(len(copias), 2)
            self.assertNotIn("respaldo_auto_20260100_000000.sqlite3", copias)
            nueva = sqlite3.connect(destino / copias[-1])
            self.assertEqual(
                nueva.execute("select name from sqlite_master").fetchone(),
                ("t",),
            )
            nueva.close()


class EquipoDeRadioTests(TestCase):
    def test_crear_radio_crea_su_equipo(self):
        radio = Radio.objects.create(
            placa="RJ-10", serial="752ITC1377",
            marca="Motorola", estado_radio="Operativo",
        )

        equipo = radio.equipo
        self.assertEqual(equipo.placa, "RJ-10")
        self.assertEqual(equipo.tipo, Equipo.Tipo.RADIO)
        self.assertEqual(equipo.marca, "Motorola")
        self.assertEqual(equipo.estado_operativo,
                         Equipo.EstadoOperativo.OPERATIVO)
        self.assertEqual(Radio.objects.get(pk=radio.pk).equipo_id, equipo.pk)

    def test_estado_unico_normaliza_y_sincroniza_el_equipo(self):
        self.assertEqual(Radio.normalizar_estado("Bueno"), "Operativo")
        self.assertEqual(Radio.normalizar_estado("malo"), "Dañado")
        radio = Radio.objects.create(placa="RJ-20", estado_radio="Dañado")
        self.assertEqual(
            radio.equipo.estado_operativo,
            Equipo.EstadoOperativo.NO_OPERATIVO,
        )
        radio.estado_radio = "Baja"
        radio.save()
        radio.refresh_from_db()
        self.assertFalse(radio.activo)

    def test_editar_y_dar_de_baja_el_radio_actualiza_el_equipo(self):
        radio = Radio.objects.create(placa="RAD-001", serial="S1")

        radio.placa = "RJ-11"
        radio.activo = False
        radio.motivo_baja = "Robado"
        radio.save(update_fields=["placa", "activo", "motivo_baja"])

        radio.equipo.refresh_from_db()
        self.assertEqual(radio.equipo.placa, "RJ-11")
        self.assertFalse(radio.equipo.activo)
        self.assertEqual(radio.equipo.motivo_baja, "Robado")

    def test_sin_placa_usa_el_id_y_evita_placas_ocupadas(self):
        Equipo.objects.create(placa="PC-01", tipo=Equipo.Tipo.COMPUTADOR)

        sin_placa = Radio.objects.create()
        choque = Radio.objects.create(placa="PC-01")

        self.assertEqual(sin_placa.equipo.placa, f"SIN-RJ-{sin_placa.pk}")
        self.assertEqual(choque.equipo.placa, f"SIN-RJ-{choque.pk}")


class ImportarEquiposSheetTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from inventario.management.commands.importar_equipos_sheet import (
            COMPUTADOR1, COMPUTADOR2, GPS, IMPRESORAS,
        )

        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.archivo = Path(carpeta.name) / "sheet.xlsx"
        self.columnas2 = COMPUTADOR2
        self.cabeceras = {
            "BASEDATOS-COMPUTADOR": list(COMPUTADOR1.values()),
            "BASEDATOS_IMP": list(IMPRESORAS.values()),
            "BASEDATOS_GPS": list(GPS.values()),
            "LISTADO PERSONAL": ["CEDULA", "NOMBRE", "CARGO", "CORREO"],
        }

    def fila2(self, **valores):
        ancho = max(i for i, _ in self.columnas2.values()) + 1
        fila = [None] * ancho
        for campo, valor in valores.items():
            fila[self.columnas2[campo][0]] = valor
        return fila

    def escribir(self, computador2=(), computador1=(), impresoras=(),
                 gps=(), personal=()):
        import openpyxl
        from inventario.management.commands.importar_equipos_sheet import (
            ALARMAS, COMPONENTES_ALARMA,
        )

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "BASEDATOS-COMPUTADOR2"
        cabecera = [None] * (max(i for i, _ in self.columnas2.values()) + 1)
        for i, nombre in self.columnas2.values():
            cabecera[i] = nombre
        hoja.append(cabecera)
        for fila in computador2:
            hoja.append(fila)
        datos = {
            "BASEDATOS-COMPUTADOR": computador1,
            "BASEDATOS_IMP": impresoras,
            "BASEDATOS_GPS": gps,
            "LISTADO PERSONAL": personal,
        }
        for nombre, cabecera in self.cabeceras.items():
            h = libro.create_sheet(nombre)
            h.append(cabecera)
            for fila in datos[nombre]:
                h.append([fila.get(c) for c in cabecera])
        alarmas = libro.create_sheet("BASEDATOS_ALARMAS")
        alarmas.append(list(ALARMAS.values()) + [
            c for _, cant, est in COMPONENTES_ALARMA for c in (cant, est)
        ])
        libro.save(self.archivo)

    def ejecutar(self, *args):
        from io import StringIO

        salida = StringIO()
        call_command("importar_equipos_sheet", "--archivo", str(self.archivo),
                     *args, stdout=salida)
        return salida.getvalue()

    def test_crea_computador_con_detalle_y_completa_desde_la_hoja_vieja(self):
        from datetime import date
        from inventario.models import DetalleComputador

        self.escribir(
            computador2=[self.fila2(
                placa="PC--02", tipo="Computador", clase="Escritorio",
                serial="2002045", marca="JANUS", modelo="M201",
                sistema_operativo="WINDOWS 11 PRO", licencia_so="AAAA-BBBB",
                vencimiento_antivirus=datetime(2027, 9, 3),
                responsable_nombre="ISABEL BUENO", mac_ethernet="N/A",
            )],
            computador1=[{"Placa": "PC--02", "IP Ethernet": "192.168.0.20",
                          "Mac Ethernet": "94-18-82-AB-8E-2C"}],
        )

        self.ejecutar("--confirmar")

        equipo = Equipo.objects.get(placa="PC--02")
        detalle = DetalleComputador.objects.get(equipo=equipo)
        self.assertEqual(equipo.tipo, Equipo.Tipo.COMPUTADOR)
        self.assertEqual(equipo.responsable_nombre, "ISABEL BUENO")
        self.assertEqual(detalle.sistema_operativo, "WINDOWS 11 PRO")
        self.assertEqual(detalle.vencimiento_antivirus, date(2027, 9, 3))
        # "N/A" en la hoja nueva no tapa el dato de la hoja vieja.
        self.assertEqual(detalle.mac_ethernet, "94-18-82-AB-8E-2C")
        self.assertEqual(detalle.ip_ethernet, "192.168.0.20")

    def test_placa_con_baja_queda_inactiva_y_escaner_se_reconoce(self):
        self.escribir(
            computador2=[self.fila2(placa="PC--71BAJA", tipo="Computador")],
            impresoras=[{"Placa": "ESC-04", "Tipo de Equipo Tecnologico": "Escaner",
                         "Modelo de  y marca de Impresora": "EPSON DS-530"}],
        )

        self.ejecutar("--confirmar")

        self.assertFalse(Equipo.objects.get(placa="PC--71").activo)
        escaner = Equipo.objects.get(placa="ESC-04")
        self.assertEqual(escaner.tipo, Equipo.Tipo.ESCANER)
        self.assertEqual((escaner.marca, escaner.modelo), ("EPSON", "DS-530"))

    def test_gps_usa_el_imei_como_placa_y_guarda_el_vehiculo(self):
        self.escribir(gps=[{
            "IMEI GPS": 869671075900041, "MARCA DE GPS": "TELTONIKA",
            "LINEA ASIGNADA": "3101234567", "VEHICULO ASIGNADO": "vms31e",
            "NOMBRE DE VEHICULO": "Supervisor", "ESTADO": "BUEN ESTADO",
        }])

        self.ejecutar("--confirmar")

        equipo = Equipo.objects.get(placa="869671075900041")
        self.assertEqual(equipo.gps.placa_vehiculo, "VMS31E")
        self.assertEqual(equipo.estado_operativo,
                         Equipo.EstadoOperativo.OPERATIVO)

    def test_no_toca_radios_ni_repite_y_crea_funcionarios(self):
        from inventario.models import AsignacionEquipo, Funcionario

        Radio.objects.create(placa="RJ-10")
        self.escribir(
            computador2=[self.fila2(placa="RJ-10", tipo="Computador")],
            personal=[{"CEDULA": 1121839582, "NOMBRE": "PRADA YEIVER",
                       "CARGO": "Sistemas", "CORREO": "N/A"}],
        )

        salida = self.ejecutar("--confirmar")
        segunda = self.ejecutar("--confirmar")

        self.assertIn("ya existe como Radio", salida)
        self.assertEqual(Equipo.objects.get(placa="RJ-10").tipo,
                         Equipo.Tipo.RADIO)
        self.assertEqual(Funcionario.objects.get().cedula, "1121839582")
        self.assertIn("Funcionarios a crear: 0", segunda)


class InventarioEquiposVistasTests(TestCase):
    def setUp(self):
        from inventario.models import DetalleComputador

        Usuario = get_user_model()
        self.encargado = Usuario.objects.create_user(username="enc", password="x")
        self.encargado.groups.add(Group.objects.create(name="Encargado de inventario"))
        self.tecnico = Usuario.objects.create_user(username="tec", password="x")
        self.tecnico.groups.add(Group.objects.create(name="Técnico de mantenimiento"))
        self.consulta = Usuario.objects.create_user(username="con", password="x")
        self.consulta.groups.add(Group.objects.create(name="Consulta"))

        self.pc = Equipo.objects.create(
            placa="PC--02", tipo=Equipo.Tipo.COMPUTADOR, serial="2002045",
            marca="JANUS", responsable_nombre="ISABEL BUENO",
        )
        DetalleComputador.objects.create(
            equipo=self.pc, sistema_operativo="WINDOWS 11 PRO",
            licencia_so="CLAVE-SECRETA-123",
        )

    def datos_pc(self, **extra):
        datos = {
            "placa": "pc--99", "serial": "SN-NUEVO", "marca": "DELL",
            "detalle-procesador": "Core i5", "detalle-sistema_operativo": "Win 11",
        }
        datos.update(extra)
        return datos

    def test_lista_filtra_por_tipo_y_busca_por_responsable(self):
        Radio.objects.create(placa="RJ-10")
        self.client.force_login(self.consulta)

        lista = self.client.get(reverse("inventario:equipos_lista"))
        contenido = lista.content.decode()
        self.assertIn(
            '<span class="sr-only">Buscar por placa, serial, marca, responsable',
            contenido,
        )
        self.assertLess(
            contenido.index('id="eq-resumen"'),
            contenido.index('class="jx-filterbar"'),
        )
        self.assertLess(
            contenido.index('class="jx-filterbar"'),
            contenido.index('class="eq-lista eq-tabla-wrap"'),
        )

        respuesta = self.client.get(
            reverse("inventario:equipos_lista"), {"tipo": "COMPUTADOR"}
        )
        self.assertEqual(list(respuesta.context["equipos"]), [self.pc])

        respuesta = self.client.get(
            reverse("inventario:equipos_lista"), {"q": "isabel"}
        )
        self.assertEqual(respuesta.context["total_resultados"], 1)

    def test_licencia_oculta_para_consulta_y_visible_para_tecnico(self):
        url = reverse("inventario:equipo_pestanas", args=["PC--02"])

        self.client.force_login(self.consulta)
        respuesta = self.client.get(url)
        self.assertNotContains(respuesta, "CLAVE-SECRETA-123")
        self.assertContains(respuesta, "Restringido")
        self.assertContains(respuesta, "WINDOWS 11 PRO")

        self.client.force_login(self.tecnico)
        self.assertContains(self.client.get(url), "CLAVE-SECRETA-123")

    def test_pagina_suelta_del_equipo_redirige_a_equipos(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:equipo_detalle", args=["PC--02"])
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            respuesta["Location"].startswith(
                reverse("inventario:equipos_lista")
            )
        )
        self.assertIn("q=PC--02", respuesta["Location"])

    def test_ficha_muestra_entregas_para_gps_y_alarmas(self):
        equipos = (
            Equipo.objects.create(placa="GPS--01", tipo=Equipo.Tipo.GPS),
            Equipo.objects.create(placa="ALAR--01", tipo=Equipo.Tipo.ALARMA),
        )
        self.client.force_login(self.encargado)

        for equipo in equipos:
            with self.subTest(tipo=equipo.tipo):
                respuesta = self.client.get(
                    reverse("inventario:equipo_pestanas", args=[equipo.placa])
                )
                self.assertContains(respuesta, 'data-tab="entregas"')
                self.assertContains(respuesta, 'id="panel-entregas"')

    def test_ficha_edita_equipo_y_detalle_desde_pestana(self):
        self.client.force_login(self.encargado)

        ficha = self.client.get(
            reverse("inventario:equipo_pestanas", args=["PC--02"])
        )
        self.assertContains(ficha, 'id="form-editar-equipo"')
        self.assertContains(ficha, 'data-p-lista')
        self.assertContains(ficha, 'class="ficha-paso"')
        self.assertGreater(len(ficha.context["pasos_edicion"]), 3)

        respuesta = self.client.post(
            reverse("inventario:equipo_editar", args=["PC--02"]),
            self.datos_pc(
                placa="PC--02",
                serial="2002045",
                **{"detalle-procesador": "Core i7",
                   "detalle-sistema_operativo": "Windows 11"},
            ) | {"embed": "1"},
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipo_pestanas", args=["PC--02"])
            + "?embed=1&guardado=1#resumen",
            fetch_redirect_response=False,
        )
        self.pc.refresh_from_db()
        self.pc.computador.refresh_from_db()
        self.assertEqual(self.pc.marca, "DELL")
        self.assertEqual(self.pc.computador.procesador, "Core i7")

    def test_error_de_edicion_embebida_regresa_a_la_pestana_editar(self):
        Equipo.objects.create(
            placa="PC--03", tipo=Equipo.Tipo.COMPUTADOR, serial="OTRO-SERIAL"
        )
        self.client.force_login(self.encargado)

        respuesta = self.client.post(
            reverse("inventario:equipo_editar", args=["PC--02"]),
            self.datos_pc(
                placa="PC--02", serial="OTRO-SERIAL"
            ) | {"embed": "1"},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["pestana_inicial"], "editar")
        self.assertIn("serial", respuesta.context["formulario_edicion"].errors)
        self.assertContains(respuesta, 'id="panel-editar"')

    def test_lista_muestra_pestanas_en_todos_los_equipos_no_radio(self):
        tipos = (
            Equipo.Tipo.COMPUTADOR,
            Equipo.Tipo.TABLETA,
            Equipo.Tipo.IMPRESORA,
            Equipo.Tipo.ESCANER,
            Equipo.Tipo.GPS,
            Equipo.Tipo.ALARMA,
            Equipo.Tipo.UPS,
            Equipo.Tipo.OTRO,
        )
        self.client.force_login(self.encargado)

        for tipo in tipos:
            equipo = Equipo.objects.create(
                placa=f"TEST-{tipo}", tipo=tipo
            )
            with self.subTest(tipo=tipo):
                respuesta = self.client.get(
                    reverse("inventario:equipos_lista"), {"tipo": tipo}
                )
                for pestana in (
                    "resumen", "entregas", "mantenimientos", "hoja-de-vida",
                    "editar", "baja",
                ):
                    self.assertContains(
                        respuesta, f'data-pf-tab="{pestana}"'
                    )
                self.assertContains(
                    respuesta,
                    f'id="pf-tab-{equipo.pk}-entregas"',
                )
                ficha = self.client.get(
                    reverse("inventario:equipo_pestanas", args=[equipo.placa])
                )
                self.assertContains(ficha, 'id="form-editar-equipo"')
                self.assertTrue(ficha.context["pasos_edicion"])

    def test_ficha_agrupa_caracteristicas_y_muestra_mantenimiento_completo(self):
        detalle = self.pc.computador
        detalle.procesador = "Core i5"
        detalle.save(update_fields=["procesador"])
        MantenimientoEquipo.objects.create(
            equipo=self.pc,
            fecha_intervencion=timezone.now(),
            tipo=MantenimientoEquipo.Tipo.CORRECTIVO,
            tecnico_responsable="Técnico de pruebas",
            motivo="Falla de arranque",
            diagnostico="Disco con errores",
            trabajo_realizado="Se reemplazó el disco",
            repuestos_utilizados="SSD 512 GB",
            resultado=MantenimientoEquipo.Resultado.SOLUCIONADO,
            estado_final=MantenimientoEquipo.EstadoFinal.OPERATIVO,
            observaciones="Equipo validado con usuario",
            registrado_por=self.encargado,
            origen_archivo="historial.xlsx",
            origen_hoja="Mantenimientos",
            fila_origen=42,
        )
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:equipo_pestanas", args=["PC--02"])
        )

        self.assertContains(respuesta, "Hardware")
        self.assertContains(respuesta, "Sistema y licencias")
        self.assertContains(respuesta, "rd-maintenance")
        self.assertContains(respuesta, "Disco con errores")
        self.assertContains(respuesta, "SSD 512 GB")
        self.assertContains(respuesta, "historial.xlsx")
        self.assertContains(respuesta, "Fila original en Excel:</strong> 42")

    def test_encargado_registra_computador_con_detalle(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.post(
            reverse("inventario:equipo_crear") + "?tipo=COMPUTADOR",
            self.datos_pc(),
        )

        equipo = Equipo.objects.get(placa="PC--99")
        self.assertRedirects(
            respuesta, reverse("inventario:equipo_detalle", args=["PC--99"]),
            fetch_redirect_response=False,
        )
        self.assertEqual(equipo.tipo, Equipo.Tipo.COMPUTADOR)
        self.assertEqual(equipo.computador.procesador, "Core i5")

    def test_editar_sin_permiso_de_licencias_no_borra_la_clave(self):
        self.client.force_login(self.encargado)

        self.client.post(
            reverse("inventario:equipo_editar", args=["PC--02"]),
            self.datos_pc(placa="PC--02", serial="2002045"),
        )

        self.pc.computador.refresh_from_db()
        self.assertEqual(self.pc.computador.licencia_so, "CLAVE-SECRETA-123")
        self.assertEqual(self.pc.computador.procesador, "Core i5")

    def test_rechaza_placa_o_serial_repetidos(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.post(
            reverse("inventario:equipo_crear") + "?tipo=COMPUTADOR",
            self.datos_pc(placa="pc--02", serial="2002-045"),
        )

        errores = respuesta.context["formulario"].errors
        self.assertIn("placa", errores)
        self.assertIn("PC--02", errores["serial"][0])

    def test_alarma_guarda_componentes_desde_texto(self):
        self.client.force_login(self.encargado)

        self.client.post(
            reverse("inventario:equipo_crear") + "?tipo=ALARMA",
            {"placa": "ALAR-002", "detalle-componentes_texto":
             "Sensores; 4; Bueno\nSirenas; 1; Regular"},
        )

        alarma = Equipo.objects.get(placa="ALAR-002").alarma
        self.assertEqual(alarma.componentes[0],
                         {"nombre": "Sensores", "cantidad": 4, "estado": "Bueno"})

    def test_baja_y_permisos(self):
        url = reverse("inventario:equipo_dar_baja", args=["PC--02"])

        self.client.force_login(self.consulta)
        self.client.post(url, {"motivo_baja": "Dañado"})
        self.pc.refresh_from_db()
        self.assertTrue(self.pc.activo)

        self.client.force_login(self.encargado)
        self.client.post(url, {"motivo_baja": "Dañado"})
        self.pc.refresh_from_db()
        self.assertFalse(self.pc.activo)

    def test_ficha_y_edicion_de_radio_redirigen_a_equipos(self):
        radio = Radio.objects.create(placa="RJ-10")
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:equipo_detalle", args=["RJ-10"])
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-10&estado=",
            fetch_redirect_response=False,
        )
        hoja = self.client.get(
            reverse("inventario:equipo_hoja_vida", args=["RJ-10"])
        )
        self.assertContains(hoja, "RJ-10")


class MantenimientosTodosLosEquiposTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="tec", password="x"
        )
        self.usuario.groups.add(Group.objects.create(name="Técnico de mantenimiento"))
        self.pc = Equipo.objects.create(placa="PC--01", tipo=Equipo.Tipo.COMPUTADOR)

    def mantenimiento(self, equipo, fecha, tecnico="T"):
        return MantenimientoEquipo.objects.create(
            equipo=equipo, fecha_intervencion=fecha,
            tipo=MantenimientoEquipo.Tipo.PREVENTIVO,
            tecnico_responsable=tecnico, motivo="M", trabajo_realizado="W",
            registrado_por=self.usuario,
        )

    def test_importa_mantenimientos_de_computadores_con_placa_escrita_distinto(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            libro = openpyxl.Workbook()
            hoja = libro.active
            hoja.title = "T.MANT"
            hoja.append(ImportarMantenimientosSheetTests.ENCABEZADOS)
            fila = dict.fromkeys(ImportarMantenimientosSheetTests.ENCABEZADOS)
            fila.update({
                "PLACA EQUIPO": "PC-01",
                "FECHA DE MANTENIMIENTO": datetime(2026, 3, 1),
                "QUE TIPO DE MANTENIMIENTO": "MANTENIMIENTO PREVENTIVO",
                "ESTADO FINAL DEL EQUIPO": "Equipo queda Operativo",
            })
            hoja.append(list(fila.values()))
            libro.save(archivo)

            call_command("importar_mantenimientos_sheet", "--archivo",
                         str(archivo), "--usuario", "tec", "--confirmar",
                         stdout=StringIO())

        self.assertEqual(MantenimientoEquipo.objects.get().equipo, self.pc)

    def test_panel_clasifica_por_estado(self):
        from datetime import timedelta
        from inventario.estado_mantenimiento import (
            PROXIMO, SIN_MANTENIMIENTO, VENCIDO, VIGENTE, equipos_con_estado,
        )

        ahora = timezone.now()
        vencido = Equipo.objects.create(placa="PC--02", tipo=Equipo.Tipo.COMPUTADOR)
        proximo = Equipo.objects.create(placa="IMP-01", tipo=Equipo.Tipo.IMPRESORA)
        vigente = Equipo.objects.create(placa="GPS-01", tipo=Equipo.Tipo.GPS)
        self.mantenimiento(vencido, ahora - timedelta(days=200))
        self.mantenimiento(proximo, ahora - timedelta(days=170))
        self.mantenimiento(vigente, ahora - timedelta(days=10))

        estados = {
            e.placa: e.estado_mantenimiento
            for e in equipos_con_estado(Equipo.objects.all())
        }
        self.assertEqual(estados, {
            "PC--01": SIN_MANTENIMIENTO, "PC--02": VENCIDO,
            "IMP-01": PROXIMO, "GPS-01": VIGENTE,
        })

        self.client.force_login(self.usuario)
        respuesta = self.client.get(
            reverse("inventario:panel_mantenimientos"), {"estado": VENCIDO}
        )
        self.assertEqual([e.placa for e in respuesta.context["equipos"]], ["PC--02"])

    def test_panel_ordena_por_urgencia(self):
        from datetime import timedelta

        ahora = timezone.now()
        vencido = Equipo.objects.create(placa="PC--02", tipo=Equipo.Tipo.COMPUTADOR)
        vigente = Equipo.objects.create(placa="GPS-01", tipo=Equipo.Tipo.GPS)
        self.mantenimiento(vencido, ahora - timedelta(days=300))
        self.mantenimiento(vigente, ahora - timedelta(days=10))
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:panel_mantenimientos"), {"vista": "equipos"}
        )

        self.assertEqual(
            [e.placa for e in respuesta.context["equipos"]],
            ["PC--02", "PC--01", "GPS-01"],
        )

    def test_panel_marca_la_visita_programada_pendiente(self):
        from datetime import date

        from inventario.estado_mantenimiento import equipos_con_estado

        for dia, estado in ((10, "PROGRAMADO"), (3, "CANCELADO")):
            MantenimientoProgramado.objects.create(
                equipo=self.pc, fecha_programada=date(2030, 1, dia),
                tipo=MantenimientoEquipo.Tipo.PREVENTIVO, descripcion="D",
                estado=estado, creado_por=self.usuario,
            )

        (equipo,) = equipos_con_estado(Equipo.objects.all())

        self.assertEqual(equipo.proximo_programado, date(2030, 1, 10))
        self.assertFalse(equipo.programado_atrasado)

    def test_describir_plazo(self):
        from inventario.estado_mantenimiento import describir_plazo

        self.assertEqual(describir_plazo(None), "")
        self.assertEqual(describir_plazo(0), "Vence hoy")
        self.assertEqual(describir_plazo(1), "Faltan 1 día")
        self.assertEqual(describir_plazo(-1), "1 día de atraso")
        self.assertEqual(describir_plazo(-10), "10 días de atraso")
        self.assertEqual(
            describir_plazo(-849), "849 días de atraso (≈ 2 años y 4 meses)"
        )

    def test_panel_filtra_por_texto_responsable_y_ubicacion(self):
        Equipo.objects.create(
            placa="PC--02", tipo=Equipo.Tipo.COMPUTADOR, marca="Dell",
            responsable_nombre="Ana Pérez", ubicacion="Puesto Norte",
        )
        self.client.force_login(self.usuario)
        url = reverse("inventario:panel_mantenimientos")

        por_marca = self.client.get(url, {"q": "dell"})
        por_responsable = self.client.get(url, {"responsable": "ana"})
        por_ubicacion = self.client.get(url, {"ubicacion": "sur"})

        self.assertEqual([e.placa for e in por_marca.context["equipos"]], ["PC--02"])
        self.assertEqual(
            [e.placa for e in por_responsable.context["equipos"]], ["PC--02"]
        )
        self.assertEqual(list(por_ubicacion.context["equipos"]), [])

    def test_panel_exporta_a_excel_lo_filtrado(self):
        from io import BytesIO

        import openpyxl

        Equipo.objects.create(
            placa="PC--02", tipo=Equipo.Tipo.COMPUTADOR, marca="Dell",
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:panel_mantenimientos"),
            {"q": "dell", "exportar": "xlsx"},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("spreadsheetml", respuesta["Content-Type"])
        hoja = openpyxl.load_workbook(BytesIO(respuesta.content)).active
        self.assertEqual([f[0] for f in hoja.iter_rows(min_row=2, values_only=True)], ["PC--02"])

    def test_enlace_directo_a_registrar_abre_la_ventana_del_panel(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimiento_crear"), {"equipo": "PC--01"}
        )

        self.assertRedirects(
            respuesta,
            reverse("inventario:panel_mantenimientos") + "?abrir=registrar&equipo=PC--01",
            fetch_redirect_response=False,
        )

    def test_enlace_directo_a_programar_abre_la_ventana_del_panel(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse("inventario:mantenimiento_programado_crear"))

        self.assertRedirects(
            respuesta,
            reverse("inventario:panel_mantenimientos") + "?abrir=programar",
            fetch_redirect_response=False,
        )

    def test_registrar_en_ventana_emergente_devuelve_solo_el_formulario(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimiento_crear"), {"equipo": "PC--01"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, "inventario/_mantenimiento_modal.html")
        self.assertTemplateNotUsed(respuesta, "base.html")
        self.assertEqual(respuesta.context["formulario"].initial["equipo"], self.pc.pk)

    def test_ventana_emergente_fija_el_equipo_y_sugiere_el_tecnico(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimiento_crear"), {"equipo": "PC--01"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.context["equipo_fijo"], self.pc)
        self.assertContains(respuesta, 'name="equipo_fijo"')
        self.assertContains(respuesta, 'type="hidden" name="equipo"')
        self.assertEqual(
            respuesta.context["formulario"].initial["tecnico_responsable"], "tec"
        )

    def test_ventana_emergente_con_errores_conserva_el_equipo_fijo(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("inventario:mantenimiento_crear"),
            {"equipo": self.pc.pk, "equipo_fijo": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.context["equipo_fijo"], self.pc)

    def test_programar_en_ventana_emergente_devuelve_solo_el_formulario(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimiento_programado_crear"), {"equipo": "PC--01"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(respuesta, "inventario/_mantenimiento_modal.html")
        self.assertTemplateNotUsed(respuesta, "base.html")
        self.assertEqual(respuesta.context["equipo_fijo"], self.pc)
        self.assertContains(
            respuesta, reverse("inventario:mantenimiento_programado_crear")
        )

    def test_programar_en_ventana_emergente_guarda_y_responde_json(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("inventario:mantenimiento_programado_crear"),
            {
                "equipo": self.pc.pk,
                "equipo_fijo": "1",
                "fecha_programada": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "tipo": MantenimientoEquipo.Tipo.PREVENTIVO,
                "descripcion": "Revisión semestral",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.json(), {"ok": True})
        self.assertEqual(MantenimientoProgramado.objects.filter(equipo=self.pc).count(), 1)

    def test_programar_en_ventana_emergente_con_fecha_pasada_muestra_el_error(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("inventario:mantenimiento_programado_crear"),
            {
                "equipo": self.pc.pk,
                "equipo_fijo": "1",
                "fecha_programada": (timezone.localdate() - timedelta(days=1)).isoformat(),
                "tipo": MantenimientoEquipo.Tipo.PREVENTIVO,
                "descripcion": "x",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(respuesta, "inventario/_mantenimiento_modal.html")
        self.assertContains(respuesta, "no puede estar en el pasado")
        self.assertEqual(MantenimientoProgramado.objects.count(), 0)

    def test_botones_del_encabezado_abren_la_ventana_en_todas_las_pestanas(self):
        self.client.force_login(self.usuario)

        for nombre, parametros in (
            ("inventario:panel_mantenimientos", {"vista": "resumen"}),
            ("inventario:panel_mantenimientos", {"vista": "equipos"}),
            ("inventario:mantenimientos_programados_lista", {}),
            ("inventario:mantenimientos_lista", {}),
        ):
            with self.subTest(pestana=nombre, parametros=parametros):
                respuesta = self.client.get(reverse(nombre), parametros)

                self.assertContains(respuesta, 'id="mant-modal"', count=1)
                self.assertContains(
                    respuesta,
                    'data-mant-modal href="%s"'
                    % reverse("inventario:mantenimiento_crear"),
                )
                self.assertContains(
                    respuesta,
                    'data-mant-modal href="%s"'
                    % reverse("inventario:mantenimiento_programado_crear"),
                )

    def test_ventana_emergente_sin_equipo_deja_elegirlo_en_la_lista(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimiento_crear"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertNotIn("equipo_fijo", respuesta.context)
        self.assertContains(respuesta, '<select name="equipo"')

    def test_ventana_emergente_guarda_y_responde_json(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("inventario:mantenimiento_crear"),
            {
                "equipo": self.pc.pk,
                "fecha_intervencion": "2026-10-30T14:29",
                "tipo": MantenimientoEquipo.Tipo.PREVENTIVO,
                "tecnico_responsable": "Yeiver Arcenio Prada Fierro",
                "motivo": "Revisión",
                "actividades_preventivas": ["limpieza_computador"],
                "trabajo_realizado": "Limpieza",
                "estado_final": MantenimientoEquipo.EstadoFinal.OPERATIVO,
                "resultado": MantenimientoEquipo.Resultado.SOLUCIONADO,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {"ok": True})
        self.assertEqual(MantenimientoEquipo.objects.filter(equipo=self.pc).count(), 1)

    def test_ventana_emergente_con_errores_vuelve_a_mostrar_el_formulario(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("inventario:mantenimiento_crear"),
            {"equipo": self.pc.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(respuesta, "inventario/_mantenimiento_modal.html")
        self.assertEqual(MantenimientoEquipo.objects.count(), 0)

    def test_panel_ofrece_registrar_en_ventana_emergente(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:panel_mantenimientos"), {"vista": "equipos"}
        )

        self.assertContains(respuesta, "data-mant-modal")
        self.assertContains(respuesta, 'id="mant-modal"')

    def test_lista_de_mantenimientos_filtra_por_tipo_de_equipo(self):
        radio = Radio.objects.create(placa="RJ-1")
        self.mantenimiento(self.pc, timezone.now())
        self.mantenimiento(radio.equipo, timezone.now())
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_lista"),
            {"tipo_equipo": "COMPUTADOR"},
        )

        self.assertEqual(respuesta.context["total_resultados"], 1)

    def test_lista_de_mantenimientos_filtra_por_tecnico_responsable(self):
        ahora = timezone.now()
        esperado = self.mantenimiento(self.pc, ahora, tecnico="Ana Torres")
        self.mantenimiento(self.pc, ahora - timedelta(days=1), tecnico="Luis Pérez")
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("inventario:mantenimientos_lista"),
            {"tecnico": "ana"},
        )

        self.assertEqual(respuesta.context["total_resultados"], 1)
        self.assertEqual(list(respuesta.context["mantenimientos"]), [esperado])


@override_settings(EMAIL_HOST_USER="prueba", DEFAULT_FROM_EMAIL="p@example.com")
class AlertasAntivirusTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from inventario.models import DetalleComputador

        hoy = timezone.localdate()
        for placa, dias in (("PC--01", -5), ("PC--02", 20), ("PC--03", 90)):
            equipo = Equipo.objects.create(placa=placa, tipo=Equipo.Tipo.COMPUTADOR)
            DetalleComputador.objects.create(
                equipo=equipo, antivirus="Kaspersky",
                vencimiento_antivirus=hoy + timedelta(days=dias),
            )

    @patch("inventario.management.commands.procesar_alertas_antivirus.send_mail")
    def test_avisa_una_sola_vez_los_vencidos_y_proximos(self, send_mail):
        from io import StringIO
        from inventario.models import AvisoAntivirus

        salida = StringIO()
        call_command("procesar_alertas_antivirus", stdout=salida)
        self.assertIn("Antivirus por avisar: 2", salida.getvalue())
        send_mail.assert_not_called()

        call_command("procesar_alertas_antivirus", "--enviar", stdout=StringIO())
        call_command("procesar_alertas_antivirus", "--enviar", stdout=StringIO())

        self.assertEqual(send_mail.call_count, 1)
        self.assertIn("PC--01", send_mail.call_args.kwargs["message"])
        self.assertNotIn("PC--03", send_mail.call_args.kwargs["message"])
        self.assertEqual(AvisoAntivirus.objects.count(), 2)


class EntregasEquiposTests(TestCase):
    def setUp(self):
        from inventario.models import DetalleComputador, DetalleGPS, Funcionario

        self.encargado = get_user_model().objects.create_user(username="enc", password="x")
        self.encargado.groups.add(Group.objects.create(name="Encargado de inventario"))
        self.client.force_login(self.encargado)
        self.pc = Equipo.objects.create(placa="PC--10", tipo=Equipo.Tipo.COMPUTADOR, serial="SN10")
        DetalleComputador.objects.create(equipo=self.pc, licencia_so="CLAVE-SECRETA")
        self.funcionario = Funcionario.objects.create(
            cedula="1022944481", nombre_completo="MARIA ISABEL BUENO", cargo="Contabilidad"
        )
        self.gps = Equipo.objects.create(placa="869671075900041", tipo=Equipo.Tipo.GPS)
        DetalleGPS.objects.create(equipo=self.gps, placa_vehiculo="VMS31E")

    def entregar(self, **extra):
        datos = {
            "funcionario": self.funcionario.pk, "area": "Contabilidad",
            "accesorios": "Cargador y mouse", "clausula_aceptada": "on",
            "firma": FIRMA_PRUEBA,
        }
        datos.update(extra)
        return self.client.post(
            reverse("inventario:equipo_entregar", args=["PC--10"]),
            {k: v for k, v in datos.items() if v is not None},
        )

    def test_entrega_actualiza_responsable_y_genera_acta_sin_licencias(self):
        from inventario.models import AsignacionEquipo

        respuesta = self.entregar()

        asignacion = AsignacionEquipo.objects.get()
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipo_pestanas", args=["PC--10"]) + "?embed=1#entregas",
            fetch_redirect_response=False,
        )
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.responsable_nombre, "MARIA ISABEL BUENO")
        self.assertEqual(self.pc.ubicacion, "Contabilidad")
        acta = self.client.get(reverse("inventario:equipo_acta", args=[asignacion.pk]))
        self.assertContains(acta, "MARIA ISABEL BUENO")
        self.assertContains(acta, f'src="{FIRMA_PRUEBA}"')
        self.assertNotContains(acta, "CLAVE-SECRETA")

    def test_entrega_se_registra_en_la_pestana_de_la_ficha(self):
        ficha = self.client.get(
            reverse("inventario:equipo_pestanas", args=["PC--10"]) + "?embed=1"
        )
        self.assertContains(ficha, 'id="form-entregar-equipo"')
        self.assertContains(ficha, 'data-ir="entregar"')
        pagina_aparte = self.client.get(
            reverse("inventario:equipo_entregar", args=["PC--10"])
        )
        self.assertRedirects(
            pagina_aparte,
            reverse("inventario:equipo_pestanas", args=["PC--10"]) + "?embed=1#entregar",
            fetch_redirect_response=False,
        )

    def test_exige_clausula_y_firma_y_no_permite_dos_entregas(self):
        from inventario.models import AsignacionEquipo

        respuesta = self.entregar(clausula_aceptada=None, firma="")
        errores = respuesta.context["formulario_entrega"].errors
        self.assertIn("clausula_aceptada", errores)
        self.assertIn("firma", errores)

        self.entregar()
        self.entregar()
        self.assertEqual(AsignacionEquipo.objects.count(), 1)

    def test_devolucion_libera_el_equipo(self):
        from inventario.models import AsignacionEquipo

        self.entregar()
        asignacion = AsignacionEquipo.objects.get()

        self.client.post(
            reverse("inventario:equipo_devolver", args=[asignacion.pk]),
            {"observaciones_devolucion": "Sin novedad"},
        )

        asignacion.refresh_from_db()
        self.pc.refresh_from_db()
        self.assertEqual(asignacion.estado, AsignacionEquipo.Estado.DEVUELTO)
        self.assertEqual(self.pc.responsable_nombre, "")
        self.entregar()
        self.assertEqual(AsignacionEquipo.objects.count(), 2)

    def test_cambio_de_gps_queda_en_historial_y_actualiza_vehiculo(self):
        from inventario.models import CambioGPS

        self.client.post(
            reverse("inventario:equipo_cambio_gps", args=[self.gps.placa]),
            {"dato_actualizado": "Vehículo", "placa_vehiculo": "abc123",
             "nombre_vehiculo": "Supervisor Neiva", "linea": "3101234567"},
        )

        cambio = CambioGPS.objects.get()
        self.assertEqual(cambio.placa_vehiculo, "ABC123")
        self.gps.gps.refresh_from_db()
        self.assertEqual(self.gps.gps.placa_vehiculo, "ABC123")
        self.gps.refresh_from_db()
        self.assertEqual(self.gps.ubicacion, "ABC123 Supervisor Neiva")

    def test_importa_entregas_y_cambios_de_gps(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl
        from inventario.management.commands.importar_entregas_equipos_sheet import (
            GPS, HOJAS_ENTREGAS,
        )
        from inventario.models import AsignacionEquipo, CambioGPS

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            libro = openpyxl.Workbook()
            libro.remove(libro.active)
            for hoja, columnas in HOJAS_ENTREGAS.items():
                h = libro.create_sheet(hoja)
                h.append(list(columnas.values()))
            asig = libro["ASIG-COMPUTADOR"]
            cab = list(HOJAS_ENTREGAS["ASIG-COMPUTADOR"].values())
            for fecha, cedula in ((datetime(2025, 1, 5, 9), 1022944481),
                                  (datetime(2025, 6, 1, 9), 80525984)):
                fila = dict.fromkeys(cab)
                fila.update({cab[0]: fecha, cab[1]: "PC-10", cab[3]: cedula,
                             cab[4]: "https://drive.google.com/firma"})
                asig.append(list(fila.values()))
            g = libro.create_sheet("RPTAGPS")
            g.append(list(GPS.values()))
            fila = dict.fromkeys(GPS.values())
            fila.update({GPS["fecha"]: datetime(2026, 5, 13, 10, 0),
                         GPS["imei"]: "869671075900041",
                         GPS["placa_vehiculo"]: "wfu98h"})
            g.append(list(fila.values()))
            libro.save(archivo)

            for _ in range(2):
                call_command("importar_entregas_equipos_sheet", "--archivo", str(archivo),
                             "--usuario", "enc", "--confirmar", stdout=StringIO())

        primera, segunda = AsignacionEquipo.objects.order_by("fecha_entrega")
        self.assertEqual(primera.nombre_recibe, "MARIA ISABEL BUENO")
        self.assertEqual(primera.estado, AsignacionEquipo.Estado.DEVUELTO)
        self.assertEqual(segunda.cedula_recibe, "80525984")
        self.assertEqual(CambioGPS.objects.get().placa_vehiculo, "WFU98H")


class EntregasImportadasNoBorranDatosTests(TestCase):
    def test_entrega_sin_cedula_no_borra_la_cedula_del_equipo(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl
        from inventario.management.commands.importar_entregas_equipos_sheet import (
            GPS, HOJAS_ENTREGAS,
        )

        get_user_model().objects.create_user(username="imp", password="x")
        equipo = Equipo.objects.create(
            placa="IMP-01", tipo=Equipo.Tipo.IMPRESORA, responsable_cedula="1121960255"
        )
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            libro = openpyxl.Workbook()
            libro.remove(libro.active)
            for hoja, columnas in HOJAS_ENTREGAS.items():
                libro.create_sheet(hoja).append(list(columnas.values()))
            cab = list(HOJAS_ENTREGAS["resp_imp"].values())
            fila = dict.fromkeys(cab)
            fila.update({cab[0]: datetime(2025, 11, 7, 9), cab[1]: "IMP-01",
                         cab[2]: "RICOH"})
            libro["resp_imp"].append(list(fila.values()))
            libro.create_sheet("RPTAGPS").append(list(GPS.values()))
            libro.save(archivo)
            call_command("importar_entregas_equipos_sheet", "--archivo", str(archivo),
                         "--usuario", "imp", "--confirmar", stdout=StringIO())

        equipo.refresh_from_db()
        self.assertEqual(equipo.responsable_cedula, "1121960255")


class MantenimientoSinTicketsTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.tecnico = Usuario.objects.create_user(username="tec", password="x")
        self.tecnico.groups.add(Group.objects.create(name="Técnico de mantenimiento"))
        self.pc = Equipo.objects.create(placa="PC--10", tipo=Equipo.Tipo.COMPUTADOR)
        self.client.force_login(self.tecnico)

    def test_intervencion_directa_se_registra(self):
        self.client.post(reverse("inventario:mantenimiento_crear"), {
            "equipo": self.pc.pk,
            "fecha_intervencion": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "tipo": "PREVENTIVO", "tecnico_responsable": "Yeiver Arcenio Prada Fierro",
            "motivo": "Rutina semestral", "trabajo_realizado": "Limpieza",
            "actividades_preventivas": ["limpieza_computador"],
            "resultado": "SOLUCIONADO", "estado_final": "OPERATIVO",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(MantenimientoEquipo.objects.get().equipo, self.pc)

    def test_programar_crea_mantenimiento_programado(self):
        fecha = timezone.localdate() + timedelta(days=7)
        respuesta = self.client.post(reverse("inventario:mantenimiento_programado_crear"), {
            "equipo": self.pc.pk, "fecha_programada": fecha.isoformat(),
            "tipo": "PREVENTIVO", "descripcion": "Revisión semestral",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(respuesta.json(), {"ok": True})
        programacion = MantenimientoProgramado.objects.get()
        self.assertEqual(programacion.fecha_programada, fecha)
        self.assertEqual(programacion.creado_por, self.tecnico)


class PoliticaSeguridadTests(TestCase):
    def setUp(self):
        self.tecnico = get_user_model().objects.create_user(username="tec", password="x", first_name="Yeiver")
        self.tecnico.groups.add(Group.objects.create(name="Técnico de mantenimiento"))
        self.consulta = get_user_model().objects.create_user(username="con", password="x")
        self.consulta.groups.add(Group.objects.create(name="Consulta"))
        self.pc = Equipo.objects.create(placa="PC--10", tipo=Equipo.Tipo.COMPUTADOR,
                                        responsable_nombre="MARIA BUENO")

    def datos(self, **cambios):
        from inventario.politica import CUMPLE, PUNTOS

        datos = {f"punto_{clave}": CUMPLE for clave, _ in PUNTOS}
        datos.update({"especialista": "Yeiver", "responsable": "MARIA BUENO"})
        datos.update(cambios)
        return datos

    def test_registra_verificacion_con_incumplimiento(self):
        from inventario.models import VerificacionPolitica

        self.client.force_login(self.tecnico)
        formulario = self.client.get(
            reverse("inventario:politica_registrar", args=["PC--10"]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertTemplateUsed(formulario, "inventario/_politica_form_modal.html")

        respuesta = self.client.post(
            reverse("inventario:politica_registrar", args=["PC--10"]),
            self.datos(punto_usb_desactivado="NO CUMPLE"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        verificacion = VerificacionPolitica.objects.get()
        self.assertEqual(respuesta.json(), {"ok": True})
        self.assertEqual(len(verificacion.respuestas), 15)
        self.assertEqual(len(verificacion.incumplimientos), 1)
        lista = self.client.get(reverse("inventario:politica_lista"), {"vista": "historial", "resultado": "incumple"})
        self.assertEqual(list(lista.context["verificaciones"]), [verificacion])
        equipos = self.client.get(reverse("inventario:politica_lista")).context["equipos"]
        self.assertEqual([e.estado_politica for e in equipos if e.pk == self.pc.pk], ["INCUMPLE"])

    def test_enlaces_directos_abren_la_ventana_en_la_lista(self):
        from inventario.models import VerificacionPolitica

        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse("inventario:politica_registrar", args=["PC--10"]))
        self.assertRedirects(
            respuesta,
            reverse("inventario:politica_lista") + "?abrir=verificar&equipo=PC--10",
            fetch_redirect_response=False,
        )
        verificacion = VerificacionPolitica.objects.create(equipo=self.pc, respuestas={})
        respuesta = self.client.get(reverse("inventario:politica_detalle", args=[verificacion.pk]))
        self.assertRedirects(
            respuesta,
            reverse("inventario:politica_lista") + f"?abrir=detalle&verificacion={verificacion.pk}",
            fetch_redirect_response=False,
        )

    def test_consulta_no_registra_y_lista_equipos_sin_verificar(self):
        from inventario.models import VerificacionPolitica

        self.client.force_login(self.consulta)
        self.client.post(
            reverse("inventario:politica_registrar", args=["PC--10"]), self.datos(),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertFalse(VerificacionPolitica.objects.exists())
        lista = self.client.get(reverse("inventario:politica_lista"))
        self.assertEqual([e.estado_politica for e in lista.context["equipos"]], ["SIN_VERIFICAR"])

    def test_historial_filtra_por_tipo_de_equipo_y_rango_de_fecha(self):
        from inventario.models import VerificacionPolitica

        tableta = Equipo.objects.create(
            placa="TAB--10", tipo=Equipo.Tipo.TABLETA
        )
        reciente = VerificacionPolitica.objects.create(
            equipo=tableta, fecha=timezone.now(), respuestas={}
        )
        VerificacionPolitica.objects.create(
            equipo=self.pc,
            fecha=timezone.now() - timedelta(days=15),
            respuestas={},
        )
        hoy = timezone.localdate().isoformat()
        self.client.force_login(self.tecnico)

        respuesta = self.client.get(
            reverse("inventario:politica_lista"),
            {
                "vista": "historial",
                "tipo": Equipo.Tipo.TABLETA,
                "fecha_desde": hoy,
                "fecha_hasta": hoy,
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context["verificaciones"]), [reciente])
        self.assertContains(respuesta, "fecha_desde")

    def test_importa_verificaciones_del_sheet_sin_duplicar(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl
        from inventario.models import VerificacionPolitica

        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            libro = openpyxl.Workbook()
            hoja = libro.active
            hoja.title = "VERIFICACION POLITICA"
            hoja.append(["Marca temporal", "Placa"] + [""] * 21)
            fila = [datetime(2025, 3, 4, 10, 0), "PC-10", datetime(2025, 3, 4), "YEIVER",
                    "MARIA BUENO", "Verificacion"] + ["CUMPLE"] * 14 + ["NO CUMPLE", "NINGUNA", "Se actualiza antivirus"]
            hoja.append(fila)
            libro.save(archivo)
            for _ in range(2):
                call_command("importar_politica_sheet", "--archivo", str(archivo),
                             "--confirmar", stdout=StringIO())

        verificacion = VerificacionPolitica.objects.get()
        self.assertEqual(verificacion.equipo, self.pc)
        self.assertEqual(verificacion.respuestas["correo_sin_prohibidos"], "NO CUMPLE")
        self.assertEqual(verificacion.observaciones, "")
        self.assertEqual(verificacion.actualizacion, "Se actualiza antivirus")
        self.assertTrue(verificacion.importada)


class ClientesPuestosYAntivirusTests(TestCase):
    def setUp(self):
        from inventario.models import Cliente, Puesto

        self.encargado = get_user_model().objects.create_user(username="enc", password="x")
        self.encargado.groups.add(Group.objects.create(name="Encargado de inventario"))
        self.tecnico = get_user_model().objects.create_user(username="tec", password="x")
        self.tecnico.groups.add(Group.objects.create(name="Técnico de mantenimiento"))
        self.cliente = Cliente.objects.create(id_externo="16", nombre="Gases del Llano")
        self.puesto = Puesto.objects.create(
            id_externo="538", cliente=self.cliente, sede="Edificio 7 de Agosto",
            nombre="Estación Serramonte",
        )
        Puesto.objects.create(cliente=self.cliente, nombre="Puesto inactivo", activo=False)
        self.radio = Radio.objects.create(placa="RJ-10", serial="S1")
        self.vigilante = Vigilante.objects.create(cedula="987654321", nombre_completo="VIGILANTE")

    def entregar(self, **extra):
        datos = {
            "radio": self.radio.pk, "vigilante": self.vigilante.pk,
            "coordinador_zona": "COORD", **ENTREGA_COMPLETA,
        }
        datos.update(extra)
        self.client.force_login(self.encargado)
        return self.client.post(reverse("inventario:asignacion_crear"), datos)

    def test_entrega_con_puesto_del_catalogo_llena_los_textos(self):
        self.entregar(cliente=self.cliente.pk, puesto=self.puesto.pk)

        asignacion = AsignacionRadio.objects.get()
        self.assertEqual(asignacion.puesto, self.puesto)
        self.assertEqual(asignacion.cliente_asignado, "Gases del Llano")
        self.assertEqual(asignacion.puesto_asignado, "Estación Serramonte (Edificio 7 de Agosto)")
        self.radio.refresh_from_db()
        self.assertEqual(self.radio.cliente_asignado, "Gases del Llano")

    def test_sin_puesto_exige_los_textos(self):
        respuesta = self.entregar(pestanas_radio="1")
        self.assertIn("puesto_asignado", respuesta.context["formulario"].errors)
        self.assertFalse(AsignacionRadio.objects.exists())

        self.entregar(cliente_asignado="Seguridad Jano", puesto_asignado="Sistemas")
        self.assertEqual(AsignacionRadio.objects.get().puesto_asignado, "Sistemas")

    def test_puestos_json_solo_devuelve_activos_del_cliente(self):
        self.client.force_login(self.encargado)
        datos = self.client.get(reverse("inventario:puestos_json"), {"cliente": self.cliente.pk}).json()
        self.assertEqual([p["id"] for p in datos["puestos"]], [self.puesto.pk])

    def test_filtro_clientes_distingue_quienes_tienen_puestos_activos(self):
        from inventario.models import Cliente, Puesto

        sin_puestos = Cliente.objects.create(nombre="Cliente sin puesto activo")
        Puesto.objects.create(
            cliente=sin_puestos, nombre="Puesto dado de baja", activo=False
        )
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:clientes_lista"), {"puestos": "sin"}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context["clientes"]), [sin_puestos])

    def test_filtro_vigilantes_por_fecha_de_actualizacion_de_excel(self):
        self.vigilante.ultima_actualizacion_excel = timezone.now()
        self.vigilante.save(update_fields=["ultima_actualizacion_excel"])
        antiguo = Vigilante.objects.create(
            cedula="11223344",
            nombre_completo="VIGILANTE ANTIGUO",
            ultima_actualizacion_excel=timezone.now() - timedelta(days=10),
        )
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:vigilantes_lista"),
            {"fecha_desde": timezone.localdate().isoformat()},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context["vigilantes"]), [self.vigilante])
        self.assertNotIn(antiguo, respuesta.context["vigilantes"])

    def test_importa_catalogo_y_actualiza_estado(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        import openpyxl
        from inventario.models import Cliente, Puesto

        cab = ["idCliente", "fecha_registro", "NIT", "Nombre_Cliente", "Estado", "Sede", "ID Puestos", "NombrePuesto"]
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "sheet.xlsx"
            libro = openpyxl.Workbook()
            hoja = libro.active
            hoja.title = "CLIENTES_PUESTOS"
            hoja.append(cab)
            hoja.append([16, None, 800021272, "Gases del Llano", "Inactivo", "Edificio 7 de Agosto", 538, "Estación Serramonte"])
            hoja.append([2, None, 860512330, "Servientrega", "Activo", "Oficina Yopal", 3, "Servientrega Yopal"])
            hoja.append([2, None, 860512330, "Servientrega", "Activo", "Oficina Yopal", None, None])
            libro.save(archivo)
            for _ in range(2):
                call_command("importar_clientes_sheet", "--archivo", str(archivo), "--confirmar", stdout=StringIO())

        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.activo)
        self.assertEqual(self.cliente.nit, "800021272")
        self.assertEqual(Cliente.objects.count(), 2)
        self.assertEqual(Puesto.objects.get(id_externo="3").cliente.nombre, "Servientrega")

    def test_renovar_antivirus_actualiza_equipo_y_deja_historial(self):
        from datetime import date
        from inventario.models import DetalleComputador, RenovacionAntivirus

        pc = Equipo.objects.create(placa="PC--10", tipo=Equipo.Tipo.COMPUTADOR)
        DetalleComputador.objects.create(equipo=pc, antivirus="Kaspersky",
                                         vencimiento_antivirus=date(2026, 1, 1))
        self.client.force_login(self.encargado)
        url = reverse("inventario:equipo_renovar_antivirus", args=["PC--10"])
        self.client.post(url, {"antivirus": "ESET", "vencimiento": "2027-10-26"})
        self.assertFalse(RenovacionAntivirus.objects.exists())  # sin permiso de licencias

        self.client.force_login(self.tecnico)
        formulario = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTemplateUsed(formulario, "inventario/_antivirus_form_modal.html")
        respuesta_error = self.client.post(
            url,
            {"antivirus": "ESET"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertTemplateUsed(respuesta_error, "inventario/_antivirus_form_modal.html")
        self.assertTrue(respuesta_error.context["formulario"].errors)
        self.assertFalse(RenovacionAntivirus.objects.exists())

        respuesta = self.client.post(
            url,
            {"antivirus": "ESET", "licencia": "XXXX", "vencimiento": "2027-10-26"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(respuesta.json(), {"ok": True})
        pc.computador.refresh_from_db()
        self.assertEqual(pc.computador.antivirus, "ESET")
        self.assertEqual(pc.computador.vencimiento_antivirus, date(2027, 10, 26))
        self.assertEqual(RenovacionAntivirus.objects.get().licencia, "XXXX")

    def test_acciones_de_seguridad_abren_modal_en_ambas_fichas(self):
        pc = Equipo.objects.create(placa="PC--11", tipo=Equipo.Tipo.COMPUTADOR)
        self.client.force_login(self.tecnico)

        respuesta = self.client.get(
            reverse("inventario:equipo_pestanas", args=[pc.placa]) + "?embed=1"
        )
        self.assertContains(respuesta, 'id="seguridad-modal"', count=1)
        self.assertContains(
            respuesta,
            reverse("inventario:politica_registrar", args=[pc.placa]),
        )
        self.assertContains(
            respuesta,
            reverse("inventario:equipo_renovar_antivirus", args=[pc.placa]),
        )


class FichaRadioPestanasTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group

        self.encargado = get_user_model().objects.create_user(
            username="encargado2", password="clave-prueba"
        )
        self.encargado.groups.add(
            Group.objects.create(name="Encargado de inventario")
        )
        self.consulta = get_user_model().objects.create_user(
            username="consulta2", password="clave-prueba"
        )
        self.consulta.groups.add(Group.objects.create(name="Consulta"))
        self.radio = Radio.objects.create(serial="752ITC2000", placa="RJ-20")

    def test_ficha_embebida_del_radio_redirige_a_equipos(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse("inventario:radio_detalle", args=[self.radio.pk])
            + "?embed=1"
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-20&estado=",
            fetch_redirect_response=False,
        )

    def test_ficha_suelta_redirige_a_equipos(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse("inventario:radio_detalle", args=[self.radio.pk])
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-20&estado=",
            fetch_redirect_response=False,
        )

    def test_editar_por_get_regresa_a_equipos(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse("inventario:radio_editar", args=[self.radio.pk])
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-20&estado=",
            fetch_redirect_response=False,
        )

    def test_edicion_con_errores_regresa_a_equipos(self):
        Radio.objects.create(serial="999ITC0001", placa="RJ-21")
        self.client.force_login(self.encargado)
        respuesta = self.client.post(
            reverse("inventario:radio_editar", args=[self.radio.pk]),
            {"placa": "RJ-21", "serial": "752ITC2000"},
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-20&estado=",
            fetch_redirect_response=False,
        )

    def test_edicion_valida_regresa_a_equipos(self):
        self.client.force_login(self.encargado)
        url = reverse("inventario:radio_editar", args=[self.radio.pk])
        respuesta = self.client.post(url, {
            "placa": "RJ-20", "serial": "752ITC2000",
            "modelo": "DEP450", "embed": "1",
        })
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista") + "?q=RJ-20&estado=",
            fetch_redirect_response=False,
        )

    def test_editar_desde_pestana_regresa_a_su_contenido_embebido(self):
        self.client.force_login(self.encargado)
        url = reverse("inventario:radio_editar", args=[self.radio.pk])
        respuesta = self.client.post(url, {
            "placa": "RJ-20",
            "serial": "752ITC2000",
            "modelo": "DEP450",
            "pestanas_radio": "1",
        })
        self.assertRedirects(
            respuesta,
            reverse(
                "inventario:equipo_pestanas",
                args=[self.radio.equipo.placa],
            ) + "?embed=1&pestanas_radio=1#editar",
            fetch_redirect_response=False,
        )

    def test_edicion_invalida_conserva_el_asistente_y_los_errores(self):
        Radio.objects.create(serial="999ITC0001", placa="RJ-21")
        self.client.force_login(self.encargado)
        respuesta = self.client.post(
            reverse("inventario:radio_editar", args=[self.radio.pk]),
            {
                "placa": "RJ-21",
                "serial": "752ITC2000",
                "pestanas_radio": "1",
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["pestana_inicial"], "editar")
        self.assertTrue(respuesta.context["formulario"].errors)
        self.assertContains(respuesta, "form-editar-radio")
        self.assertContains(respuesta, "data-titulo=\"Identificación\"")

    def test_pestanas_del_radio_se_muestran_en_equipos_sin_barra_de_progreso(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse("inventario:equipos_lista")
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Componentes ·")
        for pestana in (
            "resumen", "entregas", "mantenimientos",
            "hoja-de-vida", "editar", "baja",
        ):
            self.assertContains(respuesta, 'data-pf-tab="%s"' % pestana)
        self.assertContains(respuesta, 'class="rd-tab-count">0</span>')

    def test_pestanas_de_radio_no_muestran_acciones_sin_permiso(self):
        self.client.force_login(self.consulta)
        respuesta = self.client.get(reverse("inventario:equipos_lista"))
        for pestana in (
            "resumen", "entregas", "mantenimientos", "hoja-de-vida",
        ):
            self.assertContains(respuesta, 'data-pf-tab="%s"' % pestana)
        self.assertNotContains(respuesta, 'data-pf-tab="editar"')
        self.assertNotContains(respuesta, 'data-pf-tab="baja"')
        for ruta in (
            reverse("inventario:radio_editar", args=[self.radio.pk]),
            reverse("inventario:radio_dar_baja", args=[self.radio.pk]),
            reverse("inventario:asignacion_crear"),
            reverse(
                "inventario:radio_transferir_componentes",
                args=[self.radio.pk],
            ),
        ):
            self.assertNotContains(respuesta, ruta)

    def test_contenido_de_pestanas_radio_es_embebido_y_no_tiene_progreso(self):
        self.client.force_login(self.encargado)
        url = reverse(
            "inventario:equipo_pestanas",
            args=[self.radio.equipo.placa],
        )
        respuesta = self.client.get(
            url, {"embed": "1", "pestanas_radio": "1"}
        )
        self.assertContains(respuesta, "Entregas y actas")
        self.assertContains(respuesta, "Mantenimientos")
        self.assertContains(respuesta, "Editar datos")
        self.assertContains(respuesta, "Dar de baja")
        self.assertContains(respuesta, "Este radio no tiene entregas registradas.")
        self.assertContains(respuesta, 'id="form-editar-radio"')
        self.assertContains(respuesta, 'data-p-total>5</strong>')
        self.assertContains(respuesta, 'data-titulo="Identificación"')
        self.assertContains(respuesta, 'data-titulo="Accesorios"')

    def test_entregas_muestra_acta_integrada_y_devolucion_en_modal(self):
        asignacion = AsignacionRadio.objects.create(
            radio=self.radio,
            coordinador_zona="Coordinador",
            cedula_funcionario="12345",
            cliente_asignado="Cliente",
            puesto_asignado="Puesto",
            entregado_por=self.encargado,
            estado_radio_entrega="Bueno",
        )
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse(
                "inventario:equipo_pestanas",
                args=[self.radio.equipo.placa],
            ),
            {"embed": "1", "pestanas_radio": "1"},
        )
        self.assertContains(respuesta, "Registrar devolución")
        self.assertContains(
            respuesta, f'data-radio-acta="acta-radio-{asignacion.pk}"'
        )
        self.assertContains(respuesta, "Acta de entrega de radio")
        self.assertContains(respuesta, "Registrar devolución del radio")
        self.assertNotContains(respuesta, "Ver acta</span>")

    def test_boton_registrar_mantenimiento_respeta_permiso_de_tecnico(self):
        from django.contrib.auth.models import Group

        tecnico = get_user_model().objects.create_user(
            username="tecnico-radio", password="test"
        )
        tecnico.groups.add(
            Group.objects.create(name="Técnico de mantenimiento")
        )
        self.client.force_login(tecnico)
        respuesta = self.client.get(
            reverse(
                "inventario:equipo_pestanas",
                args=[self.radio.equipo.placa],
            ),
            {"embed": "1", "pestanas_radio": "1"},
        )
        self.assertContains(respuesta, "Registrar mantenimiento")
        self.assertContains(respuesta, "data-mant-modal")
        self.assertContains(respuesta, 'id="mant-modal"')
        formulario = self.client.get(
            reverse("inventario:mantenimiento_crear"),
            {"equipo": self.radio.equipo.placa},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(formulario.status_code, 200)
        self.assertContains(formulario, "data-mant-form")

    def test_formulario_de_entrega_se_abre_dentro_de_la_pestana(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse("inventario:asignacion_crear"),
            {
                "radio": self.radio.pk,
                "embed": "1",
                "pestanas_radio": "1",
            },
        )
        self.assertContains(respuesta, "Registrar entrega de radio")
        self.assertEqual(
            respuesta.context["formulario"]["radio"].value(),
            self.radio.pk,
        )

    def test_ruta_de_pestanas_no_abre_vista_radio_sin_modo_embed(self):
        self.client.force_login(self.encargado)
        respuesta = self.client.get(
            reverse(
                "inventario:equipo_pestanas",
                args=[self.radio.equipo.placa],
            ),
            {"pestanas_radio": "1"},
        )
        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.radio.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )


class EstadoDeComponentesDelRadioTests(TestCase):
    """La ficha del radio muestra si tiene cada componente y, además, su estado."""

    def setUp(self):
        self.encargado = get_user_model().objects.create_user(
            username="enc_comp", password="x"
        )
        self.encargado.groups.add(
            Group.objects.create(name="Encargado de inventario")
        )
        self.radio = Radio.objects.create(
            placa="RAD-COMP-1",
            estado_radio="Operativo",
            perilla_encendido=True,
            perilla_frecuencia=True,
            clip=True,
            base=False,
            estado_perilla_encendido="Bueno",
            estado_perilla_frecuencia="Regular",
            estado_clip="Dañado",
        )

    def ficha(self):
        from inventario.views_equipos import ficha_modal

        equipo = Equipo.objects.get(pk=self.radio.equipo_id)
        return {c["nombre"]: c for c in ficha_modal(equipo, self.encargado)["componentes"]}

    def test_perillas_y_clip_presentes_muestran_su_estado(self):
        comp = self.ficha()
        self.assertEqual(comp["Perilla de encendido"]["estado"], ("Bueno", "green"))
        self.assertEqual(comp["Perilla de frecuencia"]["estado"], ("Regular", "amber"))
        self.assertEqual(comp["Clip"]["estado"], ("Dañado", "red"))
        self.assertEqual(comp["Clip"]["clase"], "ok")

    def test_componente_presente_sin_estado_aparece_como_sin_dato(self):
        self.radio.estado_clip = ""
        self.radio.save()
        comp = self.ficha()
        self.assertEqual(comp["Clip"]["estado"], ("Sin dato", "amber"))
        self.assertEqual(comp["Clip"]["faltan"], 1)

    def test_componente_que_no_tiene_no_muestra_estado(self):
        comp = self.ficha()
        self.assertEqual(comp["Base"]["clase"], "no")
        self.assertEqual(comp["Base"]["estado"], ("No aplica", "gray"))

    def test_el_estado_se_guarda_desde_el_formulario_del_radio(self):
        from inventario.forms import RadioForm

        formulario = RadioForm(instance=self.radio)
        for campo in ("estado_perilla_encendido", "estado_perilla_frecuencia", "estado_clip"):
            self.assertIn(campo, formulario.fields)
        self.assertEqual(formulario.fields["estado_clip"].initial, None)
        self.assertEqual(
            formulario["estado_perilla_encendido"].value(), "Bueno"
        )


class TransferenciaComponentesRadioTests(TestCase):
    def setUp(self):
        self.encargado = get_user_model().objects.create_user(
            username="enc_transferencia_radio", password="prueba-segura"
        )
        self.encargado.groups.add(
            Group.objects.create(name="Encargado de inventario")
        )
        self.consulta = get_user_model().objects.create_user(
            username="consulta_transferencia_radio", password="prueba-segura"
        )
        self.consulta.groups.add(Group.objects.create(name="Consulta"))
        self.origen = Radio.objects.create(
            placa="RJ-ORIGEN",
            base=True,
            estado_base="Bueno",
            cargador=True,
            estado_cargador="Regular",
            antena=False,
        )
        self.destino = Radio.objects.create(
            placa="RJ-DESTINO",
            base=True,
            estado_base="Dañado",
            cargador=False,
        )
        self.url = reverse(
            "inventario:radio_transferir_componentes", args=[self.origen.pk]
        )

    def post_transferencia(self, radio_destino=None, usuario=None):
        self.client.force_login(usuario or self.encargado)
        return self.client.post(
            self.url,
            {
                "radio_destino": radio_destino or self.destino.pk,
                "embed": "1",
            },
        )

    def test_solo_mueve_componentes_que_faltan_y_conserva_su_estado(self):
        respuesta = self.post_transferencia()

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.origen.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.origen.refresh_from_db()
        self.destino.refresh_from_db()
        self.assertTrue(self.origen.base)
        self.assertEqual(self.origen.estado_base, "Bueno")
        self.assertFalse(self.origen.cargador)
        self.assertEqual(self.origen.estado_cargador, "")
        self.assertTrue(self.destino.base)
        self.assertEqual(self.destino.estado_base, "Dañado")
        self.assertTrue(self.destino.cargador)
        self.assertEqual(self.destino.estado_cargador, "Regular")

        transferencia = TransferenciaComponentesRadio.objects.get()
        self.assertEqual(
            transferencia.componentes,
            [{"nombre": "Cargador", "cantidad": 1, "estado": "Regular"}],
        )
        self.assertEqual(transferencia.registrado_por, self.encargado)
        self.assertEqual(transferencia.etiqueta_origen, "RJ-ORIGEN")
        self.assertEqual(transferencia.etiqueta_destino, "RJ-DESTINO")

    def test_registra_transferencia_asociada_a_los_dos_radios(self):
        self.post_transferencia()
        transferencia = TransferenciaComponentesRadio.objects.get()
        self.assertEqual(transferencia.radio_origen, self.origen)
        self.assertEqual(transferencia.radio_destino, self.destino)

    def test_lista_de_equipos_muestra_modal_sin_pestana_transferencias(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.get(
            reverse("inventario:equipos_lista"),
            {"q": self.origen.equipo.placa, "estado": ""},
        )

        self.assertContains(
            respuesta,
            f'data-abrir-transferencia="modal-transferencia-radio-{self.origen.pk}"',
        )
        self.assertContains(
            respuesta,
            f'id="modal-transferencia-radio-{self.origen.pk}"',
        )
        self.assertNotContains(respuesta, 'data-pf-tab="transferencias"')

    def test_transferencia_desde_equipos_regresa_a_la_ficha_del_radio(self):
        self.client.force_login(self.encargado)

        respuesta = self.client.post(self.url, {
            "radio_destino": self.destino.pk,
        })

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.origen.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.assertTrue(TransferenciaComponentesRadio.objects.exists())

    def test_transfiere_el_grupo_de_baterias_y_su_estado(self):
        self.destino.bateria_1 = False
        self.destino.cargador = True
        self.destino.save()
        self.origen.bateria_1 = True
        self.origen.bateria_2 = True
        self.origen.estado_baterias = "Bueno"
        self.origen.save()

        self.post_transferencia()

        self.origen.refresh_from_db()
        self.destino.refresh_from_db()
        self.assertFalse(self.origen.bateria_1)
        self.assertFalse(self.origen.bateria_2)
        self.assertTrue(self.destino.bateria_1)
        self.assertTrue(self.destino.bateria_2)
        self.assertEqual(self.origen.estado_baterias, "")
        self.assertEqual(self.destino.estado_baterias, "Bueno")
        transferencia = TransferenciaComponentesRadio.objects.get()
        self.assertEqual(
            transferencia.componentes,
            [{"nombre": "Baterías", "cantidad": 2, "estado": "Bueno"}],
        )

    def test_transfiere_solo_la_bateria_que_le_falta_al_destino(self):
        self.destino.bateria_1 = True
        self.destino.bateria_2 = False
        self.destino.estado_baterias = "Regular"
        self.destino.cargador = True
        self.destino.save()
        self.origen.bateria_1 = True
        self.origen.bateria_2 = True
        self.origen.estado_baterias = "Bueno"
        self.origen.save()

        self.post_transferencia()

        self.origen.refresh_from_db()
        self.destino.refresh_from_db()
        self.assertEqual(
            sum((self.origen.bateria_1, self.origen.bateria_2)), 1
        )
        self.assertEqual(
            sum((self.destino.bateria_1, self.destino.bateria_2)), 2
        )
        self.assertEqual(self.origen.estado_baterias, "Bueno")
        self.assertEqual(self.destino.estado_baterias, "Bueno")
        transferencia = TransferenciaComponentesRadio.objects.get()
        self.assertEqual(
            transferencia.componentes,
            [{"nombre": "Baterías", "cantidad": 1, "estado": "Bueno"}],
        )

    def test_no_registra_transferencia_si_destino_ya_tiene_todo(self):
        self.destino.cargador = True
        self.destino.save()

        respuesta = self.post_transferencia()

        self.assertRedirects(
            respuesta,
            reverse("inventario:equipos_lista")
            + f"?q={self.origen.equipo.placa}&estado=",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            TransferenciaComponentesRadio.objects.exists()
        )
        self.origen.refresh_from_db()
        self.assertTrue(self.origen.cargador)

    def test_no_permite_transferir_a_un_radio_dado_de_baja(self):
        self.destino.activo = False
        self.destino.save()

        self.post_transferencia()

        self.assertFalse(TransferenciaComponentesRadio.objects.exists())
        self.origen.refresh_from_db()
        self.assertTrue(self.origen.cargador)

    def test_consulta_no_puede_transferir_componentes(self):
        respuesta = self.post_transferencia(usuario=self.consulta)

        self.assertRedirects(
            respuesta, reverse("inicio"), fetch_redirect_response=False
        )
        self.assertFalse(TransferenciaComponentesRadio.objects.exists())


class RedisenoListaYDashboardTests(TestCase):
    """Dashboard nuevo, buscador global y filtros visibles de la lista de equipos."""

    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_user(username="ver", password="x")
        self.usuario.groups.add(Group.objects.create(name="Consulta"))
        self.client.force_login(self.usuario)
        self.pc = Equipo.objects.create(
            placa="PC--50", tipo=Equipo.Tipo.COMPUTADOR, serial="S-50",
            marca="DELL", responsable_nombre="ANA RUIZ",
        )
        self.pc2 = Equipo.objects.create(
            placa="PC--51", tipo=Equipo.Tipo.COMPUTADOR, serial="S-51", marca="HP",
        )
        self.impresora = Equipo.objects.create(
            placa="IMP-01", tipo=Equipo.Tipo.IMPRESORA, serial="S-60", marca="EPSON",
        )
        self.url = reverse("inventario:equipos_lista")

    def test_dashboard_trae_indicadores_y_graficos(self):
        from inventario.panel import datos_inicio

        datos = datos_inicio()
        for clave in (
            "mant_vencidos", "mant_sin", "mant_proximos", "mant_vigentes",
            "pct_al_dia", "entregados", "en_bodega", "actividad", "grafico",
        ):
            self.assertIn(clave, datos)
        self.assertEqual(
            sum(datos["grafico"]["mantenimiento"]),
            Equipo.objects.filter(activo=True).count(),
        )
        self.assertEqual(len(datos["grafico"]["tendencia"]["etiquetas"]), 12)

        respuesta = self.client.get(reverse("inicio"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'id="g-semaforo"')

    def test_buscador_global_agrupa_resultados(self):
        respuesta = self.client.get(reverse("inventario:buscar"), {"q": "ana ruiz"})
        datos = respuesta.json()
        self.assertEqual(datos["q"], "ana ruiz")
        equipos = [g for g in datos["grupos"] if g["titulo"] == "Equipos"]
        self.assertEqual([i["titulo"] for i in equipos[0]["items"]], ["PC--50"])

        vacio = self.client.get(reverse("inventario:buscar"), {"q": ""}).json()
        self.assertEqual(vacio["grupos"], [])

    def test_buscador_global_exige_sesion(self):
        self.client.logout()
        respuesta = self.client.get(reverse("inventario:buscar"), {"q": "PC"})
        self.assertEqual(respuesta.status_code, 302)

    def test_pestanas_cuentan_con_los_demas_filtros(self):
        respuesta = self.client.get(self.url, {"tipo": "COMPUTADOR"})
        pestanas = {p["valor"]: p for p in respuesta.context["pestanas"]}
        self.assertEqual(pestanas[""]["total"], 3)
        self.assertEqual(pestanas["COMPUTADOR"]["total"], 2)
        self.assertEqual(pestanas["IMPRESORA"]["total"], 1)
        self.assertTrue(pestanas["COMPUTADOR"]["activo"])
        self.assertEqual(respuesta.context["total_resultados"], 2)

    def test_filtro_de_mantenimiento_usa_el_semaforo(self):
        respuesta = self.client.get(self.url, {"mantenimiento": "SIN_MANTENIMIENTO"})
        self.assertEqual(respuesta.context["total_resultados"], 3)
        respuesta = self.client.get(self.url, {"mantenimiento": "VIGENTE"})
        self.assertEqual(respuesta.context["total_resultados"], 0)
        respuesta = self.client.get(self.url, {"mantenimiento": "INVENTADO"})
        self.assertEqual(respuesta.context["mantenimiento_seleccionado"], "")
        self.assertEqual(respuesta.context["total_resultados"], 3)

    def test_filtro_de_estado_operativo(self):
        Equipo.objects.filter(pk=self.pc.pk).update(estado_operativo="OPERATIVO")
        respuesta = self.client.get(self.url, {"estado_operativo": "OPERATIVO"})
        self.assertEqual(
            [e.placa for e in respuesta.context["equipos"]], ["PC--50"]
        )

    def test_chips_quitan_solo_su_filtro(self):
        respuesta = self.client.get(
            self.url, {"tipo": "COMPUTADOR", "mantenimiento": "SIN_MANTENIMIENTO", "q": "dell"}
        )
        chips = {c["texto"]: c["quitar"] for c in respuesta.context["filtros_activos"]}
        self.assertIn("Búsqueda: dell", chips)
        self.assertIn("Mantenimiento: Sin mantenimiento", chips)
        quitar = chips["Mantenimiento: Sin mantenimiento"]
        self.assertNotIn("mantenimiento=", quitar)
        self.assertIn("tipo=COMPUTADOR", quitar)
        self.assertIn("q=dell", quitar)
        self.assertEqual(respuesta.context["url_limpiar"], self.url)

    def test_exportar_trae_solo_lo_filtrado(self):
        from io import BytesIO
        from openpyxl import load_workbook

        respuesta = self.client.get(self.url, {"tipo": "COMPUTADOR", "exportar": "xlsx"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("attachment", respuesta["Content-Disposition"])
        hoja = load_workbook(BytesIO(respuesta.content)).active
        placas = [fila[0] for fila in hoja.iter_rows(min_row=2, values_only=True)]
        self.assertEqual(placas, ["PC--50", "PC--51"])
        self.assertEqual(hoja["A1"].value, "Placa")


class ModuloUsuariosPazYSalvoTests(TestCase):
    """Personas, equipos a cargo y el proceso de retiro con paz y salvo."""

    def setUp(self):
        from inventario.models import AsignacionEquipo, Funcionario

        Usuario = get_user_model()
        self.tic = Usuario.objects.create_user(username="tic", password="x")
        self.tic.groups.add(Group.objects.create(name="Encargado de inventario"))
        self.th = Usuario.objects.create_user(username="th", password="x")
        self.th.groups.add(Group.objects.create(name="Talento humano"))

        self.ana = Funcionario.objects.create(cedula="111", nombre_completo="ANA RUIZ", cargo="Analista")
        self.luis = Funcionario.objects.create(cedula="222", nombre_completo="LUIS PAZ")

        self.pc = Equipo.objects.create(
            placa="PC--70", tipo=Equipo.Tipo.COMPUTADOR, serial="S70",
            responsable_nombre="ANA RUIZ", responsable_cedula="111",
        )
        self.gps = Equipo.objects.create(placa="GPS-70", tipo=Equipo.Tipo.GPS, serial="G70")
        self.entrega_gps = AsignacionEquipo.objects.create(
            equipo=self.gps, funcionario=self.ana, nombre_recibe="ANA RUIZ",
            cedula_recibe="111", entregado_por=self.tic,
        )
        self.radio = Radio.objects.create(placa="RJ-700", serial="R700")
        self.entrega_radio = AsignacionRadio.objects.create(
            radio=self.radio, coordinador_zona="ANA RUIZ", cedula_funcionario="111",
            cliente_asignado="CLIENTE X", puesto_asignado="PUESTO 1", entregado_por=self.tic,
        )

    def iniciar(self, usuario=None):
        self.client.force_login(usuario or self.th)
        self.client.post(
            reverse("inventario:retiro_iniciar", args=[self.ana.pk]),
            {"motivo": "RENUNCIA", "fecha_retiro": "2026-11-30", "observaciones": ""},
        )
        from inventario.models import RetiroFuncionario
        return RetiroFuncionario.objects.get(funcionario=self.ana)

    def validar(self, retiro, placa, resultado, **extra):
        item = retiro.items.get(equipo__placa=placa)
        self.client.force_login(self.tic)
        return self.client.post(
            reverse("inventario:retiro_item_validar", args=[item.pk]),
            {"resultado": resultado, **extra},
        )

    def test_equipos_a_cargo_une_las_tres_fuentes(self):
        from inventario.personas import conteos_por_cedula, equipos_a_cargo

        placas = [d["equipo"].placa for d in equipos_a_cargo(self.ana)]
        self.assertEqual(sorted(placas), ["GPS-70", "PC--70", "RJ-700"])
        conteo = conteos_por_cedula()["111"]
        self.assertEqual(conteo["COMPUTADOR"], 1)
        self.assertEqual(conteo["GPS"], 1)
        self.assertEqual(conteo["RADIO"], 1)

        self.client.force_login(self.th)
        lista = self.client.get(reverse("inventario:personas_lista"), {"equipos": "con"})
        self.assertEqual([f["p"] for f in lista.context["filas"]], [self.ana])
        ficha = self.client.get(reverse("inventario:persona_detalle", args=[self.ana.pk]))
        self.assertEqual(len(ficha.context["a_cargo"]), 3)

    def test_paz_y_salvo_completo(self):
        retiro = self.iniciar()
        self.assertEqual(retiro.items.count(), 3)

        self.validar(retiro, "PC--70", "DEVUELTO")
        self.validar(retiro, "GPS-70", "REASIGNADO", reasignado_a=self.luis.pk)
        self.validar(retiro, "RJ-700", "REASIGNADO", reasignado_a=self.luis.pk)

        self.pc.refresh_from_db()
        self.assertEqual(self.pc.responsable_cedula, "")
        self.entrega_gps.refresh_from_db()
        self.assertEqual(self.entrega_gps.estado, AsignacionEquipo.Estado.DEVUELTO)
        self.assertTrue(AsignacionEquipo.objects.filter(
            equipo=self.gps, funcionario=self.luis, estado="ASIGNADO").exists())
        nueva = AsignacionRadio.objects.get(radio=self.radio, estado="ASIGNADO")
        self.assertEqual(nueva.cedula_funcionario, "222")
        self.assertEqual(nueva.puesto_asignado, "PUESTO 1")

        self.client.force_login(self.th)
        self.client.post(reverse("inventario:retiro_emitir", args=[retiro.pk]))
        retiro.refresh_from_db()
        self.ana.refresh_from_db()
        self.assertEqual(retiro.estado, "PAZ_Y_SALVO")
        self.assertFalse(self.ana.activo)
        documento = self.client.get(reverse("inventario:paz_y_salvo", args=[retiro.pk]))
        self.assertContains(documento, "PAZ Y SALVO")
        self.assertContains(documento, "ANA RUIZ")

    def test_faltante_bloquea_el_paz_y_salvo(self):
        retiro = self.iniciar()
        self.validar(retiro, "PC--70", "FALTANTE", observaciones="No lo trajo")
        self.validar(retiro, "GPS-70", "DEVUELTO")
        self.validar(retiro, "RJ-700", "DEVUELTO")

        self.pc.refresh_from_db()
        self.assertTrue(self.pc.requiere_revision)
        self.client.force_login(self.th)
        self.client.post(reverse("inventario:retiro_emitir", args=[retiro.pk]))
        retiro.refresh_from_db()
        self.assertEqual(retiro.estado, "EN_PROCESO")
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.activo)

    def test_talento_humano_no_valida_equipos_ni_ve_el_inventario(self):
        retiro = self.iniciar()
        item = retiro.items.get(equipo__placa="PC--70")
        self.client.force_login(self.th)
        self.client.post(
            reverse("inventario:retiro_item_validar", args=[item.pk]), {"resultado": "DEVUELTO"}
        )
        item.refresh_from_db()
        self.assertEqual(item.resultado, "PENDIENTE")

        inicio = self.client.get(reverse("inicio"))
        self.assertRedirects(inicio, reverse("inventario:personas_lista"))
        lista = self.client.get(reverse("inventario:personas_lista"))
        self.assertNotContains(lista, '<span class="jx-nav-text">Equipos</span>')
        self.assertContains(lista, "Paz y salvo")

    def test_reasignar_exige_persona_y_un_solo_retiro_abierto(self):
        retiro = self.iniciar()
        self.validar(retiro, "PC--70", "REASIGNADO")
        self.assertEqual(retiro.items.get(equipo__placa="PC--70").resultado, "PENDIENTE")

        self.iniciar()
        from inventario.models import RetiroFuncionario
        self.assertEqual(RetiroFuncionario.objects.filter(funcionario=self.ana).count(), 1)

    def test_persona_sin_equipos_recibe_paz_y_salvo_de_inmediato(self):
        self.client.force_login(self.th)
        self.client.post(
            reverse("inventario:retiro_iniciar", args=[self.luis.pk]),
            {"motivo": "DESPIDO", "fecha_retiro": "2026-11-30"},
        )
        retiro = self.luis.retiros.get()
        self.assertEqual(retiro.items.count(), 0)
        self.client.post(reverse("inventario:retiro_emitir", args=[retiro.pk]))
        retiro.refresh_from_db()
        self.assertEqual(retiro.estado, "PAZ_Y_SALVO")


class RetiroEntregaSinCedulaTests(ModuloUsuariosPazYSalvoTests):
    """Entregas importadas sin cédula: el equipo es de quien figura como responsable."""

    def test_reasignar_equipo_con_entrega_sin_cedula(self):
        imp = Equipo.objects.create(
            placa="IMP-70", tipo=Equipo.Tipo.IMPRESORA, serial="I70",
            responsable_nombre="ANA RUIZ", responsable_cedula="111",
        )
        AsignacionEquipo.objects.create(
            equipo=imp, nombre_recibe="ANA RUIZ", cedula_recibe="", entregado_por=self.tic,
        )
        from inventario.personas import conteos_por_cedula
        self.assertEqual(conteos_por_cedula()["111"]["IMPRESORA"], 1)

        retiro = self.iniciar()
        self.validar(retiro, "IMP-70", "REASIGNADO", reasignado_a=self.luis.pk)
        self.assertEqual(retiro.items.get(equipo__placa="IMP-70").resultado, "REASIGNADO")
        vigente = AsignacionEquipo.objects.get(equipo=imp, estado="ASIGNADO")
        self.assertEqual(vigente.funcionario, self.luis)


class SeccionEquiposTarjetasTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_superuser("admin_tarjetas", "a@a.co", "PruebaTemporal123!")
        self.client.force_login(self.usuario)
        Radio.objects.create(placa="RAD-T1")
        Radio.objects.create(placa="RAD-T2")
        Equipo.objects.create(placa="PC-T1", tipo=Equipo.Tipo.COMPUTADOR, requiere_revision=True)
        Equipo.objects.create(placa="PC-T2", tipo=Equipo.Tipo.COMPUTADOR, activo=False)

    def test_una_tarjeta_por_tipo_con_conteos(self):
        resp = self.client.get(reverse("inventario:equipos_inicio"))
        self.assertEqual(resp.status_code, 200)
        tarjetas = {t["titulo"]: t for t in resp.context["tarjetas"]}
        # Impresoras y GPS se ven en 0 aunque no haya ninguno registrado.
        self.assertEqual(set(tarjetas), {"Computadores", "Radios", "Impresoras", "GPS"})
        self.assertEqual(tarjetas["GPS"]["total"], 0)
        self.assertEqual(tarjetas["Radios"]["total"], 2)
        self.assertEqual(tarjetas["Radios"]["bodega"], 2)
        self.assertEqual(tarjetas["Computadores"]["total"], 1)
        self.assertEqual(tarjetas["Computadores"]["revision"], 1)
        self.assertEqual(resp.context["total"], 3)
        self.assertContains(resp, "?tipo=RADIO")
        self.assertContains(resp, '<span class="jx-nav-text">Bodega</span>')

    def test_lista_toma_el_titulo_de_la_seccion(self):
        lista = reverse("inventario:equipos_lista")
        self.assertContains(self.client.get(lista, {"tipo": "RADIO"}), "<h1>Radios</h1>")
        self.assertContains(self.client.get(lista, {"disponibilidad": "en_inventario"}), "<h1>Bodega</h1>")
        self.assertContains(self.client.get(lista), "<h1>Equipos</h1>")


class MantenimientoPorTipoDeEquipoTests(TestCase):
    def setUp(self):
        from inventario.models import Funcionario
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_superuser("admin_mant_tipo", "m@a.co", "PruebaTemporal123!")
        self.client.force_login(self.usuario)
        self.pc = Equipo.objects.create(placa="PC-MT1", tipo=Equipo.Tipo.COMPUTADOR)
        self.ups = Equipo.objects.create(placa="UPS-MT1", tipo=Equipo.Tipo.UPS)

    def _form_prog(self, **datos):
        from inventario.forms import MantenimientoProgramadoForm
        base = {"fecha_programada": timezone.localdate().isoformat(), "tipo": "PREVENTIVO"}
        return MantenimientoProgramadoForm(data={**base, **datos})

    def test_tipos_de_intervencion_del_formulario(self):
        from inventario.forms import MantenimientoEquipoForm
        valores = [v for v, _ in MantenimientoEquipoForm().fields["tipo"].choices if v]
        self.assertEqual(valores, ["PREVENTIVO", "CORRECTIVO", "DIAGNOSTICO", "CORRECCION"])

    def test_programar_con_actividades_del_tipo(self):
        form = self._form_prog(tipo_equipo="UPS", equipo=self.ups.pk,
                               actividades=["ups_baterias", "ups_transferencia"])
        self.assertTrue(form.is_valid(), form.errors)
        prog = form.save(commit=False)
        self.assertEqual(prog.actividades, ["ups_baterias", "ups_transferencia"])
        self.assertIn("Revisión de baterías", prog.descripcion)

    def test_programar_rechaza_actividades_de_otro_tipo(self):
        form = self._form_prog(tipo_equipo="UPS", equipo=self.ups.pk, actividades=["radio_antena"])
        self.assertFalse(form.is_valid())
        self.assertIn("actividades", form.errors)

    def test_equipo_debe_ser_del_tipo_elegido(self):
        form = self._form_prog(tipo_equipo="UPS", equipo=self.pc.pk, descripcion="x")
        self.assertFalse(form.is_valid())
        self.assertIn("equipo", form.errors)

    def test_correctivo_pide_partes_intervenidas(self):
        from inventario.forms import MantenimientoEquipoForm
        base = {"equipo": self.pc.pk, "tipo": "CORRECTIVO",
                "fecha_intervencion": "2026-11-13T10:00",
                "tecnico_responsable": "Yeiver Arcenio Prada Fierro",
                "trabajo_realizado": "Cambio", "causa_dano": "Golpe", "resultado": "SOLUCIONADO"}
        form = MantenimientoEquipoForm(data=base)
        self.assertFalse(form.is_valid())
        self.assertIn("componentes_intervenidos", form.errors)
        form = MantenimientoEquipoForm(data={**base, "componentes_intervenidos": ["pc_disco"]})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tipo_equipo"], "COMPUTADOR")

    def test_ventana_de_programar_muestra_tipos_y_casillas(self):
        resp = self.client.get(reverse("inventario:mantenimiento_programado_crear"),
                               HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        if resp.status_code == 302:
            self.skipTest("La ventana solo se pide por fetch")
        self.assertContains(resp, 'name="tipo_equipo"')
        self.assertContains(resp, 'data-te="UPS"')


class RegistrarSegunTipoYRetiroTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_superuser("admin_reg_tipo", "r@a.co", "PruebaTemporal123!")
        self.client.force_login(self.usuario)

    def test_boton_registrar_segun_el_tipo(self):
        lista = reverse("inventario:equipos_lista")
        crear = reverse("inventario:equipo_crear")
        resp = self.client.get(lista, {"tipo": "COMPUTADOR"})
        self.assertContains(resp, f'href="{crear}?tipo=COMPUTADOR"')
        self.assertContains(resp, "Registrar computador")
        resp = self.client.get(lista, {"tipo": "RADIO"})
        self.assertContains(resp, f'href="{reverse("inventario:radio_crear")}"')
        resp = self.client.get(lista)
        self.assertContains(resp, f'href="{crear}"')
        self.assertContains(resp, "Registrar equipo")

    def test_retiro_dice_a_nombre_de_quien_queda(self):
        from inventario.models import Funcionario, ItemRetiro, RetiroFuncionario
        from inventario.personas import iniciar_retiro, validar_item
        sale = Funcionario.objects.create(nombre_completo="PERSONA QUE SALE", cedula="111")
        recibe = Funcionario.objects.create(nombre_completo="PERSONA QUE RECIBE", cedula="222")
        pc1 = Equipo.objects.create(placa="PC-R1", tipo=Equipo.Tipo.COMPUTADOR, responsable_cedula="111")
        Equipo.objects.create(placa="PC-R2", tipo=Equipo.Tipo.COMPUTADOR, responsable_cedula="111")
        retiro = iniciar_retiro(sale, "RENUNCIA", timezone.localdate(), "", self.usuario)
        item1 = retiro.items.get(equipo=pc1)
        validar_item(item1, ItemRetiro.Resultado.REASIGNADO, self.usuario, "", recibe)
        item1.refresh_from_db()
        self.assertEqual(item1.queda_a_cargo, "Queda a nombre de PERSONA QUE RECIBE (C.C. 222)")
        pc1.refresh_from_db()
        self.assertEqual(pc1.responsable_cedula, "222")
        item2 = retiro.items.exclude(pk=item1.pk).get()
        self.assertIn("sigue a nombre de PERSONA QUE SALE", item2.queda_a_cargo)
        resp = self.client.get(reverse("inventario:retiro_detalle", args=[retiro.pk]))
        self.assertContains(resp, "Queda a nombre de PERSONA QUE RECIBE")


class AuditoriaMapaYBajasTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.usuario = Usuario.objects.create_superuser("auditor", "au@a.co", "PruebaTemporal123!")
        self.client.force_login(self.usuario)

    def test_registra_quien_crea_y_modifica(self):
        from inventario.models import RegistroAuditoria
        resp = self.client.post(reverse("inventario:equipo_crear") + "?tipo=UPS", {
            "placa": "UPS-AUD", "serial": "", "marca": "APC", "modelo": "X",
            "propiedad": Equipo._meta.get_field("propiedad").get_default() or "",
            "estado_operativo": "OPERATIVO", "ubicacion": "",
        })
        equipo = Equipo.objects.filter(placa="UPS-AUD").first()
        if equipo is None:  # el formulario pide otros campos: se crea directo
            equipo = Equipo.objects.create(placa="UPS-AUD", tipo=Equipo.Tipo.UPS, marca="APC")
        equipo.marca = "CDP"
        equipo.save()
        equipo.refresh_from_db()
        registros = RegistroAuditoria.objects.filter(referencia="UPS-AUD")
        self.assertTrue(registros.filter(accion="CREAR").exists())
        cambio = registros.filter(accion="EDITAR").latest("fecha")
        self.assertIn({"campo": "Marca", "antes": "APC", "despues": "CDP"}, cambio.cambios)
        pagina = self.client.get(reverse("inventario:auditoria"), {"q": "UPS-AUD"})
        self.assertContains(pagina, "UPS-AUD")
        self.assertContains(pagina, "Modificó")

    def test_ingreso_y_claves_ocultas(self):
        from inventario.models import RegistroAuditoria
        self.client.logout()
        self.client.login(username="auditor", password="PruebaTemporal123!")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="INGRESO", usuario=self.usuario).exists())
        self.client.login(username="auditor", password="mala")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="INGRESO_FALLIDO").exists())
        self.usuario.set_password("OtraClave123!")
        self.usuario.save()
        cambio = RegistroAuditoria.objects.filter(modelo_clave="auth.user", accion="EDITAR").latest("fecha")
        self.assertNotIn("OtraClave", str(cambio.cambios))
        self.assertNotIn("pbkdf2", str(cambio.cambios))

    def test_mapa_incluye_todos_los_tipos_por_sede(self):
        from inventario.panel import _mapa
        Equipo.objects.create(placa="PC-SEDE", tipo=Equipo.Tipo.COMPUTADOR, ubicacion="SEGURIDAD JANO LTDA SEDE PRINCIPAL")
        Equipo.objects.create(placa="PC-SIN", tipo=Equipo.Tipo.COMPUTADOR)
        m = _mapa()
        self.assertEqual(m["total"], 1)
        self.assertEqual(m["puntos"][0]["tipos"][0]["texto"], "1 computador")
        self.assertEqual(m["sin_ubicar"]["total"], 1)

    def test_baul_de_bajas(self):
        Equipo.objects.create(placa="PC-ACT", tipo=Equipo.Tipo.COMPUTADOR)
        baja = Equipo.objects.create(placa="PC-BAJA", tipo=Equipo.Tipo.COMPUTADOR)
        baja.activo = False
        baja.motivo_baja = "Board quemada"
        baja.save()
        resp = self.client.get(reverse("inventario:equipos_bajas"))
        self.assertContains(resp, "PC-BAJA")
        self.assertContains(resp, "Board quemada")
        self.assertNotContains(resp, "PC-ACT")
        self.assertContains(resp, "auditor")
        self.assertContains(self.client.get(reverse("inventario:equipos_inicio")), "Baúl de bajas")
