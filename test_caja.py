"""Regression tests: caja."""

import test_regresion


class CajaInventario(test_regresion.RegresionInventario):

    def crear(self, referencia="caja-1"):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{referencia}",
            auth=self.consulta,
            json={
                "productos": [
                    {"producto_id": 1, "cantidad": 2},
                    {"producto_id": 2, "cantidad": 1},
                ]
            },
        )

    def pagar(self, referencia="caja-1", estado="aprobado", codigo=200):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{referencia}/pago",
            codigo,
            auth=self.consulta,
            json={"estado": estado},
        )

    def test_caja_aprobada_descuenta_una_vez_y_fija_el_total(self):
        cobro = self.crear()
        self.assertEqual(cobro["total"], 24500)
        self.assertEqual(self.stock(), 7)
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        self.assertEqual(self.crear(), cobro)
        primero = self.pagar()
        self.assertEqual(primero["total"], 24500)
        self.assertEqual(self.pagar(), primero)
        self.assertEqual(self.stock(), 5)
        self.pagar(estado="rechazado", codigo=409)

    def test_caja_rechazada_conserva_existencias(self):
        self.crear()
        self.pagar(estado="rechazado")
        self.assertEqual(self.stock(), 7)
        self.pagar(codigo=409)

    def test_caja_reservada_impide_otros_descuentos(self):
        self.crear()
        self.solicitar("PATCH", "/productos/2", 409, json={"stock": 0})
        self.vender("otra-venta", 6, 409)
        self.assertEqual(self.stock(), 7)
        self.pagar()
        self.assertEqual(self.stock(), 5)
