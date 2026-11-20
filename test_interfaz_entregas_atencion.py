"""Regression tests: interfaz entregas atencion."""

from unittest import TestCase
import test_regresion

WEB = {"X-Interfaz-Web": "1"}


class InterfazEntregasAtencion(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def preparar(self, modalidad="retiro", pagar=True):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "ana_web",
                "rol": "cliente",
                "clave": "PruebaSegura123",
                "cliente": {
                    "nombre": "Ana",
                    "apellido": "Prueba",
                    "correo": "ana@example.com",
                },
            },
        )
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "operador_web",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        self.ana = ("ana_web", "PruebaSegura123")
        self.empleado = ("operador_web", "PruebaSegura123")
        data = {
            "productos": [{"producto_id": 1, "cantidad": 1}],
            "canal": "online",
            "modalidad": modalidad,
        }
        if modalidad == "envio":
            data["direccion_entrega"] = "Dirección de prueba 123"
        r = self.solicitar("PUT", "/cobros-demo/prueba-web", auth=self.ana, json=data)
        self.id = r["pedido_venta_id"]
        if pagar:
            self.solicitar(
                "PUT",
                "/cobros-demo/prueba-web/pago",
                auth=self.ana,
                json={"estado": "aprobado"},
            )
        return self.id

    def paso(self, estado, codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/entrega",
            codigo,
            auth=self.empleado,
            headers=WEB,
            json={"estado": estado},
        )

    def solicitud(self, tipo="devolucion"):
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/solicitudes/sol-web",
            auth=self.ana,
            json={"tipo": tipo, "motivo": "Prueba de atención web"},
        )
        self.base = f"/solicitudes-clientes/{self.id}/sol-web"
        return self.solicitar("GET", self.base, auth=self.empleado, headers=WEB)

    def entregar(self):
        for estado in ["preparando", "listo", "entregado"]:
            self.paso(estado)

    def test_retiro_guiado_no_duplica_stock_cobro_ni_pasos(self):
        self.preparar()
        self.assertEqual(
            self.solicitar(
                "GET",
                "/pedidos-venta?pendientes_entrega=true&limite=10",
                auth=self.empleado,
                headers=WEB,
            )["total"],
            1,
        )
        for estado in ["preparando", "listo", "entregado"]:
            p = self.solicitar(
                "GET", f"/pedidos-venta/{self.id}", auth=self.empleado, headers=WEB
            )
            self.assertEqual(p["siguiente_estado_entrega"], estado)
            self.paso(estado)
            self.paso(estado)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(self.solicitar("GET", "/cajas")["total"], 0)
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta?pendientes_entrega=true")["total"], 0
        )
        p = self.solicitar("GET", f"/pedidos-venta/{self.id}")
        for state in ["preparando", "listo", "entregado"]:
            self.assertEqual(
                sum(x["estado"] == state for x in p["historial_entrega"]), 1
            )

    def test_envio_incluye_despacho_y_direccion(self):
        self.preparar("envio")
        self.paso("entregado", 409)
        for estado in ["preparando", "listo", "enviado", "entregado"]:
            self.paso(estado)
        p = self.solicitar("GET", f"/pedidos-venta/{self.id}")
        self.assertEqual(p["direccion_entrega"], "Dirección de prueba 123")
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_sin_pago_no_ofrece_pasos_y_cliente_no_actualiza_entrega(self):
        self.preparar(pagar=False)
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta?pendientes_entrega=true")["total"], 0
        )
        self.paso("preparando", 409)
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{self.id}/entrega",
            403,
            auth=self.ana,
            headers=WEB,
            json={"estado": "preparando"},
        )

    def test_solicitud_se_retoma_recibe_reintegra_y_responde_con_ref_estable(self):
        self.preparar()
        self.entregar()
        c = self.solicitud()
        ref = c["referencia_operacion"]
        ruta = f"/pedidos-venta/{self.id}/devoluciones/{ref}"
        datos = {
            "motivo": c["solicitud"]["motivo"],
            "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
        }
        self.solicitar("PUT", ruta, auth=self.empleado, headers=WEB, json=datos)
        c = self.solicitar("GET", self.base, auth=self.empleado, headers=WEB)
        self.assertEqual(c["acciones"], ["reintegrar"])
        self.assertEqual(c["referencia_operacion"], ref)
        self.solicitar("PUT", ruta, auth=self.empleado, headers=WEB, json=datos)
        self.solicitar(
            "PUT",
            ruta + "/reintegro",
            auth=self.empleado,
            headers=WEB,
            json={"estado": "confirmado"},
        )
        self.assertEqual(
            self.solicitar("GET", self.base, auth=self.empleado)["acciones"],
            ["resolver"],
        )
        response = {
            "estado": "atendida",
            "motivo": "Mouse recibido y reintegro simulado confirmado",
        }
        self.solicitar(
            "PUT",
            self.base + "/resolucion",
            auth=self.empleado,
            headers=WEB,
            json=response,
        )
        self.solicitar(
            "PUT",
            self.base + "/resolucion",
            auth=self.empleado,
            headers=WEB,
            json=response,
        )
        c = self.solicitar("GET", self.base, auth=self.empleado)
        self.assertEqual(c["acciones"], [])
        self.assertEqual(len(c["pedido"]["devoluciones"]["operaciones"]), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        customer = self.solicitar("GET", self.base, auth=self.ana)
        self.assertEqual(customer["resolucion"], response)
        self.assertNotIn("usuario", customer["resolucion"])
        self.assertEqual(
            self.solicitar("GET", "/solicitudes-clientes?estado=pendiente_revision")[
                "total"
            ],
            0,
        )

    def test_cancelacion_solicitada_solo_admin_con_reintegro_y_respuesta(self):
        self.preparar()
        self.solicitud("cancelacion")
        employee = self.solicitar("GET", self.base, auth=self.empleado)
        admin = self.solicitar("GET", self.base)
        self.assertNotIn("cancelar", employee["acciones"])
        self.assertIn("cancelar", admin["acciones"])
        ref = admin["referencia_operacion"]
        ruta = f"/pedidos-venta/{self.id}/cancelaciones/{ref}"
        self.solicitar(
            "PUT", ruta, 403, auth=self.empleado, headers=WEB, json={"motivo": "Prueba"}
        )
        self.solicitar(
            "PUT", ruta, headers=WEB, json={"motivo": admin["solicitud"]["motivo"]}
        )
        self.assertEqual(self.solicitar("GET", self.base)["acciones"], ["reintegrar"])
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta?pendientes_entrega=true")["total"], 0
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_rechazo_explicado_no_mueve_stock_ni_dinero(self):
        self.preparar()
        self.entregar()
        self.solicitud()
        self.solicitar(
            "PUT",
            self.base + "/resolucion",
            headers=WEB,
            json={
                "estado": "rechazada",
                "motivo": "Explicación de prueba para el cliente",
            },
        )
        c = self.solicitar("GET", self.base)
        self.assertEqual(c["solicitud"]["estado"], "rechazada")
        self.assertEqual(c["pedido"]["devoluciones"]["operaciones"], [])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_filtros_por_pedido_y_estado_y_lectura_no_modifican_registros(self):
        self.preparar()
        self.entregar()
        self.solicitud()
        before = self.solicitar("GET", f"/auditoria/comercial/venta/{self.id}")["total"]
        r = self.solicitar(
            "GET",
            f"/solicitudes-clientes?pedido_id={self.id}&estado=pendiente_revision&pagina=1&limite=10",
            auth=self.empleado,
            headers=WEB,
        )
        self.assertEqual(r["total"], 1)
        self.solicitar("GET", self.base, auth=self.empleado, headers=WEB)
        self.assertEqual(
            self.solicitar("GET", "/solicitudes-clientes?estado=atendida")["total"], 0
        )
        self.assertEqual(
            self.solicitar("GET", f"/auditoria/comercial/venta/{self.id}")["total"],
            before,
        )

    def test_otro_cliente_no_ve_ni_responde_solicitud(self):
        self.preparar()
        self.entregar()
        self.solicitud()
        self.solicitar("GET", self.base, 404, auth=self.consulta, headers=WEB)
        self.solicitar(
            "PUT",
            self.base + "/resolucion",
            403,
            auth=self.ana,
            headers=WEB,
            json={"estado": "atendida", "motivo": "No autorizado"},
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
