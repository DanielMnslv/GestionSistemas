from django.apps import apps
from django.db import models

excluir = {"admin", "auth", "contenttypes", "sessions", "authtoken"}

for m in apps.get_models():
    if m._meta.app_label in excluir:
        continue

    relaciones = []

    for f in m._meta.get_fields():
        if not f.concrete:
            continue

        if isinstance(f, models.UUIDField):
            relaciones.append("UUID:" + f.name)
        elif f.is_relation and f.many_to_many:
            relaciones.append("M2M:" + f.name + "->" + f.related_model._meta.label)
        elif f.is_relation and f.one_to_one:
            relaciones.append("O2O:" + f.name + "->" + f.related_model._meta.label)
        elif f.is_relation and f.many_to_one:
            relaciones.append("FK:" + f.name + "->" + f.related_model._meta.label)

    print(
        m._meta.label,
        "| PK:", m._meta.pk.name,
        "|",
        "; ".join(relaciones)
    )
