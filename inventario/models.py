
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .estados import tono_estado


class Equipo(models.Model):
    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    """Activo de TI: radio, computador, impresora, GPS, alarma…

    Reúne los datos comunes y concentra mantenimientos, alertas y
    programaciones. Los datos propios de cada tipo viven en tablas de
    detalle uno a uno (por ejemplo, Radio).
    """

    class Tipo(models.TextChoices):
        RADIO = "RADIO", "Radio"
        COMPUTADOR = "COMPUTADOR", "Computador"
        TABLETA = "TABLETA", "Tableta"
        IMPRESORA = "IMPRESORA", "Impresora"
        ESCANER = "ESCANER", "Escáner"
        GPS = "GPS", "GPS"
        ALARMA = "ALARMA", "Alarma"
        UPS = "UPS", "UPS"
        OTRO = "OTRO", "Otro"

    class EstadoOperativo(models.TextChoices):
        OPERATIVO = "OPERATIVO", "Operativo"
        NO_OPERATIVO = "NO_OPERATIVO", "No operativo"

    placa = models.CharField(max_length=50, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, db_index=True)
    serial = models.CharField(max_length=100, blank=True, db_index=True)
    marca = models.CharField(max_length=100, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    propiedad = models.CharField(
        max_length=100,
        blank=True,
        help_text="Propio, arrendado, de JANOTEC…",
    )
    fecha_compra = models.DateField(null=True, blank=True)
    estado_operativo = models.CharField(
        max_length=20, choices=EstadoOperativo.choices, blank=True
    )

    activo = models.BooleanField(default=True, db_index=True)
    fecha_baja = models.DateField(null=True, blank=True)
    motivo_baja = models.TextField(blank=True)

    @property
    def estado_texto(self):
        """Estado a mostrar: el del radio (Operativo, Regular, Dañado, Baja)
        si es un radio; si no, el estado operativo del equipo."""
        radio = getattr(self, "radio", None)
        if radio is not None and radio.estado_radio:
            return radio.estado_radio
        return self.get_estado_operativo_display() if self.estado_operativo else ""

    @property
    def estado_tono(self):
        return {
            "Operativo": "green", "Regular": "amber", "Dañado": "red",
            "Baja": "red", "No operativo": "red",
        }.get(self.estado_texto, "gray")

    # Quién tiene el equipo y dónde está hoy. Las entregas los actualizan.
    responsable_nombre = models.CharField(max_length=200, blank=True)
    responsable_cedula = models.CharField(max_length=50, blank=True)
    ubicacion = models.CharField(max_length=200, blank=True)

    observaciones = models.TextField(blank=True)
    requiere_revision = models.BooleanField(default=False)
    motivo_revision = models.CharField(max_length=255, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ["tipo", "placa"]

    def __str__(self):
        return f"{self.placa} ({self.get_tipo_display()})"


class Radio(models.Model):
    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    # La placa (RJ) es el identificador del radio.
    codigo_fisico = models.CharField(
        "Código físico",
        max_length=50,
        blank=True,
    )
    placa = models.CharField(
        "Placa operativa",
        max_length=50,
        blank=True,
        db_index=True,
    )
    serial = models.CharField(
        "Número de serie",
        max_length=100,
        blank=True,
        db_index=True,
    )

    # Identificación del equipo.
    marca = models.CharField(max_length=100, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    tipo_frecuencia = models.CharField(max_length=50, blank=True)
    modalidad_servicio = models.CharField(max_length=100, blank=True)

    # Accesorios del inventario físico.
    bateria_1 = models.BooleanField(null=True, blank=True)
    bateria_2 = models.BooleanField(null=True, blank=True)
    perilla_encendido = models.BooleanField(null=True, blank=True)
    perilla_frecuencia = models.BooleanField(null=True, blank=True)
    antena = models.BooleanField(null=True, blank=True)
    clip = models.BooleanField(null=True, blank=True)
    base = models.BooleanField(null=True, blank=True)
    cargador = models.BooleanField(null=True, blank=True)

    # Estados registrados en las fuentes operativas.
    # Estado único del radio: Operativo, Regular, Dañado o Baja.
    estado_radio = models.CharField(max_length=100, blank=True)
    estado_base = models.CharField(max_length=100, blank=True)
    estado_cargador = models.CharField(max_length=100, blank=True)
    estado_antena = models.CharField(max_length=100, blank=True)
    estado_baterias = models.CharField(max_length=100, blank=True)
    estado_perilla_encendido = models.CharField(max_length=100, blank=True)
    estado_perilla_frecuencia = models.CharField(max_length=100, blank=True)
    estado_clip = models.CharField(max_length=100, blank=True)
    mantenimiento = models.CharField(max_length=50, blank=True)

    # Información operativa actual.
    coordinador_zona = models.CharField(max_length=200, blank=True)
    cedula_funcionario = models.CharField(max_length=50, blank=True)
    cliente_asignado = models.CharField(max_length=200, blank=True)
    puesto_asignado = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)
    requiere_revision = models.BooleanField(default=False)
    motivo_revision = models.CharField(max_length=255, blank=True, default="")

    # Registro general del radio entre todos los equipos. Se mantiene
    # sincronizado al guardar el radio (ver sincronizar_equipo).
    equipo = models.OneToOneField(
        Equipo,
        on_delete=models.PROTECT,
        related_name="radio",
        null=True,
        blank=True,
        editable=False,
    )

    # Un radio dado de baja se conserva con su historial, pero ya no se
    # puede entregar ni genera alertas de mantenimiento.
    activo = models.BooleanField(default=True, db_index=True)
    fecha_baja = models.DateField(null=True, blank=True)
    motivo_baja = models.TextField(blank=True)

    # Información adicional de la hoja BASEDATOS-RADIOS.
    software_programacion = models.CharField(max_length=200, blank=True)
    version_software = models.CharField(max_length=50, blank=True)
    tipo_licencia = models.CharField(max_length=100, blank=True)
    licencia_software = models.CharField(max_length=200, blank=True)
    fecha_compra = models.DateField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Radio"
        verbose_name_plural = "Radios"
        ordering = ["placa", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["placa"],
                condition=~models.Q(placa=""),
                name="radio_placa_unica",
            ),
        ]

    def __str__(self):
        return f"{self.placa or 'Sin placa'} - {self.marca} {self.modelo}".strip()

    ESTADO_OPERATIVO = "Operativo"
    ESTADO_REGULAR = "Regular"
    ESTADO_DANADO = "Dañado"
    ESTADO_BAJA = "Baja"
    ESTADOS = [
        (ESTADO_OPERATIVO, "Operativo"),
        (ESTADO_REGULAR, "Regular"),
        (ESTADO_DANADO, "Dañado"),
        (ESTADO_BAJA, "Baja"),
    ]

    @classmethod
    def normalizar_estado(cls, texto):
        """Lleva un texto libre ("Bueno", "malo"…) a uno de los 4 estados.
        Devuelve "" si no se reconoce."""
        t = (texto or "").strip().lower()
        if not t:
            return ""
        if "baja" in t:
            return cls.ESTADO_BAJA
        if any(p in t for p in ("dañ", "malo", "defect", "falla")):
            return cls.ESTADO_DANADO
        if "regular" in t or "desgast" in t:
            return cls.ESTADO_REGULAR
        if any(p in t for p in ("bueno", "operativ", "excelente", "nuevo")):
            return cls.ESTADO_OPERATIVO
        return ""

    def save(self, *args, **kwargs):
        if self.estado_radio == self.ESTADO_BAJA and self.activo:
            self.activo = False
            self.fecha_baja = self.fecha_baja or timezone.localdate()
            campos = kwargs.get("update_fields")
            if campos is not None:
                kwargs["update_fields"] = {*campos, "activo", "fecha_baja"}
        super().save(*args, **kwargs)
        self.sincronizar_equipo()

    def datos_equipo(self):
        return {
            "tipo": Equipo.Tipo.RADIO,
            "serial": self.serial,
            "marca": self.marca,
            "modelo": self.modelo,
            "fecha_compra": self.fecha_compra,
            "estado_operativo": {
                self.ESTADO_OPERATIVO: Equipo.EstadoOperativo.OPERATIVO,
                self.ESTADO_REGULAR: Equipo.EstadoOperativo.OPERATIVO,
                self.ESTADO_DANADO: Equipo.EstadoOperativo.NO_OPERATIVO,
                self.ESTADO_BAJA: Equipo.EstadoOperativo.NO_OPERATIVO,
            }.get(self.estado_radio, ""),
            "activo": self.activo,
            "fecha_baja": self.fecha_baja,
            "motivo_baja": self.motivo_baja,
            "observaciones": self.observaciones,
            "requiere_revision": self.requiere_revision,
            "motivo_revision": self.motivo_revision[:255],
            "ubicacion": " - ".join(
                p for p in (self.cliente_asignado, self.puesto_asignado) if p
            )[:200],
        }

    @property
    def etiqueta(self):
        """Texto para identificar el radio: su placa (RJ) o, si no tiene, su serial."""
        return self.placa or f"sin placa (serial {self.serial or 'sin dato'})"

    def placa_equipo(self):
        """Placa del radio; provisional si no tiene o si la usa otro equipo."""
        provisional = f"SIN-RJ-{self.pk}"
        if not self.placa:
            return provisional
        ocupada = Equipo.objects.filter(placa=self.placa).exclude(
            pk=self.equipo_id
        ).exists()
        return provisional if ocupada else self.placa

    def sincronizar_equipo(self):
        datos = {"placa": self.placa_equipo(), **self.datos_equipo()}
        if self.equipo_id:
            Equipo.objects.filter(pk=self.equipo_id).update(
                actualizado_en=timezone.now(), **datos
            )
        else:
            self.equipo = Equipo.objects.create(**datos)
            Radio.objects.filter(pk=self.pk).update(equipo=self.equipo)


class MantenimientoEquipo(models.Model):
    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    class Tipo(models.TextChoices):
        PREVENTIVO = "PREVENTIVO", "Mantenimiento preventivo"
        CORRECTIVO = "CORRECTIVO", "Mantenimiento correctivo"
        INSPECCION = "INSPECCION", "Inspección"
        DIAGNOSTICO = "DIAGNOSTICO", "Diagnóstico"
        REPARACION = "REPARACION", "Reparación"
        CORRECCION = "CORRECCION", "Corrección"
        OTRO = "OTRO", "Otra operación"

    # Los que se ofrecen al registrar o programar; los demás quedan solo
    # para registros viejos e importaciones.
    TIPOS_FORMULARIO = ["PREVENTIVO", "CORRECTIVO", "DIAGNOSTICO", "CORRECCION"]

    class Resultado(models.TextChoices):
        SOLUCIONADO = "SOLUCIONADO", "Solucionado"
        PARCIAL = "PARCIAL", "Solución parcial"
        PENDIENTE = "PENDIENTE", "Pendiente"

    class EstadoFinal(models.TextChoices):
        OPERATIVO = "OPERATIVO", "Operativo"
        NO_OPERATIVO = "NO_OPERATIVO", "No operativo"
        PENDIENTE_PRUEBAS = (
            "PENDIENTE_PRUEBAS",
            "Pendiente de pruebas",
        )

    class EstadoEntrega(models.TextChoices):
        OPERATIVO = "OPERATIVO", "Equipo queda operativo"
        SEGUNDO_NIVEL = "SEGUNDO_NIVEL", "Requiere mantenimiento de segundo nivel"
        TERCER_NIVEL = "TERCER_NIVEL", "Requiere mantenimiento de tercer nivel"
        BAJA = "BAJA", "No se repara (baja)"

    ACTIVIDADES_PREVENTIVAS = [
        ("componentes_internos", "Verificación de componentes internos"),
        ("pantalla_monitor", "Verificación de pantalla o monitor"),
        ("mouse_teclado", "Verificación de mouse y teclado"),
        ("fuente_adaptador", "Verificación de fuente o adaptador de energía"),
        ("perifericos_externos", "Verificación de periféricos externos"),
        ("prueba_funcionamiento", "Verificación de funcionamiento posterior al mantenimiento"),
        ("otros", "Otros"),
    ]

    equipo = models.ForeignKey(
        Equipo,
        on_delete=models.PROTECT,
        related_name="mantenimientos",
        verbose_name="Equipo",
    )

    fecha_intervencion = models.DateTimeField(
        verbose_name="Fecha y hora de la intervención",
        db_index=True,
    )

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        db_index=True,
    )

    tecnico_responsable = models.CharField(max_length=150)
    funcionario_responsable = models.ForeignKey(
        "Funcionario", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mantenimientos_equipo",
        help_text="Funcionario responsable al momento de la intervención.",
    )
    motivo = models.TextField()
    diagnostico = models.TextField(blank=True)
    causa_dano = models.TextField(blank=True)
    trabajo_realizado = models.TextField()
    actividades_preventivas = models.JSONField(default=list, blank=True)
    actividad_preventiva_otros = models.TextField(blank=True)
    # Partes intervenidas en un correctivo (claves de actividades_mantenimiento).
    componentes_intervenidos = models.JSONField(default=list, blank=True)
    estados_entrega = models.JSONField(default=list, blank=True)
    repuestos_utilizados = models.TextField(blank=True)

    resultado = models.CharField(
        max_length=15,
        choices=Resultado.choices,
        default=Resultado.SOLUCIONADO,
    )

    estado_final = models.CharField(
        max_length=20,
        choices=EstadoFinal.choices,
        blank=True,
    )

    observaciones = models.TextField(blank=True)

    # Solicitud (ticket) que originó la intervención, si la hay.
    ticket = models.ForeignKey(
        "Ticket",
        on_delete=models.SET_NULL,
        related_name="intervenciones",
        null=True,
        blank=True,
    )

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mantenimientos_registrados",
    )

    registrado_en = models.DateTimeField(auto_now_add=True)

    # Trazabilidad de importaciones históricas.
    # Los registros manuales pueden dejar estos campos vacíos.
    origen_archivo = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    origen_hoja = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    fila_origen = models.PositiveIntegerField(
        null=True,
        blank=True,
    )


    class Meta:
        verbose_name = "Intervención de mantenimiento"
        verbose_name_plural = "Historial de intervenciones"
        ordering = ["-fecha_intervencion", "-id"]
        indexes = [
            models.Index(
                fields=["equipo", "-fecha_intervencion"],
                name="mant_equipo_fecha_idx",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["origen_archivo", "origen_hoja", "fila_origen"],
                name="uniq_mant_origen_fila",
            ),
        ]


    def __str__(self):
        return (
            f"{self.equipo.placa} - "
            f"{self.get_tipo_display()} - "
            f"{self.fecha_intervencion:%d/%m/%Y}"
        )


