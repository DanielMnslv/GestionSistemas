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
# Funcionarios: solo el portal "Mi soporte" (agendar y pedir soporte).
SOLICITANTE = "Solicitante"

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
    "regularizacion_inventario": {ENCARGADO},
}


def roles_de(usuario):
    """Nombres de los roles (grupos) del usuario; se guardan en memoria por petición."""
    if not hasattr(usuario, "_roles_jano"):
        usuario._roles_jano = set(
            usuario.groups.values_list("name", flat=True)
        )
    return usuario._roles_jano


def puede(usuario, accion):
    """Indica si el usuario puede realizar ``accion`` (ver ``ACCIONES``).

    El superusuario puede todo; sin sesión no se puede nada.
    """
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


def solo_solicitante(usuario):
    """Funcionarios sin otro rol: solo ven el portal Mi soporte."""
    if usuario is None or not usuario.is_authenticated or usuario.is_superuser:
        return False
    roles = roles_de(usuario)
    return SOLICITANTE in roles and not roles & {ENCARGADO, TECNICO, CONSULTA, TALENTO}


def requiere_permiso(accion):
    """Decorador de vistas: exige que el usuario pueda realizar ``accion``.

    Si no puede, muestra "Tu rol no permite realizar esta acción" y lo
    lleva al inicio.
    """
    def decorador(vista):
        """Envuelve la vista con la verificación del permiso."""
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            """Verifica el permiso y, si lo tiene, ejecuta la vista."""
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
    # Funcionarios con rol Solicitante: solo el portal Mi soporte.
    datos["solo_portal"] = solo_solicitante(usuario)
    return {"permisos": datos}
