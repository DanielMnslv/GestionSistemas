"""Pantalla «Calidad de datos»: pendientes que hacen que el inventario no cuadre.

Cada pestaña lista un tipo de pendiente con la acción para corregirlo:

- ``entregas``: equipos con responsable escrito y sin entrega → entrega firmada.
- ``firmas``: entregas sin firma en JANO → firmar la entrega existente.
- ``puestos``: radios entregados sin puesto del catálogo → vincular el puesto.
- ``correos``: funcionarios sin correo → escribirlo o cargar un archivo.
- ``estados``: equipos sin estado operativo → completarlo con el mantenimiento.

Solo la ve el encargado de inventario (acción ``equipos``). La lógica de
cada consulta está en ``calidad.py``.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import calidad
from .forms import CLAUSULA_EQUIPOS, CorreoFuncionarioForm, FirmaEntregaForm
from .models import AsignacionEquipo, Cliente, Funcionario, Puesto
from .permisos import puede, requiere_permiso

SECCIONES = [
    ("entregas", "Equipos sin entrega"),
    ("firmas", "Entregas sin firma"),
    ("puestos", "Radios sin puesto"),
    ("correos", "Funcionarios sin correo"),
    ("estados", "Equipos sin estado"),
]


def _volver(seccion):
    """Redirige a la pestaña indicada de la pantalla."""
    return redirect(reverse("inventario:calidad_datos") + f"?seccion={seccion}")


@login_required
@requiere_permiso("equipos")
def calidad_datos(request):
    """Pantalla principal: pestañas con los pendientes y su acción."""
    seccion = request.GET.get("seccion", "entregas")
    if seccion not in dict(SECCIONES):
        seccion = "entregas"

    contexto = {
        "seccion": seccion,
        "secciones": SECCIONES,
        "conteos": calidad.resumen(),
    }
    if seccion == "entregas":
        equipos = list(calidad.equipos_sin_entrega())
        for equipo in equipos:
            equipo.funcionario_encontrado = calidad.funcionario_de(equipo)
            equipo.dice_baja = calidad.parece_baja(equipo.responsable_nombre)
        # Primero los que parecen de baja: se resuelven sin el funcionario.
        equipos.sort(key=lambda e: not e.dice_baja)
        contexto["filas"] = equipos
    elif seccion == "firmas":
        contexto["filas"] = calidad.entregas_sin_firma()
    elif seccion == "puestos":
        contexto["filas"] = calidad.grupos_radios_sin_puesto()
    elif seccion == "correos":
        pagina = Paginator(calidad.funcionarios_sin_correo(), 50).get_page(
            request.GET.get("page")
        )
        contexto.update({
            "page_obj": pagina,
            "parametros": "seccion=correos",
            "filas": pagina.object_list,
            "formulario_archivo": CorreoFuncionarioForm(),
            "puede_personas": puede(request.user, "personas"),
        })
    elif seccion == "estados":
        sin_estado = calidad.equipos_sin_estado().distinct()
        contexto.update({
            "filas": sin_estado.order_by("tipo", "placa")[:200],
            "completables": sin_estado.filter(
                mantenimientos__estado_final__in=["OPERATIVO", "NO_OPERATIVO"]
            ).distinct().count(),
        })
    return render(request, "inventario/calidad_datos.html", contexto)


@login_required
@requiere_permiso("entregas")
def entrega_firmar(request, asignacion_id):
    """Firma en JANO de una entrega vigente que no tiene firma dibujada."""
    asignacion = get_object_or_404(
        AsignacionEquipo.objects.select_related("equipo", "funcionario"),
        pk=asignacion_id, estado=AsignacionEquipo.Estado.ASIGNADO,
    )
    if asignacion.firma:
        messages.info(request, "Esta entrega ya está firmada.")
        return redirect("inventario:equipo_acta", asignacion.pk)

    formulario = FirmaEntregaForm(request.POST or None, instance=asignacion)
    if request.method == "POST" and formulario.is_valid():
        formulario.save()
        messages.success(
            request,
            f"La entrega de {asignacion.equipo.placa} quedó firmada en JANO.",
        )
        return redirect("inventario:equipo_acta", asignacion.pk)

    return render(request, "inventario/entrega_firmar.html", {
        "asignacion": asignacion,
        "equipo": asignacion.equipo,
        "formulario": formulario,
        "clausula": CLAUSULA_EQUIPOS,
    })


@login_required
@requiere_permiso("radios")
def vincular_puesto(request):
    """Elige el puesto del catálogo para un grupo de radios escrito a mano.

    GET muestra el grupo (por ``clave``) con el cliente sugerido y sus
    puestos ordenados por parecido; POST vincula todas sus entregas.
    """
    clave = request.POST.get("clave") or request.GET.get("clave", "")
    entregas = calidad.entregas_del_grupo(clave)
    if not entregas:
        messages.info(request, "Ese grupo ya no tiene radios por vincular.")
        return _volver("puestos")

    if request.method == "POST":
        puesto = Puesto.objects.filter(
            pk=request.POST.get("puesto") or 0, activo=True
        ).select_related("cliente").first()
        if puesto is None:
            messages.error(request, "Elige un puesto de la lista.")
        else:
            total = calidad.vincular_puesto(clave, puesto)
            messages.success(
                request,
                f"{total} radio{'s' if total != 1 else ''} quedaron en el puesto "
                f"{puesto} de {puesto.cliente}.",
            )
            return _volver("puestos")

    texto_cliente = entregas[0].cliente_asignado
    texto_puesto = entregas[0].puesto_asignado
    cliente = Cliente.objects.filter(
        pk=request.GET.get("cliente") or 0, activo=True
    ).first() or calidad.sugerir_cliente(texto_cliente)
    return render(request, "inventario/calidad_vincular_puesto.html", {
        "clave": clave,
        "texto_cliente": texto_cliente,
        "texto_puesto": texto_puesto,
        "entregas": entregas,
        "cliente": cliente,
        "clientes": Cliente.objects.filter(activo=True).order_by("nombre"),
        "puestos": calidad.puestos_ordenados(cliente, texto_puesto) if cliente else [],
    })


@login_required
@requiere_permiso("personas")
def guardar_correos(request):
    """Guarda los correos escritos en la lista o los de un archivo. Solo POST."""
    if request.method != "POST":
        return _volver("correos")

    if request.FILES.get("archivo"):
        formulario = CorreoFuncionarioForm(request.POST, request.FILES)
        if formulario.is_valid():
            try:
                pares = calidad.leer_archivo_correos(formulario.cleaned_data["archivo"])
            except ValueError as error:
                messages.error(request, str(error))
                return _volver("correos")
            with transaction.atomic():
                resumen = calidad.aplicar_correos(pares)
            _avisar_resumen(request, resumen)
        return _volver("correos")

    # Correos escritos en la lista: campos «correo_<id del funcionario>».
    pares = []
    for nombre, valor in request.POST.items():
        if nombre.startswith("correo_") and valor.strip():
            funcionario = Funcionario.objects.filter(pk=nombre[7:] or 0).first()
            if funcionario:
                pares.append((funcionario.cedula, valor))
    with transaction.atomic():
        resumen = calidad.aplicar_correos(pares)
    _avisar_resumen(request, resumen)
    return _volver("correos")


def _avisar_resumen(request, resumen):
    """Mensajes con el resultado de una carga de correos."""
    if resumen["actualizados"]:
        messages.success(request, f"Se guardaron {resumen['actualizados']} correos.")
    if resumen["invalidos"]:
        messages.error(
            request,
            "Correos no válidos para las cédulas: " + ", ".join(resumen["invalidos"][:20]),
        )
    if resumen["no_encontrados"]:
        messages.warning(
            request,
            f"{len(resumen['no_encontrados'])} cédulas no son de funcionarios activos: "
            + ", ".join(resumen["no_encontrados"][:20]),
        )
    if resumen["ya_tenian"]:
        messages.info(
            request,
            f"{resumen['ya_tenian']} funcionarios ya tenían correo y no se cambiaron.",
        )
    if not any([resumen["actualizados"], resumen["invalidos"], resumen["no_encontrados"],
                resumen["ya_tenian"]]):
        messages.info(request, "No había correos para guardar.")


@login_required
@requiere_permiso("equipos")
def completar_estados(request):
    """Completa el estado operativo con el último mantenimiento. Solo POST."""
    if request.method == "POST":
        with transaction.atomic():
            total = calidad.completar_estados()
        messages.success(
            request, f"Se completó el estado operativo de {total} equipos."
        )
    return _volver("estados")
