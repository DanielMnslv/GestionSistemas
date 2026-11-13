
from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, render, redirect

from .forms import UsuarioCreationForm, UsuarioEditarForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect("inicio")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)
            return redirect("inicio")

        messages.error(
            request,
            "Usuario o contraseña incorrectos."
        )

    return render(request, "usuarios/login.html")


@login_required
def inicio(request):
    from inventario.panel import datos_inicio
    from inventario.permisos import solo_solicitante, solo_talento

    if solo_solicitante(request.user):
        return redirect("portal:inicio")
    if solo_talento(request.user):
        return redirect("inventario:personas_lista")

    return render(request, "usuarios/inicio.html", datos_inicio())


@login_required
@user_passes_test(
    lambda user: user.is_superuser,
    login_url="inicio",
)
def usuarios_lista(request):
    Usuario = get_user_model()
    usuarios = Usuario.objects.all().order_by("username")

    return render(
        request,
        "usuarios/usuarios_lista.html",
        {"usuarios": usuarios},
    )


@login_required
@user_passes_test(
    lambda user: user.is_superuser,
    login_url="inicio",
)
def usuario_crear(request):
    if request.method == "POST":
        form = UsuarioCreationForm(request.POST)

        if form.is_valid():
            usuario = form.save()

            messages.success(
                request,
                f"El usuario {usuario.username} fue creado correctamente."
            )
            return redirect("usuarios_lista")
    else:
        form = UsuarioCreationForm()

    return render(
        request,
        "usuarios/usuario_form.html",
        {"form": form},
    )

@login_required
@user_passes_test(
    lambda user: user.is_superuser,
    login_url="inicio",
)
def usuario_editar(request, usuario_id):
    usuario = get_object_or_404(get_user_model(), pk=usuario_id)
    form = UsuarioEditarForm(request.POST or None, instance=usuario)

    if request.method == "POST" and form.is_valid():
        if usuario == request.user and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "No puedes desactivar tu propio usuario.")
        else:
            form.save()
            messages.success(
                request,
                f"El usuario {usuario.username} fue actualizado.",
            )
            return redirect("usuarios_lista")

    return render(
        request,
        "usuarios/usuario_form.html",
        {
            "form": form,
            "titulo": f"Editar usuario {usuario.username}",
            "boton": "Guardar cambios",
        },
    )
