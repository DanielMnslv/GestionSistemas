"""Datos del panel de inicio: equipos por tipo, mantenimientos, radios por cliente."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .ubicaciones import Localizador
from .models import (
    AsignacionRadio,
    Equipo,
    MantenimientoEquipo,
    MantenimientoProgramado,
    Puesto,
    Radio,
)

SEMANAS = 18
MAX_PUESTOS_POPUP = 12


def _dia(fecha):
    return timezone.localtime(fecha).date() if timezone.is_aware(fecha) else fecha.date()


def _pct(parte, total):
    return round(parte * 100 / total) if total else 0


def _estado(e):
    """ok, reg, mal o sin: el estado del radio si es radio; si no, el estado operativo."""
    radio = getattr(e, "radio", None)
    if radio is not None and radio.estado_radio:
        return {
            Radio.ESTADO_OPERATIVO: "ok", Radio.ESTADO_REGULAR: "reg",
            Radio.ESTADO_DANADO: "mal", Radio.ESTADO_BAJA: "mal",
        }.get(radio.estado_radio, "sin")
    return {
        Equipo.EstadoOperativo.OPERATIVO: "ok", Equipo.EstadoOperativo.NO_OPERATIVO: "mal",
    }.get(e.estado_operativo, "sin")


def _pcts(c, total):
    """Porcentajes enteros de ok/reg/mal que, con "sin", suman 100."""
    ok, reg, mal = (_pct(c[k], total) for k in ("ok", "reg", "mal"))
    return {"ok": ok, "reg": reg, "mal": mal, "sin": max(0, 100 - ok - reg - mal) if total else 0}


def _tipos(activos):
    etiquetas = dict(Equipo.Tipo.choices)
    por_tipo = defaultdict(lambda: {"ok": 0, "reg": 0, "mal": 0, "sin": 0})
    for e in activos.select_related("radio"):
        por_tipo[e.tipo][_estado(e)] += 1
    tipos = []
    for tipo, c in por_tipo.items():
        total = sum(c.values())
        w = _pcts(c, total)
        tipos.append({
            "tipo": tipo, "nombre": etiquetas.get(tipo, tipo), "total": total,
            "ok": c["ok"], "reg": c["reg"], "mal": c["mal"], "sin": c["sin"],
            "pct_ok": w["ok"], "w_ok": w["ok"], "w_reg": w["reg"], "w_mal": w["mal"], "w_sin": w["sin"],
        })
    return sorted(tipos, key=lambda t: -t["total"])


def _calor(tipos, hoy):
    """Mantenimientos por tipo de equipo en las últimas SEMANAS semanas."""
    desde = hoy - timedelta(days=hoy.weekday()) - timedelta(weeks=SEMANAS - 1)
    cuentas = defaultdict(lambda: [0] * SEMANAS)
    consulta = MantenimientoEquipo.objects.filter(
        fecha_intervencion__date__gte=desde, equipo__activo=True
    ).values_list("equipo__tipo", "fecha_intervencion")
    for tipo, fecha in consulta:
        i = (_dia(fecha) - desde).days // 7
        if 0 <= i < SEMANAS:
            cuentas[tipo][i] += 1
    return [{"nombre": t["nombre"], "semanas": cuentas[t["tipo"]]} for t in tipos]


def _mapa():
    """Radios con asignación vigente agrupados por lugar, para el mapa del panel.

    Cada puesto se ubica con el municipio que aparece en su nombre. Los puestos del mismo lugar quedan en un
    solo punto del mapa; los que no se pueden ubicar se cuentan aparte.
    """
    filas = (
        AsignacionRadio.objects.filter(estado=AsignacionRadio.Estado.ASIGNADO, radio__activo=True)
        .order_by("-fecha_entrega")
        .values_list(
            "radio_id", "radio__estado_radio", "cliente_asignado", "puesto_asignado",
        )
    )
    loc = Localizador(Puesto.objects.values_list("cliente__nombre", "sede", "nombre"))
    vistos, puestos = set(), {}
    for rid, estado, cliente, puesto in filas:
        if rid in vistos:
            continue
        vistos.add(rid)
        clave = (cliente or "Sin cliente", puesto or "")
        d = puestos.setdefault(clave, {"total": 0, "malos": 0})
        d["total"] += 1
        d["malos"] += estado == Radio.ESTADO_DANADO

    puntos, sin = {}, {"total": 0, "malos": 0, "puestos": 0}
    for (cliente, puesto), d in puestos.items():
        u = loc.de(cliente, puesto)
        if not u:
            sin["total"] += d["total"]
            sin["malos"] += d["malos"]
            sin["puestos"] += 1
            continue
        lugar, lat, lng, exacta = u
        pt = puntos.setdefault((round(lat, 4), round(lng, 4)), {
            "lat": lat, "lng": lng, "lugar": lugar, "exacta": exacta,
            "total": 0, "malos": 0, "puestos": [],
        })
        pt["total"] += d["total"]
        pt["malos"] += d["malos"]
        pt["exacta"] = pt["exacta"] and exacta
        pt["lugar"] = pt["lugar"] or lugar
        pt["puestos"].append({
            "nombre": f"{cliente}, {puesto}" if puesto else cliente,
            "total": d["total"], "malos": d["malos"],
        })
    lista = sorted(puntos.values(), key=lambda x: -x["total"])
    for pt in lista:
        pt["puestos"].sort(key=lambda x: -x["total"])
        if len(pt["puestos"]) > MAX_PUESTOS_POPUP:
            resto = pt["puestos"][MAX_PUESTOS_POPUP:]
            pt["puestos"] = pt["puestos"][:MAX_PUESTOS_POPUP] + [{
                "nombre": f"Otros puestos ({len(resto)})",
                "total": sum(x["total"] for x in resto),
                "malos": sum(x["malos"] for x in resto),
            }]

    radios = Radio.objects.filter(activo=True)
    sin_asignar = radios.count() - len(vistos)
    malos_bodega = radios.filter(estado_radio=Radio.ESTADO_DANADO).count() - sum(
        d["malos"] for d in puestos.values()
    )
    return {
        "puntos": lista,
        "sin_ubicar": sin,
        "bodega": {"total": max(sin_asignar, 0), "malos": max(malos_bodega, 0)},
        "total": len(vistos),
    }


def _atencion(hoy):
    """Lo que necesita acción: mantenimientos vencidos, próximos y equipos por revisar."""
    pendientes = MantenimientoProgramado.objects.filter(
        estado=MantenimientoProgramado.Estado.PROGRAMADO, equipo__activo=True
    )
    proximos = []
    for m in pendientes.filter(fecha_programada__gte=hoy).select_related("equipo").order_by("fecha_programada")[:5]:
        proximos.append({
            "placa": m.equipo.placa,
            "tipo": m.get_tipo_display(),
            "fecha": m.fecha_programada.strftime("%d/%m/%Y"),
            "url": reverse("inventario:equipo_detalle", args=[m.equipo.placa]),
        })
    return {
        "vencidos": pendientes.filter(fecha_programada__lt=hoy).count(),
        "en_revision": Equipo.objects.filter(activo=True, requiere_revision=True).count(),
        "proximos": proximos,
    }


def datos_inicio():
    hoy = timezone.localdate()
    activos = Equipo.objects.filter(activo=True)
    tipos = _tipos(activos)
    total = sum(t["total"] for t in tipos)
    c = {k: sum(t[k] for t in tipos) for k in ("ok", "reg", "mal", "sin")}
    w = _pcts(c, total)
    mapa = _mapa()
    return {
        "total": total,
        "n_ok": c["ok"], "n_reg": c["reg"], "n_mal": c["mal"], "n_sin": c["sin"],
        "w_ok": w["ok"], "w_reg": w["reg"], "w_mal": w["mal"], "w_sin": w["sin"],
        "pct_ok": w["ok"],
        "tipos": tipos,
        "radios_danados": Radio.objects.filter(activo=True, estado_radio=Radio.ESTADO_DANADO).count(),
        "bodega": mapa["bodega"]["total"],
        "programados_mes": MantenimientoProgramado.objects.filter(
            estado=MantenimientoProgramado.Estado.PROGRAMADO,
            fecha_programada__year=hoy.year, fecha_programada__month=hoy.month,
        ).count(),
        **_atencion(hoy),
        "grafico": {"calor": _calor(tipos, hoy), "mapa": mapa},
    }