class MantenimientoProgramado(models.Model):

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    class Estado(models.TextChoices):
        PROGRAMADO = "PROGRAMADO", "Programado"
        COMPLETADO = "COMPLETADO", "Completado"
        CANCELADO = "CANCELADO", "Cancelado"

    equipo = models.ForeignKey(
        Equipo,
        on_delete=models.PROTECT,
        related_name="mantenimientos_programados",
        verbose_name="Equipo",
    )

    fecha_programada = models.DateField(db_index=True)

    tipo = models.CharField(
        max_length=20,
        choices=MantenimientoEquipo.Tipo.choices,
        default=MantenimientoEquipo.Tipo.PREVENTIVO,
    )

    descripcion = models.TextField()

    # Lo que se va a revisar, según el tipo de equipo y de mantenimiento
    # (claves de actividades_mantenimiento).
    actividades = models.JSONField(default=list, blank=True)

    estado = models.CharField(
        max_length=15,
        choices=Estado.choices,
        default=Estado.PROGRAMADO,
        db_index=True,
    )

    intervencion_realizada = models.ForeignKey(
        MantenimientoEquipo,
        on_delete=models.PROTECT,
        related_name="programaciones_cumplidas",
        null=True,
        blank=True,
    )

    observaciones = models.TextField(blank=True)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mantenimientos_programados_creados",
    )

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mantenimiento programado"
        verbose_name_plural = "Mantenimientos programados"
        ordering = ["fecha_programada", "id"]
        indexes = [
            models.Index(
                fields=["estado", "fecha_programada"],
                name="mant_prog_estado_fecha_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.equipo.placa} - "
            f"{self.fecha_programada:%d/%m/%Y}"
        )


class AlertaMantenimiento(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ENVIADA = "ENVIADA", "Enviada"
        ERROR = "ERROR", "Error"

    equipo = models.ForeignKey(
        Equipo,
        on_delete=models.PROTECT,
        related_name="alertas_mantenimiento",
        verbose_name="Equipo",
    )

    fecha_vencimiento = models.DateField(db_index=True)

    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True,
    )

    intentos = models.PositiveIntegerField(default=0)

    ultimo_intento = models.DateTimeField(
        null=True,
        blank=True,
    )

    enviada_en = models.DateTimeField(
        null=True,
        blank=True,
    )

    detalle_error = models.TextField(blank=True)

    creada_en = models.DateTimeField(auto_now_add=True)

    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alerta de mantenimiento"
        verbose_name_plural = "Alertas de mantenimiento"
        ordering = ["fecha_vencimiento", "equipo__placa"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "fecha_vencimiento"],
                name="uniq_alerta_equipo_vencimiento",
            ),
        ]
        indexes = [
            models.Index(
                fields=["estado", "fecha_vencimiento"],
                name="alerta_estado_venc_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.equipo.placa} - "
            f"Vence {self.fecha_vencimiento:%d/%m/%Y} - "
            f"{self.get_estado_display()}"
        )


class AsignacionRadio(models.Model):

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    class Estado(models.TextChoices):
        ASIGNADO = "ASIGNADO", "Asignado"
        DEVUELTO = "DEVUELTO", "Devuelto"

    radio = models.ForeignKey(
        Radio,
        on_delete=models.PROTECT,
        related_name="asignaciones",
        verbose_name="Radio",
    )

    fecha_entrega = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha y hora de entrega",
    )

    # Supervisor del puesto que recibe y firma (antes: coordinador de zona).
    coordinador_zona = models.CharField(max_length=200)
    cedula_funcionario = models.CharField(max_length=50, blank=True)
    cliente_asignado = models.CharField(max_length=200)
    puesto_asignado = models.CharField(max_length=200)

    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.ASIGNADO,
        db_index=True,
    )

    entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="asignaciones_entregadas",
    )

    observaciones_entrega = models.TextField(blank=True)

    # Puesto del catálogo; cliente_asignado y puesto_asignado guardan el
    # texto (también para entregas anteriores al catálogo).
    puesto = models.ForeignKey(
        "Puesto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="asignaciones_radio",
    )

    # Estado del equipo al momento de la entrega (como en el formulario de
    # Google: Bueno, Regular, Dañado o No tiene).
    estado_radio_entrega = models.CharField(max_length=100, blank=True)
    estado_base_entrega = models.CharField(max_length=100, blank=True)
    estado_cargador_entrega = models.CharField(max_length=100, blank=True)
    estado_antena_entrega = models.CharField(max_length=100, blank=True)
    estado_baterias_entrega = models.CharField(max_length=100, blank=True)

    clausula_aceptada = models.BooleanField(default=False)
    # Firma dibujada en la plataforma (imagen PNG en formato data URL) o
    # enlace a la firma adjunta en el formulario de Google.
    firma = models.TextField(blank=True)
    enlace_firma = models.URLField(max_length=500, blank=True)

    fecha_devolucion = models.DateTimeField(
        null=True,
        blank=True,
    )

    recibido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="asignaciones_recibidas",
        null=True,
        blank=True,
    )

    observaciones_devolucion = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Asignación de radio"
        verbose_name_plural = "Asignaciones de radios"
        ordering = ["-fecha_entrega", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["radio"],
                condition=models.Q(estado="ASIGNADO"),
                name="una_asignacion_activa_por_radio",
            ),
        ]

    def __str__(self):
        return (
            f"{self.radio.placa or 'Sin placa'} - "
            f"{self.cedula_funcionario} - {self.estado}"
        )

    # Las entregas importadas del formulario de Google guardan este marcador
    # al inicio de las observaciones; en el acta se muestra como origen.
    PREFIJO_FORMULARIO = "[Formulario Google]"

    @property
    def viene_del_formulario(self):
        texto = (self.observaciones_entrega or "").lstrip()
        return texto.startswith(self.PREFIJO_FORMULARIO)

    @property
    def observaciones_entrega_limpias(self):
        """Observaciones sin el marcador técnico de la importación."""
        texto = (self.observaciones_entrega or "").strip()
        if texto.startswith(self.PREFIJO_FORMULARIO):
            texto = texto[len(self.PREFIJO_FORMULARIO):].strip()
        return texto

    @property
    def estados_entrega(self):
        """Estado de cada pieza al entregar, con su color para el acta."""
        filas = (
            ("Radio", self.estado_radio_entrega),
            ("Base", self.estado_base_entrega),
            ("Cargador", self.estado_cargador_entrega),
            ("Antena", self.estado_antena_entrega),
            ("Baterías", self.estado_baterias_entrega),
        )
        return [
            {"nombre": n, "valor": v or "", "tono": tono_estado(v)}
            for n, v in filas
        ]


