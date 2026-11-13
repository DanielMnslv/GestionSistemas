from django.apps import AppConfig

# Texto de la opción vacía en las listas desplegables (Django trae "---------").
OPCION_VACIA = "Seleccione…"


def _opcion_vacia_clara():
    """Cambia "---------" por un texto claro en todos los formularios."""
    from django import forms
    from django.db.models import fields

    fields.BLANK_CHOICE_DASH[:] = [("", OPCION_VACIA)]
    original = forms.ModelChoiceField.__init__
    if getattr(original, "_opcion_vacia", False):
        return

    def __init__(self, queryset, *, empty_label=OPCION_VACIA, **kwargs):
        if empty_label == "---------":
            empty_label = OPCION_VACIA
        original(self, queryset, empty_label=empty_label, **kwargs)

    __init__._opcion_vacia = True
    forms.ModelChoiceField.__init__ = __init__


class InventarioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventario'

    def ready(self):
        from . import auditoria
        auditoria.conectar()
        _opcion_vacia_clara()
