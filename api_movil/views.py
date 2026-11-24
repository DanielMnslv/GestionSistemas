from django.contrib.auth import authenticate
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from django.urls import reverse
from pathlib import Path
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.uploadedfile import UploadedFile
import hashlib

from inventario.models import (
    Equipo, Radio, Cliente, Puesto, AsignacionEquipo, AsignacionRadio,
    MantenimientoEquipo, RegistroAuditoria,
)
from inventario.permisos import ENCARGADO, TECNICO
from .authentication import BearerTokenAuthentication
from .models import OperacionMovil, EvidenciaOperacion
from .permissions import UsuarioJanoMovil
from .serializers import LoginSerializer, OperacionSerializer, SyncSerializer


def roles_usuario(user):
    roles = set(user.groups.values_list("name", flat=True))
    return {
        "entregas": bool(user.is_superuser or ENCARGADO in roles),
        "mantenimientos": bool(user.is_superuser or TECNICO in roles),
    }


def puede_operar(user, tipo):
    p = roles_usuario(user)
    return p["mantenimientos"] if tipo == "MANTENIMIENTO" else p["entregas"]


class LoginMovilView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(request, username=s.validated_data["usuario"], password=s.validated_data["clave"])
        if not user or not user.is_active:
            return Response({"error": "Usuario o contraseña incorrectos."}, status=status.HTTP_401_UNAUTHORIZED)
        permisos = roles_usuario(user)
        if not any(permisos.values()):
            return Response({"error": "El usuario no tiene permisos para JANO MÓVIL."}, status=status.HTTP_403_FORBIDDEN)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "token": token.key,
            "usuario": user.get_username(),
            "nombre": user.get_full_name() or user.get_username(),
            "permisos": permisos,
        })


class CatalogoMovilView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]

    def get(self, request):
        equipos = []
        for e in Equipo.objects.filter(activo=True).select_related("radio").order_by("placa"):
            ae = AsignacionEquipo.objects.filter(equipo=e, estado="ASIGNADO").select_related("puesto").first()
            ar = None
            radio = getattr(e, "radio", None)
            if radio:
                ar = AsignacionRadio.objects.filter(radio=radio, estado="ASIGNADO").select_related("puesto").first()
            asignacion = ar or ae
            puesto = getattr(asignacion, "puesto", None) if asignacion else None
            cliente_nombre = puesto.cliente.nombre if puesto else (getattr(asignacion, "cliente_asignado", "") if ar else "")
            sede = puesto.sede if puesto else ""
            puesto_nombre = puesto.nombre if puesto else (getattr(asignacion, "puesto_asignado", "") if ar else "")
            responsable = ""
            cedula = ""
            if ar:
                responsable = ar.coordinador_zona
                cedula = ar.cedula_funcionario
            elif radio:
                # Reutiliza el coordinador ya registrado en la ficha del radio,
                # incluso si actualmente está en bodega y no tiene asignación activa.
                responsable = radio.coordinador_zona or ""
                cedula = radio.cedula_funcionario or ""
            elif ae:
                responsable = ae.nombre_recibe or (ae.funcionario.nombre_completo if ae.funcionario_id else "")
                cedula = ae.cedula_recibe or (ae.funcionario.cedula if ae.funcionario_id else "")
            equipos.append({
                "public_id": str(e.public_id), "placa": e.placa, "tipo": e.tipo,
                "tipo_texto": e.get_tipo_display(), "es_radio": bool(radio),
                "serial": (radio.serial if radio and radio.serial else e.serial),
                "marca": (radio.marca if radio and radio.marca else e.marca),
                "modelo": (radio.modelo if radio and radio.modelo else e.modelo),
                "estado": e.estado_texto, "asignado": bool(asignacion),
                "responsable_nombre": responsable, "responsable_cedula": cedula,
                "ubicacion": " · ".join(x for x in [cliente_nombre, sede, puesto_nombre] if x) or e.ubicacion,
                "cliente_id": puesto.cliente_id if puesto else None,
                "puesto_id": puesto.pk if puesto else None,
                "requiere_revision": e.requiere_revision,
                "propiedad": e.propiedad,
            })
        clientes = list(Cliente.objects.filter(activo=True).order_by("nombre").values("id", "public_id", "nombre", "nit"))
        puestos_qs = Puesto.objects.filter(activo=True, cliente__activo=True).select_related("cliente").order_by("cliente__nombre", "sede", "nombre")
        puestos = [{"id": p.pk, "public_id": str(p.public_id), "cliente_id": p.cliente_id,
                    "cliente": p.cliente.nombre, "sede": p.sede, "nombre": p.nombre,
                    "latitud": str(p.latitud) if p.latitud is not None else None,
                    "longitud": str(p.longitud) if p.longitud is not None else None} for p in puestos_qs]
        sedes = sorted({(p.cliente_id, p.cliente.nombre, p.sede) for p in puestos_qs if p.sede})
        from inventario import actividades_mantenimiento as act
        from inventario.models import Funcionario
        actividades = lambda mapa: [
            {"tipo": tipo, "opciones": [{"valor": clave, "texto": texto} for clave, texto in lista]}
            for tipo, lista in mapa.items()
        ]
        return Response({
            "generado": timezone.now().isoformat(),
            "permisos": roles_usuario(request.user),
            "equipos": equipos,
            "clientes": clientes,
            "sedes": [{"cliente_id": cid, "cliente": nombre, "nombre": sede} for cid, nombre, sede in sedes],
            "puestos": puestos,
            "clausula_radio": "",
            "clausula_equipo": "",
            "opciones": {
                "estados_componente": ["Bueno", "Regular", "Dañado", "No tiene"],
                "tipos_mantenimiento": [{"valor": v, "texto": l} for v, l in MantenimientoEquipo.Tipo.choices if v in MantenimientoEquipo.TIPOS_FORMULARIO],
                "resultados": [{"valor": v, "texto": l} for v, l in MantenimientoEquipo.Resultado.choices],
                "estados_finales": [{"valor": v, "texto": l} for v, l in MantenimientoEquipo.EstadoFinal.choices],
                "estados_entrega": [{"valor": v, "texto": l} for v, l in MantenimientoEquipo.EstadoEntrega.choices],
                "actividades_preventivas": actividades(act.PREVENTIVAS),
                "componentes_correctivos": actividades(act.CORRECTIVAS),
                "tecnicos": ["Yeiver Arcenio Prada Fierro", "Daniel Felipe Jiménez Loaiza"],
                "funcionarios": [{"valor": str(pk), "texto": nombre} for pk, nombre in
                    Funcionario.objects.filter(activo=True).exclude(nombre_completo="").order_by("nombre_completo")
                    .values_list("pk", "nombre_completo")],
            },
        })


