"""Resumen general: las cifras clave de todo el inventario en una página."""
from datetime import timedelta

from ..estado_mantenimiento import hoy_colombia
from ..models import (
    AsignacionEquipo, AsignacionRadio, Cliente, Equipo, MantenimientoEquipo, MantenimientoProgramado,
    Puesto, Radio, Vigilante,
)
from .base import Columna, Informe
from .clientes import VigilantesConRadio
from .entregas import EntregasSinFirma
from .mantenimiento import SemaforoMantenimiento
from .seguridad import AntivirusVencimientos, EstadoPolitica


def _contar(filas, clave, valor):
    return sum(1 for f in filas if f[clave] == valor)


def _filas(informe, **filtros):
    return informe.obtener_filas(informe.validar_filtros(filtros))


class ResumenGeneral(Informe):
    clave = "resumen_general"
    titulo = "Resumen general del inventario"
    categoria = "General"
    descripcion = "Las cifras clave de equipos, radios, mantenimiento, seguridad, entregas y clientes en una sola página."
    columnas = (Columna("area", "Área", 1.6), Columna("indicador", "Indicador", 4), Columna("valor", "Valor", 1, "der"))
    orientacion = "vertical"
    filtros = ()

    def obtener_filas(self, valores, usuario=None):
        hoy = hoy_colombia()
        filas = []

        def agregar(area, indicador, valor):
            filas.append({"area": area, "indicador": indicador, "valor": valor})

        activos = Equipo.objects.filter(activo=True)
        agregar("Equipos", "Equipos en servicio", activos.count())
        agregar("Equipos", "Equipos dados de baja", Equipo.objects.filter(activo=False).count())
        agregar("Equipos", "Equipos no operativos",
                activos.filter(estado_operativo=Equipo.EstadoOperativo.NO_OPERATIVO).count())
        agregar("Equipos", "Equipos marcados para revisión", activos.filter(requiere_revision=True).count())
        for tipo, etiqueta in Equipo.Tipo.choices:
            n = activos.filter(tipo=tipo).count()
            if n:
                agregar("Equipos", f"En servicio: {etiqueta}", n)

        radios = Radio.objects.filter(activo=True)
        agregar("Radios", "Radios en servicio", radios.count())
        for estado, etiqueta in ((Radio.ESTADO_OPERATIVO, "operativos"), (Radio.ESTADO_REGULAR, "en estado regular"),
                                 (Radio.ESTADO_DANADO, "dañados")):
            agregar("Radios", f"Radios {etiqueta}", radios.filter(estado_radio=estado).count())
        agregar("Radios", "Radios sin cliente asignado", radios.filter(cliente_asignado="", puesto_asignado="").count())
        agregar("Radios", "Radios marcados para revisión", radios.filter(requiere_revision=True).count())

        filas_m = _filas(SemaforoMantenimiento())
        agregar("Mantenimiento", "Equipos con mantenimiento vencido", _contar(filas_m, "estado", "Vencido"))
        agregar("Mantenimiento", "Equipos sin ningún mantenimiento", _contar(filas_m, "estado", "Sin mantenimiento"))
        agregar("Mantenimiento", "Equipos que vencen en los próximos 30 días",
                sum(1 for f in filas_m if f["estado"].startswith("Vence en")))
        agregar("Mantenimiento", "Equipos con mantenimiento vigente", _contar(filas_m, "estado", "Vigente"))
        agregar("Mantenimiento", "Visitas programadas atrasadas", MantenimientoProgramado.objects.filter(
            estado=MantenimientoProgramado.Estado.PROGRAMADO, fecha_programada__lt=hoy).count())
        agregar("Mantenimiento", "Intervenciones en los últimos 30 días", MantenimientoEquipo.objects.filter(
            fecha_intervencion__date__gte=hoy - timedelta(days=30)).count())

        filas_p = _filas(EstadoPolitica())
        agregar("Seguridad informática", "Computadores sin verificación de política", _contar(filas_p, "estado", "Sin verificar"))
        agregar("Seguridad informática", "Verificaciones de política vencidas", _contar(filas_p, "estado", "Vencida"))
        agregar("Seguridad informática", "Computadores con incumplimientos", _contar(filas_p, "estado", "Con incumplimientos"))
        agregar("Seguridad informática", "Computadores al día con la política", _contar(filas_p, "estado", "Al día"))
        filas_a = _filas(AntivirusVencimientos())
        agregar("Seguridad informática", "Antivirus vencidos", _contar(filas_a, "estado", "Vencido"))
        agregar("Seguridad informática", "Antivirus que vencen en 30 días",
                sum(1 for f in filas_a if f["estado"].startswith("Vence en")))
        agregar("Seguridad informática", "Computadores sin fecha de antivirus", _contar(filas_a, "estado", "Sin fecha registrada"))

        agregar("Entregas", "Radios entregados a vigilantes",
                AsignacionRadio.objects.filter(estado=AsignacionRadio.Estado.ASIGNADO).count())
        agregar("Entregas", "Equipos entregados a funcionarios",
                AsignacionEquipo.objects.filter(estado=AsignacionEquipo.Estado.ASIGNADO).count())
        agregar("Entregas", "Entregas sin firma o sin cláusula aceptada", len(_filas(EntregasSinFirma())))

        agregar("Clientes y vigilantes", "Clientes activos", Cliente.objects.filter(activo=True).count())
        agregar("Clientes y vigilantes", "Puestos activos", Puesto.objects.filter(activo=True).count())
        agregar("Clientes y vigilantes", "Vigilantes activos", Vigilante.objects.filter(activo=True).count())
        agregar("Clientes y vigilantes", "Vigilantes activos sin radio", len(_filas(VigilantesConRadio(), tiene="sin")))
        return filas

    def resumen(self, filas):
        def valor(indicador):
            return next((f["valor"] for f in filas if f["indicador"] == indicador), 0)
        return [("Equipos en servicio", valor("Equipos en servicio")),
                ("Radios en servicio", valor("Radios en servicio")),
                ("Mantenimientos vencidos", valor("Equipos con mantenimiento vencido")),
                ("Antivirus vencidos", valor("Antivirus vencidos")),
                ("Radios entregados", valor("Radios entregados a vigilantes"))]


INFORME = ResumenGeneral()
