"""Gestión de tickets: bandeja, detalle, asignación y atención."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import tickets as flujo
from .forms import (
    AsignarTicketForm,
    AtencionTicketForm,
    IntervencionTicketForm,
    TextoTicketForm,
    TicketForm,
    validar_foto,
)
from .models import Equipo, FotoTicket, Ticket
from .permisos import puede, requiere_permiso
from .views import equipo_de_la_url, paginar


def puede_atender(usuario, ticket):
    """El técnico asignado, cualquier técnico si no hay asignado, o quien
    asigna tickets."""
    if puede(usuario, "tickets_asignar"):
        return True
    if not puede(usuario, "tickets_atender"):
        return False
    return ticket.tecnico_id in (None, usuario.pk)


@login_required
def tickets_lista(request):
    consulta = Ticket.objects.select_related("equipo", "tecnico")

    estado = request.GET.get("estado", "activos")
    tecnico = request.GET.get("tecnico", "")
    tipo_equipo = request.GET.get("tipo_equipo", "")
    prioridad = request.GET.get("prioridad", "")
    busqueda = request.GET.get("q", "").strip()
    origen = request.GET.get("origen", "")
    if origen in Ticket.Origen.values:
        consulta = consulta.filter(origen=origen)
    else:
        origen = ""

    if estado == "activos":
        consulta = consulta.filter(estado__in=Ticket.ACTIVOS)
    elif estado == "vencidos":
        consulta = consulta.filter(
            estado__in=[Ticket.Estado.ABIERTO, Ticket.Estado.ASIGNADO,
                        Ticket.Estado.EN_ATENCION],
            fecha_programada__lt=timezone.localdate(),
        )
    elif estado in Ticket.Estado.values:
        consulta = consulta.filter(estado=estado)
    else:
        estado = ""
    if tecnico == "mios":
        consulta = consulta.filter(tecnico=request.user)
    elif tecnico == "sin":
        consulta = consulta.filter(tecnico__isnull=True)
    else:
        tecnico = ""
    if tipo_equipo in Equipo.Tipo.values:
        consulta = consulta.filter(equipo__tipo=tipo_equipo)
    else:
        tipo_equipo = ""
    if prioridad in Ticket.Prioridad.values:
        consulta = consulta.filter(prioridad=prioridad)
    else:
        prioridad = ""
    if busqueda:
        consulta = consulta.filter(
            Q(numero__icontains=busqueda)
            | Q(solicitante_nombre__icontains=busqueda)
            | Q(solicitante_cedula__icontains=busqueda)
            | Q(equipo__placa__icontains=busqueda)
            | Q(descripcion__icontains=busqueda)
        )

    page_obj, parametros = paginar(request, consulta, 50)
    return render(request, "inventario/tickets_lista.html", {
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "total_resultados": page_obj.paginator.count,
        "estado_seleccionado": estado,
        "tecnico_seleccionado": tecnico,
        "tipo_equipo_seleccionado": tipo_equipo,
        "prioridad_seleccionada": prioridad,
        "busqueda": busqueda,
        "origen_seleccionado": origen,
        "origenes": Ticket.Origen.choices,
        "estados": Ticket.Estado.choices,
        "tipos_equipo": Equipo.Tipo.choices,
        "prioridades": Ticket.Prioridad.choices,
        "abiertos_sin_tecnico": Ticket.objects.filter(
            estado=Ticket.Estado.ABIERTO, tecnico__isnull=True
        ).count(),
        "conteos": {
            "activos": Ticket.objects.filter(estado__in=Ticket.ACTIVOS).count(),
            "mios": Ticket.objects.filter(estado__in=Ticket.ACTIVOS, tecnico=request.user).count(),
            "vencidos": Ticket.objects.filter(
                estado__in=[Ticket.Estado.ABIERTO, Ticket.Estado.ASIGNADO, Ticket.Estado.EN_ATENCION],
                fecha_programada__lt=timezone.localdate(),
            ).count(),
            "por_confirmar": Ticket.objects.filter(estado=Ticket.Estado.RESUELTO).count(),
        },
    })


@login_required
@requiere_permiso("tickets_crear")
def ticket_crear(request):
    formulario = TicketForm(
        request.POST or None,
        initial={"equipo": equipo_de_la_url(request)},
    )
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        ticket = flujo.crear(
            usuario=request.user, origen=Ticket.Origen.INTERNO, **datos
        )
        messages.success(request, f"Se creó el ticket {ticket.numero}.")
        return redirect("inventario:ticket_detalle", ticket.numero)
    return render(request, "inventario/ticket_form.html", {
        "formulario": formulario,
    })


@login_required
def ticket_detalle(request, numero):
    ticket = get_object_or_404(
        Ticket.objects.select_related("equipo", "tecnico", "funcionario"),
        numero=numero,
    )
    return render(request, "inventario/ticket_detalle.html", {
        "ticket": ticket,
        "eventos": ticket.eventos.select_related("usuario"),
        "fotos": ticket.fotos.all(),
        "intervenciones": ticket.intervenciones.select_related("equipo"),
        "form_asignar": AsignarTicketForm(initial={
            "tecnico": ticket.tecnico_id,
            "fecha_programada": ticket.fecha_programada,
            "franja": ticket.franja,
            "prioridad": ticket.prioridad,
        }),
        "form_texto": TextoTicketForm(),
        "puede_asignar": puede(request.user, "tickets_asignar")
        and flujo.puede_pasar(ticket, Ticket.Estado.ASIGNADO),
        "puede_atender": puede_atender(request.user, ticket)
        and flujo.puede_pasar(ticket, Ticket.Estado.RESUELTO),
        "puede_iniciar": puede_atender(request.user, ticket)
        and ticket.estado in (Ticket.Estado.ABIERTO, Ticket.Estado.ASIGNADO),
        "puede_cancelar": puede(request.user, "tickets_asignar")
        and flujo.puede_pasar(ticket, Ticket.Estado.CANCELADO),
        "puede_comentar": puede(request.user, "tickets_crear")
        or puede(request.user, "tickets_asignar"),
    })


@login_required
@requiere_permiso("tickets_asignar")
def ticket_asignar(request, numero):
    ticket = get_object_or_404(Ticket, numero=numero)
    formulario = AsignarTicketForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            flujo.asignar(
                ticket, formulario.cleaned_data["tecnico"], request.user,
                formulario.cleaned_data["fecha_programada"],
                formulario.cleaned_data["franja"],
                formulario.cleaned_data["prioridad"],
            )
            messages.success(request, "El ticket quedó asignado.")
        except flujo.TransicionInvalida as error:
            messages.error(request, str(error))
    elif request.method == "POST":
        messages.error(request, "Selecciona el técnico.")
    return redirect("inventario:ticket_detalle", numero)


@login_required
def ticket_iniciar(request, numero):
    ticket = get_object_or_404(Ticket, numero=numero)
    if request.method == "POST" and puede_atender(request.user, ticket):
        try:
            flujo.iniciar_atencion(ticket, request.user)
        except flujo.TransicionInvalida as error:
            messages.error(request, str(error))
    return redirect("inventario:ticket_detalle", numero)


@login_required
def ticket_atender(request, numero):
    ticket = get_object_or_404(
        Ticket.objects.select_related("equipo"), numero=numero
    )
    if not puede_atender(request.user, ticket):
        messages.error(request, "Tu rol no permite atender este ticket.")
        return redirect("inventario:ticket_detalle", numero)
    if not flujo.puede_pasar(ticket, Ticket.Estado.RESUELTO):
        messages.error(request, "Este ticket ya no se puede atender.")
        return redirect("inventario:ticket_detalle", numero)

    datos = request.POST if request.method == "POST" else None
    formulario = AtencionTicketForm(datos)
    intervencion = None
    if ticket.equipo_id:
        tipo = {
            Ticket.Tipo.PREVENTIVO: "PREVENTIVO",
            Ticket.Tipo.SOPORTE: "DIAGNOSTICO",
        }.get(ticket.tipo, "CORRECTIVO")
        intervencion = IntervencionTicketForm(datos, equipo=ticket.equipo, initial={
            "fecha_intervencion": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "tipo": tipo,
            "tecnico_responsable": request.user.get_full_name() or request.user.username,
            "motivo": ticket.descripcion,
        })

    fotos = request.FILES.getlist("fotos")
    errores_fotos = []
    for foto in fotos:
        try:
            validar_foto(foto)
        except ValidationError as error:
            errores_fotos.extend(error.messages)

    if datos is not None and formulario.is_valid() and not errores_fotos and (
        intervencion is None or intervencion.is_valid()
    ):
        with transaction.atomic():
            registro = None
            if intervencion is not None:
                registro = intervencion.save(commit=False)
                registro.equipo = ticket.equipo
                registro.registrado_por = request.user
                registro.save()
            for foto in fotos:
                FotoTicket.objects.create(
                    ticket=ticket, archivo=foto, subido_por=request.user
                )
            flujo.resolver(
                ticket, request.user,
                formulario.cleaned_data["solucion"],
                formulario.cleaned_data["firma"],
                formulario.cleaned_data["firma_nombre"],
                registro,
            )
        messages.success(request, f"El ticket {ticket.numero} quedó resuelto.")
        return redirect("inventario:ticket_detalle", numero)

    return render(request, "inventario/ticket_atencion.html", {
        "ticket": ticket,
        "formulario": formulario,
        "intervencion": intervencion,
        "errores_fotos": errores_fotos,
        "equipo_fijo": True,
    })


@login_required
@requiere_permiso("tickets_asignar")
def ticket_cancelar(request, numero):
    ticket = get_object_or_404(Ticket, numero=numero)
    formulario = TextoTicketForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            flujo.cancelar(ticket, formulario.cleaned_data["texto"], request.user)
            messages.success(request, "El ticket quedó cancelado.")
        except flujo.TransicionInvalida as error:
            messages.error(request, str(error))
    elif request.method == "POST":
        messages.error(request, "Indica el motivo de la cancelación.")
    return redirect("inventario:ticket_detalle", numero)


@login_required
def ticket_comentar(request, numero):
    ticket = get_object_or_404(Ticket, numero=numero)
    permitido = puede(request.user, "tickets_crear") or puede(
        request.user, "tickets_asignar"
    )
    formulario = TextoTicketForm(request.POST or None)
    if request.method == "POST" and permitido and formulario.is_valid():
        flujo.comentar(
            ticket, formulario.cleaned_data["texto"], request.user,
            formulario.cleaned_data["publico"],
        )
    return redirect("inventario:ticket_detalle", numero)


@login_required
def ticket_foto(request, pk):
    foto = get_object_or_404(FotoTicket, pk=pk)
    try:
        return FileResponse(foto.archivo.open("rb"))
    except FileNotFoundError:
        raise Http404("La foto ya no existe.")


def horas(delta):
    return round(delta.total_seconds() / 3600, 1)


@login_required
def tickets_indicadores(request):
    from collections import defaultdict
    from datetime import timedelta

    hoy = timezone.localdate()
    desde = timezone.now() - timedelta(days=90)
    activos = Ticket.objects.filter(estado__in=Ticket.ACTIVOS)

    por_estado = [
        (etiqueta, activos.filter(estado=valor).count())
        for valor, etiqueta in Ticket.Estado.choices
        if valor in Ticket.ACTIVOS
    ]
    atrasados = activos.exclude(estado=Ticket.Estado.RESUELTO).filter(
        fecha_programada__lt=hoy
    ).count()

    # Tiempos de respuesta: solo casos reales (no importados ni registros
    # internos que se cierran al momento).
    resueltos = Ticket.objects.filter(
        resuelto_en__gte=desde,
        origen__in=[Ticket.Origen.FORMULARIO, Ticket.Origen.PREVENTIVO],
    ).select_related("tecnico", "equipo")

    por_tecnico = defaultdict(lambda: {"activos": 0, "resueltos": 0, "tiempos": []})
    for t in activos.select_related("tecnico"):
        nombre = (t.tecnico.get_full_name() or t.tecnico.username) if t.tecnico else "Sin asignar"
        por_tecnico[nombre]["activos"] += 1
    por_tipo = defaultdict(lambda: {"activos": 0, "resueltos": 0, "tiempos": []})
    for t in activos.select_related("equipo"):
        por_tipo[t.equipo.get_tipo_display() if t.equipo else "Sin equipo"]["activos"] += 1
    for t in resueltos:
        nombre = (t.tecnico.get_full_name() or t.tecnico.username) if t.tecnico else "Sin asignar"
        tipo = t.equipo.get_tipo_display() if t.equipo else "Sin equipo"
        for grupo in (por_tecnico[nombre], por_tipo[tipo]):
            grupo["resueltos"] += 1
            grupo["tiempos"].append(t.tiempo_respuesta)

    def filas(grupos):
        resultado = []
        for nombre, g in sorted(grupos.items()):
            promedio = (
                horas(sum(g["tiempos"], timedelta()) / len(g["tiempos"]))
                if g["tiempos"] else None
            )
            resultado.append((nombre, g["activos"], g["resueltos"], promedio))
        return resultado

    meses = []
    for atras in range(5, -1, -1):
        indice = hoy.year * 12 + hoy.month - 1 - atras
        mes = hoy.replace(year=indice // 12, month=indice % 12 + 1, day=1)
        siguiente = (mes + timedelta(days=32)).replace(day=1)
        no_importados = Ticket.objects.exclude(origen=Ticket.Origen.IMPORTADO)
        meses.append((
            mes,
            no_importados.filter(creado_en__date__gte=mes, creado_en__date__lt=siguiente).count(),
            no_importados.filter(resuelto_en__date__gte=mes, resuelto_en__date__lt=siguiente).count(),
        ))

    return render(request, "inventario/tickets_indicadores.html", {
        "por_estado": por_estado,
        "atrasados": atrasados,
        "por_tecnico": filas(por_tecnico),
        "por_tipo": filas(por_tipo),
        "tablas": [("Por técnico", filas(por_tecnico)), ("Por tipo de equipo", filas(por_tipo))],
        "meses": meses,
    })