class DashboardMovilView(APIView):
    """Indicadores centrales del dashboard web para el inicio móvil."""
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]

    def get(self, request):
        from inventario.panel import datos_inicio

        datos = datos_inicio()
        actividad = [{
            "fecha": item["fecha"].isoformat(),
            "clase": item["clase"],
            "titulo": item["titulo"],
            "detalle": item["detalle"],
        } for item in datos.get("actividad", [])]
        return Response({
            "generado": timezone.now().isoformat(),
            "equipos_activos": datos["total"],
            "operativos": datos["n_ok"],
            "regulares": datos["n_reg"],
            "no_operativos": datos["n_mal"],
            "sin_estado": datos["n_sin"],
            "entregados": datos["entregados"],
            "en_bodega": datos["en_bodega"],
            "mantenimiento_vencido": datos["mant_vencidos"],
            "sin_mantenimiento": datos["mant_sin"],
            "mantenimiento_proximo": datos["mant_proximos"],
            "mantenimiento_vigente": datos["mant_vigentes"],
            "por_revisar": datos["en_revision"],
            "politica_pendiente": datos["politica_pendientes"],
            "antivirus_vencidos": datos["antivirus_vencidos"],
            "antivirus_por_vencer": datos["antivirus_por_vencer"],
            "programados_mes": datos["programados_mes"],
            "radios_danados": datos["radios_danados"],
            "tipos": datos["tipos"],
            "actividad": actividad,
        })


