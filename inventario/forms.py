"""Formularios de JANO Inventario.

Cada formulario valida lo que el usuario escribe antes de guardarlo y aplica
las reglas de negocio: placas y seriales sin repetir, una sola entrega vigente
por equipo, actividades de mantenimiento según el tipo de equipo, firma válida
en las actas, fechas de visita que no estén en el pasado, etc.

Grupos:
- Mantenimiento: MantenimientoEquipoForm, MantenimientoProgramadoForm.
- Radios: RadioForm, RadioBajaForm, AsignacionRadioForm (entrega a un puesto).
- Equipos: EquipoForm y los formularios de detalle por tipo
  (DetalleComputadorForm, DetalleImpresoraForm, DetalleGPSForm,
  DetalleAlarmaForm), AsignacionEquipoForm, CambioGPSForm.
- Seguridad: VerificacionPoliticaForm, RenovacionAntivirusForm.
- Mesa de ayuda: TicketForm, AsignarTicketForm, AtencionTicketForm,
  IntervencionTicketForm, TextoTicketForm, CedulaSoporteForm, SoporteForm,
  ReabrirForm.
"""

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
    Sede,
    Radio,
    Ticket,
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
        """Recibe ``datos_opcion``: {valor: {atributo: valor}} para cada opción."""
        self.datos_opcion = datos_opcion or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        """Agrega a la opción sus atributos ``data-*`` (los usa el JavaScript del formulario)."""
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        opcion["attrs"].update(self.datos_opcion.get(str(value), {}))
        return opcion


class SelectConDatos(_OpcionesConDatos, forms.Select):
    """Lista desplegable cuyas opciones llevan atributos ``data-*`` (por ejemplo, el tipo de cada equipo)."""
    pass


class CasillasConDatos(_OpcionesConDatos, forms.CheckboxSelectMultiple):
    """Casillas múltiples cuyas opciones llevan atributos ``data-*``.

    Permite mostrar solo las actividades que aplican al tipo de equipo elegido.
    """
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
        """Limita el campo ``equipo`` a los tipos con mantenimiento y marca cada opción con su tipo.

        Así la pantalla muestra solo las actividades y partes que corresponden
        al equipo seleccionado.
        """
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
        """Comprueba que el equipo sea del tipo elegido y devuelve el tipo final.

        Si hay equipo, su tipo manda sobre lo que se haya escogido en la lista.
        """
        equipo = cleaned.get("equipo")
        tipo_equipo = cleaned.get("tipo_equipo")
        if equipo is not None:
            if tipo_equipo and tipo_equipo != equipo.tipo:
                self.add_error("equipo", "El equipo no es del tipo seleccionado.")
            cleaned["tipo_equipo"] = equipo.tipo
        return cleaned.get("tipo_equipo") or ""

    def _casillas_ajenas(self, cleaned, campo, catalogo, tipo_equipo):
        """Marca error si en ``campo`` hay opciones que no aplican a ``tipo_equipo``."""
        sobran = set(cleaned.get(campo) or []) - act.claves_validas(catalogo, tipo_equipo)
        if tipo_equipo and sobran:
            self.add_error(campo, "Hay opciones que no corresponden a este tipo de equipo.")


