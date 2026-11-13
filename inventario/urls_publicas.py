"""Mesa de ayuda pública: pedir soporte y consultar el caso."""
from django.urls import path

from . import views_publicas

urlpatterns = [
    path("", views_publicas.soporte_formulario, name="soporte"),
    path("caso/<uuid:token>/", views_publicas.soporte_caso, name="soporte_caso"),
]
