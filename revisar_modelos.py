from django.apps import apps

nombres = [
    "Equipo",
    "Radio",
    "MantenimientoEquipo",
    "AsignacionRadio",
    "AsignacionEquipo",
    "Puesto",
    "Funcionario",
    "Cliente",
    "DetalleComputador",
    "DetalleImpresora",
    "DetalleGPS",
    "DetalleAlarma",
    "CambioGPS",
    "VerificacionPolitica",
]

app = apps.get_app_config("inventario")

for nombre in nombres:
    modelo = app.get_model(nombre)

    print("\n" + "=" * 60)
    print("MODELO:", nombre)
    print("=" * 60)

    for campo in modelo._meta.get_fields():
        if not campo.concrete:
            continue

        tipo = campo.__class__.__name__
        relacion = ""

        if campo.is_relation and campo.related_model:
            relacion = " -> " + campo.related_model.__name__

        print(f"{campo.name}: {tipo}{relacion}")