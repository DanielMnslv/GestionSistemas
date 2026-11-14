"""Informes de radios de comunicación."""
from ..estados import tono_estado
from ..models import Radio
from .ayudas import OPCIONES_ACTIVO, aplicar_activo, contiene, opciones_con_todos, ordenar_por_placa
from .base import Columna, Filtro, Informe

CATEGORIA = "Radios"
FILTRO_ESTADO_RADIO = Filtro("estado_radio", "Estado del radio", "select", opciones_con_todos(Radio.ESTADOS))
FILTRO_ACTIVO = Filtro("activo", "Servicio", "select", OPCIONES_ACTIVO, inicial="activos")
SIN_ASIGNAR = "Sin asignar"

COMPONENTES = (
    ("estado_base", "Base"), ("estado_cargador", "Cargador"), ("estado_antena", "Antena"),
    ("estado_baterias", "Baterías"), ("estado_perilla_encendido", "Perilla de encendido"),
    ("estado_perilla_frecuencia", "Perilla de frecuencia"), ("estado_clip", "Clip"),
)


def _fila_radio(r):
    """Fila del informe con los datos básicos de un radio."""
    return {
        "placa": r.placa or "—", "codigo": r.codigo_fisico, "serial": r.serial,
        "marca": r.marca, "modelo": r.modelo, "frecuencia": r.tipo_frecuencia,
        "estado": "Baja" if not r.activo else (r.estado_radio or "Sin dato"),
        "cliente": r.cliente_asignado, "puesto": r.puesto_asignado,
        "coordinador": r.coordinador_zona, "observaciones": r.observaciones,
    }


