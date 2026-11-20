"""Regression tests: menu abastecimiento."""

from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import test_menu_pedidos_cliente
import repositorio_sqlite
import menu_abastecimiento as menu


class Abastecimiento(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    sesion = test_menu_pedidos_cliente.PedidosCliente.sesion

    def preparar(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={"usuario": "operador", "rol": "empleado", "clave": "PruebaSegura123"},
        )
        self.empleado = ("operador", "PruebaSegura123")
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                "INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos) VALUES (1,'demo','0012',3,120000)"
            )
        return 1

    def test_recibir_seleccionando_pedido_y_precio_en_pesos(self):
        self.preparar()
        with patch(
            "builtins.input",
            side_effect=["1", "2", "remito-1", "1", "1200,50", "s", "3", "0", "0"],
        ), patch("builtins.print"):
            menu.pedidos(self.sesion(self.empleado))
        c = self.solicitar("GET", "/abastecimiento/pedidos/1", auth=self.empleado)
        self.assertEqual(c["pedido"]["estado"], "parcial")
        self.assertEqual(c["pedido"]["cantidad_recibida"], 1)
        self.assertNotIn("corregir", c["acciones"])
        self.assertNotIn("cerrar", c["acciones"])
        r = self.solicitar(
            "GET", "/abastecimiento/pedidos/1/remitos", auth=self.empleado
        )
        self.assertEqual(r["remitos"][0]["costo_pagado_centavos"], 120050)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 8)

    def test_admin_corrige_seleccionando_remito(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito-1",
            json={"cantidad": 1, "costo_pagado_centavos": 120000},
        )
        with patch(
            "builtins.input",
            side_effect=["8", "1", "2", "1200", "Cantidad verificada", "s", "0"],
        ), patch("builtins.print"):
            menu.gestionar(self.sesion(self.compras), 1)
        c = self.solicitar("GET", "/abastecimiento/pedidos/1")
        self.assertEqual(c["pedido"]["cantidad_recibida"], 2)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 9)
        h = self.solicitar("GET", "/auditoria/comercial/pedido_proveedor/1")[
            "movimientos"
        ]
        self.assertEqual(sum(x["accion"] == "recepcion_corregida" for x in h), 1)

    def test_empleado_no_cancela_cierra_ni_corrige_por_api(self):
        self.preparar()
        c = self.solicitar("GET", "/abastecimiento/pedidos/1", auth=self.empleado)
        self.assertNotIn("cancelar", c["acciones"])
        self.solicitar("PUT", "/pedidos/1/cancelacion", 403, auth=self.empleado)
        self.solicitar("PUT", "/pedidos/1/cierre-incompleto", 403, auth=self.empleado)
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/r/correcciones/c",
            403,
            auth=self.empleado,
            json={"cantidad": 1, "costo_pagado_centavos": 120000, "motivo": "Prueba"},
        )

    def test_cerrado_sin_acciones_de_escritura(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito",
            json={"cantidad": 3, "costo_pagado_centavos": 120000},
        )
        c = self.solicitar("GET", "/abastecimiento/pedidos/1")
        self.assertEqual(c["acciones"], ["remitos", "avisos", "historial"])
        with patch("builtins.input", side_effect=["3", "4", "5", "0"]), patch(
            "builtins.print"
        ):
            menu.gestionar(self.sesion(self.empleado), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)

    def test_reintento_mismo_remito_no_duplica_stock(self):
        self.preparar()
        for _ in range(2):
            with patch(
                "builtins.input",
                side_effect=["2", "remito-repetido", "1", "1200", "s", "0"],
            ), patch("builtins.print"):
                menu.gestionar(self.sesion(self.empleado), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 8)
        self.assertEqual(
            self.solicitar("GET", "/abastecimiento/pedidos/1/remitos")["total"], 1
        )

    def test_proveedor_y_cliente_no_acceden_al_personal(self):
        self.preparar()
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
        for auth in [self.consulta, ("proveedor_a", "PruebaSegura123")]:
            for ruta in [
                "/abastecimiento/pedidos",
                "/abastecimiento/pedidos/1",
                "/abastecimiento/pedidos/1/remitos",
                "/abastecimiento/pedidos/1/avisos",
            ]:
                self.solicitar("GET", ruta, 403, auth=auth)
        self.solicitar("GET", "/abastecimiento/pedidos/999", 404, auth=self.empleado)
        self.solicitar(
            "GET", "/abastecimiento/pedidos/999/remitos", 404, auth=self.empleado
        )

    def test_admin_cierre_parcial_sin_ingresar_lo_faltante(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito",
            json={"cantidad": 1, "costo_pagado_centavos": 120000},
        )
        with patch("builtins.input", side_effect=["7", "s", "0"]), patch(
            "builtins.print"
        ):
            menu.gestionar(self.sesion(self.compras), 1)
        self.assertEqual(
            self.solicitar("GET", "/abastecimiento/pedidos/1")["pedido"]["estado"],
            "cerrado_incompleto",
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 8)
        self.assertEqual(self.solicitar("GET", "/abastecimiento/pedidos")["total"], 0)
        self.assertEqual(
            self.solicitar("GET", "/abastecimiento/pedidos?filtro=todos")["total"], 1
        )

    def test_costos_exactos_y_formatos_invalidos(self):
        with patch(
            "builtins.input", side_effect=["1.200", "-1", "0", "1,234", "1200,05"]
        ), patch("builtins.print"):
            self.assertEqual(menu.pedir_costo(), 120005)
        with patch("builtins.input", return_value="0.01"):
            self.assertEqual(menu.pedir_costo(), 1)

    def test_cancelar_confirmacion_no_modifica_y_pagina_filtrada(self):
        self.preparar()
        with patch("builtins.input", side_effect=["6", "n", "0"]), patch(
            "builtins.print"
        ):
            menu.gestionar(self.sesion(self.compras), 1)
        self.assertEqual(
            self.solicitar("GET", "/abastecimiento/pedidos/1")["pedido"]["estado"],
            "pendiente",
        )
        self.assertEqual(
            self.solicitar("GET", "/abastecimiento/pedidos?pagina=2&limite=1")[
                "pedidos"
            ],
            [],
        )

    def test_respuesta_perdida_reintenta_mismo_remito(self):
        import menu_api

        self.preparar()
        original = menu_api.solicitar_compras
        escrituras = []

        def perder(sesion, metodo, ruta, datos=None):
            resultado = original(sesion, metodo, ruta, datos)
            if metodo == "PUT":
                escrituras.append((ruta, datos))
                if len(escrituras) == 1:
                    return None
            return resultado

        with patch.object(menu_api, "solicitar_compras", side_effect=perder), patch(
            "builtins.input",
            side_effect=["2", "remito-perdido", "1", "1200", "s", "s", "0"],
        ), patch("builtins.print"):
            menu.gestionar(self.sesion(self.empleado), 1)
        self.assertEqual(escrituras[0], escrituras[1])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 8)
        h = self.solicitar("GET", "/auditoria/comercial/pedido_proveedor/1")[
            "movimientos"
        ]
        self.assertEqual(sum(x["accion"] == "mercaderia_recibida" for x in h), 1)
