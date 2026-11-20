"""Regression tests: portfolio release."""

import ast
import json
import re
import time
from pathlib import Path
from unittest import TestCase
import test_regresion
from demo_setup import create_demo_accounts
from usuarios import consultar_usuario
from repositorio_sqlite import conectar_db


class PortfolioRelease(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def test_receipt_languages_preserve_order_and_product_data(self):
        name = "Confirmar <script>alert(1)</script>"
        product = self.solicitar(
            "POST",
            "/productos",
            201,
            json={
                "nombre": name,
                "marca": "Demo",
                "categoria": "tecnologia",
                "precio": 1000,
                "stock": 2,
            },
        )
        sale = self.solicitar(
            "PUT",
            "/ventas/portfolio-sale",
            auth=self.consulta,
            json={"producto_id": product["id"], "cantidad": 1},
        )["pedido_venta_id"]
        before = self.solicitar("GET", "/productos/" + str(product["id"]))
        for language, heading in [
            ("es", "Ticket de demostración"),
            ("en", "Demonstration receipt"),
        ]:
            response = self.cliente.get(
                f"/pedidos-venta/{sale}/ticket?idioma={language}", auth=self.compras
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(f'lang="{language}"', response.text)
            self.assertIn(heading, response.text)
            self.assertIn("Confirmar &lt;script&gt;", response.text)
            self.assertNotIn("<script>alert", response.text)
            if language == "en":
                self.assertIn("ARS 1,000.00", response.text)
                self.assertIn("Not a tax invoice", response.text)
                self.assertIn("Approved", response.text)
        self.assertEqual(
            before, self.solicitar("GET", "/productos/" + str(product["id"]))
        )
        self.assertEqual(
            self.cliente.get(
                f"/pedidos-venta/{sale}/ticket?idioma=fr", auth=self.compras
            ).status_code,
            422,
        )

    def test_receipt_language_parameter_does_not_bypass_ownership(self):
        create_demo_accounts("PublicDemoTest123", conectar_db)
        customer = ("demo_customer", "PublicDemoTest123")
        sale = self.solicitar(
            "PUT",
            "/ventas/private-receipt",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 1},
        )["pedido_venta_id"]
        response = self.cliente.get(
            f"/pedidos-venta/{sale}/ticket?idioma=en", auth=customer
        )
        self.assertEqual(response.status_code, 404)

    def test_bootstrap_is_idempotent_and_does_not_reset_passwords(self):
        created = create_demo_accounts("PublicDemoTest123", conectar_db)
        self.assertEqual(len(created), 4)
        before = consultar_usuario(conectar_db, "demo_admin")
        self.assertEqual(create_demo_accounts("DifferentPassword123", conectar_db), [])
        self.assertEqual(before, consultar_usuario(conectar_db, "demo_admin"))
        self.solicitar("GET", "/sesion", auth=("demo_admin", "PublicDemoTest123"))
        self.solicitar(
            "GET", "/sesion", 401, auth=("demo_admin", "DifferentPassword123")
        )

    def test_public_web_assets_include_translation_module(self):
        response = self.cliente.get("/interfaz/i18n.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["cache-control"])
        page = self.cliente.get("/interfaz/").text
        self.assertLess(page.index("i18n.js"), page.index("app.js"))
        self.assertIn('id="ui-language"', page)

    def test_literal_domain_errors_have_english_translations(self):
        base = Path(__file__).parent
        catalog = json.loads((base / "interfaz/messages.json").read_text())
        missing = []
        for file in base.glob("*.py"):
            if file.name.startswith(("test_", "prueba_")):
                continue
            for node in ast.walk(ast.parse(file.read_text())):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                    values = [
                        *node.exc.args,
                        *[kw.value for kw in node.exc.keywords if kw.arg == "detail"],
                    ]
                    for value in values:
                        if (
                            isinstance(value, ast.Constant)
                            and isinstance(value.value, str)
                            and value.value not in catalog
                        ):
                            missing.append((file.name, value.value))
        self.assertEqual(missing, [])

    def test_payment_worker_recovers_without_an_open_page(self):
        self.solicitar(
            "PUT",
            "/cobros-demo/worker-payment",
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 1}]},
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/worker-payment/eventos/approved",
            auth=self.consulta,
            json={"estado": "aprobado"},
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.solicitar("GET", "/productos/1")["stock"] == 6:
                break
            time.sleep(0.05)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            self.solicitar("GET", "/cobros-demo/worker-payment", auth=self.consulta)[
                "estado"
            ],
            "aprobado",
        )
