"""Informes de equipos de TI (computadores, impresoras, GPS, alarmas...)."""
from datetime import date

from ..models import DetalleAlarma, DetalleComputador, DetalleGPS, Equipo
from .ayudas import (
    OPCIONES_ACTIVO, aplicar_activo, contiene, opciones_con_todos, ordenar_por_placa,
)
from .base import Columna, Filtro, Informe

CATEGORIA = "Equipos de TI"
ETIQUETA_TIPO = dict(Equipo.Tipo.choices)
FILTRO_TIPO = Filtro("tipo", "Tipo de equipo", "select", opciones_con_todos(Equipo.Tipo.choices))
FILTRO_ESTADO = Filtro("estado", "Estado", "select", OPCIONES_ACTIVO, inicial="activos")


def _estado_equipo(equipo):
    return equipo.estado_texto or "Sin dato"


class InventarioEquipos(Informe):
    clave = "equipos_inventario"
    titulo = "Inventario general de equipos"
    categoria = CATEGORIA
    descripcion = "Todos los equipos con su tipo, estado, responsable y ubicación."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1),
        Columna("marca", "Marca", 1), Columna("modelo", "Modelo", 1.2),
        Columna("serial", "Serial", 1.4), Columna("propiedad", "Propiedad", 1),
        Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("responsable", "Responsable", 1.8), Columna("ubicacion", "Ubicación", 2),
        Columna("fecha_compra", "Fecha de compra", 1, "der"),
    )
    columnas_pdf = ("placa", "tipo", "marca", "modelo", "serial", "estado", "responsable", "ubicacion")
    filtros = (FILTRO_TIPO, FILTRO_ESTADO,
               Filtro("q", "Buscar", ayuda="Placa, serial, marca, modelo o responsable."))

    def obtener_filas(self, valores, usuario=None):
        consulta = Equipo.objects.select_related("radio")
        if valores["tipo"]:
            consulta = consulta.filter(tipo=valores["tipo"])
        consulta = aplicar_activo(consulta, valores["estado"])
        buscado = valores["q"]
        filas = []
        for e in consulta:
            if buscado and not any(contiene(v, buscado) for v in
                                   (e.placa, e.serial, e.marca, e.modelo, e.responsable_nombre)):
                continue
            filas.append({
                "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo),
                "marca": e.marca, "modelo": e.modelo, "serial": e.serial,
                "propiedad": e.propiedad,
                "estado": "Baja" if not e.activo else _estado_equipo(e),
                "responsable": e.responsable_nombre, "ubicacion": e.ubicacion,
                "fecha_compra": e.fecha_compra,
            })
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        estados = [f["estado"] for f in filas]
        return [
            ("Equipos", len(filas)),
            ("Operativos", estados.count("Operativo")),
            ("Regulares", estados.count("Regular")),
            ("Dañados / no operativos", estados.count("Dañado") + estados.count("No operativo")),
            ("Dados de baja", estados.count("Baja")),
        ]


class EquiposPorTipo(Informe):
    clave = "equipos_por_tipo"
    titulo = "Equipos por tipo y estado"
    categoria = CATEGORIA
    descripcion = "Cuántos equipos hay de cada tipo, cuántos operan y cuántos están de baja."
    columnas = (
        Columna("tipo", "Tipo de equipo", 2), Columna("total", "Total", 1, "der"),
        Columna("activos", "En servicio", 1, "der"), Columna("operativos", "Operativos", 1, "der"),
        Columna("no_operativos", "No operativos", 1, "der"), Columna("sin_estado", "Sin estado", 1, "der"),
        Columna("baja", "De baja", 1, "der"), Columna("revision", "Por revisar", 1, "der"),
    )
    orientacion = "horizontal"

    def obtener_filas(self, valores, usuario=None):
        por_tipo = {}
        for e in Equipo.objects.values("tipo", "activo", "estado_operativo", "requiere_revision"):
            f = por_tipo.setdefault(e["tipo"], dict.fromkeys(
                ("total", "activos", "operativos", "no_operativos", "sin_estado", "baja", "revision"), 0))
            f["total"] += 1
            if not e["activo"]:
                f["baja"] += 1
                continue
            f["activos"] += 1
            if e["estado_operativo"] == Equipo.EstadoOperativo.OPERATIVO:
                f["operativos"] += 1
            elif e["estado_operativo"] == Equipo.EstadoOperativo.NO_OPERATIVO:
                f["no_operativos"] += 1
            else:
                f["sin_estado"] += 1
            if e["requiere_revision"]:
                f["revision"] += 1
        filas = [{"tipo": etiqueta, **por_tipo[tipo]}
                 for tipo, etiqueta in Equipo.Tipo.choices if tipo in por_tipo]
        if filas:
            total = {"tipo": "TOTAL"}
            for clave in filas[0]:
                if clave != "tipo":
                    total[clave] = sum(f[clave] for f in filas)
            filas.append(total)
        return filas

    def resumen(self, filas):
        total = filas[-1] if filas else {}
        return [("Equipos registrados", total.get("total", 0)), ("En servicio", total.get("activos", 0)),
                ("De baja", total.get("baja", 0)), ("Por revisar", total.get("revision", 0))]


