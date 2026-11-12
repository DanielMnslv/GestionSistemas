from django.urls import path

from . import views

# Se incluye en inventario/urls.py bajo "informes/".
urlpatterns = [
    path("", views.inicio_informes, name="informes_inicio"),
    path("<slug:clave>/", views.vista_previa, name="informe_detalle"),
    path("<slug:clave>/excel/", views.exportar_informe_excel, name="informe_excel"),
    path("<slug:clave>/pdf/", views.exportar_informe_pdf, name="informe_pdf"),
]
