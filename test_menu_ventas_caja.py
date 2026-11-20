"""Regression tests: menu ventas caja."""

from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import test_menu_pedidos_cliente
import menu_api
import menu_ventas_caja as menu


class VentasCaja(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    sesion = test_menu_pedidos_cliente.PedidosCliente.sesion

    def preparar(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={"usuario": "cajero", "rol": "empleado", "clave": "PruebaSegura123"},
        )
        self.empleado = ("cajero", "PruebaSegura123")
        self.solicitar(
            "PUT",
            "/cajas/turno/apertura",
            auth=self.empleado,
            json={"fondo_inicial": 1000},
        )

    def vender(self, ref="venta"):
        return self.solicitar(
            "PUT",
            "/ventas-efectivo/" + ref,
            auth=self.empleado,
            json={
                "caja": "turno",
                "recibido": 10000,
                "productos": [{"producto_id": 1, "cantidad": 1}],
            },
        )["pedido_venta_id"]

    def test_cobro_turno_automatico_y_comprobante_de_la_venta(self):
        self.preparar()
        with TemporaryDirectory() as t:
            with patch.object(
                menu_api, "__file__", str(Path(t) / "menu_api.py")
            ), patch(
                "builtins.input",
                side_effect=["1", "1", "n", "10000", "s", "s", "1", "2", "0"],
            ), patch(
                "builtins.print"
            ):
                menu.nueva_venta(self.sesion(self.empleado))
            id = self.solicitar("GET", "/ventas")["pedidos"][0]["id"]
            self.assertTrue((Path(t) / "tickets" / f"venta-{id}.html").is_file())
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 9500)
        d = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertEqual(d["efectivo"]["vuelto"], 1500)
        self.assertEqual(d["registrado_por"], "cajero")

    def test_no_caja_no_pide_carrito(self):
        with patch("builtins.input") as entrada, patch("builtins.print"):
            menu.nueva_venta(self.sesion(self.compras))
        entrada.assert_not_called()
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)

    def test_abrir_y_cerrar_sin_escribir_referencia(self):
        with patch(
            "builtins.input", side_effect=["1", "1000", "s", "3", "1000", "s", "0"]
        ), patch("builtins.print"):
            menu.caja_actual(self.sesion(self.compras))
        cajas = self.solicitar("GET", "/cajas")["cajas"]
        self.assertEqual(len(cajas), 1)
        self.assertEqual(cajas[0]["diferencia"], 0)
        self.assertIsNotNone(cajas[0]["cerrado_en"])

    def test_cambio_precio_rechaza_total_previamente_confirmado(self):
        self.preparar()
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        self.solicitar(
            "PUT",
            "/ventas-efectivo/precio",
            409,
            auth=self.empleado,
            json={
                "caja": "turno",
                "recibido": 10000,
                "total_esperado": 8500,
                "productos": [{"producto_id": 1, "cantidad": 1}],
            },
        )
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 1000)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_respuesta_perdida_no_duplica_cobro(self):
        self.preparar()
        original = menu.api
        intentos = []

        def perder(sesion, metodo, ruta, datos=None):
            r = original(sesion, metodo, ruta, datos)
            if metodo == "PUT":
                intentos.append((ruta, datos))
                if len(intentos) == 1:
                    return None
            return r

        with patch.object(menu, "api", side_effect=perder), patch(
            "builtins.input", side_effect=["1", "1", "n", "10000", "s", "s", "n"]
        ), patch("builtins.print"):
            menu.nueva_venta(self.sesion(self.empleado))
        self.assertEqual(intentos[0], intentos[1])
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 1)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 9500)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_cancelar_cobro_no_escribe(self):
        self.preparar()
        with patch("builtins.input", side_effect=["1", "1", "n", "10000", "n"]), patch(
            "builtins.print"
        ):
            menu.nueva_venta(self.sesion(self.empleado))
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 1000)

    def test_devolucion_y_reintegro_seleccionados_sin_ids(self):
        self.preparar()
        id = self.vender()
        with patch(
            "builtins.input",
            side_effect=[
                "4",
                "Prueba de devolución",
                "1",
                "s",
                "s",
                "6",
                "1",
                "1",
                "s",
                "0",
            ],
        ), patch("builtins.print"):
            menu.gestionar_venta(self.sesion(self.empleado), id)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 1000)
        d = self.solicitar("GET", f"/operaciones/ventas/{id}", auth=self.empleado)
        self.assertNotIn("reintegrar", d["acciones"])
        self.assertNotIn("devolver", d["acciones"])

    def test_permisos_contexto_y_movimientos_admin(self):
        self.preparar()
        id = self.vender()
        self.assertNotIn(
            "movimiento",
            self.solicitar("GET", "/operaciones/caja-actual", auth=self.empleado)[
                "acciones"
            ],
        )
        self.assertIn(
            "movimiento", self.solicitar("GET", "/operaciones/caja-actual")["acciones"]
        )
        for ruta in ["/operaciones/caja-actual", f"/operaciones/ventas/{id}"]:
            self.solicitar("GET", ruta, 403, auth=self.consulta)
        self.solicitar(
            "PUT",
            "/cajas/turno/movimientos/retiro",
            403,
            auth=self.empleado,
            json={"tipo": "retiro", "importe": 100, "motivo": "Prueba"},
        )

    def test_solicitud_pendiente_se_enlaza_a_su_recorrido(self):
        self.preparar()
        r = self.solicitar(
            "PUT",
            "/cobros-demo/cliente",
            auth=self.consulta,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
            },
        )
        id = r["pedido_venta_id"]
        self.solicitar(
            "PUT",
            "/cobros-demo/cliente/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/solicitudes/sol",
            auth=self.consulta,
            json={"tipo": "cancelacion", "motivo": "Prueba"},
        )
        c = self.solicitar("GET", f"/operaciones/ventas/{id}")
        self.assertIn("atender_solicitud", c["acciones"])
        self.assertNotIn("cancelar", c["acciones"])
        with patch("builtins.input", side_effect=["10", "1", "0", "0"]), patch(
            "builtins.print"
        ):
            menu.gestionar_venta(self.sesion(self.empleado), id)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_reintento_venta_anterior_sin_total_opcional(self):
        self.preparar()
        a = self.vender("anterior")
        b = self.vender("anterior")
        self.assertEqual(a, b)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_cierre_rechaza_movimientos_posteriores_a_la_consulta(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/cajas/turno/movimientos/ingreso",
            json={"tipo": "ingreso", "importe": 100, "motivo": "Prueba"},
        )
        self.solicitar(
            "PUT",
            "/cajas/turno/cierre",
            409,
            auth=self.empleado,
            json={"contado": 1000, "saldo_esperado": 1000},
        )
        caja = self.solicitar("GET", "/cajas/turno")
        self.assertEqual(caja["estado"], "abierta")
        self.assertEqual(caja["saldo_esperado"], 1100)