class TransferenciaComponentesRadio(models.Model):
    """Trazabilidad del movimiento de accesorios entre dos radios."""

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    radio_origen = models.ForeignKey(
        Radio,
        on_delete=models.PROTECT,
        related_name="transferencias_componentes_origen",
    )
    radio_destino = models.ForeignKey(
        Radio,
        on_delete=models.PROTECT,
        related_name="transferencias_componentes_destino",
    )
    etiqueta_origen = models.CharField(max_length=150)
    etiqueta_destino = models.CharField(max_length=150)
    componentes = models.JSONField(default=list)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="transferencias_componentes_radio",
    )
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Transferencia de componentes de radio"
        verbose_name_plural = "Transferencias de componentes de radios"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return (
            f"{self.etiqueta_origen} → "
            f"{self.etiqueta_destino} ({self.fecha:%d/%m/%Y})"
        )


class DetalleComputador(models.Model):
    """Computadores y tabletas."""

    equipo = models.OneToOneField(
        Equipo, on_delete=models.CASCADE, related_name="computador"
    )
    clase = models.CharField(
        max_length=100, blank=True,
        help_text="Portátil, escritorio, todo en uno, servidor, Android…",
    )
    procesador = models.CharField(max_length=150, blank=True)
    velocidad_procesador = models.CharField(max_length=50, blank=True)
    tipo_disco = models.CharField(max_length=50, blank=True)
    capacidad_disco = models.CharField(max_length=100, blank=True)
    tipo_ram = models.CharField(max_length=50, blank=True)
    capacidad_ram = models.CharField(max_length=50, blank=True)

    mouse = models.CharField(max_length=100, blank=True)
    teclado = models.CharField(max_length=100, blank=True)
    regulador = models.CharField(max_length=100, blank=True)
    parlantes = models.CharField(max_length=100, blank=True)
    webcam = models.CharField(max_length=100, blank=True)
    monitor_serial = models.CharField(max_length=100, blank=True)
    monitor_modelo = models.CharField(max_length=150, blank=True)
    monitor2_serial = models.CharField(max_length=100, blank=True)
    monitor2_modelo = models.CharField(max_length=150, blank=True)
    ups_serial = models.CharField(max_length=100, blank=True)
    ups_modelo = models.CharField(max_length=150, blank=True)
    telefono_ip_serial = models.CharField(max_length=100, blank=True)
    telefono_ip_modelo = models.CharField(max_length=150, blank=True)

    # Las claves de licencia solo las ven el técnico y el superusuario
    # (permiso "licencias").
    sistema_operativo = models.CharField(max_length=150, blank=True)
    licencia_so = models.CharField(max_length=200, blank=True)
    antivirus = models.CharField(max_length=150, blank=True)
    licencia_antivirus = models.CharField(max_length=200, blank=True)
    vencimiento_antivirus = models.DateField(null=True, blank=True)
    office = models.CharField(max_length=150, blank=True)
    licencia_office = models.CharField(max_length=200, blank=True)
    software_licenciado = models.TextField(blank=True)
    software_libre = models.TextField(blank=True)

    mac_ethernet = models.CharField(max_length=50, blank=True)
    mac_wifi = models.CharField(max_length=50, blank=True)
    ip_ethernet = models.CharField(max_length=50, blank=True)
    ip_wifi = models.CharField(max_length=50, blank=True)
    imei = models.CharField(max_length=50, blank=True)
    linea_celular = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "Detalle de computador"
        verbose_name_plural = "Detalles de computadores"