class HistorialEquipoMovilView(APIView):
    """Historial operativo/técnico de un activo, consultable desde el móvil."""
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]

    def get(self, request, public_id):
        equipo = get_object_or_404(Equipo.objects.select_related("radio"), public_id=public_id)
        eventos = []
        asignaciones_equipo = AsignacionEquipo.objects.filter(equipo=equipo).select_related("puesto", "entregado_por", "recibido_por")
        for a in asignaciones_equipo:
            puesto = a.puesto
            eventos.append({
                "id": str(a.public_id), "tipo": "ENTREGA_DEVOLUCION", "estado": a.estado,
                "fecha": a.fecha_devolucion.isoformat() if a.fecha_devolucion else a.fecha_entrega.isoformat(),
                "fecha_entrega": a.fecha_entrega.isoformat(),
                "fecha_devolucion": a.fecha_devolucion.isoformat() if a.fecha_devolucion else None,
                "cliente": puesto.cliente.nombre if puesto else "",
                "sede": puesto.sede if puesto else "", "puesto": puesto.nombre if puesto else a.area,
                "responsable": a.nombre_recibe or (a.funcionario.nombre_completo if a.funcionario_id else ""),
                "tecnico": a.entregado_por.get_full_name() or a.entregado_por.get_username(),
                "estado_entrega": a.estado_entrega, "accesorios": a.accesorios,
                "observaciones": a.observaciones_devolucion or a.observaciones_entrega,
                "firma_devolucion_registrada": bool(a.firma_devolucion),
                "inspeccion_devolucion": a.inspeccion_devolucion,
            })
        radio = getattr(equipo, "radio", None)
        if radio:
            asignaciones_radio = AsignacionRadio.objects.filter(radio=radio).select_related("puesto", "entregado_por", "recibido_por")
            for a in asignaciones_radio:
                puesto = a.puesto
                eventos.append({
                    "id": str(a.public_id), "tipo": "ENTREGA_DEVOLUCION", "estado": a.estado,
                    "fecha": a.fecha_devolucion.isoformat() if a.fecha_devolucion else a.fecha_entrega.isoformat(),
                    "fecha_entrega": a.fecha_entrega.isoformat(),
                    "fecha_devolucion": a.fecha_devolucion.isoformat() if a.fecha_devolucion else None,
                    "cliente": puesto.cliente.nombre if puesto else a.cliente_asignado,
                    "sede": puesto.sede if puesto else "", "puesto": puesto.nombre if puesto else a.puesto_asignado,
                    "responsable": a.coordinador_zona,
                    "tecnico": a.entregado_por.get_full_name() or a.entregado_por.get_username(),
                    "estado_entrega": {"radio": a.estado_radio_entrega, "base": a.estado_base_entrega,
                                       "cargador": a.estado_cargador_entrega, "antena": a.estado_antena_entrega,
                                       "baterias": a.estado_baterias_entrega},
                    "accesorios": "", "observaciones": a.observaciones_devolucion or a.observaciones_entrega,
                    "firma_devolucion_registrada": bool(a.firma_devolucion),
                    "inspeccion_devolucion": a.inspeccion_devolucion,
                })
        mantenimientos = MantenimientoEquipo.objects.filter(equipo=equipo).select_related("registrado_por")
        for m in mantenimientos:
            eventos.append({
                "id": str(m.public_id), "tipo": "MANTENIMIENTO", "estado": m.estado_final,
                "fecha": m.fecha_intervencion.isoformat(), "fecha_entrega": None, "fecha_devolucion": None,
                "cliente": "", "sede": "", "puesto": "", "responsable": "",
                "tecnico": m.tecnico_responsable, "estado_entrega": m.estado_final,
                "accesorios": m.repuestos_utilizados,
                "observaciones": m.observaciones,
                "detalle": {"tipo": m.get_tipo_display(), "motivo": m.motivo,
                            "diagnostico": m.diagnostico, "trabajo_realizado": m.trabajo_realizado,
                            "resultado": m.get_resultado_display()},
            })
        eventos.sort(key=lambda x: x["fecha"], reverse=True)
        evidencias = []
        qs_evidencias = EvidenciaOperacion.objects.filter(
            operacion__placa=equipo.placa, operacion__estado="OK"
        )
        # El historial del activo es compartido por los roles autorizados,
        # pero las evidencias (fotos/firmas) solo se exponen a su propietario.
        if not request.user.is_superuser:
            qs_evidencias = qs_evidencias.filter(operacion__usuario=request.user)
        qs_evidencias = qs_evidencias.select_related("operacion").order_by("creada_en")
        for evidencia in qs_evidencias:
            url = request.build_absolute_uri(
                reverse("api-movil-evidencia-detail", kwargs={"evidencia_id": evidencia.pk})
            )
            evidencias.append({
                "id": str(evidencia.pk), "operacion_uuid": str(evidencia.operacion_id),
                "tipo": evidencia.tipo, "nombre": evidencia.nombre_original,
                "mime_type": evidencia.mime_type, "bytes": evidencia.bytes,
                "url": url, "creada_en": evidencia.creada_en.isoformat(),
            })
        return Response({
            "equipo": {"public_id": str(equipo.public_id), "placa": equipo.placa,
                       "tipo": equipo.get_tipo_display(), "serial": equipo.serial,
                       "marca": equipo.marca, "modelo": equipo.modelo},
            "total": len(eventos), "eventos": eventos, "evidencias": evidencias,
        })


