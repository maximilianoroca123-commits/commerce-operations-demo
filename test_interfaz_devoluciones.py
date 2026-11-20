"""Regression tests: interfaz devoluciones."""

from unittest import TestCase
import test_regresion

WEB = {"X-Interfaz-Web": "1"}


class InterfazDevoluciones(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def preparar(self, cantidad=1):
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
        self.actor = ("cajero_web", "PruebaSegura123")
        self.producto = self.solicitar(
            "POST",
            "/productos",
            201,
            json={
                "nombre": "Joystick",
                "categoria": "tecnologia",
                "marca": "GamingSur",
                "precio": 1000,
                "stock": cantidad,
            },
        )["id"]
        self.solicitar(
            "PUT",
            "/cajas/venta-original/apertura",
            auth=self.actor,
            json={"fondo_inicial": 1000},
        )
        r = self.solicitar(
            "PUT",
            "/ventas-efectivo/venta-original",
            auth=self.actor,
            json={
                "caja": "venta-original",
                "recibido": cantidad * 1000 + 1000,
                "total_esperado": cantidad * 1000,
                "productos": [{"producto_id": self.producto, "cantidad": cantidad}],
            },
        )
        self.id = r["pedido_venta_id"]
        self.ruta = f"/pedidos-venta/{self.id}/devoluciones/devolucion-web-prueba"

    def devolver(self, reponer=True, cantidad=1, codigo=200):
        return self.solicitar(
            "PUT",
            self.ruta,
            codigo,
            auth=self.actor,
            headers=WEB,
            json={
                "motivo": "Prueba desde web",
                "productos": [
                    {
                        "producto_id": self.producto,
                        "cantidad": cantidad,
                        "reponer": reponer,
                    }
                ],
            },
        )

    def reintegrar(self, caja=None, estado="confirmado", codigo=200):
        data = {"estado": estado}
        if caja is not None:
            data["caja_esperada"] = caja
        return self.solicitar(
            "PUT",
            self.ruta + "/reintegro",
            codigo,
            auth=self.actor,
            headers=WEB,
            json=data,
        )

    def test_recorrido_venta_cerrada_devolucion_turno_nuevo_reintegro_y_reintentos(
        self,
    ):
        self.preparar()
        self.solicitar(
            "PUT",
            "/cajas/venta-original/cierre",
            auth=self.actor,
            json={"contado": 2000, "saldo_esperado": 2000},
        )
        receipt = self.devolver()
        self.assertEqual(
            (receipt["importe_reintegrado"], receipt["importe_por_reintegrar"]),
            (0, 1000),
        )
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 1
        )
        self.assertEqual(
            self.solicitar("GET", "/cajas/venta-original")["saldo_esperado"], 2000
        )
        self.reintegrar(codigo=409)
        self.solicitar(
            "PUT",
            "/cajas/reintegro-web/apertura",
            auth=self.actor,
            json={"fondo_inicial": 1000},
        )
        r = self.reintegrar("reintegro-web")
        self.assertEqual(
            (r["importe_reintegrado"], r["importe_por_reintegrar"]), (1000, 0)
        )
        cash = self.solicitar("GET", "/cajas/reintegro-web")
        self.assertEqual((cash["saldo_esperado"], len(cash["movimientos"])), (0, 1))
        self.solicitar(
            "PUT",
            "/cajas/reintegro-web/cierre",
            auth=self.actor,
            json={"contado": 0, "saldo_esperado": 0},
        )
        self.assertEqual(self.reintegrar("reintegro-web"), r)
        self.devolver()
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 1
        )
        self.assertEqual(
            len(self.solicitar("GET", "/cajas/reintegro-web")["movimientos"]), 1
        )
        context = self.solicitar(
            "GET", f"/operaciones/ventas/{self.id}", auth=self.actor
        )
        self.assertNotIn("devolver", context["acciones"])
        self.assertNotIn("reintegrar", context["acciones"])

    def test_no_apto_no_aumenta_stock_ni_devuelve_dinero_al_recibir(self):
        self.preparar()
        r = self.devolver(False)
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 0
        )
        self.assertEqual(
            (r["importe_reintegrado"], r["importe_por_reintegrar"]), (0, 1000)
        )
        self.assertEqual(
            self.solicitar("GET", "/cajas/venta-original")["saldo_esperado"], 2000
        )

    def test_parcial_conserva_pendientes_y_no_permite_excederlos(self):
        self.preparar(2)
        self.devolver(cantidad=1)
        c = self.solicitar("GET", f"/operaciones/ventas/{self.id}", auth=self.actor)
        self.assertEqual(
            c["pedido"]["devoluciones"]["estado_comercial"], "devuelta_parcial"
        )
        self.assertIn("devolver", c["acciones"])
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/devoluciones/otra",
            409,
            auth=self.actor,
            headers=WEB,
            json={
                "motivo": "Exceso",
                "productos": [
                    {"producto_id": self.producto, "cantidad": 2, "reponer": True}
                ],
            },
        )
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 1
        )

    def test_fallido_sigue_pendiente_y_puede_confirmarse_sin_duplicar(self):
        self.preparar()
        self.devolver()
        r = self.reintegrar(estado="fallido")
        self.assertEqual(r["importe_por_reintegrar"], 1000)
        self.assertEqual(
            len(self.solicitar("GET", "/cajas/venta-original")["movimientos"]), 1
        )
        self.reintegrar("venta-original")
        self.reintegrar("venta-original")
        self.assertEqual(
            self.solicitar("GET", "/cajas/venta-original")["saldo_esperado"], 1000
        )
        self.assertEqual(
            len(self.solicitar("GET", "/cajas/venta-original")["movimientos"]), 2
        )

    def test_no_cobra_en_otro_turno_si_cambia_la_caja_antes_de_confirmar(self):
        self.preparar()
        self.devolver()
        self.solicitar("PUT", "/cajas/venta-original/cierre", json={"contado": 2000})
        self.solicitar("PUT", "/cajas/nueva/apertura", json={"fondo_inicial": 1000})
        self.reintegrar("venta-original", codigo=409)
        self.assertEqual(self.solicitar("GET", "/cajas/nueva")["saldo_esperado"], 1000)
        self.assertEqual(
            self.solicitar("GET", f"/operaciones/ventas/{self.id}")["pedido"][
                "devoluciones"
            ]["importe_por_reintegrar"],
            1000,
        )

    def test_saldo_insuficiente_preserva_pendiente(self):
        self.preparar()
        self.devolver()
        self.solicitar("PUT", "/cajas/venta-original/cierre", json={"contado": 2000})
        self.solicitar("PUT", "/cajas/sin-saldo/apertura", json={"fondo_inicial": 0})
        self.reintegrar("sin-saldo", codigo=409)
        self.assertEqual(self.solicitar("GET", "/cajas/sin-saldo")["saldo_esperado"], 0)
        self.assertEqual(
            self.solicitar("GET", f"/operaciones/ventas/{self.id}")["pedido"][
                "devoluciones"
            ]["importe_por_reintegrar"],
            1000,
        )

    def test_cliente_no_puede_registrar_recepcion_ni_reintegro(self):
        self.preparar()
        self.solicitar(
            "PUT",
            self.ruta,
            403,
            auth=self.consulta,
            headers=WEB,
            json={
                "motivo": "Prueba",
                "productos": [
                    {"producto_id": self.producto, "cantidad": 1, "reponer": True}
                ],
            },
        )
        self.devolver()
        self.solicitar(
            "PUT",
            self.ruta + "/reintegro",
            403,
            auth=self.consulta,
            headers=WEB,
            json={"estado": "confirmado"},
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