class DetalleImpresora(models.Model):
    """Impresoras y escáneres."""

    equipo = models.OneToOneField(
        Equipo, on_delete=models.CASCADE, related_name="impresora"
    )
    clase = models.CharField(
        max_length=100, blank=True,
        help_text="Láser, tinta, multifuncional…",
    )

    class Meta:
        verbose_name = "Detalle de impresora"
        verbose_name_plural = "Detalles de impresoras"


class DetalleGPS(models.Model):
    equipo = models.OneToOneField(
        Equipo, on_delete=models.CASCADE, related_name="gps"
    )
    imei = models.CharField(max_length=50, blank=True, db_index=True)
    linea = models.CharField(max_length=50, blank=True)
    operador = models.CharField(max_length=100, blank=True)
    placa_vehiculo = models.CharField(max_length=20, blank=True)
    nombre_vehiculo = models.CharField(max_length=150, blank=True)
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    plataforma = models.CharField(
        max_length=100, blank=True,
        help_text="Estado en la plataforma de rastreo (reporta, no reporta…).",
    )

    class Meta:
        verbose_name = "Detalle de GPS"
        verbose_name_plural = "Detalles de GPS"


class DetalleAlarma(models.Model):
    equipo = models.OneToOneField(
        Equipo, on_delete=models.CASCADE, related_name="alarma"
    )
    clase = models.CharField(max_length=100, blank=True)
    reporta_central = models.CharField(max_length=50, blank=True)
    # Lista de {"nombre": "Teclados", "cantidad": 1, "estado": "Bueno"}.
    componentes = models.JSONField(default=list, blank=True)
    serial_comunicador = models.CharField(max_length=100, blank=True)
    estado_comunicador = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "Detalle de alarma"
        verbose_name_plural = "Detalles de alarmas"


