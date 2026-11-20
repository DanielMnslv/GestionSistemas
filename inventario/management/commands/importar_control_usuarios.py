"""Importa el Excel CONTROL DE USUARIOS sin leer ni guardar contraseñas.

Simula por defecto. Use ``--confirmar`` únicamente después de revisar el
resumen y de aplicar las migraciones del directorio, accesos y SSI.
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
import re
import unicodedata

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth import get_user_model

from inventario.models import (
    AccesoPlataforma,
    ActivoInformacionSSI,
    CatalogoSSI,
    ControlSSIUsuario,
    Funcionario,
    PerfilPlataforma,
    PlataformaAcceso,
)


# Los intervalos evitan leer las columnas de contraseña de la hoja CONTROL.
# Columnas excluidas: 8, 11, 14, 17 y 23.
CONTROL_RANGOS_SEGUROS = ((1, 7), (9, 10), (12, 13), (15, 16), (18, 22), (24, 24))
# La matriz SSI tiene una columna de credencial entre criticidad y antivirus.
MATRIZ_RANGOS_SEGUROS = ((1, 11), (13, 16))

PLATAFORMAS_CONTROL = (
    ("SEIF", 7, 9),
    ("Novasoft", 10, 12),
    ("Correo corporativo", 13, 15),
    ("Servidor", 16, 18),
    ("Correo SITE", 22, 24),
)


def texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor)).strip()
    resultado = str(valor).strip()
    if resultado.endswith(".0") and resultado[:-2].isdigit():
        resultado = resultado[:-2]
    return resultado


def cedula_normalizada(valor):
    return "".join(c for c in texto(valor) if c.isdigit())


def clave_nombre(valor):
    valor = unicodedata.normalize("NFKD", texto(valor).casefold())
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    return " ".join(valor.split())


def clave_nombre_tokens(valor):
    return " ".join(sorted(clave_nombre(valor).split()))


def afirmacion(valor):
    valor = texto(valor).upper()
    if valor in {"SI", "SÍ", "YES"}:
        return ControlSSIUsuario.Respuesta.SI
    if valor in {"NO", "N"}:
        return ControlSSIUsuario.Respuesta.NO
    if valor in {"N/A", "NA", "NO APLICA"}:
        return ControlSSIUsuario.Respuesta.NA
    return ""


def filas_en_rangos(hoja, rangos, min_row):
    iteradores = [
        hoja.iter_rows(min_row=min_row, min_col=inicio, max_col=fin, values_only=True)
        for inicio, fin in rangos
    ]
    for bloques in zip(*iteradores):
        fila = {}
        for (inicio, _), bloque in zip(rangos, bloques):
            for desplazamiento, valor in enumerate(bloque):
                fila[inicio + desplazamiento] = valor
        yield fila


def tipo_activo(valor):
    valor = texto(valor).casefold()
    if "hardware" in valor:
        return ActivoInformacionSSI.TipoActivo.HARDWARE
    if "software" in valor:
        return ActivoInformacionSSI.TipoActivo.SOFTWARE
    if "inform" in valor or "dato" in valor:
        return ActivoInformacionSSI.TipoActivo.INFORMACION
    if "servicio" in valor:
        return ActivoInformacionSSI.TipoActivo.SERVICIO
    return ActivoInformacionSSI.TipoActivo.OTRO


def numero(valor):
    valor = texto(valor).replace(",", ".")
    if not valor:
        return None


def fecha_vigencia_control(hoja):
    """Lee solo la fecha de vigencia del encabezado, nunca columnas secretas."""
    for fila in hoja.iter_rows(min_row=1, max_row=4, values_only=True):
        for valor in fila:
            texto_fecha = texto(valor)
            if "FECHA DE VIGENCIA" not in texto_fecha.upper():
                continue
            encontrado = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", texto_fecha)
            if encontrado:
                try:
                    return datetime.strptime(encontrado.group(1), "%d/%m/%Y").date()
                except ValueError:
                    return None
    return None
    try:
        return Decimal(valor)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Simula o importa CONTROL DE USUARIOS sin contraseñas ni secretos."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path, help="Ruta al archivo XLSX")
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Guarda personas, accesos, controles y catálogos seguros.",
        )

    def handle(self, *args, **options):
        ruta = options["archivo"].expanduser()
        if not ruta.is_file():
            raise CommandError("No se encontró el archivo indicado.")

        try:
            libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        except Exception as exc:
            raise CommandError("No se pudo leer el XLSX.") from exc

        requeridas = {
            "BASE DE DATOS", "DIRECTORIO", "CONTROL", "MATRIZ SSI",
            "CRITICIDAD", "DATOS",
        }
        faltantes = requeridas - set(libro.sheetnames)
        if faltantes:
            raise CommandError("El archivo no contiene todas las hojas esperadas.")

        personas = {}
        cedulas_base_datos = set()
        for fila in libro["BASE DE DATOS"].iter_rows(min_row=2, values_only=True):
            cedula = cedula_normalizada(fila[0] if len(fila) > 0 else "")
            nombre = texto(fila[1] if len(fila) > 1 else "")
            if not cedula or not nombre:
                continue
            cedulas_base_datos.add(cedula)
            estado_fuente = texto(fila[3] if len(fila) > 3 else "").upper()
            personas[cedula] = {
                "nombre_completo": nombre,
                "cargo": texto(fila[2] if len(fila) > 2 else ""),
                "estado_persona": (
                    Funcionario.EstadoPersona.INACTIVA
                    if estado_fuente.startswith("INACT")
                    else Funcionario.EstadoPersona.ACTIVA
                    if estado_fuente.startswith("ACT")
                    else Funcionario.EstadoPersona.PENDIENTE
                ),
                "telefono": texto(fila[4] if len(fila) > 4 else ""),
                "perfil_seif": texto(fila[5] if len(fila) > 5 else ""),
                "area": texto(fila[6] if len(fila) > 6 else ""),
                "extension_interna": texto(fila[7] if len(fila) > 7 else ""),
            }

        directorio = {}
        nombres_ambiguos = set()
        for fila in libro["DIRECTORIO"].iter_rows(min_row=2, values_only=True):
            nombre = texto(fila[0] if fila else "")
            llave = clave_nombre(nombre)
            if not llave:
                continue
            if llave in directorio:
                nombres_ambiguos.add(llave)
            directorio[llave] = {
                "correo": texto(fila[1] if len(fila) > 1 else ""),
                "cargo": texto(fila[2] if len(fila) > 2 else ""),
                "telefono": texto(fila[3] if len(fila) > 3 else ""),
                "area": texto(fila[5] if len(fila) > 5 else ""),
            }
        for cedula, datos in personas.items():
            llave = clave_nombre(datos["nombre_completo"])
            if llave in directorio and llave not in nombres_ambiguos:
                for campo, valor in directorio[llave].items():
                    if valor and not datos.get(campo):
                        datos[campo] = valor

        fecha_control = fecha_vigencia_control(libro["CONTROL"])
        control_rows = list(filas_en_rangos(libro["CONTROL"], CONTROL_RANGOS_SEGUROS, 7))
        accesos = []
        controles = []
        for fila in control_rows:
            cedula = cedula_normalizada(fila.get(1))
            nombre = texto(fila.get(2))
            if not cedula or not nombre:
                continue
            datos = personas.setdefault(cedula, {
                "nombre_completo": nombre,
                "cargo": "",
                # Una cuenta listada en CONTROL no demuestra que la persona
                # continúe activa; el estado vigente viene de BASE DE DATOS.
                "estado_persona": Funcionario.EstadoPersona.PENDIENTE,
                "telefono": "",
                "area": "",
                "extension_interna": "",
                "perfil_seif": "",
            })
            # CONTROL es una fuente antigua de accesos. BASE DE DATOS es la
            # fuente del directorio y tiene prioridad para nombre, cargo y área.
            for campo, valor in (
                ("nombre_completo", nombre),
                ("cargo", texto(fila.get(4))),
                ("area", texto(fila.get(3))),
            ):
                if valor and not datos.get(campo):
                    datos[campo] = valor

            for nombre_plataforma, col_usuario, col_perfil in PLATAFORMAS_CONTROL:
                usuario = texto(fila.get(col_usuario))
                perfil = texto(fila.get(col_perfil))
                if (usuario or perfil) and usuario.upper() not in {"N/A", "NA", "NO APLICA", "-"}:
                    accesos.append((cedula, nombre_plataforma, usuario, perfil))

            correo = texto(fila.get(13))
            if "@" in correo and not datos.get("correo"):
                datos["correo"] = correo

            controles.append({
                "cedula": cedula,
                "proceso": texto(fila.get(3)),
                "nivel_criticidad": texto(fila.get(5)),
                "control_accesos": texto(fila.get(6)),
                "redes_sociales": afirmacion(fila.get(19)),
                "vpn": afirmacion(fila.get(20)),
                "usb": afirmacion(fila.get(21)),
                "fecha_revision": fecha_control,
            })

        activos_ssi = []
        matriz = libro["MATRIZ SSI"]
        for fila in filas_en_rangos(matriz, MATRIZ_RANGOS_SEGUROS, 2):
            activo = texto(fila.get(2))
            if not activo:
                continue
            activos_ssi.append({
                "proceso": texto(fila.get(1)),
                "activo": activo,
                "tipo_activo": tipo_activo(fila.get(3)),
                "perfil_usuario": texto(fila.get(4)),
                "tipo_ubicacion": texto(fila.get(5)),
                "nivel_confidencialidad": texto(fila.get(6)),
                "confidencialidad": int(numero(fila.get(7)) or 0) or None,
                "integridad": int(numero(fila.get(8)) or 0) or None,
                "disponibilidad": int(numero(fila.get(9)) or 0) or None,
                "valor": numero(fila.get(10)),
                "nivel_criticidad": texto(fila.get(11)),
                "requiere_antivirus": afirmacion(fila.get(13)),
                "requiere_vpn": afirmacion(fila.get(14)),
                "riesgos": texto(fila.get(15)),
                "medidas_seguridad": texto(fila.get(16)),
            })

        criticidades = []
        for fila in libro["CRITICIDAD"].iter_rows(min_row=2, values_only=True):
            valor = texto(fila[1] if len(fila) > 1 else "")
            descripcion = texto(fila[2] if len(fila) > 2 else "")
            if valor:
                criticidades.append(("NIVEL_CRITICIDAD", valor, descripcion))

        catalogos = list(criticidades)
        hoja_datos = libro["DATOS"]
        encabezados = next(hoja_datos.iter_rows(min_row=1, max_row=1, values_only=True), ())
        for indice, categoria in enumerate(encabezados, 1):
            categoria = texto(categoria)
            if not categoria or any(p in categoria.casefold() for p in ("contrase", "password", "clave", "secret")):
                continue
            for fila in hoja_datos.iter_rows(min_row=2, min_col=indice, max_col=indice, values_only=True):
                valor = texto(fila[0])
                if valor:
                    catalogos.append((categoria, valor, ""))

        seif_en_control = {
            cedula for cedula, nombre_plataforma, _, _ in accesos
            if nombre_plataforma == "SEIF"
        }
        for cedula, datos in personas.items():
            perfil_seif = datos.get("perfil_seif", "")
            if perfil_seif and cedula not in seif_en_control:
                accesos.append((cedula, "SEIF", "", perfil_seif))

        resumen = (
            ("Personas a crear o actualizar", len(personas)),
            ("Accesos por plataforma", len(accesos)),
            ("Evaluaciones de control SSI", len(controles)),
            ("Activos de información SSI", len(activos_ssi)),
            ("Valores de catálogos SSI", len(catalogos)),
        )
        for etiqueta, cantidad in resumen:
            self.stdout.write(f"{etiqueta}: {cantidad}")

        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "Simulación: no se guardaron cambios. Revisa los conteos y luego usa --confirmar."
            ))
            return

        with transaction.atomic():
            personas_db = {}
            Usuario = get_user_model()
            usuarios_jano = list(Usuario.objects.all())
            usuarios_por_correo = {}
            usuarios_por_nombre = {}
            for cuenta in usuarios_jano:
                correo = texto(cuenta.email).casefold()
                if correo:
                    usuarios_por_correo.setdefault(correo, []).append(cuenta)
                nombre = clave_nombre_tokens(
                    f"{cuenta.first_name} {cuenta.last_name}"
                )
                if nombre:
                    usuarios_por_nombre.setdefault(nombre, []).append(cuenta)

            personas_por_nombre = {}
            for cedula, datos in personas.items():
                nombre = clave_nombre_tokens(datos.get("nombre_completo", ""))
                if nombre:
                    personas_por_nombre.setdefault(nombre, []).append(cedula)

            for cedula, datos in personas.items():
                valores = {k: v for k, v in datos.items() if v}
                perfil_seif = valores.pop("perfil_seif", "")
                valores.setdefault("tipo_persona", Funcionario.TipoPersona.INTERNO)
                persona, creada = Funcionario.objects.get_or_create(
                    cedula=cedula, defaults=valores
                )
                if not creada:
                    # Sincroniza el padrón que el usuario identifica como
                    # fuente vigente. Los campos vacíos del Excel no borran
                    # información existente. CONTROL solo aporta accesos y
                    # no debe pisar los datos del directorio.
                    cambio = False
                    campos_sincronizados = {
                        "nombre_completo", "cargo", "correo", "telefono",
                        "area", "extension_interna",
                    }
                    for campo, valor in valores.items():
                        if campo in campos_sincronizados and valor and getattr(persona, campo) != valor:
                            setattr(persona, campo, valor)
                            cambio = True
                    if cedula in cedulas_base_datos:
                        estado = datos["estado_persona"]
                        if persona.estado_persona != estado:
                            persona.estado_persona = estado
                            cambio = True
                    if cambio:
                        persona.save()
                if not persona.usuario_jano_id:
                    usuario_jano = Usuario.objects.filter(username=cedula).first()
                    if not usuario_jano:
                        correo = texto(datos.get("correo", "")).casefold()
                        candidatos = usuarios_por_correo.get(correo, []) if correo else []
                        if len(candidatos) == 1:
                            usuario_jano = candidatos[0]
                    if not usuario_jano:
                        nombre = clave_nombre_tokens(datos.get("nombre_completo", ""))
                        candidatos = usuarios_por_nombre.get(nombre, [])
                        personas_candidatas = personas_por_nombre.get(nombre, [])
                        if len(candidatos) == 1 and len(personas_candidatas) == 1:
                            usuario_jano = candidatos[0]
                    if usuario_jano and not Funcionario.objects.filter(
                        usuario_jano=usuario_jano
                    ).exclude(pk=persona.pk).exists():
                        persona.usuario_jano = usuario_jano
                        persona.save(update_fields=["usuario_jano", "actualizado_en"])
                personas_db[cedula] = persona

            plataformas = {}
            for cedula, nombre_plataforma, usuario, perfil_nombre in accesos:
                plataforma = plataformas.get(nombre_plataforma)
                if plataforma is None:
                    plataforma, _ = PlataformaAcceso.objects.get_or_create(
                        nombre=nombre_plataforma
                    )
                    plataformas[nombre_plataforma] = plataforma
                perfil = None
                if perfil_nombre:
                    perfil, _ = PerfilPlataforma.objects.get_or_create(
                        plataforma=plataforma,
                        nombre=perfil_nombre,
                    )
                acceso, creado = AccesoPlataforma.objects.get_or_create(
                    funcionario=personas_db[cedula],
                    plataforma=plataforma,
                    usuario=usuario,
                    defaults={
                        "perfil": perfil,
                        "perfil_texto": perfil_nombre,
                        "estado": AccesoPlataforma.Estado.PENDIENTE,
                        "fuente": AccesoPlataforma.Fuente.CONTROL_EXCEL,
                    },
                )
                if not creado and perfil and acceso.perfil_id is None:
                    acceso.perfil = perfil
                    acceso.perfil_texto = perfil_nombre
                    acceso.save(update_fields=["perfil", "perfil_texto", "actualizado_en"])

            for control in controles:
                persona = personas_db[control.pop("cedula")]
                existente = ControlSSIUsuario.objects.filter(
                    funcionario=persona,
                    proceso=control["proceso"],
                ).order_by("fecha_revision", "-creado_en").first()
                if existente:
                    for campo, valor in control.items():
                        if valor:
                            setattr(existente, campo, valor)
                    existente.save()
                else:
                    ControlSSIUsuario.objects.create(funcionario=persona, **control)

            for activo in activos_ssi:
                ActivoInformacionSSI.objects.get_or_create(
                    proceso=activo["proceso"],
                    activo=activo["activo"],
                    defaults=activo,
                )

            for categoria, valor, descripcion in catalogos:
                CatalogoSSI.objects.get_or_create(
                    categoria=categoria,
                    valor=valor,
                    defaults={"descripcion": descripcion},
                )

        self.stdout.write(self.style.SUCCESS(
            "Importación segura completada. No se importaron contraseñas ni secretos."
        ))
