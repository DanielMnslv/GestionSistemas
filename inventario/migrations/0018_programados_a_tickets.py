from django.db import migrations
from django.utils import timezone


# Los mantenimientos programados pasan a ser tickets preventivos. La tabla
# de programados se conserva como historial.
ESTADOS = {
    "PROGRAMADO": "ABIERTO",
    "COMPLETADO": "CERRADO",
    "CANCELADO": "CANCELADO",
}


def programados_a_tickets(apps, schema_editor):
    Programado = apps.get_model("inventario", "MantenimientoProgramado")
    Ticket = apps.get_model("inventario", "Ticket")
    EventoTicket = apps.get_model("inventario", "EventoTicket")

    contadores = {}
    for p in Programado.objects.order_by("creado_en", "id"):
        anio = timezone.localtime(p.creado_en).year
        if anio not in contadores:
            contadores[anio] = Ticket.objects.filter(
                numero__startswith=f"TK-{anio}-"
            ).count()
        contadores[anio] += 1
        estado = ESTADOS.get(p.estado, "ABIERTO")
        intervencion = p.intervencion_realizada
        ticket = Ticket.objects.create(
            numero=f"TK-{anio}-{contadores[anio]:04d}",
            origen="PREVENTIVO",
            tipo="PREVENTIVO" if p.tipo == "PREVENTIVO" else "CORRECTIVO",
            categoria="MANTENIMIENTO",
            estado=estado,
            equipo_id=p.equipo_id,
            descripcion=p.descripcion,
            fecha_programada=p.fecha_programada,
            solucion=(intervencion.trabajo_realizado if intervencion else ""),
            creado_por_id=p.creado_por_id,
            creado_en=p.creado_en,
            resuelto_en=(intervencion.fecha_intervencion if intervencion else None),
            cerrado_en=(
                intervencion.fecha_intervencion if intervencion
                else (p.creado_en if estado == "CANCELADO" else None)
            ),
        )
        EventoTicket.objects.create(
            ticket=ticket, fecha=p.creado_en, usuario_id=p.creado_por_id,
            tipo="CREADO",
            texto="Creado a partir de un mantenimiento programado.",
        )
        if intervencion:
            intervencion.ticket = ticket
            intervencion.save(update_fields=["ticket"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0017_tickets"),
    ]

    operations = [
        migrations.RunPython(programados_a_tickets, migrations.RunPython.noop),
    ]
