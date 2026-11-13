"""Mesa de ayuda: solicitud pública por cédula y equipo, cola TIC y atención."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventario.models import Equipo, Funcionario, MantenimientoEquipo, Ticket


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="jano@example.com",
)
class SolicitudPublicaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.persona = Funcionario.objects.create(
            cedula="1075000111", nombre_completo="Ana Prueba", correo="ana@example.com",
        )
        self.pc = Equipo.objects.create(
            placa="PC--900", tipo=Equipo.Tipo.COMPUTADOR, responsable_cedula="1075000111",
        )
        self.otro = Equipo.objects.create(placa="IMP-900", tipo=Equipo.Tipo.IMPRESORA)
        self.url = reverse("soporte")

    def test_paso_1_rechaza_cedula_desconocida(self):
        r = self.client.post(self.url, {"paso": "1", "cedula": "999"})
        self.assertContains(r, "no está en el listado")

    def test_paso_1_muestra_los_equipos_de_la_persona(self):
        r = self.client.post(self.url, {"paso": "1", "cedula": "1.075.000.111"})
        self.assertContains(r, "PC--900")
        self.assertNotContains(r, "IMP-900")
        self.assertContains(r, "ana@example.com")

    def test_campo_trampa_bloquea_robots(self):
        r = self.client.post(self.url, {"paso": "1", "cedula": "1075000111", "sitio_web": "x"})
        self.assertNotContains(r, "PC--900")

    def test_paso_2_crea_la_solicitud_y_avisa(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url, {
            "paso": "2", "cedula": "1075000111",
            "categoria": Ticket.Categoria.EQUIPO_OFICINA, "equipo": str(self.pc.pk),
            "descripcion": "No enciende", "ubicacion": "Sede principal",
            "correo": "ana@example.com",
            })
        ticket = Ticket.objects.get()
        self.assertRedirects(r, reverse("soporte_caso", args=[ticket.token]))
        self.assertEqual(ticket.equipo, self.pc)
        self.assertEqual(ticket.funcionario, self.persona)
        self.assertEqual(ticket.tipo, Ticket.Tipo.CORRECTIVO)
        self.assertEqual(ticket.origen, Ticket.Origen.FORMULARIO)
        self.assertTrue(any("ana@example.com" in m.to for m in mail.outbox))
        caso = self.client.get(r.url)
        self.assertContains(caso, ticket.numero)

    def test_otro_equipo_por_placa(self):
        self.client.post(self.url, {
            "paso": "2", "cedula": "1075000111",
            "categoria": Ticket.Categoria.EQUIPO_OFICINA, "equipo": "otro", "placa": "imp-900",
            "descripcion": "Atasca papel", "ubicacion": "Sede", "correo": "ana@example.com",
        })
        self.assertEqual(Ticket.objects.get().equipo, self.otro)

    def test_sin_equipo_solo_para_software(self):
        datos = {
            "paso": "2", "cedula": "1075000111", "equipo": "ninguno",
            "descripcion": "No llega el correo", "ubicacion": "Sede", "correo": "ana@example.com",
        }
        r = self.client.post(self.url, dict(datos, categoria=Ticket.Categoria.EQUIPO_OFICINA))
        self.assertContains(r, "Elija el equipo")
        self.assertFalse(Ticket.objects.exists())
        self.client.post(self.url, dict(datos, categoria=Ticket.Categoria.SOFTWARE))
        ticket = Ticket.objects.get()
        self.assertIsNone(ticket.equipo)
        self.assertEqual(ticket.tipo, Ticket.Tipo.SOPORTE)

    def test_paso_2_con_cedula_alterada_vuelve_al_paso_1(self):
        r = self.client.post(self.url, {"paso": "2", "cedula": "123", "categoria": "SOFTWARE"})
        self.assertContains(r, "no está en el listado")
        self.assertFalse(Ticket.objects.exists())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ColaTicTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.encargado = User.objects.create_user("enc", password="x-prueba-1")
        self.encargado.groups.add(Group.objects.get_or_create(name="Encargado de inventario")[0])
        self.tecnico = User.objects.create_user("tec", password="x-prueba-1", first_name="Tomás")
        self.tecnico.groups.add(Group.objects.get_or_create(name="Técnico de mantenimiento")[0])
        self.pc = Equipo.objects.create(placa="PC--901", tipo=Equipo.Tipo.COMPUTADOR)
        from inventario import tickets as flujo
        self.ticket = flujo.crear(
            origen=Ticket.Origen.FORMULARIO, tipo=Ticket.Tipo.CORRECTIVO,
            categoria=Ticket.Categoria.EQUIPO_OFICINA, equipo=self.pc,
            descripcion="Pantalla azul", solicitante_nombre="Ana",
        )

    def test_cola_y_detalle_cargan(self):
        self.client.force_login(self.encargado)
        r = self.client.get(reverse("inventario:tickets_lista"))
        self.assertContains(r, self.ticket.numero)
        r = self.client.get(reverse("inventario:ticket_detalle", args=[self.ticket.numero]))
        self.assertContains(r, "Asignar técnico")
        r = self.client.get(reverse("inventario:tickets_indicadores"))
        self.assertEqual(r.status_code, 200)

    def test_asignar_fija_tecnico_y_prioridad(self):
        self.client.force_login(self.encargado)
        self.client.post(reverse("inventario:ticket_asignar", args=[self.ticket.numero]), {
            "tecnico": self.tecnico.pk, "prioridad": "ALTA",
        })
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.tecnico, self.tecnico)
        self.assertEqual(self.ticket.prioridad, "ALTA")
        self.assertEqual(self.ticket.estado, Ticket.Estado.ASIGNADO)

    def test_atender_registra_la_intervencion_del_equipo(self):
        self.client.force_login(self.tecnico)
        url = reverse("inventario:ticket_atender", args=[self.ticket.numero])
        r = self.client.get(url)
        self.assertContains(r, "Intervención en PC--901")
        self.assertEqual(r.context["intervencion"]["tipo"].value(), "CORRECTIVO")
        r = self.client.post(url, {
            "fecha_intervencion": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "tipo": "DIAGNOSTICO",
            "tecnico_responsable": "Daniel Felipe Jiménez Loaiza",
            "motivo": "Pantalla azul",
            "diagnostico": "Memoria RAM dañada",
            "trabajo_realizado": "Se revisó el equipo",
            "resultado": MantenimientoEquipo._meta.get_field("resultado").choices[0][0],
            "estado_final": "OPERATIVO",
            "solucion": "Se cambió la memoria",
        })
        if r.status_code != 302:
            self.fail(r.context["intervencion"].errors.as_text() + r.context["formulario"].errors.as_text())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, Ticket.Estado.RESUELTO)
        intervencion = self.ticket.intervenciones.get()
        self.assertEqual(intervencion.equipo, self.pc)