class Funcionario(models.Model):
    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    """Personal administrativo que recibe computadores, impresoras…"""

    cedula = models.CharField(max_length=20, unique=True)
    nombre_completo = models.CharField(max_length=200)
    cargo = models.CharField(max_length=150, blank=True)
    correo = models.EmailField(blank=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Funcionario"
        verbose_name_plural = "Funcionarios"
        ordering = ["nombre_completo"]

    def __str__(self):
        return f"{self.nombre_completo} ({self.cedula})"


class CambioGPS(models.Model):
    """Historial de cambios de línea, operador o vehículo de un GPS."""

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    equipo = models.ForeignKey(
        Equipo, on_delete=models.PROTECT, related_name="cambios_gps"
    )
    fecha = models.DateTimeField(default=timezone.now)
    responsable = models.CharField(max_length=200, blank=True)
    dato_actualizado = models.CharField(max_length=150, blank=True)
    linea = models.CharField(max_length=50, blank=True)
    operador = models.CharField(max_length=100, blank=True)
    placa_vehiculo = models.CharField(max_length=20, blank=True)
    nombre_vehiculo = models.CharField(max_length=150, blank=True)
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="cambios_gps",
    )

    class Meta:
        verbose_name = "Cambio de GPS"
        verbose_name_plural = "Cambios de GPS"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "fecha"], name="uniq_cambio_gps_fecha"
            ),
        ]


