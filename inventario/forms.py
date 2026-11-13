
import base64
import binascii
import re

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from . import actividades_mantenimiento as act
from .google_sheet import normalizar_serial
from .orden import orden_placa
from .models import (
    AsignacionRadio,
    DetalleAlarma,
    DetalleComputador,
    DetalleGPS,
    DetalleImpresora,
    AsignacionEquipo,
    CambioGPS,
    Equipo,
    MantenimientoEquipo,
    MantenimientoProgramado,
    Funcionario,
    Cliente,
    Puesto,
    Radio,
    Vigilante,
)


def configurar_campo_equipo(campo):
    """Lista de equipos activos, ordenada por tipo y placa."""
    campo.queryset = Equipo.objects.filter(activo=True).order_by(
        "tipo", "placa"
    )
    campo.label_from_instance = lambda equipo: (
        f"{equipo.placa} · {equipo.get_tipo_display()} "
        f"{equipo.marca} {equipo.modelo}".strip()
    )


class _OpcionesConDatos:
    """Agrega atributos data-* a cada opción según su valor."""

    def __init__(self, *args, datos_opcion=None, **kwargs):
        self.datos_opcion = datos_opcion or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        opcion["attrs"].update(self.datos_opcion.get(str(value), {}))
        return opcion


class SelectConDatos(_OpcionesConDatos, forms.Select):
    pass


class CasillasConDatos(_OpcionesConDatos, forms.CheckboxSelectMultiple):
    pass


def _datos_casillas(catalogo, tipo_mantenimiento="*"):
    """data-te (tipo de equipo) y data-tm (tipo de mantenimiento) por clave."""
    datos = {
        clave: {"data-te": tipo, "data-tm": tipo_mantenimiento}
        for clave, tipo in act.tipo_de_clave(catalogo).items()
    }
    datos[act.OTROS[0]] = {"data-te": "*", "data-tm": "*"}
    return datos


class MantenimientoPorTipoMixin:
    """Primero el tipo de equipo; el equipo y las casillas dependen de él.

    El campo "tipo_equipo" no se guarda: filtra el desplegable de equipos y
    decide qué actividades se muestran. Si llega vacío (equipo fijo) se toma
    del equipo.
    """

    def _preparar_tipos(self):
        campo = self.fields["equipo"]
        configurar_campo_equipo(campo)
        campo.queryset = campo.queryset.filter(
            tipo__in=[t for t, _ in act.TIPOS_EQUIPO]
        )
        campo.widget = SelectConDatos(datos_opcion={
            str(pk): {"data-te": tipo}
            for pk, tipo in campo.queryset.values_list("pk", "tipo")
        })
        campo.widget.choices = campo.choices
        self.fields["tipo_equipo"] = forms.ChoiceField(
            label="Tipo de equipo", required=False,
            choices=[("", "Seleccione el tipo de equipo")] + act.TIPOS_EQUIPO,
        )
        orden = [f for f in self.fields if f != "tipo_equipo"]
        orden.insert(orden.index("equipo"), "tipo_equipo")
        self.order_fields(orden)

        equipo = self.initial.get("equipo") or (
            self.instance.equipo_id if self.instance and self.instance.pk else None
        )
        if equipo:
            pk = getattr(equipo, "pk", equipo)
            self.initial["tipo_equipo"] = (
                Equipo.objects.filter(pk=pk).values_list("tipo", flat=True).first() or ""
            )

        actual = self.instance.tipo if self.instance and self.instance.pk else ""
        inicial = self.initial.get("tipo") or ""
        permitidos = set(MantenimientoEquipo.TIPOS_FORMULARIO) | {actual, inicial}
        self.fields["tipo"].choices = [("", "Seleccione el tipo")] + [
            (v, l) for v, l in MantenimientoEquipo.Tipo.choices if v in permitidos
        ]

    def _validar_tipo_equipo(self, cleaned):
        equipo = cleaned.get("equipo")
        tipo_equipo = cleaned.get("tipo_equipo")
        if equipo is not None:
            if tipo_equipo and tipo_equipo != equipo.tipo:
                self.add_error("equipo", "El equipo no es del tipo seleccionado.")
            cleaned["tipo_equipo"] = equipo.tipo
        return cleaned.get("tipo_equipo") or ""

    def _casillas_ajenas(self, cleaned, campo, catalogo, tipo_equipo):
        sobran = set(cleaned.get(campo) or []) - act.claves_validas(catalogo, tipo_equipo)
        if tipo_equipo and sobran:
            self.add_error(campo, "Hay opciones que no corresponden a este tipo de equipo.")


