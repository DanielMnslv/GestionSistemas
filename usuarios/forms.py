"""Formularios de administración de cuentas (solo superusuarios)."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.core.validators import RegexValidator


VALIDADOR_CEDULA = RegexValidator(
    regex=r"^\d+$",
    message="Escribe solo números, sin puntos ni espacios.",
)


class UsuarioCreationForm(UserCreationForm):
    """Creación de una cuenta con nombre, correo, contraseña y un rol.

    Los roles son grupos de Django; cada cuenta tiene uno (ver
    ``inventario/permisos.py``).
    """
    ROLES = [
        ("Encargado de inventario", "Encargado de inventario"),
        ("Técnico de mantenimiento", "Técnico de mantenimiento"),
        ("Consulta", "Consulta"),
        ("Talento humano", "Talento humano"),
        ("Solicitante", "Solicitante (portal Mi soporte)"),
    ]

    first_name = forms.CharField(
        label="Nombres",
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=True,
    )

    email = forms.EmailField(
        label="Correo electrónico",
        required=True,
    )

    username = forms.CharField(
        label="Número de cédula",
        max_length=20,
        validators=[VALIDADOR_CEDULA],
        help_text="Será el usuario para iniciar sesión: solo números, sin puntos ni espacios.",
    )

    rol = forms.ChoiceField(
        label="Rol del usuario",
        choices=ROLES,
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
        )
        labels = {
            "username": "Número de cédula",
        }

    def clean_username(self):
        cedula = super().clean_username()
        from inventario.models import Funcionario

        persona = Funcionario.objects.filter(cedula=cedula).first()
        if persona and persona.usuario_jano_id:
            raise forms.ValidationError("Esta cédula ya está vinculada a otra cuenta.")
        return cedula

    def save(self, commit=True):
        """Guarda la cuenta con sus datos y le asigna el rol elegido."""
        usuario = super().save(commit=False)

        usuario.first_name = self.cleaned_data["first_name"]
        usuario.last_name = self.cleaned_data["last_name"]
        usuario.email = self.cleaned_data["email"]

        if commit:
            usuario.save()

            from inventario.models import Funcionario

            persona = Funcionario.objects.filter(cedula=usuario.username).first()
            if persona:
                persona.usuario_jano = usuario
                persona.save(update_fields=["usuario_jano"])

            grupo, _ = Group.objects.get_or_create(
                name=self.cleaned_data["rol"]
            )
            usuario.groups.add(grupo)

        return usuario


class UsuarioEditarForm(forms.ModelForm):
    """Edición de una cuenta: datos, rol y si está activa."""
    cedula = forms.CharField(
        label="Número de cédula",
        max_length=20,
        validators=[VALIDADOR_CEDULA],
        help_text="Se usará para iniciar sesión, sin puntos ni espacios.",
    )
    rol = forms.ChoiceField(
        label="Rol del usuario",
        choices=UsuarioCreationForm.ROLES,
    )

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email", "is_active")
        labels = {
            "first_name": "Nombres",
            "last_name": "Apellidos",
            "email": "Correo electrónico",
            "is_active": "Usuario activo",
        }

    def __init__(self, *args, **kwargs):
        """Muestra marcado el rol actual de la cuenta."""
        super().__init__(*args, **kwargs)
        from inventario.models import Funcionario

        persona = Funcionario.objects.filter(usuario_jano=self.instance).first()
        if not persona:
            persona = Funcionario.objects.filter(cedula=self.instance.username).first()
        self.fields["cedula"].initial = (
            persona.cedula if persona else (
                self.instance.username if self.instance.username.isdigit() else ""
            )
        )
        roles = dict(UsuarioCreationForm.ROLES)
        actual = self.instance.groups.filter(name__in=roles).first()
        if actual:
            self.fields["rol"].initial = actual.name

    def clean_cedula(self):
        cedula = self.cleaned_data["cedula"].strip()
        Usuario = get_user_model()
        if Usuario.objects.filter(username=cedula).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe otra cuenta con esta cédula.")

        from inventario.models import Funcionario

        persona = Funcionario.objects.filter(cedula=cedula).first()
        if persona and persona.usuario_jano_id not in (None, self.instance.pk):
            raise forms.ValidationError("Esta cédula ya está vinculada a otra cuenta.")
        return cedula

    def save(self, commit=True):
        """Guarda la cédula como usuario y la vincula al directorio si existe."""
        usuario = super().save(commit=False)
        cedula = self.cleaned_data["cedula"]
        usuario.username = cedula
        if commit:
            usuario.save()
            self.save_m2m()
            from inventario.models import Funcionario

            Funcionario.objects.filter(usuario_jano=usuario).exclude(
                cedula=cedula
            ).update(usuario_jano=None)
            persona = Funcionario.objects.filter(cedula=cedula).first()
            if persona and persona.usuario_jano_id != usuario.pk:
                persona.usuario_jano = usuario
                persona.save(update_fields=["usuario_jano"])
            # Un rol por usuario: se reemplaza el anterior.
            usuario.groups.remove(*usuario.groups.filter(
                name__in=dict(UsuarioCreationForm.ROLES)
            ))
            grupo, _ = Group.objects.get_or_create(
                name=self.cleaned_data["rol"]
            )
            usuario.groups.add(grupo)
        return usuario
