"""Páginas públicas de soporte (sin inicio de sesión).

El funcionario pide soporte con su cédula y consulta su caso con un enlace
secreto (token) que recibe por correo.
"""
from datetime import timedelta

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import agenda, personas
from . import tickets as flujo
from .forms import (
    FOTOS_MAXIMAS, CedulaSoporteForm, ReabrirForm, SoporteForm, validar_foto,
)
from .models import FotoTicket, Ticket

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


MAXIMO_CONSULTAS_IP_HORA = 30


def consultas_excedidas(request):
    """Evita que alguien pruebe cédulas una tras otra."""
    clave = f"soporte-cedula-ip-{ip_de(request)}"
    veces = cache.get(clave, 0)
    cache.set(clave, veces + 1, 3600)
    return veces >= MAXIMO_CONSULTAS_IP_HORA


def _paso_equipo(request, cedula_form, datos=None, archivos=None):
    funcionario = cedula_form.funcionario
    equipos = [d["equipo"] for d in personas.equipos_a_cargo(funcionario)]
    formulario = SoporteForm(datos, funcionario=funcionario, equipos=equipos)
    return funcionario, formulario


def soporte_formulario(request):
    """Paso 1: la cédula. Paso 2: qué falla y en cuál de sus equipos."""
    paso = request.POST.get("paso", "1") if request.method == "POST" else "1"

    if request.method == "POST" and paso == "1":
        cedula_form = CedulaSoporteForm(request.POST)
        if consultas_excedidas(request):
            cedula_form.add_error(None, "Demasiadas consultas desde este equipo. Intenta en una hora.")
        elif cedula_form.is_valid():
            funcionario, formulario = _paso_equipo(request, cedula_form)
            return render(request, "publico/soporte_formulario.html", {
                "paso": 2, "funcionario": funcionario, "formulario": formulario,
                "cedula": cedula_form.cleaned_data["cedula"],
            })
        return render(request, "publico/soporte_formulario.html", {"paso": 1, "formulario": cedula_form})

    if request.method == "POST" and paso == "2":
        cedula_form = CedulaSoporteForm({"cedula": request.POST.get("cedula", "")})
        if not cedula_form.is_valid():
            return render(request, "publico/soporte_formulario.html", {"paso": 1, "formulario": cedula_form})
        cedula = cedula_form.cleaned_data["cedula"]
        funcionario, formulario = _paso_equipo(request, cedula_form, request.POST)
        fotos = request.FILES.getlist("fotos")
        errores_fotos = []
        if len(fotos) > FOTOS_MAXIMAS:
            errores_fotos.append(f"Puedes adjuntar máximo {FOTOS_MAXIMAS} fotos.")
        for foto in fotos[:FOTOS_MAXIMAS]:
            try:
                validar_foto(foto)
            except ValidationError as error:
                errores_fotos.extend(error.messages)

        if formulario.is_valid() and not errores_fotos:
            if supera_limite(request, cedula):
                formulario.add_error(
                    None,
                    "Ya recibimos varias solicitudes tuyas en la última hora. "
                    "Intenta más tarde o comunícate con el área de TI.",
                )
            else:
                datos = formulario.cleaned_data
                categoria = datos["categoria"]
                fecha, franja = formulario.fecha_visita, formulario.franja_visita
                if fecha and not agenda.hay_cupo(fecha, franja):
                    formulario = SoporteForm(request.POST, funcionario=funcionario, equipos=formulario.equipos.values())
                    formulario.is_valid()
                    formulario.add_error("visita", "Esa franja se acaba de llenar. Elige otra.")
                    return render(request, "publico/soporte_formulario.html", {
                        "paso": 2, "funcionario": funcionario, "formulario": formulario, "cedula": cedula,
                    })
                with transaction.atomic():
                    ticket = flujo.crear(
                        fecha_programada=fecha,
                        franja=franja,
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
                    for foto in fotos:
                        FotoTicket.objects.create(ticket=ticket, archivo=foto, descripcion="Enviada por el solicitante")
                contar_ip(request)
                messages.success(
                    request,
                    f"Recibimos tu solicitud. Tu número de caso es {ticket.numero}.",
                )
                return redirect("soporte_caso", ticket.token)

        return render(request, "publico/soporte_formulario.html", {
            "paso": 2, "funcionario": funcionario, "formulario": formulario,
            "cedula": cedula, "errores_fotos": errores_fotos,
        })

    return render(request, "publico/soporte_formulario.html", {
        "paso": 1, "formulario": CedulaSoporteForm(),
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
