"""Regression tests: pagos limite."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import caja
import test_regresion


class PagosLimite(test_regresion.RegresionInventario):
    def setUp(self):
        # Keep the controlled-clock cases independent of the periodic worker.
        # Explicit reconciliation routes still use the real function after startup.
        with patch.object(caja, "recuperar_cobros", return_value=None):
            super().setUp()
        self.fecha = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.enterContext(patch.object(caja, "ahora", side_effect=lambda: self.fecha))

    def crear(self, ref="pago-1", cantidad=7, codigo=200):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{ref}",
            codigo,
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": cantidad}]},
        )

    def ver(self, ref="pago-1"):
        return self.solicitar("GET", f"/cobros-demo/{ref}", auth=self.consulta)

    def evento(self, estado, ref="pago-1", evento=None, codigo=200):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{ref}/eventos/{evento or estado}",
            codigo,
            auth=self.consulta,
            json={"estado": estado},
        )

    def pagar(self, estado="aprobado", ref="pago-1"):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{ref}/pago",
            auth=self.consulta,
            json={"estado": estado},
        )

    def disponibilidad(self):
        return self.solicitar("GET", "/productos/1/disponibilidad")

    def test_reserva_prioriza_la_primera_caja(self):
        self.crear()
        self.crear("otra-caja", 1, 409)
        self.vender("venta-directa", 1, 409)
        self.assertEqual(self.disponibilidad()["disponible"], 0)
        self.assertEqual(self.stock(), 7)

    def test_vencimiento_confirmado_libera_y_el_reintento_no_renueva(self):
        self.crear()
        self.fecha += timedelta(minutes=5)
        self.assertEqual(self.ver()["estado"], "vencido")
        self.assertEqual(self.crear()["estado"], "vencido")
        self.assertEqual(self.disponibilidad()["reservado"], 0)

    def test_pago_iniciado_al_limite_conserva_la_reserva(self):
        self.crear()
        self.fecha += timedelta(minutes=4, seconds=59)
        self.evento("procesando")
        self.fecha += timedelta(seconds=5)
        self.assertEqual(self.ver()["estado"], "procesando")
        self.evento("cancelado", codigo=409)
        self.assertEqual(self.pagar()["estado"], "aprobado")
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.pagar()["estado"], "aprobado")
        self.assertEqual(self.stock(), 0)

    def test_desconexion_al_vencer_mantiene_reserva(self):
        self.crear()
        self.solicitar(
            "PUT",
            "/cobros-demo/pago-1/conexion",
            auth=self.consulta,
            json={"disponible": False},
        )
        self.fecha += timedelta(minutes=6)
        self.assertEqual(self.ver()["estado"], "verificando")
        self.assertEqual(self.disponibilidad()["reservado"], 7)
        self.solicitar(
            "PUT",
            "/cobros-demo/pago-1/conexion",
            auth=self.consulta,
            json={"disponible": True},
        )
        self.assertEqual(self.ver()["estado"], "vencido")

    def test_resultado_persistido_se_recupera_sin_notificacion(self):
        self.crear()
        self.evento("aprobado")
        self.assertEqual(self.stock(), 7)

        self.solicitar("POST", "/pagos-demo/conciliar")
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.ver()["estado"], "aprobado")

    def test_notificaciones_atrasadas_y_eventos_repetidos(self):
        self.crear()
        self.pagar()
        self.evento("pendiente")
        self.evento("procesando")
        self.assertEqual(self.ver()["estado"], "aprobado")
        self.evento("aprobado", evento="aprobado")
        self.evento("rechazado", evento="aprobado", codigo=409)
        self.assertEqual(self.stock(), 0)

    def test_aprobacion_tardia_sin_stock_requiere_devolucion(self):
        self.crear()
        self.fecha += timedelta(minutes=6)
        self.ver()
        self.vender("venta-posterior", 7)
        self.evento("aprobado", evento="aprobacion-tardia")
        self.assertEqual(self.ver()["estado"], "requiere_devolucion")
        ruta = "/cobros-demo/pago-1/devolucion"
        self.assertEqual(
            self.solicitar("PUT", ruta, auth=self.consulta)["estado"], "reembolsado"
        )
        self.assertEqual(
            self.solicitar("PUT", ruta, auth=self.consulta)["reembolso"], "confirmado"
        )
        self.assertEqual(self.stock(), 0)

    def test_aprobacion_tardia_con_stock_completa_la_venta(self):
        self.crear()
        self.fecha += timedelta(minutes=6)
        self.ver()
        self.evento("aprobado", evento="tardio")
        self.assertEqual(self.ver()["estado"], "aprobado")
        self.assertEqual(self.stock(), 0)

    def test_dos_cajas_simultaneas_reservan_una_sola_vez(self):
        def intento(ref):
            return self.cliente.put(
                f"/cobros-demo/{ref}",
                auth=self.consulta,
                json={"productos": [{"producto_id": 1, "cantidad": 7}]},
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(
                sorted(pool.map(intento, ("caja-a", "caja-b"))), [200, 409]
            )

    def test_cancelacion_confirmada_libera(self):
        self.crear()
        self.evento("cancelado")
        self.assertEqual(self.ver()["estado"], "cancelado")
        self.assertEqual(self.disponibilidad()["disponible"], 7)

    def test_aprobacion_y_cancelacion_concurrentes_no_duplican_stock(self):
        self.crear()

        def resultado(estado):
            return self.cliente.put(
                "/cobros-demo/pago-1/pago", auth=self.consulta, json={"estado": estado}
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            list(pool.map(resultado, ("aprobado", "rechazado")))
        cobro = self.ver()
        self.assertIn(cobro["estado"], ("aprobado", "rechazado"))
        self.assertEqual(self.stock(), 0 if cobro["estado"] == "aprobado" else 7)

    def test_pago_tardio_no_consume_la_reserva_de_otra_caja(self):
        self.crear()
        self.fecha += timedelta(minutes=6)
        self.ver()
        self.crear("segunda-caja")
        self.evento("aprobado", evento="tardio")
        self.solicitar("POST", "/pagos-demo/conciliar")
        self.assertEqual(self.ver()["estado"], "requiere_devolucion")
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.disponibilidad()["disponible"], 0)

    def test_datos_invalidos_y_sin_credenciales(self):
        respuesta = self.cliente.put(
            "/cobros-demo/sin-clave",
            json={"productos": [{"producto_id": 1, "cantidad": 1}]},
        )
        self.assertEqual(respuesta.status_code, 401)
        self.solicitar(
            "PUT", "/cobros-demo/vacio", 422, auth=self.consulta, json={"productos": []}
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/invalido",
            422,
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": True}]},
        )
