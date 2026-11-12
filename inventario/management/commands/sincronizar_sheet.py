from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand

from inventario.google_sheet import libro_del_sheet


class Command(BaseCommand):
    help = (
        "Descarga el Google Sheet una vez y ejecuta, en orden, la "
        "importación de radios, equipos de TI, entregas y mantenimientos. "
        "Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--usuario",
            required=True,
            help="Usuario responsable de las asignaciones y mantenimientos.",
        )
        parser.add_argument(
            "--archivo",
            help="Ruta a un .xlsx exportado del Google Sheet.",
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Guardar los cambios.",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Sincronización {datetime.now():%Y-%m-%d %H:%M}")
        extra = ["--confirmar"] if options["confirmar"] else []

        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            # Los equipos van primero: las entregas y los mantenimientos se
            # cruzan con las placas que esas importaciones completan.
            usuario = ["--usuario", options["usuario"]]
            pasos = [
                ("Clientes y puestos", "importar_clientes_sheet", []),
                ("Radios", "importar_radios_sheet", []),
                ("Equipos de TI", "importar_equipos_sheet", []),
                ("Entregas de radios", "importar_asignaciones_sheet", usuario),
                ("Entregas de equipos y GPS",
                 "importar_entregas_equipos_sheet", usuario),
                ("Mantenimientos", "importar_mantenimientos_sheet", usuario),
                ("Política de seguridad", "importar_politica_sheet", []),
                ("Renovaciones de antivirus", "importar_antivirus_sheet", []),
            ]
            for titulo, comando, argumentos in pasos:
                self.stdout.write(f"\n=== {titulo} ===")
                call_command(
                    comando,
                    "--archivo", str(archivo),
                    *argumentos,
                    *extra,
                    stdout=self.stdout,
                    stderr=self.stderr,
                )
