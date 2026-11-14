"""Crea la cuenta de cada funcionario activo para el portal Mi soporte.

- Usuario: la cédula. Rol: Solicitante. Sin contraseña: el funcionario la
  crea con el enlace que le llega al correo.
- No toca cuentas que ya existen (solo les agrega el rol si se pide).
- Sin --enviar no crea nada ni manda correos: solo muestra el resumen.

Ejemplos:
    manage.py crear_cuentas_solicitantes                 # ver qué haría
    manage.py crear_cuentas_solicitantes --enviar        # crear y enviar
    manage.py crear_cuentas_solicitantes --cedula 123 --enviar   # una persona
"""
import time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from inventario.models import Funcionario
from inventario.permisos import SOLICITANTE
from usuarios.cuenta import enviar_bienvenida


class Command(BaseCommand):
    """Crea las cuentas de los funcionarios (rol Solicitante) y envía el enlace de contraseña."""
    help = "Crea las cuentas de los funcionarios (rol Solicitante) y envía el enlace de contraseña."

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--enviar``: Crear las cuentas y enviar los correos.
        - ``--cedula``: Solo estas cédulas.
        - ``--reenviar``: Reenviar el enlace a cuentas ya creadas que aún no tienen contraseña.
        - ``--pausa``: Segundos entre correos.
        """
        parser.add_argument("--enviar", action="store_true", help="Crear las cuentas y enviar los correos.")
        parser.add_argument("--cedula", action="append", default=[], help="Solo estas cédulas.")
        parser.add_argument("--reenviar", action="store_true",
                            help="Reenviar el enlace a cuentas ya creadas que aún no tienen contraseña.")
        parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre correos.")

    def handle(self, *args, **opciones):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--enviar`` solo muestra lo que haría; no envía correos.
        """
        User = get_user_model()
        enviar = opciones["enviar"]
        grupo = Group.objects.get_or_create(name=SOLICITANTE)[0] if enviar else None
        personas = Funcionario.objects.filter(activo=True).order_by("nombre_completo")
        if opciones["cedula"]:
            personas = personas.filter(cedula__in=opciones["cedula"])

        nuevas, reenvios, sin_correo, existentes, errores = [], [], [], [], []
        for f in personas:
            if not f.correo:
                sin_correo.append(f)
                continue
            usuario = User.objects.filter(username=f.cedula).first()
            if usuario is not None:
                if opciones["reenviar"] and not usuario.has_usable_password() and usuario.is_active:
                    reenvios.append((f, usuario))
                else:
                    existentes.append(f)
                continue
            nuevas.append((f, None))

        self.stdout.write(
            f"Funcionarios activos revisados: {personas.count()}\n"
            f"  Cuentas nuevas: {len(nuevas)}\n"
            f"  Reenvío de enlace: {len(reenvios)}\n"
            f"  Ya tenían cuenta: {len(existentes)}\n"
            f"  Sin correo (no se puede enviar el enlace): {len(sin_correo)}"
        )
        if not enviar:
            self.stdout.write(self.style.WARNING(
                "Modo de revisión: no se creó nada ni se envió ningún correo. Usa --enviar para hacerlo."
            ))
            return

        for f, usuario in nuevas + reenvios:
            try:
                with transaction.atomic():
                    if usuario is None:
                        partes = f.nombre_completo.split()
                        usuario = User(
                            username=f.cedula, email=f.correo,
                            first_name=" ".join(partes[:2])[:150] if partes else "",
                            is_active=True,
                        )
                        usuario.set_unusable_password()
                        usuario.save()
                        usuario.groups.add(grupo)
                    enviar_bienvenida(usuario, f.nombre_completo)
            except Exception as error:  # Un correo malo no detiene a los demás.
                errores.append((f, error))
                continue
            if opciones["pausa"]:
                time.sleep(opciones["pausa"])

        enviados = len(nuevas) + len(reenvios) - len(errores)
        self.stdout.write(self.style.SUCCESS(f"Correos enviados: {enviados}"))
        for f, error in errores:
            self.stdout.write(self.style.ERROR(f"No se pudo con la cédula {f.cedula}: {error}"))
