from django.db import migrations


def _normalizar(texto):
    t = (texto or "").strip().lower()
    if not t:
        return ""
    if "baja" in t:
        return "Baja"
    if any(p in t for p in ("dañ", "malo", "defect", "falla")):
        return "Dañado"
    if "regular" in t or "desgast" in t:
        return "Regular"
    if any(p in t for p in ("bueno", "operativ", "excelente", "nuevo")):
        return "Operativo"
    return ""


def unificar(apps, schema_editor):
    """Une 'operativo' (S/N) y 'estado_radio' en un solo estado.

    El estado físico manda: Bueno -> Operativo (un radio sin cliente asignado
    figuraba como 'No operativo' pero está bien), Regular -> Regular y
    Dañado -> Dañado. Si no hay estado físico, S -> Operativo y N -> Dañado.
    Los radios dados de baja quedan en Baja.
    """
    Radio = apps.get_model("inventario", "Radio")
    Equipo = apps.get_model("inventario", "Equipo")
    for radio in Radio.objects.all():
        if not radio.activo:
            nuevo = "Baja"
        else:
            nuevo = _normalizar(radio.estado_radio)
            if not nuevo:
                nuevo = {"S": "Operativo", "N": "Dañado"}.get(
                    (radio.operativo or "").strip().upper(), ""
                )
        Radio.objects.filter(pk=radio.pk).update(estado_radio=nuevo)
        if radio.equipo_id:
            Equipo.objects.filter(pk=radio.equipo_id).update(
                estado_operativo={
                    "Operativo": "OPERATIVO", "Regular": "OPERATIVO",
                    "Dañado": "NO_OPERATIVO", "Baja": "NO_OPERATIVO",
                }.get(nuevo, "")
            )


def revertir(apps, schema_editor):
    Radio = apps.get_model("inventario", "Radio")
    for radio in Radio.objects.all():
        if radio.estado_radio in ("Dañado", "Baja"):
            Radio.objects.filter(pk=radio.pk).update(operativo="N")
        elif radio.estado_radio:
            Radio.objects.filter(pk=radio.pk).update(operativo="S")


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0021_quitar_id_inventario"),
    ]

    operations = [
        migrations.RunPython(unificar, revertir),
    ]