class SyncMovilView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]

    def post(self, request):
        sobre = SyncSerializer(data=request.data)
        sobre.is_valid(raise_exception=True)
        resultados = []

        # Cada operación se valida y procesa de forma independiente. Una
        # operación inválida no bloquea las demás del mismo lote.
        for raw in sobre.validated_data["operaciones"]:
            serializador = OperacionSerializer(data=raw)
            if not serializador.is_valid():
                resultados.append({
                    "uuid": str(raw.get("uuid") or ""),
                    "ok": False,
                    "error": str(serializador.errors),
                    "duplicada": False,
                    "reintentar": False,
                })
                continue

            op = serializador.validated_data
            op_uuid = op["uuid"]
            tipo = op["tipo"]
            datos = op["datos"]
            placa = str(datos.get("placa") or "").strip()

            if not puede_operar(request.user, tipo):
                resultados.append({
                    "uuid": str(op_uuid), "ok": False,
                    "error": "Tu usuario no tiene permiso para esta operación.",
                    "duplicada": False, "reintentar": False,
                })
                continue

            existente = OperacionMovil.objects.filter(pk=op_uuid).first()
            if existente:
                if existente.usuario_id != request.user.pk:
                    resultados.append({
                        "uuid": str(op_uuid), "ok": False,
                        "error": "El identificador de operación pertenece a otra cuenta.",
                        "duplicada": False, "reintentar": False,
                    })
                else:
                    resultados.append(self._respuesta_existente(existente))
                continue

            try:
                with transaction.atomic():
                    # El registro de idempotencia y el movimiento central
                    # quedan confirmados o revertidos en una sola transacción.
                    registro = OperacionMovil.objects.create(
                        uuid=op_uuid, usuario=request.user, tipo=tipo, placa=placa,
                        payload={"fecha_cliente": op["fecha"].isoformat(), "datos": datos},
                        estado="PROCESANDO",
                    )
                    equipo = Equipo.objects.select_for_update().select_related("radio").get(
                        placa=placa, activo=True
                    )
                    if tipo == "ENTREGA":
                        self._entrega(request.user, equipo, datos, op["fecha"])
                    elif tipo == "DEVOLUCION":
                        self._devolucion(request.user, equipo, datos, op["fecha"])
                    else:
                        self._mantenimiento(request.user, equipo, datos, op["fecha"])

                    registro.estado = "OK"
                    registro.resultado = {"ok": True, "placa": placa}
                    registro.procesada_en = timezone.now()
                    registro.save(update_fields=["estado", "resultado", "procesada_en"])

                resultados.append({
                    "uuid": str(op_uuid), "ok": True, "error": None,
                    "duplicada": False, "reintentar": False,
                })
            except IntegrityError:
                existente = OperacionMovil.objects.filter(pk=op_uuid).first()
                if existente and existente.usuario_id == request.user.pk:
                    resultados.append(self._respuesta_existente(existente))
                elif existente:
                    resultados.append({
                        "uuid": str(op_uuid), "ok": False,
                        "error": "El identificador de operación pertenece a otra cuenta.",
                        "duplicada": False, "reintentar": False,
                    })
                else:
                    mensaje = "El activo cambió durante la operación. Actualiza el catálogo y verifica su estado."
                    self._guardar_rechazo(op_uuid, request.user, tipo, placa, op, mensaje)
                    resultados.append({
                        "uuid": str(op_uuid), "ok": False, "error": mensaje,
                        "duplicada": False, "reintentar": False,
                    })
            except (Equipo.DoesNotExist, Puesto.DoesNotExist, AsignacionEquipo.DoesNotExist,
                    AsignacionRadio.DoesNotExist, ValueError) as exc:
                mensaje = str(exc) or "No fue posible validar la operación."
                self._guardar_rechazo(op_uuid, request.user, tipo, placa, op, mensaje)
                resultados.append({
                    "uuid": str(op_uuid), "ok": False, "error": mensaje,
                    "duplicada": False, "reintentar": False,
                })
            except Exception:
                # Error inesperado: no se marca como rechazado de forma
                # permanente. Android puede reintentar el mismo UUID.
                resultados.append({
                    "uuid": str(op_uuid), "ok": False,
                    "error": "Error interno al procesar la operación.",
                    "duplicada": False, "reintentar": True,
                })

        return Response({"resultados": resultados})

    @staticmethod
    def _guardar_rechazo(op_uuid, user, tipo, placa, op, mensaje):
        """Persiste rechazos de negocio para que el mismo UUID no se reprocese."""
        try:
            OperacionMovil.objects.get_or_create(
                uuid=op_uuid,
                defaults={
                    "usuario": user,
                    "tipo": tipo,
                    "placa": placa,
                    "payload": {"fecha_cliente": op["fecha"].isoformat(), "datos": op["datos"]},
                    "resultado": {"ok": False, "error": mensaje},
                    "estado": "RECHAZADA",
                    "procesada_en": timezone.now(),
                },
            )
        except IntegrityError:
            # Otra solicitud concurrente pudo registrar primero el UUID.
            pass

    @staticmethod
    def _respuesta_existente(registro):
        ok = registro.estado == "OK"
        return {"uuid": str(registro.pk), "ok": ok,
                "error": registro.resultado.get("error") if not ok else None,
                "duplicada": True, "reintentar": registro.estado == "PROCESANDO"}

    def _entrega(self, user, equipo, d, fecha):
        puesto = Puesto.objects.get(pk=d.get("puesto_id"), activo=True) if d.get("puesto_id") else None
        if not puesto:
            raise ValueError("Selecciona un puesto válido del catálogo descargado.")
        if getattr(equipo, "radio", None) is not None:
            radio = Radio.objects.select_for_update().get(equipo=equipo)
            if AsignacionRadio.objects.filter(radio=radio, estado="ASIGNADO").exists():
                raise ValueError("El radio ya tiene una asignación activa.")
            coordinador = d.get("coordinador_zona") or radio.coordinador_zona or ""
            asignacion = AsignacionRadio.objects.create(
                radio=radio, fecha_entrega=fecha, coordinador_zona=coordinador,
                cedula_funcionario=d.get("responsable_cedula", d.get("cedula", "")), cliente_asignado=puesto.cliente.nombre,
                puesto_asignado=puesto.nombre, puesto=puesto, entregado_por=user,
                observaciones_entrega=d.get("observaciones", ""),
                estado_radio_entrega=d.get("estado_radio", ""),
                estado_base_entrega=d.get("estado_base", ""),
                estado_cargador_entrega=d.get("estado_cargador", ""),
                estado_antena_entrega=d.get("estado_antena", ""),
                estado_baterias_entrega=d.get("estado_baterias", ""),
                clausula_aceptada=bool(d.get("clausula_aceptada")), firma=d.get("firma", ""))
            radio.coordinador_zona = coordinador
            radio.cliente_asignado = puesto.cliente.nombre
            radio.puesto_asignado = puesto.nombre
            radio.save(update_fields=["coordinador_zona", "cliente_asignado", "puesto_asignado", "actualizado_en"])
        else:
            if not str(d.get("responsable_nombre") or "").strip():
                raise ValueError("La entrega requiere el nombre de quien recibe el equipo.")
            if AsignacionEquipo.objects.filter(equipo=equipo, estado="ASIGNADO").exists():
                raise ValueError("El equipo ya tiene una asignación activa.")
            AsignacionEquipo.objects.create(
                equipo=equipo, fecha_entrega=fecha, funcionario=None,
                nombre_recibe=d.get("responsable_nombre", ""), cedula_recibe=d.get("responsable_cedula", ""),
                area=f"{puesto.cliente.nombre} · {puesto.sede} · {puesto.nombre}",
                puesto=puesto, entregado_por=user, estado_entrega=d.get("estado_entrega", ""),
                accesorios=d.get("accesorios", ""), observaciones_entrega=d.get("observaciones", ""),
                clausula_aceptada=bool(d.get("clausula_aceptada")), firma=d.get("firma", ""))
        equipo.responsable_nombre = d.get("responsable_nombre") or (getattr(equipo.radio, "coordinador_zona", "") if hasattr(equipo, "radio") else "")
        equipo.responsable_cedula = d.get("responsable_cedula", d.get("cedula", ""))
        equipo.ubicacion = f"{puesto.cliente.nombre} · {puesto.sede} · {puesto.nombre}"
        equipo.save(update_fields=["responsable_nombre", "responsable_cedula", "ubicacion", "actualizado_en"])

    def _devolucion(self, user, equipo, d, fecha):
        if hasattr(equipo, "radio"):
            a = AsignacionRadio.objects.select_for_update().get(radio=equipo.radio, estado="ASIGNADO")
        else:
            a = AsignacionEquipo.objects.select_for_update().get(equipo=equipo, estado="ASIGNADO")
        a.estado = "DEVUELTO"
        a.fecha_devolucion = fecha
        a.observaciones_devolucion = d.get("observaciones", "")
        a.firma_devolucion = d.get("firma", "")
        a.inspeccion_devolucion = d.get("inspeccion", {}) or {}
        a.recibido_por = user
        a.save(update_fields=[
            "estado", "fecha_devolucion", "observaciones_devolucion",
            "firma_devolucion", "inspeccion_devolucion", "recibido_por", "actualizado_en",
        ])
        equipo.responsable_nombre = ""
        equipo.responsable_cedula = ""
        equipo.ubicacion = d.get("ubicacion_destino", "Bodega") or "Bodega"
        equipo.save(update_fields=["responsable_nombre", "responsable_cedula", "ubicacion", "actualizado_en"])

    def _mantenimiento(self, user, equipo, d, fecha):
        from inventario import actividades_mantenimiento as act
        preventivas = d.get("actividades_preventivas") or []
        correctivas = d.get("componentes_intervenidos") or []
        if not isinstance(preventivas, list) or not isinstance(correctivas, list):
            raise ValueError("Las actividades deben enviarse como listas.")
        tipo = d["tipo"]
        if tipo == MantenimientoEquipo.Tipo.PREVENTIVO:
            permitidas = act.claves_validas(act.PREVENTIVAS, equipo.tipo)
            if not preventivas or set(preventivas) - permitidas:
                raise ValueError("Selecciona actividades preventivas válidas para este equipo.")
            if "otros" in preventivas and not str(d.get("actividad_preventiva_otros") or "").strip():
                raise ValueError("Describe las otras actividades realizadas.")
        else:
            preventivas = []
        if tipo == MantenimientoEquipo.Tipo.CORRECTIVO:
            permitidas = act.claves_validas(act.CORRECTIVAS, equipo.tipo)
            if not correctivas or set(correctivas) - permitidas:
                raise ValueError("Selecciona las partes intervenidas válidas para este equipo.")
            if not str(d.get("causa_dano") or "").strip():
                raise ValueError("Describe la posible causa del daño.")
        else:
            correctivas = []
        funcionario_id = d.get("funcionario_responsable") or None
        nombre_recibe = str(d.get("recibido_por_nombre") or "").strip()
        firma = str(d.get("firma_recibido") or "")
        tecnico = str(d.get("tecnico") or user.get_full_name() or user.get_username()).strip()
        tecnicos_validos = {"Yeiver Arcenio Prada Fierro", "Daniel Felipe Jiménez Loaiza"}
        if tecnico not in tecnicos_validos:
            raise ValueError("Selecciona un especialista válido.")
        estados_entrega = d.get("estados_entrega") or []
        permitidos_estado = {valor for valor, _ in MantenimientoEquipo.EstadoEntrega.choices}
        if not isinstance(estados_entrega, list) or set(estados_entrega) - permitidos_estado:
            raise ValueError("Selecciona estados de entrega válidos.")
        if not nombre_recibe or not firma:
            raise ValueError("Registra quién recibe el equipo y su firma.")
        from inventario.forms import validar_firma
        from django import forms
        try:
            firma = validar_firma(firma)
        except forms.ValidationError as exc:
            raise ValueError("La firma de quien recibe no es vÃ¡lida.") from exc
        funcionario = None
        if funcionario_id:
            from inventario.models import Funcionario
            funcionario = Funcionario.objects.filter(pk=funcionario_id, activo=True).first()
            if not funcionario:
                raise ValueError("El funcionario responsable no es válido.")
        MantenimientoEquipo.objects.create(
            equipo=equipo, fecha_intervencion=fecha,
            tipo=d["tipo"], tecnico_responsable=tecnico,
            funcionario_responsable=funcionario, motivo=d.get("motivo", ""), diagnostico=d.get("diagnostico", ""),
            causa_dano=d.get("causa_dano", ""), actividades_preventivas=preventivas,
            actividad_preventiva_otros=d.get("actividad_preventiva_otros", ""),
            componentes_intervenidos=correctivas, estados_entrega=estados_entrega,
            trabajo_realizado=d.get("trabajo_realizado", ""), repuestos_utilizados=d.get("repuestos", ""),
            resultado=d.get("resultado", "SOLUCIONADO"), estado_final=d.get("estado_final", ""),
            observaciones=d.get("observaciones", ""), recibido_por_nombre=nombre_recibe,
            firma_recibido=firma, registrado_por=user)
        equipo.actualizar_estado_operativo()


