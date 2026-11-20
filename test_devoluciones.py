"""Regression tests: devoluciones."""

from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
import preparar_db_api
import test_regresion


class Devoluciones(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def vender(self, cantidad=3):
        return self.solicitar(
            "PUT",
            "/ventas/venta",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": cantidad},
        )["pedido_venta_id"]

    def stock(self):
        return self.solicitar("GET", "/productos/1")["stock"]

    def devolver(
        self, pedido, ref="dev1", cantidad=1, reponer=True, codigo=200, **kwargs
    ):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{pedido}/devoluciones/{ref}",
            codigo,
            json={
                "motivo": "Prueba",
                "productos": [
                    {"producto_id": 1, "cantidad": cantidad, "reponer": reponer}
                ],
            },
            **kwargs,
        )

    def reintegrar(self, pedido, ref="dev1", estado="confirmado", codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{pedido}/devoluciones/{ref}/reintegro",
            codigo,
            json={"estado": estado},
        )

    def online(self, modalidad="retiro"):
        id = self.solicitar(
            "PUT",
            "/cobros-demo/online",
            auth=self.consulta,
            json={
                "productos": [{"producto_id": 1, "cantidad": 2}],
                "canal": "online",
                "modalidad": modalidad,
            },
        )["pedido_venta_id"]
        self.solicitar(
            "PUT",
            "/cobros-demo/online/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        return id

    def cancelar(self, id, codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/cancelaciones/cancelar",
            codigo,
            json={"motivo": "Cliente desistió"},
        )

    def test_parcial_total_danado_y_precio_original(self):
        id = self.vender()
        self.solicitar("PATCH", "/productos/1", json={"precio": 9999})
        r = self.devolver(id)
        self.assertEqual(self.stock(), 5)
        self.assertEqual(r["importe_por_reintegrar"], 8500)
        self.assertEqual(self.devolver(id), r)
        self.assertEqual(self.stock(), 5)
        self.devolver(id, cantidad=2, codigo=409)
        r = self.devolver(id, "dev2", cantidad=2, reponer=False)
        self.assertEqual(self.stock(), 5)
        self.assertEqual(r["importe_devoluciones"], 25500)
        self.devolver(id, "dev3", codigo=409)
        self.assertEqual(self.stock(), 5)

    def test_reintegro_fallido_reintento_y_repetido(self):
        id = self.vender()
        self.devolver(id)
        self.assertEqual(
            self.reintegrar(id, estado="fallido")["importe_por_reintegrar"], 8500
        )
        r = self.reintegrar(id)
        self.assertEqual(r["importe_reintegrado"], 8500)
        self.assertEqual(r["importe_por_reintegrar"], 0)
        self.assertEqual(self.reintegrar(id), r)
        self.reintegrar(id, estado="fallido", codigo=409)
        self.assertEqual(self.stock(), 5)

    def test_cancelacion_online_no_se_reabre_por_pago_o_migracion(self):
        id = self.online()
        r = self.cancelar(id)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.cancelar(id), r)
        self.assertEqual(self.stock(), 7)
        self.solicitar(
            "PUT",
            "/cobros-demo/online/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        preparar_db_api.preparar_db_api()
        pedido = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertEqual(pedido["estado_entrega"], "cancelado")
        self.assertEqual(pedido["devoluciones"]["importe_por_reintegrar"], 17000)
        self.assertEqual(
            self.solicitar("GET", "/productos/1/disponibilidad")[
                "vendido_pendiente_entrega"
            ],
            0,
        )
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/entrega", 409, json={"estado": "preparando"}
        )
        self.reintegrar(id, "cancelar")
        self.assertEqual(self.stock(), 7)

    def test_despachado_requiere_recepcion_y_no_cancelacion(self):
        id = self.online("envio")
        for estado in ("preparando", "listo", "enviado"):
            self.solicitar(
                "PUT", f"/pedidos-venta/{id}/entrega", json={"estado": estado}
            )
        self.cancelar(id, 409)
        self.devolver(id, codigo=409)
        self.assertEqual(self.stock(), 5)
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/entrega", json={"estado": "entregado"}
        )
        self.devolver(id, cantidad=2)
        self.assertEqual(self.stock(), 7)

    def test_permisos_validacion_y_operacion_sin_venta(self):
        id = self.vender()
        self.devolver(id, codigo=403, auth=self.consulta)
        self.devolver(id, cantidad=0, codigo=422)
        self.devolver(999, codigo=404)
        self.reintegrar(id, codigo=409)
        self.cancelar(id, 409)
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/ajeno",
            409,
            json={
                "motivo": "Prueba",
                "productos": [{"producto_id": 2, "cantidad": 1, "reponer": True}],
            },
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/duplicado",
            409,
            json={
                "motivo": "Prueba",
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}] * 2,
            },
        )
        self.assertEqual(self.stock(), 4)

    def test_concurrencia_impide_devolver_mas_de_lo_vendido(self):
        id = self.vender(1)

        def enviar(ref):
            return self.cliente.put(
                f"/pedidos-venta/{id}/devoluciones/{ref}",
                auth=self.compras,
                json={
                    "motivo": "Prueba",
                    "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
                },
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            resultados = list(ejecutor.map(enviar, ["a", "b"]))
        self.assertEqual(sorted(resultados), [200, 409])
        self.assertEqual(self.stock(), 7)

    def test_ticket_y_historial_conservan_venta_original(self):
        id = self.vender()
        self.devolver(id)
        self.reintegrar(id)
        respuesta = self.cliente.get(f"/pedidos-venta/{id}/ticket", auth=self.compras)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("25.500,00", respuesta.text)
        self.assertIn("Dinero reintegrado: $ 8.500,00", respuesta.text)
        self.assertEqual(self.solicitar("GET", "/ventas")["pedidos"][0]["total"], 25500)

    def test_pendiente_rechazado_y_carrito_completo_se_validan_antes_de_reponer(self):
        id = self.solicitar(
            "PUT",
            "/cobros-demo/sin-pagar",
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 1}]},
        )["pedido_venta_id"]
        self.devolver(id, codigo=409)
        self.cancelar(id, 409)
        self.solicitar(
            "PUT",
            "/cobros-demo/sin-pagar/pago",
            auth=self.consulta,
            json={"estado": "rechazado"},
        )
        self.devolver(id, codigo=409)
        id = self.vender()
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/invalida",
            409,
            json={
                "motivo": "Prueba",
                "productos": [
                    {"producto_id": 1, "cantidad": 1, "reponer": True},
                    {"producto_id": 2, "cantidad": 1, "reponer": True},
                ],
            },
        )
        self.assertEqual(self.stock(), 4)
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}")["devoluciones"][
                "operaciones"
            ],
            [],
        )

    def test_devolucion_multilinea_y_reintento_concurrente_misma_referencia(self):
        id = self.solicitar(
            "PUT",
            "/cobros-demo/carrito",
            auth=self.consulta,
            json={
                "productos": [
                    {"producto_id": 1, "cantidad": 2},
                    {"producto_id": 2, "cantidad": 1},
                ]
            },
        )["pedido_venta_id"]
        self.solicitar(
            "PUT",
            "/cobros-demo/carrito/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        datos = {
            "motivo": "Regreso completo",
            "productos": [
                {"producto_id": 1, "cantidad": 2, "reponer": True},
                {"producto_id": 2, "cantidad": 1, "reponer": False},
            ],
        }

        def enviar(_):
            return self.cliente.put(
                f"/pedidos-venta/{id}/devoluciones/total", auth=self.compras, json=datos
            )

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            respuestas = list(ejecutor.map(enviar, [1, 2]))
        self.assertEqual([x.status_code for x in respuestas], [200, 200])
        self.assertEqual(respuestas[0].json(), respuestas[1].json())
        self.assertEqual(respuestas[0].json()["estado_comercial"], "devuelta")
        self.assertEqual(respuestas[0].json()["importe_por_reintegrar"], 24500)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(self.solicitar("GET", "/productos/2")["stock"], 4)

    def test_menu_devolucion_y_reintegro(self):
        from unittest.mock import patch
        import menu_api

        id = self.vender()
        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **kwargs):
                return cliente.request(metodo, url, auth=auth, **kwargs)

        with patch(
            "builtins.input",
            side_effect=[str(id), "menu-dev", "Prueba", "1", "1", "s", "s"],
        ), patch("builtins.print"):
            menu_api.gestionar_devolucion(Sesion())
        self.assertEqual(self.stock(), 5)
        with patch(
            "builtins.input", side_effect=[str(id), "menu-dev", "1", "s"]
        ), patch("builtins.print"):
            menu_api.simular_reintegro(Sesion())
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}")["devoluciones"][
                "importe_reintegrado"
            ],
            8500,
        )
