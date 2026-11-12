
from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("login/", views.login_view, name="login"),
    path(
        "logout/",
        LogoutView.as_view(next_page="login"),
        name="logout",
    ),
    path(
        "usuarios/",
        views.usuarios_lista,
        name="usuarios_lista",
    ),
    path(
        "usuarios/<int:usuario_id>/editar/",
        views.usuario_editar,
        name="usuario_editar",
    ),
    path(
        "usuarios/crear/",
        views.usuario_crear,
        name="usuario_crear",
    ),
]