class EquiposBaja(Informe):
    clave = "equipos_baja"
    titulo = "Equipos dados de baja"
    categoria = CATEGORIA
    descripcion = "Equipos retirados del servicio, con la fecha y el motivo de la baja."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("marca", "Marca", 1),
        Columna("modelo", "Modelo", 1.2), Columna("serial", "Serial", 1.4),
        Columna("fecha_baja", "Fecha de baja", 1, "der"), Columna("motivo", "Motivo", 3),
    )
    filtros = (FILTRO_TIPO, Filtro("desde", "Baja desde", "date"), Filtro("hasta", "Baja hasta", "date"))

    def obtener_filas(self, valores, usuario=None):
        consulta = Equipo.objects.filter(activo=False)
        if valores["tipo"]:
            consulta = consulta.filter(tipo=valores["tipo"])
        if valores["desde"]:
            consulta = consulta.filter(fecha_baja__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha_baja__lte=valores["hasta"])
        filas = [{
            "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo), "marca": e.marca,
            "modelo": e.modelo, "serial": e.serial, "fecha_baja": e.fecha_baja, "motivo": e.motivo_baja,
        } for e in consulta]
        # Las bajas más recientes primero; las que no tienen fecha, al final.
        return sorted(filas, key=lambda f: f["fecha_baja"] or date.min, reverse=True)

    def resumen(self, filas):
        return [("Equipos dados de baja", len(filas))]


class EquiposPorRevisar(Informe):
    clave = "equipos_por_revisar"
    titulo = "Equipos marcados para revisión"
    categoria = CATEGORIA
    descripcion = "Equipos con datos dudosos o incompletos que alguien debe verificar."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("marca", "Marca", 1),
        Columna("serial", "Serial", 1.4), Columna("responsable", "Responsable", 1.8),
        Columna("ubicacion", "Ubicación", 2), Columna("motivo", "Motivo de la revisión", 3),
    )
    filtros = (FILTRO_TIPO,)

    def obtener_filas(self, valores, usuario=None):
        consulta = Equipo.objects.filter(activo=True, requiere_revision=True)
        if valores["tipo"]:
            consulta = consulta.filter(tipo=valores["tipo"])
        return ordenar_por_placa([{
            "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo), "marca": e.marca,
            "serial": e.serial, "responsable": e.responsable_nombre, "ubicacion": e.ubicacion,
            "motivo": e.motivo_revision,
        } for e in consulta])

    def resumen(self, filas):
        return [("Equipos por revisar", len(filas))]