class AvisoAntivirus(models.Model):
    """Aviso ya enviado del vencimiento del antivirus de un equipo."""

    equipo = models.ForeignKey(
        Equipo, on_delete=models.CASCADE, related_name="avisos_antivirus"
    )
    fecha_vencimiento = models.DateField()
    enviado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Aviso de antivirus"
        verbose_name_plural = "Avisos de antivirus"
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "fecha_vencimiento"],
                name="uniq_aviso_antivirus",
            ),
        ]


class AsignacionEquipo(models.Model):
    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    """Entrega de un equipo (computador, impresora, tableta…) a un
    funcionario. Las entregas de radios a puestos van en AsignacionRadio."""

    class Estado(models.TextChoices):
        ASIGNADO = "ASIGNADO", "Asignado"
        DEVUELTO = "DEVUELTO", "Devuelto"

    equipo = models.ForeignKey(
        Equipo, on_delete=models.PROTECT, related_name="asignaciones"
    )
    funcionario = models.ForeignKey(
        Funcionario, on_delete=models.PROTECT, related_name="asignaciones",
        null=True, blank=True,
    )
    # Copia de quién recibió, para entregas importadas sin funcionario
    # registrado y para que el historial no cambie si se edita el
    # funcionario.
    nombre_recibe = models.CharField(max_length=200, blank=True)
    cedula_recibe = models.CharField(max_length=50, blank=True)
    area = models.CharField(max_length=200, blank=True)

    fecha_entrega = models.DateTimeField(default=timezone.now)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.ASIGNADO,
        db_index=True,
    )
    entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="equipos_entregados",
    )
    accesorios = models.TextField(blank=True)
    observaciones_entrega = models.TextField(blank=True)
    clausula_aceptada = models.BooleanField(default=False)
    firma = models.TextField(blank=True)
    enlace_firma = models.URLField(max_length=500, blank=True)

    fecha_devolucion = models.DateTimeField(null=True, blank=True)
    recibido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="equipos_recibidos", null=True, blank=True,
    )
    observaciones_devolucion = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Entrega de equipo"
        verbose_name_plural = "Entregas de equipos"
        ordering = ["-fecha_entrega", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipo"],
                condition=models.Q(estado="ASIGNADO"),
                name="una_entrega_activa_por_equipo",
            ),
        ]

    def __str__(self):
        return f"{self.equipo.placa} - {self.nombre_recibe} - {self.estado}"


class VerificacionPolitica(models.Model):
    """Verificación de la política de seguridad informática en un computador
    (puntos en inventario/politica.py)."""

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    equipo = models.ForeignKey(
        Equipo, on_delete=models.PROTECT, related_name="verificaciones_politica"
    )
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    especialista = models.CharField(max_length=200, blank=True)
    responsable = models.CharField(
        max_length=200, blank=True,
        help_text="Funcionario responsable del equipo al momento de verificar.",
    )
    # {"usuario_dominio": "CUMPLE", "usb_desactivado": "NO CUMPLE", …}
    respuestas = models.JSONField(default=dict)
    observaciones = models.TextField(blank=True)
    actualizacion = models.TextField(
        blank=True, help_text="Actualizaciones realizadas (antivirus, Office, Windows…).",
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="verificaciones_politica",
    )
    importada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Verificación de política de seguridad"
        verbose_name_plural = "Verificaciones de política de seguridad"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "fecha"], name="uniq_verificacion_equipo_fecha"
            ),
        ]

    def __str__(self):
        return f"{self.equipo.placa} - {self.fecha:%d/%m/%Y}"

    @property
    def incumplimientos(self):
        from .politica import incumplimientos

        return incumplimientos(self.respuestas)


class Cliente(models.Model):
    """Cliente de Seguridad Jano (hoja CLIENTES_PUESTOS)."""

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    id_externo = models.CharField(max_length=20, unique=True, null=True, blank=True)
    nit = models.CharField(max_length=30, blank=True)
    nombre = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Puesto(models.Model):
    """Puesto de servicio de un cliente (sede y nombre del puesto)."""

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    id_externo = models.CharField(max_length=20, unique=True, null=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="puestos")
    sede = models.CharField(max_length=200, blank=True)
    nombre = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = "Puesto"
        verbose_name_plural = "Puestos"
        ordering = ["cliente__nombre", "sede", "nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.sede})" if self.sede else self.nombre


class RenovacionAntivirus(models.Model):

    # Identificador público estable para integración entre plataformas.
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    equipo = models.ForeignKey(
        Equipo, on_delete=models.CASCADE, related_name="renovaciones_antivirus"
    )
    fecha = models.DateTimeField(default=timezone.now)
    antivirus = models.CharField(max_length=150)
    licencia = models.CharField(max_length=200, blank=True)
    vencimiento = models.DateField(null=True, blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="renovaciones_antivirus",
    )
    importada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Renovación de antivirus"
        verbose_name_plural = "Renovaciones de antivirus"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "fecha"], name="uniq_renovacion_equipo_fecha"
            ),
        ]




