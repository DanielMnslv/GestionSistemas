"""Datos de equipos y radios que JANO comparte con Gestión TIC por la API."""
from rest_framework import serializers

from inventario.models import Equipo, Radio


class EquipoIntegracionSerializer(serializers.ModelSerializer):
    """
    Información autorizada de equipos para Gestión TIC.
    """

    class Meta:
        model = Equipo

        fields = [
            "id",
            "public_id",
            "placa",
            "tipo",
            "serial",
            "marca",
            "modelo",
            "propiedad",
            "fecha_compra",
            "estado_operativo",
            "activo",
            "ubicacion",
            "requiere_revision",
            "creado_en",
            "actualizado_en",
        ]

        read_only_fields = fields


class RadioIntegracionSerializer(serializers.ModelSerializer):
    """
    Información autorizada de radios para Gestión TIC.
    """

    class Meta:
        model = Radio

        fields = [
            "id",
            "public_id",
            "codigo_fisico",
            "placa",
            "serial",
            "marca",
            "modelo",
            "tipo_frecuencia",
            "modalidad_servicio",
            "estado_radio",
            "activo",
            "fecha_baja",
            "requiere_revision",
        ]

        read_only_fields = fields