class EquiposPorResponsable(Informe):
    clave = "equipos_por_responsable"
    titulo = "Equipos por responsable"
    categoria = CATEGORIA
    descripcion = "Qué equipos tiene a cargo cada persona (útil para actas y paz y salvos)."
    columnas = (
        Columna("responsable", "Responsable", 2), Columna("cedula", "Cédula", 1),
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1),
        Columna("equipo", "Marca y modelo", 2), Columna("serial", "Serial", 1.4),
        Columna("ubicacion", "Ubicación", 2),
    )
    filtros = (FILTRO_TIPO, Filtro("q", "Responsable o cédula", ayuda="Parte del nombre o de la cédula."))

    def obtener_filas(self, valores, usuario=None):
        consulta = Equipo.objects.filter(activo=True).exclude(responsable_nombre="")
        if valores["tipo"]:
            consulta = consulta.filter(tipo=valores["tipo"])
        filas = []
        for e in consulta:
            if valores["q"] and not (contiene(e.responsable_nombre, valores["q"])
                                     or contiene(e.responsable_cedula, valores["q"])):
                continue
            filas.append({
                "responsable": e.responsable_nombre, "cedula": e.responsable_cedula,
                "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo),
                "equipo": f"{e.marca} {e.modelo}".strip(), "serial": e.serial, "ubicacion": e.ubicacion,
            })
        filas.sort(key=lambda f: (f["responsable"].lower(), f["placa"]))
        return filas

    def resumen(self, filas):
        return [("Equipos asignados", len(filas)), ("Personas", len({f["responsable"] for f in filas}))]


class Computadores(Informe):
    clave = "computadores_hardware"
    titulo = "Computadores y tabletas: hardware y software"
    categoria = CATEGORIA
    descripcion = "Ficha técnica de cada computador: procesador, memoria, disco, sistema operativo, red y antivirus."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 0.9), Columna("clase", "Clase", 1),
        Columna("equipo", "Marca y modelo", 1.6), Columna("procesador", "Procesador", 1.6),
        Columna("ram", "RAM", 0.9), Columna("disco", "Disco", 1.1),
        Columna("so", "Sistema operativo", 1.4), Columna("office", "Office", 1.1),
        Columna("antivirus", "Antivirus", 1.1), Columna("ip", "IP", 1.1),
        Columna("responsable", "Responsable", 1.6), Columna("ubicacion", "Ubicación", 1.6),
    )
    columnas_pdf = ("placa", "clase", "equipo", "procesador", "ram", "disco", "so", "antivirus", "ip", "responsable")
    filtros = (
        Filtro("tipo", "Tipo", "select", opciones_con_todos((
            (Equipo.Tipo.COMPUTADOR, "Computador"), (Equipo.Tipo.TABLETA, "Tableta")))),
        FILTRO_ESTADO,
        Filtro("q", "Buscar", ayuda="Placa, responsable, procesador o sistema operativo."),
    )

    def obtener_filas(self, valores, usuario=None):
        consulta = DetalleComputador.objects.select_related("equipo")
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        consulta = aplicar_activo(consulta, valores["estado"], "equipo__activo")
        filas = []
        for d in consulta:
            e = d.equipo
            fila = {
                "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo), "clase": d.clase,
                "equipo": f"{e.marca} {e.modelo}".strip(),
                "procesador": " ".join(p for p in (d.procesador, d.velocidad_procesador) if p),
                "ram": " ".join(p for p in (d.capacidad_ram, d.tipo_ram) if p),
                "disco": " ".join(p for p in (d.capacidad_disco, d.tipo_disco) if p),
                "so": d.sistema_operativo, "office": d.office, "antivirus": d.antivirus,
                "ip": d.ip_ethernet or d.ip_wifi,
                "responsable": e.responsable_nombre, "ubicacion": e.ubicacion,
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("placa", "responsable", "procesador", "so")):
                continue
            filas.append(fila)
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        return [("Equipos", len(filas)),
                ("Sin sistema operativo registrado", sum(1 for f in filas if not f["so"])),
                ("Sin antivirus registrado", sum(1 for f in filas if not f["antivirus"]))]


