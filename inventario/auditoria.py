"""Auditoría: quién hizo qué en la plataforma, cuándo y desde dónde.

- AuditoriaMiddleware guarda el usuario, la IP y la página de cada petición.
- Las señales registran cada creación, cambio o eliminación de los datos del
  inventario (y de los accesos), con los campos que cambiaron: antes → después.
- También quedan los ingresos, salidas e intentos fallidos de ingreso.

Lo que hacen los procesos automáticos (importaciones, tareas programadas)
queda a nombre de "Proceso automático".
"""
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save

_contexto = ContextVar("jano_auditoria", default=None)

# Campos que no aportan a la auditoría (fechas automáticas, identificadores).
IGNORAR = {
    "id", "public_id", "creado_en", "actualizado_en", "registrado_en",
    "last_login", "date_joined",
}
# Campos cuyo valor no se guarda, solo que cambió.
# Las claves de licencia solo las ve quien tiene ese permiso: aquí no se copian.
OCULTOS = {
    "password", "token", "key", "licencia", "licencia_so", "licencia_office",
    "licencia_antivirus", "licencia_software",
}
MAX_TEXTO = 300
# Listas de casillas que se guardan como claves: se muestran con su texto.
CASILLAS = {"actividades", "actividades_preventivas", "componentes_intervenidos"}

# Modelos que no se auditan: la propia bitácora y colas internas.
EXCLUIDOS = {"registroauditoria"}


class AuditoriaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        token = _contexto.set({"request": request, "ip": ip[:45], "ruta": request.path[:255]})
        try:
            return self.get_response(request)
        finally:
            _contexto.reset(token)


def _actor():
    ctx = _contexto.get()
    if not ctx:
        return None, "Proceso automático", "", ""
    usuario = getattr(ctx["request"], "user", None)
    if usuario is not None and usuario.is_authenticated:
        nombre = usuario.get_full_name() or usuario.get_username()
        return usuario, nombre, ctx["ip"], ctx["ruta"]
    return None, "Visitante sin sesión", ctx["ip"], ctx["ruta"]


def _texto(valor):
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f")
    if isinstance(valor, (list, tuple)):
        return ", ".join(_texto(v) for v in valor)
    texto = str(valor)
    if texto.startswith("data:"):
        return "(archivo o firma)"
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO] + "…"


def _valores(instancia):
    """{campo: texto legible} de los campos que se auditan."""
    datos = {}
    for campo in instancia._meta.concrete_fields:
        if campo.name in IGNORAR:
            continue
        if campo.is_relation:
            pk = getattr(instancia, campo.attname)
            datos[campo.name] = ("fk", pk)
            continue
        valor = campo.value_from_object(instancia)
        if campo.name in CASILLAS and isinstance(valor, list):
            from .actividades_mantenimiento import textos
            valor = textos(valor)
        if campo.choices:
            valor = dict(campo.flatchoices).get(valor, valor)
        datos[campo.name] = _texto(valor)
    return datos


def _fk_texto(instancia, campo, pk):
    if pk is None:
        return ""
    modelo = instancia._meta.get_field(campo).related_model
    obj = modelo._default_manager.filter(pk=pk).first()
    return _texto(obj) if obj is not None else f"#{pk}"


def _etiqueta(instancia, campo):
    try:
        return str(instancia._meta.get_field(campo).verbose_name).capitalize()
    except Exception:
        return campo


def _referencia(instancia):
    """Placa del equipo (o nombre) para poder buscar el registro después."""
    for nombre in ("placa",):
        if hasattr(instancia, nombre) and getattr(instancia, nombre):
            return str(getattr(instancia, nombre))[:100]
    for rel in ("equipo", "radio"):
        obj = getattr(instancia, f"{rel}_id", None) and getattr(instancia, rel, None)
        if obj is not None:
            placa = getattr(obj, "placa", None) or getattr(getattr(obj, "equipo", None), "placa", None)
            if placa:
                return str(placa)[:100]
    for nombre in ("cedula", "username", "nombre_completo", "nombre"):
        if getattr(instancia, nombre, None):
            return str(getattr(instancia, nombre))[:100]
    return ""


def _se_audita(sender):
    meta = sender._meta
    if meta.model_name in EXCLUIDOS or meta.proxy:
        return False
    return meta.app_label in ("inventario", "usuarios") or (meta.app_label == "auth" and meta.model_name == "user")