class InventarioRadios(Informe):
    """Informe «Inventario de radios».

    Todos los radios con su estado y el cliente y puesto donde están.
    """
    clave = "radios_inventario"
    titulo = "Inventario de radios"
    categoria = CATEGORIA
    descripcion = "Todos los radios con su estado y el cliente y puesto donde están."
    columnas = (
        Columna("placa", "Placa (RJ)", 1), Columna("codigo", "Código físico", 1),
        Columna("serial", "Serial", 1.4), Columna("marca", "Marca", 1), Columna("modelo", "Modelo", 1.1),
        Columna("frecuencia", "Frecuencia", 1), Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("cliente", "Cliente", 2), Columna("puesto", "Puesto", 2),
        Columna("coordinador", "Coordinador de zona", 1.6),
    )
    columnas_pdf = ("placa", "serial", "marca", "modelo", "estado", "cliente", "puesto", "coordinador")
    filtros = (
        FILTRO_ESTADO_RADIO, FILTRO_ACTIVO,
        Filtro("cliente", "Cliente", ayuda="Parte del nombre del cliente."),
        Filtro("q", "Buscar", ayuda="Placa, serial, código, marca, modelo, puesto o coordinador."),
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Inventario de radios» según los filtros elegidos (``valores``)."""
        consulta = aplicar_activo(Radio.objects.all(), valores["activo"])
        if valores["estado_radio"]:
            consulta = consulta.filter(estado_radio=valores["estado_radio"])
        if valores["cliente"]:
            consulta = consulta.filter(cliente_asignado__icontains=valores["cliente"])
        filas = []
        for r in consulta:
            fila = _fila_radio(r)
            if valores["q"] and not any(contiene(fila[k], valores["q"]) for k in
                                        ("placa", "serial", "codigo", "marca", "modelo", "puesto", "coordinador")):
                continue
            filas.append(fila)
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        """Totales del encabezado: Radios, Operativos, Regulares, Dañados, De baja."""
        estados = [f["estado"] for f in filas]
        return [("Radios", len(filas)), ("Operativos", estados.count("Operativo")),
                ("Regulares", estados.count("Regular")), ("Dañados", estados.count("Dañado")),
                ("De baja", estados.count("Baja"))]


class RadiosPorCliente(Informe):
    """Informe «Radios por cliente».

    Cuántos radios tiene cada cliente y en qué estado están.
    """
    clave = "radios_por_cliente"
    titulo = "Radios por cliente"
    categoria = CATEGORIA
    descripcion = "Cuántos radios tiene cada cliente y en qué estado están."
    columnas = (
        Columna("cliente", "Cliente", 3), Columna("total", "Radios", 1, "der"),
        Columna("operativos", "Operativos", 1, "der"), Columna("regulares", "Regulares", 1, "der"),
        Columna("danados", "Dañados", 1, "der"), Columna("sin_estado", "Sin estado", 1, "der"),
        Columna("puestos", "Puestos", 1, "der"),
    )
    orientacion = "horizontal"

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios por cliente» según los filtros elegidos (``valores``)."""
        grupos = {}
        for r in Radio.objects.filter(activo=True):
            cliente = r.cliente_asignado.strip() or SIN_ASIGNAR
            g = grupos.setdefault(cliente, {
                "cliente": cliente, "total": 0, "operativos": 0, "regulares": 0,
                "danados": 0, "sin_estado": 0, "_puestos": set()})
            g["total"] += 1
            clave = {Radio.ESTADO_OPERATIVO: "operativos", Radio.ESTADO_REGULAR: "regulares",
                     Radio.ESTADO_DANADO: "danados"}.get(r.estado_radio, "sin_estado")
            g[clave] += 1
            if r.puesto_asignado.strip():
                g["_puestos"].add(r.puesto_asignado.strip().lower())
        filas = []
        for g in grupos.values():
            g["puestos"] = len(g.pop("_puestos"))
            filas.append(g)
        filas.sort(key=lambda f: (f["cliente"] == SIN_ASIGNAR, -f["total"], f["cliente"].lower()))
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Clientes con radios, Radios en clientes, Radios sin asignar."""
        con = [f for f in filas if f["cliente"] != SIN_ASIGNAR]
        return [("Clientes con radios", len(con)), ("Radios en clientes", sum(f["total"] for f in con)),
                ("Radios sin asignar", sum(f["total"] for f in filas if f["cliente"] == SIN_ASIGNAR))]


class RadiosComponentes(Informe):
    """Informe «Radios con accesorios en mal estado».

    Radios activos cuya base, cargador, antena, baterías, perillas o clip están regulares o dañados.
    """
    clave = "radios_componentes_danados"
    titulo = "Radios con accesorios en mal estado"
    categoria = CATEGORIA
    descripcion = "Radios activos cuya base, cargador, antena, baterías, perillas o clip están regulares o dañados."
    columnas = (
        Columna("placa", "Placa (RJ)", 1), Columna("serial", "Serial", 1.4),
        Columna("estado", "Estado del radio", 1, "centro", tono=True),
        Columna("cliente", "Cliente", 1.8), Columna("puesto", "Puesto", 1.8),
        Columna("cantidad", "Accesorios", 0.8, "der"),
        Columna("detalle", "Accesorios con problema", 4),
    )
    filtros = (Filtro("nivel", "Mostrar", "select", (("todos", "Regulares y dañados"), ("danados", "Solo dañados"))),)

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios con accesorios en mal estado» según los filtros elegidos (``valores``)."""
        tonos = {"red"} if valores["nivel"] == "danados" else {"red", "amber"}
        filas = []
        for r in Radio.objects.filter(activo=True):
            problemas = [f"{nombre}: {getattr(r, campo)}" for campo, nombre in COMPONENTES
                         if getattr(r, campo) and tono_estado(getattr(r, campo)) in tonos]
            if problemas:
                fila = _fila_radio(r)
                fila["cantidad"] = len(problemas)
                fila["detalle"] = "; ".join(problemas)
                filas.append(fila)
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        """Totales del encabezado: Radios afectados, Accesorios con problema."""
        return [("Radios afectados", len(filas)), ("Accesorios con problema", sum(f["cantidad"] for f in filas))]


class RadiosSinAsignar(Informe):
    """Informe «Radios disponibles (sin cliente asignado)».

    Radios activos que no están en ningún cliente o puesto: los que se pueden entregar.
    """
    clave = "radios_sin_asignar"
    titulo = "Radios disponibles (sin cliente asignado)"
    categoria = CATEGORIA
    descripcion = "Radios activos que no están en ningún cliente o puesto: los que se pueden entregar."
    columnas = (
        Columna("placa", "Placa (RJ)", 1), Columna("codigo", "Código físico", 1),
        Columna("serial", "Serial", 1.4), Columna("marca", "Marca", 1), Columna("modelo", "Modelo", 1.1),
        Columna("estado", "Estado", 1, "centro", tono=True), Columna("observaciones", "Observaciones", 3),
    )
    filtros = (FILTRO_ESTADO_RADIO,)

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios disponibles (sin cliente asignado)» según los filtros elegidos (``valores``)."""
        consulta = Radio.objects.filter(activo=True, cliente_asignado="", puesto_asignado="")
        if valores["estado_radio"]:
            consulta = consulta.filter(estado_radio=valores["estado_radio"])
        return ordenar_por_placa([_fila_radio(r) for r in consulta])

    def resumen(self, filas):
        """Totales del encabezado: Radios disponibles."""
        return [("Radios disponibles", len(filas))]


class RadiosBaja(Informe):
    """Informe «Radios dados de baja».

    Radios retirados del servicio, con fecha y motivo.
    """
    clave = "radios_baja"
    titulo = "Radios dados de baja"
    categoria = CATEGORIA
    descripcion = "Radios retirados del servicio, con fecha y motivo."
    columnas = (
        Columna("placa", "Placa (RJ)", 1), Columna("serial", "Serial", 1.4), Columna("marca", "Marca", 1),
        Columna("modelo", "Modelo", 1.1), Columna("fecha_baja", "Fecha de baja", 1, "der"),
        Columna("motivo", "Motivo", 3.5),
    )
    filtros = (Filtro("desde", "Baja desde", "date"), Filtro("hasta", "Baja hasta", "date"))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios dados de baja» según los filtros elegidos (``valores``)."""
        consulta = Radio.objects.filter(activo=False)
        if valores["desde"]:
            consulta = consulta.filter(fecha_baja__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha_baja__lte=valores["hasta"])
        return ordenar_por_placa([{
            "placa": r.placa or "—", "serial": r.serial, "marca": r.marca, "modelo": r.modelo,
            "fecha_baja": r.fecha_baja, "motivo": r.motivo_baja} for r in consulta])

    def resumen(self, filas):
        """Totales del encabezado: Radios dados de baja."""
        return [("Radios dados de baja", len(filas))]


class RadiosPorRevisar(Informe):
    """Informe «Radios marcados para revisión».

    Radios con datos que no coinciden (placa, serial, asignación) y esperan verificación física.
    """
    clave = "radios_por_revisar"
    titulo = "Radios marcados para revisión"
    categoria = CATEGORIA
    descripcion = "Radios con datos que no coinciden (placa, serial, asignación) y esperan verificación física."
    columnas = (
        Columna("placa", "Placa (RJ)", 1), Columna("serial", "Serial", 1.4), Columna("marca", "Marca", 1),
        Columna("cliente", "Cliente", 1.8), Columna("puesto", "Puesto", 1.8),
        Columna("motivo", "Motivo de la revisión", 3.5),
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios marcados para revisión» según los filtros elegidos (``valores``)."""
        return ordenar_por_placa([{
            "placa": r.placa or "—", "serial": r.serial, "marca": r.marca,
            "cliente": r.cliente_asignado, "puesto": r.puesto_asignado, "motivo": r.motivo_revision,
        } for r in Radio.objects.filter(activo=True, requiere_revision=True)])

    def resumen(self, filas):
        """Totales del encabezado: Radios por revisar."""
        return [("Radios por revisar", len(filas))]


class RadiosRepetidos(Informe):
    """Informe «Radios con serial o placa repetidos».

    Control de calidad: radios que comparten serial o placa y pueden estar duplicados.
    """
    clave = "radios_repetidos"
    titulo = "Radios con serial o placa repetidos"
    categoria = CATEGORIA
    descripcion = "Control de calidad: radios que comparten serial o placa y pueden estar duplicados."
    columnas = (
        Columna("repetido", "Dato repetido", 1.2), Columna("valor", "Valor", 1.6),
        Columna("placa", "Placa (RJ)", 1), Columna("serial", "Serial", 1.4),
        Columna("marca", "Marca y modelo", 1.8), Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("cliente", "Cliente", 2), Columna("puesto", "Puesto", 2),
    )

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Radios con serial o placa repetidos» según los filtros elegidos (``valores``)."""
        radios = list(Radio.objects.all())
        filas = []
        for campo, etiqueta in (("serial", "Serial"), ("placa", "Placa")):
            grupos = {}
            for r in radios:
                valor = (getattr(r, campo) or "").strip().upper()
                if valor:
                    grupos.setdefault(valor, []).append(r)
            for valor, lista in sorted(grupos.items()):
                if len(lista) < 2:
                    continue
                for r in lista:
                    fila = _fila_radio(r)
                    fila.update(repetido=etiqueta, valor=valor, marca=f"{r.marca} {r.modelo}".strip())
                    filas.append(fila)
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Radios involucrados, Valores repetidos."""
        return [("Radios involucrados", len(filas)),
                ("Valores repetidos", len({(f["repetido"], f["valor"]) for f in filas}))]


INFORMES = [InventarioRadios(), RadiosPorCliente(), RadiosComponentes(), RadiosSinAsignar(),
            RadiosBaja(), RadiosPorRevisar(), RadiosRepetidos()]
