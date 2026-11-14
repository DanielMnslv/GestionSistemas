"""Hoja de vida de un equipo: todo lo que le ha pasado, en orden."""
from datetime import datetime, time

from ..estado_mantenimiento import ZONA_COLOMBIA
from ..models import (
    AlertaMantenimiento, AsignacionEquipo, AsignacionRadio, CambioGPS, Equipo, MantenimientoEquipo,
    MantenimientoProgramado, RenovacionAntivirus, TransferenciaComponentesRadio, VerificacionPolitica,
)
from .base import Columna, Filtro, Informe


def _momento(valor):
    """Convierte una fecha en fecha y hora (para ordenar los eventos juntos)."""
    if isinstance(valor, datetime):
        return valor
    return datetime.combine(valor, time.min, tzinfo=ZONA_COLOMBIA)


def _usuario(u):
    """Nombre del usuario, o vacío si no hay."""
    return (u.get_full_name() or u.get_username()) if u else ""


def _recortar(texto, largo=300):
    """Texto en una línea, recortado a ``largo`` caracteres."""
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"


class HistorialEquipo(Informe):
    """Informe «Hoja de vida de un equipo».

    Todo lo que ha pasado con un equipo: mantenimientos, entregas, verificaciones, renovaciones y bajas. Escribe la placa.
    """
    clave = "historial_equipo"
    titulo = "Hoja de vida de un equipo"
    categoria = "Equipos de TI"
    descripcion = "Todo lo que ha pasado con un equipo: mantenimientos, entregas, verificaciones, renovaciones y bajas. Escribe la placa."
    columnas = (
        Columna("fecha", "Fecha", 1.2, "der"), Columna("evento", "Evento", 1.8),
        Columna("detalle", "Detalle", 5), Columna("responsable", "Responsable", 1.6),
    )
    orientacion = "vertical"
    filtros = (Filtro("placa", "Placa o serial", ayuda="Escribe la placa o el serial exacto del equipo."),)

    def _buscar(self, texto):
        """Busca el equipo por placa o por serial (sin importar mayúsculas)."""
        if not texto:
            return None
        base = Equipo.objects.select_related("radio")
        return base.filter(placa__iexact=texto).first() or base.filter(serial__iexact=texto).first()

    def aviso(self, valores, filas):
        """Mensaje si falta la placa o si el equipo no existe."""
        if not valores["placa"]:
            return "Escribe la placa o el serial de un equipo para ver su hoja de vida."
        equipo = self._buscar(valores["placa"])
        if equipo is None:
            return f"No se encontró ningún equipo con la placa o serial «{valores['placa']}»."
        return (f"{equipo.placa} · {equipo.get_tipo_display()} · "
                f"{(equipo.marca + ' ' + equipo.modelo).strip() or 'sin marca'}"
                f" · Serial {equipo.serial or 'sin dato'}")

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Hoja de vida de un equipo» según los filtros elegidos (``valores``)."""
        equipo = self._buscar(valores["placa"])
        if equipo is None:
            return []
        eventos = []

        def agregar(fecha, evento, detalle="", responsable="", clase=""):
            """Agrega un evento a la hoja de vida."""
            eventos.append({"fecha": fecha, "evento": evento, "detalle": _recortar(detalle),
                            "responsable": responsable, "_momento": _momento(fecha), "_clase": clase})

        agregar(equipo.creado_en, "Registro en el inventario",
                f"Propiedad: {equipo.propiedad}" if equipo.propiedad else "")
        if equipo.fecha_compra:
            agregar(equipo.fecha_compra, "Compra")
        if not equipo.activo:
            agregar(equipo.fecha_baja or equipo.actualizado_en, "Baja del inventario", equipo.motivo_baja)

        for m in MantenimientoEquipo.objects.filter(equipo=equipo):
            agregar(m.fecha_intervencion, m.get_tipo_display(),
                    f"{m.trabajo_realizado} — Resultado: {m.get_resultado_display()}; "
                    f"estado final: {m.get_estado_final_display()}", m.tecnico_responsable, "mantenimiento")
        for p in MantenimientoProgramado.objects.filter(equipo=equipo).select_related("creado_por"):
            agregar(p.fecha_programada, f"Mantenimiento programado ({p.get_estado_display()})",
                    p.descripcion, _usuario(p.creado_por))
        for a in AlertaMantenimiento.objects.filter(equipo=equipo):
            agregar(a.fecha_vencimiento, f"Alerta de mantenimiento ({a.get_estado_display()})",
                    "Vencimiento del mantenimiento preventivo.")
        for a in AsignacionEquipo.objects.filter(equipo=equipo).select_related(
                "funcionario", "entregado_por", "recibido_por"):
            quien = a.nombre_recibe or (a.funcionario.nombre_completo if a.funcionario else "")
            agregar(a.fecha_entrega, "Entrega", f"A {quien}" + (f" · {a.area}" if a.area else ""),
                    _usuario(a.entregado_por), "entrega")
            if a.fecha_devolucion:
                agregar(a.fecha_devolucion, "Devolución", f"De {quien}", _usuario(a.recibido_por))
        for v in VerificacionPolitica.objects.filter(equipo=equipo):
            n = len(v.incumplimientos)
            agregar(v.fecha, "Verificación de política de seguridad",
                    f"{n} punto{'s' if n != 1 else ''} no cumple{'n' if n != 1 else ''}. {v.observaciones}",
                    v.especialista)
        for r in RenovacionAntivirus.objects.filter(equipo=equipo).select_related("registrado_por"):
            venc = f" · vence {r.vencimiento:%d/%m/%Y}" if r.vencimiento else ""
            agregar(r.fecha, "Renovación de antivirus", f"{r.antivirus}{venc}", _usuario(r.registrado_por))
        for c in CambioGPS.objects.filter(equipo=equipo).select_related("registrado_por"):
            agregar(c.fecha, "Cambio de datos del GPS", f"{c.dato_actualizado} {c.observaciones}".strip(),
                    c.responsable or _usuario(c.registrado_por))

        radio = getattr(equipo, "radio", None)
        if radio is not None:
            for a in AsignacionRadio.objects.filter(radio=radio).select_related("entregado_por", "recibido_por"):
                destino = f"{a.cliente_asignado} - {a.puesto_asignado} (cédula {a.cedula_funcionario})"
                agregar(a.fecha_entrega, "Entrega del radio", destino, _usuario(a.entregado_por), "entrega")
                if a.fecha_devolucion:
                    agregar(a.fecha_devolucion, "Devolución del radio", destino, _usuario(a.recibido_por))
            for t in TransferenciaComponentesRadio.objects.filter(radio_origen=radio).select_related("registrado_por"):
                agregar(t.fecha, "Accesorios entregados a otro radio", f"A {t.etiqueta_destino}",
                        _usuario(t.registrado_por))
            for t in TransferenciaComponentesRadio.objects.filter(radio_destino=radio).select_related("registrado_por"):
                agregar(t.fecha, "Accesorios recibidos de otro radio", f"De {t.etiqueta_origen}",
                        _usuario(t.registrado_por))

        eventos.sort(key=lambda e: e["_momento"], reverse=True)
        return eventos

    def resumen(self, filas):
        """Totales del encabezado: Eventos, Mantenimientos, Entregas."""
        return [("Eventos", len(filas)),
                ("Mantenimientos", sum(1 for f in filas if f["_clase"] == "mantenimiento")),
                ("Entregas", sum(1 for f in filas if f["_clase"] == "entrega"))]


INFORME = HistorialEquipo()
