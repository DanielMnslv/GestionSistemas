"""Módulo de Usuarios: qué equipos tiene cada persona y su paz y salvo.

Una persona tiene a cargo un equipo cuando:
- hay una entrega vigente (AsignacionEquipo) a su nombre o a su cédula;
- el equipo la tiene como responsable (dato importado del Sheet), o
- es la coordinadora del radio en una entrega vigente (AsignacionRadio).
"""
from collections import Counter

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AsignacionEquipo,
    AsignacionRadio,
    Equipo,
    Funcionario,
    ItemRetiro,
    Radio,
    RetiroFuncionario,
)


def _ced(valor):
    """Cédula sin espacios en los extremos."""
    return (valor or "").strip()


def equipos_a_cargo(funcionario):
    """Lista de {equipo, asignacion_equipo, asignacion_radio, desde} sin repetir equipos."""
    cedula = _ced(funcionario.cedula)
    vistos = {}

    entregas = (
        AsignacionEquipo.objects.filter(estado=AsignacionEquipo.Estado.ASIGNADO)
        .filter(Q(funcionario=funcionario) | Q(cedula_recibe=cedula))
        .select_related("equipo")
    )
    for a in entregas:
        if a.equipo.activo:
            vistos[a.equipo_id] = {
                "equipo": a.equipo, "asignacion_equipo": a,
                "asignacion_radio": None, "desde": a.fecha_entrega,
            }

    if cedula:
        responsables = Equipo.objects.filter(
            activo=True, responsable_cedula=cedula
        ).exclude(tipo=Equipo.Tipo.RADIO)
        vigentes = {
            a.equipo_id: a for a in AsignacionEquipo.objects.filter(
                estado=AsignacionEquipo.Estado.ASIGNADO,
                equipo__in=responsables,
            )
        }
        for e in responsables:
            a = vigentes.get(e.pk)
            if a and _ced(a.cedula_recibe) and _ced(a.cedula_recibe) != cedula:
                continue  # La entrega vigente es de otra persona: manda la entrega.
            vistos.setdefault(e.pk, {
                "equipo": e, "asignacion_equipo": a,
                "asignacion_radio": None, "desde": a.fecha_entrega if a else None,
            })

        radios = (
            AsignacionRadio.objects.filter(
                estado=AsignacionRadio.Estado.ASIGNADO, cedula_funcionario=cedula,
                radio__activo=True, radio__equipo__isnull=False,
            ).select_related("radio__equipo")
        )
        for a in radios:
            vistos.setdefault(a.radio.equipo_id, {
                "equipo": a.radio.equipo, "asignacion_equipo": None,
                "asignacion_radio": a, "desde": a.fecha_entrega,
            })

    return sorted(vistos.values(), key=lambda d: (d["equipo"].tipo, d["equipo"].placa))


def conteos_por_cedula():
    """{cédula: Counter(tipo)} de los equipos a cargo de todas las personas."""
    por_equipo = {}
    for equipo_id, tipo, ced, fid in AsignacionEquipo.objects.filter(
        estado=AsignacionEquipo.Estado.ASIGNADO, equipo__activo=True,
    ).values_list("equipo_id", "equipo__tipo", "cedula_recibe", "funcionario__cedula"):
        if _ced(fid) or _ced(ced):
            por_equipo[equipo_id] = (tipo, _ced(fid) or _ced(ced))
    for equipo_id, tipo, ced in Equipo.objects.filter(activo=True).exclude(
        responsable_cedula=""
    ).exclude(tipo=Equipo.Tipo.RADIO).values_list("id", "tipo", "responsable_cedula"):
        por_equipo.setdefault(equipo_id, (tipo, _ced(ced)))
    for equipo_id, ced in AsignacionRadio.objects.filter(
        estado=AsignacionRadio.Estado.ASIGNADO, radio__activo=True,
        radio__equipo__isnull=False,
    ).values_list("radio__equipo_id", "cedula_funcionario"):
        por_equipo.setdefault(equipo_id, (Equipo.Tipo.RADIO, _ced(ced)))

    conteos = {}
    for tipo, ced in por_equipo.values():
        if ced:
            conteos.setdefault(ced, Counter())[tipo] += 1
    return conteos


def retiro_en_proceso(funcionario):
    """Retiro en proceso del funcionario, o None."""
    return funcionario.retiros.filter(
        estado=RetiroFuncionario.Estado.EN_PROCESO
    ).first()