def _guardar(accion, instancia, cambios, descripcion=""):
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    usuario, nombre, ip, ruta = _actor()
    try:
        texto_objeto = _texto(instancia)
    except Exception:
        texto_objeto = f"#{instancia.pk}"
    Registro.objects.create(
        usuario=usuario, usuario_nombre=nombre[:150], accion=accion,
        modelo=str(instancia._meta.verbose_name).capitalize()[:100],
        modelo_clave=instancia._meta.label_lower[:100],
        objeto_id=str(instancia.pk)[:64], objeto_texto=texto_objeto[:255],
        referencia=_referencia(instancia), cambios=cambios,
        descripcion=descripcion[:255], ip=ip or None, ruta=ruta,
    )


def antes_de_guardar(sender, instance, raw=False, **kwargs):
    if raw or not _se_audita(sender) or instance.pk is None:
        return
    anterior = sender._default_manager.filter(pk=instance.pk).first()
    instance._auditoria_antes = _valores(anterior) if anterior is not None else None


def despues_de_guardar(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw or not _se_audita(sender):
        return
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    antes = getattr(instance, "_auditoria_antes", None)
    instance._auditoria_antes = None
    ahora = _valores(instance)
    cambios = []
    for campo, valor in ahora.items():
        previo = antes.get(campo) if antes else None
        if not created and antes is not None and previo == valor:
            continue
        if created and valor in ("", ("fk", None)):
            continue
        if isinstance(valor, tuple):
            nuevo = _fk_texto(instance, campo, valor[1])
            viejo = _fk_texto(instance, campo, previo[1]) if isinstance(previo, tuple) else ""
        else:
            nuevo, viejo = valor, (previo or "")
        if campo in OCULTOS:
            nuevo, viejo = "(cambió)", ""
        cambios.append({"campo": _etiqueta(instance, campo), "antes": "" if created else viejo, "despues": nuevo})
    if not created and not cambios:
        return
    _guardar(Registro.Accion.CREAR if created else Registro.Accion.EDITAR, instance, cambios)


def despues_de_eliminar(sender, instance, **kwargs):
    if not _se_audita(sender):
        return
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    datos = _valores(instance)
    cambios = [
        {"campo": _etiqueta(instance, c), "antes": v if not isinstance(v, tuple) else (f"#{v[1]}" if v[1] else ""), "despues": ""}
        for c, v in datos.items() if v not in ("", ("fk", None)) and c not in OCULTOS
    ]
    _guardar(Registro.Accion.ELIMINAR, instance, cambios)


def al_ingresar(sender, request, user, **kwargs):
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    _, _, ip, ruta = _actor()
    Registro.objects.create(
        usuario=user, usuario_nombre=(user.get_full_name() or user.get_username())[:150],
        accion=Registro.Accion.INGRESO, modelo="Sesión", modelo_clave="sesion",
        objeto_texto=user.get_username(), referencia=user.get_username()[:100],
        descripcion="Ingresó a la plataforma", ip=ip or None, ruta=ruta,
    )


def al_salir(sender, request, user, **kwargs):
    if user is None:
        return
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    _, _, ip, ruta = _actor()
    Registro.objects.create(
        usuario=user, usuario_nombre=(user.get_full_name() or user.get_username())[:150],
        accion=Registro.Accion.SALIDA, modelo="Sesión", modelo_clave="sesion",
        objeto_texto=user.get_username(), referencia=user.get_username()[:100],
        descripcion="Cerró sesión", ip=ip or None, ruta=ruta,
    )


def al_fallar_ingreso(sender, credentials, request=None, **kwargs):
    Registro = apps.get_model("inventario", "RegistroAuditoria")
    _, _, ip, ruta = _actor()
    nombre = str((credentials or {}).get("username", ""))[:100]
    Registro.objects.create(
        usuario=None, usuario_nombre=nombre or "Desconocido",
        accion=Registro.Accion.INGRESO_FALLIDO, modelo="Sesión", modelo_clave="sesion",
        objeto_texto=nombre, referencia=nombre,
        descripcion="Intento de ingreso fallido", ip=ip or None, ruta=ruta,
    )


def conectar():
    pre_save.connect(antes_de_guardar, dispatch_uid="jano_auditoria_pre_save")
    post_save.connect(despues_de_guardar, dispatch_uid="jano_auditoria_post_save")
    post_delete.connect(despues_de_eliminar, dispatch_uid="jano_auditoria_post_delete")
    user_logged_in.connect(al_ingresar, dispatch_uid="jano_auditoria_login")
    user_logged_out.connect(al_salir, dispatch_uid="jano_auditoria_logout")
    user_login_failed.connect(al_fallar_ingreso, dispatch_uid="jano_auditoria_login_fallido")