class SoftwareInstalado(Informe):
    clave = "software_instalado"
    titulo = "Sistemas operativos, Office y antivirus en uso"
    categoria = CATEGORIA
    descripcion = "Cuántos computadores usan cada versión de sistema operativo, Office y antivirus."
    columnas = (Columna("categoria", "Software", 1.5), Columna("nombre", "Versión o producto", 3),
                Columna("cantidad", "Equipos", 1, "der"))
    orientacion = "vertical"
    filtros = (FILTRO_ESTADO,)

    def obtener_filas(self, valores, usuario=None):
        consulta = aplicar_activo(DetalleComputador.objects.all(), valores["estado"], "equipo__activo")
        conteos = {"Sistema operativo": {}, "Office": {}, "Antivirus": {}}
        for d in consulta:
            for categoria, valor in (("Sistema operativo", d.sistema_operativo),
                                     ("Office", d.office), ("Antivirus", d.antivirus)):
                nombre = (valor or "").strip() or "Sin registrar"
                conteos[categoria][nombre] = conteos[categoria].get(nombre, 0) + 1
        return [{"categoria": c, "nombre": n, "cantidad": q}
                for c, nombres in conteos.items()
                for n, q in sorted(nombres.items(), key=lambda x: (-x[1], x[0]))]

    def resumen(self, filas):
        return [("Combinaciones", len(filas))]


class GPS(Informe):
    clave = "gps_lineas"
    titulo = "GPS: líneas, vehículos y plataforma"
    categoria = CATEGORIA
    descripcion = "Dispositivos GPS con su IMEI, línea, operador, vehículo y estado en la plataforma."
    columnas = (
        Columna("placa", "Placa", 1), Columna("imei", "IMEI", 1.6), Columna("linea", "Línea", 1.2),
        Columna("operador", "Operador", 1), Columna("placa_vehiculo", "Placa vehículo", 1),
        Columna("vehiculo", "Vehículo", 1.8), Columna("plataforma", "Plataforma", 1.4, "centro", tono=True),
        Columna("asignado", "Asignado desde", 1.2, "der"), Columna("marca", "Marca y modelo", 1.6),
    )
    filtros = (FILTRO_ESTADO, Filtro("q", "Buscar", ayuda="IMEI, línea, placa del vehículo o nombre."))

    def obtener_filas(self, valores, usuario=None):
        consulta = aplicar_activo(DetalleGPS.objects.select_related("equipo"),
                                  valores["estado"], "equipo__activo")
        filas = []
        for g in consulta:
            fila = {
                "placa": g.equipo.placa, "imei": g.imei, "linea": g.linea, "operador": g.operador,
                "placa_vehiculo": g.placa_vehiculo, "vehiculo": g.nombre_vehiculo,
                "plataforma": g.plataforma, "asignado": g.fecha_asignacion,
                "marca": f"{g.equipo.marca} {g.equipo.modelo}".strip(),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("placa", "imei", "linea", "placa_vehiculo", "vehiculo")):
                continue
            filas.append(fila)
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        reporta = sum(1 for f in filas if (f["plataforma"] or "").lower().startswith("reporta"))
        return [("GPS", len(filas)), ("Reportan", reporta),
                ("Sin línea registrada", sum(1 for f in filas if not f["linea"]))]


class Alarmas(Informe):
    clave = "alarmas"
    titulo = "Alarmas y comunicadores"
    categoria = CATEGORIA
    descripcion = "Sistemas de alarma, si reportan a la central y el estado de su comunicador."
    columnas = (
        Columna("placa", "Placa", 1), Columna("clase", "Clase", 1.4),
        Columna("reporta", "Reporta a central", 1.2),
        Columna("serial_comunicador", "Serial del comunicador", 1.6),
        Columna("estado_comunicador", "Estado del comunicador", 1.4, "centro", tono=True),
        Columna("componentes", "Componentes", 0.9, "der"), Columna("ubicacion", "Ubicación", 2),
    )
    filtros = (FILTRO_ESTADO,)

    def obtener_filas(self, valores, usuario=None):
        consulta = aplicar_activo(DetalleAlarma.objects.select_related("equipo"),
                                  valores["estado"], "equipo__activo")
        return ordenar_por_placa([{
            "placa": a.equipo.placa, "clase": a.clase, "reporta": a.reporta_central,
            "serial_comunicador": a.serial_comunicador, "estado_comunicador": a.estado_comunicador,
            "componentes": len(a.componentes or []), "ubicacion": a.equipo.ubicacion,
        } for a in consulta])

    def resumen(self, filas):
        return [("Alarmas", len(filas))]


INFORMES = [InventarioEquipos(), EquiposPorTipo(), EquiposBaja(), EquiposPorRevisar(),
            EquiposPorResponsable(), Computadores(), SoftwareInstalado(), GPS(), Alarmas()]