def sincronizar_items(retiro):
    """Agrega al retiro los equipos que la persona tenga a cargo y aún no estén."""
    if retiro.estado != RetiroFuncionario.Estado.EN_PROCESO:
        return 0
    existentes = set(retiro.items.values_list("equipo_id", flat=True))
    nuevos = [
        ItemRetiro(
            retiro=retiro, equipo=d["equipo"],
            asignacion_equipo=d["asignacion_equipo"],
            asignacion_radio=d["asignacion_radio"],
        )
        for d in equipos_a_cargo(retiro.funcionario)
        if d["equipo"].pk not in existentes
    ]
    ItemRetiro.objects.bulk_create(nuevos)
    return len(nuevos)


@transaction.atomic
def iniciar_retiro(funcionario, motivo, fecha_retiro, observaciones, usuario):
    """Crea el retiro y su lista de equipos por validar."""
    retiro = RetiroFuncionario.objects.create(
        funcionario=funcionario, motivo=motivo, fecha_retiro=fecha_retiro,
        observaciones=observaciones, creado_por=usuario,
    )
    sincronizar_items(retiro)
    return retiro


def _cerrar_entrega_equipo(asignacion, usuario, nota):
    """Marca como devuelta la entrega de un equipo al validar el retiro."""
    asignacion.estado = AsignacionEquipo.Estado.DEVUELTO
    asignacion.fecha_devolucion = timezone.now()
    asignacion.recibido_por = usuario
    asignacion.observaciones_devolucion = nota
    asignacion.save()


def _cerrar_entrega_radio(asignacion, usuario, nota):
    """Marca como devuelta la entrega de un radio al validar el retiro."""
    asignacion.estado = AsignacionRadio.Estado.DEVUELTO
    asignacion.fecha_devolucion = timezone.now()
    asignacion.recibido_por = usuario
    asignacion.observaciones_devolucion = nota
    asignacion.save(update_fields=[
        "estado", "fecha_devolucion", "recibido_por",
        "observaciones_devolucion", "actualizado_en",
    ])


def _entrega_vigente_radio(item):
    """Entrega de radio del ítem si sigue vigente, o None."""
    a = item.asignacion_radio
    if a and a.estado == AsignacionRadio.Estado.ASIGNADO:
        return a
    return None


@transaction.atomic
def validar_item(item, resultado, usuario, observaciones="", reasignado_a=None):
    """Registra lo que pasó con el equipo y actualiza su entrega y responsable."""
    R = ItemRetiro.Resultado
    item = ItemRetiro.objects.select_for_update().select_related(
        "retiro__funcionario", "equipo"
    ).get(pk=item.pk)
    if item.retiro.estado != RetiroFuncionario.Estado.EN_PROCESO:
        raise ValueError("El retiro ya está cerrado.")
    if item.resultado != R.PENDIENTE:
        raise ValueError("Este equipo ya fue validado.")
    if resultado == R.REASIGNADO and (
        reasignado_a is None or reasignado_a.pk == item.retiro.funcionario_id
    ):
        raise ValueError("Elige a la persona que recibe el equipo.")
    if resultado not in R.values or resultado == R.PENDIENTE:
        raise ValueError("Resultado no válido.")

    persona = item.retiro.funcionario
    equipo = Equipo.objects.select_for_update().get(pk=item.equipo_id)
    nota = f"Retiro de {persona.nombre_completo}: {R(resultado).label.lower()}."
    if observaciones:
        nota += f" {observaciones}"

    radio = Radio.objects.filter(equipo=equipo).first()
    entrega_eq = AsignacionEquipo.objects.select_for_update().filter(
        equipo=equipo, estado=AsignacionEquipo.Estado.ASIGNADO
    ).first()
    ced_entrega = _ced(entrega_eq.cedula_recibe) if entrega_eq else ""
    if entrega_eq and (
        (entrega_eq.funcionario_id and entrega_eq.funcionario_id != persona.pk)
        or (ced_entrega and ced_entrega != _ced(persona.cedula))
    ):
        raise ValueError(
            f"{equipo.placa} tiene una entrega vigente a {entrega_eq.nombre_recibe}; "
            "revísala en la ficha del equipo."
        )
    entrega_radio = _entrega_vigente_radio(item)
    if entrega_radio:
        entrega_radio = AsignacionRadio.objects.select_for_update().get(pk=entrega_radio.pk)

    if resultado in (R.DEVUELTO, R.DEVUELTO_DANO, R.REASIGNADO):
        if entrega_eq:
            _cerrar_entrega_equipo(entrega_eq, usuario, nota)
        if entrega_radio:
            _cerrar_entrega_radio(entrega_radio, usuario, nota)

        if resultado == R.REASIGNADO and radio is not None and entrega_radio:
            # El radio sigue en el mismo puesto; cambia el coordinador a cargo.
            nueva = AsignacionRadio.objects.create(
                radio=radio, coordinador_zona=reasignado_a.nombre_completo,
                cedula_funcionario=reasignado_a.cedula,
                cliente_asignado=entrega_radio.cliente_asignado,
                puesto_asignado=entrega_radio.puesto_asignado,
                puesto=entrega_radio.puesto, entregado_por=usuario,
                observaciones_entrega=nota,
                estado_radio_entrega=entrega_radio.estado_radio_entrega,
                estado_base_entrega=entrega_radio.estado_base_entrega,
                estado_cargador_entrega=entrega_radio.estado_cargador_entrega,
                estado_antena_entrega=entrega_radio.estado_antena_entrega,
                estado_baterias_entrega=entrega_radio.estado_baterias_entrega,
            )
            radio.coordinador_zona = nueva.coordinador_zona
            radio.cedula_funcionario = nueva.cedula_funcionario
            radio.save()
        elif resultado == R.REASIGNADO:
            AsignacionEquipo.objects.create(
                equipo=equipo, funcionario=reasignado_a,
                nombre_recibe=reasignado_a.nombre_completo,
                cedula_recibe=reasignado_a.cedula,
                area=entrega_eq.area if entrega_eq else "",
                entregado_por=usuario, observaciones_entrega=nota,
            )
            equipo.responsable_nombre = reasignado_a.nombre_completo
            equipo.responsable_cedula = reasignado_a.cedula
            equipo.save(update_fields=[
                "responsable_nombre", "responsable_cedula", "actualizado_en",
            ])
        elif radio is not None:
            if radio.cedula_funcionario == persona.cedula:
                radio.coordinador_zona = ""
                radio.cedula_funcionario = ""
                radio.cliente_asignado = ""
                radio.puesto_asignado = ""
                radio.save()
        else:
            equipo.responsable_nombre = ""
            equipo.responsable_cedula = ""
            equipo.ubicacion = ""
            equipo.save(update_fields=[
                "responsable_nombre", "responsable_cedula", "ubicacion",
                "actualizado_en",
            ])

    if resultado in (R.DEVUELTO_DANO, R.FALTANTE):
        motivo = f"{R(resultado).label} en el retiro de {persona.nombre_completo}"[:255]
        if radio is not None:
            radio.requiere_revision = True
            radio.motivo_revision = motivo
            radio.save()
        else:
            Equipo.objects.filter(pk=equipo.pk).update(
                requiere_revision=True, motivo_revision=motivo,
            )

    item.resultado = resultado
    item.reasignado_a = reasignado_a if resultado == R.REASIGNADO else None
    item.observaciones = observaciones
    item.validado_por = usuario
    item.validado_en = timezone.now()
    item.save()
    return item


