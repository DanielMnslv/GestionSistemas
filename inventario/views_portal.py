"""Portal "Mi soporte" para los funcionarios (rol Solicitante).

Cada funcionario entra con su cédula y su contraseña y, sin ver el resto de
JANO, puede:
- ver los equipos que tiene a cargo y el estado de su mantenimiento,
- agendar el mantenimiento de un equipo (reemplaza a Calendly),
- pedir soporte al área de sistemas (reemplaza al formulario de Google),
- seguir sus casos.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from . import agenda, personas
from . import tickets as flujo
from .forms import FOTOS_MAXIMAS, SoporteForm, validar_foto
from .models import FotoTicket, Funcionario, Ticket


def funcionario_de(usuario):
    """El funcionario de la cuenta: el usuario es su cédula."""
    if not usuario.is_authenticated:
        return None
    return Funcionario.objects.filter(cedula=usuario.get_username(), activo=True).first()


def _equipos(funcionario):
    """Equipos a cargo del funcionario, con su estado de mantenimiento."""
    from .estado_mantenimiento import equipos_con_estado

    equipos = [d["equipo"] for d in personas.equipos_a_cargo(funcionario)]
    if not equipos:
        return []
    con_estado = {e.pk: e for e in equipos_con_estado(
        type(equipos[0]).objects.filter(pk__in=[e.pk for e in equipos])
    )}
    return [con_estado.get(e.pk, e) for e in equipos]


def _sin_funcionario(request):
    """Página de aviso cuando la cuenta no está enlazada a un funcionario."""
    return render(request, "portal/sin_funcionario.html", status=403)


def _fotos(request):
    """Lee las fotos adjuntas y devuelve (fotos, errores) según cantidad y tamaño máximos."""
    fotos = request.FILES.getlist("fotos")
    errores = []
    if len(fotos) > FOTOS_MAXIMAS:
        errores.append(f"Puedes adjuntar máximo {FOTOS_MAXIMAS} fotos.")
    for foto in fotos[:FOTOS_MAXIMAS]:
        try:
            validar_foto(foto)
        except ValidationError as error:
            errores.extend(error.messages)
    return fotos[:FOTOS_MAXIMAS], errores


def _crear(request, funcionario, fotos, **datos):
    """Crea la solicitud del funcionario con sus fotos en una sola transacción."""
    with transaction.atomic():
        ticket = flujo.crear(
            origen=Ticket.Origen.FORMULARIO,
            funcionario=funcionario,
            solicitante_nombre=funcionario.nombre_completo,
            solicitante_cedula=funcionario.cedula,
            **datos,
        )
        for foto in fotos:
            FotoTicket.objects.create(ticket=ticket, archivo=foto, descripcion="Enviada por el solicitante")
    return ticket


@login_required
def mi_soporte(request):
    """Inicio del portal Mi soporte: casos del funcionario y sus equipos."""
    funcionario = funcionario_de(request.user)
    if funcionario is None:
        return _sin_funcionario(request)
    casos = Ticket.objects.filter(
        Q(funcionario=funcionario) | Q(solicitante_cedula=funcionario.cedula)
    ).select_related("equipo", "tecnico").order_by("-creado_en")[:30]
    activos_por_equipo = set(
        Ticket.objects.filter(
            estado__in=[Ticket.Estado.ABIERTO, Ticket.Estado.ASIGNADO, Ticket.Estado.EN_ATENCION],
            tipo=Ticket.Tipo.PREVENTIVO, equipo__isnull=False,
        ).values_list("equipo_id", flat=True)
    )
    return render(request, "portal/inicio.html", {
        "funcionario": funcionario,
        "equipos": _equipos(funcionario),
        "casos": casos,
        "agendados": activos_por_equipo,
    })


@login_required
def mi_soporte_nueva(request):
    """Formulario para que el funcionario pida soporte sobre uno de sus equipos."""
    funcionario = funcionario_de(request.user)
    if funcionario is None:
        return _sin_funcionario(request)
    equipos = [d["equipo"] for d in personas.equipos_a_cargo(funcionario)]
    formulario = SoporteForm(request.POST or None, funcionario=funcionario, equipos=equipos,
                             initial={"equipo": request.GET.get("equipo", "")})
    errores_fotos = []
    if request.method == "POST":
        fotos, errores_fotos = _fotos(request)
        if formulario.is_valid() and not errores_fotos:
            fecha, franja = formulario.fecha_visita, formulario.franja_visita
            if fecha and not agenda.hay_cupo(fecha, franja):
                formulario.add_error("visita", "Esa franja se acaba de llenar. Elige otra.")
            else:
                datos = formulario.cleaned_data
                ticket = _crear(
                    request, funcionario, fotos,
                    tipo=Ticket.Tipo.SOPORTE if datos["categoria"] == Ticket.Categoria.SOFTWARE else Ticket.Tipo.CORRECTIVO,
                    categoria=datos["categoria"], equipo=formulario.equipo,
                    descripcion=datos["descripcion"], ubicacion=datos["ubicacion"],
                    solicitante_correo=datos["correo"], solicitante_telefono=datos["telefono"],
                    fecha_programada=fecha, franja=franja,
                )
                messages.success(request, f"Recibimos tu solicitud. Tu número de caso es {ticket.numero}.")
                return redirect("portal:inicio")
    return render(request, "portal/solicitud.html", {
        "funcionario": funcionario, "formulario": formulario, "errores_fotos": errores_fotos,
    })


class AgendarMantenimientoForm(forms.Form):
    """Solicitud de visita de mantenimiento desde el portal."""
    visita = forms.ChoiceField(label="Día y franja de la visita")
    ubicacion = forms.CharField(label="¿Dónde está el equipo? (sede, oficina o puesto)", max_length=200)
    correo = forms.EmailField(label="Correo para avisarte")
    telefono = forms.CharField(label="Teléfono o celular", max_length=50, required=False)
    observaciones = forms.CharField(
        label="Observaciones (opcional)", required=False, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        """Ofrece los días y franjas con cupo libre en la agenda."""
        super().__init__(*args, **kwargs)
        self.fields["visita"].choices = [("", "Elige un día y una franja")] + [
            (c["valor"], f"{c['etiqueta']} ({c['libres']} cupo{'s' if c['libres'] != 1 else ''})")
            for c in agenda.cupos_disponibles()
        ]

    def clean_visita(self):
        """Verifica que la franja elegida exista y siga teniendo cupo."""
        fecha, franja = agenda.leer_valor(self.cleaned_data["visita"])
        if fecha is None:
            raise forms.ValidationError("Elige el día y la franja.")
        if not agenda.hay_cupo(fecha, franja):
            raise forms.ValidationError("Esa franja se acaba de llenar. Elige otra.")
        self.fecha, self.franja = fecha, franja
        return self.cleaned_data["visita"]


@login_required
def mi_soporte_agendar(request, equipo_id):
    """El funcionario agenda una visita de mantenimiento para uno de sus equipos."""
    funcionario = funcionario_de(request.user)
    if funcionario is None:
        return _sin_funcionario(request)
    equipos = {e.pk: e for e in (d["equipo"] for d in personas.equipos_a_cargo(funcionario))}
    equipo = equipos.get(equipo_id)
    if equipo is None:
        messages.error(request, "Ese equipo no está a tu cargo.")
        return redirect("portal:inicio")
    formulario = AgendarMantenimientoForm(request.POST or None, initial={
        "correo": funcionario.correo, "ubicacion": equipo.ubicacion,
    })
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        texto = f"Mantenimiento preventivo agendado por {funcionario.nombre_completo}."
        if datos["observaciones"]:
            texto += f"\n{datos['observaciones']}"
        ticket = _crear(
            request, funcionario, [],
            tipo=Ticket.Tipo.PREVENTIVO, categoria=Ticket.Categoria.MANTENIMIENTO,
            equipo=equipo, descripcion=texto, ubicacion=datos["ubicacion"],
            solicitante_correo=datos["correo"], solicitante_telefono=datos["telefono"],
            fecha_programada=formulario.fecha, franja=formulario.franja,
        )
        messages.success(
            request,
            f"Quedó agendado el mantenimiento de {equipo.placa} para el "
            f"{agenda.nombre_dia(ticket.fecha_programada)}, {ticket.get_franja_display()}. Caso {ticket.numero}.",
        )
        return redirect("portal:inicio")
    return render(request, "portal/agendar.html", {
        "funcionario": funcionario, "equipo": equipo, "formulario": formulario,
    })
