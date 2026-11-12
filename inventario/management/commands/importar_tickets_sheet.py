from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    clave_placa,
    libro_del_sheet,
    normalizar_encabezado,
    normalizar_placa,
    texto_celda,
)
from inventario.models import Equipo, EventoTicket, MantenimientoEquipo, Ticket

ZONA = ZoneInfo("America/Bogota")
# Las solicitudes más recientes que esto sin cierre quedan abiertas; las
# anteriores se cierran como histórico para no llenar la bandeja.
DIAS_ABIERTAS = 30

# CONSOLIDADO REPORTE: campo -> encabezado.
CONSOLIDADO = {
    "fecha": "FECHA DE REGISTRO",
    "nombre": "NOMBRE",
    "falla": "POR FAVOR DESCRIBA CUAL ES LA FALLA",
    "equipo": "EQUIPO A INTERVENIR",
    "placa": "PLACA DEL EQUIPO",
    "tecnico": "TECNICO ASIGNADO",
    "fecha_asignacion": "FECHA DE ASIGNACION",
    "horario": "HORARIO ASIGNADO",
    "correo": "CORREO SOLICITANTE",
    "codigo": "CODIGO CONSULTA",
    "actividad": "ACTIVIDAD REALIZADA",
    "estado_final": "ESTADO FINAL DEL EQUIPO",
}
# BD (respuestas del formulario de soporte): campo -> posición.
BD = {
    "fecha": 0, "tipo_soporte": 2, "detalle": 5, "lugar": 6, "elemento": 7,
    "falla_presentada": 9,
}
CATEGORIAS = {
    "SOPORTE": (Ticket.Tipo.SOPORTE, Ticket.Categoria.SOFTWARE),
    "OFICINA": (Ticket.Tipo.CORRECTIVO, Ticket.Categoria.EQUIPO_OFICINA),
    "OPERACION": (Ticket.Tipo.CORRECTIVO, Ticket.Categoria.OPERACION),
}


def limpio(valor):
    texto = texto_celda(valor)
    return "" if texto.upper() in ("#N/A", "N/A", "NONE", "FALSO", "VERDADERO") else texto


def celda(fila, i):
    return fila[i] if i < len(fila) else None


def aware(fecha):
    return timezone.make_aware(fecha.replace(microsecond=0), ZONA)


