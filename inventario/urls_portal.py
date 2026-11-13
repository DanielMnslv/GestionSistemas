"""Portal Mi soporte (funcionarios con sesión)."""
from django.urls import path

from . import views_portal

app_name = "portal"

urlpatterns = [
    path("", views_portal.mi_soporte, name="inicio"),
    path("nueva/", views_portal.mi_soporte_nueva, name="nueva"),
    path("agendar/<int:equipo_id>/", views_portal.mi_soporte_agendar, name="agendar"),
]
