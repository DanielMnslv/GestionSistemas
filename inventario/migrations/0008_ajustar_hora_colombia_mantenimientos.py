from datetime import timedelta

from django.db import migrations
from django.db.models import F


# Hasta esta migración TIME_ZONE era UTC: las horas digitadas en el
# formulario y las fechas importadas de Excel se guardaron como si fueran
# UTC, aunque eran hora de Colombia (UTC-5). Al pasar a America/Bogota se
# corrigen sumando 5 horas, para que se sigan viendo igual.
DESFASE = timedelta(hours=5)


def a_hora_colombia(apps, schema_editor):
    MantenimientoRadio = apps.get_model("inventario", "MantenimientoRadio")
    MantenimientoRadio.objects.update(
        fecha_intervencion=F("fecha_intervencion") + DESFASE
    )


def a_utc(apps, schema_editor):
    MantenimientoRadio = apps.get_model("inventario", "MantenimientoRadio")
    MantenimientoRadio.objects.update(
        fecha_intervencion=F("fecha_intervencion") - DESFASE
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0007_vigilante"),
    ]

    operations = [
        migrations.RunPython(a_hora_colombia, a_utc),
    ]
