"""Correos de los tickets.

Los correos nunca detienen el flujo: si el envío falla, queda anotado en la
bitácora del ticket (como evento interno).
"""
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .models import EventoTicket, Ticket

T = EventoTicket.Tipo


def enlace_caso(ticket):
    return settings.SITIO_URL.rstrip("/") + reverse("soporte_caso", args=[ticket.token])


def enlace_interno(ticket):
    return settings.SITIO_URL.rstrip("/") + reverse(
        "inventario:ticket_detalle", args=[ticket.numero]
    )


def destinatarios_ti():
    from .management.commands.procesar_alertas_mantenimiento import DESTINATARIOS

    return list(DESTINATARIOS)


def resumen(ticket):
    lineas = [f"Caso: {ticket.numero}", f"Tipo: {ticket.get_tipo_display()}"]
    if ticket.equipo_id:
        lineas.append(
            f"Equipo: {ticket.equipo.placa} ({ticket.equipo.get_tipo_display()})"
        )
    lineas.append(f"Descripción: {ticket.descripcion}")
    return "\n".join(lineas)


def mensajes_para(ticket, evento):
    """[(destinatarios, asunto, cuerpo)] según el evento."""
    saludo = f"Estimado(a) {ticket.solicitante_nombre or 'usuario'},\n\n"
    firma = "\n\nÁrea de Tecnología · Seguridad Jano\nMensaje automático."
    tecnico = ticket.tecnico
    mensajes = []

    if evento == T.CREADO:
        if ticket.solicitante_correo:
            mensajes.append((
                [ticket.solicitante_correo],
                f"Recibimos tu solicitud {ticket.numero}",
                saludo + "Me permito notificar que el requerimiento de soporte "
                "fue recibido y será atendido por el área de TI.\n\n"
                f"{resumen(ticket)}\n\nConsulta el estado de tu caso aquí:\n"
                f"{enlace_caso(ticket)}" + firma,
            ))
        if ticket.origen == Ticket.Origen.FORMULARIO:
            mensajes.append((
                destinatarios_ti(),
                f"Nueva solicitud de soporte {ticket.numero}",
                f"{ticket.solicitante_nombre} ({ticket.ubicacion}) pidió soporte.\n\n"
                f"{resumen(ticket)}\n\nAsignar técnico: {enlace_interno(ticket)}",
            ))
    elif evento == T.ASIGNADO:
        cuando = ""
        if ticket.fecha_programada:
            cuando = f" para el {ticket.fecha_programada:%d/%m/%Y}"
            if ticket.franja:
                cuando += f" de {ticket.get_franja_display()}"
        nombre_tecnico = tecnico.get_full_name() or tecnico.username
        if ticket.solicitante_correo:
            mensajes.append((
                [ticket.solicitante_correo],
                f"Tu caso {ticket.numero} tiene técnico asignado",
                saludo + f"Tu requerimiento fue asignado a {nombre_tecnico}"
                f"{cuando}.\n\n{resumen(ticket)}\n\nSeguimiento: "
                f"{enlace_caso(ticket)}" + firma,
            ))
        if tecnico.email:
            mensajes.append((
                [tecnico.email],
                f"Te asignaron el ticket {ticket.numero}",
                f"Se te asignó el ticket {ticket.numero}{cuando}.\n\n"
                f"Solicitante: {ticket.solicitante_nombre} · "
                f"{ticket.solicitante_telefono or ticket.solicitante_correo}\n"
                f"Ubicación: {ticket.ubicacion}\n{resumen(ticket)}\n\n"
                f"Atender: {enlace_interno(ticket)}",
            ))
    elif evento == T.RESUELTO:
        if ticket.solicitante_correo:
            mensajes.append((
                [ticket.solicitante_correo],
                f"Tu caso {ticket.numero} fue resuelto",
                saludo + "Me permito notificar que el requerimiento de soporte "
                f"fue atendido.\n\nSolución: {ticket.solucion}\n\n"
                "Confirma si quedó resuelto o indícanos si sigue fallando:\n"
                f"{enlace_caso(ticket)}\n\nSi no respondes, el caso se cerrará "
                "automáticamente en 3 días." + firma,
            ))
    elif evento == T.REABIERTO:
        para = [tecnico.email] if tecnico and tecnico.email else destinatarios_ti()
        mensajes.append((
            para,
            f"Se reabrió el ticket {ticket.numero}",
            f"El solicitante indicó que el caso {ticket.numero} no quedó "
            f"resuelto.\n\n{resumen(ticket)}\n\nRevisar: {enlace_interno(ticket)}",
        ))
    return mensajes


def notificar_ticket(ticket, evento):
    if ticket.origen == Ticket.Origen.IMPORTADO:
        return
    for destinatarios, asunto, cuerpo in mensajes_para(ticket, evento):
        destinatarios = [d for d in destinatarios if d]
        if not destinatarios:
            continue
        try:
            send_mail(
                subject=asunto, message=cuerpo,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=destinatarios, fail_silently=False,
            )
            texto = f"Correo enviado a {', '.join(destinatarios)}: {asunto}"
        except Exception as error:  # El correo no debe romper el flujo.
            texto = (
                f"No se pudo enviar el correo a {', '.join(destinatarios)} "
                f"({asunto}): {error}"
            )
        EventoTicket.objects.create(
            ticket=ticket, tipo=T.CORREO, texto=texto, publico=False
        )
