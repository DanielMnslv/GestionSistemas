from rest_framework import serializers
from inventario.models import MantenimientoEquipo


class LoginSerializer(serializers.Serializer):
    usuario = serializers.CharField(max_length=150)
    clave = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class OperacionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    tipo = serializers.ChoiceField(choices=["ENTREGA", "DEVOLUCION", "MANTENIMIENTO"])
    fecha = serializers.DateTimeField()
    datos = serializers.DictField()

    def validate(self, attrs):
        tipo, datos = attrs["tipo"], attrs["datos"]
        placa = str(datos.get("placa") or "").strip()
        if not placa:
            raise serializers.ValidationError({"datos": "La placa del activo es obligatoria."})

        if tipo == "ENTREGA":
            try:
                int(datos.get("puesto_id"))
            except (TypeError, ValueError):
                raise serializers.ValidationError({"datos": "La entrega requiere un puesto válido."})
            if not datos.get("firma"):
                raise serializers.ValidationError({"datos": "La firma de recepción es obligatoria."})
            if not datos.get("clausula_aceptada"):
                raise serializers.ValidationError({"datos": "Debe constar la aceptación de la cláusula."})

        elif tipo == "DEVOLUCION":
            if not datos.get("firma"):
                raise serializers.ValidationError({"datos": "La firma de quien devuelve es obligatoria."})
            inspeccion = datos.get("inspeccion")
            if inspeccion is not None and not isinstance(inspeccion, dict):
                raise serializers.ValidationError({"datos": "La inspección de devolución debe ser un objeto."})

        elif tipo == "MANTENIMIENTO":
            requeridos = ["tipo"]
            faltantes = [campo for campo in requeridos if not str(datos.get(campo) or "").strip()]
            if faltantes:
                raise serializers.ValidationError({"datos": "Faltan campos de mantenimiento: " + ", ".join(faltantes)})
            tipos = {v for v, _ in MantenimientoEquipo.Tipo.choices if v in MantenimientoEquipo.TIPOS_FORMULARIO}
            if datos["tipo"] not in tipos:
                raise serializers.ValidationError({"datos": "Tipo de mantenimiento no permitido."})
            resultados = {v for v, _ in MantenimientoEquipo.Resultado.choices}
            estados = {v for v, _ in MantenimientoEquipo.EstadoFinal.choices}
            if datos.get("resultado") and datos["resultado"] not in resultados:
                raise serializers.ValidationError({"datos": "Resultado de mantenimiento no válido."})
            if datos.get("estado_final") and datos["estado_final"] not in estados:
                raise serializers.ValidationError({"datos": "Estado final de mantenimiento no válido."})
        return attrs


class SyncSerializer(serializers.Serializer):
    """Valida solo el sobre. Cada operación se valida por separado en la vista.

    Así un registro defectuoso no bloquea los demás movimientos del lote.
    """
    operaciones = serializers.ListField(child=serializers.DictField(), allow_empty=False)
