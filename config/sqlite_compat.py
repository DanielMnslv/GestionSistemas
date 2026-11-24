"""Use the app-bundled SQLite build on Linux without changing system Python."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def configure_sqlite() -> None:
    """Prefer pysqlite3, optionally installed under ``.runtime/vendor``.

    Django 5.2 requires SQLite 3.31 or newer. Plesk's Python 3.10 runtime in
    production ships SQLite 3.26, so use the wheel bundled with the app. Local
    non-Linux development keeps using Python's standard sqlite3 module.
    """
    if not sys.platform.startswith("linux"):
        return

    vendor_path = Path(__file__).resolve().parent.parent / ".runtime" / "vendor"
    if vendor_path.is_dir() and str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))

    try:
        bundled_sqlite = importlib.import_module("pysqlite3")
    except ImportError as exc:
        raise RuntimeError(
            "JANO requiere pysqlite3-binary para ejecutar Django 5.2 en este "
            "servidor. Instala la dependencia en el entorno de la aplicación "
            "o en .runtime/vendor antes de iniciar Django."
        ) from exc

    sys.modules["sqlite3"] = bundled_sqlite
