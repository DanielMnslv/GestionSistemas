import re
from datetime import date, datetime

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventario.google_sheet import (
    leer_hoja,
    libro_del_sheet,
    normalizar_encabezado,
    texto_celda,
)
from inventario.models import (
    DetalleAlarma,
    DetalleComputador,
    DetalleGPS,
    DetalleImpresora,
    Equipo,
    Funcionario,
)


VACIOS = {"N/A", "NA", "NO ASIGNADO", "NONE", "-", "SIN REGISTRO", "VERIFICAR"}

# BASEDATOS-COMPUTADOR2 repite encabezados ("Serial", "Observaciones"…),
# así que se lee por posición y se verifica el encabezado de cada columna.
COMPUTADOR2 = {
    "placa": (0, "PLACA"),
    "tipo": (1, "Escoja el tipo de equipo"),
    "clase": (2, "Tipo de equipo tecnologico"),
    "serial": (3, "Serial de equipo tecnologico"),
    "marca": (4, "Marca de equipo Tecnologico"),
    "modelo": (5, "Modelo de equipo tecnologico"),
    "procesador": (6, "Modelo Procesador"),
    "velocidad_procesador": (7, "Capacidad Procesador"),
    "tipo_disco": (8, "Tipo de Disco Duro"),
    "capacidad_disco": (9, "Capacidad de Disco Duro"),
    "tipo_ram": (10, "Memoria RAM"),
    "capacidad_ram": (11, "Capacidad Memoria RAM"),
    "mouse": (13, "Tipo Mouse"),
    "teclado": (15, "Tipo de Teclado"),
    "regulador": (16, "REGULADOR"),
    "parlantes": (17, "PARLANTES O AUDIFONOS"),
    "webcam": (18, "WEB CAM"),
    "ups_serial": (20, "Serial UPS"),
    "ups_marca": (21, "Marca UPS"),
    "ups_capacidad": (22, "Capacidad UPS"),
    "ups_modelo": (23, "Modelo UPS"),
    "telefono_ip_serial": (25, "Serial Teléfono IP"),
    "telefono_ip_marca": (26, "Marca Teléfono IP"),
    "telefono_ip_modelo": (27, "Modelo Teléfono IP"),
    "sistema_operativo": (29, "Marca y versión del Sistema Operativo"),
    "licencia_so": (30, "Licencia del Sistema Operativo"),
    "antivirus": (32, "Marca y Versión de Antivirus"),
    "licencia_antivirus": (33, "Licencia de Antivirus"),
    "office": (36, "Marca y Versión de Office"),
    "licencia_office": (37, "Serial de Licencia de Office"),
    "software_licenciado": (39, "Nombre de software licenciado y licencia"),
    "software_libre": (41, "Escriba los nombres y versiones de los programas Libres"),
    "monitor_serial": (43, "Serial Monitor"),
    "monitor_modelo": (44, "Modelo, Marca y tamaño de Monitor"),
    "imei": (55, "IMEI"),
    "linea_celular": (56, "LINEA CELULAR"),
    "responsable_nombre": (57, "ASIGNACION"),
    "responsable_cedula": (58, "CEDULA FUNCIONARIO"),
    "propiedad": (59, "PROPIO / ARRENDADO"),
    "mac_ethernet": (60, "MAC TARJETA DE RED"),
    "vencimiento_antivirus": (61, "FECHA DE VENCIMIENTO ANTIVIRUS"),
    "fecha_compra": (63, "Año de Compra"),
    "mac_wifi": (66, "MAC Inalambrica"),
    "observaciones": (67, "NOTAS / OBSERVACIONES"),
}

