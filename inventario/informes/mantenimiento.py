"""Informes de mantenimiento: semáforo, historial, programados y alertas."""
from ..estado_mantenimiento import (
    ESTADOS, PROXIMO, SIN_MANTENIMIENTO, VENCIDO, equipos_con_estado, fecha_local, hoy_colombia,
)
from ..models import AlertaMantenimiento, Equipo, MantenimientoEquipo, MantenimientoProgramado
from .ayudas import clave_placa, opciones_con_todos, ordenar_por_placa
from .base import Columna, Filtro, Informe

CATEGORIA = "Mantenimiento"
ETIQUETA_TIPO_EQUIPO = dict(Equipo.Tipo.choices)
ETIQUETA_ESTADO = dict(ESTADOS)
FILTRO_TIPO_EQUIPO = Filtro("tipo", "Tipo de equipo", "select", opciones_con_todos(Equipo.Tipo.choices))
FILTRO_TIPO_MANT = Filtro("tipo_mant", "Tipo de mantenimiento", "select",
                          opciones_con_todos(MantenimientoEquipo.Tipo.choices))


def _rango(consulta, valores, campo):
    """Filtra la consulta entre las fechas ``desde`` y ``hasta`` de los filtros."""
    if valores.get("desde"):
        consulta = consulta.filter(**{f"{campo}__gte": valores["desde"]})
    if valores.get("hasta"):
        consulta = consulta.filter(**{f"{campo}__lte": valores["hasta"]})
    return consulta


