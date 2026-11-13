
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group


class UsuarioCreationForm(UserCreationForm):
    ROLES = [
        ("Encargado de inventario", "Encargado de inventario"),
        ("Técnico de mantenimiento", "Técnico de mantenimiento"),
        ("Consulta", "Consulta"),
        ("Talento humano", "Talento humano"),
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
            "username": "Nombre de usuario",
        }

    def save(self, commit=True):
        usuario = super().save(commit=False)

        usuario.first_name = self.cleaned_data["first_name"]
        usuario.last_name = self.cleaned_data["last_name"]
        usuario.email = self.cleaned_data["email"]

        if commit:
            usuario.save()

            grupo, _ = Group.objects.get_or_create(
                name=self.cleaned_data["rol"]
            )
            usuario.groups.add(grupo)

        return usuario


class UsuarioEditarForm(forms.ModelForm):
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
        super().__init__(*args, **kwargs)
        roles = dict(UsuarioCreationForm.ROLES)
        actual = self.instance.groups.filter(name__in=roles).first()
        if actual:
            self.fields["rol"].initial = actual.name

    def save(self, commit=True):
        usuario = super().save(commit=commit)
        if commit:
            # Un rol por usuario: se reemplaza el anterior.
            usuario.groups.remove(*usuario.groups.filter(
                name__in=dict(UsuarioCreationForm.ROLES)
            ))
            grupo, _ = Group.objects.get_or_create(
                name=self.cleaned_data["rol"]
            )
            usuario.groups.add(grupo)
        return usuario
