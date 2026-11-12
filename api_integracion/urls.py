from django.urls import path
from .views import EquiposAPI, RadiosAPI, recibir_evento_gestion_tic

app_name = "api_integracion"
urlpatterns = [
    path("equipos/", EquiposAPI.as_view(), name="equipos"),
    path("radios/", RadiosAPI.as_view(), name="radios"),
    path("eventos/gestion-tic/", recibir_evento_gestion_tic, name="recibir_evento_gestion_tic"),
]
