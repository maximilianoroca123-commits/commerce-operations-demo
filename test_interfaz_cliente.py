"""Regression tests: interfaz cliente."""

from unittest import TestCase
import test_regresion

WEB = {"X-Interfaz-Web": "1"}


class InterfazCliente(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def cuenta(self, name):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": name,
                "rol": "cliente",
                "clave": "PruebaSegura123",
                "cliente": {
                    "nombre": name,
                    "apellido": "Prueba",
                    "correo": name + "@example.com",
                },
            },
        )
        return (name, "PruebaSegura123")

    def preparar(self, modalidad="retiro", ref="compra-web-prueba"):
        self.ana = self.cuenta("ana_web")
        self.bruno = self.cuenta("bruno_web")
        self.ref = ref
        self.data = {
            "productos": [{"producto_id": 1, "cantidad": 1}],
            "canal": "online",
            "modalidad": modalidad,
        }
        if modalidad == "envio":
            self.data["direccion_entrega"] = "Calle de prueba 123, localidad de prueba"
        r = self.solicitar(
            "PUT", "/cobros-demo/" + ref, auth=self.ana, headers=WEB, json=self.data
        )
        self.id = r["pedido_venta_id"]
        return r

    def pagar(self, estado="aprobado"):
        return self.solicitar(
            "PUT",
            "/cobros-demo/" + self.ref + "/pago",
            auth=self.ana,
            headers=WEB,
            json={"estado": estado},
        )

    def entregar(self):
        for state in ["preparando", "listo", "entregado"]:
            self.solicitar(
                "PUT", f"/pedidos-venta/{self.id}/entrega", json={"estado": state}
            )

    def test_compra_reserva_pago_y_reintentos_con_un_solo_descuento(self):
        r = self.preparar()
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(
            self.solicitar("GET", "/productos/1/disponibilidad", auth=self.ana)[
                "disponible"
            ],
            6,
        )
        self.assertEqual(
            self.solicitar(
                "PUT",
                "/cobros-demo/" + self.ref,
                auth=self.ana,
                headers=WEB,
                json=self.data,
            ),
            r,
        )
        paid = self.pagar()
        self.assertEqual(self.pagar(), paid)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        p = self.solicitar(
            "GET", f"/pedidos-venta/{self.id}", auth=self.ana, headers=WEB
        )
        self.assertNotIn("pagar", p["acciones_cliente"])
        self.assertIn("comprobante", p["acciones_cliente"])
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta", auth=self.ana)["total"], 1
        )

    def test_otra_cuenta_no_ve_paga_ni_descarga_el_pedido(self):
        self.preparar()
        for route in [
            f"/pedidos-venta/{self.id}",
            f"/pedidos-venta/{self.id}/ticket",
            "/cobros-demo/" + self.ref,
        ]:
            self.solicitar("GET", route, 404, auth=self.bruno, headers=WEB)
        self.solicitar(
            "PUT",
            "/cobros-demo/" + self.ref + "/pago",
            404,
            auth=self.bruno,
            headers=WEB,
            json={"estado": "aprobado"},
        )
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta", auth=self.bruno)["total"], 0
        )

    def test_envio_con_direccion_y_rechazo_sin_descontar_stock(self):
        self.preparar("envio")
        r = self.pagar("rechazado")
        self.assertEqual(r["estado"], "rechazado")
        p = self.solicitar("GET", f"/pedidos-venta/{self.id}", auth=self.ana)
        self.assertEqual(p["direccion_entrega"], self.data["direccion_entrega"])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(
            self.solicitar("GET", "/productos/1/disponibilidad", auth=self.ana)[
                "disponible"
            ],
            7,
        )

    def test_devolucion_solicitada_no_mueve_stock_y_respuesta_llega_al_cliente(self):
        self.preparar()
        self.pagar()
        self.entregar()
        route = f"/pedidos-venta/{self.id}/solicitudes/solicitud-web-prueba"
        payload = {"tipo": "devolucion", "motivo": "Prueba del cliente web"}
        self.solicitar("PUT", route, auth=self.ana, headers=WEB, json=payload)
        self.solicitar("PUT", route, auth=self.ana, headers=WEB, json=payload)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        base = f"/solicitudes-clientes/{self.id}/solicitud-web-prueba"
        c = self.solicitar("GET", base)
        ref = c["referencia_operacion"]
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/devoluciones/{ref}",
            json={
                "motivo": payload["motivo"],
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
            },
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/devoluciones/{ref}/reintegro",
            json={"estado": "confirmado"},
        )
        self.solicitar(
            "PUT",
            base + "/resolucion",
            json={
                "estado": "atendida",
                "motivo": "Producto recibido y reintegro confirmado",
            },
        )
        r = self.solicitar(
            "GET",
            f"/solicitudes-clientes?pedido_id={self.id}&limite=10",
            auth=self.ana,
            headers=WEB,
        )
        self.assertEqual(r["total"], 1)
        self.assertEqual(
            r["solicitudes"][0]["resolucion"]["motivo"],
            "Producto recibido y reintegro confirmado",
        )
        self.assertNotIn("usuario", r["solicitudes"][0]["resolucion"])
        self.assertEqual(
            self.solicitar(
                "GET", f"/solicitudes-clientes?pedido_id={self.id}", auth=self.bruno
            )["total"],
            0,
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_solicitud_de_cancelacion_antes_de_entrega_y_validacion_devolucion(self):
        self.preparar()
        self.pagar()
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/solicitudes/dev",
            409,
            auth=self.ana,
            headers=WEB,
            json={"tipo": "devolucion", "motivo": "No entregado"},
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/solicitudes/cancelar",
            auth=self.ana,
            headers=WEB,
            json={"tipo": "cancelacion", "motivo": "Cambio de planes"},
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            self.solicitar(
                "GET", f"/solicitudes-clientes?pedido_id={self.id}", auth=self.ana
            )["total"],
            1,
        )

    def test_perfil_y_comprobante_solo_del_titular(self):
        self.preparar()
        self.pagar()
        profile = self.solicitar("GET", "/mi-perfil", auth=self.ana, headers=WEB)
        self.assertEqual(profile["cliente"]["correo"], "ana_web@example.com")
        self.assertNotIn("clave_hash", str(profile))
        ticket = self.cliente.get(
            f"/pedidos-venta/{self.id}/ticket", auth=self.ana, headers=WEB
        )
        self.assertEqual(ticket.status_code, 200)
        self.assertIn("text/html", ticket.headers["content-type"])
        self.assertEqual(ticket.headers["cache-control"], "no-store")
        self.assertIn("Mouse", ticket.text)

    def test_paginacion_respeta_titular_antes_de_filtrar(self):
        self.preparar()
        self.pagar("rechazado")
        for i in range(11):
            self.solicitar(
                "PUT",
                f"/cobros-demo/otro-{i}",
                auth=self.bruno,
                json={
                    "productos": [{"producto_id": 1, "cantidad": 1}],
                    "canal": "online",
                    "modalidad": "retiro",
                },
            )
            self.solicitar(
                "PUT",
                f"/cobros-demo/otro-{i}/pago",
                auth=self.bruno,
                json={"estado": "rechazado"},
            )
        a = self.solicitar(
            "GET", "/pedidos-venta?pagina=1&limite=10", auth=self.ana, headers=WEB
        )
        b = self.solicitar(
            "GET", "/pedidos-venta?pagina=2&limite=10", auth=self.bruno, headers=WEB
        )
        self.assertEqual((a["total"], len(a["pedidos"])), (1, 1))
        self.assertEqual((b["total"], len(b["pedidos"])), (11, 1))
        self.assertNotEqual(b["pedidos"][0]["id"], self.id)

    def test_cliente_no_accede_a_operaciones_del_personal(self):
        self.preparar()
        for route in [
            "/operaciones/caja-actual",
            "/ventas",
            "/usuarios",
            f"/operaciones/ventas/{self.id}",
        ]:
            self.solicitar("GET", route, 403, auth=self.ana, headers=WEB)


if __name__ == "__main__":
    import unittest

    unittest.main()
