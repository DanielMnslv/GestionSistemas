"""Datos del panel de inicio: equipos por tipo, mantenimientos, radios por cliente."""
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .ubicaciones import Localizador
from .models import (
    AsignacionEquipo,
    AsignacionRadio,
    DetalleComputador,
    Equipo,
    MantenimientoEquipo,
    MantenimientoProgramado,
    Puesto,
    Radio,
)

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


MESES_TENDENCIA = 12
DIAS_ANTIVIRUS = 30
NOMBRES_MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _mantenimiento_estados(activos):
    """Cuántos equipos activos hay en cada estado del semáforo de mantenimiento."""
    from .estado_mantenimiento import ESTADOS, equipos_con_estado

    conteo = {e: 0 for e, _ in ESTADOS}
    for e in equipos_con_estado(activos):
        conteo[e.estado_mantenimiento] += 1
    return conteo


def _tendencia(hoy):
    """Mantenimientos registrados por mes (últimos 12), preventivos y el resto."""
    inicio = date(hoy.year, hoy.month, 1)
    for _ in range(MESES_TENDENCIA - 1):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    meses = []
    m = inicio
    for _ in range(MESES_TENDENCIA):
        meses.append((m.year, m.month))
        m = (m + timedelta(days=32)).replace(day=1)
    indice = {ym: i for i, ym in enumerate(meses)}
    preventivos = [0] * MESES_TENDENCIA
    otros = [0] * MESES_TENDENCIA
    consulta = MantenimientoEquipo.objects.filter(
        fecha_intervencion__date__gte=inicio
    ).values_list("tipo", "fecha_intervencion")
    for tipo, fecha in consulta:
        d = _dia(fecha)
        i = indice.get((d.year, d.month))
        if i is None:
            continue
        if tipo == MantenimientoEquipo.Tipo.PREVENTIVO:
            preventivos[i] += 1
        else:
            otros[i] += 1
    return {
        "etiquetas": [f"{NOMBRES_MES[mes - 1]} {str(anio)[2:]}" for anio, mes in meses],
        "preventivos": preventivos,
        "otros": otros,
    }


def _entregados():
    """Equipos activos con una entrega vigente (radios a vigilantes y equipos a funcionarios)."""
    radios = AsignacionRadio.objects.filter(
        estado=AsignacionRadio.Estado.ASIGNADO, radio__activo=True
    ).values("radio_id").distinct().count()
    equipos = AsignacionEquipo.objects.filter(
        estado=AsignacionEquipo.Estado.ASIGNADO, equipo__activo=True
    ).values("equipo_id").distinct().count()
    return radios + equipos


def _antivirus(hoy):
    limite = hoy + timedelta(days=DIAS_ANTIVIRUS)
    base = DetalleComputador.objects.filter(
        equipo__activo=True, vencimiento_antivirus__isnull=False
    )
    return {
        "antivirus_vencidos": base.filter(vencimiento_antivirus__lt=hoy).count(),
        "antivirus_por_vencer": base.filter(
            vencimiento_antivirus__gte=hoy, vencimiento_antivirus__lte=limite
        ).count(),
    }


def _politica(hoy):
    from . import politica
    from .views_equipos import _equipos_con_estado_politica

    conteo = defaultdict(int)
    for e in _equipos_con_estado_politica(hoy):
        conteo[e.estado_politica] += 1
    return {
        "politica_pendientes": conteo[politica.SIN_VERIFICAR] + conteo[politica.VENCIDA],
        "politica_incumple": conteo[politica.INCUMPLE],
    }


def _actividad(limite=7):
    """Últimas intervenciones y entregas, de la más reciente a la más antigua."""
    items = []
    for m in MantenimientoEquipo.objects.select_related("equipo").order_by(
        "-fecha_intervencion", "-id"
    )[:limite]:
        items.append({
            "fecha": m.fecha_intervencion,
            "clase": "mant",
            "titulo": m.equipo.placa,
            "detalle": " · ".join(x for x in [m.get_tipo_display(), m.tecnico_responsable] if x),
            "url": reverse("inventario:equipo_detalle", args=[m.equipo.placa]),
        })
    for a in AsignacionRadio.objects.select_related("radio").order_by(
        "-fecha_entrega", "-id"
    )[:limite]:
        items.append({
            "fecha": a.fecha_entrega,
            "clase": "entrega",
            "titulo": a.radio.placa,
            "detalle": " · ".join(x for x in ["Entrega", a.cliente_asignado, a.puesto_asignado] if x),
            "url": reverse("inventario:equipo_detalle", args=[a.radio.placa]),
        })
    for a in AsignacionEquipo.objects.select_related("equipo").order_by(
        "-fecha_entrega", "-id"
    )[:limite]:
        items.append({
            "fecha": a.fecha_entrega,
            "clase": "entrega",
            "titulo": a.equipo.placa,
            "detalle": " · ".join(x for x in ["Entrega", a.nombre_recibe or a.area] if x),
            "url": reverse("inventario:equipo_detalle", args=[a.equipo.placa]),
        })
    items.sort(key=lambda x: x["fecha"], reverse=True)
    return items[:limite]


def datos_inicio():
    from .estado_mantenimiento import PROXIMO, SIN_MANTENIMIENTO, VENCIDO, VIGENTE

    hoy = timezone.localdate()
    activos = Equipo.objects.filter(activo=True)
    tipos = _tipos(activos)
    total = sum(t["total"] for t in tipos)
    c = {k: sum(t[k] for t in tipos) for k in ("ok", "reg", "mal", "sin")}
    w = _pcts(c, total)
    mapa = _mapa()
    mant = _mantenimiento_estados(activos)
    entregados = _entregados()
    return {
        "hoy": hoy,
        "mant_vencidos": mant[VENCIDO],
        "mant_sin": mant[SIN_MANTENIMIENTO],
        "mant_proximos": mant[PROXIMO],
        "mant_vigentes": mant[VIGENTE],
        "pct_al_dia": _pct(mant[VIGENTE] + mant[PROXIMO], total),
        "entregados": entregados,
        "en_bodega": max(total - entregados, 0),
        "actividad": _actividad(),
        **_antivirus(hoy),
        **_politica(hoy),
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
        "grafico": {
            "mapa": mapa,
            "tendencia": _tendencia(hoy),
            "tipos": [
                {"tipo": t["tipo"], "nombre": t["nombre"], "ok": t["ok"],
                 "reg": t["reg"], "mal": t["mal"], "sin": t["sin"]}
                for t in tipos
            ],
            "mantenimiento": [mant[VENCIDO], mant[SIN_MANTENIMIENTO], mant[PROXIMO], mant[VIGENTE]],
        },
    }
