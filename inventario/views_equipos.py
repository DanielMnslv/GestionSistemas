"""Inventario general de equipos de TI (todo lo que no es radio).

Los radios tienen sus propias pantallas (views.py); aquí se redirige a
ellas cuando el equipo es un radio.
"""
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .estados import tono_estado
from .estado_mantenimiento import (
    ESTADOS, PROXIMO, VENCIDO, VIGENTE, equipos_con_estado,
    hoy_colombia,
)
from .forms import (
    CLAUSULA_CONFIDENCIALIDAD,
    CLAUSULA_EQUIPOS,
    FORMULARIOS_DETALLE,
    AsignacionEquipoForm,
    CambioGPSForm,
    EquipoForm,
    RadioBajaForm,
    RadioForm,
    RenovacionAntivirusForm,
    VerificacionPoliticaForm,
)
from .models import (
    AsignacionEquipo,
    AsignacionRadio,
    DetalleGPS,
    Equipo,
    DetalleComputador,
    MantenimientoEquipo,
    Radio,
    RenovacionAntivirus,
    VerificacionPolitica,
    Vigilante,
)
from .permisos import puede, requiere_permiso
from .orden import orden_placa
from .radio_componentes import destinos_radio_para_transferencia
from .views import filas_por_pagina, paginar, pide_modal


def detalle_de(equipo):
    """El registro de detalle del equipo según su tipo, si existe."""
    formulario = FORMULARIOS_DETALLE.get(equipo.tipo)
    if formulario is None:
        return None
    nombre = formulario._meta.model._meta.get_field(
        "equipo"
    ).remote_field.related_name
    return getattr(equipo, nombre, None)


def formulario_detalle(equipo, data=None, usuario=None):
    clase = FORMULARIOS_DETALLE.get(equipo.tipo)
    if clase is None:
        return None
    instancia = detalle_de(equipo) or clase._meta.model(equipo=equipo)
    extra = {}
    if hasattr(clase, "LICENCIAS"):
        extra["ver_licencias"] = puede(usuario, "licencias")
    return clase(data, instance=instancia, prefix="detalle", **extra)


def campos_detalle(equipo, usuario, incluir_vacios=False):
    """[(campo, etiqueta, valor)] del detalle, con las licencias ocultas si
    el usuario no tiene permiso."""
    detalle = detalle_de(equipo)
    clase = FORMULARIOS_DETALLE.get(equipo.tipo)
    if clase is None:
        return []
    if detalle is None:
        if not incluir_vacios:
            return []
        # Sin registro de detalle todavía: se muestran los campos como pendientes.
        detalle = clase._meta.model(equipo=equipo)
    etiquetas = getattr(clase.Meta, "labels", {})
    licencias = getattr(clase, "LICENCIAS", [])
    ver_licencias = puede(usuario, "licencias")
    filas = []
    for campo in detalle._meta.fields:
        if campo.name in ("id", "equipo"):
            continue
        valor = getattr(detalle, campo.name)
        if campo.name == "componentes":
            valor = ", ".join(
                f"{c.get('nombre')}: {c.get('cantidad')} ({c.get('estado')})"
                for c in valor or []
            )
        if valor in ("", None):
            if not incluir_vacios:
                continue
            valor = ""
        elif campo.name in licencias and not ver_licencias:
            valor = "Restringido"
        etiqueta = etiquetas.get(campo.name) or campo.verbose_name.capitalize()
        filas.append((campo.name, etiqueta, valor))
    return filas


def filas_detalle(equipo, usuario, incluir_vacios=False):
    """[(etiqueta, valor)] del detalle (lo que usa la ficha de la página)."""
    return [
        (etiqueta, valor)
        for _, etiqueta, valor in campos_detalle(equipo, usuario, incluir_vacios)
    ]


# Cómo se agrupan en la ventana las características de cada tipo de equipo.
GRUPOS_DETALLE = {
    "COMPUTADOR": [
        ("Hardware", ["clase", "procesador", "velocidad_procesador", "tipo_disco",
                      "capacidad_disco", "tipo_ram", "capacidad_ram"]),
        ("Periféricos", ["mouse", "teclado", "regulador", "parlantes", "webcam"]),
        ("Equipos conectados", ["@monitor", "@monitor2", "@ups", "@telefono_ip"]),
        ("Sistema y licencias", ["sistema_operativo", "licencia_so", "antivirus",
                                 "licencia_antivirus", "vencimiento_antivirus",
                                 "office", "licencia_office"]),
        ("Software", ["software_licenciado", "software_libre"]),
        ("Red y comunicaciones", ["mac_ethernet", "mac_wifi", "ip_ethernet",
                                  "ip_wifi", "imei", "linea_celular"]),
    ],
    "GPS": [
        ("Línea", ["imei", "linea", "operador", "plataforma"]),
        ("Vehículo", ["placa_vehiculo", "nombre_vehiculo", "fecha_asignacion"]),
    ],
}
GRUPOS_DETALLE["TABLETA"] = GRUPOS_DETALLE["COMPUTADOR"]

# Pares modelo + serial que se muestran en una sola fila: (clave, etiqueta, campo modelo, campo serial).
PARES_DETALLE = [
    ("@monitor", "Monitor", "monitor_modelo", "monitor_serial"),
    ("@monitor2", "Monitor 2", "monitor2_modelo", "monitor2_serial"),
    ("@ups", "UPS", "ups_modelo", "ups_serial"),
    ("@telefono_ip", "Teléfono IP", "telefono_ip_modelo", "telefono_ip_serial"),
]


def agrupar_detalle(equipo, usuario):
    """[(título, [(etiqueta, valor)])] con las características agrupadas."""
    campos = campos_detalle(equipo, usuario, incluir_vacios=True)
    grupos = GRUPOS_DETALLE.get(equipo.tipo)
    if not grupos:
        return [("Características", [(e, v) for _, e, v in campos])]
    por_campo = {c: (e, v) for c, e, v in campos}
    usados = set()
    if equipo.tipo in ("COMPUTADOR", "TABLETA"):
        for clave, etiqueta, modelo, serial in PARES_DETALLE:
            if modelo not in por_campo and serial not in por_campo:
                continue
            m = por_campo.get(modelo, ("", ""))[1]
            n = por_campo.get(serial, ("", ""))[1]
            partes = [str(m)] if m else []
            if n:
                partes.append(f"Serial {n}")
            por_campo[clave] = (etiqueta, " · ".join(partes))
            usados.update((modelo, serial))
    secciones = []
    for titulo, nombres in grupos:
        filas = [por_campo[n] for n in nombres if n in por_campo]
        usados.update(n for n in nombres if n in por_campo)
        if filas:
            secciones.append((titulo, filas))
    resto = [(e, v) for c, e, v in campos if c not in usados]
    if resto:
        secciones.append(("Otros datos", resto))
    return secciones


def repartir_columnas(secciones):
    """Reparte las secciones en columnas de altura parecida: 3 columnas si
    son pocas secciones (más anchas es mejor con 4 o más: 2 columnas)."""
    if not secciones:
        return []
    n = min(3, len(secciones)) if len(secciones) <= 3 else 2

    def peso(filas):
        # Las listas de más de 6 filas se muestran en dos columnas.
        total = 2
        cortas = 0
        for _, v in filas:
            texto = str(v or "")
            if len(texto) <= 24:
                cortas += 1
            else:
                total += 2 + len(texto) // 60
        total += (cortas + 1) // 2 if len(filas) > 6 else cortas
        return total

    pesos = [peso(filas) for _, filas in secciones]
    columnas = [[] for _ in range(n)]
    alturas = [0] * n
    # Las más altas primero, cada una en la columna más baja; luego se
    # recupera el orden original dentro de cada columna.
    for idx in sorted(range(len(secciones)), key=lambda k: -pesos[k]):
        k = alturas.index(min(alturas))
        columnas[k].append(idx)
        alturas[k] += pesos[idx]
    return [
        [secciones[idx] for idx in sorted(col)] for col in columnas if col
    ]


_tono_estado = tono_estado