# BASEDATOS-COMPUTADOR (versión anterior): campo -> encabezado.
COMPUTADOR1 = {
    "placa": "Placa",
    "clase": "Tipo de Computador",
    "serial": "Escriba serial del Computador",
    "marca": "Marca del Computador",
    "modelo": "Modelo del Computador",
    "propiedad": "Propiedad del Computador",
    "procesador": "Modelo de Procesador",
    "tipo_disco": "Tipo de Disco Duro",
    "capacidad_disco": "Capacidad de Disco Duro",
    "capacidad_ram": "Capacidad de Memoria RAM",
    "mouse": "Mouse",
    "teclado": "Teclado",
    "regulador": "Regulador",
    "webcam": "Webcam",
    "parlantes": "Parlantes",
    "monitor_serial": "Escriba Serial de Monitor",
    "monitor_modelo": "Escriba modelo y marca de Monitor 1",
    "monitor2_serial": "Serial Monitor 2",
    "monitor2_modelo": "Escriba modelo y marca de Monitor 2",
    "ups_serial": "Serial UPS",
    "ups_modelo": "Escriba modelo y marca de UPS",
    "sistema_operativo": "Escriba Sistema Operativo",
    "licencia_so": "Licencia de Sistemas Operativo",
    "antivirus": "Antivirus",
    "licencia_antivirus": "Escriba Licencia de Antivirus",
    "vencimiento_antivirus": "Escriba Fecha de vencimiento de antivirus",
    "office": "Escriba la versión de Office Instalado",
    "licencia_office": "Escriba licencia de Ofimática",
    "software_licenciado": "Otro software licenciado",
    "responsable_nombre": "Funcionario Asignado",
    "responsable_cedula": "Cedula de Funcionario",
    "fecha_compra": "Fecha de compra",
    "mac_ethernet": "Mac Ethernet",
    "mac_wifi": "Mac Wifi",
    "ip_ethernet": "IP Ethernet",
    "ip_wifi": "IP Wifi Asignada",
}

IMPRESORAS = {
    "placa": "Placa",
    "tipo": "Tipo de Equipo Tecnologico",
    "serial": "Serial de Impresora",
    "marca_modelo": "Modelo de  y marca de Impresora",
    "clase": "Tipo de Impresora",
    "responsable_nombre": "Escoja al Funcionario a quien se le asigna la impresora",
    "responsable_cedula": "Cedula de Funcionario",
    "fecha_compra": "Fecha de Compra",
}

GPS = {
    "imei": "IMEI GPS",
    "serial": "SERIAL",
    "marca": "MARCA DE GPS",
    "modelo": "MODELO DE GPS",
    "linea": "LINEA ASIGNADA",
    "operador": "OPERADOR DE SIM",
    "placa_vehiculo": "VEHICULO ASIGNADO",
    "nombre_vehiculo": "NOMBRE DE VEHICULO",
    "fecha_asignacion": "FECHA DE ASIGNACION",
    "estado": "ESTADO",
    "plataforma": "PLATAFORMA GPS",
    "fecha_compra": "FECHA DE COMPRA",
    "observaciones": "OBSERVACIONES",
}

# Componentes de la alarma: (nombre, columna de cantidad, columna de estado).
# El Sheet escribe "Cantoidad de Magneticos" y repite "Cantidad de Sirenas".
ALARMAS = {
    "placa": "Placa",
    "clase": "Tipo de Alarma",
    "serial": "Serial de la Alarma",
    "marca": "Marca de La Alarma",
    "modelo": "Modelo de La Alarma",
    "propiedad": "Propiedad de la Alarma",
    "estado": "Estado General de la Alarma",
    "reporta_central": "Reporta a la central",
    "serial_comunicador": "Serial del Comunicador",
    "estado_comunicador": "Estado del Comunicador",
    "responsable_nombre": "Funcionario Asignado",
    "ubicacion": "Puesto Asignado",
    "observaciones": "Observaciones",
    "fecha_compra": "FECHA DE COMPRA",
}
COMPONENTES_ALARMA = [
    ("Teclados", "Cantidad de Teclados", "Estado de Teclado"),
    ("Sensores", "Cantidad de Sensores", "Estado de Sensores"),
    ("Magnéticos", "Cantoidad de Magneticos", "Estado de Magneticos"),
    ("Botones de pánico", "Cantidad de Botón de Panico",
     "Estado de Botón de Panico"),
    ("Sirenas", "Cantidad de Sirenas", "Estado de Sirenas"),
]

