from django.core.management.base import BaseCommand
from django.db import transaction

from inventario.google_sheet import leer_hoja, libro_del_sheet, texto_celda
from inventario.models import Cliente, Puesto

HOJA = "CLIENTES_PUESTOS"
COLUMNAS = ["idCliente", "NIT", "Nombre_Cliente", "Estado", "Sede", "ID Puestos", "NombrePuesto"]


class Command(BaseCommand):
    help = (
        "Importa el catálogo de clientes y puestos de la hoja CLIENTES_PUESTOS. "
        "Crea los nuevos y actualiza nombre, NIT, sede y estado de los "
        "existentes (por su id del Sheet). Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument("--confirmar", action="store_true", help="Guardar los cambios.")

    def handle(self, *args, **options):
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = leer_hoja(archivo, HOJA, COLUMNAS)

        clientes = {c.id_externo: c for c in Cliente.objects.exclude(id_externo=None)}
        puestos = {p.id_externo: p for p in Puesto.objects.exclude(id_externo=None)}
        datos_clientes, datos_puestos = {}, {}
        for f in filas:
            id_cliente = texto_celda(f["idCliente"])
            nombre = texto_celda(f["Nombre_Cliente"])
            if not id_cliente or not nombre:
                continue
            datos_clientes[id_cliente] = {
                "nit": texto_celda(f["NIT"])[:30],
                "nombre": nombre[:200],
                "activo": texto_celda(f["Estado"]).lower() != "inactivo",
            }
            id_puesto = texto_celda(f["ID Puestos"])
            nombre_puesto = texto_celda(f["NombrePuesto"])
            if id_puesto and nombre_puesto:
                datos_puestos[id_puesto] = {
                    "cliente": id_cliente,
                    "sede": texto_celda(f["Sede"])[:200],
                    "nombre": nombre_puesto[:200],
                }

        crear_c = [k for k in datos_clientes if k not in clientes]
        cambiar_c = [
            k for k, d in datos_clientes.items()
            if k in clientes and any(getattr(clientes[k], c) != v for c, v in d.items())
        ]
        crear_p = [k for k in datos_puestos if k not in puestos]
        cambiar_p = [
            k for k, d in datos_puestos.items()
            if k in puestos and (
                puestos[k].sede != d["sede"] or puestos[k].nombre != d["nombre"]
                or puestos[k].cliente.id_externo != d["cliente"]
            )
        ]
        self.stdout.write(f"Clientes a crear: {len(crear_c)} · a actualizar: {len(cambiar_c)}")
        self.stdout.write(f"Puestos a crear: {len(crear_p)} · a actualizar: {len(cambiar_p)}")
        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. Usa --confirmar para aplicar."
            ))
            return

        with transaction.atomic():
            for k in crear_c:
                clientes[k] = Cliente.objects.create(id_externo=k, **datos_clientes[k])
            for k in cambiar_c:
                for campo, valor in datos_clientes[k].items():
                    setattr(clientes[k], campo, valor)
                clientes[k].save()
            for k in crear_p + cambiar_p:
                d = dict(datos_puestos[k])
                d["cliente"] = clientes[d["cliente"]]
                if k in puestos:
                    for campo, valor in d.items():
                        setattr(puestos[k], campo, valor)
                    puestos[k].save()
                else:
                    Puesto.objects.create(id_externo=k, **d)
        self.stdout.write(self.style.SUCCESS("Catálogo de clientes y puestos actualizado."))