class Command(BaseCommand):
    help = (
        "Importa las solicitudes de soporte del Sheet (CONSOLIDADO REPORTE y "
        "BD) como tickets. Las enlaza con su mantenimiento por el código de "
        "consulta. Las antiguas sin cierre quedan cerradas como histórico. "
        "Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument("--confirmar", action="store_true", help="Guardar los cambios.")

    def handle(self, *args, **options):
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            libro = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
            try:
                hoja = list(libro["CONSOLIDADO REPORTE"].iter_rows(values_only=True))
                bd = [
                    r for r in libro["BD"].iter_rows(min_row=2, values_only=True)
                    if isinstance(r[0], datetime)
                ]
            finally:
                libro.close()

        posiciones = {normalizar_encabezado(v): i for i, v in enumerate(hoja[0]) if v}
        indices = {c: posiciones[normalizar_encabezado(h)] for c, h in CONSOLIDADO.items()}
        filas = [
            {c: (r[i] if i < len(r) else None) for c, i in indices.items()}
            for r in hoja[1:] if r and isinstance(r[0], datetime)
        ]
        filas.sort(key=lambda f: f["fecha"])

        equipos = {e.placa: e for e in Equipo.objects.all()}
        por_clave = {}
        for e in equipos.values():
            por_clave.setdefault(clave_placa(e.placa), []).append(e)
        existentes = set(
            Ticket.objects.filter(origen=Ticket.Origen.IMPORTADO)
            .values_list("creado_en", flat=True)
        )
        limite_abiertas = timezone.now() - timedelta(days=DIAS_ABIERTAS)

        plan = []
        for f in filas:
            creado = aware(f["fecha"])
            if creado in existentes:
                continue
            existentes.add(creado)
            respuesta = next(
                (b for b in bd if abs((b[BD["fecha"]] - f["fecha"]).total_seconds()) < 5),
                None,
            )
            tipo_soporte = limpio(celda(respuesta, BD["tipo_soporte"])).upper() if respuesta else ""
            tipo, categoria = next(
                (v for k, v in CATEGORIAS.items() if k in tipo_soporte),
                (Ticket.Tipo.CORRECTIVO, Ticket.Categoria.OTRA),
            )
            partes = [limpio(f["falla"])]
            if respuesta:
                partes += [limpio(celda(respuesta, BD[c])) for c in ("detalle", "falla_presentada", "elemento")]
            descripcion = "\n".join(dict.fromkeys(p for p in partes if p)) or "Sin descripción"

            placa = normalizar_placa(f["placa"])
            equipo = equipos.get(placa)
            if equipo is None and placa:
                candidatos = por_clave.get(clave_placa(placa), [])
                equipo = candidatos[0] if len(candidatos) == 1 else None

            codigo = limpio(f["codigo"])
            intervencion = (
                MantenimientoEquipo.objects.filter(observaciones__contains=codigo).first()
                if len(codigo) > 6 else None
            )
            actividad = limpio(f["actividad"])
            estado_final = limpio(f["estado_final"])
            resuelto = intervencion is not None or bool(actividad or estado_final)

            horario = limpio(f["horario"]).replace(" ", "")
            fecha_asignacion = f["fecha_asignacion"]
            plan.append({
                "ticket": dict(
                    origen=Ticket.Origen.IMPORTADO, tipo=tipo, categoria=categoria,
                    equipo=equipo, descripcion=descripcion,
                    solicitante_nombre=limpio(f["nombre"])[:200],
                    solicitante_correo=limpio(f["correo"]) if "@" in limpio(f["correo"]) else "",
                    ubicacion=limpio(celda(respuesta, BD["lugar"]))[:200] if respuesta else "",
                    fecha_programada=fecha_asignacion.date() if isinstance(fecha_asignacion, datetime) else None,
                    franja=(Ticket.Franja.MANANA if horario.startswith("8") else
                            Ticket.Franja.TARDE if horario.startswith("2") else ""),
                    creado_en=creado,
                ),
                "tecnico": limpio(f["tecnico"]),
                "intervencion": intervencion,
                "resuelto": resuelto,
                "solucion": actividad or estado_final or (
                    intervencion.trabajo_realizado if intervencion else ""
                ),
                "abierto": not resuelto and creado >= limite_abiertas,
                "placa_sin_equipo": placa if placa and equipo is None else "",
            })

        abiertos = sum(1 for p in plan if p["abierto"])
        self.stdout.write(f"Tickets a importar: {len(plan)}")
        self.stdout.write(f"  con mantenimiento enlazado: {sum(1 for p in plan if p['intervencion'])}")
        self.stdout.write(f"  resueltos: {sum(1 for p in plan if p['resuelto'])}")
        self.stdout.write(f"  quedan abiertos (últimos {DIAS_ABIERTAS} días sin cierre): {abiertos}")
        sin_equipo = sorted({p["placa_sin_equipo"] for p in plan if p["placa_sin_equipo"]})
        if sin_equipo:
            self.stdout.write(f"  placas sin equipo en la plataforma: {', '.join(sin_equipo)}")
        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. Usa --confirmar para aplicar."
            ))
            return

        with transaction.atomic():
            for p in plan:
                datos = p["ticket"]
                creado = datos["creado_en"]
                ticket = Ticket(**datos)
                eventos = [EventoTicket(
                    tipo=EventoTicket.Tipo.CREADO, fecha=creado,
                    texto=f"Importado del Sheet: {datos['descripcion']}",
                )]
                if p["tecnico"]:
                    eventos.append(EventoTicket(
                        tipo=EventoTicket.Tipo.ASIGNADO, fecha=creado,
                        texto=f"Asignado en el Sheet a {p['tecnico']}.",
                    ))
                if p["resuelto"]:
                    fin = (
                        p["intervencion"].fecha_intervencion if p["intervencion"] else creado
                    )
                    ticket.estado = Ticket.Estado.CERRADO
                    ticket.solucion = p["solucion"]
                    ticket.resuelto_en = ticket.cerrado_en = max(fin, creado)
                    eventos.append(EventoTicket(
                        tipo=EventoTicket.Tipo.CERRADO, fecha=ticket.cerrado_en,
                        texto=p["solucion"] or "Cerrado en el Sheet.",
                    ))
                elif not p["abierto"]:
                    ticket.estado = Ticket.Estado.CERRADO
                    ticket.cerrado_en = creado
                    ticket.solucion = "Histórico sin cierre registrado en el Sheet."
                    eventos.append(EventoTicket(
                        tipo=EventoTicket.Tipo.CERRADO, fecha=creado,
                        texto=ticket.solucion,
                    ))
                ticket.save()
                for evento in eventos:
                    evento.ticket = ticket
                EventoTicket.objects.bulk_create(eventos)
                if p["intervencion"] and p["intervencion"].ticket_id is None:
                    p["intervencion"].ticket = ticket
                    p["intervencion"].save(update_fields=["ticket"])
        self.stdout.write(self.style.SUCCESS(f"Importación completada: {len(plan)} tickets."))
