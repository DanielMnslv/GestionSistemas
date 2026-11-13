
from django.urls import include, path
from . import (
    views, views_auditoria, views_catalogos, views_equipos, views_personas,
    views_tickets,
)

app_name = "inventario"

urlpatterns = [
    path("informes/", include("inventario.informes.urls")),
    path("equipos/tipos/", views_equipos.equipos_inicio, name="equipos_inicio"),
    path("equipos/bajas/", views_equipos.equipos_bajas, name="equipos_bajas"),
    path("equipos/", views_equipos.equipos_lista, name="equipos_lista"),
    path("buscar/", views_equipos.buscar_json, name="buscar"),
    # Módulo de Usuarios: personas, equipos a cargo y paz y salvo.
    path("personas/", views_personas.personas_lista, name="personas_lista"),
    path("personas/nueva/", views_personas.persona_crear, name="persona_crear"),
    path("personas/<int:pk>/", views_personas.persona_detalle, name="persona_detalle"),
    path("personas/<int:pk>/editar/", views_personas.persona_editar, name="persona_editar"),
    path("personas/<int:pk>/retiro/", views_personas.retiro_iniciar, name="retiro_iniciar"),
    path("paz-y-salvo/", views_personas.retiros_lista, name="retiros_lista"),
    path("paz-y-salvo/<int:pk>/", views_personas.retiro_detalle, name="retiro_detalle"),
    path("paz-y-salvo/<int:pk>/emitir/", views_personas.retiro_emitir, name="retiro_emitir"),
    path("paz-y-salvo/<int:pk>/cancelar/", views_personas.retiro_cancelar, name="retiro_cancelar"),
    path("paz-y-salvo/<int:pk>/documento/", views_personas.paz_y_salvo, name="paz_y_salvo"),
    path("paz-y-salvo/item/<int:pk>/validar/", views_personas.retiro_item_validar, name="retiro_item_validar"),
    path("clientes/", views_catalogos.clientes_lista, name="clientes_lista"),
    path("clientes/nuevo/", views_catalogos.cliente_crear, name="cliente_crear"),
    path("clientes/puestos.json", views_catalogos.puestos_json, name="puestos_json"),
    path("clientes/<int:pk>/", views_catalogos.cliente_detalle, name="cliente_detalle"),
    path("clientes/<int:pk>/estado/", views_catalogos.cliente_cambiar_estado, name="cliente_cambiar_estado"),
    path("clientes/<int:pk>/puestos/nuevo/", views_catalogos.puesto_crear, name="puesto_crear"),
    path("puestos/<int:pk>/estado/", views_catalogos.puesto_cambiar_estado, name="puesto_cambiar_estado"),
    path(
        "equipos/<str:placa>/antivirus/",
        views_equipos.equipo_renovar_antivirus,
        name="equipo_renovar_antivirus",
    ),
    path("politica/", views_equipos.politica_lista, name="politica_lista"),
    path("politica/<int:pk>/", views_equipos.politica_detalle, name="politica_detalle"),
    path(
        "equipos/<str:placa>/politica/",
        views_equipos.politica_registrar,
        name="politica_registrar",
    ),
    path(
        "mantenimientos/panel/",
        views_equipos.panel_mantenimientos,
        name="panel_mantenimientos",
    ),
    path("equipos/nuevo/", views_equipos.equipo_crear, name="equipo_crear"),
    path("auditoria/", views_auditoria.auditoria_lista, name="auditoria"),
    # Solicitudes de soporte (mesa de ayuda)
    path("solicitudes/", views_tickets.tickets_lista, name="tickets_lista"),
    path("solicitudes/nueva/", views_tickets.ticket_crear, name="ticket_crear"),
    path("solicitudes/indicadores/", views_tickets.tickets_indicadores, name="tickets_indicadores"),
    path("solicitudes/fotos/<int:pk>/", views_tickets.ticket_foto, name="ticket_foto"),
    path("solicitudes/<str:numero>/", views_tickets.ticket_detalle, name="ticket_detalle"),
    path("solicitudes/<str:numero>/asignar/", views_tickets.ticket_asignar, name="ticket_asignar"),
    path("solicitudes/<str:numero>/iniciar/", views_tickets.ticket_iniciar, name="ticket_iniciar"),
    path("solicitudes/<str:numero>/atender/", views_tickets.ticket_atender, name="ticket_atender"),
    path("solicitudes/<str:numero>/cancelar/", views_tickets.ticket_cancelar, name="ticket_cancelar"),
    path("solicitudes/<str:numero>/comentar/", views_tickets.ticket_comentar, name="ticket_comentar"),
    path(
        "equipos/<str:placa>/",
        views_equipos.equipo_detalle,
        name="equipo_detalle",
    ),
    path(
        "equipos/<str:placa>/pestanas/",
        views_equipos.equipo_pestanas,
        name="equipo_pestanas",
    ),
    path(
        "equipos/<str:placa>/editar/",
        views_equipos.equipo_editar,
        name="equipo_editar",
    ),
    path(
        "equipos/<str:placa>/baja/",
        views_equipos.equipo_dar_baja,
        name="equipo_dar_baja",
    ),
    path(
        "equipos/<str:placa>/reactivar/",
        views_equipos.equipo_reactivar,
        name="equipo_reactivar",
    ),
    path(
        "equipos/<str:placa>/entregar/",
        views_equipos.equipo_entregar,
        name="equipo_entregar",
    ),
    path(
        "equipos/<str:placa>/cambio-gps/",
        views_equipos.equipo_cambio_gps,
        name="equipo_cambio_gps",
    ),
    path(
        "entregas-equipos/<int:asignacion_id>/devolver/",
        views_equipos.equipo_devolver,
        name="equipo_devolver",
    ),
    path(
        "entregas-equipos/<int:asignacion_id>/acta/",
        views_equipos.equipo_acta,
        name="equipo_acta",
    ),
    path(
        "equipos/<str:placa>/hoja-de-vida/",
        views_equipos.equipo_hoja_vida,
        name="equipo_hoja_vida",
    ),
    path("radios/nuevo/", views.radio_crear, name="radio_crear"),
    path(
        "radios/<int:radio_id>/editar/",
        views.radio_editar,
        name="radio_editar",
    ),
    path(
        "radios/<int:radio_id>/transferir-componentes/",
        views.radio_transferir_componentes,
        name="radio_transferir_componentes",
    ),
    path(
        "radios/<int:radio_id>/baja/",
        views.radio_dar_baja,
        name="radio_dar_baja",
    ),
    path(
        "radios/<int:radio_id>/reactivar/",
        views.radio_reactivar,
        name="radio_reactivar",
    ),
    path(
        "radios/<int:radio_id>/",
        views.radio_detalle,
        name="radio_detalle",
    ),
    path(
        "mantenimientos/",
        views.mantenimientos_lista,
        name="mantenimientos_lista",
    ),
    path(
        "mantenimientos/nuevo/",
        views.mantenimiento_crear,
        name="mantenimiento_crear",
    ),
    path(
        "mantenimientos/programados/",
        views.mantenimientos_programados_lista,
        name="mantenimientos_programados_lista",
    ),
    path(
        "mantenimientos/programar/",
        views.mantenimiento_programado_crear,
        name="mantenimiento_programado_crear",
    ),
    path(
        "mantenimientos/programados/<int:programacion_id>/completar/",
        views.mantenimiento_programado_completar,
        name="mantenimiento_programado_completar",
    ),
    path(
        "mantenimientos/programados/<int:programacion_id>/cancelar/",
        views.mantenimiento_programado_cancelar,
        name="mantenimiento_programado_cancelar",
    ),
    path(
        "asignaciones/nueva/",
        views.asignacion_crear,
        name="asignacion_crear",
    ),
    path(
        "asignaciones/<int:asignacion_id>/acta/",
        views.asignacion_acta,
        name="asignacion_acta",
    ),
    path(
        "asignaciones/<int:asignacion_id>/devolver/",
        views.asignacion_devolver,
        name="asignacion_devolver",
    ),
    path(
        "vigilantes/",
        views.vigilantes_lista,
        name="vigilantes_lista",
    ),
]
