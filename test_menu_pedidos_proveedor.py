"""Regression tests: menu pedidos proveedor."""

from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import test_menu_pedidos_cliente
import repositorio_sqlite
import menu_pedidos_proveedor as menu


class Proveedor(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    importar_oferta = test_regresion.RegresionInventario.importar_oferta
    sesion = test_menu_pedidos_cliente.PedidosCliente.sesion

    def preparar(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "proveedor_a",
                "rol": "proveedor",
                "proveedor": "demo",
                "clave": "PruebaSegura123",
            },
        )
        self.proveedor = ("proveedor_a", "PruebaSegura123")
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.executemany(
                "INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos) VALUES (1,?,?,2,120000)",
                [("demo", "0012"), ("demo-b", "0012")],
            )
        return 1

    def test_menu_informa_y_consulta_sin_pedir_id(self):
        id = self.preparar()
        with patch(
            "builtins.input",
            side_effect=["1", "3", "2", "Sale hoy", "s", "2", "0", "0"],
        ), patch("builtins.print"):
            menu.mis_pedidos(self.sesion(self.proveedor))
        c = self.solicitar("GET", f"/mi-proveedor/pedidos/{id}", auth=self.proveedor)
        self.assertEqual(c["ultimo_aviso"]["estado"], "despachado")
        self.assertEqual(c["pedido"]["cantidad_recibida"], 0)
        self.assertEqual(c["pedido"]["estado"], "pendiente")
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_filtra_antes_de_paginar_y_no_permite_pedido_ajeno(self):
        self.preparar()
        r = self.solicitar("GET", "/mi-proveedor/pedidos?limite=1", auth=self.proveedor)
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["pedidos"][0]["id"], 1)
        self.assertEqual(
            self.solicitar(
                "GET", "/mi-proveedor/pedidos?limite=1&pagina=2", auth=self.proveedor
            )["pedidos"],
            [],
        )
        self.solicitar("GET", "/mi-proveedor/pedidos/2", 404, auth=self.proveedor)
        self.solicitar(
            "GET", "/mi-proveedor/pedidos/2/avisos", 404, auth=self.proveedor
        )
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/2/avisos/ajeno",
            404,
            auth=self.proveedor,
            json={"estado": "despachado", "nota": "Prueba"},
        )

    def test_roles_no_proveedor_y_recepcion_prohibida(self):
        self.preparar()
        for auth in [self.compras, self.consulta]:
            self.solicitar("GET", "/mi-proveedor/pedidos", 403, auth=auth)
            self.solicitar("GET", "/mi-proveedor/pedidos/1", 403, auth=auth)
            self.solicitar("GET", "/mi-proveedor/pedidos/1/avisos", 403, auth=auth)
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito",
            403,
            auth=self.proveedor,
            json={"cantidad": 2, "costo_pagado_centavos": 120000},
        )

    def test_cerrado_solo_consulta_y_reintento_anterior_se_conserva(self):
        self.preparar()
        datos = {"estado": "despachado", "nota": "Sale hoy"}
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/1/avisos/original",
            auth=self.proveedor,
            json=datos,
        )
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito",
            json={"cantidad": 2, "costo_pagado_centavos": 120000},
        )
        c = self.solicitar("GET", "/mi-proveedor/pedidos/1", auth=self.proveedor)
        self.assertEqual(c["acciones_aviso"], [])
        self.assertEqual(
            self.solicitar("GET", "/mi-proveedor/pedidos", auth=self.proveedor)[
                "total"
            ],
            0,
        )
        self.assertEqual(
            self.solicitar(
                "GET", "/mi-proveedor/pedidos?filtro=todos", auth=self.proveedor
            )["total"],
            1,
        )
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/1/avisos/nuevo",
            409,
            auth=self.proveedor,
            json=datos,
        )
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/1/avisos/original",
            auth=self.proveedor,
            json=datos,
        )
        self.assertEqual(
            self.solicitar(
                "GET", "/mi-proveedor/pedidos/1/avisos", auth=self.proveedor
            )["total"],
            1,
        )
        with patch("builtins.input", side_effect=["2", "0"]), patch(
            "builtins.print"
        ) as salida:
            menu.gestionar(self.sesion(self.proveedor), 1)
        self.assertNotIn("3. Informar estado", str(salida.call_args_list))

    def test_reintento_por_respuesta_perdida_misma_referencia(self):
        self.preparar()
        contexto = self.solicitar("GET", "/mi-proveedor/pedidos/1", auth=self.proveedor)
        original = menu.api
        llamadas = []

        def perder(sesion, metodo, ruta, datos=None):
            r = original(sesion, metodo, ruta, datos)
            if metodo == "PUT":
                llamadas.append(ruta)
                if len(llamadas) == 1:
                    return None
            return r

        with patch.object(menu, "api", side_effect=perder), patch(
            "builtins.input", side_effect=["1", "Confirmado para mañana", "s", "s"]
        ), patch("builtins.print"):
            menu.informar(self.sesion(self.proveedor), contexto)
        self.assertEqual(llamadas[0], llamadas[1])
        self.assertEqual(
            self.solicitar(
                "GET", "/mi-proveedor/pedidos/1/avisos", auth=self.proveedor
            )["total"],
            1,
        )
        h = self.solicitar("GET", "/auditoria/comercial/pedido_proveedor/1")[
            "movimientos"
        ]
        self.assertEqual(sum(x["accion"] == "aviso_proveedor_recibido" for x in h), 1)

    def test_no_duplica_ultimo_aviso_igual(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/1/avisos/primero",
            auth=self.proveedor,
            json={"estado": "confirmado", "nota": "Prueba"},
        )
        c = self.solicitar("GET", "/mi-proveedor/pedidos/1", auth=self.proveedor)
        with patch("builtins.input", side_effect=["1", "Prueba"]), patch(
            "builtins.print"
        ), patch.object(menu, "api") as enviar:
            menu.informar(self.sesion(self.proveedor), c)
        enviar.assert_not_called()

    def test_cancelar_confirmacion_no_envia_aviso(self):
        self.preparar()
        c = self.solicitar("GET", "/mi-proveedor/pedidos/1", auth=self.proveedor)
        with patch("builtins.input", side_effect=["2", "Sale mañana", "n"]), patch(
            "builtins.print"
        ), patch.object(menu, "api") as enviar:
            menu.informar(self.sesion(self.proveedor), c)
        enviar.assert_not_called()

    def test_ofertas_legibles_y_listado_de_cerrados(self):
        self.preparar()
        self.importar_oferta("demo", "1200.00")
        with patch("builtins.print") as salida:
            menu.mostrar_ofertas(self.sesion(self.proveedor), "demo")
        self.assertIn("Costo unitario: $1200,00", str(salida.call_args_list))
        self.solicitar("PUT", "/pedidos/1/cancelacion")
        with patch("builtins.input", side_effect=["t", "1", "1", "0", "0"]), patch(
            "builtins.print"
        ):
            menu.mis_pedidos(self.sesion(self.proveedor))

    def test_paginacion_de_avisos(self):
        self.preparar()
        for n in range(3):
            self.solicitar(
                "PUT",
                f"/mi-proveedor/pedidos/1/avisos/aviso-{n}",
                auth=self.proveedor,
                json={"estado": "confirmado", "nota": str(n)},
            )
        a = self.solicitar(
            "GET", "/mi-proveedor/pedidos/1/avisos?limite=2", auth=self.proveedor
        )
        b = self.solicitar(
            "GET",
            "/mi-proveedor/pedidos/1/avisos?limite=2&pagina=2",
            auth=self.proveedor,
        )
        self.assertEqual(a["total"], 3)
        self.assertEqual(len(a["avisos"]), 2)
        self.assertEqual(len(b["avisos"]), 1)
        self.assertFalse(
            {x["referencia"] for x in a["avisos"]}
            & {x["referencia"] for x in b["avisos"]}
        )
