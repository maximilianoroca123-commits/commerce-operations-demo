"""Regression tests: efectivo."""

from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import preparar_db_api
import test_regresion


class Efectivo(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def abrir(self, ref="turno", fondo=1000, codigo=200):
        return self.solicitar(
            "PUT", f"/cajas/{ref}/apertura", codigo, json={"fondo_inicial": fondo}
        )

    def cobrar(
        self, ref="venta", caja="turno", recibido=10000, productos=None, codigo=200
    ):
        return self.solicitar(
            "PUT",
            f"/ventas-efectivo/{ref}",
            codigo,
            json={
                "caja": caja,
                "recibido": recibido,
                "productos": productos or [{"producto_id": 1, "cantidad": 1}],
            },
        )

    def caja(self, ref="turno"):
        return self.solicitar("GET", f"/cajas/{ref}")

    def stock(self):
        return self.solicitar("GET", "/productos/1")["stock"]

    def cerrar(self, ref="turno", contado=9500, codigo=200):
        return self.solicitar(
            "PUT", f"/cajas/{ref}/cierre", codigo, json={"contado": contado}
        )

    def devolver(self, id):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/dev",
            json={
                "motivo": "Devuelto",
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
            },
        )

    def reintegrar(self, id, estado="confirmado", codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/dev/reintegro",
            codigo,
            json={"estado": estado},
        )

    def test_apertura_reintento_cierre_diferencia_y_nuevo_turno(self):
        a = self.abrir()
        self.assertEqual(self.abrir(), a)
        self.abrir(fondo=2000, codigo=409)
        self.abrir("otra", codigo=409)
        c = self.cerrar(contado=900)
        self.assertEqual((c["saldo_esperado"], c["diferencia"]), (1000, -100))
        self.assertEqual(self.cerrar(contado=900), c)
        self.cerrar(contado=1000, codigo=409)
        self.assertEqual(self.abrir()["estado"], "cerrada")
        self.abrir("otra")
        self.assertEqual(self.solicitar("GET", "/cajas")["total"], 2)

    def test_carrito_vuelto_stock_ticket_y_reintento_tras_cierre(self):
        self.abrir()
        productos = [
            {"producto_id": 1, "cantidad": 2},
            {"producto_id": 2, "cantidad": 1},
        ]
        venta = self.cobrar(recibido=25000, productos=productos)
        self.assertEqual((venta["total"], venta["vuelto"]), (24500, 500))
        self.assertEqual(self.stock(), 5)
        self.assertEqual(self.caja()["saldo_esperado"], 25500)
        id = venta["pedido_venta_id"]
        pedido = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertEqual(pedido["medio_pago"], "efectivo")
        self.assertEqual(pedido["estado_entrega"], "entregado")
        ticket = self.cliente.get(f"/pedidos-venta/{id}/ticket", auth=self.compras)
        self.assertIn("Efectivo recibido: $ 25.000,00", ticket.text)
        self.assertIn("Vuelto: $ 500,00", ticket.text)
        self.cerrar(contado=25500)
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.cobrar(recibido=25000, productos=productos), venta)
        self.assertEqual(self.stock(), 5)
        self.assertEqual(len(self.caja()["movimientos"]), 1)
        self.cobrar("otra", codigo=409)
        self.cobrar(recibido=26000, productos=productos, codigo=409)

    def test_ingreso_retiro_y_saldo_insuficiente(self):
        self.abrir()
        ruta = "/cajas/turno/movimientos/retiro"
        datos = {"tipo": "retiro", "importe": 300, "motivo": "Retiro a caja fuerte"}
        r = self.solicitar("PUT", ruta, json=datos)
        self.assertEqual(r["saldo_esperado"], 700)
        self.assertEqual(self.solicitar("PUT", ruta, json=datos), r)
        self.solicitar("PUT", ruta, 409, json={**datos, "importe": 200})
        self.solicitar(
            "PUT",
            "/cajas/turno/movimientos/exceso",
            409,
            json={**datos, "importe": 701},
        )
        r = self.solicitar(
            "PUT",
            "/cajas/turno/movimientos/ingreso",
            json={"tipo": "ingreso", "importe": 500, "motivo": "Cambio"},
        )
        self.assertEqual(r["saldo_esperado"], 1200)
        self.cerrar(contado=1200)
        self.solicitar("PUT", "/cajas/turno/movimientos/tarde", 409, json=datos)

    def test_reintegro_fallido_confirmado_repetido_no_duplica_egreso(self):
        self.abrir()
        id = self.cobrar()["pedido_venta_id"]
        self.devolver(id)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.caja()["saldo_esperado"], 9500)
        self.reintegrar(id, "fallido")
        self.assertEqual(len(self.caja()["movimientos"]), 1)
        self.reintegrar(id)
        self.reintegrar(id)
        self.assertEqual(self.caja()["saldo_esperado"], 1000)
        self.assertEqual(len(self.caja()["movimientos"]), 2)
        self.assertEqual(self.stock(), 7)

    def test_reintegro_turno_siguiente_y_sin_saldo_conserva_deuda(self):
        self.abrir()
        id = self.cobrar()["pedido_venta_id"]
        self.cerrar()
        self.devolver(id)
        self.reintegrar(id, codigo=409)
        self.abrir("turno2", fondo=100)
        self.reintegrar(id, codigo=409)
        self.assertEqual(self.caja("turno2")["saldo_esperado"], 100)
        pedido = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertEqual(pedido["devoluciones"]["importe_por_reintegrar"], 8500)
        self.solicitar(
            "PUT",
            "/cajas/turno2/movimientos/fondo",
            json={"tipo": "ingreso", "importe": 9000, "motivo": "Fondo para reintegro"},
        )
        self.reintegrar(id)
        self.assertEqual(self.caja("turno2")["saldo_esperado"], 600)
        self.assertEqual(self.caja()["saldo_esperado"], 9500)

    def test_stock_reservado_y_carrito_invalido_no_cambian_caja(self):
        self.abrir()
        self.solicitar(
            "PUT",
            "/cobros-demo/reserva",
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 7}]},
        )
        self.cobrar(codigo=409)
        self.cobrar(
            "invalida",
            productos=[
                {"producto_id": 2, "cantidad": 1},
                {"producto_id": 1, "cantidad": 1},
            ],
            codigo=409,
        )
        self.assertEqual(self.solicitar("GET", "/productos/2")["stock"], 5)
        self.assertEqual(self.caja()["saldo_esperado"], 1000)
        self.assertEqual(self.stock(), 7)

    def test_fallo_registro_caja_revierte_toda_la_venta(self):
        self.abrir()
        with patch("servidor.logger.error"), patch(
            "caja_efectivo.mover",
            side_effect=sqlite3.OperationalError("Fallo simulado"),
        ):
            self.cobrar(codigo=500)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.caja()["movimientos"], [])
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)
        m = self.solicitar("GET", "/inventario/movimientos?producto_id=1")[
            "movimientos"
        ]
        self.assertEqual(len(m), 1)
        self.cobrar()

    def test_permisos_validacion_y_pago_insuficiente(self):
        self.solicitar(
            "PUT",
            "/cajas/turno/apertura",
            403,
            auth=self.consulta,
            json={"fondo_inicial": 100},
        )
        self.solicitar(
            "PUT", "/cajas/turno/apertura", 422, json={"fondo_inicial": True}
        )
        self.cobrar(codigo=404)
        self.abrir()
        self.cobrar(recibido=8499, codigo=409)
        self.cobrar(productos=[{"producto_id": 1, "cantidad": 1}] * 2, codigo=409)
        self.solicitar("GET", "/cajas?pagina=0", 422)
        self.solicitar("GET", "/cajas/no-existe", 404)
        self.assertEqual(self.cliente.get("/cajas").status_code, 401)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.caja()["saldo_esperado"], 1000)

    def test_venta_simultanea_y_cierre_no_dejan_venta_sin_caja(self):
        self.abrir()

        def accion(operacion):
            if operacion == "venta":
                return self.cliente.put(
                    "/ventas-efectivo/venta",
                    auth=self.compras,
                    json={
                        "caja": "turno",
                        "recibido": 10000,
                        "productos": [{"producto_id": 1, "cantidad": 1}],
                    },
                ).status_code
            return self.cliente.put(
                "/cajas/turno/cierre", auth=self.compras, json={"contado": 1000}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as e:
            estados = list(e.map(accion, ["venta", "cierre"]))
        self.assertEqual(estados[1], 200)
        self.assertIn(estados[0], [200, 409])
        caja = self.caja()
        self.assertEqual(caja["saldo_esperado"], 9500 if estados[0] == 200 else 1000)
        self.assertEqual(self.stock(), 6 if estados[0] == 200 else 7)

    def test_menu_apertura_cobro_consulta_y_cierre(self):
        import menu_api

        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

        with patch("builtins.input", side_effect=["turno", "1000", "s"]), patch(
            "builtins.print"
        ):
            menu_api.gestionar_caja_efectivo(Sesion(), "apertura")
        with patch(
            "builtins.input",
            side_effect=["turno", "venta", "1", "1", "n", "10000", "s"],
        ), patch("builtins.print"):
            menu_api.cobrar_en_efectivo(Sesion())
        with patch("builtins.input", side_effect=["turno", "9500", "s"]), patch(
            "builtins.print"
        ):
            menu_api.gestionar_caja_efectivo(Sesion(), "cierre")
        self.assertEqual(self.caja()["diferencia"], 0)
        self.assertEqual(self.stock(), 6)
