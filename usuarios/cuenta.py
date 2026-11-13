"""Enlaces para crear la contraseña (primer ingreso) o recuperarla."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class RecuperarClaveForm(PasswordResetForm):
    """Como el de Django, pero también sirve para quien aún no ha creado su
    contraseña (cuentas nuevas sin contraseña)."""

    def get_users(self, email):
        return get_user_model()._default_manager.filter(email__iexact=email, is_active=True)


def enlace_crear_clave(usuario):
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    return settings.SITIO_URL_PUBLICO.rstrip("/") + reverse("crear_clave", args=[uid, token])


def enviar_bienvenida(usuario, nombre):
    """Correo de bienvenida con el enlace para crear la contraseña."""
    cuerpo = render_to_string("cuenta/correo_bienvenida.txt", {
        "nombre": nombre, "usuario": usuario.get_username(),
        "enlace": enlace_crear_clave(usuario),
        "entrar": settings.SITIO_URL_PUBLICO.rstrip("/") + reverse("login"),
        "horas": settings.PASSWORD_RESET_TIMEOUT // 3600,
    })
    send_mail(
        "Tu acceso a la mesa de ayuda de Seguridad Jano", cuerpo,
        settings.DEFAULT_FROM_EMAIL, [usuario.email], fail_silently=False,
    )
