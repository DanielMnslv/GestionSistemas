"""Publicación por internet (túnel de Cloudflare).

Cuando JANO se abre por una dirección pública (DJANGO_HOSTS_PUBLICOS), solo
responde la mesa de ayuda (/soporte/) y sus archivos estáticos. El resto de
la plataforma (inventario, inicio de sesión, administración) da 404 y solo
se usa dentro del computador o de la red.
"""
from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.http.request import split_domain_port, validate_host

RUTAS_PUBLICAS = ("/soporte/",)


def es_host_publico(request):
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
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if es_host_publico(request):
            ruta = request.path
            if ruta == "/":
                return HttpResponseRedirect("/soporte/")
            permitidas = RUTAS_PUBLICAS + (settings.STATIC_URL,)
            if not ruta.startswith(permitidas):
                raise Http404("No disponible desde internet.")
        return self.get_response(request)
