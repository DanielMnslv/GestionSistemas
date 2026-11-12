from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    clave_placa,
    leer_hoja,
    libro_del_sheet,
    normalizar_placa,
    texto_celda,
)
from inventario.models import AsignacionEquipo, CambioGPS, Equipo, Funcionario


ZONA_FORMULARIO = ZoneInfo("America/Bogota")
PREFIJO = "[Formulario Google]"

# Hoja -> {campo: encabezado}
HOJAS_ENTREGAS = {
    "ASIG-COMPUTADOR": {
        "fecha": "Marca temporal",
        "placa": "Escoja la Placa del Computador",
        "nombre": "Busque y seleccione el nombre del funcionario asignado",
        "cedula": "Escriba el numero de cédula correspondiente al funcionario asignado",
        "firma": "Por Favor adjuntar Firma",
    },
    "resp_imp": {
        "fecha": "Marca temporal",
        "placa": "Escriba Placa de Impresora",
        "nombre": "Escoja al Funcionario a quien se le asigna la impresora",
        "clausula": "Cláusula de Aceptación y Responsabilidad por Asignación de Impresora",
        "firma": "Adjuntar Firma",
        "cedula": "Número de Cedula del Funcionario Asignado",
    },
}
GPS = {
    "fecha": "Marca temporal",
    "imei": "Escoja el IMEI DEL GPS a Actualizar",
    "responsable": "RESPONSABLE DE ACTUALIZACION",
    "observaciones": "OBSERVACIONES",
    "dato": "QUE DATO VAS A ACTUALIZAR",
    "linea": "ESCRIBA LA LINEA NUEVA",
    "operador": "Escoja el Operador de la línea",
    "placa_vehiculo": "ESCOJA EL VEHICULO A ASIGNAR",
    "nombre_vehiculo": "Nombre de Vehiculo",
}


def limpio(valor):
    texto = texto_celda(valor)
    return "" if texto.upper() in ("N/A", "NA", "NONE", "-") else texto


def aware(fecha):
    return timezone.make_aware(fecha.replace(microsecond=0), ZONA_FORMULARIO)