class _SemaforoBase(Informe):
    """Base común de los informes del semáforo de mantenimiento."""
    categoria = CATEGORIA
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("marca", "Marca y modelo", 1.8),
        Columna("responsable", "Responsable", 1.8), Columna("ubicacion", "Ubicación", 2),
        Columna("ultimo", "Último mantenimiento", 1.2, "der"), Columna("proximo", "Vence", 1, "der"),
        Columna("estado", "Estado", 1.3, "centro", tono=True), Columna("plazo", "Plazo", 1.8),
    )
    columnas_pdf = ("placa", "tipo", "marca", "responsable", "ultimo", "proximo", "estado", "plazo")
    estados_incluidos = None

    def obtener_filas(self, valores, usuario=None):
        """Filas de del informe según los filtros elegidos (``valores``)."""
        consulta = Equipo.objects.filter(activo=True).select_related("radio")
        if valores.get("tipo"):
            consulta = consulta.filter(tipo=valores["tipo"])
        filas = []
        for e in equipos_con_estado(consulta, hoy_colombia()):
            estado = e.estado_mantenimiento
            if self.estados_incluidos and estado not in self.estados_incluidos:
                continue
            if valores.get("estado") and estado != valores["estado"]:
                continue
            filas.append({
                "placa": e.placa, "tipo": ETIQUETA_TIPO_EQUIPO.get(e.tipo, e.tipo),
                "marca": f"{e.marca} {e.modelo}".strip(), "responsable": e.responsable_nombre,
                "ubicacion": e.ubicacion, "ultimo": e.ultimo_fecha, "proximo": e.proximo_mantenimiento,
                "estado": ETIQUETA_ESTADO[estado],
                "plazo": e.plazo_texto or "Sin mantenimiento registrado",
                "_orden": estado, "_dias": e.dias_para_vencer,
            })
        orden = {codigo: i for i, (codigo, _) in enumerate(ESTADOS)}
        filas.sort(key=lambda f: (orden[f["_orden"]], f["_dias"] if f["_dias"] is not None else 0,
                                  clave_placa(f["placa"])))
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Equipos."""
        etiquetas = [e for _, e in ESTADOS]
        conteo = {e: 0 for e in etiquetas}
        for f in filas:
            conteo[f["estado"]] += 1
        return [("Equipos", len(filas))] + [(e, conteo[e]) for e in etiquetas if conteo[e]]


class SemaforoMantenimiento(_SemaforoBase):
    """Informe «Estado del mantenimiento preventivo».

    Cada equipo activo con su último mantenimiento y cuándo vence el siguiente (cada 6 meses).
    """
    clave = "mantenimiento_semaforo"
    titulo = "Estado del mantenimiento preventivo"
    descripcion = "Cada equipo activo con su último mantenimiento y cuándo vence el siguiente (cada 6 meses)."
    filtros = (FILTRO_TIPO_EQUIPO, Filtro("estado", "Estado", "select", opciones_con_todos(ESTADOS)))


class MantenimientosVencidos(_SemaforoBase):
    """Informe «Equipos con mantenimiento vencido o sin mantenimiento».

    Lista de trabajo: los equipos que ya deberían haber tenido mantenimiento, del más atrasado al menos atrasado.
    """
    clave = "mantenimiento_vencidos"
    titulo = "Equipos con mantenimiento vencido o sin mantenimiento"
    descripcion = "Lista de trabajo: los equipos que ya deberían haber tenido mantenimiento, del más atrasado al menos atrasado."
    estados_incluidos = {VENCIDO, SIN_MANTENIMIENTO}
    filtros = (FILTRO_TIPO_EQUIPO,)


class MantenimientosProximos(_SemaforoBase):
    """Informe «Mantenimientos por vencer (próximos 30 días)».

    Equipos cuyo mantenimiento vence pronto, para programar las visitas.
    """
    clave = "mantenimiento_proximos"
    titulo = "Mantenimientos por vencer (próximos 30 días)"
    descripcion = "Equipos cuyo mantenimiento vence pronto, para programar las visitas."
    estados_incluidos = {PROXIMO}
    filtros = (FILTRO_TIPO_EQUIPO,)


def _clasificar(g, tipo):
    """Suma el mantenimiento al contador de su clase (preventivo, correctivo u otro)."""
    if tipo == MantenimientoEquipo.Tipo.PREVENTIVO:
        g["preventivos"] += 1
    elif tipo in (MantenimientoEquipo.Tipo.CORRECTIVO, MantenimientoEquipo.Tipo.REPARACION):
        g["correctivos"] += 1
    else:
        g["otros"] += 1


class MantenimientosRealizados(Informe):
    """Informe «Mantenimientos realizados».

    Historial de intervenciones por rango de fechas, tipo, técnico y resultado.
    """
    clave = "mantenimientos_realizados"
    titulo = "Mantenimientos realizados"
    categoria = CATEGORIA
    descripcion = "Historial de intervenciones por rango de fechas, tipo, técnico y resultado."
    columnas = (
        Columna("fecha", "Fecha", 1.2), Columna("placa", "Placa", 1), Columna("tipo_equipo", "Equipo", 1),
        Columna("tipo", "Tipo de mantenimiento", 1.4), Columna("tecnico", "Técnico", 1.4),
        Columna("motivo", "Motivo", 2), Columna("trabajo", "Trabajo realizado", 3),
        Columna("repuestos", "Repuestos", 1.4), Columna("resultado", "Resultado", 1.1, "centro", tono=True),
        Columna("estado_final", "Estado final", 1.2, "centro", tono=True),
    )
    columnas_pdf = ("fecha", "placa", "tipo", "tecnico", "motivo", "trabajo", "resultado", "estado_final")
    filtros = (
        Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"),
        FILTRO_TIPO_MANT, FILTRO_TIPO_EQUIPO,
        Filtro("resultado", "Resultado", "select", opciones_con_todos(MantenimientoEquipo.Resultado.choices)),
        Filtro("tecnico", "Técnico", ayuda="Parte del nombre."),
        Filtro("placa", "Placa", ayuda="Parte de la placa."),
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Mantenimientos realizados» según los filtros elegidos (``valores``)."""
        consulta = MantenimientoEquipo.objects.select_related("equipo")
        consulta = _rango(consulta, valores, "fecha_intervencion__date")
        if valores["tipo_mant"]:
            consulta = consulta.filter(tipo=valores["tipo_mant"])
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        if valores["resultado"]:
            consulta = consulta.filter(resultado=valores["resultado"])
        if valores["tecnico"]:
            consulta = consulta.filter(tecnico_responsable__icontains=valores["tecnico"])
        if valores["placa"]:
            consulta = consulta.filter(equipo__placa__icontains=valores["placa"])
        return [{
            "fecha": m.fecha_intervencion, "placa": m.equipo.placa,
            "tipo_equipo": ETIQUETA_TIPO_EQUIPO.get(m.equipo.tipo, m.equipo.tipo),
            "tipo": m.get_tipo_display(), "tecnico": m.tecnico_responsable, "motivo": m.motivo,
            "trabajo": m.trabajo_realizado, "repuestos": m.repuestos_utilizados,
            "resultado": m.get_resultado_display(), "estado_final": m.get_estado_final_display(),
        } for m in consulta.order_by("-fecha_intervencion", "-id")]

    def resumen(self, filas):
        """Totales del encabezado: Intervenciones, Preventivos, Correctivos, Equipos atendidos."""
        return [("Intervenciones", len(filas)),
                ("Preventivos", sum(1 for f in filas if "preventivo" in f["tipo"].lower())),
                ("Correctivos", sum(1 for f in filas if "correctivo" in f["tipo"].lower())),
                ("Equipos atendidos", len({f["placa"] for f in filas}))]


