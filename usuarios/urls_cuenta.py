"""Crear o recuperar la contraseña con un enlace enviado al correo."""
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .cuenta import RecuperarClaveForm

urlpatterns = [
    path("recuperar/", auth_views.PasswordResetView.as_view(
        form_class=RecuperarClaveForm,
        template_name="cuenta/recuperar.html",
        email_template_name="cuenta/correo_clave.txt",
        subject_template_name="cuenta/correo_clave_asunto.txt",
        success_url=reverse_lazy("cuenta_enviado"),
    ), name="cuenta_recuperar"),
    path("recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(
        template_name="cuenta/enviado.html",
    ), name="cuenta_enviado"),
    path("clave/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="cuenta/crear_clave.html",
        success_url=reverse_lazy("cuenta_lista"),
    ), name="crear_clave"),
    path("clave/lista/", auth_views.PasswordResetCompleteView.as_view(
        template_name="cuenta/lista.html",
    ), name="cuenta_lista"),
]
