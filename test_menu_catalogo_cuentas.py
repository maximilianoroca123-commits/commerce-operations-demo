"""Regression tests: menu catalogo cuentas."""

from unittest import TestCase
from unittest.mock import patch
import test_regresion
import test_menu_pedidos_cliente
import menu_catalogo_cuentas as menu
import menu_api


class CatalogoCuentas(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    sesion = test_menu_pedidos_cliente.PedidosCliente.sesion

    def alta(self, nombre, rol="empleado"):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={"usuario": nombre, "rol": rol, "clave": "PruebaSegura123"},
        )
        return (nombre, "PruebaSegura123")

    def test_editar_producto_sin_repetir_id(self):
        with patch(
            "builtins.input",
            side_effect=["1", "2", "precio", "9000", "s", "1", "0", "0"],
        ), patch("builtins.print"):
            menu.productos(self.sesion(self.compras), texto="Mouse")
        self.assertEqual(self.solicitar("GET", "/productos/1")["precio"], 9000)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_ajuste_stock_con_motivo_y_contexto(self):
        with patch(
            "builtins.input",
            side_effect=["2", "stock", "8", "Conteo físico de prueba", "s", "3", "0"],
        ), patch("builtins.print"):
            menu.producto(self.sesion(self.compras), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 8)
        movimientos = self.solicitar("GET", "/inventario/movimientos?producto_id=1")[
            "movimientos"
        ]
        self.assertIn("Conteo físico de prueba", str(movimientos))

    def test_empleado_consulta_sin_editar_ni_ver_regla_privada(self):
        auth = self.alta("operador")
        c = self.solicitar("GET", "/operaciones/productos/1", auth=auth)
        self.assertEqual(c["acciones"], ["detalle", "movimientos"])
        self.assertIsNone(c["regla"])
        with patch("builtins.input", side_effect=["1", "3", "0"]), patch(
            "builtins.print"
        ) as salida:
            menu.producto(self.sesion(auth), 1)
        self.assertNotIn("Editar marca", str(salida.call_args_list))
        self.solicitar("PATCH", "/productos/1", 403, auth=auth, json={"precio": 100})

    def test_cancelar_edicion_y_evaluacion_no_modifica(self):
        with patch(
            "builtins.input", side_effect=["2", "precio", "9000", "n", "6", "n", "0"]
        ), patch("builtins.print"):
            menu.producto(self.sesion(self.compras), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["precio"], 8500)
        self.assertEqual(self.solicitar("GET", "/pedidos"), [])

    def test_regla_contextual_reutiliza_formulario(self):
        with patch("builtins.input", side_effect=["5", "0"]), patch(
            "builtins.print"
        ), patch.object(menu_api, "configurar_regla_reposicion") as configurar:
            menu.producto(self.sesion(self.compras), 1)
        configurar.assert_called_once()
        self.assertEqual(configurar.call_args.kwargs, {"id": 1})

    def test_activar_desactivar_seleccionando_una_cuenta(self):
        self.alta("operador")
        with patch(
            "builtins.input", side_effect=["1", "3", "s", "4", "s", "2", "0", "0"]
        ), patch("builtins.print"):
            menu.cuentas(self.sesion(self.compras))
        c = self.solicitar("GET", "/usuarios/operador")
        self.assertEqual(c["cuenta"]["activo"], 1)
        h = self.solicitar("GET", "/auditoria/cuentas?usuario=operador")["movimientos"]
        self.assertEqual(sum(x["accion"] == "cuenta_desactivada" for x in h), 1)
        self.assertEqual(sum(x["accion"] == "cuenta_activada" for x in h), 1)

    def test_restablecer_desde_cuenta_con_referencia_automatica(self):
        auth = self.alta("operador")
        with patch(
            "builtins.input", side_effect=["5", "Prueba de recuperación", "s", "0"]
        ), patch("menu_cuentas.getpass", return_value="TemporalSegura456"), patch(
            "builtins.print"
        ):
            menu.cuenta(self.sesion(self.compras), "operador")
        c = self.solicitar("GET", "/usuarios/operador")
        self.assertEqual(c["cuenta"]["debe_cambiar_clave"], 1)
        self.solicitar("GET", "/sesion", 401, auth=auth)
        self.assertTrue(
            self.solicitar("GET", "/sesion", auth=("operador", "TemporalSegura456"))[
                "debe_cambiar_clave"
            ]
        )
        self.assertNotIn("clave_hash", str(c))
        self.assertNotIn("TemporalSegura456", str(c))

    def test_cuenta_propia_y_ultimo_administrador_protegidos(self):
        admin = self.alta("jefe", "administrador")
        propia = self.solicitar("GET", "/usuarios/jefe", auth=admin)
        self.assertEqual(propia["acciones"], ["detalle", "historial"])
        otra = self.solicitar("GET", "/usuarios/jefe")
        self.assertNotIn("desactivar", otra["acciones"])
        self.solicitar("PUT", "/usuarios/jefe/estado", 409, json={"activo": False})

    def test_cuenta_y_producto_respetan_accesos(self):
        auth = self.alta("operador")
        self.solicitar("GET", "/usuarios/operador", 403, auth=auth)
        self.solicitar("GET", "/usuarios/operador", 403, auth=self.consulta)
        self.solicitar("GET", "/operaciones/productos/1", 403, auth=self.consulta)
        self.solicitar("GET", "/usuarios/inexistente", 404)
        self.solicitar("GET", "/operaciones/productos/999", 404)

    def test_cuenta_inactiva_no_ofrece_restablecer(self):
        self.alta("operador")
        self.solicitar("PUT", "/usuarios/operador/estado", json={"activo": False})
        c = self.solicitar("GET", "/usuarios/operador")
        self.assertIn("activar", c["acciones"])
        self.assertNotIn("restablecer", c["acciones"])

    def test_reintento_restablecimiento_no_duplica_auditoria(self):
        import menu_cuentas

        self.alta("operador")
        original = menu_cuentas.api
        intentos = []

        def perder(sesion, metodo, ruta, datos=None):
            r = original(sesion, metodo, ruta, datos)
            if metodo == "PUT" and "/restablecimientos/" in ruta:
                intentos.append(ruta)
                if len(intentos) == 1:
                    return None
            return r

        with patch.object(menu_cuentas, "api", side_effect=perder), patch(
            "builtins.input", side_effect=["5", "Prueba de recuperación", "s", "s", "0"]
        ), patch("menu_cuentas.getpass", return_value="TemporalSegura456"), patch(
            "builtins.print"
        ):
            menu.cuenta(self.sesion(self.compras), "operador")
        self.assertEqual(intentos[0], intentos[1])
        h = self.solicitar("GET", "/auditoria/cuentas?usuario=operador")["movimientos"]
        self.assertEqual(sum(x["accion"] == "clave_restablecida" for x in h), 1)