def resumen_retiro(retiro):
    """Cuenta los equipos del retiro: total, pendientes y con novedad, y si ya
    se puede emitir el paz y salvo.
    """
    items = list(retiro.items.all())
    total = len(items)
    pendientes = sum(1 for i in items if i.resultado == ItemRetiro.Resultado.PENDIENTE)
    novedades = sum(
        1 for i in items
        if i.resultado in (ItemRetiro.Resultado.DEVUELTO_DANO, ItemRetiro.Resultado.FALTANTE)
    )
    validados = total - pendientes
    return {
        "total": total, "pendientes": pendientes, "novedades": novedades,
        "validados": validados,
        "pct": round(validados * 100 / total) if total else 100,
        "puede_emitir": (
            retiro.estado == RetiroFuncionario.Estado.EN_PROCESO
            and pendientes == 0 and novedades == 0
        ),
    }


@transaction.atomic
def emitir_paz_y_salvo(retiro, usuario):
    """Emite el paz y salvo y deja inactivo al funcionario.

    Lanza ``ValueError`` si quedan equipos sin validar, dañados o faltantes.
    """
    retiro = RetiroFuncionario.objects.select_for_update().get(pk=retiro.pk)
    sincronizar_items(retiro)
    if not resumen_retiro(retiro)["puede_emitir"]:
        raise ValueError(
            "Aún hay equipos sin validar, con daño o faltantes."
        )
    retiro.estado = RetiroFuncionario.Estado.PAZ_Y_SALVO
    retiro.cerrado_por = usuario
    retiro.cerrado_en = timezone.now()
    retiro.save()
    Funcionario.objects.filter(pk=retiro.funcionario_id).update(activo=False)
    return retiro


@transaction.atomic
def cancelar_retiro(retiro, usuario):
    """Para cuando la persona no se retira. Lo ya validado no se deshace."""
    retiro = RetiroFuncionario.objects.select_for_update().get(pk=retiro.pk)
    if retiro.estado != RetiroFuncionario.Estado.EN_PROCESO:
        raise ValueError("El retiro ya está cerrado.")
    retiro.estado = RetiroFuncionario.Estado.CANCELADO
    retiro.cerrado_por = usuario
    retiro.cerrado_en = timezone.now()
    retiro.save()
    return retiro
