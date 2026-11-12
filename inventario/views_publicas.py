"""Páginas públicas de soporte (sin inicio de sesión).

El funcionario pide soporte con su cédula y consulta su caso con un enlace
secreto (token) que recibe por correo.
"""
from datetime import timedelta

from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import tickets as flujo
from .forms import ReabrirForm, SoporteForm
from .models import Ticket

MAXIMO_POR_CEDULA_HORA = 5
MAXIMO_POR_IP_HORA = 15


def ip_de(request):
    return request.META.get("REMOTE_ADDR", "")


def supera_limite(request, cedula):
    """True si la cédula o la dirección IP ya pidieron demasiados casos en la
    última hora."""
    hace_una_hora = timezone.now() - timedelta(hours=1)
    por_cedula = Ticket.objects.filter(
        origen=Ticket.Origen.FORMULARIO, solicitante_cedula=cedula,
        creado_en__gte=hace_una_hora,
    ).count()
    clave = f"soporte-ip-{ip_de(request)}"
    return por_cedula >= MAXIMO_POR_CEDULA_HORA or cache.get(clave, 0) >= MAXIMO_POR_IP_HORA


def contar_ip(request):
    clave = f"soporte-ip-{ip_de(request)}"
    cache.set(clave, cache.get(clave, 0) + 1, 3600)


def soporte_formulario(request):
    formulario = SoporteForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        if supera_limite(request, datos["cedula"]):
            formulario.add_error(
                None,
                "Ya recibimos varias solicitudes en la última hora. "
                "Intenta más tarde o comunícate con el área de TI.",
            )
        else:
            funcionario = formulario.funcionario
            categoria = datos["categoria"]
            ticket = flujo.crear(
                origen=Ticket.Origen.FORMULARIO,
                tipo=(
                    Ticket.Tipo.SOPORTE
                    if categoria == Ticket.Categoria.SOFTWARE
                    else Ticket.Tipo.CORRECTIVO
                ),
                categoria=categoria,
                equipo=formulario.equipo,
                descripcion=datos["descripcion"],
                funcionario=funcionario,
                solicitante_nombre=funcionario.nombre_completo,
                solicitante_cedula=funcionario.cedula,
                solicitante_correo=datos["correo"],
                solicitante_telefono=datos["telefono"],
                ubicacion=datos["ubicacion"],
            )
            contar_ip(request)
            messages.success(
                request,
                f"Recibimos tu solicitud. Tu número de caso es {ticket.numero}.",
            )
            return redirect("soporte_caso", ticket.token)

    return render(request, "publico/soporte_formulario.html", {
        "formulario": formulario,
    })


def soporte_caso(request, token):
    ticket = get_object_or_404(
        Ticket.objects.select_related("equipo", "tecnico"), token=token
    )
    reabrir = ReabrirForm(request.POST or None)

    if request.method == "POST" and ticket.estado == Ticket.Estado.RESUELTO:
        accion = request.POST.get("accion")
        if accion == "confirmar":
            flujo.confirmar(ticket)
            messages.success(request, "Gracias. El caso quedó cerrado.")
            return redirect("soporte_caso", token)
        if accion == "reabrir" and reabrir.is_valid():
            flujo.reabrir(ticket, reabrir.cleaned_data["motivo"])
            messages.success(request, "Reabrimos el caso; el área de TI lo revisará.")
            return redirect("soporte_caso", token)

    return render(request, "publico/soporte_caso.html", {
        "ticket": ticket,
        "eventos": ticket.eventos.filter(publico=True),
        "reabrir": reabrir,
        "dias_cierre": flujo.DIAS_CIERRE_AUTOMATICO,
    })
