"""Regression tests: tickets."""

import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import test_regresion


class TicketsVenta(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def vender(self, referencia="venta-ticket"):
        return self.solicitar(
            "PUT",
            f"/ventas/{referencia}",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 2},
        )["pedido_venta_id"]

    def ticket(self, pedido, codigo=200):
        r = self.cliente.get(f"/pedidos-venta/{pedido}/ticket", auth=self.compras)
        self.assertEqual(r.status_code, codigo, r.text)
        return r

    def test_listado_incluye_solo_ventas_cobradas_de_ambos_origenes(self):
        self.vender()
        for referencia, canal in (
            ("qr-pendiente", "online"),
            ("qr-cobrado", "online"),
            ("qr-rechazado", "presencial"),
        ):
            self.solicitar(
                "PUT",
                f"/cobros-demo/{referencia}",
                auth=self.consulta,
                json={"productos": [{"producto_id": 2, "cantidad": 1}], "canal": canal},
            )
        self.solicitar(
            "PUT",
            "/cobros-demo/qr-cobrado/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/qr-rechazado/pago",
            auth=self.consulta,
            json={"estado": "rechazado"},
        )
        listado = self.solicitar("GET", "/ventas")
        self.assertEqual(listado["total"], 2)
        self.assertEqual({p["origen"] for p in listado["pedidos"]}, {"directa", "qr"})
        self.assertEqual(self.solicitar("GET", "/ventas?canal=online")["total"], 1)
        self.assertEqual(len(self.solicitar("GET", "/ventas?limite=1")["pedidos"]), 1)
        self.solicitar("GET", "/ventas?pagina=0", 422)
        self.solicitar("GET", "/ventas", 403, auth=self.consulta)

    def test_ticket_conserva_precio_y_stock_despues_de_cambiar_catalogo(self):
        pedido = self.vender()
        antes = self.ticket(pedido).text
        self.solicitar("PATCH", "/productos/1", json={"precio": 9999})
        despues = self.ticket(pedido)
        self.assertEqual(despues.text, antes)
        self.assertIn("text/html", despues.headers["content-type"])
        self.assertIn("$ 8.500,00", despues.text)
        self.assertIn("$ 17.000,00", despues.text)
        self.assertIn("Sin validez fiscal", despues.text)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 5)

    def test_ticket_qr_online_muestra_lineas_y_total(self):
        cobro = self.solicitar(
            "PUT",
            "/cobros-demo/ticket-online",
            auth=self.consulta,
            json={
                "productos": [
                    {"producto_id": 1, "cantidad": 2},
                    {"producto_id": 2, "cantidad": 1},
                ],
                "canal": "online",
                "modalidad": "envio",
            },
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/ticket-online/pago",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        html = self.ticket(cobro["pedido_venta_id"]).text
        for texto in (
            "Mouse",
            "teclado",
            "$ 24.500,00",
            "online",
            "envio",
            "Pendiente",
        ):
            self.assertIn(texto, html)

    def test_ticket_exige_pago_y_credenciales_y_escapa_texto(self):
        pendiente = self.solicitar(
            "PUT",
            "/cobros-demo/pendiente",
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 1}]},
        )["pedido_venta_id"]
        self.ticket(pendiente, 409)
        self.ticket(999, 404)
        self.assertEqual(
            self.cliente.get(f"/pedidos-venta/{pendiente}/ticket").status_code, 401
        )
        r = self.cliente.post(
            "/productos",
            auth=self.compras,
            json={
                "nombre": "<script>prueba</script> & producto",
                "categoria": "tecnologia",
                "precio": 10,
                "stock": 1,
                "marca": "Ejemplo",
            },
        )
        self.assertEqual(r.status_code, 201)
        venta = self.solicitar(
            "PUT",
            "/ventas/escape",
            auth=self.consulta,
            json={"producto_id": r.json()["id"], "cantidad": 1},
        )
        html = self.ticket(venta["pedido_venta_id"]).text
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp; producto", html)

    def test_menu_consulta_detalle_y_guarda_ticket(self):
        import menu_api

        pedido = self.vender()
        cliente = self.cliente
        auth = self.compras

        class Sesion:
            def request(self, metodo, url, **kwargs):
                return cliente.request(
                    metodo,
                    url.removeprefix(menu_api.URL_API_LOCAL),
                    auth=auth,
                    json=kwargs.get("json"),
                )

            def get(self, url, **kwargs):
                return self.request("GET", url, **kwargs)

        with TemporaryDirectory() as temporal:
            archivo = str(Path(temporal) / "menu_api.py")
            with patch.object(menu_api, "__file__", archivo), patch(
                "builtins.input",
                side_effect=["2", "12", "1", "1", "2", "0", "0", "0", "0"],
            ), redirect_stdout(io.StringIO()) as salida:
                menu_api.ejecutar_menu(Sesion(), "compras")
            self.assertIn(f"Venta {pedido}", salida.getvalue())
            self.assertIn("2 x Mouse", salida.getvalue())
            html = (Path(temporal) / "tickets" / f"venta-{pedido}.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("$ 17.000,00", html)
