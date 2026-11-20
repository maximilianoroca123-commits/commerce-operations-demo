"""Regression tests: menu atencion."""

from unittest import TestCase
from unittest.mock import patch
import test_regresion
import test_menu_entregas
import menu_atencion
import menu_navegacion


class Atencion(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    sesion = test_menu_entregas.MenuEntregas.sesion

    def preparar(self, tipo="devolucion"):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "ana",
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
            json={"usuario": "empleado", "rol": "empleado", "clave": "PruebaSegura123"},
        )
        self.ana = ("ana", "PruebaSegura123")
        self.empleado = ("empleado", "PruebaSegura123")
        r = self.solicitar(
            "PUT",
            "/cobros-demo/atencion",
            auth=self.ana,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
            },
        )
        id = r["pedido_venta_id"]
        self.solicitar(
            "PUT",
            "/cobros-demo/atencion/pago",
            auth=self.ana,
            json={"estado": "aprobado"},
        )
        if tipo == "devolucion":
            for estado in ["preparando", "listo", "entregado"]:
                self.solicitar(
                    "PUT",
                    f"/pedidos-venta/{id}/entrega",
                    auth=self.empleado,
                    json={"estado": estado},
                )
        s = self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/solicitudes/sol-1",
            auth=self.ana,
            json={"tipo": tipo, "motivo": "Prueba"},
        )
        self.base = f"/solicitudes-clientes/{id}/sol-1"
        return s

    def test_recorrido_completo_desde_solicitud(self):
        s = self.preparar()

        with patch(
            "builtins.input",
            side_effect=[
                "1",
                "2",
                "1",
                "s",
                "s",
                "1",
                "1",
                "s",
                "1",
                "Producto recibido y reintegro confirmado",
                "s",
                "0",
            ],
        ), patch("builtins.print"):
            menu_atencion.gestionar_solicitudes(self.sesion(self.empleado))
        c = self.solicitar("GET", self.base, auth=self.empleado)
        self.assertEqual(c["solicitud"]["estado"], "atendida")
        self.assertEqual(c["operacion"]["estado_reintegro"], "confirmado")
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        h = self.solicitar("GET", f'/auditoria/comercial/venta/{s["pedido_id"]}')[
            "movimientos"
        ]
        self.assertEqual(sum(x["accion"] == "devolucion_recibida" for x in h), 1)
        self.assertEqual(sum(x["accion"] == "reintegro_actualizado" for x in h), 1)
        cliente = self.solicitar("GET", self.base, auth=self.ana)
        self.assertIn("reintegro confirmado", cliente["resolucion"]["motivo"])
        self.assertNotIn("usuario", cliente["resolucion"])

    def test_salir_y_retomar_sin_repetir_recepcion(self):
        s = self.preparar()
        with patch("builtins.input", side_effect=["2", "1", "s", "s", "0"]), patch(
            "builtins.print"
        ):
            menu_atencion.atender(self.sesion(self.empleado), s)
        c = self.solicitar("GET", self.base, auth=self.empleado)
        self.assertEqual(c["acciones"], ["reintegrar"])
        ref = c["referencia_operacion"]
        with patch("builtins.input", side_effect=["1", "1", "s", "0"]), patch(
            "builtins.print"
        ):
            menu_atencion.atender(self.sesion(self.empleado), s)
        c = self.solicitar("GET", self.base, auth=self.empleado)
        self.assertEqual(c["acciones"], ["resolver"])
        self.assertEqual(c["referencia_operacion"], ref)
        self.assertEqual(len(c["pedido"]["devoluciones"]["operaciones"]), 1)

    def test_cancelacion_solo_administrador(self):
        self.preparar("cancelacion")
        self.assertNotIn(
            "cancelar", self.solicitar("GET", self.base, auth=self.empleado)["acciones"]
        )
        self.assertIn("cancelar", self.solicitar("GET", self.base)["acciones"])

    def test_otra_cuenta_no_ve_solicitud(self):
        self.preparar()
        self.solicitar("GET", self.base, 404, auth=self.consulta)
        self.assertEqual(
            self.solicitar(
                "GET",
                "/solicitudes-clientes?estado=pendiente_revision",
                auth=self.consulta,
            )["total"],
            0,
        )

    def test_rechazar_sin_movimientos(self):
        s = self.preparar()
        with patch(
            "builtins.input", side_effect=["1", "No corresponde", "s", "0"]
        ), patch("builtins.print"):
            menu_atencion.atender(self.sesion(self.empleado), s)
        c = self.solicitar("GET", self.base, auth=self.empleado)
        self.assertEqual(c["acciones"], [])
        self.assertEqual(c["solicitud"]["estado"], "rechazada")
        self.assertEqual(c["pedido"]["devoluciones"]["operaciones"], [])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            self.solicitar("GET", "/solicitudes-clientes?estado=pendiente_revision")[
                "total"
            ],
            0,
        )

    def test_sector_oculta_acciones_sin_permisos(self):
        with patch("builtins.input", side_effect=["1", "0", "0"]), patch(
            "builtins.print"
        ) as salida:
            self.assertEqual(
                menu_navegacion.elegir_sector(
                    [("Cuenta", ["31"]), ("Ventas", ["12"])],
                    {"31": "Crear cuenta", "12": "Ver ventas"},
                    ["12"],
                ),
                "0",
            )
        texto = str(salida.call_args_list)
        self.assertNotIn("Crear cuenta", texto)
        self.assertIn("Ver ventas", texto)

    def test_sector_se_conserva_entre_acciones(self):
        estado = {}
        with patch("builtins.input", side_effect=["1", "12", "12", "0", "0"]), patch(
            "builtins.print"
        ):
            for _ in range(2):
                self.assertEqual(
                    menu_navegacion.elegir_sector(
                        [("Ventas", ["12"])],
                        {"12": "Ver ventas"},
                        ["12"],
                        estado=estado,
                    ),
                    "12",
                )
            self.assertEqual(
                menu_navegacion.elegir_sector(
                    [("Ventas", ["12"])], {"12": "Ver ventas"}, ["12"], estado=estado
                ),
                "0",
            )
