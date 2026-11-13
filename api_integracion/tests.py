from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token

from inventario.models import (
    DetalleComputador,
    Equipo,
    Funcionario,
    MantenimientoEquipo,
    MantenimientoProgramado,
    Radio,
    RetiroFuncionario,
    VerificacionPolitica,
)

from .indicadores import periodo_desde_parametros, resumen_indicadores

HOY = date(2026, 11, 13)


def _momento(d):
    return datetime(d.year, d.month, d.day, 15, 0, tzinfo=dt_timezone.utc)


class IndicadoresJanoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()
        cls.usuario = Usuario.objects.create_user(
            **{Usuario.USERNAME_FIELD: "gestion_tic_api"}, password="PruebaTemporal123!"
        )
        cls.pc_al_dia = Equipo.objects.create(placa="PC-A", tipo=Equipo.Tipo.COMPUTADOR)
        cls.pc_vencido = Equipo.objects.create(placa="PC-B", tipo=Equipo.Tipo.COMPUTADOR)
        cls.pc_sin = Equipo.objects.create(placa="PC-C", tipo=Equipo.Tipo.COMPUTADOR)
        Equipo.objects.create(placa="PC-Z", tipo=Equipo.Tipo.COMPUTADOR, activo=False)
        cls.radio = Radio.objects.create(placa="RAD-1").equipo

        def mant(equipo, d, tipo=MantenimientoEquipo.Tipo.PREVENTIVO):
            MantenimientoEquipo.objects.create(
                registrado_por=cls.usuario, equipo=equipo, fecha_intervencion=_momento(d),
                tipo=tipo, tecnico_responsable="Técnico", motivo="Prueba",
                trabajo_realizado="Prueba", origen_archivo="PRUEBA",
            )

        mant(cls.pc_al_dia, date(2026, 10, 1))
        mant(cls.pc_vencido, date(2026, 1, 10))
        mant(cls.radio, date(2026, 9, 1))
        # Posterior al cierre del trimestre pasado: allí no debe contar.
        mant(cls.pc_vencido, date(2026, 11, 5), MantenimientoEquipo.Tipo.CORRECTIVO)

        for d, estado in [
            (date(2026, 10, 5), MantenimientoProgramado.Estado.COMPLETADO),
            (date(2026, 10, 20), MantenimientoProgramado.Estado.PROGRAMADO),
            (date(2026, 11, 1), MantenimientoProgramado.Estado.CANCELADO),
            (date(2026, 7, 1), MantenimientoProgramado.Estado.COMPLETADO),
        ]:
            MantenimientoProgramado.objects.create(
                equipo=cls.pc_al_dia, fecha_programada=d, estado=estado, descripcion="Visita",
                creado_por=cls.usuario,
            )

        VerificacionPolitica.objects.create(
            equipo=cls.pc_al_dia, fecha=_momento(date(2026, 3, 1)), respuestas={}
        )
        VerificacionPolitica.objects.create(
            equipo=cls.pc_vencido, fecha=_momento(date(2026, 2, 1)),
            respuestas={"usb_desactivado": "NO CUMPLE"},
        )

        DetalleComputador.objects.create(equipo=cls.pc_al_dia, vencimiento_antivirus=date(2027, 1, 1))
        DetalleComputador.objects.create(equipo=cls.pc_vencido, vencimiento_antivirus=date(2026, 11, 1))

        f1 = Funcionario.objects.create(cedula="1", nombre_completo="Ana")
        f2 = Funcionario.objects.create(cedula="2", nombre_completo="Luis")
        f3 = Funcionario.objects.create(cedula="3", nombre_completo="Eva")
        RetiroFuncionario.objects.create(funcionario=f1, creado_por=cls.usuario, fecha_retiro=date(2026, 10, 2),
                                         estado=RetiroFuncionario.Estado.PAZ_Y_SALVO)
        RetiroFuncionario.objects.create(funcionario=f2, creado_por=cls.usuario, fecha_retiro=date(2026, 11, 2))
        RetiroFuncionario.objects.create(funcionario=f3, creado_por=cls.usuario, fecha_retiro=date(2026, 11, 3),
                                         estado=RetiroFuncionario.Estado.CANCELADO)

    def test_trimestre_en_curso(self):
        r = resumen_indicadores(date(2026, 10, 1), date(2026, 12, 31), hoy=HOY)
        m = r["metricas"]
        self.assertEqual(r["fecha_corte"], "2026-11-13")

        # PC-A y RAD-1 al día; PC-B atendido el 5/11; PC-C sin registro; PC-Z inactivo.
        self.assertEqual((m["mantenimiento_al_dia"]["valor"], m["mantenimiento_al_dia"]["meta"]), (3, 4))
        self.assertEqual(m["mantenimiento_al_dia"]["pendientes"][0]["placa"], "PC-C")
        self.assertEqual((m["mantenimiento_computadores"]["valor"], m["mantenimiento_computadores"]["meta"]), (2, 3))
        self.assertEqual((m["mantenimiento_radios"]["valor"], m["mantenimiento_radios"]["meta"]), (1, 1))

        self.assertEqual((m["ejecucion_programacion"]["valor"], m["ejecucion_programacion"]["meta"]), (1, 2))
        self.assertEqual(m["ejecucion_programacion"]["pendientes"][0]["estado"], "Atrasado")
        self.assertEqual(m["mantenimientos_realizados"]["valor"], 2)
        self.assertEqual(m["mantenimientos_realizados"]["preventivos"], 1)
        self.assertIsNone(m["mantenimientos_realizados"]["meta"])

        self.assertEqual((m["politica_al_dia"]["valor"], m["politica_al_dia"]["meta"]), (1, 3))
        self.assertEqual((m["antivirus_vigente"]["valor"], m["antivirus_vigente"]["meta"]), (1, 2))
        self.assertEqual((m["paz_y_salvo"]["valor"], m["paz_y_salvo"]["meta"]), (1, 2))
        self.assertEqual(m["paz_y_salvo"]["pct"], 50.0)

    def test_periodo_pasado_usa_su_fecha_de_corte(self):
        r = resumen_indicadores(date(2026, 7, 1), date(2026, 9, 30), hoy=HOY)
        m = r["metricas"]
        self.assertEqual(r["fecha_corte"], "2026-09-30")
        # Al 30/09 PC-A aún no tenía mantenimiento (fue el 1/10) y PC-B estaba vencido.
        self.assertEqual(m["mantenimiento_computadores"]["valor"], 0)
        self.assertEqual(m["mantenimiento_radios"]["valor"], 1)
        self.assertEqual((m["ejecucion_programacion"]["valor"], m["ejecucion_programacion"]["meta"]), (1, 1))
        self.assertEqual(m["antivirus_vigente"]["valor"], 2)
        self.assertIsNone(m["paz_y_salvo"]["pct"])

    def test_periodo_por_defecto_es_el_trimestre(self):
        self.assertEqual(periodo_desde_parametros({}, hoy=HOY), (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertEqual(periodo_desde_parametros({}, hoy=date(2026, 2, 3)), (date(2026, 1, 1), date(2026, 3, 31)))
        with self.assertRaises(ValueError):
            periodo_desde_parametros({"desde": "2026-12-01", "hasta": "2026-01-01"})

    def test_endpoint_exige_token(self):
        url = "/api/v1/indicadores/?desde=2026-10-01&hasta=2026-12-31"
        self.assertIn(self.client.get(url).status_code, (401, 403))

        token = Token.objects.create(user=self.usuario)
        auth = {"HTTP_AUTHORIZATION": f"Token {token.key}"}
        resp = self.client.get(url, **auth)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("paz_y_salvo", resp.json()["metricas"])

        self.assertEqual(self.client.get("/api/v1/indicadores/?desde=malo&hasta=2026-12-31", **auth).status_code, 400)
        self.assertIn(self.client.post(url, **auth).status_code, (403, 405))
