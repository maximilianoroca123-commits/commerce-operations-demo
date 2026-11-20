"""Regression tests: interfaz ventas caja."""

from unittest import TestCase
import test_regresion

WEB = {"X-Interfaz-Web": "1"}


class InterfazVentasCaja(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def preparar(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "cajero_web",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        self.empleado = ("cajero_web", "PruebaSegura123")
        self.solicitar(
            "PUT",
            "/cajas/caja-web-prueba/apertura",
            auth=self.empleado,
            headers=WEB,
            json={"fondo_inicial": 1000},
        )

    def cobrar(self, referencia="venta-web-prueba", codigo=200, **cambios):
        datos = {
            "caja": "caja-web-prueba",
            "recibido": 10000,
            "total_esperado": 8500,
            "productos": [{"producto_id": 1, "cantidad": 1}],
        }
        return self.solicitar(
            "PUT",
            "/ventas-efectivo/" + referencia,
            codigo,
            auth=self.empleado,
            headers=WEB,
            json={**datos, **cambios},
        )

    def test_empleado_abre_cobra_descarga_ticket_consulta_y_cierra(self):
        self.preparar()
        c = self.solicitar(
            "GET", "/operaciones/caja-actual", auth=self.empleado, headers=WEB
        )
        self.assertEqual(c["caja"]["saldo_esperado"], 1000)
        producto = self.solicitar(
            "GET",
            "/productos?texto=Mouse&pagina=1&limite=10",
            auth=self.empleado,
            headers=WEB,
        )["productos"][0]
        self.assertEqual(producto["id"], 1)
        venta = self.cobrar()
        self.assertEqual((venta["total"], venta["vuelto"]), (8500, 1500))
        id = venta["pedido_venta_id"]
        detalle = self.solicitar(
            "GET", f"/operaciones/ventas/{id}", auth=self.empleado, headers=WEB
        )["pedido"]
        self.assertEqual(detalle["registrado_por"], "cajero_web")
        self.assertEqual(detalle["efectivo"]["recibido"], 10000)
        ticket = self.cliente.get(
            f"/pedidos-venta/{id}/ticket", auth=self.empleado, headers=WEB
        )
        self.assertEqual(ticket.status_code, 200)
        self.assertIn("text/html", ticket.headers["content-type"])
        self.assertIn("Efectivo recibido: $ 10.000,00", ticket.text)
        self.assertIn("Vuelto: $ 1.500,00", ticket.text)
        self.assertEqual(ticket.headers["cache-control"], "no-store")
        self.assertEqual(
            self.solicitar("GET", "/ventas", auth=self.empleado, headers=WEB)["total"],
            1,
        )
        caja = self.solicitar(
            "GET", "/cajas/caja-web-prueba", auth=self.empleado, headers=WEB
        )
        self.assertEqual((caja["saldo_esperado"], len(caja["movimientos"])), (9500, 1))
        cerrada = self.solicitar(
            "PUT",
            "/cajas/caja-web-prueba/cierre",
            auth=self.empleado,
            headers=WEB,
            json={"contado": 9500, "saldo_esperado": 9500},
        )
        self.assertEqual((cerrada["estado"], cerrada["diferencia"]), ("cerrada", 0))
        self.assertIsNone(
            self.solicitar(
                "GET", "/operaciones/caja-actual", auth=self.empleado, headers=WEB
            )["caja"]
        )
        self.assertEqual(self.cobrar(), venta)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            len(self.solicitar("GET", "/cajas/caja-web-prueba")["movimientos"]), 1
        )

    def test_sin_caja_se_consulta_pero_no_se_cobra(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "cajero_web",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        self.empleado = ("cajero_web", "PruebaSegura123")
        c = self.solicitar(
            "GET", "/operaciones/caja-actual", auth=self.empleado, headers=WEB
        )
        self.assertIsNone(c["caja"])
        self.cobrar(codigo=404)
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)

    def test_precio_cambiado_requiere_nuevo_resumen_sin_cobro_parcial(self):
        self.preparar()
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        self.cobrar(codigo=409)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(
            self.solicitar("GET", "/cajas/caja-web-prueba")["saldo_esperado"], 1000
        )
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)

    def test_cierre_con_saldo_obsoleto_debe_revisarse(self):
        self.preparar()
        self.cobrar()
        self.solicitar(
            "PUT",
            "/cajas/caja-web-prueba/cierre",
            409,
            auth=self.empleado,
            headers=WEB,
            json={"contado": 1000, "saldo_esperado": 1000},
        )
        self.assertIsNone(self.solicitar("GET", "/cajas/caja-web-prueba")["cerrado_en"])

    def test_multi_producto_con_total_y_vuelto_coherentes(self):
        self.preparar()
        venta = self.cobrar(
            total_esperado=24500,
            recibido=25000,
            productos=[
                {"producto_id": 1, "cantidad": 2},
                {"producto_id": 2, "cantidad": 1},
            ],
        )
        self.assertEqual((venta["total"], venta["vuelto"]), (24500, 500))
        self.assertEqual(
            self.solicitar("GET", "/cajas/caja-web-prueba")["saldo_esperado"], 25500
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 5)
        self.assertEqual(self.solicitar("GET", "/productos/2")["stock"], 4)

    def test_cuenta_cliente_no_puede_abrir_cobrar_ni_consultar_cajas(self):
        for method, path, data in [
            ("GET", "/operaciones/caja-actual", None),
            ("GET", "/ventas", None),
            ("GET", "/cajas", None),
            ("PUT", "/cajas/prueba/apertura", {"fondo_inicial": 0}),
            (
                "PUT",
                "/ventas-efectivo/prueba",
                {
                    "caja": "prueba",
                    "recibido": 10000,
                    "productos": [{"producto_id": 1, "cantidad": 1}],
                },
            ),
        ]:
            extra = {"json": data} if data is not None else {}
            self.solicitar(method, path, 403, auth=self.consulta, headers=WEB, **extra)


if __name__ == "__main__":
    import unittest

    unittest.main()
