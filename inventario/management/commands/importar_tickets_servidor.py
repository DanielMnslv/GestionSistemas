"""Carga los tickets exportados del JANO antiguo (exportar_tickets_servidor.py).

    manage.py importar_tickets_servidor tickets_servidor.json            # revisar
    manage.py importar_tickets_servidor tickets_servidor.json --guardar  # cargar

- Los equipos se buscan por placa, las personas por cédula y los usuarios
  por nombre de usuario. Si algo no existe aquí, el caso se carga sin ese
  vínculo (y queda anotado en la bitácora).
- Se conserva el número y el enlace (token) de cada caso. Los que ya
  existen aquí no se repiten, así que se puede correr más de una vez.
- No envía correos.
"""
import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime

from inventario.models import Equipo, EventoTicket, FotoTicket, Funcionario, Ticket


def _valores(modelo, datos):
    """Solo los campos simples del modelo, con fechas convertidas."""
    resultado = {}
    for campo in modelo._meta.concrete_fields:
        if campo.is_relation or campo.name == "id" or campo.name not in datos:
            continue
        valor = datos[campo.name]
        tipo = campo.get_internal_type()
        if valor and tipo == "DateTimeField":
            valor = parse_datetime(valor)
        elif valor and tipo == "DateField":
            valor = parse_date(valor)
        elif valor and tipo == "UUIDField":
            valor = uuid.UUID(str(valor))
        resultado[campo.name] = valor
    return resultado


class Command(BaseCommand):
    help = "Carga los tickets exportados del servidor antiguo."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--guardar", action="store_true", help="Cargar (sin esto solo revisa).")

    def handle(self, archivo, guardar=False, **opciones):
        try:
            with open(archivo, encoding="utf-8") as f:
                casos = json.load(f)["tickets"]
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(f"No se pudo leer {archivo}: {error}")

        User = get_user_model()
        usuarios = {u.get_username(): u for u in User.objects.all()}
        equipos = {e.placa.upper(): e for e in Equipo.objects.all()}
        personas = {p.cedula: p for p in Funcionario.objects.all()}
        numeros = set(Ticket.objects.values_list("numero", flat=True))
        tokens = {str(t) for t in Ticket.objects.values_list("token", flat=True)}

        nuevos, repetidos, sin_equipo = [], 0, 0
        for d in casos:
            if d.get("numero") in numeros:
                repetidos += 1
                continue
            if d.get("equipo_placa") and d["equipo_placa"].upper() not in equipos:
                sin_equipo += 1
            nuevos.append(d)

        self.stdout.write(
            f"En el archivo: {len(casos)}\n  Nuevos: {len(nuevos)}\n"
            f"  Ya estaban: {repetidos}\n  Con placa que no existe aquí: {sin_equipo}"
        )
        if not guardar:
            self.stdout.write(self.style.WARNING("Modo de revisión: no se cargó nada. Usa --guardar."))
            return

        with transaction.atomic():
            for d in nuevos:
                valores = _valores(Ticket, d)
                if str(valores.get("token")) in tokens:
                    valores.pop("token")
                placa = (d.get("equipo_placa") or "").upper()
                ticket = Ticket(
                    **valores,
                    equipo=equipos.get(placa),
                    funcionario=personas.get(d.get("funcionario_cedula") or ""),
                    tecnico=usuarios.get(d.get("tecnico") or ""),
                    creado_por=usuarios.get(d.get("creado_por") or ""),
                )
                ticket.save()
                for e in d.get("eventos", []):
                    EventoTicket.objects.create(
                        ticket=ticket, usuario=usuarios.get(e.get("usuario") or ""),
                        **_valores(EventoTicket, e),
                    )
                for foto in d.get("fotos", []):
                    datos_foto = _valores(FotoTicket, foto)
                    datos_foto.pop("archivo", None)
                    FotoTicket.objects.create(
                        ticket=ticket, archivo=foto.get("archivo", ""),
                        subido_por=usuarios.get(foto.get("subido_por") or ""), **datos_foto,
                    )
                if placa and placa not in equipos:
                    EventoTicket.objects.create(
                        ticket=ticket, tipo=EventoTicket.Tipo.COMENTARIO, publico=False,
                        texto=f"Importado del servidor: el equipo {placa} no existe en este inventario.",
                    )
        self.stdout.write(self.style.SUCCESS(f"Cargados {len(nuevos)} tickets."))