CAMPOS_EQUIPO = [
    "serial", "marca", "modelo", "propiedad", "fecha_compra",
    "estado_operativo", "responsable_nombre", "responsable_cedula",
    "ubicacion", "observaciones",
]
DETALLES = {
    Equipo.Tipo.COMPUTADOR: DetalleComputador,
    Equipo.Tipo.TABLETA: DetalleComputador,
    Equipo.Tipo.IMPRESORA: DetalleImpresora,
    Equipo.Tipo.ESCANER: DetalleImpresora,
    Equipo.Tipo.GPS: DetalleGPS,
    Equipo.Tipo.ALARMA: DetalleAlarma,
}
TIPOS_COMPUTADOR2 = {
    "COMPUTADOR": Equipo.Tipo.COMPUTADOR,
    "TABLETA": Equipo.Tipo.TABLETA,
    "GPS": Equipo.Tipo.GPS,
    "UPS": Equipo.Tipo.UPS,
}


def limpio(valor):
    texto = texto_celda(valor)
    if texto.upper() in VACIOS:
        return ""
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    return texto


def fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = limpio(valor)
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    return None


def fecha_hora(valor):
    if isinstance(valor, datetime):
        return valor
    dia = fecha(valor)
    return datetime.combine(dia, datetime.min.time()) if dia else None


def placa_y_baja(valor):
    """'PC--11 BAJA' -> ('PC--11', True)."""
    texto = limpio(valor).upper()
    baja = "BAJA" in texto
    placa = texto.replace("BAJA", "").strip(" -")
    return re.sub(r"\s+", "", placa), baja


def unir(*partes):
    return " ".join(p for p in (limpio(x) for x in partes) if p)


def estado_operativo(valor):
    texto = limpio(valor).upper()
    if texto.startswith("BUEN"):
        return Equipo.EstadoOperativo.OPERATIVO
    if "DAÑ" in texto or "MAL" in texto:
        return Equipo.EstadoOperativo.NO_OPERATIVO
    return ""


def registro(hoja, fila, placa, tipo, baja=False, equipo=None, detalle=None):
    return {
        "hoja": hoja,
        "fila": fila,
        "placa": placa,
        "tipo": tipo,
        "baja": baja,
        "equipo": {k: v for k, v in (equipo or {}).items() if v},
        "detalle": {k: v for k, v in (detalle or {}).items() if v not in ("", None, [])},
    }


