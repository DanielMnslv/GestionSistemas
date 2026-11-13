"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # API de integración con Gestión TIC
    path(
        "api/v1/",
        include("api_integracion.urls"),
    ),

    # Módulos actuales de JANO
    # Mesa de ayuda pública (sin inicio de sesión)
    path("soporte/", include("inventario.urls_publicas")),
    # Portal de los funcionarios y creación de contraseña
    path("mi-soporte/", include("inventario.urls_portal")),
    path("cuenta/", include("usuarios.urls_cuenta")),

    path("inventario/", include("inventario.urls")),
    path("", include("usuarios.urls")),
]