class MantenimientosPorTecnico(Informe):
    """Informe «Mantenimientos por técnico».

    Cuántas intervenciones hizo cada técnico y con qué resultado.
    """
    clave = "mantenimientos_por_tecnico"
    titulo = "Mantenimientos por técnico"
    categoria = CATEGORIA
    descripcion = "Cuántas intervenciones hizo cada técnico y con qué resultado."
    columnas = (
        Columna("tecnico", "Técnico", 3), Columna("total", "Intervenciones", 1, "der"),
        Columna("preventivos", "Preventivos", 1, "der"), Columna("correctivos", "Correctivos", 1, "der"),
        Columna("otros", "Otros", 1, "der"), Columna("solucionados", "Solucionados", 1, "der"),
        Columna("pendientes", "Parcial o pendiente", 1, "der"),
        Columna("equipos", "Equipos distintos", 1, "der"), Columna("ultima", "Última", 1, "der"),
    )
    filtros = (Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Mantenimientos por técnico» según los filtros elegidos (``valores``)."""
        consulta = _rango(MantenimientoEquipo.objects.all(), valores, "fecha_intervencion__date")
        grupos = {}
        for m in consulta.values("tecnico_responsable", "tipo", "resultado", "equipo_id", "fecha_intervencion"):
            nombre = " ".join(m["tecnico_responsable"].split()) or "Sin técnico"
            g = grupos.setdefault(nombre.lower(), {
                "tecnico": nombre, "total": 0, "preventivos": 0, "correctivos": 0, "otros": 0,
                "solucionados": 0, "pendientes": 0, "_equipos": set(), "ultima": None})
            g["total"] += 1
            _clasificar(g, m["tipo"])
            if m["resultado"] == MantenimientoEquipo.Resultado.SOLUCIONADO:
                g["solucionados"] += 1
            else:
                g["pendientes"] += 1
            g["_equipos"].add(m["equipo_id"])
            fecha = fecha_local(m["fecha_intervencion"])
            if g["ultima"] is None or fecha > g["ultima"]:
                g["ultima"] = fecha
        filas = []
        for g in grupos.values():
            g["equipos"] = len(g.pop("_equipos"))
            filas.append(g)
        filas.sort(key=lambda f: (-f["total"], f["tecnico"].lower()))
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Técnicos, Intervenciones."""
        return [("Técnicos", len(filas)), ("Intervenciones", sum(f["total"] for f in filas))]


class MantenimientosPorMes(Informe):
    """Informe «Mantenimientos por mes».

    Cuántas intervenciones se hicieron cada mes, para ver la carga de trabajo.
    """
    clave = "mantenimientos_por_mes"
    titulo = "Mantenimientos por mes"
    categoria = CATEGORIA
    descripcion = "Cuántas intervenciones se hicieron cada mes, para ver la carga de trabajo."
    columnas = (
        Columna("mes", "Mes", 1.4), Columna("total", "Intervenciones", 1, "der"),
        Columna("preventivos", "Preventivos", 1, "der"), Columna("correctivos", "Correctivos", 1, "der"),
        Columna("otros", "Otros", 1, "der"), Columna("equipos", "Equipos atendidos", 1, "der"),
    )
    orientacion = "vertical"
    filtros = (Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"))
    MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre")

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Mantenimientos por mes» según los filtros elegidos (``valores``)."""
        consulta = _rango(MantenimientoEquipo.objects.all(), valores, "fecha_intervencion__date")
        grupos = {}
        for m in consulta.values("tipo", "equipo_id", "fecha_intervencion"):
            f = fecha_local(m["fecha_intervencion"])
            g = grupos.setdefault((f.year, f.month), {
                "total": 0, "preventivos": 0, "correctivos": 0, "otros": 0, "_equipos": set()})
            g["total"] += 1
            _clasificar(g, m["tipo"])
            g["_equipos"].add(m["equipo_id"])
        filas = []
        for (anio, mes), g in sorted(grupos.items(), reverse=True):
            g["equipos"] = len(g.pop("_equipos"))
            filas.append({"mes": f"{self.MESES[mes - 1].capitalize()} {anio}", **g})
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Meses con actividad, Intervenciones."""
        return [("Meses con actividad", len(filas)), ("Intervenciones", sum(f["total"] for f in filas))]


class TrabajoPendiente(Informe):
    """Informe «Equipos con trabajo pendiente tras el último mantenimiento».

    Equipos cuyo último mantenimiento quedó parcial, pendiente, no operativo o en pruebas.
    """
    clave = "mantenimiento_trabajo_pendiente"
    titulo = "Equipos con trabajo pendiente tras el último mantenimiento"
    categoria = CATEGORIA
    descripcion = "Equipos cuyo último mantenimiento quedó parcial, pendiente, no operativo o en pruebas."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("fecha", "Último mantenimiento", 1.3),
        Columna("tecnico", "Técnico", 1.4), Columna("resultado", "Resultado", 1.1, "centro", tono=True),
        Columna("estado_final", "Estado final", 1.3, "centro", tono=True),
        Columna("diagnostico", "Diagnóstico", 2.5), Columna("observaciones", "Observaciones", 2.5),
    )
    filtros = (FILTRO_TIPO_EQUIPO,)

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Equipos con trabajo pendiente tras el último mantenimiento» según los filtros elegidos (``valores``)."""
        consulta = MantenimientoEquipo.objects.filter(equipo__activo=True).select_related("equipo")
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        ultimos = {}
        for m in consulta.order_by("equipo_id", "-fecha_intervencion", "-id"):
            ultimos.setdefault(m.equipo_id, m)
        resuelto = MantenimientoEquipo.Resultado.SOLUCIONADO
        bueno = MantenimientoEquipo.EstadoFinal.OPERATIVO
        filas = []
        for m in ultimos.values():
            if m.resultado == resuelto and m.estado_final == bueno:
                continue
            filas.append({
                "placa": m.equipo.placa, "tipo": ETIQUETA_TIPO_EQUIPO.get(m.equipo.tipo, m.equipo.tipo),
                "fecha": m.fecha_intervencion, "tecnico": m.tecnico_responsable,
                "resultado": m.get_resultado_display(), "estado_final": m.get_estado_final_display(),
                "diagnostico": m.diagnostico, "observaciones": m.observaciones,
            })
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        """Totales del encabezado: Equipos con trabajo pendiente."""
        return [("Equipos con trabajo pendiente", len(filas))]


class MantenimientosProgramados(Informe):
    """Informe «Mantenimientos programados».

    Visitas programadas, cuáles se cumplieron y cuáles están atrasadas.
    """
    clave = "mantenimientos_programados"
    titulo = "Mantenimientos programados"
    categoria = CATEGORIA
    descripcion = "Visitas programadas, cuáles se cumplieron y cuáles están atrasadas."
    columnas = (
        Columna("fecha", "Fecha programada", 1.2, "der"), Columna("placa", "Placa", 1),
        Columna("tipo_equipo", "Equipo", 1), Columna("tipo", "Tipo", 1.4),
        Columna("descripcion", "Descripción", 3), Columna("estado", "Estado", 1.2, "centro", tono=True),
        Columna("creado_por", "Programado por", 1.4),
    )
    filtros = (
        Filtro("estado", "Estado", "select", opciones_con_todos(
            tuple(MantenimientoProgramado.Estado.choices) + (("ATRASADO", "Atrasado"),)),
            inicial="PROGRAMADO"),
        Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"), FILTRO_TIPO_EQUIPO,
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Mantenimientos programados» según los filtros elegidos (``valores``)."""
        hoy = hoy_colombia()
        consulta = MantenimientoProgramado.objects.select_related("equipo", "creado_por")
        estado = valores["estado"]
        if estado == "ATRASADO":
            consulta = consulta.filter(estado=MantenimientoProgramado.Estado.PROGRAMADO,
                                       fecha_programada__lt=hoy)
        elif estado:
            consulta = consulta.filter(estado=estado)
        consulta = _rango(consulta, valores, "fecha_programada")
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        filas = []
        for p in consulta:
            atrasado = (p.estado == MantenimientoProgramado.Estado.PROGRAMADO and p.fecha_programada < hoy)
            creador = ""
            if p.creado_por:
                creador = p.creado_por.get_full_name() or p.creado_por.get_username()
            filas.append({
                "fecha": p.fecha_programada, "placa": p.equipo.placa,
                "tipo_equipo": ETIQUETA_TIPO_EQUIPO.get(p.equipo.tipo, p.equipo.tipo),
                "tipo": p.get_tipo_display(), "descripcion": p.descripcion,
                "estado": "Atrasado" if atrasado else p.get_estado_display(), "creado_por": creador,
            })
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Programados, Atrasados, Completados, Cancelados."""
        estados = [f["estado"] for f in filas]
        return [("Programados", len(filas)), ("Atrasados", estados.count("Atrasado")),
                ("Completados", estados.count("Completado")), ("Cancelados", estados.count("Cancelado"))]


class AlertasMantenimientoInforme(Informe):
    """Informe «Alertas de mantenimiento enviadas».

    Avisos de vencimiento generados por el sistema: enviados, pendientes y con error.
    """
    clave = "alertas_mantenimiento"
    titulo = "Alertas de mantenimiento enviadas"
    categoria = CATEGORIA
    descripcion = "Avisos de vencimiento generados por el sistema: enviados, pendientes y con error."
    columnas = (
        Columna("vencimiento", "Vencimiento", 1.2, "der"), Columna("placa", "Placa", 1),
        Columna("tipo", "Equipo", 1), Columna("estado", "Estado de la alerta", 1.3, "centro", tono=True),
        Columna("intentos", "Intentos", 0.8, "der"), Columna("enviada", "Enviada", 1.4, "der"),
        Columna("error", "Detalle del error", 3),
    )
    filtros = (
        Filtro("estado", "Estado", "select", opciones_con_todos(AlertaMantenimiento.Estado.choices)),
        Filtro("desde", "Vence desde", "date"), Filtro("hasta", "Vence hasta", "date"),
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Alertas de mantenimiento enviadas» según los filtros elegidos (``valores``)."""
        consulta = AlertaMantenimiento.objects.select_related("equipo")
        if valores["estado"]:
            consulta = consulta.filter(estado=valores["estado"])
        consulta = _rango(consulta, valores, "fecha_vencimiento")
        return [{
            "vencimiento": a.fecha_vencimiento, "placa": a.equipo.placa,
            "tipo": ETIQUETA_TIPO_EQUIPO.get(a.equipo.tipo, a.equipo.tipo),
            "estado": a.get_estado_display(), "intentos": a.intentos,
            "enviada": a.enviada_en, "error": a.detalle_error,
        } for a in consulta.order_by("-fecha_vencimiento", "equipo__placa")]

    def resumen(self, filas):
        """Totales del encabezado: Alertas, Enviadas, Pendientes, Con error."""
        estados = [f["estado"] for f in filas]
        return [("Alertas", len(filas)), ("Enviadas", estados.count("Enviada")),
                ("Pendientes", estados.count("Pendiente")), ("Con error", estados.count("Error"))]


INFORMES = [
    SemaforoMantenimiento(), MantenimientosVencidos(), MantenimientosProximos(),
    MantenimientosRealizados(), MantenimientosPorTecnico(), MantenimientosPorMes(),
    TrabajoPendiente(), MantenimientosProgramados(), AlertasMantenimientoInforme(),
]
