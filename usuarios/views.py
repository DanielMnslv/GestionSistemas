"""Vistas de ingreso, inicio y administración de cuentas de la plataforma.

La administración de cuentas (lista, crear, editar) es solo para
superusuarios: menú Control › Accesos a la plataforma.
"""

import logging
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.models import Group

from .forms import UsuarioCreationForm, UsuarioEditarForm


logger_seguridad = logging.getLogger("nucleo.seguridad")


def login_view(request):
    """Pantalla de ingreso con usuario y contraseña."""
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

        # Fail2ban analiza esta línea para bloquear la IP tras varios
        # intentos. Nunca se registra la contraseña. Se quitan saltos de
        # línea del usuario para impedir inyección de entradas en el log.
        remote_addr = request.META.get("REMOTE_ADDR", "desconocida")
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if remote_addr in settings.DJANGO_TRUSTED_PROXY_IPS and forwarded_for:
            ip = forwarded_for.split(",", 1)[0].strip()
        else:
            ip = remote_addr
        usuario_intentado = re.sub(
            r"[\r\n\t]+", " ", request.POST.get("username", "")
        ).strip()[:150]
        logger_seguridad.warning(
            "LOGIN_FALLIDO ip=%s usuario=%s", ip, usuario_intentado
        )

        messages.error(
            request,
            "Usuario o contraseña incorrectos."
        )

    return render(request, "usuarios/login.html")


@login_required
def inicio(request):
    """Tablero de inicio según el rol.

    Los solicitantes van al portal Mi soporte; Talento humano, a la lista de personas;
    el resto ve el tablero con indicadores (``inventario/panel.py``).
    """
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
    """Lista de cuentas de la plataforma (solo superusuarios)."""
    from inventario.models import Funcionario

    Usuario = get_user_model()
    consulta = Usuario.objects.all().prefetch_related("groups").order_by("username")
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    staff = request.GET.get("staff", "")
    superusuario = request.GET.get("superusuario", "")
    grupo = request.GET.get("grupo", "")

    if busqueda:
        personas = Funcionario.objects.filter(
            Q(cedula__icontains=busqueda)
            | Q(nombre_completo__icontains=busqueda)
            | Q(cargo__icontains=busqueda)
            | Q(area__icontains=busqueda)
            | Q(correo__icontains=busqueda)
        )
        usernames = personas.values_list("cedula", flat=True)
        cuentas_vinculadas = personas.exclude(usuario_jano=None).values_list(
            "usuario_jano_id", flat=True
        )
        consulta = consulta.filter(
            Q(username__icontains=busqueda)
            | Q(first_name__icontains=busqueda)
            | Q(last_name__icontains=busqueda)
            | Q(email__icontains=busqueda)
            | Q(username__in=usernames)
            | Q(pk__in=cuentas_vinculadas)
        ).distinct()

    if estado == "activo":
        consulta = consulta.filter(is_active=True)
    elif estado == "inactivo":
        consulta = consulta.filter(is_active=False)
    if staff in {"si", "no"}:
        consulta = consulta.filter(is_staff=(staff == "si"))
    if superusuario in {"si", "no"}:
        consulta = consulta.filter(is_superuser=(superusuario == "si"))
    if grupo:
        consulta = consulta.filter(groups__name=grupo)

    grupos = Group.objects.order_by("name").values_list("name", flat=True)
    pagina = Paginator(consulta.distinct(), 30).get_page(request.GET.get("page"))
    usuarios = list(pagina.object_list)

    personas = Funcionario.objects.filter(
        Q(usuario_jano__in=usuarios)
        | Q(cedula__in=[u.username for u in usuarios])
    )
    por_usuario = {p.usuario_jano_id: p for p in personas if p.usuario_jano_id}
    por_cedula = {p.cedula: p for p in personas}
    for usuario in usuarios:
        persona_directa = por_usuario.get(usuario.pk)
        persona_por_cedula = por_cedula.get(usuario.username)
        if persona_por_cedula and persona_por_cedula.usuario_jano_id:
            persona_por_cedula = None
        usuario.persona_directorio = persona_directa or persona_por_cedula

    return render(
        request,
        "usuarios/usuarios_lista.html",
        {
            "usuarios": usuarios,
            "page_obj": pagina,
            "q": busqueda,
            "estado": estado,
            "staff": staff,
            "superusuario": superusuario,
            "grupo": grupo,
            "grupos": grupos,
            "total": pagina.paginator.count,
        },
    )


@login_required
@user_passes_test(
    lambda user: user.is_superuser,
    login_url="inicio",
)
def usuario_crear(request):
    """Creación de una cuenta con su rol (solo superusuarios)."""
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
    """Edición de una cuenta: datos, rol y si está activa (solo superusuarios).

    Nadie puede desactivar su propia cuenta.
    """
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
