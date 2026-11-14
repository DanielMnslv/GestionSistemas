"""Comando ``respaldar_bd``: copia la base de datos SQLite a una carpeta de respaldos y borra las copias automáticas más antiguas. Pensado para programarse a diario.

Uso: ``python manage.py respaldar_bd`` (opciones en ``--help``).
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


PATRON = "respaldo_auto_*.sqlite3"


class Command(BaseCommand):
    """Copia la base de datos SQLite a una carpeta de respaldos y borra las copias automáticas más antiguas. Pensado para programarse a diario."""
    help = (
        "Copia la base de datos SQLite a una carpeta de respaldos y borra "
        "las copias automáticas más antiguas. Pensado para programarse a "
        "diario."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--destino``: Carpeta de respaldos. Por defecto JANO_RESPALDOS_DIR o la carpeta respaldos/ del proyecto.
        - ``--conservar``: Cantidad de copias automáticas a conservar (por defecto 30).
        """
        parser.add_argument(
            "--destino",
            help=(
                "Carpeta de respaldos. Por defecto JANO_RESPALDOS_DIR o la "
                "carpeta respaldos/ del proyecto."
            ),
        )
        parser.add_argument(
            "--conservar",
            type=int,
            default=30,
            help="Cantidad de copias automáticas a conservar (por defecto 30).",
        )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
        if connection.vendor != "sqlite":
            raise CommandError("respaldar_bd solo funciona con SQLite.")
        if options["conservar"] < 1:
            raise CommandError("--conservar debe ser al menos 1.")

        destino = Path(
            options["destino"]
            or os.getenv("JANO_RESPALDOS_DIR")
            or Path(settings.BASE_DIR) / "respaldos"
        )
        destino.mkdir(parents=True, exist_ok=True)

        archivo = destino / (
            f"respaldo_auto_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
        )
        # La API de respaldo de SQLite copia de forma consistente aunque la
        # plataforma esté en uso.
        origen = sqlite3.connect(settings.DATABASES["default"]["NAME"])
        copia = sqlite3.connect(archivo)
        try:
            origen.backup(copia)
            resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copia.close()
            origen.close()

        if resultado != "ok":
            archivo.unlink(missing_ok=True)
            raise CommandError(f"La copia no pasó la verificación: {resultado}")

        antiguos = sorted(destino.glob(PATRON))[:-options["conservar"]]
        for viejo in antiguos:
            viejo.unlink()

        self.stdout.write(self.style.SUCCESS(
            f"Respaldo creado: {archivo} "
            f"({len(antiguos)} copia(s) antigua(s) eliminada(s))."
        ))
