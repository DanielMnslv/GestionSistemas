"""Pantalla de auditoría: qué se hizo en la plataforma, quién y cuándo."""
from datetime import datetime, time

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from .models import RegistroAuditoria
from .permisos import requiere_permiso
from .views import paginar


def _fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@login_required
@requiere_permiso("auditoria")
def auditoria_lista(request):
    registros = RegistroAuditoria.objects.select_related("usuario")
    q = request.GET.get("q", "").strip()
    accion = request.GET.get("accion", "")
    modelo = request.GET.get("modelo", "")
    usuario = request.GET.get("usuario", "")
    desde = _fecha(request.GET.get("desde"))
    hasta = _fecha(request.GET.get("hasta"))

    if q:
        registros = registros.filter(
            Q(referencia__icontains=q) | Q(objeto_texto__icontains=q)
            | Q(usuario_nombre__icontains=q) | Q(descripcion__icontains=q)
        )
    if accion in RegistroAuditoria.Accion.values:
        registros = registros.filter(accion=accion)
    else:
        accion = ""
    if modelo:
        registros = registros.filter(modelo_clave=modelo)
    if usuario:
        registros = registros.filter(usuario_nombre=usuario)
    zona = timezone.get_current_timezone()
    if desde:
        registros = registros.filter(fecha__gte=timezone.make_aware(datetime.combine(desde, time.min), zona))
    if hasta:
        registros = registros.filter(fecha__lte=timezone.make_aware(datetime.combine(hasta, time.max), zona))

    page_obj, parametros = paginar(request, registros, 50)
    todos = RegistroAuditoria.objects
    return render(request, "inventario/auditoria.html", {
        "registros": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "total": page_obj.paginator.count,
        "q": q, "accion": accion, "modelo": modelo, "usuario": usuario,
        "desde": desde.isoformat() if desde else "",
        "hasta": hasta.isoformat() if hasta else "",
        "acciones": RegistroAuditoria.Accion.choices,
        "modelos": todos.order_by("modelo").values_list("modelo_clave", "modelo").distinct(),
        "usuarios": todos.order_by("usuario_nombre").values_list("usuario_nombre", flat=True).distinct(),
        "hay_filtros": any([q, accion, modelo, usuario, desde, hasta]),
    })