class MantenimientoEquipoForm(MantenimientoPorTipoMixin, forms.ModelForm):
    """Registro o edición de una intervención de mantenimiento.

    Reglas:
        - El especialista se elige de la lista de técnicos de TIC.
        - Las actividades preventivas solo se guardan en un preventivo; las
          partes intervenidas, solo en un correctivo.
        - Solo se aceptan actividades y partes que correspondan al tipo de
          equipo (ver ``inventario/actividades_mantenimiento.py``).
    """
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
        """Ajusta formatos de fecha, deja opcionales los textos que dependen del tipo
        y carga las actividades ya marcadas al editar.
        """
        super().__init__(*args, **kwargs)
        self.fields["fecha_intervencion"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["funcionario_responsable"].queryset = Funcionario.objects.filter(activo=True)
        self.fields["funcionario_responsable"].required = False
        self.fields["motivo"].required = False
        self.fields["trabajo_realizado"].required = False
        self.fields["causa_dano"].required = False
        self._preparar_tipos()
        # Los registros importados del Sheet no traen actividades, partes ni
        # causa del daño: al corregirlos no se exige completarlos.
        self.exigir_detalle = not (self.instance.pk and self.instance.origen_archivo)
        if self.instance and self.instance.pk:
            self.initial["actividades_preventivas"] = self.instance.actividades_preventivas or []
            self.initial["componentes_intervenidos"] = self.instance.componentes_intervenidos or []
            self.initial["estados_entrega"] = self.instance.estados_entrega or []
            self._preparar_edicion()
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

    def _preparar_edicion(self):
        """Ajustes al corregir una intervención ya registrada.

        - El equipo no se cambia (aunque esté de baja o su tipo ya no tenga
          mantenimiento): una intervención mal asignada se borra y se
          registra de nuevo en el equipo correcto.
        - Se aceptan el especialista y el funcionario guardados aunque ya no
          estén en las listas (registros importados del Sheet o funcionarios
          retirados), para no obligar a cambiarlos al corregir otro dato.
        """
        equipo = self.instance.equipo
        campo = self.fields["equipo"]
        campo.queryset = Equipo.objects.filter(pk=equipo.pk)
        campo.widget.datos_opcion = {str(equipo.pk): {"data-te": equipo.tipo}}
        campo.widget.choices = campo.choices
        campo.disabled = True
        tipos = self.fields["tipo_equipo"]
        if equipo.tipo not in dict(tipos.choices):
            tipos.choices = list(tipos.choices) + [(equipo.tipo, equipo.get_tipo_display())]
        self.initial["tipo_equipo"] = equipo.tipo

        tecnico = self.instance.tecnico_responsable
        opciones = self.fields["tecnico_responsable"].choices
        if tecnico and tecnico not in dict(opciones):
            self.fields["tecnico_responsable"].choices = list(opciones) + [(tecnico, tecnico)]

        if self.instance.funcionario_responsable_id:
            campo = self.fields["funcionario_responsable"]
            campo.queryset = Funcionario.objects.filter(
                Q(activo=True) | Q(pk=self.instance.funcionario_responsable_id)
            )

    def clean(self):
        """Valida el conjunto según el tipo de mantenimiento.

        Borra lo que no aplica al tipo (actividades o partes) y exige los datos
        mínimos de cada clase de intervención.
        """
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        tipo_equipo = self._validar_tipo_equipo(cleaned)
        if tipo != MantenimientoEquipo.Tipo.PREVENTIVO:
            cleaned["actividades_preventivas"] = []
            cleaned["actividad_preventiva_otros"] = ""
        if tipo != MantenimientoEquipo.Tipo.CORRECTIVO:
            cleaned["componentes_intervenidos"] = []
        if not self.exigir_detalle:
            # Registro importado: lo marcado se valida, pero nada es obligatorio.
            self._casillas_ajenas(cleaned, "componentes_intervenidos", act.CORRECTIVAS, tipo_equipo)
            self._casillas_ajenas(cleaned, "actividades_preventivas", act.PREVENTIVAS, tipo_equipo)
        elif tipo == MantenimientoEquipo.Tipo.CORRECTIVO:
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
    """Programación de una visita de mantenimiento.

    Se marcan las actividades que se van a revisar; si la descripción queda
    vacía, se arma con ellas. La fecha no puede estar en el pasado.
    """
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
        """Prepara la lista de equipos por tipo y carga las actividades al editar."""
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
        """Deja solo las actividades válidas para el tipo de mantenimiento y de equipo
        y arma la descripción si no se escribió.
        """
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
        """Rechaza fechas anteriores a hoy."""
        fecha = self.cleaned_data["fecha_programada"]

        if fecha < timezone.localdate():
            raise forms.ValidationError(
                "La fecha programada no puede estar en el pasado."
            )

        return fecha


# Texto que acepta el supervisor al recibir el radio. Reemplázalo por el
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
    """Entrega de un radio a un puesto de un cliente (acta de entrega).

    Recibe el supervisor del puesto (cédula opcional). Se registra el estado de
    cada pieza, la aceptación de la cláusula y la firma dibujada.

    Reglas:
        - El radio no puede tener otra entrega vigente.
        - Si se elige un puesto del catálogo, el cliente y el puesto se copian
          de él; si no, hay que escribirlos.
    """

    ESTADOS = [
        "estado_radio_entrega", "estado_base_entrega",
        "estado_cargador_entrega", "estado_antena_entrega",
        "estado_baterias_entrega",
    ]

    class Meta:
        model = AsignacionRadio
        fields = [
            "radio",
            "coordinador_zona",
            "cedula_funcionario",
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
            "coordinador_zona": "Supervisor que recibe",
            "cedula_funcionario": "Cédula del supervisor",
            "cliente_asignado": "Cliente",
            "puesto_asignado": "Puesto asignado",
            "observaciones_entrega": "Observaciones de entrega",
            "puesto": "Puesto",
            "estado_radio_entrega": "Radio",
            "estado_base_entrega": "Base",
            "estado_cargador_entrega": "Cargador",
            "estado_antena_entrega": "Antena",
            "estado_baterias_entrega": "Baterías",
            "clausula_aceptada": "El supervisor acepta la cláusula",
        }
        widgets = {
            "observaciones_entrega": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        """Crea los campos de estado de cada pieza, la cláusula obligatoria y
        prepara las listas de radios disponibles y de puestos activos.
        """
        super().__init__(*args, **kwargs)

        for campo in self.ESTADOS:
            self.fields[campo] = forms.ChoiceField(
                label=self.Meta.labels[campo],
                choices=ESTADOS_COMPONENTE,
            )
        self.fields["clausula_aceptada"] = forms.BooleanField(
            label=self.Meta.labels["clausula_aceptada"],
            error_messages={
                "required": "El supervisor debe aceptar la cláusula.",
            },
        )
        self.fields["firma"] = forms.CharField(
            widget=forms.HiddenInput,
            error_messages={"required": "Falta la firma del supervisor."},
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

        self.fields["cedula_funcionario"].required = False

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
        """Completa cliente y puesto desde el catálogo o exige escribirlos."""
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
        """Pasa al modelo el cliente y el puesto que ``clean`` completó."""
        super()._post_clean()
        # clean() completa los textos desde el puesto; se pasan al modelo.
        for campo in ("cliente_asignado", "puesto_asignado"):
            if campo in self.cleaned_data:
                setattr(self.instance, campo, self.cleaned_data[campo])

    def clean_firma(self):
        """Valida que la firma sea una imagen PNG dibujada (ver ``validar_firma``)."""
        return validar_firma(self.cleaned_data["firma"])

    def clean_radio(self):
        """Rechaza el radio si ya tiene una entrega vigente sin devolver."""
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
        """Guarda la entrega. La vista completa quién entrega y actualiza el radio."""
        asignacion = super().save(commit=False)
        if commit:
            asignacion.save()

        return asignacion


class RadioForm(forms.ModelForm):
    """Registro y edición de un radio con su estado y accesorios.

    Reglas:
        - La placa se guarda sin espacios y en mayúsculas, y no puede repetirse.
        - El serial no puede repetirse (se compara normalizado, sin guiones ni
          espacios).
        - El estado del radio es uno de los 4 estados; los de las piezas usan
          Bueno, Regular, Dañado o No tiene.
    """
    MODALIDADES_SERVICIO = [
        ("", "Seleccione una modalidad"),
        ("Punto a punto", "Punto a punto"),
        ("Repetidora", "Repetidora"),
    ]
    modalidad_servicio = forms.ChoiceField(
        label="Modalidad de servicio",
        choices=MODALIDADES_SERVICIO,
        required=False,
    )

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
    ESTADOS_ACCESORIO_UNIFICADO = [
        ("", "Sin dato"),
        ("No tiene", "No tiene"),
        ("Bueno", "Bueno"),
        ("Regular", "Regular"),
        ("Dañado", "Dañado"),
    ]
    # Campos virtuales: combinan presencia y condición sin agregar columnas.
    base_unificado = forms.ChoiceField(
        label="Base de carga", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )
    cargador_unificado = forms.ChoiceField(
        label="Cargador", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )
    antena_unificada = forms.ChoiceField(
        label="Antena", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )
    clip_unificado = forms.ChoiceField(
        label="Clip", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )
    perilla_encendido_unificada = forms.ChoiceField(
        label="Perilla de encendido", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )
    perilla_frecuencia_unificada = forms.ChoiceField(
        label="Perilla de frecuencia", choices=ESTADOS_ACCESORIO_UNIFICADO, required=False
    )

    CAMPOS_ACCESORIOS_UNIFICADOS = {
        "base_unificado": ("base", "estado_base"),
        "cargador_unificado": ("cargador", "estado_cargador"),
        "antena_unificada": ("antena", "estado_antena"),
        "clip_unificado": ("clip", "estado_clip"),
        "perilla_encendido_unificada": ("perilla_encendido", "estado_perilla_encendido"),
        "perilla_frecuencia_unificada": ("perilla_frecuencia", "estado_perilla_frecuencia"),
    }

    class Meta:
        model = Radio
        fields = [
            "codigo_fisico", "placa", "serial",
            "marca", "modelo", "tipo_frecuencia", "modalidad_servicio",
            "estado_radio", "estado_baterias",
            "bateria_1", "bateria_2",
            "base_unificado", "cargador_unificado", "antena_unificada",
            "clip_unificado", "perilla_encendido_unificada",
            "perilla_frecuencia_unificada",
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
            "base_unificado": "Base de carga",
            "cargador_unificado": "Cargador",
            "antena_unificada": "Antena",
            "clip_unificado": "Clip",
            "perilla_encendido_unificada": "Perilla de encendido",
            "perilla_frecuencia_unificada": "Perilla de frecuencia",
            "bateria_1": "Batería 1 (presencia)",
            "bateria_2": "Batería 2 (presencia)",
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
        """Arma las listas de estado de cada pieza y conserva valores antiguos que
        no estén en la lista para no perderlos al editar.
        """
        super().__init__(*args, **kwargs)

        # Conserva modalidades históricas que no estén en la lista nueva.
        modalidad_actual = getattr(self.instance, "modalidad_servicio", "")
        if modalidad_actual and modalidad_actual not in dict(self.MODALIDADES_SERVICIO):
            self.fields["modalidad_servicio"].choices = [
                *self.MODALIDADES_SERVICIO,
                (modalidad_actual, f"{modalidad_actual} (valor existente)"),
            ]

        for campo in ("estado_radio", "estado_baterias"):
            actual = getattr(self.instance, campo, "")
            if campo == "estado_radio":
                opciones = [("", "Sin dato"), *Radio.ESTADOS]
            else:
                opciones = list(self.ESTADOS)
            # Conserva valores libres que vienen de importaciones.
            if actual and actual not in dict(opciones):
                opciones.append((actual, f"{actual} (valor existente)"))
            self.fields[campo] = forms.ChoiceField(
                label=self.Meta.labels[campo], choices=opciones,
                required=False,
            )

        # Inicializa cada selector unificado desde los dos campos históricos.
        for nombre, (campo_presencia, campo_estado) in self.CAMPOS_ACCESORIOS_UNIFICADOS.items():
            presencia = getattr(self.instance, campo_presencia, None)
            estado = (getattr(self.instance, campo_estado, "") or "").strip()
            if presencia is False or estado.lower() == "no tiene":
                inicial = "No tiene"
            elif estado:
                inicial = estado
                opciones = list(self.fields[nombre].choices)
                if estado not in dict(opciones):
                    opciones.append((estado, f"{estado} (valor existente)"))
                    self.fields[nombre].choices = opciones
            else:
                # Si el accesorio existe pero no tiene condición registrada,
                # mostrar "Sin dato" sin inventar un estado adicional.
                inicial = ""
            self.fields[nombre].initial = inicial
        # Las baterías conservan presencia independiente; el modelo solo
        # dispone de un estado compartido para ambas.
        for campo in ("bateria_1", "bateria_2"):
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

        revision_activa = (
            self.data.get("requiere_revision") in {"on", "true", "1", "yes"}
            if self.is_bound else self.instance.requiere_revision
        )
        self.fields["motivo_revision"].disabled = not revision_activa

        for nombre, field in self.fields.items():
            if nombre != "requiere_revision":
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("requiere_revision"):
            cleaned["motivo_revision"] = ""
        return cleaned

    def save(self, commit=True):
        """Guarda los selectores unificados en los campos históricos del modelo.

        No crea columnas ni requiere migraciones. Los campos de presencia y
        estado existentes siguen siendo la fuente persistente.
        """
        instance = super().save(commit=False)
        for nombre, (campo_presencia, campo_estado) in self.CAMPOS_ACCESORIOS_UNIFICADOS.items():
            valor = self.cleaned_data.get(nombre, "")
            if valor == "No tiene":
                setattr(instance, campo_presencia, False)
                setattr(instance, campo_estado, "No tiene")
            elif valor:
                # Acepta y conserva estados históricos importados.
                setattr(instance, campo_presencia, True)
                setattr(instance, campo_estado, valor)
            else:
                # "Sin dato" no debe borrar información histórica. En un radio
                # nuevo, los campos permanecen en sus valores vacíos iniciales.
                pass

        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def clean_placa(self):
        """Normaliza la placa (sin espacios, mayúsculas) y verifica que no se repita."""
        placa = re.sub(r"\s+", "", self.cleaned_data["placa"]).upper()
        if placa and Radio.objects.filter(placa__iexact=placa).exclude(
            pk=self.instance.pk
        ).exists():
            raise forms.ValidationError("Otro radio ya tiene esta placa.")
        return placa

    def clean_serial(self):
        """Verifica que el serial normalizado no esté en otro radio."""
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


class CambioPlacaForm(forms.Form):
    """Nueva placa para un equipo registrado con la placa equivocada.

    Se normaliza igual que al registrar (sin espacios, en mayúsculas) y no
    puede ser la misma ni estar en otro equipo. Espera ``equipo``.
    """

    placa = forms.CharField(label="Placa correcta", max_length=50)

    def __init__(self, *args, equipo, **kwargs):
        """Guarda el equipo que se corrige para validar contra los demás."""
        super().__init__(*args, **kwargs)
        self.equipo = equipo

    def clean_placa(self):
        """Normaliza la placa y verifica que cambie y que nadie más la tenga."""
        placa = re.sub(r"\s+", "", self.cleaned_data["placa"]).upper()
        if not placa:
            raise forms.ValidationError("Escribe la placa correcta.")
        if placa == self.equipo.placa:
            raise forms.ValidationError("Es la misma placa que ya tiene.")
        otro = Equipo.objects.filter(placa__iexact=placa).exclude(pk=self.equipo.pk).first()
        if otro is not None:
            raise forms.ValidationError(f"La placa {otro.placa} ya es de otro equipo.")
        return placa


class RadioBajaForm(forms.Form):
    """Motivo por el que se da de baja un radio."""
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
        """Prepara fechas y la lista de sedes para el campo de ubicación.

        La ubicación se elige entre la sede principal y las sedes de los puestos
        para que el equipo aparezca en el mapa del tablero; si el equipo tenía
        un valor que no está en la lista, se conserva.
        """
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
        self.sedes_opciones = [valor for valor, _ in opciones if valor]
        self.fields["ubicacion"].widget = forms.TextInput(attrs={
            "list": "lista-sedes-equipo",
            "autocomplete": "off",
        })
        self.fields["ubicacion"].help_text = "Con la sede, el equipo aparece en el mapa del inicio."
        asignacion_activa = None
        if self.instance.pk:
            # La placa identifica al equipo en las importaciones y en T.MANT.
            self.fields["placa"].disabled = True
            asignacion_activa = (
                self.instance.asignaciones
                .filter(estado=AsignacionEquipo.Estado.ASIGNADO)
                .select_related("funcionario")
                .order_by("-fecha_entrega", "-id")
                .first()
            )
        self._responsable_manual = asignacion_activa is None
        self._responsables_por_valor = {}
        if asignacion_activa:
            funcionario = asignacion_activa.funcionario
            self.fields["responsable_nombre"].initial = (
                funcionario.nombre_completo if funcionario
                else asignacion_activa.nombre_recibe
            )
            self.fields["responsable_cedula"].initial = (
                funcionario.cedula if funcionario
                else asignacion_activa.cedula_recibe
            )
            self.fields["responsable_nombre"].disabled = True
            self.fields["responsable_cedula"].disabled = True
        else:
            funcionarios = Funcionario.objects.filter(
                activo=True,
                estado_persona=Funcionario.EstadoPersona.ACTIVA,
            ).order_by("nombre_completo", "cedula")
            opciones_responsables = [("", "Seleccione una persona responsable")]
            for persona in funcionarios:
                opciones_responsables.append((
                    persona.cedula,
                    f"{persona.nombre_completo} · C.C. {persona.cedula}",
                ))
                self._responsables_por_valor[persona.cedula] = (
                    persona.nombre_completo,
                    persona.cedula,
                )

            cedula_actual = (self.instance.responsable_cedula or "").strip()
            if (
                cedula_actual
                and cedula_actual not in self._responsables_por_valor
                and self.instance.responsable_nombre
            ):
                clave_actual = f"actual:{cedula_actual}"
                opciones_responsables.append((
                    clave_actual,
                    f"{self.instance.responsable_nombre} · registro actual",
                ))
                self._responsables_por_valor[clave_actual] = (
                    self.instance.responsable_nombre,
                    cedula_actual,
                )
                self.initial["responsable_nombre"] = clave_actual
            elif cedula_actual:
                self.initial["responsable_nombre"] = cedula_actual

            self.fields["responsable_nombre"] = forms.ChoiceField(
                label="Responsable",
                choices=opciones_responsables,
                required=False,
                help_text="Al elegir una persona, se completa su cédula automáticamente.",
            )
            self.fields["responsable_nombre"].widget.attrs[
                "data-responsable-selector"
            ] = ""
            self.fields["responsable_cedula"].disabled = True
            self.fields["responsable_cedula"].widget.attrs[
                "data-responsable-cedula"
            ] = ""
        self.fields["responsable_cedula"].disabled = True
        self.fields["responsable_nombre"].help_text = (
            "Se muestra el responsable de la entrega activa. "
            "Los cambios se registran desde Entregas y actas."
            if not self._responsable_manual else
            "Seleccione una persona; su cédula se completa automáticamente."
        )
        self.fields["responsable_cedula"].help_text = (
            "Se completa automáticamente con la persona seleccionada."
            if self._responsable_manual else
            "La identificación se toma de la persona vinculada a la entrega activa."
        )
        revision_activa = (
            self.data.get("requiere_revision") in {"on", "true", "1", "yes"}
            if self.is_bound else self.instance.requiere_revision
        )
        self.fields["motivo_revision"].disabled = not revision_activa
        for nombre, field in self.fields.items():
            if nombre != "requiere_revision":
                field.widget.attrs["class"] = "form-control"

    def clean_placa(self):
        """Normaliza la placa (sin espacios, mayúsculas) y verifica que sea única."""
        placa = re.sub(r"\s+", "", self.cleaned_data["placa"]).upper()
        if Equipo.objects.filter(placa__iexact=placa).exclude(
            pk=self.instance.pk
        ).exists():
            raise forms.ValidationError("Otro equipo ya tiene esta placa.")
        return placa

    def clean_serial(self):
        """Verifica que el serial normalizado no esté registrado en otro equipo."""
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

    def clean_responsable_nombre(self):
        valor = self.cleaned_data.get("responsable_nombre", "")
        if not self._responsable_manual:
            return valor
        if not valor:
            self._responsable_elegido = ("", "")
            return ""
        persona = self._responsables_por_valor.get(valor)
        if not persona:
            raise forms.ValidationError("Selecciona una persona del directorio.")
        self._responsable_elegido = persona
        return persona[0]

    def clean(self):
        cleaned = super().clean()
        if self._responsable_manual:
            nombre, cedula = getattr(self, "_responsable_elegido", ("", ""))
            cleaned["responsable_nombre"] = nombre
            cleaned["responsable_cedula"] = cedula
        if not cleaned.get("requiere_revision"):
            cleaned["motivo_revision"] = ""
        return cleaned


class DetalleForm(forms.ModelForm):
    """Base de los formularios de detalle por tipo."""

    def __init__(self, *args, **kwargs):
        """Aplica el estilo de la plataforma y el formato de fecha a todos los campos."""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
            if isinstance(field.widget, forms.DateInput):
                field.input_formats = ["%Y-%m-%d"]


class DetalleComputadorForm(DetalleForm):
    """Datos técnicos de un computador o tableta.

    Las claves de licencia solo aparecen para quien tiene el permiso
    "licencias"; sin él, ni se muestran ni se pueden modificar.
    """
    LICENCIAS = ["licencia_so", "licencia_antivirus", "licencia_office"]
    CLASES = [
        ("Portátil / Laptop", "Portátil / Laptop"),
        ("Escritorio torre", "Escritorio torre"),
        ("Todo en uno", "Todo en uno"),
        ("Servidor", "Servidor"),
        ("Android", "Android"),
        ("Otro", "Otro"),
    ]
    TIPOS_DISCO = [
        ("HDD", "HDD (mecánico)"),
        ("SSD SATA", "SSD SATA"),
        ("SSD NVMe", "SSD NVMe"),
        ("eMMC", "eMMC"),
        ("Híbrido (HDD + SSD)", "Híbrido (HDD + SSD)"),
    ]
    TIPOS_RAM = [
        ("DDR2", "DDR2"),
        ("DDR3", "DDR3"),
        ("DDR4", "DDR4"),
        ("DDR5", "DDR5"),
        ("LPDDR4", "LPDDR4"),
        ("LPDDR5", "LPDDR5"),
    ]
    clase = forms.ChoiceField(
        label="Clase",
        choices=[("", "Seleccione la clase"), *CLASES],
        required=False,
        help_text="Elija la clase que corresponda al equipo.",
    )
    tipo_disco = forms.ChoiceField(
        label="Tipo de disco",
        choices=[("", "Seleccione el tipo de disco"), *TIPOS_DISCO],
        required=False,
    )
    tipo_ram = forms.ChoiceField(
        label="Tipo de RAM",
        choices=[("", "Seleccione el tipo de RAM"), *TIPOS_RAM],
        required=False,
    )
    telefono_ip_asignado = forms.BooleanField(
        label="Tiene teléfono IP asignado",
        required=False,
        help_text="Marque esta opción para registrar un teléfono IP.",
        widget=forms.CheckboxInput(attrs={"data-telefono-ip-toggle": ""}),
    )

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
        """Quita los campos de licencia si ``ver_licencias`` es falso."""
        super().__init__(*args, **kwargs)
        actual = (getattr(self.instance, "clase", "") or "").strip()
        opciones = list(self.fields["clase"].choices)
        if actual and actual not in dict(opciones):
            opciones.append((actual, f"{actual} (valor actual)"))
        self.fields["clase"].choices = opciones

        for campo in ("tipo_disco", "tipo_ram"):
            actual = (getattr(self.instance, campo, "") or "").strip()
            opciones = list(self.fields[campo].choices)
            if actual and actual not in dict(opciones):
                opciones.append((actual, f"{actual} (valor actual)"))
            self.fields[campo].choices = opciones

        es_tableta = (
            getattr(getattr(self.instance, "equipo", None), "tipo", "")
            == Equipo.Tipo.TABLETA
        )
        if es_tableta:
            # Estos componentes son propios de una estación de trabajo; no
            # se solicitan en tabletas. Al excluirlos del ModelForm, cualquier
            # dato histórico que existiera queda intacto en la base de datos.
            for campo in (
                "mouse", "teclado", "monitor_serial", "monitor_modelo",
                "monitor2_serial", "monitor2_modelo", "ups_serial",
                "ups_modelo", "telefono_ip_asignado",
                "telefono_ip_serial", "telefono_ip_modelo",
            ):
                self.fields.pop(campo, None)
        else:
            telefono_actual = bool(
                getattr(self.instance, "telefono_ip_serial", "")
                or getattr(self.instance, "telefono_ip_modelo", "")
            )
            if not self.is_bound:
                self.initial["telefono_ip_asignado"] = telefono_actual

            habilitado = bool(self["telefono_ip_asignado"].value())
            toggle = self.fields["telefono_ip_asignado"]
            toggle.widget.attrs["class"] = "telefono-ip-toggle"
            for campo in ("telefono_ip_serial", "telefono_ip_modelo"):
                widget = self.fields[campo].widget
                widget.attrs["class"] = "form-control telefono-ip-input"
                widget.attrs["data-telefono-ip-field"] = ""
                if habilitado:
                    widget.attrs.pop("disabled", None)
                else:
                    widget.attrs["disabled"] = "disabled"

            # El check aparece inmediatamente antes de los datos del teléfono.
            orden = list(self.fields)
            orden.remove("telefono_ip_asignado")
            indice = orden.index("telefono_ip_serial")
            orden.insert(indice, "telefono_ip_asignado")
            self.order_fields(orden)

        if not ver_licencias:
            # Sin el permiso, las claves ni se muestran ni se modifican.
            for campo in self.LICENCIAS:
                del self.fields[campo]

    def save(self, commit=True):
        instancia = super().save(commit=False)
        if (
            "telefono_ip_asignado" in self.fields
            and not self.cleaned_data.get("telefono_ip_asignado")
        ):
            instancia.telefono_ip_serial = ""
            instancia.telefono_ip_modelo = ""
        if commit:
            instancia.save()
            self.save_m2m()
        return instancia


class DetalleImpresoraForm(DetalleForm):
    """Datos propios de una impresora o escáner."""
    CLASES = [
        ("L\u00e1ser", "L\u00e1ser"),
        ("Inyecci\u00f3n de tinta", "Inyecci\u00f3n de tinta"),
        ("Multifuncional l\u00e1ser", "Multifuncional l\u00e1ser"),
        ("Multifuncional de tinta", "Multifuncional de tinta"),
        ("Matricial", "Matricial"),
        ("T\u00e9rmica", "T\u00e9rmica"),
        ("Esc\u00e1ner", "Esc\u00e1ner"),
        ("Otro", "Otro"),
    ]
    clase = forms.ChoiceField(
        label="Tipo de impresora o esc\u00e1ner",
        choices=[("", "Seleccione el tipo"), *CLASES],
        required=False,
        help_text="Elija la tecnolog\u00eda que corresponda.",
    )

    class Meta:
        model = DetalleImpresora
        exclude = ["equipo"]
        labels = {"clase": "Tipo de impresora o escáner"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actual = (self.instance.clase or "").strip()
        opciones = list(self.fields["clase"].choices)
        if actual and actual not in dict(opciones):
            opciones.append((actual, f"{actual} (valor actual)"))
        self.fields["clase"].choices = opciones


class DetalleGPSForm(DetalleForm):
    """Datos del GPS: IMEI, línea, operador, vehículo y estado en la plataforma.

    Los cambios posteriores de línea o vehículo se registran con CambioGPSForm.
    """
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
    """Datos de un panel de alarma y su lista de componentes.

    Los componentes se escriben uno por línea: ``nombre; cantidad; estado``.
    """
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
        """Muestra los componentes guardados en el formato de texto editable."""
        super().__init__(*args, **kwargs)
        self.fields["componentes_texto"].initial = "\n".join(
            "{}; {}; {}".format(
                c.get("nombre", ""), c.get("cantidad", ""), c.get("estado", "")
            )
            for c in self.instance.componentes or []
        )

    def clean_componentes_texto(self):
        """Convierte el texto en una lista de componentes y valida cada línea.

        Cada línea debe tener tres partes separadas por punto y coma, y la
        cantidad debe ser un número entero.
        """
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
        """Guarda la lista de componentes ya convertida."""
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
    "Declaro que recibo el equipo y los accesorios descritos, en el estado "
    "indicado en esta acta. "
    "Me comprometo a usarlo solo para las funciones de mi cargo, a cuidarlo, "
    "a no instalar software sin autorización del área de TI, a guardar "
    "reserva sobre la información de la empresa que maneje en él y a "
    "devolverlo cuando se me solicite. Respondo por la pérdida o el daño "
    "causado por mal uso."
)


class AsignacionEquipoForm(forms.ModelForm):
    """Entrega de un equipo (computador, impresora, tableta…) a un funcionario.

    Exige funcionario activo, aceptación de la cláusula y firma dibujada.
    """
    class Meta:
        model = AsignacionEquipo
        fields = [
            "funcionario", "area", "estado_entrega", "accesorios",
            "observaciones_entrega", "clausula_aceptada", "firma",
        ]
        labels = {
            "funcionario": "Funcionario que recibe",
            "area": "Área o sede",
            "estado_entrega": "Estado en que se entrega",
            "accesorios": "Accesorios entregados",
            "observaciones_entrega": "Observaciones de entrega",
            "clausula_aceptada": "El funcionario acepta la cláusula",
        }
        widgets = {
            "accesorios": forms.Textarea(attrs={"rows": 2}),
            "observaciones_entrega": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, primera_entrega=False, **kwargs):
        """Lista solo funcionarios activos (nombre · cédula) y hace obligatoria la cláusula.

        Args:
            primera_entrega: si el equipo nunca se ha entregado, el estado
                sugerido es «Nuevo» (el caso de un equipo recién comprado).
        """
        super().__init__(*args, **kwargs)
        self.fields["area"].widget = forms.TextInput(attrs={
            "class": "form-control",
            "list": "lista-sedes-puestos-entrega",
            "autocomplete": "off",
            "placeholder": "Busca o escribe una sede, puesto o área",
        })
        # Los registros históricos de entrega guardan el área como texto.
        # Ofrecemos sedes y puestos del catálogo, pero mantenemos entrada libre
        # para áreas administrativas y ubicaciones que aún no estén catalogadas.
        opciones = set(
            Puesto.objects.filter(activo=True)
            .exclude(sede__exact="")
            .values_list("sede", flat=True)
        )
        opciones.update(
            Puesto.objects.filter(activo=True)
            .values_list("nombre", flat=True)
        )
        opciones.update(
            Sede.objects.filter(activo=True).values_list("nombre", flat=True)
        )
        self.sedes_puestos_opciones = sorted(
            {valor.strip() for valor in opciones if valor and valor.strip()},
            key=str.casefold,
        )
        self.fields["funcionario"].required = True
        estado = self.fields["estado_entrega"]
        estado.required = True
        estado.choices = [("", "Selecciona el estado")] + list(
            AsignacionEquipo.EstadoEntrega.choices
        )
        estado.error_messages["required"] = "Indica en qué estado se entrega el equipo."
        if primera_entrega and not self.is_bound:
            self.initial.setdefault(
                "estado_entrega", AsignacionEquipo.EstadoEntrega.NUEVO
            )
        self.fields["observaciones_entrega"].help_text = (
            "Si el equipo tiene detalles (rayones, golpes, piezas faltantes), "
            "descríbelos aquí: quedan en el acta firmada."
        )
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
        """Valida que la firma sea una imagen PNG dibujada."""
        return validar_firma(self.cleaned_data["firma"])

    def clean(self):
        """Si el equipo se entrega con detalles, exige describirlos."""
        datos = super().clean()
        if (
            datos.get("estado_entrega") == AsignacionEquipo.EstadoEntrega.DETALLES
            and not (datos.get("observaciones_entrega") or "").strip()
        ):
            self.add_error(
                "observaciones_entrega",
                "Describe los detalles con que se entrega el equipo.",
            )
        return datos


class FirmaEntregaForm(forms.ModelForm):
    """Firma en JANO de una entrega que ya existe (regularización).

    Para entregas importadas que solo tienen el enlace a la firma en Google
    o ninguna firma: el funcionario confirma el estado del equipo, acepta la
    cláusula y firma. El enlace anterior se conserva.
    """

    class Meta:
        model = AsignacionEquipo
        fields = ["estado_entrega", "clausula_aceptada", "firma"]
        labels = {
            "estado_entrega": "Estado en que tiene el equipo",
            "clausula_aceptada": "El funcionario acepta la cláusula",
        }

    def __init__(self, *args, **kwargs):
        """Hace obligatorios el estado, la cláusula y la firma."""
        super().__init__(*args, **kwargs)
        estado = self.fields["estado_entrega"]
        estado.required = True
        estado.choices = [("", "Selecciona el estado")] + list(
            AsignacionEquipo.EstadoEntrega.choices
        )
        estado.widget.attrs["class"] = "form-control"
        self.fields["clausula_aceptada"] = forms.BooleanField(
            label=self.Meta.labels["clausula_aceptada"],
            error_messages={"required": "El funcionario debe aceptar la cláusula."},
        )
        self.fields["firma"] = forms.CharField(
            widget=forms.HiddenInput,
            error_messages={"required": "Falta la firma del funcionario."},
        )

    def clean_firma(self):
        """Valida que la firma sea una imagen PNG dibujada."""
        return validar_firma(self.cleaned_data["firma"])


class CorreoFuncionarioForm(forms.Form):
    """Archivo con cédulas y correos de funcionarios (Excel o CSV)."""

    archivo = forms.FileField(
        label="Archivo con cédula y correo",
        help_text="Excel (.xlsx) o CSV con columnas «Cédula» y «Correo». "
        "Solo se llenan los funcionarios que aún no tienen correo.",
    )


class CambioGPSForm(forms.ModelForm):
    """Registro de un cambio de línea, operador o vehículo de un GPS."""
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
        """Ofrece la lista de qué cambia (vehículo, línea, ambos u otro)."""
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
    """Verificación de los 15 puntos de la política de seguridad informática.

    Crea un campo por punto (``punto_<clave>``) con las respuestas de
    ``inventario/politica.py``; por defecto todos quedan en "Cumple".
    """
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
        """Crea un campo de opción por cada punto de la política."""
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
        """Campos de los puntos, en orden, para pintarlos en la plantilla."""
        return [self[n] for n in self.fields if n.startswith("punto_")]

    def respuestas(self):
        """Respuestas como {clave_del_punto: respuesta} para guardar en la verificación."""
        return {
            nombre.removeprefix("punto_"): valor
            for nombre, valor in self.cleaned_data.items()
            if nombre.startswith("punto_")
        }


class RenovacionAntivirusForm(forms.Form):
    """Renovación del antivirus de un computador: producto, licencia y vencimiento."""
    antivirus = forms.CharField(label="Antivirus instalado", max_length=150)
    licencia = forms.CharField(label="Licencia", max_length=200, required=False)
    vencimiento = forms.DateField(
        label="Fecha de vencimiento",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, **kwargs):
        """Aplica el estilo de la plataforma a todos los campos."""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


# ---------------------------------------------------------------------------
# Solicitudes de soporte (tickets)
# ---------------------------------------------------------------------------

FOTO_MAX_BYTES = 5 * 1024 * 1024
FOTOS_MAXIMAS = 3
# Primeros bytes de cada formato de imagen permitido.
FIRMAS_IMAGEN = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
}


def validar_foto(archivo):
    """Solo imágenes JPG, PNG o WEBP de hasta 5 MB (se revisa el contenido,
    no solo la extensión)."""
    if archivo.size > FOTO_MAX_BYTES:
        raise forms.ValidationError(f"La foto {archivo.name} pesa más de 5 MB.")
    inicio = archivo.read(12)
    archivo.seek(0)
    es_webp = inicio[:4] == b"RIFF" and inicio[8:12] == b"WEBP"
    if not es_webp and not any(inicio.startswith(m) for m in FIRMAS_IMAGEN):
        raise forms.ValidationError(f"{archivo.name} no es una foto JPG, PNG o WEBP.")
    return archivo


def tecnicos():
    """Usuarios activos que pueden atender solicitudes."""
    return get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(groups__name="Técnico de mantenimiento")
    ).distinct().order_by("first_name", "username")


class TicketForm(forms.ModelForm):
    """Solicitud registrada por el área de TI (por teléfono, en persona…)."""

    class Meta:
        model = Ticket
        fields = [
            "tipo", "categoria", "prioridad", "equipo", "descripcion",
            "solicitante_nombre", "solicitante_cedula", "solicitante_correo",
            "solicitante_telefono", "ubicacion",
        ]
        labels = {
            "categoria": "Categoría",
            "descripcion": "Descripción de la falla o del trabajo",
            "solicitante_nombre": "Solicitante",
            "solicitante_cedula": "Cédula del solicitante",
            "solicitante_correo": "Correo del solicitante",
            "solicitante_telefono": "Teléfono del solicitante",
            "ubicacion": "Sede o lugar",
        }
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        """Prepara la lista de equipos (opcional: hay solicitudes sin equipo, como correo o red)."""
        super().__init__(*args, **kwargs)
        configurar_campo_equipo(self.fields["equipo"])
        self.fields["equipo"].required = False
        self.fields["equipo"].empty_label = "Sin equipo (por ejemplo, correo o red)"
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class AsignarTicketForm(forms.Form):
    """Asignación de una solicitud: técnico, prioridad y fecha y franja de la visita."""
    tecnico = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), label="Técnico",
        empty_label="Seleccione un técnico",
    )
    prioridad = forms.ChoiceField(label="Prioridad", choices=Ticket.Prioridad.choices)
    fecha_programada = forms.DateField(
        label="Fecha de la visita", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    franja = forms.ChoiceField(
        label="Horario", required=False,
        choices=[("", "Sin horario")] + list(Ticket.Franja.choices),
    )

    def __init__(self, *args, **kwargs):
        """Lista solo los usuarios con rol de técnico, por su nombre."""
        super().__init__(*args, **kwargs)
        self.fields["tecnico"].queryset = tecnicos()
        self.fields["tecnico"].label_from_instance = (
            lambda u: u.get_full_name() or u.username
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class AtencionTicketForm(forms.Form):
    """Cierre técnico de una solicitud: solución y, si la hay, firma de quien recibe."""
    solucion = forms.CharField(
        label="Solución (la verá el solicitante)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    firma_nombre = forms.CharField(
        label="Nombre de quien recibe", max_length=200, required=False,
    )
    firma = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        """Aplica el estilo de la plataforma (salvo al campo oculto de la firma)."""
        super().__init__(*args, **kwargs)
        for nombre, field in self.fields.items():
            if nombre != "firma":
                field.widget.attrs["class"] = "form-control"

    def clean_firma(self):
        """Valida la firma si se dibujó; es opcional."""
        firma = self.cleaned_data["firma"]
        return validar_firma(firma) if firma else ""

    def clean(self):
        """Si hay firma, exige el nombre de quien firma."""
        datos = super().clean()
        if datos.get("firma") and not datos.get("firma_nombre"):
            self.add_error("firma_nombre", "Indica quién firma.")
        return datos


class IntervencionTicketForm(MantenimientoEquipoForm):
    """La intervención de una solicitud: el equipo es el de la solicitud y se
    usan las mismas casillas por tipo de equipo que en mantenimiento."""

    def __init__(self, *args, equipo=None, **kwargs):
        """Fija el equipo de la solicitud: el mantenimiento se registra sobre ese equipo."""
        super().__init__(*args, **kwargs)
        if equipo is not None:
            self.fields["equipo"].initial = equipo.pk
            self.fields["tipo_equipo"].initial = equipo.tipo
        self.fields["equipo"].disabled = True
        self.fields["tipo_equipo"].disabled = True


class TextoTicketForm(forms.Form):
    """Comentario sobre una solicitud; puede ser interno o visible para el solicitante."""
    texto = forms.CharField(
        label="Texto", widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        max_length=2000,
    )
    publico = forms.BooleanField(label="Visible para el solicitante", required=False)


class CedulaSoporteForm(forms.Form):
    """Paso 1 de la solicitud pública: quién la pide."""

    cedula = forms.CharField(label="Número de cédula", max_length=20)
    # Campo trampa: las personas no lo ven; los robots lo llenan.
    sitio_web = forms.CharField(required=False, label="Sitio web")

    def __init__(self, *args, **kwargs):
        """Prepara el campo de cédula y el campo trampa contra robots."""
        super().__init__(*args, **kwargs)
        self.funcionario = None
        self.fields["cedula"].widget.attrs.update({
            "inputmode": "numeric", "autocomplete": "off", "class": "form-control",
        })
        self.fields["sitio_web"].widget.attrs.update({"tabindex": "-1", "autocomplete": "off"})

    def clean_cedula(self):
        """Deja solo dígitos y verifica que la cédula sea de un funcionario activo.

        Guarda el funcionario encontrado en ``self.funcionario``.
        """
        cedula = re.sub(r"\D", "", self.cleaned_data["cedula"])
        funcionario = Funcionario.objects.filter(cedula=cedula, activo=True).first()
        if funcionario is None:
            raise forms.ValidationError(
                "La cédula no está en el listado de personal activo. "
                "Comunícate con el área de TI."
            )
        self.funcionario = funcionario
        return cedula

    def clean_sitio_web(self):
        """Campo trampa: si un robot lo llena, la solicitud se rechaza."""
        if self.cleaned_data["sitio_web"]:
            raise forms.ValidationError("Solicitud no válida.")
        return ""


class SoporteForm(forms.Form):
    """Paso 2: qué pasa y con cuál de sus equipos.

    Se muestran los equipos que la persona tiene a cargo según el inventario;
    si el equipo no está en la lista, puede escribir la placa.
    """

    CATEGORIAS = [
        (Ticket.Categoria.EQUIPO_OFICINA, "Daño en equipo de oficina"),
        (Ticket.Categoria.SOFTWARE, "Soporte de correo, Novasoft, SEIF, servidor o internet"),
        (Ticket.Categoria.OPERACION, "Daño en elementos de operación (radios, repetidora, cámaras)"),
    ]
    OTRO = "otro"
    NINGUNO = "ninguno"

    categoria = forms.ChoiceField(
        label="Tipo de soporte que necesita", choices=CATEGORIAS, widget=forms.RadioSelect,
    )
    equipo = forms.ChoiceField(label="Equipo con la falla", required=False, widget=forms.RadioSelect)
    placa = forms.CharField(
        label="Placa del equipo", max_length=50, required=False,
        help_text="Está en la etiqueta del equipo, por ejemplo PC--21 o RJ-2022.",
    )
    descripcion = forms.CharField(
        label="Describa la falla", widget=forms.Textarea(attrs={"rows": 4}), max_length=3000,
    )
    ubicacion = forms.CharField(label="¿Dónde está? (sede, oficina o puesto)", max_length=200)
    correo = forms.EmailField(label="Correo para avisarle del avance")
    telefono = forms.CharField(label="Teléfono o celular", max_length=50, required=False)
    visita = forms.ChoiceField(
        label="¿Cuándo podemos atenderte?", required=False,
        help_text="Elige el día y la franja. TIC confirma la visita al asignar el técnico.",
    )

    def __init__(self, *args, funcionario=None, equipos=(), **kwargs):
        """Arma las opciones del formulario de soporte para un funcionario.

        ``equipos`` son los equipos a su cargo (se ofrecen para elegir); la lista
        de visitas muestra los cupos libres de la agenda (``inventario/agenda.py``).
        """
        from . import agenda

        super().__init__(*args, **kwargs)
        self.funcionario = funcionario
        self.equipo = None
        self.fecha_visita, self.franja_visita = None, ""
        self.fields["visita"].choices = [("", "Que TIC me contacte para acordar la visita")] + [
            (c["valor"], f"{c['etiqueta']} ({c['libres']} cupo{'s' if c['libres'] != 1 else ''})")
            for c in agenda.cupos_disponibles()
        ]
        self.equipos = {str(e.pk): e for e in equipos}
        self.fields["equipo"].choices = [
            (str(e.pk), f"{e.placa} · {e.get_tipo_display()} {e.marca} {e.modelo}".strip())
            for e in equipos
        ] + [
            (self.OTRO, "Otro equipo (escribir la placa)"),
            (self.NINGUNO, "No es de un equipo (correo, programas, internet…)"),
        ]
        if funcionario is not None and not self.is_bound:
            self.initial.setdefault("correo", funcionario.correo)
        for nombre, field in self.fields.items():
            if nombre not in ("categoria", "equipo"):
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        """Resuelve el equipo elegido (de la lista o por placa) y la visita pedida.

        Si se escribe una placa, debe existir; la visita elegida debe seguir
        teniendo cupo.
        """
        datos = super().clean()
        eleccion = datos.get("equipo") or ""
        self.equipo = None
        if eleccion in self.equipos:
            self.equipo = self.equipos[eleccion]
        elif eleccion == self.OTRO:
            placa = re.sub(r"\s+", "", datos.get("placa") or "").upper()
            if not placa:
                self.add_error("placa", "Escriba la placa del equipo.")
            else:
                self.equipo = Equipo.objects.filter(placa__iexact=placa, activo=True).first()
                if self.equipo is None:
                    self.add_error("placa", "No encontramos un equipo activo con esa placa.")
        elif eleccion == self.NINGUNO:
            if datos.get("categoria") != Ticket.Categoria.SOFTWARE:
                self.add_error("equipo", "Elija el equipo que presenta la falla.")
        else:
            self.add_error("equipo", "Elija el equipo o indique que no es de un equipo.")
        if datos.get("visita"):
            from . import agenda

            self.fecha_visita, self.franja_visita = agenda.leer_valor(datos["visita"])
        return datos


class ReabrirForm(forms.Form):
    """Motivo con el que el solicitante reabre un caso que sigue fallando."""
    motivo = forms.CharField(
        label="¿Qué sigue fallando?",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        max_length=2000,
    )