class Command(BaseCommand):
    help = (
        "Importa el historial de entregas de computadores (ASIG-COMPUTADOR) "
        "e impresoras (resp_imp) a funcionarios, y los cambios de GPS "
        "(RPTAGPS). Cada entrega cierra la anterior del mismo equipo y en "
        "ejecuciones siguientes solo se agregan respuestas nuevas. Es una "
        "simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True,
                            help="Usuario responsable de las entregas.")
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument("--confirmar", action="store_true",
                            help="Guardar los cambios.")

    def handle(self, *args, **options):
        try:
            usuario = get_user_model().objects.get(username=options["usuario"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"No existe el usuario {options['usuario']!r}.")

        self.omitidos = []
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = []
            for hoja, columnas in HOJAS_ENTREGAS.items():
                for f in leer_hoja(archivo, hoja, list(columnas.values())):
                    filas.append({
                        "hoja": hoja, "_fila": f["_fila"],
                        **{campo: f[col] for campo, col in columnas.items()},
                    })
            filas_gps = leer_hoja(archivo, "RPTAGPS", list(GPS.values()))

        plan = self.planear(filas)
        cambios_gps = self.planear_gps(filas_gps)
        total = sum(len(e) for _, e in plan)
        self.stdout.write(f"Entregas a registrar: {total} en {len(plan)} equipos")
        self.stdout.write(f"Cambios de GPS a registrar: {len(cambios_gps)}")
        self.stdout.write(f"Respuestas omitidas: {len(self.omitidos)}")
        for linea in self.omitidos:
            self.stdout.write(self.style.WARNING(f"  {linea}"))

        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. "
                "Usa --confirmar para aplicar."
            ))
            return

        with transaction.atomic():
            for equipo, entregas in plan:
                activa = equipo.asignaciones.filter(
                    estado=AsignacionEquipo.Estado.ASIGNADO
                ).first()
                for entrega in entregas:
                    if activa:
                        activa.estado = AsignacionEquipo.Estado.DEVUELTO
                        activa.fecha_devolucion = entrega["fecha_entrega"]
                        activa.recibido_por = usuario
                        activa.observaciones_devolucion = (
                            f"{PREFIJO} Cerrada al registrarse una nueva entrega "
                            f"a {entrega['nombre_recibe']}."
                        )
                        activa.save()
                    activa = AsignacionEquipo.objects.create(
                        equipo=equipo, entregado_por=usuario, **entrega
                    )
                # Solo completa: nunca reemplaza un dato con uno vacío.
                cambios = {
                    campo: valor for campo, valor in (
                        ("responsable_nombre", activa.nombre_recibe),
                        ("responsable_cedula", activa.cedula_recibe),
                    )
                    if valor and not getattr(equipo, campo)
                }
                if cambios:
                    for campo, valor in cambios.items():
                        setattr(equipo, campo, valor)
                    equipo.save(update_fields=[*cambios, "actualizado_en"])
            CambioGPS.objects.bulk_create(cambios_gps)

        self.stdout.write(self.style.SUCCESS(
            f"Importación completada: {total} entregas y "
            f"{len(cambios_gps)} cambios de GPS."
        ))

    def buscar_equipo(self, placa, equipos, por_clave):
        equipo = equipos.get(placa)
        if equipo is None:
            candidatos = por_clave.get(clave_placa(placa), [])
            equipo = candidatos[0] if len(candidatos) == 1 else None
        return equipo

    def planear(self, filas):
        equipos = {
            e.placa: e for e in Equipo.objects.exclude(tipo=Equipo.Tipo.RADIO)
        }
        por_clave = {}
        for e in equipos.values():
            por_clave.setdefault(clave_placa(e.placa), []).append(e)
        funcionarios = {f.cedula: f for f in Funcionario.objects.all()}

        por_equipo = {}
        for f in filas:
            etiqueta = f"{f['hoja']} fila {f['_fila']} ({texto_celda(f['placa'])})"
            if not isinstance(f["fecha"], datetime):
                self.omitidos.append(f"{etiqueta}: sin marca temporal.")
                continue
            equipo = self.buscar_equipo(
                normalizar_placa(f["placa"]), equipos, por_clave
            )
            if equipo is None:
                self.omitidos.append(f"{etiqueta}: no se encontró el equipo.")
                continue
            cedula = limpio(f["cedula"])
            funcionario = funcionarios.get(cedula)
            nombre = limpio(f["nombre"]) or (
                funcionario.nombre_completo if funcionario else ""
            )
            clausula = limpio(f.get("clausula"))
            por_equipo.setdefault(equipo.pk, (equipo, []))[1].append({
                "fecha_entrega": aware(f["fecha"]),
                "funcionario": funcionario,
                "nombre_recibe": nombre[:200],
                "cedula_recibe": cedula[:50],
                "clausula_aceptada": clausula.lower().startswith(("sí", "si", "acept")),
                "enlace_firma": limpio(f["firma"])[:500],
                "observaciones_entrega": PREFIJO,
            })

        ultimas = {}
        for a in AsignacionEquipo.objects.order_by("fecha_entrega"):
            ultimas[a.equipo_id] = a

        plan = []
        for equipo, entregas in por_equipo.values():
            entregas.sort(key=lambda e: e["fecha_entrega"])
            ultima = ultimas.get(equipo.pk)
            anterior = None
            if ultima:
                entregas = [
                    e for e in entregas if e["fecha_entrega"] > ultima.fecha_entrega
                ]
                if ultima.estado == AsignacionEquipo.Estado.ASIGNADO:
                    anterior = ultima.cedula_recibe or ultima.nombre_recibe
            nuevas = []
            for entrega in entregas:
                quien = entrega["cedula_recibe"] or entrega["nombre_recibe"]
                if quien == anterior:
                    # Reenvío para la misma persona: misma entrega.
                    if nuevas:
                        nuevas[-1] = {**entrega,
                                      "fecha_entrega": nuevas[-1]["fecha_entrega"]}
                    continue
                nuevas.append(entrega)
                anterior = quien
            if nuevas:
                plan.append((equipo, nuevas))
        plan.sort(key=lambda par: par[0].placa)
        return plan

    def planear_gps(self, filas):
        gps = {
            e.placa: e for e in Equipo.objects.filter(tipo=Equipo.Tipo.GPS)
        }
        existentes = set(CambioGPS.objects.values_list("equipo_id", "fecha"))
        cambios = []
        for f in filas:
            etiqueta = f"RPTAGPS fila {f['_fila']}"
            imei = limpio(f[GPS["imei"]])
            equipo = gps.get(imei)
            if equipo is None or not isinstance(f[GPS["fecha"]], datetime):
                self.omitidos.append(f"{etiqueta} ({imei}): GPS no encontrado.")
                continue
            fecha = aware(f[GPS["fecha"]])
            if (equipo.pk, fecha) in existentes:
                continue
            existentes.add((equipo.pk, fecha))
            cambios.append(CambioGPS(
                equipo=equipo,
                fecha=fecha,
                responsable=limpio(f[GPS["responsable"]])[:200],
                dato_actualizado=limpio(f[GPS["dato"]])[:150],
                linea=limpio(f[GPS["linea"]])[:50],
                operador=limpio(f[GPS["operador"]])[:100],
                placa_vehiculo=limpio(f[GPS["placa_vehiculo"]]).upper()[:20],
                nombre_vehiculo=limpio(f[GPS["nombre_vehiculo"]])[:150],
                observaciones=limpio(f[GPS["observaciones"]]),
            ))
        return cambios