class Command(BaseCommand):
    help = (
        "Importa computadores, tabletas, impresoras, escáneres, GPS, UPS y "
        "alarmas desde el Google Sheet, y los funcionarios de LISTADO "
        "PERSONAL. Crea los equipos que faltan y solo completa campos "
        "vacíos de los existentes. Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Guardar los cambios después de validar todo.",
        )
        parser.add_argument(
            "--detalle", action="store_true",
            help="Mostrar cada equipo que se crearía o completaría.",
        )

    def handle(self, *args, **options):
        self.omitidos = []
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            registros = (
                self.leer_computador2(archivo)
                + self.leer_computador1(archivo)
                + self.leer_impresoras(archivo)
                + self.leer_gps(archivo)
                + self.leer_alarmas(archivo)
            )
            funcionarios = self.leer_funcionarios(archivo)

        plan = self.planear(self.fusionar(registros), funcionarios)
        self.mostrar(plan, options["detalle"])

        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. "
                "Usa --confirmar para aplicar."
            ))
            return

        with transaction.atomic():
            for datos in plan["funcionarios_crear"]:
                Funcionario.objects.create(**datos)
            for reg in plan["crear"]:
                equipo = Equipo.objects.create(
                    placa=reg["placa"], tipo=reg["tipo"],
                    activo=not reg["baja"],
                    motivo_baja="Marcado como baja en el Sheet" if reg["baja"] else "",
                    **reg["equipo"],
                )
                modelo = DETALLES.get(reg["tipo"])
                if modelo:
                    modelo.objects.create(equipo=equipo, **reg["detalle"])
            for equipo, cambios, detalle, cambios_detalle in plan["completar"]:
                if cambios:
                    for campo, valor in cambios.items():
                        setattr(equipo, campo, valor)
                    equipo.save()
                if cambios_detalle:
                    for campo, valor in cambios_detalle.items():
                        setattr(detalle, campo, valor)
                    detalle.save()

        self.stdout.write(self.style.SUCCESS(
            f"Importación completada: {len(plan['crear'])} equipos creados, "
            f"{len(plan['completar'])} completados, "
            f"{len(plan['funcionarios_crear'])} funcionarios creados."
        ))

    # --- Lectura -------------------------------------------------------

    def filas_por_posicion(self, archivo, hoja, columnas):
        libro = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
        try:
            if hoja not in libro.sheetnames:
                raise CommandError(f"No existe la hoja {hoja}.")
            filas = libro[hoja].iter_rows(values_only=True)
            encabezados = next(filas)
            for campo, (i, esperado) in columnas.items():
                real = encabezados[i] if i < len(encabezados) else None
                if normalizar_encabezado(real) != normalizar_encabezado(esperado):
                    raise CommandError(
                        f"{hoja}: la columna {i + 1} debería ser "
                        f"{esperado!r} y es {real!r}."
                    )
            resultado = []
            for numero, fila in enumerate(filas, start=2):
                if not any(v not in (None, "") for v in fila):
                    continue
                datos = {
                    campo: fila[i] if i < len(fila) else None
                    for campo, (i, _) in columnas.items()
                }
                datos["_fila"] = numero
                resultado.append(datos)
            return resultado
        finally:
            libro.close()

    def por_nombre(self, archivo, hoja, columnas):
        filas = leer_hoja(archivo, hoja, list(columnas.values()))
        return [
            {**{campo: f[col] for campo, col in columnas.items()},
             "_fila": f["_fila"]}
            for f in filas
        ]

    def leer_computador2(self, archivo):
        hoja = "BASEDATOS-COMPUTADOR2"
        registros = []
        for f in self.filas_por_posicion(archivo, hoja, COMPUTADOR2):
            placa, baja = placa_y_baja(f["placa"])
            tipo = TIPOS_COMPUTADOR2.get(limpio(f["tipo"]).upper())
            if not placa or not tipo:
                motivo = (
                    "sin placa" if not placa else
                    f"tipo {texto_celda(f['tipo']) or 'vacío'} no se importa"
                )
                self.omitidos.append(
                    f"{hoja} fila {f['_fila']} ({texto_celda(f['placa'])}): "
                    f"{motivo}."
                )
                continue
            equipo = {
                "serial": limpio(f["serial"]),
                "marca": limpio(f["marca"]),
                "modelo": limpio(f["modelo"]),
                "propiedad": limpio(f["propiedad"]),
                "fecha_compra": fecha(f["fecha_compra"]),
                "responsable_nombre": limpio(f["responsable_nombre"]),
                "responsable_cedula": limpio(f["responsable_cedula"]),
                "observaciones": limpio(f["observaciones"]),
            }
            if tipo == Equipo.Tipo.GPS:
                detalle = {
                    "imei": limpio(f["imei"]),
                    "linea": limpio(f["linea_celular"]),
                }
            elif tipo == Equipo.Tipo.UPS:
                detalle = {}
            else:
                detalle = {
                    campo: limpio(f[campo]) for campo in (
                        "clase", "procesador", "velocidad_procesador",
                        "tipo_disco", "capacidad_disco", "tipo_ram",
                        "capacidad_ram", "mouse", "teclado", "regulador",
                        "parlantes", "webcam", "ups_serial",
                        "telefono_ip_serial", "sistema_operativo",
                        "licencia_so", "antivirus", "licencia_antivirus",
                        "office", "licencia_office", "software_licenciado",
                        "software_libre", "monitor_serial", "monitor_modelo",
                        "imei", "linea_celular", "mac_ethernet", "mac_wifi",
                    )
                }
                detalle["ups_modelo"] = unir(
                    f["ups_marca"], f["ups_modelo"], f["ups_capacidad"]
                )
                detalle["telefono_ip_modelo"] = unir(
                    f["telefono_ip_marca"], f["telefono_ip_modelo"]
                )
                detalle["vencimiento_antivirus"] = fecha(
                    f["vencimiento_antivirus"]
                )
            registros.append(registro(
                hoja, f["_fila"], placa, tipo, baja, equipo, detalle
            ))
        return registros

    def leer_computador1(self, archivo):
        hoja = "BASEDATOS-COMPUTADOR"
        registros = []
        for f in self.por_nombre(archivo, hoja, COMPUTADOR1):
            placa, baja = placa_y_baja(f["placa"])
            if not placa:
                continue
            equipo = {
                campo: limpio(f[campo]) for campo in (
                    "serial", "marca", "modelo", "propiedad",
                    "responsable_nombre", "responsable_cedula",
                )
            }
            equipo["fecha_compra"] = fecha(f["fecha_compra"])
            detalle = {
                campo: limpio(f[campo]) for campo in COMPUTADOR1
                if campo not in equipo and campo not in (
                    "placa", "fecha_compra", "vencimiento_antivirus"
                )
            }
            detalle["vencimiento_antivirus"] = fecha(f["vencimiento_antivirus"])
            registros.append(registro(
                hoja, f["_fila"], placa, Equipo.Tipo.COMPUTADOR, baja,
                equipo, detalle,
            ))
        return registros

    def leer_impresoras(self, archivo):
        hoja = "BASEDATOS_IMP"
        registros = []
        for f in self.por_nombre(archivo, hoja, IMPRESORAS):
            placa, baja = placa_y_baja(f["placa"])
            if not placa:
                continue
            tipo = (
                Equipo.Tipo.ESCANER
                if "ESC" in limpio(f["tipo"]).upper() or placa.startswith("ESC")
                else Equipo.Tipo.IMPRESORA
            )
            marca, _, modelo = limpio(f["marca_modelo"]).partition(" ")
            registros.append(registro(
                hoja, f["_fila"], placa, tipo, baja,
                {
                    "serial": limpio(f["serial"]),
                    "marca": marca,
                    "modelo": modelo,
                    "fecha_compra": fecha(f["fecha_compra"]),
                    "responsable_nombre": limpio(f["responsable_nombre"]),
                    "responsable_cedula": limpio(f["responsable_cedula"]),
                },
                {"clase": limpio(f["clase"])},
            ))
        return registros

    def leer_gps(self, archivo):
        hoja = "BASEDATOS_GPS"
        registros = []
        for f in self.por_nombre(archivo, hoja, GPS):
            imei = limpio(f["imei"])
            if not imei:
                continue
            registros.append(registro(
                hoja, f["_fila"], imei, Equipo.Tipo.GPS, False,
                {
                    "serial": limpio(f["serial"]),
                    "marca": limpio(f["marca"]),
                    "modelo": limpio(f["modelo"]),
                    "fecha_compra": fecha(f["fecha_compra"]),
                    "estado_operativo": estado_operativo(f["estado"]),
                    "ubicacion": unir(f["placa_vehiculo"], f["nombre_vehiculo"]),
                    "observaciones": limpio(f["observaciones"]),
                },
                {
                    "imei": imei,
                    "linea": limpio(f["linea"]),
                    "operador": limpio(f["operador"]),
                    "placa_vehiculo": limpio(f["placa_vehiculo"]).upper(),
                    "nombre_vehiculo": limpio(f["nombre_vehiculo"]),
                    "fecha_asignacion": fecha_hora(f["fecha_asignacion"]),
                    "plataforma": limpio(f["plataforma"]),
                },
            ))
        return registros

    def leer_alarmas(self, archivo):
        hoja = "BASEDATOS_ALARMAS"
        columnas = dict(ALARMAS)
        for nombre, cantidad, estado in COMPONENTES_ALARMA:
            columnas[f"cant_{nombre}"] = cantidad
            columnas[f"est_{nombre}"] = estado
        registros = []
        for f in self.por_nombre(archivo, hoja, columnas):
            placa, baja = placa_y_baja(f["placa"])
            if not placa:
                continue
            componentes = [
                {
                    "nombre": nombre,
                    "cantidad": int(f[f"cant_{nombre}"] or 0),
                    "estado": limpio(f[f"est_{nombre}"]),
                }
                for nombre, _, _ in COMPONENTES_ALARMA
                if isinstance(f[f"cant_{nombre}"], (int, float))
                and f[f"cant_{nombre}"] > 0
            ]
            registros.append(registro(
                hoja, f["_fila"], placa, Equipo.Tipo.ALARMA, baja,
                {
                    "serial": limpio(f["serial"]),
                    "marca": limpio(f["marca"]),
                    "modelo": limpio(f["modelo"]),
                    "propiedad": limpio(f["propiedad"]),
                    "fecha_compra": fecha(f["fecha_compra"]),
                    "estado_operativo": estado_operativo(f["estado"]),
                    "responsable_nombre": limpio(f["responsable_nombre"]),
                    "ubicacion": limpio(f["ubicacion"]),
                    "observaciones": limpio(f["observaciones"]),
                },
                {
                    "clase": limpio(f["clase"]),
                    "reporta_central": limpio(f["reporta_central"]),
                    "componentes": componentes,
                    "serial_comunicador": limpio(f["serial_comunicador"]),
                    "estado_comunicador": limpio(f["estado_comunicador"]),
                },
            ))
        return registros

    def leer_funcionarios(self, archivo):
        filas = leer_hoja(
            archivo, "LISTADO PERSONAL", ["CEDULA", "NOMBRE", "CARGO", "CORREO"]
        )
        funcionarios = {}
        for f in filas:
            cedula = limpio(f["CEDULA"])
            nombre = limpio(f["NOMBRE"])
            if cedula and nombre and cedula not in funcionarios:
                correo = limpio(f["CORREO"])
                funcionarios[cedula] = {
                    "cedula": cedula[:20],
                    "nombre_completo": nombre[:200],
                    "cargo": limpio(f["CARGO"])[:150],
                    "correo": correo if "@" in correo else "",
                }
        return funcionarios

    # --- Plan ----------------------------------------------------------

    def fusionar(self, registros):
        """Un registro por placa: el primero manda y los siguientes de la
        misma placa y tipo solo completan campos vacíos."""
        por_placa = {}
        for reg in registros:
            actual = por_placa.get(reg["placa"])
            if actual is None:
                por_placa[reg["placa"]] = reg
                continue
            if actual["tipo"] != reg["tipo"] or actual["hoja"] == reg["hoja"]:
                self.omitidos.append(
                    f"{reg['hoja']} fila {reg['fila']} ({reg['placa']}): "
                    f"placa repetida (ya está en {actual['hoja']} fila "
                    f"{actual['fila']})."
                )
                continue
            for parte in ("equipo", "detalle"):
                for campo, valor in reg[parte].items():
                    actual[parte].setdefault(campo, valor)
        return list(por_placa.values())

    def planear(self, registros, funcionarios):
        plan = {"crear": [], "completar": [], "sin_cambios": 0,
                "funcionarios_crear": []}
        existentes = {
            e.placa: e for e in Equipo.objects.select_related(
                "computador", "impresora", "gps", "alarma"
            )
        }
        seriales = {}
        for e in existentes.values():
            if e.serial:
                seriales.setdefault(e.serial.upper(), e.placa)

        for reg in registros:
            equipo = existentes.get(reg["placa"])
            if equipo is None:
                serial = reg["equipo"].get("serial", "").upper()
                if serial and serial in seriales:
                    self.omitidos.append(
                        f"{reg['hoja']} fila {reg['fila']} ({reg['placa']}): "
                        f"el serial ya es del equipo {seriales[serial]}."
                    )
                    continue
                if serial:
                    seriales[serial] = reg["placa"]
                plan["crear"].append(reg)
                continue
            if equipo.tipo != reg["tipo"]:
                self.omitidos.append(
                    f"{reg['hoja']} fila {reg['fila']} ({reg['placa']}): ya "
                    f"existe como {equipo.get_tipo_display()}."
                )
                continue
            cambios = {
                campo: valor for campo, valor in reg["equipo"].items()
                if campo in CAMPOS_EQUIPO
                and getattr(equipo, campo) in ("", None)
            }
            modelo = DETALLES.get(reg["tipo"])
            detalle = None
            cambios_detalle = {}
            if modelo:
                nombre = modelo._meta.get_field("equipo").remote_field.related_name
                detalle = getattr(equipo, nombre, None) or modelo(equipo=equipo)
                cambios_detalle = {
                    campo: valor for campo, valor in reg["detalle"].items()
                    if getattr(detalle, campo) in ("", None, [])
                }
            if cambios or cambios_detalle:
                plan["completar"].append(
                    (equipo, cambios, detalle, cambios_detalle)
                )
            else:
                plan["sin_cambios"] += 1

        actuales = set(Funcionario.objects.values_list("cedula", flat=True))
        plan["funcionarios_crear"] = [
            datos for cedula, datos in funcionarios.items()
            if cedula not in actuales
        ]
        return plan

    def mostrar(self, plan, detalle):
        por_tipo = {}
        for reg in plan["crear"]:
            por_tipo[reg["tipo"]] = por_tipo.get(reg["tipo"], 0) + 1
        etiquetas = dict(Equipo.Tipo.choices)
        self.stdout.write(f"Equipos a crear: {len(plan['crear'])}")
        for tipo, n in sorted(por_tipo.items()):
            self.stdout.write(f"  {etiquetas[tipo]}: {n}")
        bajas = sum(1 for reg in plan["crear"] if reg["baja"])
        if bajas:
            self.stdout.write(f"  (de ellos, dados de baja: {bajas})")
        self.stdout.write(f"Equipos a completar: {len(plan['completar'])}")
        self.stdout.write(f"Equipos sin cambios: {plan['sin_cambios']}")
        self.stdout.write(
            f"Funcionarios a crear: {len(plan['funcionarios_crear'])}"
        )
        self.stdout.write(f"Filas omitidas: {len(self.omitidos)}")

        if detalle:
            for reg in plan["crear"]:
                self.stdout.write(
                    f"  + {reg['placa']} ({etiquetas[reg['tipo']]}) "
                    f"{reg['equipo'].get('marca', '')} "
                    f"{reg['equipo'].get('modelo', '')} · {reg['hoja']}"
                )
            for equipo, cambios, _, cambios_detalle in plan["completar"]:
                self.stdout.write(
                    f"  ~ {equipo.placa}: "
                    f"{', '.join([*cambios, *cambios_detalle])}"
                )
        if self.omitidos:
            self.stdout.write("\nOmitidas:")
            for linea in self.omitidos:
                self.stdout.write(self.style.WARNING(f"  {linea}"))
