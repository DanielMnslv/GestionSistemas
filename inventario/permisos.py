"""Permisos por rol.

Los roles son grupos de Django creados al registrar usuarios
(usuarios/forms.py). Un superusuario puede hacer todo.
"""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

ENCARGADO = "Encargado de inventario"
TECNICO = "Técnico de mantenimiento"
CONSULTA = "Consulta"
TALENTO = "Talento humano"

# Acción -> roles que la pueden realizar.
ACCIONES = {
    "radios": {ENCARGADO},
    "equipos": {ENCARGADO},
    # Ver y editar claves de licencia (Windows, Office, antivirus).
    "licencias": {TECNICO},
    "entregas": {ENCARGADO},
    "mantenimientos": {TECNICO},
    "programar": {ENCARGADO, TECNICO},
    # Módulo de Usuarios: iniciar retiros y emitir el paz y salvo.
    "retiros": {ENCARGADO, TALENTO},
    # Validar el estado de cada equipo que devuelve la persona (TIC).
    "validar_retiro": {ENCARGADO},
    # Registrar y editar personas (funcionarios).
    "personas": {ENCARGADO, TALENTO},
    # Ver la auditoría (quién hizo qué y cuándo).
    "auditoria": {ENCARGADO},
    # Solicitudes de soporte: registrar, repartir y atender.
    "tickets_crear": {ENCARGADO, TECNICO},
    "tickets_asignar": {ENCARGADO},
    "tickets_atender": {TECNICO},
}


def roles_de(usuario):
    if not hasattr(usuario, "_roles_jano"):
        usuario._roles_jano = set(
            usuario.groups.values_list("name", flat=True)
        )
    return usuario._roles_jano


def puede(usuario, accion):
    if usuario is None or not usuario.is_authenticated:
        return False
    if usuario.is_superuser:
        return True
    return bool(roles_de(usuario) & ACCIONES[accion])


def solo_talento(usuario):
    """Usuarios de Talento humano sin otro rol: solo ven el módulo de Usuarios."""
    if usuario is None or not usuario.is_authenticated or usuario.is_superuser:
        return False
    roles = roles_de(usuario)
    return TALENTO in roles and not roles & {ENCARGADO, TECNICO, CONSULTA}


def requiere_permiso(accion):
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not puede(request.user, accion):
                messages.error(
                    request,
                    "Tu rol no permite realizar esta acción.",
                )
                return redirect("inicio")
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


def permisos(request):
    """Procesador de contexto: {{ permisos.radios }}, etc."""
    usuario = getattr(request, "user", None)
    if usuario is None:
        return {"permisos": {}}
    datos = {accion: puede(usuario, accion) for accion in ACCIONES}
    # Menú de Inventario y Mantenimiento: todos menos Talento humano.
    datos["tecnico"] = not solo_talento(usuario)
    return {"permisos": datos}
