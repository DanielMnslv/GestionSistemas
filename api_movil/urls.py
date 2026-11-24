from django.urls import path
from .views import LoginMovilView, CatalogoMovilView, DashboardMovilView, SyncMovilView, HistorialEquipoMovilView, EvidenciaMovilView, EvidenciaMovilDetailView

urlpatterns = [
    path("login/", LoginMovilView.as_view(), name="api-movil-login"),
    path("catalogo/", CatalogoMovilView.as_view(), name="api-movil-catalogo"),
    path("dashboard/", DashboardMovilView.as_view(), name="api-movil-dashboard"),
    path("sync/", SyncMovilView.as_view(), name="api-movil-sync"),
    path("evidencias/", EvidenciaMovilView.as_view(), name="api-movil-evidencias"),
    path("evidencias/<uuid:evidencia_id>/", EvidenciaMovilDetailView.as_view(), name="api-movil-evidencia-detail"),
    path("equipos/<uuid:public_id>/historial/", HistorialEquipoMovilView.as_view(), name="api-movil-historial-equipo"),
]
