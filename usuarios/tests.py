from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


class UsuarioEditarTests(TestCase):
    def setUp(self):
        Usuario = get_user_model()
        self.admin = Usuario.objects.create_superuser(
            username="admin", password="clave-prueba"
        )
        self.usuario = Usuario.objects.create_user(
            username="darka", password="clave-prueba"
        )
        self.usuario.groups.add(
            Group.objects.create(name="Técnico de mantenimiento")
        )

    def datos(self, **cambios):
        datos = {
            "cedula": "1029984706",
            "first_name": "Darka",
            "last_name": "Prueba",
            "email": "darka@example.com",
            "is_active": "on",
            "rol": "Encargado de inventario",
        }
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_cambia_el_rol_reemplazando_el_anterior(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("usuario_editar", args=[self.usuario.pk]), self.datos()
        )

        self.assertEqual(
            list(self.usuario.groups.values_list("name", flat=True)),
            ["Encargado de inventario"],
        )

    def test_solo_el_superusuario_puede_editar(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(
            reverse("usuario_editar", args=[self.usuario.pk]), self.datos()
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            self.usuario.groups.filter(name="Técnico de mantenimiento").exists()
        )

    def test_no_permite_desactivarse_a_si_mismo(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("usuario_editar", args=[self.admin.pk]),
            self.datos(is_active=None),
        )

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
