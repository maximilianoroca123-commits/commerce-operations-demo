"""Regression tests: menu entregas."""

from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import repositorio_sqlite
import menu_api


class MenuEntregas(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def empleado(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={"usuario": "operador", "rol": "empleado", "clave": "PruebaSegura123"},
        )
        return ("operador", "PruebaSegura123")

    def pedido(self, ref="entrega", modalidad="retiro", pagar=True):
        r = self.solicitar(
            "PUT",
            "/cobros-demo/" + ref,
            auth=self.consulta,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": modalidad,
            },
        )
        if pagar:
            self.solicitar(
                "PUT",
                "/cobros-demo/" + ref + "/pago",
                auth=self.consulta,
                json={"estado": "aprobado"},
            )
        return r["pedido_venta_id"]

    def sesion(self, auth):
        cliente = self.cliente

        class Sesion:
            def __init__(self):
                self.llamadas = []

            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                self.llamadas.append((metodo, url, datos))
                return cliente.request(metodo, url, auth=auth, **datos)

        return Sesion()

    def test_retiro_completo_desde_menu_no_vuelve_a_cobrar_ni_descontar(self):
        empleado = self.empleado()
        id = self.pedido()
        sesion = self.sesion(empleado)
        with patch(
            "builtins.input", side_effect=["1", str(id), "s", "s", "s", "s", "s"]
        ), patch("builtins.print") as salida:
            menu_api.gestionar_entregas(sesion)
        detalle = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertEqual(detalle["estado_entrega"], "entregado")
        self.assertIsNone(detalle["siguiente_estado_entrega"])
        self.assertEqual(detalle["total"], 8500)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            [x[2]["json"]["estado"] for x in sesion.llamadas if x[0] == "PUT"],
            ["preparando", "listo", "entregado"],
        )
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM movimientos_caja").fetchone()[0], 0
            )
        self.assertIn(
            "cliente ya recibió", " ".join(str(x) for x in salida.call_args_list)
        )

    def test_envio_incluye_despacho_y_no_permite_saltar(self):
        id = self.pedido(modalidad="envio")
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/entrega", 409, json={"estado": "entregado"}
        )
        estados = []
        while True:
            d = self.solicitar("GET", f"/pedidos-venta/{id}")
            siguiente = d["siguiente_estado_entrega"]
            if not siguiente:
                break
            estados.append(siguiente)
            self.solicitar(
                "PUT", f"/pedidos-venta/{id}/entrega", json={"estado": siguiente}
            )
        self.assertEqual(estados, ["preparando", "listo", "enviado", "entregado"])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_cancelar_confirmacion_no_envia_actualizacion(self):
        sesion = self.sesion(self.empleado())
        id = self.pedido()
        with patch("builtins.input", side_effect=["1", str(id), "n"]), patch(
            "builtins.print"
        ):
            menu_api.gestionar_entregas(sesion)
        self.assertFalse(any(x[0] == "PUT" for x in sesion.llamadas))
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}")["estado_entrega"], "pendiente"
        )

    def test_sin_pendientes_no_pide_datos(self):
        self.pedido(pagar=False)
        with patch("builtins.input") as entrada, patch("builtins.print") as salida:
            menu_api.gestionar_entregas(self.sesion(self.compras))
        entrada.assert_not_called()
        self.assertIn(
            "No hay pedidos pagados", " ".join(str(x) for x in salida.call_args_list)
        )

    def test_pedido_cancelado_no_ofrece_siguiente_paso(self):
        id = self.pedido()
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/cancelaciones/cancelar",
            json={"motivo": "Prueba"},
        )
        d = self.solicitar("GET", f"/pedidos-venta/{id}")
        self.assertIsNone(d["siguiente_estado_entrega"])
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta?pendientes_entrega=true")["total"], 0
        )

    def test_filtro_aplicado_antes_de_paginar_y_conserva_titular(self):
        a = self.pedido("uno")
        b = self.pedido("dos")
        self.pedido("sinpago", pagar=False)
        for e in ["preparando", "listo", "entregado"]:
            self.solicitar("PUT", f"/pedidos-venta/{a}/entrega", json={"estado": e})
        r = self.solicitar(
            "GET", "/pedidos-venta?pendientes_entrega=true&limite=1", auth=self.consulta
        )
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["pedidos"][0]["id"], b)
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "cliente_dos",
                "rol": "cliente",
                "clave": "PruebaSegura123",
                "cliente": {
                    "nombre": "Otra",
                    "apellido": "Persona",
                    "correo": "otra@example.com",
                },
            },
        )
        self.assertEqual(
            self.solicitar(
                "GET",
                "/pedidos-venta?pendientes_entrega=true",
                auth=("cliente_dos", "PruebaSegura123"),
            )["total"],
            0,
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{b}/entrega",
            403,
            auth=self.consulta,
            json={"estado": "preparando"},
        )

    def test_empleado_recibe_opcion_38_y_menu_la_muestra(self):
        datos = self.solicitar("GET", "/sesion", auth=self.empleado())
        self.assertIn("38", datos["opciones_operativas"])
        with patch("builtins.input", side_effect=["3", "0", "0"]), patch(
            "builtins.print"
        ) as salida:
            menu_api.ejecutar_menu(None, "empleado", datos["opciones_operativas"])
        texto = " ".join(str(x) for x in salida.call_args_list)
        self.assertIn("38. Preparar, despachar o entregar", texto)
        self.assertIn("Entregas", texto)
        self.assertNotIn("31. Crear", texto)
