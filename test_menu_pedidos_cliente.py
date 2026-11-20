"""Regression tests: menu pedidos cliente."""

from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import test_regresion
import menu_pedidos_cliente
import menu_cuentas
import menu_api


class PedidosCliente(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def cuenta(self, nombre):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": nombre,
                "rol": "cliente",
                "clave": "PruebaSegura123",
                "cliente": {
                    "nombre": nombre,
                    "apellido": "Prueba",
                    "correo": nombre + "@example.com",
                },
            },
        )
        return (nombre, "PruebaSegura123")

    def pedido(self, auth, ref="cliente", entregado=False):
        r = self.solicitar(
            "PUT",
            "/cobros-demo/" + ref,
            auth=auth,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
            },
        )
        id = r["pedido_venta_id"]
        if entregado:
            self.solicitar(
                "PUT",
                "/cobros-demo/" + ref + "/pago",
                auth=auth,
                json={"estado": "aprobado"},
            )
            for estado in ["preparando", "listo", "entregado"]:
                self.solicitar(
                    "PUT", f"/pedidos-venta/{id}/entrega", json={"estado": estado}
                )
        return id

    def sesion(self, auth):
        cliente = self.cliente

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

            def get(self, url, **datos):
                return self.request("GET", url, **datos)

        return Sesion()

    def test_pagar_seleccionando_sin_reescribir_referencia(self):
        auth = self.cuenta("ana")
        id = self.pedido(auth)
        self.assertNotIn(
            "comprobante",
            self.solicitar("GET", f"/pedidos-venta/{id}", auth=auth)[
                "acciones_cliente"
            ],
        )
        with patch("builtins.input", side_effect=["1", "2", "1", "0", "0"]), patch(
            "builtins.print"
        ):
            menu_pedidos_cliente.mis_pedidos(self.sesion(auth))
        d = self.solicitar("GET", f"/pedidos-venta/{id}", auth=auth)
        self.assertEqual(d["estado_pago"], "aprobado")
        self.assertNotIn("pagar", d["acciones_cliente"])
        self.assertIn("cancelacion", d["acciones_cliente"])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_solicitar_devolucion_con_id_conservado(self):
        auth = self.cuenta("ana")
        id = self.pedido(auth, entregado=True)
        with patch(
            "builtins.input", side_effect=["4", "s", "Producto de prueba", "0"]
        ), patch("builtins.print"):
            menu_pedidos_cliente.gestionar_pedido(self.sesion(auth), id)
        r = self.solicitar("GET", f"/solicitudes-clientes?pedido_id={id}", auth=auth)
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["solicitudes"][0]["tipo"], "devolucion")
        self.assertEqual(r["solicitudes"][0]["motivo"], "Producto de prueba")
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

        with patch("builtins.input", side_effect=["4", "0"]), patch("builtins.print"):
            menu_pedidos_cliente.gestionar_pedido(self.sesion(auth), id)
        self.assertEqual(
            self.solicitar("GET", f"/solicitudes-clientes?pedido_id={id}", auth=auth)[
                "total"
            ],
            1,
        )

    def test_comprobante_no_pide_id_y_respeta_titular(self):
        auth = self.cuenta("ana")
        id = self.pedido(auth, entregado=True)
        with TemporaryDirectory() as t:
            with patch.object(
                menu_api, "__file__", str(Path(t) / "menu_api.py")
            ), patch("builtins.input", side_effect=["3", "0"]), patch("builtins.print"):
                menu_pedidos_cliente.gestionar_pedido(self.sesion(auth), id)
            self.assertTrue((Path(t) / "tickets" / f"venta-{id}.html").is_file())
        otro = self.cuenta("bruno")
        self.solicitar("GET", f"/pedidos-venta/{id}", 404, auth=otro)
        self.assertEqual(
            self.solicitar("GET", f"/solicitudes-clientes?pedido_id={id}", auth=otro)[
                "total"
            ],
            0,
        )

    def test_respuestas_debajo_de_cada_solicitud_y_filtradas(self):
        auth = self.cuenta("ana")
        a = self.pedido(auth, "primero", True)
        b = self.pedido(auth, "segundo", True)
        for id, motivo in [(a, "Respuesta al primero"), (b, "Respuesta al segundo")]:
            self.solicitar(
                "PUT",
                f"/pedidos-venta/{id}/solicitudes/sol",
                auth=auth,
                json={"tipo": "devolucion", "motivo": "Prueba"},
            )
            self.solicitar(
                "PUT",
                f"/solicitudes-clientes/{id}/sol/resolucion",
                json={"estado": "rechazada", "motivo": motivo},
            )
        with patch("builtins.print") as salida:
            menu_cuentas.ver_solicitudes(self.sesion(auth))
        lineas = [x.args[0] for x in salida.call_args_list]
        for id, respuesta in [(a, "Respuesta al primero"), (b, "Respuesta al segundo")]:
            n = next(
                n
                for n, linea in enumerate(lineas)
                if linea.startswith(f"Pedido {id} |")
            )
            self.assertIn(respuesta, lineas[n + 1])
        r = self.solicitar("GET", f"/solicitudes-clientes?pedido_id={a}", auth=auth)
        self.assertEqual(r["total"], 1)
        self.assertEqual(
            r["solicitudes"][0]["resolucion"]["motivo"], "Respuesta al primero"
        )
        self.assertNotIn("usuario", r["solicitudes"][0]["resolucion"])

    def test_pedido_devuelto_no_ofrece_otra_devolucion(self):
        auth = self.cuenta("ana")
        id = self.pedido(auth, entregado=True)
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/dev",
            json={
                "motivo": "Prueba",
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
            },
        )
        self.assertNotIn(
            "devolucion",
            self.solicitar("GET", f"/pedidos-venta/{id}", auth=auth)[
                "acciones_cliente"
            ],
        )

    def test_sin_pedidos_no_solicita_identificadores(self):
        auth = self.cuenta("ana")
        with patch("builtins.input") as entrada, patch("builtins.print"):
            menu_pedidos_cliente.mis_pedidos(self.sesion(auth))
        entrada.assert_not_called()

    def test_paginacion_y_eleccion_solo_de_la_pagina(self):
        paginas = {
            1: {
                "pedidos": [
                    {
                        "id": 11,
                        "total": 10,
                        "estado_pago": "pendiente",
                        "estado_entrega": "pendiente",
                    }
                ],
                "total": 11,
            },
            2: {
                "pedidos": [
                    {
                        "id": 22,
                        "total": 10,
                        "estado_pago": "pendiente",
                        "estado_entrega": "pendiente",
                    }
                ],
                "total": 11,
            },
        }

        def consultar(sesion, metodo, ruta):
            return paginas[2 if "pagina=2" in ruta else 1]

        with patch.object(
            menu_pedidos_cliente, "api", side_effect=consultar
        ), patch.object(menu_pedidos_cliente, "gestionar_pedido") as abrir, patch(
            "builtins.input", side_effect=["s", "22", "1", "0"]
        ), patch(
            "builtins.print"
        ):
            menu_pedidos_cliente.mis_pedidos(None)
        abrir.assert_called_once_with(None, 22)
