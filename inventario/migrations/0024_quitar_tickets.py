from django.db import migrations

ACTIVOS = ("ABIERTO", "ASIGNADO", "EN_ATENCION")


def devolver_a_programados(apps, schema_editor):
    """Los tickets preventivos eran los mantenimientos programados (0018).
    Antes de borrar los tickets, la programación vuelve a su tabla de origen
    para no perder los mantenimientos pendientes."""
    Ticket = apps.get_model("inventario", "Ticket")
    Programado = apps.get_model("inventario", "MantenimientoProgramado")

    preventivos = list(
        Ticket.objects.filter(
            origen="PREVENTIVO",
            equipo__isnull=False,
            fecha_programada__isnull=False,
        ).order_by("creado_en", "id")
    )
    usados = set()

    # 1) Programaciones que ya existían: se actualizan con lo ocurrido en
    #    su ticket (cancelado o ya atendido).
    for programacion in Programado.objects.filter(
        estado="PROGRAMADO"
    ).order_by("creado_en", "id"):
        ticket = next(
            (
                t for t in preventivos
                if t.pk not in usados
                and t.equipo_id == programacion.equipo_id
                and t.fecha_programada == programacion.fecha_programada
            ),
            None,
        )
        if ticket is None:
            continue
        usados.add(ticket.pk)
        if ticket.estado == "CANCELADO":
            programacion.estado = "CANCELADO"
        elif ticket.estado in ("RESUELTO", "CERRADO"):
            programacion.estado = "COMPLETADO"
            intervencion = ticket.intervenciones.order_by(
                "-fecha_intervencion", "-id"
            ).first()
            if intervencion is not None:
                programacion.intervencion_realizada_id = intervencion.pk
        else:
            continue
        programacion.save(
            update_fields=["estado", "intervencion_realizada"]
        )

    # 2) Mantenimientos programados después de 0018: solo existían como
    #    ticket. Los pendientes vuelven como programaciones.
    for ticket in preventivos:
        if ticket.pk in usados:
            continue
        if ticket.estado not in ACTIVOS or not ticket.creado_por_id:
            continue
        Programado.objects.create(
            equipo_id=ticket.equipo_id,
            fecha_programada=ticket.fecha_programada,
            tipo="PREVENTIVO" if ticket.tipo == "PREVENTIVO" else "CORRECTIVO",
            descripcion=ticket.descripcion,
            estado="PROGRAMADO",
            creado_por_id=ticket.creado_por_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0023_quitar_operativo_radio"),
    ]

    operations = [
        migrations.RunPython(devolver_a_programados, migrations.RunPython.noop),
        migrations.RemoveField(model_name="mantenimientoequipo", name="ticket"),
        migrations.DeleteModel(name="FotoTicket"),
        migrations.DeleteModel(name="EventoTicket"),
        migrations.DeleteModel(name="Ticket"),
    ]
