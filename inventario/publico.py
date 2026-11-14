"""Publicación por internet (túnel de Cloudflare).

Cuando JANO se abre por una dirección pública (DJANGO_HOSTS_PUBLICOS), solo
responden la mesa de ayuda (/soporte/), el portal de los funcionarios
(/mi-soporte/), el ingreso y la creación de contraseña. El inventario, la
administración y la API dan 404 y solo se usan dentro del computador o la red.
Si JANO completo ya está publicado, no definas DJANGO_HOSTS_PUBLICOS.
"""
from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.http.request import split_domain_port, validate_host

RUTAS_PUBLICAS = ("/soporte/", "/mi-soporte/", "/cuenta/", "/login/", "/logout/")


def es_host_publico(request):
    """Indica si la petición llega por un dominio público (``HOSTS_PUBLICOS``)."""
    hosts = getattr(settings, "HOSTS_PUBLICOS", [])
    if not hosts:
        return False
    dominio, _ = split_domain_port(request.get_host())
    return bool(dominio) and validate_host(dominio, hosts)


def ip_cliente(request):
    """IP real del visitante: detrás del túnel llega en CF-Connecting-IP."""
    if es_host_publico(request):
        ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if ip:
            return ip[:45]
    return request.META.get("REMOTE_ADDR", "")


class SoloSoportePublicoMiddleware:
    """En el dominio público solo deja abrir el soporte y el portal.

    Cualquier otra ruta (inventario, administración…) responde 404.
    """
    def __init__(self, get_response):
        """Recibe el siguiente paso de la cadena de Django."""
        self.get_response = get_response

    def __call__(self, request):
        """Redirige la raíz al portal y bloquea las rutas no públicas."""
        if es_host_publico(request):
            ruta = request.path
            if ruta == "/":
                return HttpResponseRedirect("/mi-soporte/")
            permitidas = RUTAS_PUBLICAS + (settings.STATIC_URL,)
            if not ruta.startswith(permitidas):
                raise Http404("No disponible desde internet.")
        return self.get_response(request)


RUTAS_SOLICITANTE = ("/mi-soporte/", "/soporte/", "/cuenta/", "/logout/", "/login/")


class SoloPortalSolicitanteMiddleware:
    """Las cuentas de funcionarios (rol Solicitante) solo ven Mi soporte."""

    def __init__(self, get_response):
        """Recibe el siguiente paso de la cadena de Django."""
        self.get_response = get_response

    def __call__(self, request):
        """Si la cuenta es solo de solicitante, la lleva al portal fuera de sus rutas."""
        from .permisos import solo_solicitante

        if solo_solicitante(request.user):
            ruta = request.path
            if not ruta.startswith(RUTAS_SOLICITANTE + (settings.STATIC_URL,)):
                return HttpResponseRedirect("/mi-soporte/")
        return self.get_response(request)
