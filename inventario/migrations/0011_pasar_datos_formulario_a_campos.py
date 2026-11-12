import re

from django.db import migrations


# Las entregas importadas del formulario de Google guardaron el estado del
# equipo, la cláusula y la firma como texto en observaciones_entrega, por
# ejemplo: "[Formulario Google] Estado al entregar: radio: Bueno; base: No
# tiene. Cláusula de confidencialidad: Sí. Firma: https://...". Aquí se
# pasan a los campos nuevos.
PREFIJO = "[Formulario Google]"
CAMPOS = {
    "radio": "estado_radio_entrega",
    "base": "estado_base_entrega",
    "cargador": "estado_cargador_entrega",
    "antena": "estado_antena_entrega",
    "baterías": "estado_baterias_entrega",
}
ESTADOS = re.compile(r"Estado al entregar: (.*?)\.(?= Cláusula| Firma|$)")
CLAUSULA = re.compile(
    r"Cláusula de confidencialidad: (.*?)\.(?= Firma|$)"
)
FIRMA = re.compile(r"Firma: (\S+)$")


def pasar_a_campos(apps, schema_editor):
    AsignacionRadio = apps.get_model("inventario", "AsignacionRadio")
    for asignacion in AsignacionRadio.objects.filter(
        observaciones_entrega__startswith=PREFIJO
    ):
        texto = asignacion.observaciones_entrega
        estados = ESTADOS.search(texto)
        if estados:
            for parte in estados.group(1).split("; "):
                nombre, _, valor = parte.partition(": ")
                if nombre in CAMPOS:
                    setattr(asignacion, CAMPOS[nombre], valor[:100])
        clausula = CLAUSULA.search(texto)
        if clausula:
            asignacion.clausula_aceptada = (
                clausula.group(1).strip().lower() in ("sí", "si")
            )
        firma = FIRMA.search(texto)
        if firma:
            asignacion.enlace_firma = firma.group(1)[:500]
        asignacion.observaciones_entrega = PREFIJO
        asignacion.save()


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0010_asignacion_estado_y_firma"),
    ]

    operations = [
        migrations.RunPython(pasar_a_campos, migrations.RunPython.noop),
    ]