def ficha_modal(equipo, usuario):
    """Datos de la ventana de ficha: lo más importante arriba (destacados),
    luego secciones agrupadas y, en los radios, el estado de cada componente."""
    radio = getattr(equipo, "radio", None) if equipo.tipo == "RADIO" else None
    responsable = equipo.responsable_nombre
    if not responsable and radio is not None:
        # La cédula del radio es la del coordinador de zona; el nombre debe
        # salir de la misma fuente para que ambos datos coincidan.
        responsable = radio.coordinador_zona

    def limpiar(filas):
        # Se conservan los vacíos para mostrarlos con el marcador uniforme de la ficha.
        return list(filas)

    secciones = []
    componentes = []
    if radio is not None:
        destacados = limpiar([
            ("Serial", equipo.serial or radio.serial),
            ("Cliente asignado", radio.cliente_asignado),
            ("Puesto asignado", radio.puesto_asignado),
            ("Coordinador de zona", radio.coordinador_zona),
        ])
        secciones.append(("Identificación", limpiar([
            ("Código físico", radio.codigo_fisico),
            ("Marca", equipo.marca or radio.marca),
            ("Modelo", equipo.modelo or radio.modelo),
            ("Propiedad", equipo.propiedad),
            ("Tipo de frecuencia", radio.tipo_frecuencia),
            ("Modalidad de servicio", radio.modalidad_servicio),
        ])))
        secciones.append(("Responsable y ubicación", limpiar([
            ("Responsable", responsable),
            ("Cédula del responsable",
             equipo.responsable_cedula or radio.cedula_funcionario),
            ("Ubicación", equipo.ubicacion),
        ])))
        secciones.append(("Estado y mantenimiento", limpiar([
            ("Estado del radio", radio.estado_radio),
            ("Mantenimiento", radio.mantenimiento),
            ("Fecha de baja", radio.fecha_baja),
            ("Motivo de baja", radio.motivo_baja),
        ])))
        ver_licencias = puede(usuario, "licencias")
        licencia = radio.licencia_software
        if licencia and not ver_licencias:
            licencia = "Restringido"
        secciones.append(("Software y licencia", limpiar([
            ("Software de programación", radio.software_programacion),
            ("Versión", radio.version_software),
            ("Tipo de licencia", radio.tipo_licencia),
            ("Licencia", licencia),
            ("Fecha de compra", radio.fecha_compra or equipo.fecha_compra),
        ])))

        def fila(nombre, presente, estado, tiene_estado=True, detalle=""):
            """Una fila por componente: si lo tiene (Sí/No) y su estado."""
            faltan = 0
            nota = ""
            sin_estado_real = (estado or "").strip().lower() in (
                "no tiene", "no aplica", "n/a", "ninguno",
            )
            if nombre == "Radio":
                tiene = ("Sí", "green")  # el radio es el equipo mismo
            elif presente is None:
                tiene = ("-", "amber")
                faltan += 1
            elif presente:
                tiene = (detalle or "Sí", "green")
            else:
                tiene = ("No", "gray")

            est = ("No aplica", "gray")  # nunca se deja vacío: se ve por qué
            if tiene_estado:
                if presente is False and (not estado or sin_estado_real):
                    est = ("No aplica", "gray")  # no lo tiene: no hay estado
                elif estado:
                    est = (estado, _tono_estado(estado))
                    if presente and sin_estado_real:
                        est = (estado, "amber")
                        nota = (
                            f"{nombre}: está marcado como presente, pero su "
                            f"estado dice «{estado}»."
                        )
                    elif presente is False:
                        est = (estado, "amber")
                        nota = (
                            f"{nombre}: está marcado como no presente, pero "
                            f"tiene estado «{estado}»."
                        )
                else:
                    est = ("Sin dato", "amber")
                    faltan += 1
            # Para la ficha en tarjetas: color, ícono y texto de cada componente.
            if nombre == "Radio":
                clase, icono, texto = "ok", "✓", "Equipo principal"
            elif presente is None:
                clase, icono, texto = "q", "?", "Sin dato"
            elif presente:
                clase, icono = "ok", "✓"
                texto = tiene[0] if detalle else "Sí tiene"
            else:
                clase, icono, texto = "no", "✕", "No tiene"
            componentes.append({
                "nombre": nombre, "tiene": tiene, "estado": est,
                "faltan": faltan, "nota": nota,
                "clase": clase, "icono": icono, "texto": texto,
            })

        fila("Radio", None, radio.estado_radio)
        fila("Base", radio.base, radio.estado_base)
        fila("Cargador", radio.cargador, radio.estado_cargador)
        fila("Antena", radio.antena, radio.estado_antena)
        baterias = [b for b in (radio.bateria_1, radio.bateria_2) if b is not None]
        cantidad = sum(1 for b in baterias if b)
        fila(
            "Baterías",
            (cantidad > 0) if baterias else None,
            radio.estado_baterias,
            detalle=f"Sí · {cantidad}",
        )
        fila("Perilla de encendido", radio.perilla_encendido,
             radio.estado_perilla_encendido)
        fila("Perilla de frecuencia", radio.perilla_frecuencia,
             radio.estado_perilla_frecuencia)
        fila("Clip", radio.clip, radio.estado_clip)
    else:
        destacados = limpiar([
            ("Serial", equipo.serial),
            ("Responsable", responsable),
            ("Ubicación", equipo.ubicacion),
            ("Propiedad", equipo.propiedad),
        ])
        secciones.append(("General", limpiar([
            ("Fecha de compra", equipo.fecha_compra),
            ("Estado operativo", equipo.get_estado_operativo_display()),
            ("Cédula del responsable", equipo.responsable_cedula),
        ])))
        secciones += agrupar_detalle(equipo, usuario)

    observaciones = equipo.observaciones or (radio.observaciones if radio else "")
    avisos = []
    if equipo.requiere_revision:
        avisos.append(("amber", "Requiere revisión", equipo.motivo_revision))
    if not equipo.activo:
        avisos.append(("gray", "Dado de baja", equipo.motivo_baja))
    secciones = [(t, f) for t, f in secciones if f]
    # Datos de baja: en un equipo activo se muestran (con su nota) pero no cuentan.
    datos_de_baja = ("Fecha de baja", "Motivo de baja")

    def cuenta(filas):
        return [
            (e, v) for e, v in filas
            if not (equipo.activo and e in datos_de_baja)
        ]

    contados = cuenta(destacados) + [
        fv for _, filas in secciones for fv in cuenta(filas)
    ]
    vacios = sum(1 for _, v in contados if v in ("", None))
    comp_faltan = sum(1 for c in componentes if c["faltan"])
    faltantes = vacios + comp_faltan + (0 if observaciones else 1)
    total = len(contados) + len(componentes) + 1
    cliente_puesto = ""
    if radio is not None:
        cliente_puesto = " · ".join(
            p for p in (radio.cliente_asignado, radio.puesto_asignado) if p
        )
    return {
        "destacados": destacados,
        "secciones": secciones,
        "columnas": repartir_columnas(secciones),
        "componentes": componentes,
        "componentes_con": sum(1 for c in componentes if c["clase"] == "ok"),
        "componentes_mitades": [
            componentes[: (len(componentes) + 1) // 2],
            componentes[(len(componentes) + 1) // 2:],
        ],
        "notas_componentes": [c["nota"] for c in componentes if c["nota"]],
        "avisos": avisos,
        "observaciones": observaciones,
        "faltantes": faltantes,
        "total": total,
        "completos": total - faltantes,
        "porcentaje": round((total - faltantes) * 100 / total) if total else 100,
        "datos_de_baja": datos_de_baja,
        "responsable": responsable,
        "cliente_puesto": cliente_puesto,
    }


def entregas_ficha(equipo, limite=30):
    """Entregas del equipo ya armadas para mostrarlas dentro del panel de la
    lista (sin salir de la página). None si el tipo no tiene entregas."""
    if equipo.tipo == "RADIO":
        return None
    filas = []
    for a in equipo.asignaciones.order_by("-fecha_entrega", "-id")[:limite]:
        filas.append({
            "fecha": a.fecha_entrega,
            "recibe": a.nombre_recibe or "",
            "cedula": a.cedula_recibe or "",
            "detalle": a.area or "",
            "activa": a.estado == "ASIGNADO",
            "devolucion": a.fecha_devolucion,
            "acta": reverse("inventario:equipo_acta", args=[a.pk]),
        })
    return filas


def q_busqueda_equipos(texto):
    """Placa, serial, marca, modelo, responsable, ubicación o placa del vehículo."""
    return (
        Q(placa__icontains=texto)
        | Q(serial__icontains=texto)
        | Q(marca__icontains=texto)
        | Q(modelo__icontains=texto)
        | Q(responsable_nombre__icontains=texto)
        | Q(responsable_cedula__icontains=texto)
        | Q(ubicacion__icontains=texto)
        | Q(gps__placa_vehiculo__icontains=texto)
    )


@login_required
def buscar_json(request):
    """Buscador global de la barra superior: equipos, clientes y vigilantes."""
    from .models import Cliente

    texto = request.GET.get("q", "").strip()
    if len(texto) < 2:
        return JsonResponse({"q": texto, "grupos": []})

    etiquetas = dict(Equipo.Tipo.choices)
    equipos = (
        Equipo.objects.select_related("gps")
        .filter(q_busqueda_equipos(texto))
        .order_by("-activo", "placa")[:8]
    )
    clientes = Cliente.objects.filter(
        Q(nombre__icontains=texto) | Q(nit__icontains=texto)
    ).order_by("-activo", "nombre")[:4]
    vigilantes = Vigilante.objects.filter(
        Q(nombre_completo__icontains=texto) | Q(cedula__icontains=texto)
    ).order_by("nombre_completo")[:4]

    grupos = []
    if equipos:
        grupos.append({"titulo": "Equipos", "items": [{
            "titulo": e.placa,
            "detalle": " · ".join(x for x in [
                etiquetas.get(e.tipo, e.tipo),
                " ".join(x for x in [e.marca, e.modelo] if x),
                e.responsable_nombre,
            ] if x),
            "etiqueta": "" if e.activo else "De baja",
            "url": reverse("inventario:equipo_detalle", args=[e.placa]),
        } for e in equipos]})
    if clientes:
        grupos.append({"titulo": "Clientes", "items": [{
            "titulo": c.nombre,
            "detalle": f"NIT {c.nit}" if c.nit else "",
            "etiqueta": "" if c.activo else "Inactivo",
            "url": reverse("inventario:cliente_detalle", args=[c.pk]),
        } for c in clientes]})
    if vigilantes:
        grupos.append({"titulo": "Vigilantes", "items": [{
            "titulo": v.nombre_completo,
            "detalle": f"C.C. {v.cedula}",
            "etiqueta": "",
            "url": reverse("inventario:vigilantes_lista") + "?" + urlencode({"q": v.cedula}),
        } for v in vigilantes]})
    return JsonResponse({
        "q": texto,
        "grupos": grupos,
        "todos": reverse("inventario:equipos_lista") + "?" + urlencode({"q": texto, "estado": "todos"}),
    })


ETIQUETAS_FILTROS = {
    "estado": ("Inventario", {"baja": "Dados de baja", "": "Activos y de baja"}),
    "estado_operativo": ("Estado", {"OPERATIVO": "Operativos", "NO_OPERATIVO": "No operativos"}),
    "mantenimiento": ("Mantenimiento", None),
    "disponibilidad": ("Ubicación", {"en_inventario": "En bodega", "entregado": "Entregados"}),
    "asignacion": ("Responsable", {"asignado": "Con responsable", "sin_asignar": "Sin responsable"}),
    "revision": ("Revisión", {"si": "Por revisar", "no": "Sin revisión pendiente"}),
    "accesorios": ("Accesorios", {"completos": "Completos", "incompletos": "Incompletos"}),
    "datos": ("Datos", {"completos": "Completos", "pendientes": "Con datos pendientes"}),
}


def _url_lista(seleccion, **cambios):
    """URL de la lista con la selección actual y los cambios indicados."""
    valores = {**seleccion, **cambios}
    params = {}
    for clave, valor in valores.items():
        if clave == "estado":
            if valor != "activos":
                params["estado"] = valor or "todos"
        elif valor:
            params[clave] = valor
    url = reverse("inventario:equipos_lista")
    return url + ("?" + urlencode(params) if params else "")


def _chips_filtros(seleccion):
    """Filtros activos, cada uno con el enlace que lo quita."""
    chips = []
    if seleccion["q"]:
        chips.append({
            "texto": "Búsqueda: " + seleccion["q"],
            "quitar": _url_lista(seleccion, q=""),
        })
    etiquetas_mant = dict(ESTADOS)
    for clave, (nombre, opciones) in ETIQUETAS_FILTROS.items():
        valor = seleccion[clave]
        if clave == "estado":
            if valor == "activos":
                continue
            texto = opciones.get(valor, valor)
            quitar = _url_lista(seleccion, estado="activos")
        else:
            if not valor:
                continue
            fuente = etiquetas_mant if opciones is None else opciones
            texto = fuente.get(valor, valor)
            quitar = _url_lista(seleccion, **{clave: ""})
        chips.append({"texto": nombre + ": " + texto, "quitar": quitar})
    return chips


def _exportar_equipos(equipos, seleccion):
    """Excel con exactamente los equipos que muestra la lista filtrada."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    etiquetas_tipo = dict(Equipo.Tipo.choices)
    etiquetas_mant = dict(ESTADOS)
    hoy = hoy_colombia()
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Equipos"
    hoja.append([
        "Placa", "Tipo", "Marca", "Modelo", "Serial", "Responsable", "Cédula",
        "Ubicación", "Propiedad", "Estado", "Inventario", "Requiere revisión",
        "Mantenimiento", "Último mantenimiento", "Próximo vencimiento",
    ])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="2E3092")
    filas = sorted(
        equipos_con_estado(equipos.select_related("radio")),
        key=lambda x: (x.tipo, x.placa),
    )
    for e in filas:
        radio = getattr(e, "radio", None) if e.tipo == "RADIO" else None
        if radio is not None and radio.estado_radio:
            estado = radio.estado_radio
        elif e.estado_operativo:
            estado = e.get_estado_operativo_display()
        else:
            estado = ""
        hoja.append([
            e.placa, etiquetas_tipo.get(e.tipo, e.tipo), e.marca, e.modelo, e.serial,
            e.responsable_nombre, e.responsable_cedula, e.ubicacion, e.propiedad,
            estado, "Activo" if e.activo else "De baja",
            "Sí" if e.requiere_revision else "No",
            etiquetas_mant.get(e.estado_mantenimiento, ""),
            e.ultimo_fecha, e.proximo_mantenimiento,
        ])
        fila = hoja[hoja.max_row]
        for celda in fila:
            if isinstance(celda.value, str):
                celda.data_type = "s"
        fila[13].number_format = "DD/MM/YYYY"
        fila[14].number_format = "DD/MM/YYYY"
    anchos = [14, 13, 16, 22, 20, 30, 14, 28, 14, 16, 11, 12, 20, 14, 14]
    for indice, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    respuesta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    respuesta["Content-Disposition"] = f'attachment; filename="equipos_{hoy:%Y%m%d}.xlsx"'
    libro.save(respuesta)
    return respuesta


@login_required
def equipos_lista(request):
    equipos = Equipo.objects.select_related("radio", "gps")

    busqueda = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "").strip()
    estado = request.GET.get("estado", "activos").strip()

    if busqueda:
        equipos = equipos.filter(q_busqueda_equipos(busqueda))
    if tipo not in Equipo.Tipo.values:
        tipo = ""
    if estado == "baja":
        equipos = equipos.filter(activo=False)
    elif estado == "activos":
        equipos = equipos.filter(activo=True)
    else:
        estado = ""

    # Estado operativo, con la misma regla del dashboard: en los radios manda
    # su estado; en los demás, el estado operativo del equipo.
    estado_operativo = request.GET.get("estado_operativo", "").strip()
    sin_estado_radio = (
        Q(radio__isnull=True) | Q(radio__estado_radio="")
        | Q(radio__estado_radio__isnull=True)
    )
    if estado_operativo == Equipo.EstadoOperativo.OPERATIVO:
        equipos = equipos.filter(
            Q(radio__estado_radio=Radio.ESTADO_OPERATIVO)
            | (sin_estado_radio & Q(estado_operativo=Equipo.EstadoOperativo.OPERATIVO))
        )
    elif estado_operativo == Equipo.EstadoOperativo.NO_OPERATIVO:
        equipos = equipos.filter(
            Q(radio__estado_radio__in=[Radio.ESTADO_DANADO, Radio.ESTADO_BAJA])
            | (sin_estado_radio & Q(estado_operativo=Equipo.EstadoOperativo.NO_OPERATIVO))
        )
    else:
        estado_operativo = ""

    # Filtros del desplegable de la búsqueda.
    asignacion = request.GET.get("asignacion", "").strip()
    revision = request.GET.get("revision", "").strip()
    accesorios = request.GET.get("accesorios", "").strip()
    datos = request.GET.get("datos", "").strip()

    # "Asignado" = tiene responsable (el mismo dato que muestra la tabla).
    con_responsable = (
        Q(responsable_nombre__gt="") | Q(radio__coordinador_zona__gt="")
    )
    if asignacion == "asignado":
        equipos = equipos.filter(con_responsable)
    elif asignacion == "sin_asignar":
        equipos = equipos.exclude(con_responsable)
    else:
        asignacion = ""

    # En inventario = sin entrega vigente (disponible); entregado = tiene una entrega activa.
    en_uso = (
        Exists(AsignacionEquipo.objects.filter(
            equipo=OuterRef("pk"), estado=AsignacionEquipo.Estado.ASIGNADO,
        ))
        | Exists(AsignacionRadio.objects.filter(
            radio__equipo=OuterRef("pk"), estado=AsignacionRadio.Estado.ASIGNADO,
        ))
    )
    disponibilidad = request.GET.get("disponibilidad", "").strip()
    if disponibilidad == "en_inventario":
        equipos = equipos.filter(~en_uso)
    elif disponibilidad == "entregado":
        equipos = equipos.filter(en_uso)
    else:
        disponibilidad = ""

    if revision == "si":
        equipos = equipos.filter(requiere_revision=True)
    elif revision == "no":
        equipos = equipos.filter(requiere_revision=False)
    else:
        revision = ""

    # Accesorios (solo radios): los 8 marcados como "Sí" = completos.
    todos_los_accesorios = Q()
    for campo in (
        "bateria_1", "bateria_2", "perilla_encendido", "perilla_frecuencia",
        "antena", "clip", "base", "cargador",
    ):
        todos_los_accesorios &= Q(**{f"radio__{campo}": True})
    if accesorios == "completos":
        equipos = equipos.filter(tipo="RADIO").filter(todos_los_accesorios)
    elif accesorios == "incompletos":
        equipos = equipos.filter(tipo="RADIO").exclude(todos_los_accesorios)
    else:
        accesorios = ""

    # Datos completos: se calcula con la misma cuenta de la ficha (columna "Datos").
    if datos in ("completos", "pendientes"):
        quiere_completos = datos == "completos"
        ids = [
            e.pk for e in equipos
            if (ficha_modal(e, request.user)["faltantes"] == 0) == quiere_completos
        ]
        equipos = equipos.filter(pk__in=ids)
    else:
        datos = ""

    # Estado del mantenimiento preventivo (el mismo semáforo del panel).
    mantenimiento = request.GET.get("mantenimiento", "").strip()
    if mantenimiento in dict(ESTADOS):
        ids = [
            e.pk for e in equipos_con_estado(equipos)
            if e.estado_mantenimiento == mantenimiento
        ]
        equipos = equipos.filter(pk__in=ids)
    else:
        mantenimiento = ""

    # Pestañas por tipo: cuentan con los demás filtros aplicados.
    conteo_tipos = dict(
        equipos.order_by().values_list("tipo").annotate(n=Count("id"))
    )
    if tipo:
        equipos = equipos.filter(tipo=tipo)

    n_filtros = sum([
        bool(tipo), estado != "activos", bool(asignacion), bool(disponibilidad),
        bool(revision), bool(estado_operativo), bool(mantenimiento),
        bool(accesorios), bool(datos),
    ])

    seleccion = {
        "q": busqueda, "tipo": tipo, "estado": estado,
        "estado_operativo": estado_operativo, "mantenimiento": mantenimiento,
        "asignacion": asignacion, "disponibilidad": disponibilidad,
        "revision": revision, "accesorios": accesorios, "datos": datos,
    }

    if request.GET.get("exportar") == "xlsx":
        return _exportar_equipos(equipos, seleccion)

    filtros_activos = _chips_filtros(seleccion)
    total_sin_tipo = sum(conteo_tipos.values())
    pestanas = [{
        "valor": "", "etiqueta": "Todos", "total": total_sin_tipo,
        "url": _url_lista(seleccion, tipo=""), "activo": not tipo,
    }] + [{
        "valor": valor, "etiqueta": etiqueta, "total": conteo_tipos.get(valor, 0),
        "url": _url_lista(seleccion, tipo=valor), "activo": tipo == valor,
    } for valor, etiqueta in Equipo.Tipo.choices if conteo_tipos.get(valor) or tipo == valor]

    try:
        por_pagina = max(3, min(50, int(request.GET.get("pp", 8))))
    except ValueError:
        por_pagina = 8
    page_obj, parametros = paginar(
        request, orden_placa(equipos, "tipo"), por_pagina
    )
    radios_equipo = {
        equipo.pk: getattr(equipo, "radio", None)
        for equipo in page_obj.object_list
        if equipo.tipo == "RADIO"
    }
    radios_equipo = {
        equipo_id: radio for equipo_id, radio in radios_equipo.items()
        if radio is not None
    }
    ids_radios_en_pagina = list(radios_equipo)
    entregas_radio_por_equipo = dict(
        AsignacionRadio.objects.filter(
            radio__equipo_id__in=ids_radios_en_pagina
        )
        .values("radio__equipo_id")
        .annotate(total=Count("pk"))
        .values_list("radio__equipo_id", "total")
    )
    mantenimientos_radio_por_equipo = dict(
        MantenimientoEquipo.objects.filter(
            equipo_id__in=ids_radios_en_pagina
        )
        .values("equipo_id")
        .annotate(total=Count("pk"))
        .values_list("equipo_id", "total")
    )
    radios_activos = None
    if puede(request.user, "radios") and radios_equipo:
        radios_activos = list(
            Radio.objects.filter(activo=True).order_by("placa", "id")
        )
    for equipo in page_obj.object_list:
        equipo.ficha = ficha_modal(equipo, request.user)
        equipo.entregas = entregas_ficha(equipo)
        if equipo.pk in radios_equipo:
            equipo.entregas_radio_count = entregas_radio_por_equipo.get(
                equipo.pk, 0
            )
            equipo.mantenimientos_radio_count = (
                mantenimientos_radio_por_equipo.get(equipo.pk, 0)
            )
        equipo.radios_destino_transferencia = (
            destinos_radio_para_transferencia(
                radios_equipo[equipo.pk], radios_activos
            )
            if radios_activos is not None and equipo.pk in radios_equipo
            else []
        )
    conteos = dict(
        Equipo.objects.filter(activo=True).values_list("tipo")
        .annotate(n=Count("id")).values_list("tipo", "n")
    )

    titulos = {t: titulo for t, titulo, _, _ in TARJETAS_TIPO}
    if disponibilidad == "en_inventario":
        titulo_lista = "Bodega" + (f" · {titulos[tipo]}" if tipo else "")
    else:
        titulo_lista = titulos.get(tipo, "Equipos")
    return render(request, "inventario/equipos_lista.html", {
        "titulo_lista": titulo_lista,
        "equipos": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "total_resultados": page_obj.paginator.count,
        "busqueda": busqueda,
        "tipo_seleccionado": tipo,
        "estado_seleccionado": estado,
        "asignacion_seleccionada": asignacion,
        "disponibilidad_seleccionada": disponibilidad,
        "revision_seleccionada": revision,
        "accesorios_seleccionados": accesorios,
        "datos_seleccionados": datos,
        "estado_operativo_seleccionado": estado_operativo,
        "mantenimiento_seleccionado": mantenimiento,
        "estados_mantenimiento": ESTADOS,
        "n_filtros": n_filtros,
        "pestanas": pestanas,
        "filtros_activos": filtros_activos,
        "url_limpiar": reverse("inventario:equipos_lista"),
        "url_exportar": _url_lista(seleccion, exportar="xlsx"),
        "tipos": [
            (valor, etiqueta, conteos.get(valor, 0))
            for valor, etiqueta in Equipo.Tipo.choices
        ],
    })


@login_required
def equipo_detalle(request, placa):
    """Atajo a la ficha del equipo: la ficha vive en el panel de Equipos."""
    equipo = get_object_or_404(Equipo, placa=placa)
    consulta = urlencode({"q": equipo.placa, "estado": ""})
    return redirect(reverse("inventario:equipos_lista") + "?" + consulta)


@login_required
@xframe_options_sameorigin
def equipo_pestanas(request, placa):
    """Contenido de las pestañas del panel de equipos (se carga en su marco)."""
    equipo = get_object_or_404(Equipo, placa=placa)
    if equipo.tipo == Equipo.Tipo.RADIO and hasattr(equipo, "radio"):
        if (
            request.GET.get("embed") == "1"
            and request.GET.get("pestanas_radio") == "1"
        ):
            radio = equipo.radio
            asignaciones = list(radio.asignaciones.select_related(
                "entregado_por", "recibido_por"
            ).order_by("-fecha_entrega", "-id"))
            cedulas = {
                asignacion.cedula_funcionario for asignacion in asignaciones
            }
            vigilantes = {
                vigilante.cedula: vigilante
                for vigilante in Vigilante.objects.filter(cedula__in=cedulas)
            }
            for asignacion in asignaciones:
                asignacion.vigilante = vigilantes.get(
                    asignacion.cedula_funcionario
                )
            return render(request, "inventario/radio_pestanas.html", {
                "radio": radio,
                "asignaciones": asignaciones,
                "asignacion_activa": next(
                    (
                        asignacion for asignacion in asignaciones
                        if asignacion.estado
                        == AsignacionRadio.Estado.ASIGNADO
                    ),
                    None,
                ),
                "mantenimientos": MantenimientoEquipo.objects.filter(
                    equipo=equipo
                ).select_related("registrado_por").order_by(
                    "-fecha_intervencion", "-id"
                ),
                "formulario": (
                    RadioForm(instance=radio)
                    if puede(request.user, "radios")
                    else None
                ),
                "formulario_baja": RadioBajaForm(),
                "clausula": CLAUSULA_CONFIDENCIALIDAD,
            })
        consulta = urlencode({"q": equipo.placa, "estado": ""})
        return redirect(reverse("inventario:equipos_lista") + "?" + consulta)

    return render_equipo_pestanas(request, equipo)


def _volver_a_pestanas(placa, pestana="resumen"):
    """Vuelve a las pestañas del equipo dentro del marco del panel."""
    destino = reverse("inventario:equipo_pestanas", args=[placa])
    return redirect(destino + "?embed=1#" + pestana)


def pasos_formulario_equipo(formulario, detalle):
    pasos = []
    campos_comunes = {
        "Identificación": (
            "placa", "serial", "marca", "modelo", "propiedad", "fecha_compra",
        ),
        "Responsable y estado": (
            "estado_operativo", "responsable_nombre", "responsable_cedula",
            "ubicacion",
        ),
        "Observaciones y revisión": (
            "observaciones", "requiere_revision", "motivo_revision",
        ),
    }
    usados = set()
    for titulo, nombres in campos_comunes.items():
        campos = [formulario[nombre] for nombre in nombres
                  if nombre in formulario.fields]
        usados.update(nombres)
        if campos:
            pasos.append({"titulo": titulo, "campos": campos})

    restantes = [
        campo for campo in formulario
        if campo.name not in usados
    ]
    if restantes:
        pasos.append({"titulo": "Otros datos generales", "campos": restantes})

    if detalle is not None:
        campos_detalle = list(detalle)
        tamano_paso = 6
        total_pasos = (len(campos_detalle) + tamano_paso - 1) // tamano_paso
        for inicio in range(0, len(campos_detalle), tamano_paso):
            numero = inicio // tamano_paso + 1
            titulo = f"Características {numero} de {total_pasos}"
            pasos.append({
                "titulo": titulo,
                "campos": campos_detalle[inicio:inicio + tamano_paso],
            })

    return pasos


def render_equipo_pestanas(
    request, equipo, formulario_edicion=None, detalle_edicion=None,
    pestana_inicial=None, formulario_entrega=None,
):
    pestana_inicial = pestana_inicial or request.GET.get("pestana", "resumen")
    # Los datos vacíos no se ocultan: la plantilla los marca como "Sin dato".
    secciones_detalle = [
        (titulo, list(filas))
        for titulo, filas in agrupar_detalle(equipo, request.user)
        if filas
    ]
    if puede(request.user, "equipos") and formulario_edicion is None:
        formulario_edicion = EquipoForm(instance=equipo)
        detalle_edicion = formulario_detalle(equipo, usuario=request.user)
    pasos_edicion = (
        pasos_formulario_equipo(formulario_edicion, detalle_edicion)
        if formulario_edicion is not None else []
    )

    asignacion_activa = equipo.asignaciones.filter(
        estado=AsignacionEquipo.Estado.ASIGNADO
    ).first()
    # El registro de entrega vive en su propia pestaña de la ficha.
    if (
        formulario_entrega is None
        and equipo.activo
        and asignacion_activa is None
        and puede(request.user, "entregas")
    ):
        formulario_entrega = AsignacionEquipoForm()

    return render(request, "inventario/equipo_pestanas.html", {
        "equipo": equipo,
        "ficha": ficha_modal(equipo, request.user),
        "pestana_inicial": pestana_inicial,
        "formulario_entrega": formulario_entrega,
        "clausula": CLAUSULA_EQUIPOS,
        "secciones_detalle": secciones_detalle,
        "formulario_edicion": formulario_edicion,
        "detalle_edicion": detalle_edicion,
        "pasos_edicion": pasos_edicion,
        "mantenimientos": MantenimientoEquipo.objects.filter(
            equipo=equipo
        ).select_related("registrado_por").order_by("-fecha_intervencion"),
        "cambios_gps": equipo.cambios_gps.all(),
        "verificaciones": equipo.verificaciones_politica.all()[:5],
        "renovaciones": equipo.renovaciones_antivirus.all()[:5],
        "asignaciones": equipo.asignaciones.select_related("entregado_por"),
        "asignacion_activa": asignacion_activa,
        "formulario_baja": RadioBajaForm(),
    })


@login_required
@xframe_options_sameorigin
def equipo_hoja_vida(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa)
    # Características agrupadas (Hardware, Red, Licencias…), solo con datos.
    secciones_detalle = [
        (titulo, filas)
        for titulo, filas in (
            (t, [(e, v) for e, v in fs if v not in ("", None)])
            for t, fs in agrupar_detalle(equipo, request.user)
        )
        if filas
    ]
    pestana_inicial = request.GET.get("pestana", "general")
    return render(request, "inventario/equipo_hoja_vida.html", {
        "equipo": equipo,
        "pestana_inicial": pestana_inicial,
        "radio": getattr(equipo, "radio", None),
        "secciones_detalle": secciones_detalle,
        "mantenimientos": MantenimientoEquipo.objects.filter(
            equipo=equipo
        ).order_by("-fecha_intervencion"),
        "cambios_gps": equipo.cambios_gps.all(),
        "asignaciones": equipo.asignaciones.all(),
        "generado": timezone.localtime(),
    })


@login_required
@requiere_permiso("equipos")
def equipo_crear(request):
    tipo = request.GET.get("tipo", "")
    if tipo == Equipo.Tipo.RADIO:
        return redirect("inventario:radio_crear")
    if tipo not in Equipo.Tipo.values:
        return render(request, "inventario/equipo_tipo.html", {
            "tipos": [
                (valor, etiqueta) for valor, etiqueta in Equipo.Tipo.choices
            ],
        })

    equipo = Equipo(tipo=tipo)
    return guardar_equipo(request, equipo, f"Registrar {equipo.get_tipo_display().lower()}")


@login_required
@requiere_permiso("equipos")
def equipo_editar(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa)
    if equipo.tipo == Equipo.Tipo.RADIO and hasattr(equipo, "radio"):
        return redirect("inventario:radio_editar", equipo.radio.pk)

    if request.method == "POST" and request.POST.get("embed") == "1":
        formulario = EquipoForm(request.POST, instance=equipo)
        detalle = formulario_detalle(equipo, request.POST, request.user)
        if formulario.is_valid() and (
            detalle is None or detalle.is_valid()
        ):
            with transaction.atomic():
                equipo = formulario.save()
                if detalle is not None:
                    detalle.instance.equipo = equipo
                    detalle.save()
            messages.success(request, f"El equipo {equipo.placa} quedó guardado.")
            destino = reverse("inventario:equipo_pestanas", args=[equipo.placa])
            return redirect(f"{destino}?embed=1&guardado=1#resumen")

        return render_equipo_pestanas(
            request, equipo, formulario, detalle, pestana_inicial="editar"
        )

    return guardar_equipo(request, equipo, f"Editar {equipo.placa}")


def guardar_equipo(request, equipo, titulo):
    datos = request.POST if request.method == "POST" else None
    formulario = EquipoForm(datos, instance=equipo)
    detalle = formulario_detalle(equipo, datos, request.user)

    if datos is not None and formulario.is_valid() and (
        detalle is None or detalle.is_valid()
    ):
        with transaction.atomic():
            equipo = formulario.save()
            if detalle is not None:
                detalle.instance.equipo = equipo
                detalle.save()
        messages.success(request, f"El equipo {equipo.placa} quedó guardado.")
        return redirect("inventario:equipo_detalle", equipo.placa)

    return render(request, "inventario/equipo_form.html", {
        "formulario": formulario,
        "detalle": detalle,
        "equipo": equipo,
        "titulo": titulo,
    })


@login_required
@requiere_permiso("equipos")
def equipo_dar_baja(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa)
    if request.method != "POST" or equipo.tipo == Equipo.Tipo.RADIO:
        return _volver_a_pestanas(placa)

    formulario = RadioBajaForm(request.POST)
    if not equipo.activo:
        messages.error(request, "El equipo ya está dado de baja.")
    elif not formulario.is_valid():
        messages.error(request, "Indica el motivo de la baja.")
    else:
        equipo.activo = False
        equipo.fecha_baja = timezone.localdate()
        equipo.motivo_baja = formulario.cleaned_data["motivo_baja"]
        equipo.save(update_fields=[
            "activo", "fecha_baja", "motivo_baja", "actualizado_en",
        ])
        messages.success(request, "El equipo quedó dado de baja.")
    return _volver_a_pestanas(placa, "baja")


@login_required
@requiere_permiso("equipos")
def equipo_reactivar(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa)
    if request.method == "POST" and not equipo.activo and (
        equipo.tipo != Equipo.Tipo.RADIO
    ):
        equipo.activo = True
        equipo.fecha_baja = None
        equipo.motivo_baja = ""
        equipo.save(update_fields=[
            "activo", "fecha_baja", "motivo_baja", "actualizado_en",
        ])
        messages.success(request, "El equipo volvió al inventario activo.")
    return _volver_a_pestanas(placa)


ORDEN_ESTADO = {codigo: posicion for posicion, (codigo, _) in enumerate(ESTADOS)}


def _contiene(texto, aguja):
    return aguja in (texto or "").lower()


def _exportar_mantenimientos(equipos, hoy):
    """Excel con los equipos que se están viendo en el panel."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    etiquetas_estado = dict(ESTADOS)
    etiquetas_tipo = dict(Equipo.Tipo.choices)
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Mantenimientos"
    encabezados = [
        "Placa", "Tipo", "Marca", "Modelo", "Serial", "Responsable",
        "Ubicación", "Estado", "Último mantenimiento", "Próximo",
        "Visita programada", "Días para vencer (negativo = atrasado)",
    ]
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="080D79")
        celda.alignment = Alignment(wrap_text=True, vertical="center")

    for equipo in equipos:
        hoja.append([
            equipo.placa,
            etiquetas_tipo.get(equipo.tipo, equipo.tipo),
            equipo.marca, equipo.modelo, equipo.serial,
            equipo.responsable_nombre, equipo.ubicacion,
            etiquetas_estado[equipo.estado_mantenimiento],
            equipo.ultimo_fecha, equipo.proximo_mantenimiento,
            equipo.proximo_programado, equipo.dias_para_vencer,
        ])
        fila = hoja[hoja.max_row]
        # Un texto que empieza con "=" no debe interpretarse como fórmula.
        for celda in fila:
            if isinstance(celda.value, str):
                celda.data_type = "s"
        for posicion in (8, 9, 10):
            fila[posicion].number_format = "DD/MM/YYYY"

    anchos = [16, 14, 16, 18, 18, 28, 28, 20, 20, 14, 16, 18]
    for indice, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    hoja.row_dimensions[1].height = 32
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions

    respuesta = HttpResponse(
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )
    respuesta["Content-Disposition"] = (
        f'attachment; filename="mantenimientos_{hoy:%Y%m%d}.xlsx"'
    )
    libro.save(respuesta)
    return respuesta


@login_required
def panel_mantenimientos(request):
    hoy = hoy_colombia()
    equipos = equipos_con_estado(
        Equipo.objects.filter(activo=True).select_related("radio"), hoy
    )

    etiquetas_tipo = dict(Equipo.Tipo.choices)
    etiquetas_estado = dict(ESTADOS)
    matriz = {}
    for equipo in equipos:
        fila = matriz.setdefault(equipo.tipo, {e: 0 for e, _ in ESTADOS})
        fila[equipo.estado_mantenimiento] += 1

    def porcentaje_al_dia(conteos):
        total = sum(conteos.values())
        if not total:
            return 0
        return round(100 * (conteos[VIGENTE] + conteos[PROXIMO]) / total)

    # Primero los tipos con más equipos vencidos; la barra muestra la proporción.
    filas = [
        (
            tipo, etiquetas_tipo[tipo],
            [(e, conteos[e]) for e, _ in ESTADOS],
            porcentaje_al_dia(conteos),
            [
                (e, conteos[e], round(100 * conteos[e] / sum(conteos.values()), 1))
                for e, _ in ESTADOS
            ],
            sum(conteos.values()),
        )
        for tipo, conteos in sorted(
            matriz.items(), key=lambda par: (-par[1][VENCIDO], par[0])
        )
    ]
    conteo_total = {
        e: sum(1 for eq in equipos if eq.estado_mantenimiento == e)
        for e, _ in ESTADOS
    }
    totales = [(e, conteo_total[e]) for e, _ in ESTADOS]
    total_equipos = len(equipos)
    resumen = [
        {
            "estado": e,
            "etiqueta": etiqueta,
            "n": conteo_total[e],
            "ancho": (
                round(100 * conteo_total[e] / total_equipos, 1)
                if total_equipos else 0
            ),
        }
        for e, etiqueta in ESTADOS
    ]

    tipo = request.GET.get("tipo", "").strip()
    if tipo not in etiquetas_tipo:
        tipo = ""
    estado = request.GET.get("estado", "").strip()
    if estado not in etiquetas_estado:
        estado = ""
    busqueda = request.GET.get("q", "").strip()
    responsable = request.GET.get("responsable", "").strip()
    ubicacion = request.GET.get("ubicacion", "").strip()
    hay_filtros = any([tipo, estado, busqueda, responsable, ubicacion])
    # Vista: "resumen" (por tipo) o "equipos" (filtros y lista). Sin pedirla,
    # se muestran los equipos solo si hay algún filtro.
    vista = request.GET.get("vista", "").strip()
    if vista not in ("resumen", "equipos"):
        vista = "equipos" if hay_filtros else "resumen"

    q = busqueda.lower()
    resp = responsable.lower()
    ubic = ubicacion.lower()
    coincidentes = [
        e for e in equipos
        if (not tipo or e.tipo == tipo)
        and (not q or any(
            _contiene(valor, q)
            for valor in (e.placa, e.serial, e.marca, e.modelo)
        ))
        and (not resp or _contiene(e.responsable_nombre, resp))
        and (not ubic or _contiene(e.ubicacion, ubic))
    ]
    seleccion = [
        e for e in coincidentes
        if not estado or e.estado_mantenimiento == estado
    ]
    # Más urgentes primero; dentro de cada estado, el que venció antes.
    seleccion.sort(key=lambda e: (
        ORDEN_ESTADO[e.estado_mantenimiento],
        e.proximo_mantenimiento or date.min,
        e.placa,
    ))

    if request.GET.get("exportar") == "xlsx":
        return _exportar_mantenimientos(seleccion, hoy)

    # En escritorio la página ajusta "pp" (filas por página) a la altura
    # disponible para que la lista no necesite barra de desplazamiento.
    try:
        por_pagina = max(3, min(50, int(request.GET.get("pp", 10))))
    except ValueError:
        por_pagina = 10
    page_obj, parametros = paginar(request, seleccion, por_pagina)

    titulo_lista = etiquetas_estado.get(estado, "Todos los equipos")
    if tipo:
        titulo_lista = f"{titulo_lista} · {etiquetas_tipo[tipo]}"

    return render(request, "inventario/panel_mantenimientos.html", {
        "vista": vista,
        "pestana": vista,
        "estados": ESTADOS,
        "filas": filas,
        "totales": totales,
        "resumen": resumen,
        "total_equipos": total_equipos,
        "pct_al_dia": porcentaje_al_dia(conteo_total) if total_equipos else 0,
        "tipos_opciones": [(t, etiquetas_tipo[t]) for t, _ in sorted(matriz.items())],
        "estado_seleccionado": estado,
        "titulo_lista": titulo_lista,
        "tipo_seleccionado": tipo,
        "busqueda": busqueda,
        "responsable": responsable,
        "ubicacion": ubicacion,
        "hay_filtros": hay_filtros,
        "equipos": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "total_seleccion": len(seleccion),
    })


@login_required
@xframe_options_sameorigin
@requiere_permiso("entregas")
def equipo_entregar(request, placa):
    """El registro vive en la pestaña «Entregar» de la ficha del equipo,
    igual que en los radios."""
    equipo = get_object_or_404(Equipo, placa=placa)
    if equipo.tipo == Equipo.Tipo.RADIO:
        consulta = urlencode({"q": equipo.placa, "estado": ""})
        return redirect(reverse("inventario:equipos_lista") + "?" + consulta)
    if request.method != "POST":
        return redirect(
            reverse("inventario:equipo_pestanas", args=[placa])
            + "?embed=1#entregar"
        )
    if not equipo.activo:
        messages.error(request, "El equipo está dado de baja.")
        return _volver_a_pestanas(placa, "entregas")
    if equipo.asignaciones.filter(estado=AsignacionEquipo.Estado.ASIGNADO).exists():
        messages.error(
            request,
            "El equipo ya está entregado. Registra primero la devolución.",
        )
        return _volver_a_pestanas(placa, "entregas")

    formulario = AsignacionEquipoForm(request.POST)
    if formulario.is_valid():
        try:
            with transaction.atomic():
                asignacion = formulario.save(commit=False)
                funcionario = formulario.cleaned_data["funcionario"]
                asignacion.equipo = equipo
                asignacion.entregado_por = request.user
                asignacion.nombre_recibe = funcionario.nombre_completo
                asignacion.cedula_recibe = funcionario.cedula
                asignacion.save()
                equipo.responsable_nombre = funcionario.nombre_completo
                equipo.responsable_cedula = funcionario.cedula
                equipo.ubicacion = asignacion.area
                equipo.save(update_fields=[
                    "responsable_nombre", "responsable_cedula", "ubicacion",
                    "actualizado_en",
                ])
        except IntegrityError:
            formulario.add_error(
                None,
                "El equipo ya tiene una entrega activa. "
                "Actualiza la página y verifica su estado.",
            )
        else:
            messages.success(request, "La entrega del equipo quedó registrada.")
            return _volver_a_pestanas(placa, "entregas")

    return render_equipo_pestanas(
        request, equipo, formulario_entrega=formulario,
        pestana_inicial="entregar",
    )


@login_required
@requiere_permiso("entregas")
def equipo_devolver(request, asignacion_id):
    if request.method != "POST":
        return redirect("inventario:equipos_lista")
    with transaction.atomic():
        asignacion = get_object_or_404(
            AsignacionEquipo.objects.select_for_update().select_related("equipo"),
            pk=asignacion_id,
        )
        if asignacion.estado == AsignacionEquipo.Estado.ASIGNADO:
            asignacion.estado = AsignacionEquipo.Estado.DEVUELTO
            asignacion.fecha_devolucion = timezone.now()
            asignacion.recibido_por = request.user
            asignacion.observaciones_devolucion = request.POST.get(
                "observaciones_devolucion", ""
            ).strip()
            asignacion.save()
            equipo = asignacion.equipo
            equipo.responsable_nombre = ""
            equipo.responsable_cedula = ""
            equipo.ubicacion = ""
            equipo.save(update_fields=[
                "responsable_nombre", "responsable_cedula", "ubicacion",
                "actualizado_en",
            ])
            messages.success(request, "La devolución quedó registrada.")
    return _volver_a_pestanas(asignacion.equipo.placa, "entregas")


@login_required
@xframe_options_sameorigin
def equipo_acta(request, asignacion_id):
    asignacion = get_object_or_404(
        AsignacionEquipo.objects.select_related(
            "equipo", "funcionario", "entregado_por"
        ),
        pk=asignacion_id,
    )
    return render(request, "inventario/equipo_acta.html", {
        "asignacion": asignacion,
        "equipo": asignacion.equipo,
        # El acta se imprime y se entrega: nunca lleva claves de licencia.
        "filas_detalle": [
            fila for fila in filas_detalle(asignacion.equipo, None)
            if fila[1] != "Restringido"
        ],
        "clausula": CLAUSULA_EQUIPOS,
    })


@login_required
@requiere_permiso("equipos")
def equipo_cambio_gps(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa, tipo=Equipo.Tipo.GPS)
    gps = getattr(equipo, "gps", None) or DetalleGPS(equipo=equipo)
    formulario = CambioGPSForm(request.POST or None, initial={
        "linea": gps.linea,
        "operador": gps.operador,
        "placa_vehiculo": gps.placa_vehiculo,
        "nombre_vehiculo": gps.nombre_vehiculo,
    })
    if request.method == "POST" and formulario.is_valid():
        with transaction.atomic():
            cambio = formulario.save(commit=False)
            cambio.equipo = equipo
            cambio.registrado_por = request.user
            cambio.responsable = (
                request.user.get_full_name() or request.user.username
            )
            cambio.placa_vehiculo = cambio.placa_vehiculo.strip().upper()
            cambio.save()
            gps.linea = cambio.linea
            gps.operador = cambio.operador
            gps.placa_vehiculo = cambio.placa_vehiculo
            gps.nombre_vehiculo = cambio.nombre_vehiculo
            gps.fecha_asignacion = cambio.fecha
            gps.save()
            equipo.ubicacion = " ".join(
                p for p in (cambio.placa_vehiculo, cambio.nombre_vehiculo) if p
            )[:200]
            equipo.save(update_fields=["ubicacion", "actualizado_en"])
        messages.success(request, "El cambio del GPS quedó registrado.")
        return redirect("inventario:equipo_detalle", placa)

    return render(request, "inventario/equipo_cambio_gps.html", {
        "formulario": formulario,
        "equipo": equipo,
    })


TIPOS_CON_POLITICA = [Equipo.Tipo.COMPUTADOR, Equipo.Tipo.TABLETA]


def _abrir_politica_en_ventana(**parametros):
    """Verificar y Ver detalle ya no tienen página propia: viven en la ventana emergente.

    Quien llega por un enlace directo (ficha del equipo, marcador antiguo) va a la
    Política de seguridad y la ventana se abre sola.
    """
    return redirect(f"{reverse('inventario:politica_lista')}?{urlencode(parametros)}")


@login_required
@requiere_permiso("mantenimientos")
def politica_registrar(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa, tipo__in=TIPOS_CON_POLITICA)
    if not pide_modal(request):
        return _abrir_politica_en_ventana(abrir="verificar", equipo=equipo.placa)

    formulario = VerificacionPoliticaForm(request.POST or None, initial={
        "especialista": request.user.get_full_name() or request.user.username,
        "responsable": equipo.responsable_nombre,
    })
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        verificacion = VerificacionPolitica.objects.create(
            equipo=equipo,
            especialista=datos["especialista"],
            responsable=datos["responsable"],
            respuestas=formulario.respuestas(),
            observaciones=datos["observaciones"],
            actualizacion=datos["actualizacion"],
            registrado_por=request.user,
        )
        if verificacion.incumplimientos:
            messages.warning(
                request,
                f"Verificación guardada con {len(verificacion.incumplimientos)} "
                "incumplimiento(s).",
            )
        else:
            messages.success(request, "Verificación guardada: cumple la política.")
        # La ventana recarga la lista y muestra el mensaje.
        return JsonResponse({"ok": True})

    return render(request, "inventario/_politica_form_modal.html", {
        "formulario": formulario, "equipo": equipo,
    })


@login_required
def politica_detalle(request, pk):
    from .politica import PUNTOS

    verificacion = get_object_or_404(
        VerificacionPolitica.objects.select_related("equipo"), pk=pk
    )
    if not pide_modal(request):
        return _abrir_politica_en_ventana(abrir="detalle", verificacion=verificacion.pk)
    return render(request, "inventario/_politica_detalle_modal.html", {
        "verificacion": verificacion,
        "filas": [
            (texto, verificacion.respuestas.get(clave, "-"))
            for clave, texto in PUNTOS
        ],
    })


def _equipos_con_estado_politica(hoy):
    """Computadores y tabletas activos con el estado de su verificación."""
    from . import politica
    from .estado_mantenimiento import fecha_local

    ultimas = {}
    for v in VerificacionPolitica.objects.order_by("-fecha", "-id").values(
        "id", "equipo_id", "fecha", "respuestas"
    ):
        ultimas.setdefault(v["equipo_id"], v)

    equipos = list(Equipo.objects.filter(activo=True, tipo__in=TIPOS_CON_POLITICA))
    for equipo in equipos:
        v = ultimas.get(equipo.pk)
        equipo.verificacion_id = v["id"] if v else None
        equipo.ultima_fecha = fecha_local(v["fecha"]) if v else None
        equipo.n_incumplimientos = (
            sum(1 for r in v["respuestas"].values() if r == politica.NO_CUMPLE)
            if v else 0
        )
        equipo.estado_politica, equipo.vence = politica.estado_verificacion(
            equipo.ultima_fecha, equipo.n_incumplimientos, hoy
        )
        equipo.estado_clase = politica.CLASE_ESTADO[equipo.estado_politica]
        dias = (equipo.vence - hoy).days if equipo.vence else None
        if equipo.estado_politica == politica.VENCIDA:
            equipo.plazo_texto = f"Venció hace {-dias} día{'s' if dias != -1 else ''}"
        elif equipo.estado_politica == politica.PROXIMA:
            equipo.plazo_texto = f"Vence en {dias} día{'s' if dias != 1 else ''}"
        elif equipo.estado_politica == politica.INCUMPLE:
            n = equipo.n_incumplimientos
            equipo.plazo_texto = f"{n} punto{'s' if n != 1 else ''} no cumple{'n' if n != 1 else ''}"
        else:
            equipo.plazo_texto = ""
    return equipos


def _exportar_politica(equipos, hoy):
    """Excel con los equipos que se están viendo en la página de política."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from . import politica

    etiquetas_estado = dict(politica.ESTADOS)
    etiquetas_tipo = dict(Equipo.Tipo.choices)
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Política de seguridad"
    hoja.append([
        "Placa", "Tipo", "Marca", "Modelo", "Serial", "Responsable",
        "Ubicación", "Estado", "Última verificación", "Vence",
        "Puntos que no cumple",
    ])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="080D79")
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    for equipo in equipos:
        hoja.append([
            equipo.placa, etiquetas_tipo.get(equipo.tipo, equipo.tipo),
            equipo.marca, equipo.modelo, equipo.serial,
            equipo.responsable_nombre, equipo.ubicacion,
            etiquetas_estado[equipo.estado_politica],
            equipo.ultima_fecha, equipo.vence, equipo.n_incumplimientos,
        ])
        fila = hoja[hoja.max_row]
        for celda in fila:
            if isinstance(celda.value, str):
                celda.data_type = "s"
        for posicion in (8, 9):
            fila[posicion].number_format = "DD/MM/YYYY"
    for indice, ancho in enumerate([16, 14, 16, 18, 18, 28, 28, 20, 20, 14, 18], start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    hoja.row_dimensions[1].height = 32
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    respuesta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    respuesta["Content-Disposition"] = f'attachment; filename="politica_{hoy:%Y%m%d}.xlsx"'
    libro.save(respuesta)
    return respuesta


@login_required
def politica_lista(request):
    from . import politica

    hoy = hoy_colombia()
    etiquetas_tipo = dict(Equipo.Tipo.choices)
    etiquetas_estado = dict(politica.ESTADOS)
    ctx = {"estados": politica.ESTADOS}

    vista = request.GET.get("vista", "").strip()
    # Enlaces antiguos: ?filtro=incumplimientos abría el historial filtrado.
    if request.GET.get("filtro") == "incumplimientos":
        vista = "historial"
    if vista not in ("equipos", "historial"):
        vista = "equipos"

    if vista == "equipos":
        equipos = _equipos_con_estado_politica(hoy)
        tipo = request.GET.get("tipo", "").strip()
        if tipo not in TIPOS_CON_POLITICA:
            tipo = ""
        estado = request.GET.get("estado", "").strip()
        if estado not in etiquetas_estado:
            estado = ""
        busqueda = request.GET.get("q", "").strip()
        responsable = request.GET.get("responsable", "").strip()
        ubicacion = request.GET.get("ubicacion", "").strip()
        q, resp, ubic = busqueda.lower(), responsable.lower(), ubicacion.lower()

        coincidentes = [
            e for e in equipos
            if (not tipo or e.tipo == tipo)
            and (not q or any(
                _contiene(valor, q)
                for valor in (e.placa, e.serial, e.marca, e.modelo)
            ))
            and (not resp or _contiene(e.responsable_nombre, resp))
            and (not ubic or _contiene(e.ubicacion, ubic))
        ]
        conteos = {codigo: 0 for codigo, _ in politica.ESTADOS}
        for e in coincidentes:
            conteos[e.estado_politica] += 1
        seleccion = [
            e for e in coincidentes if not estado or e.estado_politica == estado
        ]
        orden = {codigo: i for i, (codigo, _) in enumerate(politica.ESTADOS)}
        seleccion.sort(key=lambda e: (
            orden[e.estado_politica], e.vence or date.min, e.placa,
        ))

        if request.GET.get("exportar") == "xlsx":
            return _exportar_politica(seleccion, hoy)

        page_obj, parametros = paginar(request, seleccion, filas_por_pagina(request, 10))
        titulo = etiquetas_estado.get(estado, "Todos los equipos")
        if tipo:
            titulo = f"{titulo} · {etiquetas_tipo[tipo]}"
        ctx.update({
            "equipos": page_obj.object_list,
            "page_obj": page_obj,
            "parametros": parametros,
            "total_seleccion": len(seleccion),
            "total_equipos": len(equipos),
            "tarjetas": [(c, n, conteos[c]) for c, n in politica.ESTADOS],
            "tipos_opciones": [(t, etiquetas_tipo[t]) for t in TIPOS_CON_POLITICA],
            "tipo_seleccionado": tipo,
            "estado_seleccionado": estado,
            "busqueda": busqueda,
            "responsable": responsable,
            "ubicacion": ubicacion,
            "hay_filtros": any([tipo, estado, busqueda, responsable, ubicacion]),
            "titulo_lista": titulo,
        })
    else:
        verificaciones = VerificacionPolitica.objects.select_related("equipo")
        busqueda = request.GET.get("q", "").strip()
        tipo = request.GET.get("tipo", "").strip()
        if tipo in TIPOS_CON_POLITICA:
            verificaciones = verificaciones.filter(equipo__tipo=tipo)
        else:
            tipo = ""
        fecha_desde = request.GET.get("fecha_desde", "").strip()
        fecha_hasta = request.GET.get("fecha_hasta", "").strip()
        if fecha_desde:
            try:
                fecha_desde = date.fromisoformat(fecha_desde).isoformat()
            except ValueError:
                fecha_desde = ""
        if fecha_desde:
            verificaciones = verificaciones.filter(fecha__date__gte=fecha_desde)
        if fecha_hasta:
            try:
                fecha_hasta = date.fromisoformat(fecha_hasta).isoformat()
            except ValueError:
                fecha_hasta = ""
        if fecha_hasta:
            verificaciones = verificaciones.filter(fecha__date__lte=fecha_hasta)
        if busqueda:
            verificaciones = verificaciones.filter(
                Q(equipo__placa__icontains=busqueda)
                | Q(equipo__serial__icontains=busqueda)
                | Q(especialista__icontains=busqueda)
                | Q(responsable__icontains=busqueda)
            )
        resultado = request.GET.get("resultado", "").strip()
        if request.GET.get("filtro") == "incumplimientos":
            resultado = "incumple"
        if resultado in ("cumple", "incumple"):
            con_incumplimiento = {
                pk for pk, respuestas in verificaciones.values_list("pk", "respuestas")
                if politica.NO_CUMPLE in respuestas.values()
            }
            if resultado == "incumple":
                verificaciones = verificaciones.filter(pk__in=con_incumplimiento)
            else:
                verificaciones = verificaciones.exclude(pk__in=con_incumplimiento)
        else:
            resultado = ""
        page_obj, parametros = paginar(request, verificaciones, filas_por_pagina(request, 50))
        ctx.update({
            "verificaciones": page_obj.object_list,
            "page_obj": page_obj,
            "parametros": parametros,
            "total_resultados": page_obj.paginator.count,
            "total_registros": VerificacionPolitica.objects.count(),
            "busqueda": busqueda,
            "tipo_seleccionado": tipo,
            "tipos_historial": [
                (t, etiquetas_tipo[t]) for t in TIPOS_CON_POLITICA
            ],
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "resultado_seleccionado": resultado,
            "hay_filtros": bool(
                busqueda or tipo or fecha_desde or fecha_hasta or resultado
            ),
            "total_equipos": Equipo.objects.filter(
                activo=True, tipo__in=TIPOS_CON_POLITICA
            ).count(),
        })
    ctx.update({"vista": vista, "pestana": vista, "defecto_filas": 10 if vista == "equipos" else 50})
    return render(request, "inventario/politica_lista.html", ctx)


@login_required
@requiere_permiso("licencias")
def equipo_renovar_antivirus(request, placa):
    equipo = get_object_or_404(Equipo, placa=placa, tipo__in=TIPOS_CON_POLITICA)
    detalle = getattr(equipo, "computador", None) or DetalleComputador(equipo=equipo)
    formulario = RenovacionAntivirusForm(request.POST or None, initial={
        "antivirus": detalle.antivirus,
    })
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        with transaction.atomic():
            RenovacionAntivirus.objects.create(
                equipo=equipo, registrado_por=request.user, **datos
            )
            detalle.antivirus = datos["antivirus"]
            if datos["licencia"]:
                detalle.licencia_antivirus = datos["licencia"]
            detalle.vencimiento_antivirus = datos["vencimiento"]
            detalle.save()
        messages.success(
            request,
            f"Antivirus renovado hasta el {datos['vencimiento']:%d/%m/%Y}.",
        )
        if pide_modal(request):
            return JsonResponse({"ok": True})
        return redirect("inventario:equipo_detalle", placa)
    if pide_modal(request):
        return render(request, "inventario/_antivirus_form_modal.html", {
            "formulario": formulario, "equipo": equipo,
        })
    return render(request, "inventario/equipo_renovar_antivirus.html", {
        "formulario": formulario, "equipo": equipo,
    })


# Tarjetas de la sección Equipos: (tipo, título, icono, descripción).
TARJETAS_TIPO = [
    (Equipo.Tipo.COMPUTADOR, "Computadores", "monitor", "Portátiles y de escritorio de las áreas administrativas"),
    (Equipo.Tipo.RADIO, "Radios", "radio", "Radios de comunicación entregados a los puestos y vigilantes"),
    (Equipo.Tipo.TABLETA, "Tabletas", "tablet", "Tabletas para supervisión y registro en campo"),
    (Equipo.Tipo.IMPRESORA, "Impresoras", "printer", "Impresoras y multifuncionales"),
    (Equipo.Tipo.ESCANER, "Escáneres", "scan", "Escáneres de documentos"),
    (Equipo.Tipo.GPS, "GPS", "map", "Dispositivos de rastreo satelital"),
    (Equipo.Tipo.ALARMA, "Alarmas", "bell", "Paneles y sistemas de alarma"),
    (Equipo.Tipo.UPS, "UPS", "battery", "Respaldo de energía"),
    (Equipo.Tipo.OTRO, "Otros equipos", "box", "Equipos que no encajan en las demás categorías"),
]


def _ids_entregados():
    """Equipos activos con una entrega vigente (a funcionarios o radios a vigilantes)."""
    ids = set(AsignacionEquipo.objects.filter(
        estado=AsignacionEquipo.Estado.ASIGNADO, equipo__activo=True
    ).values_list("equipo_id", flat=True))
    ids.update(AsignacionRadio.objects.filter(
        estado=AsignacionRadio.Estado.ASIGNADO, radio__activo=True
    ).values_list("radio__equipo_id", flat=True))
    return ids


@login_required
def equipos_inicio(request):
    """Sección Equipos: una tarjeta por tipo que lleva a la lista ya filtrada."""
    activos = Equipo.objects.filter(activo=True)
    por_tipo = {
        f["tipo"]: f for f in activos.values("tipo").annotate(
            total=Count("id"), revision=Count("id", filter=Q(requiere_revision=True))
        )
    }
    entregados = {}
    for tipo in activos.filter(pk__in=_ids_entregados()).values_list("tipo", flat=True):
        entregados[tipo] = entregados.get(tipo, 0) + 1

    lista = reverse("inventario:equipos_lista")
    tarjetas = []
    for tipo, titulo, icono, descripcion in TARJETAS_TIPO:
        datos = por_tipo.get(tipo)
        if not datos:
            continue
        entregado = entregados.get(tipo, 0)
        tarjetas.append({
            "titulo": titulo, "icono": icono, "descripcion": descripcion,
            "total": datos["total"], "entregados": entregado,
            "bodega": max(datos["total"] - entregado, 0), "revision": datos["revision"],
            "url": f"{lista}?tipo={tipo}",
            "url_bodega": f"{lista}?tipo={tipo}&disponibilidad=en_inventario",
            "url_revision": f"{lista}?tipo={tipo}&revision=si",
        })
    total = sum(t["total"] for t in tarjetas)
    return render(request, "inventario/equipos_inicio.html", {
        "tarjetas": tarjetas,
        "total": total,
        "total_entregados": sum(t["entregados"] for t in tarjetas),
        "url_todos": lista,
    })
