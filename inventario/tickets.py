"""Reglas del flujo de tickets.

Toda modificación de estado pasa por aquí: valida la transición, guarda las
marcas de tiempo, deja el evento en la bitácora y avisa a quien
corresponda (inventario/notificaciones.py).
"""
from django.db import transaction
from django.utils import timezone

from .models import EventoTicket, Ticket

E = Ticket.Estado

TRANSICIONES = {
    E.ABIERTO: {E.ASIGNADO, E.EN_ATENCION, E.RESUELTO, E.CANCELADO},
    E.ASIGNADO: {E.ASIGNADO, E.EN_ATENCION, E.RESUELTO, E.CANCELADO},
    E.EN_ATENCION: {E.ASIGNADO, E.RESUELTO, E.CANCELADO},
    E.RESUELTO: {E.CERRADO, E.ABIERTO, E.ASIGNADO},
    E.CERRADO: set(),
    E.CANCELADO: set(),
}

DIAS_CIERRE_AUTOMATICO = 3


class TransicionInvalida(Exception):
    pass


def puede_pasar(ticket, estado):
    return estado in TRANSICIONES[ticket.estado]


def _validar(ticket, estado):
    if not puede_pasar(ticket, estado):
        raise TransicionInvalida(
            f"El ticket {ticket.numero} está {ticket.get_estado_display().lower()} "
            f"y no puede pasar a {E(estado).label.lower()}."
        )


def registrar_evento(ticket, tipo, usuario=None, texto="", publico=True):
    return EventoTicket.objects.create(
        ticket=ticket, tipo=tipo, usuario=usuario, texto=texto, publico=publico
    )


def _avisar(ticket, evento):
    # Importación tardía: notificaciones usa este módulo.
    from .notificaciones import notificar_ticket

    transaction.on_commit(lambda: notificar_ticket(ticket, evento))


@transaction.atomic
def crear(usuario=None, **datos):
    ticket = Ticket.objects.create(creado_por=usuario, **datos)
    registrar_evento(
        ticket, EventoTicket.Tipo.CREADO, usuario,
        f"{ticket.get_origen_display()}: {ticket.descripcion}",
    )
    _avisar(ticket, EventoTicket.Tipo.CREADO)
    return ticket


@transaction.atomic
def asignar(ticket, tecnico, usuario, fecha_programada=None, franja="",
            prioridad=None):
    _validar(ticket, E.ASIGNADO)
    reprogramacion = ticket.estado == E.ASIGNADO
    if prioridad:
        ticket.prioridad = prioridad
    ticket.tecnico = tecnico
    ticket.fecha_programada = fecha_programada
    ticket.franja = franja
    ticket.estado = E.ASIGNADO
    ticket.asignado_en = timezone.now()
    ticket.save()
    cuando = ""
    if fecha_programada:
        cuando = f" para el {fecha_programada:%d/%m/%Y}"
        if franja:
            cuando += f" de {ticket.get_franja_display()}"
    registrar_evento(
        ticket, EventoTicket.Tipo.ASIGNADO, usuario,
        f"{'Reprogramado' if reprogramacion else 'Asignado'} a "
        f"{tecnico.get_full_name() or tecnico.username}{cuando}.",
    )
    _avisar(ticket, EventoTicket.Tipo.ASIGNADO)
    return ticket


@transaction.atomic
def iniciar_atencion(ticket, usuario):
    _validar(ticket, E.EN_ATENCION)
    ticket.estado = E.EN_ATENCION
    ticket.atencion_en = timezone.now()
    if ticket.tecnico_id is None:
        ticket.tecnico = usuario
    ticket.save()
    registrar_evento(ticket, EventoTicket.Tipo.ATENCION, usuario,
                     "El técnico inició la atención.")
    return ticket


@transaction.atomic
def resolver(ticket, usuario, solucion, firma="", firma_nombre="",
             intervencion=None):
    _validar(ticket, E.RESUELTO)
    ahora = timezone.now()
    ticket.estado = E.RESUELTO
    ticket.solucion = solucion
    ticket.firma = firma
    ticket.firma_nombre = firma_nombre
    ticket.resuelto_en = ahora
    ticket.atencion_en = ticket.atencion_en or ahora
    if ticket.tecnico_id is None:
        ticket.tecnico = usuario
    ticket.save()
    if intervencion is not None:
        intervencion.ticket = ticket
        intervencion.save(update_fields=["ticket"])
    registrar_evento(ticket, EventoTicket.Tipo.RESUELTO, usuario, solucion)
    _avisar(ticket, EventoTicket.Tipo.RESUELTO)
    return ticket


def _cerrar(ticket, tipo, texto, usuario=None, automatico=False):
    _validar(ticket, E.CERRADO)
    ticket.estado = E.CERRADO
    ticket.cerrado_en = timezone.now()
    ticket.cierre_automatico = automatico
    ticket.save()
    registrar_evento(ticket, tipo, usuario, texto)
    return ticket


@transaction.atomic
def confirmar(ticket, usuario=None):
    """El solicitante confirma que quedó resuelto."""
    return _cerrar(ticket, EventoTicket.Tipo.CONFIRMADO,
                   "El solicitante confirmó la solución.", usuario)


@transaction.atomic
def cerrar_automaticamente(ticket):
    return _cerrar(
        ticket, EventoTicket.Tipo.CERRADO,
        f"Cerrado automáticamente: pasaron {DIAS_CIERRE_AUTOMATICO} días sin "
        "respuesta del solicitante.",
        automatico=True,
    )


@transaction.atomic
def reabrir(ticket, motivo, usuario=None):
    destino = E.ASIGNADO if ticket.tecnico_id else E.ABIERTO
    _validar(ticket, destino)
    ticket.estado = destino
    ticket.resuelto_en = None
    ticket.save()
    registrar_evento(ticket, EventoTicket.Tipo.REABIERTO, usuario,
                     motivo or "El solicitante indicó que no quedó resuelto.")
    _avisar(ticket, EventoTicket.Tipo.REABIERTO)
    return ticket


@transaction.atomic
def cancelar(ticket, motivo, usuario):
    _validar(ticket, E.CANCELADO)
    ticket.estado = E.CANCELADO
    ticket.cerrado_en = timezone.now()
    ticket.save()
    registrar_evento(ticket, EventoTicket.Tipo.CANCELADO, usuario, motivo)
    return ticket


def comentar(ticket, texto, usuario, publico=False):
    return registrar_evento(
        ticket, EventoTicket.Tipo.COMENTARIO, usuario, texto, publico
    )