class RetiroFuncionario(models.Model):
    """Retiro de un funcionario (renuncia, despido…) y su paz y salvo.

    Talento Humano lo inicia; TIC valida cada equipo que la persona tiene a
    cargo. El paz y salvo se emite cuando todos quedan devueltos en buen
    estado o reasignados a otra persona.
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Motivo(models.TextChoices):
        RENUNCIA = "RENUNCIA", "Renuncia"
        DESPIDO = "DESPIDO", "Despido"
        FIN_CONTRATO = "FIN_CONTRATO", "Terminación de contrato"
        TRASLADO = "TRASLADO", "Traslado"
        OTRO = "OTRO", "Otro"

    class Estado(models.TextChoices):
        EN_PROCESO = "EN_PROCESO", "En proceso"
        PAZ_Y_SALVO = "PAZ_Y_SALVO", "Paz y salvo emitido"
        CANCELADO = "CANCELADO", "Cancelado"

    funcionario = models.ForeignKey(
        Funcionario, on_delete=models.PROTECT, related_name="retiros"
    )
    motivo = models.CharField(max_length=20, choices=Motivo.choices)
    fecha_retiro = models.DateField(verbose_name="Fecha de retiro")
    observaciones = models.TextField(blank=True)
    estado = models.CharField(
        max_length=12, choices=Estado.choices, default=Estado.EN_PROCESO,
        db_index=True,
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="retiros_iniciados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="retiros_cerrados", null=True, blank=True,
    )
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Retiro de funcionario"
        verbose_name_plural = "Retiros de funcionarios"
        ordering = ["-creado_en", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["funcionario"],
                condition=models.Q(estado="EN_PROCESO"),
                name="un_retiro_en_proceso_por_funcionario",
            ),
        ]

    def __str__(self):
        return f"Retiro de {self.funcionario.nombre_completo} ({self.get_estado_display()})"


class ItemRetiro(models.Model):
    """Un equipo que la persona tenía a cargo al iniciar su retiro."""

    class Resultado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de validar"
        DEVUELTO = "DEVUELTO", "Devuelto en buen estado"
        DEVUELTO_DANO = "DEVUELTO_DANO", "Devuelto con daño"
        REASIGNADO = "REASIGNADO", "Reasignado a otra persona"
        FALTANTE = "FALTANTE", "No fue entregado (faltante)"

    # Resultados que impiden emitir el paz y salvo.
    BLOQUEAN = {Resultado.PENDIENTE, Resultado.DEVUELTO_DANO, Resultado.FALTANTE}

    retiro = models.ForeignKey(
        RetiroFuncionario, on_delete=models.CASCADE, related_name="items"
    )
    equipo = models.ForeignKey(
        Equipo, on_delete=models.PROTECT, related_name="items_retiro"
    )
    asignacion_equipo = models.ForeignKey(
        AsignacionEquipo, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    asignacion_radio = models.ForeignKey(
        AsignacionRadio, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    resultado = models.CharField(
        max_length=15, choices=Resultado.choices, default=Resultado.PENDIENTE,
    )
    reasignado_a = models.ForeignKey(
        Funcionario, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+",
    )
    observaciones = models.TextField(blank=True)
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        blank=True, related_name="+",
    )
    validado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Equipo del retiro"
        verbose_name_plural = "Equipos del retiro"
        ordering = ["equipo__tipo", "equipo__placa"]
        constraints = [
            models.UniqueConstraint(
                fields=["retiro", "equipo"], name="un_item_por_equipo_en_retiro"
            ),
        ]

    @property
    def bloquea(self):
        return self.resultado in self.BLOQUEAN

    @property
    def puesto_radio(self):
        """Cliente · puesto donde está el radio según su entrega (si la hay)."""
        a = self.asignacion_radio
        if not a:
            return ""
        return " · ".join(x for x in (a.cliente_asignado, a.puesto_asignado) if x)

    @property
    def queda_a_cargo(self):
        """A nombre de quién queda el equipo después de validarlo."""
        R = self.Resultado
        persona = self.retiro.funcionario.nombre_completo
        if self.resultado == R.REASIGNADO and self.reasignado_a:
            nuevo = f"{self.reasignado_a.nombre_completo} (C.C. {self.reasignado_a.cedula})"
            if self.asignacion_radio_id and self.puesto_radio:
                return f"Sigue en {self.puesto_radio}, ahora a cargo de {nuevo}"
            return f"Queda a nombre de {nuevo}"
        if self.resultado == R.DEVUELTO:
            return "Vuelve a bodega TIC, sin responsable"
        if self.resultado == R.DEVUELTO_DANO:
            return "Vuelve a bodega TIC, sin responsable y marcado por revisar"
        if self.resultado == R.FALTANTE:
            return f"Sigue a nombre de {persona} hasta que se resuelva el faltante"
        return f"Por ahora sigue a nombre de {persona}"


class RegistroAuditoria(models.Model):
    """Bitácora de lo que se hace en la plataforma (ver inventario/auditoria.py)."""

    class Accion(models.TextChoices):
        CREAR = "CREAR", "Creó"
        EDITAR = "EDITAR", "Modificó"
        ELIMINAR = "ELIMINAR", "Eliminó"
        INGRESO = "INGRESO", "Ingresó"
        SALIDA = "SALIDA", "Cerró sesión"
        INGRESO_FALLIDO = "INGRESO_FALLIDO", "Ingreso fallido"

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registros_auditoria",
    )
    # Se guarda el nombre por si el usuario se elimina después.
    usuario_nombre = models.CharField(max_length=150)
    accion = models.CharField(max_length=20, choices=Accion.choices, db_index=True)
    modelo = models.CharField("Tipo de registro", max_length=100)
    modelo_clave = models.CharField(max_length=100, db_index=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    objeto_texto = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=100, blank=True, db_index=True)
    cambios = models.JSONField(default=list, blank=True)
    descripcion = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ruta = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Auditoría"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} {self.usuario_nombre} {self.get_accion_display()} {self.modelo}"


class Ticket(models.Model):
    """Caso de mantenimiento o soporte: lo pide un funcionario (formulario
    público), lo crea el área de TI o sale de un mantenimiento preventivo.
    Flujo: abierto → asignado → en atención → resuelto → cerrado."""

    class Origen(models.TextChoices):
        FORMULARIO = "FORMULARIO", "Formulario público"
        INTERNO = "INTERNO", "Registrado por TI"
        PREVENTIVO = "PREVENTIVO", "Mantenimiento preventivo"
        IMPORTADO = "IMPORTADO", "Importado del Sheet"

    class Tipo(models.TextChoices):
        CORRECTIVO = "CORRECTIVO", "Correctivo (daño o falla)"
        PREVENTIVO = "PREVENTIVO", "Mantenimiento preventivo"
        SOPORTE = "SOPORTE", "Soporte (correo, programas, red)"

    class Categoria(models.TextChoices):
        SOFTWARE = "SOFTWARE", "Correo, Novasoft, SEIF, servidor o internet"
        EQUIPO_OFICINA = "EQUIPO_OFICINA", "Daño en equipo de oficina"
        OPERACION = "OPERACION", (
            "Daño en elementos de operación (radios, repetidora, cámaras)"
        )
        MANTENIMIENTO = "MANTENIMIENTO", "Mantenimiento preventivo"
        OTRA = "OTRA", "Otra"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        ASIGNADO = "ASIGNADO", "Asignado"
        EN_ATENCION = "EN_ATENCION", "En atención"
        RESUELTO = "RESUELTO", "Resuelto"
        CERRADO = "CERRADO", "Cerrado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Franja(models.TextChoices):
        MANANA = "MANANA", "8:00 a 12:00"
        TARDE = "TARDE", "2:00 a 5:00"

    ACTIVOS = [Estado.ABIERTO, Estado.ASIGNADO, Estado.EN_ATENCION, Estado.RESUELTO]

    numero = models.CharField(max_length=20, unique=True, editable=False)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    origen = models.CharField(max_length=15, choices=Origen.choices)
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    categoria = models.CharField(
        max_length=20, choices=Categoria.choices, default=Categoria.OTRA
    )
    prioridad = models.CharField(
        max_length=10, choices=Prioridad.choices, default=Prioridad.MEDIA
    )
    estado = models.CharField(
        max_length=15, choices=Estado.choices, default=Estado.ABIERTO,
        db_index=True,
    )
    equipo = models.ForeignKey(
        "Equipo", on_delete=models.PROTECT, related_name="tickets",
        null=True, blank=True,
    )
    descripcion = models.TextField()

    # Quién pide el servicio.
    funcionario = models.ForeignKey(
        "Funcionario", on_delete=models.SET_NULL, related_name="tickets",
        null=True, blank=True,
    )
    solicitante_nombre = models.CharField(max_length=200, blank=True)
    solicitante_cedula = models.CharField(max_length=50, blank=True)
    solicitante_correo = models.EmailField(blank=True)
    solicitante_telefono = models.CharField(max_length=50, blank=True)
    ubicacion = models.CharField("Sede o lugar", max_length=200, blank=True)

    # Asignación.
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="tickets_asignados", null=True, blank=True,
    )
    fecha_programada = models.DateField(null=True, blank=True, db_index=True)
    franja = models.CharField(max_length=10, choices=Franja.choices, blank=True)

    # Resultado.
    solucion = models.TextField(blank=True)
    firma = models.TextField(blank=True)
    firma_nombre = models.CharField(max_length=200, blank=True)
    cierre_automatico = models.BooleanField(default=False)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="tickets_creados", null=True, blank=True,
    )
    creado_en = models.DateTimeField(default=timezone.now, db_index=True)
    asignado_en = models.DateTimeField(null=True, blank=True)
    atencion_en = models.DateTimeField(null=True, blank=True)
    resuelto_en = models.DateTimeField(null=True, blank=True)
    cerrado_en = models.DateTimeField(null=True, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-creado_en", "-id"]

    def __str__(self):
        return f"{self.numero} - {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = self.siguiente_numero(self.creado_en)
        super().save(*args, **kwargs)

    @staticmethod
    def siguiente_numero(fecha):
        anio = timezone.localtime(fecha).year if timezone.is_aware(fecha) else fecha.year
        prefijo = f"TK-{anio}-"
        ultimo = (
            Ticket.objects.filter(numero__startswith=prefijo)
            .order_by("-numero").values_list("numero", flat=True).first()
        )
        siguiente = int(ultimo.rsplit("-", 1)[1]) + 1 if ultimo else 1
        return f"{prefijo}{siguiente:04d}"

    @property
    def activo(self):
        return self.estado in self.ACTIVOS

    @property
    def tiempo_respuesta(self):
        """Tiempo desde la creación hasta la resolución."""
        if self.resuelto_en:
            return self.resuelto_en - self.creado_en
        return None


class EventoTicket(models.Model):
    """Bitácora del ticket."""

    class Tipo(models.TextChoices):
        CREADO = "CREADO", "Creado"
        ASIGNADO = "ASIGNADO", "Asignado"
        ATENCION = "ATENCION", "En atención"
        RESUELTO = "RESUELTO", "Resuelto"
        CONFIRMADO = "CONFIRMADO", "Confirmado por el solicitante"
        REABIERTO = "REABIERTO", "Reabierto"
        CERRADO = "CERRADO", "Cerrado"
        CANCELADO = "CANCELADO", "Cancelado"
        COMENTARIO = "COMENTARIO", "Comentario"
        CORREO = "CORREO", "Correo"

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="eventos"
    )
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="eventos_ticket",
    )
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    texto = models.TextField(blank=True)
    # Los comentarios internos no se muestran en la página pública del caso.
    publico = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Evento de ticket"
        verbose_name_plural = "Eventos de tickets"
        ordering = ["fecha", "id"]

    def __str__(self):
        return f"{self.ticket.numero} · {self.get_tipo_display()}"


class FotoTicket(models.Model):
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="fotos"
    )
    archivo = models.FileField(upload_to="tickets/%Y/%m/")
    descripcion = models.CharField(max_length=200, blank=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="fotos_ticket",
    )
    subido_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Foto de ticket"
        verbose_name_plural = "Fotos de tickets"
        ordering = ["subido_en", "id"]