class EvidenciaMovilView(APIView):
    """Recibe fotografías únicamente para operaciones centrales confirmadas."""
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 8 * 1024 * 1024

    def post(self, request):
        raw_uuid = str(request.data.get("operacion_uuid") or "").strip()
        archivo = request.FILES.get("archivo")
        tipo = str(request.data.get("tipo") or "GENERAL").strip().upper()[:32]
        if not raw_uuid or not archivo:
            return Response({"error": "Se requiere operacion_uuid y archivo."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            import uuid as uuid_lib
            op_uuid = uuid_lib.UUID(raw_uuid)
        except (ValueError, TypeError, AttributeError):
            return Response({"error": "El UUID de operación no es válido."}, status=status.HTTP_400_BAD_REQUEST)
        operacion = get_object_or_404(OperacionMovil, pk=op_uuid)
        if operacion.usuario_id != request.user.pk and not request.user.is_superuser:
            return Response({"error": "No puedes adjuntar evidencias a operaciones de otro usuario."}, status=status.HTTP_403_FORBIDDEN)
        if operacion.estado != "OK":
            return Response({"error": "La operación debe estar confirmada en JANO INVENTARIO antes de cargar evidencias."}, status=status.HTTP_409_CONFLICT)
        if archivo.size <= 0 or archivo.size > self.MAX_BYTES:
            return Response({"error": "La imagen debe pesar entre 1 byte y 8 MB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        inicio = archivo.read(16)
        archivo.seek(0)
        mime = None
        if inicio.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif inicio.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif len(inicio) >= 12 and inicio[:4] == b"RIFF" and inicio[8:12] == b"WEBP":
            mime = "image/webp"
        if not mime:
            return Response({"error": "Formato no permitido. Usa JPEG, PNG o WEBP."}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

        digest = hashlib.sha256()
        for chunk in archivo.chunks():
            digest.update(chunk)
        archivo.seek(0)
        sha = digest.hexdigest()
        existente = EvidenciaOperacion.objects.filter(operacion=operacion, sha256=sha).first()
        if existente:
            return Response({"id": str(existente.pk), "duplicada": True, "tipo": existente.tipo}, status=status.HTTP_200_OK)

        nombre = str(getattr(archivo, "name", "evidencia"))[:255]
        evidencia = EvidenciaOperacion.objects.create(
            operacion=operacion, archivo=archivo, tipo=tipo or "GENERAL",
            nombre_original=nombre, mime_type=mime, sha256=sha, bytes=archivo.size,
            cargada_por=request.user,
        )
        return Response({
            "id": str(evidencia.pk), "duplicada": False, "tipo": evidencia.tipo,
            "mime_type": evidencia.mime_type, "bytes": evidencia.bytes,
        }, status=status.HTTP_201_CREATED)


class EvidenciaMovilDetailView(APIView):
    """Entrega una evidencia mediante una ruta autenticada, sin publicar MEDIA_URL."""
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated, UsuarioJanoMovil]

    def get(self, request, evidencia_id):
        evidencia = get_object_or_404(
            EvidenciaOperacion.objects.select_related("operacion"), pk=evidencia_id
        )
        if evidencia.operacion.usuario_id != request.user.pk and not request.user.is_superuser:
            return Response({"error": "No tienes permiso para consultar esta evidencia."}, status=status.HTTP_403_FORBIDDEN)
        nombre = Path(evidencia.nombre_original or "evidencia").name.replace('"', "")
        respuesta = FileResponse(evidencia.archivo.open("rb"), content_type=evidencia.mime_type)
        respuesta["Content-Disposition"] = f'inline; filename="{nombre}"'
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