class MantenimientoEquipoForm(MantenimientoPorTipoMixin, forms.ModelForm):
    tecnico_responsable = forms.ChoiceField(
        label="Especialista asignado",
        choices=[
            ("Yeiver Arcenio Prada Fierro", "Yeiver Arcenio Prada Fierro"),
            ("Daniel Felipe Jiménez Loaiza", "Daniel Felipe Jiménez Loaiza"),
        ],
    )
    actividades_preventivas = forms.MultipleChoiceField(
        label="Actividades realizadas", required=False,
        choices=act.CHOICES_PREVENTIVAS,
        widget=CasillasConDatos(datos_opcion=_datos_casillas(act.PREVENTIVAS)),
    )
    componentes_intervenidos = forms.MultipleChoiceField(
        label="Partes intervenidas", required=False,
        choices=act.CHOICES_CORRECTIVAS,
        widget=CasillasConDatos(datos_opcion=_datos_casillas(act.CORRECTIVAS)),
    )
    estados_entrega = forms.MultipleChoiceField(
        label="Estado de entrega del equipo", required=False,
        choices=MantenimientoEquipo.EstadoEntrega.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="Seleccione la(s) opción(es) que correspondan al resultado registrado.",
    )

    class Meta:
        model = MantenimientoEquipo
        fields = [
            "equipo", "fecha_intervencion", "tipo", "tecnico_responsable",
            "funcionario_responsable", "motivo", "diagnostico", "causa_dano",
            "actividades_preventivas", "actividad_preventiva_otros", "componentes_intervenidos",
            "trabajo_realizado",
            "repuestos_utilizados", "resultado", "estado_final", "estados_entrega",
            "observaciones",
        ]
        labels = {
            "tecnico_responsable": "Especialista asignado",
            "funcionario_responsable": "Funcionario responsable del equipo",
            "diagnostico": "Diagnóstico técnico",
            "causa_dano": "Posible causa del daño presentado",
            "trabajo_realizado": "Descripción de la actividad realizada",
            "actividad_preventiva_otros": "Describa otras actividades",
        }
        widgets = {
            "fecha_intervencion": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "motivo": forms.Textarea(attrs={"rows": 3}),
            "diagnostico": forms.Textarea(attrs={"rows": 3}),
            "causa_dano": forms.Textarea(attrs={"rows": 3}),
            "trabajo_realizado": forms.Textarea(attrs={"rows": 4}),
            "actividad_preventiva_otros": forms.Textarea(attrs={"rows": 2}),
            "repuestos_utilizados": forms.Textarea(attrs={"rows": 2}),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_intervencion"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["funcionario_responsable"].queryset = Funcionario.objects.filter(activo=True)
        self.fields["funcionario_responsable"].required = False
        self.fields["motivo"].required = False
        self.fields["trabajo_realizado"].required = False
        self.fields["causa_dano"].required = False
        self._preparar_tipos()
        if self.instance and self.instance.pk:
            self.initial["actividades_preventivas"] = self.instance.actividades_preventivas or []
            self.initial["componentes_intervenidos"] = self.instance.componentes_intervenidos or []
            self.initial["estados_entrega"] = self.instance.estados_entrega or []
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        tipo_equipo = self._validar_tipo_equipo(cleaned)
        if tipo != MantenimientoEquipo.Tipo.PREVENTIVO:
            cleaned["actividades_preventivas"] = []
            cleaned["actividad_preventiva_otros"] = ""
        if tipo != MantenimientoEquipo.Tipo.CORRECTIVO:
            cleaned["componentes_intervenidos"] = []
        if tipo == MantenimientoEquipo.Tipo.CORRECTIVO:
            if not cleaned.get("componentes_intervenidos"):
                self.add_error("componentes_intervenidos", "Seleccione al menos una parte intervenida.")
            self._casillas_ajenas(cleaned, "componentes_intervenidos", act.CORRECTIVAS, tipo_equipo)
            if not cleaned.get("trabajo_realizado"):
                self.add_error("trabajo_realizado", "Describa la actividad realizada.")
            if not cleaned.get("causa_dano"):
                self.add_error("causa_dano", "Describa la posible causa del daño.")
        elif tipo == MantenimientoEquipo.Tipo.PREVENTIVO:
            if not cleaned.get("actividades_preventivas"):
                self.add_error("actividades_preventivas", "Seleccione al menos una actividad.")
            self._casillas_ajenas(cleaned, "actividades_preventivas", act.PREVENTIVAS, tipo_equipo)
            if "otros" in (cleaned.get("actividades_preventivas") or []) and not cleaned.get("actividad_preventiva_otros"):
                self.add_error("actividad_preventiva_otros", "Describa las otras actividades realizadas.")
        return cleaned


class MantenimientoProgramadoForm(MantenimientoPorTipoMixin, forms.ModelForm):
    actividades = forms.MultipleChoiceField(
        label="Qué se va a revisar", required=False,
        choices=act.CHOICES_PREVENTIVAS[:-1] + act.CHOICES_CORRECTIVAS,
        widget=CasillasConDatos(datos_opcion={
            **_datos_casillas(act.PREVENTIVAS, "PREVENTIVO"),
            **_datos_casillas(act.CORRECTIVAS, "CORRECTIVO"),
        }),
    )

    class Meta:
        model = MantenimientoProgramado
        fields = [
            "equipo",
            "fecha_programada",
            "tipo",
            "actividades",
            "descripcion",
            "observaciones",
        ]
        labels = {"descripcion": "Descripción"}

        widgets = {
            "fecha_programada": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "descripcion": forms.Textarea(attrs={"rows": 3}),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._preparar_tipos()
        self.fields["descripcion"].required = False
        self.fields["descripcion"].help_text = (
            "Si la deja vacía, se arma con lo que marcó arriba."
        )
        if self.instance and self.instance.pk:
            self.initial["actividades"] = self.instance.actividades or []

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        tipo_equipo = self._validar_tipo_equipo(cleaned)
        catalogo = {
            MantenimientoEquipo.Tipo.PREVENTIVO: act.PREVENTIVAS,
            MantenimientoEquipo.Tipo.CORRECTIVO: act.CORRECTIVAS,
        }.get(tipo)
        if catalogo is None:
            cleaned["actividades"] = []
        else:
            self._casillas_ajenas(cleaned, "actividades", catalogo, tipo_equipo)
        if not (cleaned.get("descripcion") or "").strip():
            if cleaned.get("actividades"):
                cleaned["descripcion"] = "; ".join(act.textos(cleaned["actividades"])) + "."
            else:
                self.add_error(
                    "descripcion", "Marque lo que se va a revisar o describa el mantenimiento."
                )
        return cleaned

    def clean_fecha_programada(self):
        fecha = self.cleaned_data["fecha_programada"]

        if fecha < timezone.localdate():
            raise forms.ValidationError(
                "La fecha programada no puede estar en el pasado."
            )

        return fecha


# Texto que acepta el vigilante al recibir el radio. Reemplázalo por el
# texto oficial de la empresa cuando esté disponible.
CLAUSULA_CONFIDENCIALIDAD = (
    "Declaro que recibo el radio y sus accesorios en el estado indicado. "
    "Me comprometo a usarlo solo para la prestación del servicio, a "
    "cuidarlo y a devolverlo cuando se me solicite. Guardaré reserva sobre "
    "la información que se transmita por este medio y respondo por la "
    "pérdida o el daño causado por mal uso."
)

ESTADOS_COMPONENTE = [
    ("", "Seleccione"),
    ("Bueno", "Bueno"),
    ("Regular", "Regular"),
    ("Dañado", "Dañado"),
    ("No tiene", "No tiene"),
]

# Una firma dibujada pesa unos pocos KB; el límite evita cargas abusivas.
FIRMA_MAX_CARACTERES = 300_000


def validar_firma(firma):
    """La firma debe ser una imagen PNG en data URL de tamaño razonable."""
    prefijo = "data:image/png;base64,"
    if not firma.startswith(prefijo) or len(firma) > FIRMA_MAX_CARACTERES:
        raise forms.ValidationError("La firma no es válida.")
    try:
        base64.b64decode(firma[len(prefijo):], validate=True)
    except (binascii.Error, ValueError):
        raise forms.ValidationError("La firma no es válida.")
    return firma


class AsignacionRadioForm(forms.ModelForm):
    ESTADOS = [
        "estado_radio_entrega", "estado_base_entrega",
        "estado_cargador_entrega", "estado_antena_entrega",
        "estado_baterias_entrega",
    ]

    vigilante = forms.ModelChoiceField(
        queryset=Vigilante.objects.none(),
        label="Vigilante",
        required=True,
        empty_label="Seleccione un vigilante",
        help_text="Busca por cédula o nombre en la lista de vigilantes activos.",
    )

    class Meta:
        model = AsignacionRadio
        fields = [
            "radio",
            "coordinador_zona",
            "cliente_asignado",
            "puesto_asignado",
            "observaciones_entrega",
            "puesto",
            "estado_radio_entrega",
            "estado_base_entrega",
            "estado_cargador_entrega",
            "estado_antena_entrega",
            "estado_baterias_entrega",
            "clausula_aceptada",
            "firma",
        ]
        labels = {
            "radio": "Radio",
            "coordinador_zona": "Coordinador de zona",
            "cliente_asignado": "Cliente",
            "puesto_asignado": "Puesto asignado",
            "observaciones_entrega": "Observaciones de entrega",
            "puesto": "Puesto",
            "estado_radio_entrega": "Radio",
            "estado_base_entrega": "Base",
            "estado_cargador_entrega": "Cargador",
            "estado_antena_entrega": "Antena",
            "estado_baterias_entrega": "Baterías",
            "clausula_aceptada": "El vigilante acepta la cláusula",
        }
        widgets = {
            "observaciones_entrega": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for campo in self.ESTADOS:
            self.fields[campo] = forms.ChoiceField(
                label=self.Meta.labels[campo],
                choices=ESTADOS_COMPONENTE,
            )
        self.fields["clausula_aceptada"] = forms.BooleanField(
            label=self.Meta.labels["clausula_aceptada"],
            error_messages={
                "required": "El vigilante debe aceptar la cláusula.",
            },
        )
        self.fields["firma"] = forms.CharField(
            widget=forms.HiddenInput,
            error_messages={"required": "Falta la firma del vigilante."},
        )

        # Solo radios activos y sin una entrega vigente.
        self.fields["radio"].queryset = (
            Radio.objects.filter(activo=True)
            .exclude(asignaciones__estado=AsignacionRadio.Estado.ASIGNADO)
        )
        self.fields["radio"].queryset = orden_placa(
            self.fields["radio"].queryset
        )
        self.fields["radio"].label_from_instance = (
            lambda radio: (
                f"{radio.placa or 'Sin placa (' + radio.serial + ')'} - "
                f"{radio.marca} {radio.modelo}".strip()
            )
        )

        self.fields["vigilante"].queryset = (
            Vigilante.objects.filter(activo=True).order_by(
                "nombre_completo"
            )
        )
        self.fields["vigilante"].label_from_instance = (
            lambda vigilante: (
                f"{vigilante.cedula} - {vigilante.nombre_completo}"
            )
        )

        # Cliente y puesto se eligen del catálogo; los textos solo se
        # escriben a mano si el puesto no está en el catálogo.
        self.fields["cliente"] = forms.ModelChoiceField(
            queryset=Cliente.objects.filter(activo=True), required=False,
            label="Cliente", empty_label="Seleccione un cliente",
        )
        self.fields["puesto"].queryset = Puesto.objects.filter(
            activo=True
        ).select_related("cliente")
        self.fields["puesto"].required = False
        self.fields["puesto"].empty_label = "Seleccione primero el cliente"
        self.fields["cliente_asignado"].required = False
        self.fields["puesto_asignado"].required = False
        self.fields["cliente_asignado"].label = "Cliente (si no está en la lista)"
        self.fields["puesto_asignado"].label = "Puesto (si no está en la lista)"

        for nombre, field in self.fields.items():
            if nombre not in ("clausula_aceptada", "firma"):
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        datos = super().clean()
        puesto = datos.get("puesto")
        if puesto:
            datos["cliente_asignado"] = puesto.cliente.nombre[:200]
            datos["puesto_asignado"] = str(puesto)[:200]
        else:
            for campo in ("cliente_asignado", "puesto_asignado"):
                if not datos.get(campo):
                    self.add_error(
                        campo, "Elige el puesto de la lista o escríbelo."
                    )
        return datos

    def _post_clean(self):
        super()._post_clean()
        # clean() completa los textos desde el puesto; se pasan al modelo.
        for campo in ("cliente_asignado", "puesto_asignado"):
            if campo in self.cleaned_data:
                setattr(self.instance, campo, self.cleaned_data[campo])

    def clean_firma(self):
        return validar_firma(self.cleaned_data["firma"])

    def clean_radio(self):
        radio = self.cleaned_data["radio"]

        if AsignacionRadio.objects.filter(
            radio=radio,
            estado=AsignacionRadio.Estado.ASIGNADO,
        ).exists():
            raise forms.ValidationError(
                "Este radio ya tiene una asignación activa. "
                "Registra primero su devolución."
            )

        return radio

    def save(self, commit=True):
        asignacion = super().save(commit=False)
        vigilante = self.cleaned_data["vigilante"]

        asignacion.cedula_funcionario = vigilante.cedula

        if commit:
            asignacion.save()

        return asignacion


class RadioForm(forms.ModelForm):
    ESTADOS = [
        ("", "Sin dato"),
        ("Bueno", "Bueno"),
        ("Regular", "Regular"),
        ("Dañado", "Dañado"),
        ("No tiene", "No tiene"),
    ]
    ACCESORIOS = [
        "bateria_1", "bateria_2", "perilla_encendido", "perilla_frecuencia",
        "antena", "clip", "base", "cargador",
    ]

    class Meta:
        model = Radio
        fields = [
            "codigo_fisico", "placa", "serial",
            "marca", "modelo", "tipo_frecuencia", "modalidad_servicio",
            "estado_radio", "estado_base", "estado_cargador",
            "estado_antena", "estado_baterias",
            "estado_perilla_encendido", "estado_perilla_frecuencia", "estado_clip",
            "bateria_1", "bateria_2", "perilla_encendido",
            "perilla_frecuencia", "antena", "clip", "base", "cargador",
            "software_programacion", "version_software", "tipo_licencia",
            "licencia_software", "fecha_compra",
            "observaciones", "requiere_revision", "motivo_revision",
        ]
        labels = {
            "codigo_fisico": "Código físico",
            "placa": "Placa (RJ)",
            "serial": "Serial",
            "tipo_frecuencia": "Tipo de frecuencia",
            "modalidad_servicio": "Modalidad de servicio",
            "estado_radio": "Estado del radio",
            "estado_base": "Estado de la base",
            "estado_cargador": "Estado del cargador",
            "estado_antena": "Estado de la antena",
            "estado_baterias": "Estado de las baterías",
            "estado_perilla_encendido": "Estado de la perilla de encendido",
            "estado_perilla_frecuencia": "Estado de la perilla de frecuencia",
            "estado_clip": "Estado del clip",
            "bateria_1": "Batería 1",
            "bateria_2": "Batería 2",
            "perilla_encendido": "Perilla de encendido",
            "perilla_frecuencia": "Perilla de frecuencia",
            "software_programacion": "Software de programación",
            "version_software": "Versión del software",
            "tipo_licencia": "Tipo de licencia",
            "licencia_software": "Licencia de software",
            "fecha_compra": "Fecha de compra",
            "requiere_revision": "Requiere revisión",
            "motivo_revision": "Motivo de la revisión",
        }
        widgets = {
            "fecha_compra": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for campo in ("estado_radio", "estado_base", "estado_cargador",
                      "estado_antena", "estado_baterias",
                      "estado_perilla_encendido", "estado_perilla_frecuencia",
                      "estado_clip"):
            actual = getattr(self.instance, campo, "")
            if campo == "estado_radio":
                opciones = [("", "Sin dato"), *Radio.ESTADOS]
            else:
                opciones = list(self.ESTADOS)
            # Conserva valores libres que vienen de importaciones.
            if actual and actual not in dict(opciones):
                opciones.append((actual, actual))
            self.fields[campo] = forms.ChoiceField(
                label=self.Meta.labels[campo], choices=opciones,
                required=False,
            )
        for campo in self.ACCESORIOS:
            self.fields[campo] = forms.NullBooleanField(
                label=self.Meta.labels.get(campo, campo.capitalize()),
                required=False,
                widget=forms.Select(choices=[
                    ("unknown", "Sin dato"), ("true", "Sí tiene"),
                    ("false", "No tiene"),
                ]),
            )

        if not self.instance.pk:
            # La placa (RJ) es el identificador del radio.
            self.fields["placa"].required = True
        self.fields["fecha_compra"].input_formats = ["%Y-%m-%d"]

        for nombre, field in self.fields.items():
            if nombre != "requiere_revision":
                field.widget.attrs["class"] = "form-control"

    def clean_placa(self):
        placa = re.sub(r"\s+", "", self.cleaned_data["placa"]).upper()
        if placa and Radio.objects.filter(placa__iexact=placa).exclude(
            pk=self.instance.pk
        ).exists():
            raise forms.ValidationError("Otro radio ya tiene esta placa.")
        return placa

    def clean_serial(self):
        serial = self.cleaned_data["serial"].strip()
        clave = normalizar_serial(serial)
        if clave:
            for otro in Radio.objects.exclude(pk=self.instance.pk).exclude(
                serial=""
            ).only("placa", "serial"):
                if normalizar_serial(otro.serial) == clave:
                    raise forms.ValidationError(
                        f"Este serial ya está registrado en "
                        f"{otro.placa or 'otro radio sin placa'}."
                    )
        return serial


class RadioBajaForm(forms.Form):
    motivo_baja = forms.CharField(
        label="Motivo de la baja",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        max_length=1000,
    )


SEDE_PRINCIPAL = "SEGURIDAD JANO LTDA SEDE PRINCIPAL"


class EquipoForm(forms.ModelForm):
    """Datos comunes de cualquier equipo que no sea radio."""

    class Meta:
        model = Equipo
        fields = [
            "placa", "serial", "marca", "modelo", "propiedad",
            "fecha_compra", "estado_operativo", "responsable_nombre",
            "responsable_cedula", "ubicacion", "observaciones",
            "requiere_revision", "motivo_revision",
        ]
        labels = {
            "placa": "Placa",
            "estado_operativo": "Estado operativo",
            "fecha_compra": "Fecha de compra",
            "responsable_nombre": "Responsable",
            "responsable_cedula": "Cédula del responsable",
            "ubicacion": "Sede",
            "requiere_revision": "Requiere revisión",
            "motivo_revision": "Motivo de la revisión",
        }
        widgets = {
            "fecha_compra": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_compra"].input_formats = ["%Y-%m-%d"]
        # La sede se elige de la lista (sede principal y sedes de los puestos)
        # para que el equipo aparezca en el mapa "Dónde están los equipos".
        actual = (self.instance.ubicacion or "").strip()
        sedes = sorted(
            {s.strip() for s in Puesto.objects.filter(activo=True).values_list("sede", flat=True) if s.strip()}
            - {SEDE_PRINCIPAL}
        )
        opciones = [("", "Sin sede registrada"), (SEDE_PRINCIPAL, SEDE_PRINCIPAL)]
        if actual and actual != SEDE_PRINCIPAL and actual not in sedes:
            opciones.append((actual, actual))
        opciones += [(x, x) for x in sedes]
        self.fields["ubicacion"].widget = forms.Select(choices=opciones)
        self.fields["ubicacion"].help_text = "Con la sede, el equipo aparece en el mapa del inicio."
        if self.instance.pk:
            # La placa identifica al equipo en las importaciones y en T.MANT.
            self.fields["placa"].disabled = True
        for nombre, field in self.fields.items():
            if nombre != "requiere_revision":
                field.widget.attrs["class"] = "form-control"

    def clean_placa(self):
        placa = re.sub(r"\s+", "", self.cleaned_data["placa"]).upper()
        if Equipo.objects.filter(placa__iexact=placa).exclude(
            pk=self.instance.pk
        ).exists():
            raise forms.ValidationError("Otro equipo ya tiene esta placa.")
        return placa

    def clean_serial(self):
        serial = self.cleaned_data["serial"].strip()
        clave = normalizar_serial(serial)
        if clave:
            for otro in Equipo.objects.exclude(pk=self.instance.pk).exclude(
                serial=""
            ).only("placa", "serial"):
                if normalizar_serial(otro.serial) == clave:
                    raise forms.ValidationError(
                        f"Este serial ya está registrado en {otro.placa}."
                    )
        return serial


class DetalleForm(forms.ModelForm):
    """Base de los formularios de detalle por tipo."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
            if isinstance(field.widget, forms.DateInput):
                field.input_formats = ["%Y-%m-%d"]


class DetalleComputadorForm(DetalleForm):
    LICENCIAS = ["licencia_so", "licencia_antivirus", "licencia_office"]

    class Meta:
        model = DetalleComputador
        exclude = ["equipo"]
        labels = {
            "velocidad_procesador": "Velocidad del procesador",
            "tipo_disco": "Tipo de disco",
            "capacidad_disco": "Capacidad del disco",
            "tipo_ram": "Tipo de RAM",
            "capacidad_ram": "Capacidad de RAM",
            "monitor_serial": "Serial del monitor",
            "monitor_modelo": "Marca y modelo del monitor",
            "monitor2_serial": "Serial del monitor 2",
            "monitor2_modelo": "Marca y modelo del monitor 2",
            "ups_serial": "Serial de la UPS",
            "ups_modelo": "Marca y modelo de la UPS",
            "telefono_ip_serial": "Serial del teléfono IP",
            "telefono_ip_modelo": "Marca y modelo del teléfono IP",
            "sistema_operativo": "Sistema operativo",
            "licencia_so": "Licencia del sistema operativo",
            "licencia_antivirus": "Licencia del antivirus",
            "vencimiento_antivirus": "Vencimiento del antivirus",
            "licencia_office": "Licencia de Office",
            "software_licenciado": "Otro software licenciado",
            "software_libre": "Software libre",
            "mac_ethernet": "MAC Ethernet",
            "mac_wifi": "MAC Wi-Fi",
            "ip_ethernet": "IP Ethernet",
            "ip_wifi": "IP Wi-Fi",
            "imei": "IMEI",
            "linea_celular": "Línea celular",
        }
        widgets = {
            "vencimiento_antivirus": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "software_licenciado": forms.Textarea(attrs={"rows": 2}),
            "software_libre": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, ver_licencias=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not ver_licencias:
            # Sin el permiso, las claves ni se muestran ni se modifican.
            for campo in self.LICENCIAS:
                del self.fields[campo]


class DetalleImpresoraForm(DetalleForm):
    class Meta:
        model = DetalleImpresora
        exclude = ["equipo"]
        labels = {"clase": "Tipo (láser, tinta, multifuncional…)"}


class DetalleGPSForm(DetalleForm):
    class Meta:
        model = DetalleGPS
        exclude = ["equipo", "fecha_asignacion"]
        labels = {
            "imei": "IMEI",
            "linea": "Línea",
            "placa_vehiculo": "Placa del vehículo",
            "nombre_vehiculo": "Nombre del vehículo",
            "plataforma": "Estado en la plataforma",
        }


class DetalleAlarmaForm(DetalleForm):
    componentes_texto = forms.CharField(
        label="Componentes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Uno por línea: nombre; cantidad; estado. "
                  "Ejemplo: Sensores; 4; Bueno",
    )

    class Meta:
        model = DetalleAlarma
        exclude = ["equipo", "componentes"]
        labels = {
            "clase": "Tipo de alarma",
            "reporta_central": "Reporta a la central",
            "serial_comunicador": "Serial del comunicador",
            "estado_comunicador": "Estado del comunicador",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["componentes_texto"].initial = "\n".join(
            "{}; {}; {}".format(
                c.get("nombre", ""), c.get("cantidad", ""), c.get("estado", "")
            )
            for c in self.instance.componentes or []
        )

    def clean_componentes_texto(self):
        componentes = []
        for numero, linea in enumerate(
            self.cleaned_data["componentes_texto"].splitlines(), start=1
        ):
            if not linea.strip():
                continue
            partes = [p.strip() for p in linea.split(";")]
            if len(partes) != 3 or not partes[1].isdigit():
                raise forms.ValidationError(
                    f"Línea {numero}: usa el formato nombre; cantidad; estado."
                )
            componentes.append({
                "nombre": partes[0], "cantidad": int(partes[1]),
                "estado": partes[2],
            })
        return componentes

    def save(self, commit=True):
        self.instance.componentes = self.cleaned_data["componentes_texto"]
        return super().save(commit=commit)


FORMULARIOS_DETALLE = {
    Equipo.Tipo.COMPUTADOR: DetalleComputadorForm,
    Equipo.Tipo.TABLETA: DetalleComputadorForm,
    Equipo.Tipo.IMPRESORA: DetalleImpresoraForm,
    Equipo.Tipo.ESCANER: DetalleImpresoraForm,
    Equipo.Tipo.GPS: DetalleGPSForm,
    Equipo.Tipo.ALARMA: DetalleAlarmaForm,
}


# Texto que acepta el funcionario al recibir un equipo. Reemplázalo por el
# texto oficial de la empresa cuando esté disponible.
CLAUSULA_EQUIPOS = (
    "Declaro que recibo el equipo y los accesorios descritos en buen estado. "
    "Me comprometo a usarlo solo para las funciones de mi cargo, a cuidarlo, "
    "a no instalar software sin autorización del área de TI, a guardar "
    "reserva sobre la información de la empresa que maneje en él y a "
    "devolverlo cuando se me solicite. Respondo por la pérdida o el daño "
    "causado por mal uso."
)


class AsignacionEquipoForm(forms.ModelForm):
    class Meta:
        model = AsignacionEquipo
        fields = [
            "funcionario", "area", "accesorios", "observaciones_entrega",
            "clausula_aceptada", "firma",
        ]
        labels = {
            "funcionario": "Funcionario que recibe",
            "area": "Área o sede",
            "accesorios": "Accesorios entregados",
            "observaciones_entrega": "Observaciones de entrega",
            "clausula_aceptada": "El funcionario acepta la cláusula",
        }
        widgets = {
            "accesorios": forms.Textarea(attrs={"rows": 2}),
            "observaciones_entrega": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["funcionario"].required = True
        self.fields["funcionario"].queryset = Funcionario.objects.filter(
            activo=True
        ).order_by("nombre_completo")
        self.fields["funcionario"].label_from_instance = (
            lambda f: f"{f.nombre_completo} · {f.cedula}"
        )
        self.fields["clausula_aceptada"] = forms.BooleanField(
            label=self.Meta.labels["clausula_aceptada"],
            error_messages={"required": "El funcionario debe aceptar la cláusula."},
        )
        self.fields["firma"] = forms.CharField(
            widget=forms.HiddenInput,
            error_messages={"required": "Falta la firma del funcionario."},
        )
        for nombre, field in self.fields.items():
            if nombre not in ("clausula_aceptada", "firma"):
                field.widget.attrs["class"] = "form-control"

    def clean_firma(self):
        return validar_firma(self.cleaned_data["firma"])


class CambioGPSForm(forms.ModelForm):
    class Meta:
        model = CambioGPS
        fields = [
            "dato_actualizado", "linea", "operador", "placa_vehiculo",
            "nombre_vehiculo", "observaciones",
        ]
        labels = {
            "dato_actualizado": "¿Qué cambia?",
            "linea": "Línea",
            "placa_vehiculo": "Placa del vehículo",
            "nombre_vehiculo": "Nombre del vehículo",
        }
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dato_actualizado"] = forms.ChoiceField(
            label=self.Meta.labels["dato_actualizado"],
            choices=[
                ("Vehículo", "Vehículo"),
                ("Línea", "Línea"),
                ("Vehículo y línea", "Vehículo y línea"),
                ("Otro", "Otro"),
            ],
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class VerificacionPoliticaForm(forms.Form):
    especialista = forms.CharField(label="Especialista que verifica", max_length=200)
    responsable = forms.CharField(
        label="Funcionario responsable del equipo", max_length=200, required=False
    )
    observaciones = forms.CharField(
        label="Observaciones", required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    actualizacion = forms.CharField(
        label="Actualizaciones realizadas (antivirus, Office, Windows…)",
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        from .politica import CUMPLE, PUNTOS, RESPUESTAS

        super().__init__(*args, **kwargs)
        for clave, texto in PUNTOS:
            self.fields[f"punto_{clave}"] = forms.ChoiceField(
                label=texto, choices=RESPUESTAS, initial=CUMPLE,
                widget=forms.RadioSelect,
            )
        for nombre, field in self.fields.items():
            if not nombre.startswith("punto_"):
                field.widget.attrs["class"] = "form-control"

    def puntos(self):
        return [self[n] for n in self.fields if n.startswith("punto_")]

    def respuestas(self):
        return {
            nombre.removeprefix("punto_"): valor
            for nombre, valor in self.cleaned_data.items()
            if nombre.startswith("punto_")
        }


class RenovacionAntivirusForm(forms.Form):
    antivirus = forms.CharField(label="Antivirus instalado", max_length=150)
    licencia = forms.CharField(label="Licencia", max_length=200, required=False)
    vencimiento = forms.DateField(
        label="Fecha de vencimiento",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


